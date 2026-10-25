from __future__ import annotations

import io
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))


@pytest.fixture(autouse=True)
def runtime_test_environment(monkeypatch):
    monkeypatch.setenv("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("STUDIO_APP_ORIGIN", "https://studio.test")
    monkeypatch.setenv("STUDIO_COOKIE_SECURE", "false")


def identity(component: str = "worker", commit: str = "a" * 40):
    from studio_api.runtime_observability import RuntimeIdentity

    return RuntimeIdentity(component, "0.1.0", f"{component}-{commit}", commit)


def test_runtime_status_migration_is_single_additive_head():
    script = ScriptDirectory.from_config(Config(str(ROOT / "apps/studio-api/alembic.ini")))
    assert script.get_heads() == ["0043_yandex_disk"]
    revision = script.get_revision("0026_runtime_component_status")
    assert revision is not None
    assert revision.down_revision == "0025_audio_preparation"
    assert revision.module.release_safety == "additive"
    source = (ROOT / "apps/studio-api/alembic/versions/0026_runtime_component_status.py").read_text(encoding="utf-8")
    assert "create_index" not in source and "last_seen_at" in source


def test_runtime_identity_build_and_health_contracts_are_exact_and_component_scoped():
    api_docker = (ROOT / "apps/studio-api/Dockerfile").read_text(encoding="utf-8")
    web_docker = (ROOT / "apps/studio/Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "deploy/studio/compose.platform.yml").read_text(encoding="utf-8")
    deploy = (ROOT / "scripts/deploy_studio_platform_component.sh").read_text(encoding="utf-8")
    package = (ROOT / "apps/studio/package.json").read_text(encoding="utf-8")

    for dockerfile in (api_docker, web_docker):
        assert "ARG STUDIO_RELEASE_VERSION=unknown" in dockerfile
        assert "ARG STUDIO_COMMIT_SHA=unknown" in dockerfile
        assert "STUDIO_RUNTIME_COMMIT_SHA=${STUDIO_COMMIT_SHA}" in dockerfile
        assert "STUDIO_RUNTIME_BUILD_ID=${STUDIO_COMPONENT}-${STUDIO_COMMIT_SHA}" in dockerfile
    for component in ("web", "api", "worker"):
        assert f"STUDIO_COMPONENT: {component}" in compose
    assert compose.count("STUDIO_COMMIT_SHA: ${STUDIO_RELEASE_SHA:-unknown}") == 3
    assert "/api/readyz" in compose and '"--mode", "readiness"' in compose
    assert 'export STUDIO_RELEASE_SHA="$target_revision"' in deploy
    assert deploy.index('export STUDIO_RELEASE_SHA="$target_revision"') < deploy.index('compose build "$SERVICE"')
    assert 'HEALTH_URL="http://127.0.0.1:8182/api/readyz"' in deploy
    assert "node scripts/write-build-meta.mjs" in package


def database():
    from studio_api.db import Base
    import studio_api.models  # noqa: F401

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)()


def test_runtime_identity_and_web_metadata_fail_closed():
    from studio_api.runtime_observability import (
        coherent_release_version,
        load_web_runtime_identity,
        parse_runtime_identity,
        runtime_identity_payload,
    )

    valid = identity("web")
    assert parse_runtime_identity(valid.payload(), expected_component="web") == valid
    for candidate in (
        {**valid.payload(), "commit_sha": "short"},
        {**valid.payload(), "component": "api"},
        {**valid.payload(), "build_id": "unknown"},
        {**valid.payload(), "release_version": "https://unsafe.test"},
    ):
        assert parse_runtime_identity(candidate, expected_component="web") is None
    assert runtime_identity_payload(None) == {"status": "unavailable"}
    coherent = {
        "web": {"status": "available", **identity("web").payload()},
        "api": {"status": "available", **identity("api").payload()},
        "worker": {"status": "ready", **identity("worker").payload()},
    }
    assert coherent_release_version(coherent) == "0.1.0"
    assert coherent_release_version({**coherent, "worker": {**coherent["worker"], "release_version": "0.2.0"}}) == "unavailable"
    assert coherent_release_version({**coherent, "worker": {"status": "stale", **identity("worker").payload()}}) == "unavailable"

    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *args): self.close()

    raw = ('{"component":"web","release_version":"0.1.0","build_id":"web-' + "a" * 40 + '","commit_sha":"' + "a" * 40 + '"}').encode()
    assert load_web_runtime_identity(opener=lambda url, timeout: Response(raw)) == valid
    assert load_web_runtime_identity(opener=lambda url, timeout: Response(b"{")) is None
    assert load_web_runtime_identity(opener=lambda url, timeout: Response(b"x" * 4097)) is None


def test_worker_heartbeat_is_authoritative_and_stale_aware():
    from studio_api.runtime_observability import (
        load_worker_runtime_status,
        record_worker_runtime_heartbeat,
    )

    engine, db = database()
    now = datetime(2026, 8, 28, 7, 0, tzinfo=timezone.utc)
    try:
        assert load_worker_runtime_status(db, now=now, stale_after_seconds=120) == {"status": "absent"}
        record_worker_runtime_heartbeat(
            db,
            identity=identity(),
            instance_id="worker-instance-a",
            started_at=now,
            seen_at=now,
        )
        ready = load_worker_runtime_status(db, now=now + timedelta(seconds=30), stale_after_seconds=120)
        assert ready["status"] == "ready"
        assert ready["commit_sha"] == "a" * 40
        assert ready["heartbeat_age_seconds"] == 30
        assert load_worker_runtime_status(
            db,
            now=now + timedelta(seconds=30),
            stale_after_seconds=120,
            expected_instance_id="worker-instance-b",
        ) == {"status": "foreign"}
        stale = load_worker_runtime_status(db, now=now + timedelta(seconds=121), stale_after_seconds=120)
        assert stale["status"] == "stale"

        record_worker_runtime_heartbeat(
            db,
            identity=identity(commit="b" * 40),
            instance_id="worker-instance-b",
            started_at=now + timedelta(minutes=5),
            seen_at=now + timedelta(minutes=5),
        )
        replaced = load_worker_runtime_status(db, now=now + timedelta(minutes=5), stale_after_seconds=120)
        assert replaced["status"] == "ready" and replaced["commit_sha"] == "b" * 40
        assert replaced["started_at"].startswith("2026-08-28T07:05:00")
    finally:
        db.close()
        engine.dispose()


def test_worker_runtime_instance_id_is_process_incarnation_scoped(tmp_path):
    from studio_api.runtime_observability import current_worker_runtime_instance_id

    stat = tmp_path / "stat"
    stat.write_text("1 (python worker) S " + " ".join(["1"] * 18 + ["12345"] + ["0"] * 20), encoding="utf-8")
    first = current_worker_runtime_instance_id(pid1_stat_path=stat, hostname="container-a")
    second = current_worker_runtime_instance_id(pid1_stat_path=stat, hostname="container-a")
    assert first == second and first.startswith("worker-") and len(first) == 71
    assert current_worker_runtime_instance_id(pid1_stat_path=stat, hostname="container-b") != first


def test_bounded_queue_storage_and_provider_health_are_safe_and_read_only(tmp_path):
    from studio_api import models as m
    from studio_api.runtime_observability import (
        queue_runtime_status,
        source_storage_runtime_status,
        stt_provider_runtime_status,
    )

    engine, db = database()
    now = datetime(2026, 8, 28, 7, 0, tzinfo=timezone.utc)
    try:
        user = m.User(email="owner@example.com", role=m.UserRole.admin, status=m.UserStatus.active)
        db.add(user); db.flush()
        project = m.Project(owner_user_id=user.id, title="private")
        db.add(project); db.flush()
        db.add(m.TranscriptionJob(project_id=project.id, owner_user_id=user.id, status=m.JobStatus.queued, created_at=now - timedelta(seconds=45)))
        credential = m.ProviderCredential(user_id=user.id, provider=m.CredentialProvider.elevenlabs, label="private-label")
        db.add(credential); db.flush()
        version = m.ProviderCredentialVersion(
            credential_id=credential.id,
            version=1,
            ciphertext=b"ciphertext",
            nonce=b"nonce",
            key_id="v1",
            masked_value="masked",
            fingerprint="f" * 64,
        )
        db.add(version); db.flush(); credential.active_version_id = version.id; db.commit()

        queue = queue_runtime_status(db, now=now)
        assert queue == {"status": "ready", "queued": 1, "processing": 0, "oldest_queued_age_seconds": 45}
        provider = stt_provider_runtime_status(db, owner_user_id=user.id)
        assert provider == {"status": "configured", "configured_credentials": 1, "providers": ["elevenlabs"], "availability": "unknown", "probe": "not_run"}
        assert "private" not in str(queue) + str(provider)

        access = tmp_path / "access"; secret = tmp_path / "secret"
        access.write_text("access", encoding="utf-8"); secret.write_text("secret", encoding="utf-8")
        settings = SimpleNamespace(
            source_s3_endpoint_url="https://storage.invalid",
            source_s3_region="auto",
            source_s3_bucket="private-bucket",
            source_s3_access_key_id_file=str(access),
            source_s3_secret_access_key_file=str(secret),
            source_s3_lifecycle_rule_id="transcription-retention",
            audio_reference_s3_endpoint_url="https://storage.invalid",
            audio_reference_s3_region="auto",
            audio_reference_s3_bucket="private-audio-bucket",
            audio_reference_s3_access_key_id_file=str(tmp_path / "audio-access"),
            audio_reference_s3_secret_access_key_file=str(tmp_path / "audio-secret"),
            audio_reference_s3_lifecycle_rule_id="audio-retention",
        )
        calls = []
        client = SimpleNamespace(head_bucket=lambda **kwargs: calls.append(kwargs))
        assert source_storage_runtime_status(settings, client_factory=lambda: client) == {
            "status": "ready",
            "probe": "read_only_head",
            "boundaries": {
                "transcription": "ready",
                "audio_processing": "ready",
            },
        }
        assert calls == [
            {"Bucket": "private-bucket"},
            {"Bucket": "private-audio-bucket"},
        ]
    finally:
        db.close()
        engine.dispose()
