import base64
import io
import os
import secrets
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/studio-api"))
os.environ.setdefault("STUDIO_DATABASE_SCHEME", "postgresql+psycopg")
os.environ.setdefault("STUDIO_DATABASE_HOST", "127.0.0.1")
os.environ.setdefault("STUDIO_DATABASE_PORT", "5432")
os.environ.setdefault("STUDIO_DATABASE_NAME", "studio_test")
os.environ.setdefault("STUDIO_DATABASE_USER", "studio_test")
os.environ.setdefault("STUDIO_POSTGRES_PASSWORD_FILE", str(Path(tempfile.gettempdir()) / "studio_test_pg_password"))
os.environ.setdefault("STUDIO_REDIS_URL", "redis://127.0.0.1:6379/0")
os.environ.setdefault("STUDIO_APP_ORIGIN", "https://studio.test")
os.environ.setdefault("STUDIO_COOKIE_SECURE", "false")
os.environ.setdefault("STUDIO_CREDENTIAL_MASTER_KEY_FILE", str(Path(tempfile.gettempdir()) / "studio_test_master_key"))


def _write_fixture_secret_if_missing(path_value: str, value: str) -> None:
    path = Path(path_value)
    if not path.exists():
        path.write_text(value, encoding="utf-8")


_write_fixture_secret_if_missing(
    os.environ["STUDIO_POSTGRES_PASSWORD_FILE"],
    os.environ.get("STUDIO_TEST_POSTGRES_PASSWORD", "studio_test_password"),
)
_write_fixture_secret_if_missing(
    os.environ["STUDIO_CREDENTIAL_MASTER_KEY_FILE"],
    base64.b64encode(secrets.token_bytes(32)).decode(),
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

import studio_api.main as studio_main
from studio_api.db import SessionLocal, engine
from studio_api.elevenlabs_transcription import normalize_elevenlabs_transcript_response
from studio_api.google_docs_output import GOOGLE_DOC_MIME_TYPE, GoogleDocsCreateResult
from studio_api.google_drive import GOOGLE_FOLDER_MIME_TYPE
from studio_api.job_elevenlabs_transcription import transcribe_processing_job_source_with_elevenlabs
from studio_api.job_google_docs_output import create_processing_job_google_doc_from_transcript
from studio_api.job_output_destination import DriveFolderAuthorizationMetadata
from studio_api.job_output_folder_selection import VerifiedOutputFolderSelection
from studio_api.job_processing_orchestrator import orchestrate_processing_job
from studio_api.job_processing_runner import claim_next_and_orchestrate_processing_job
from studio_api.media_preparation import PreparedMediaInput
from studio_api.models import (
    JobStatus,
    LocalIdentity,
    OutputReconciliationStatus,
    SourceAttemptRetryDisposition,
    TranscriptionJob,
    TranscriptionJobOutput,
    TranscriptionJobSourceAttempt,
    TranscriptionOutputReconciliation,
    User,
    UserRole,
    UserStatus,
)
from studio_api.security import hash_password, utcnow
from studio_api.source_storage import ObjectHead, SourceObjectStream


ALEMBIC = ROOT / "apps/studio-api/alembic.ini"
ORIGIN = "https://studio.test"
SAFE_OUTPUT_KEYS = {
    "source_id",
    "source_position",
    "source_name",
    "source_type",
    "output_kind",
    "transcript_standard",
    "web_view_url",
    "link_available",
    "document_character_count",
    "document_created_at",
    "persisted_at",
}
DATABASE_TABLES = [
    "transcription_job_source_attempts",
    "transcription_output_reconciliations",
    "diagnostic_debug_sessions",
    "diagnostic_events",
    "audit_events",
    "google_oauth_states",
    "google_connections",
    "provider_credential_versions",
    "provider_credentials",
    "transcription_job_outputs",
    "transcription_job_sources",
    "transcription_jobs",
    "sources",
    "projects",
    "sessions",
    "login_contexts",
    "local_identities",
    "users",
]


class FakeSourceStorage:
    def __init__(self):
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.last_presigned_key: str | None = None

    def presigned_put_url(self, key: str, content_type: str, expires_seconds: int, size_bytes: int) -> str:
        assert 60 <= expires_seconds <= 900
        self.last_presigned_key = key
        return f"https://uploads.test/{uuid.uuid4().hex}"

    def put(self, key: str, body: bytes, content_type: str) -> None:
        self.objects[key] = (body, content_type)

    def head_object(self, key: str) -> ObjectHead:
        if key not in self.objects:
            raise FileNotFoundError(key)
        body, content_type = self.objects[key]
        return ObjectHead(size_bytes=len(body), content_type=content_type)

    def open_read(self, key: str) -> SourceObjectStream:
        if key not in self.objects:
            raise FileNotFoundError(key)
        body, content_type = self.objects[key]
        return SourceObjectStream(io.BytesIO(body), content_type, len(body))


@contextmanager
def passthrough_test_media(**kwargs):
    yield PreparedMediaInput(
        filename=kwargs["original_filename"],
        mime_type=kwargs["mime_type"],
        byte_count=kwargs["byte_count"],
        stream=kwargs["stream"],
        duration_seconds=1.0,
        source_duration_seconds=1.0,
    )


@pytest.fixture(scope="module", autouse=True)
def platform_services():
    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    except OperationalError:
        if os.environ.get("CI", "").lower() == "true":
            pytest.fail("PostgreSQL is required for the processing E2E in CI")
        pytest.skip("PostgreSQL unavailable for the processing E2E")
    try:
        studio_main.limiter.redis.ping()
    except Exception:
        if os.environ.get("CI", "").lower() == "true":
            pytest.fail("Redis is required for the processing E2E in CI")
        pytest.skip("Redis unavailable for the processing E2E")
    migration_env = os.environ.copy()
    # Other collected test modules intentionally exercise SQLite through the
    # direct URL override. The processing E2E must always migrate PostgreSQL;
    # preserve an explicit PostgreSQL URL when the operator supplied one.
    direct_database_url = migration_env.get("STUDIO_DATABASE_URL", "").strip().lower()
    if direct_database_url.startswith("sqlite"):
        migration_env.pop("STUDIO_DATABASE_URL", None)
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC), "upgrade", "head"],
        cwd=ROOT,
        check=True,
        env=migration_env,
    )
    yield


@pytest.fixture(autouse=True)
def clean_platform_state(platform_services):
    studio_main.limiter.redis.flushdb()
    with engine.begin() as connection:
        missing = set(DATABASE_TABLES) - set(inspect(connection).get_table_names())
        assert not missing, f"shared test database schema is not at current head: {sorted(missing)}"
        connection.execute(text("TRUNCATE " + ", ".join(DATABASE_TABLES) + " RESTART IDENTITY CASCADE"))
    yield


def _create_admin(password: str) -> None:
    with SessionLocal() as db:
        user = User(email="processing-e2e@example.com", role=UserRole.admin, status=UserStatus.active)
        db.add(user)
        db.flush()
        db.add(LocalIdentity(user_id=user.id, password_hash=hash_password(password)))
        db.commit()


def _login(client: TestClient, password: str) -> str:
    context = client.post("/api/auth/login-context", headers={"Origin": ORIGIN})
    assert context.status_code == 200
    response = client.post(
        "/api/auth/login",
        json={
            "email": "processing-e2e@example.com",
            "password": password,
            "login_csrf_token": context.json()["login_csrf_token"],
        },
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_api_created_job_completes_through_worker_and_public_output_api(monkeypatch):
    password = secrets.token_urlsafe(24)
    provider_secret = secrets.token_urlsafe(32)
    google_access_token = secrets.token_urlsafe(32)
    source_bytes = secrets.token_bytes(32)
    folder_id = f"folder-{uuid.uuid4().hex}"
    document_id = uuid.uuid4().hex
    document_url = f"https://docs.google.com/document/d/{document_id}/edit"
    storage = FakeSourceStorage()
    calls = {"provider": 0, "google": 0}

    folder_metadata = DriveFolderAuthorizationMetadata(
        id=folder_id,
        mime_type=GOOGLE_FOLDER_MIME_TYPE,
        trashed=False,
        can_add_children=True,
        name="E2E output",
        web_view_link=f"https://drive.google.com/drive/folders/{folder_id}",
    )

    monkeypatch.setattr(studio_main.settings, "source_s3_endpoint_url", "https://storage.test")
    monkeypatch.setattr(studio_main.settings, "source_s3_bucket", "studio-e2e")
    monkeypatch.setattr(studio_main.settings, "source_s3_access_key_id_file", "transcription-id-for-test")
    monkeypatch.setattr(studio_main.settings, "source_s3_secret_access_key_file", "transcription-secret-for-test")
    monkeypatch.setattr(studio_main.settings, "source_s3_lifecycle_rule_id", "transcription-reference-retention")
    monkeypatch.setattr(studio_main.settings, "audio_reference_s3_endpoint_url", "https://storage.test")
    monkeypatch.setattr(studio_main.settings, "audio_reference_s3_region", "auto")
    monkeypatch.setattr(studio_main.settings, "audio_reference_s3_bucket", "studio-e2e-audio")
    monkeypatch.setattr(studio_main.settings, "audio_reference_s3_access_key_id_file", "audio-id-for-test")
    monkeypatch.setattr(studio_main.settings, "audio_reference_s3_secret_access_key_file", "audio-secret-for-test")
    monkeypatch.setattr(studio_main.settings, "audio_reference_s3_lifecycle_rule_id", "audio-reference-retention")
    monkeypatch.setattr(studio_main.settings, "source_max_upload_bytes", 1024 * 1024)
    monkeypatch.setattr(
        studio_main.settings,
        "elevenlabs_scribe_v2_rate_per_hour_usd",
        Decimal("0.22"),
    )
    monkeypatch.setattr(
        studio_main.settings,
        "elevenlabs_pricing_effective_date",
        date(2026, 8, 30),
    )
    monkeypatch.setattr(
        studio_main.settings,
        "elevenlabs_pricing_source",
        "elevenlabs_public_api_pricing",
    )
    monkeypatch.setattr(
        studio_main,
        "get_reference_storage",
        lambda settings, reference_class: storage,
    )
    monkeypatch.setattr(studio_main, "refreshed_google_drive_access_token", lambda db, user: google_access_token)

    def verify_selected_folder(token: str, selected_folder_id: str):
        assert token == google_access_token
        assert selected_folder_id == folder_id
        return VerifiedOutputFolderSelection(
            id=selected_folder_id,
            name=folder_metadata.name,
            web_view_url=folder_metadata.web_view_link,
            verified_at=utcnow(),
        )

    monkeypatch.setattr(studio_main, "verify_output_folder_selection", verify_selected_folder)

    def resolve_google_token(*args, **kwargs):
        return google_access_token

    def fetch_folder_metadata(token: str, selected_folder_id: str):
        assert token == google_access_token
        assert selected_folder_id == folder_id
        return folder_metadata

    def transcribe_with_fake_provider(**kwargs):
        calls["provider"] += 1
        assert kwargs["api_key"] == provider_secret
        assert kwargs["stream"].read() == source_bytes
        assert kwargs["mime_type"] == "audio/mpeg"
        return normalize_elevenlabs_transcript_response(
            {"text": "[redacted]", "language_code": "en", "words": []}
        )

    def create_with_fake_google(**kwargs):
        calls["google"] += 1
        assert kwargs["access_token"] == google_access_token
        assert kwargs["folder_id"] == folder_id
        assert "[redacted]" in kwargs["document_text"]
        assert kwargs["reconciliation_token"]
        return GoogleDocsCreateResult(
            document_id=document_id,
            name=kwargs["title"],
            mime_type=GOOGLE_DOC_MIME_TYPE,
            web_view_link=document_url,
            parents=(folder_id,),
        )

    def transcription_opener(db, **kwargs):
        @contextmanager
        def transaction_free_media(**media_kwargs):
            assert db.in_transaction() is False
            with passthrough_test_media(**media_kwargs) as prepared:
                yield prepared

        return transcribe_processing_job_source_with_elevenlabs(
            db,
            **kwargs,
            token_resolver=resolve_google_token,
            metadata_fetcher=fetch_folder_metadata,
            storage_factory=lambda settings: storage,
            media_preparer=transaction_free_media,
            elevenlabs_transport=transcribe_with_fake_provider,
        )

    def google_docs_opener(db, **kwargs):
        return create_processing_job_google_doc_from_transcript(
            db,
            **kwargs,
            token_resolver=resolve_google_token,
            metadata_fetcher=fetch_folder_metadata,
            google_docs_transport=create_with_fake_google,
        )

    def e2e_orchestrator(db, **kwargs):
        return orchestrate_processing_job(
            db,
            **kwargs,
            transcription_opener=transcription_opener,
            google_docs_opener=google_docs_opener,
        )

    _create_admin(password)
    with TestClient(studio_main.app) as client:
        csrf = _login(client, password)
        write_headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}

        project_response = client.post(
            "/api/projects",
            json={"title": "Processing E2E"},
            headers=write_headers,
        )
        assert project_response.status_code == 200
        project_id = project_response.json()["id"]

        credential_response = client.post(
            "/api/credentials",
            json={"provider": "elevenlabs", "label": "E2E provider", "raw_value": provider_secret},
            headers=write_headers,
        )
        assert credential_response.status_code == 200
        assert provider_secret not in credential_response.text
        credential_id = credential_response.json()["id"]

        upload_response = client.post(
            f"/api/projects/{project_id}/sources/local-upload/initiate",
            json={"original_filename": "processing-e2e.mp3", "mime_type": "audio/mpeg", "size_bytes": len(source_bytes), "reference_class": "transcription"},
            headers=write_headers,
        )
        assert upload_response.status_code == 200
        source_id = upload_response.json()["source_id"]
        assert storage.last_presigned_key
        storage.put(storage.last_presigned_key, source_bytes, "audio/mpeg")
        complete_response = client.post(
            f"/api/sources/{source_id}/local-upload/complete",
            headers=write_headers,
        )
        assert complete_response.status_code == 200

        folder_response = client.post(
            f"/api/projects/{project_id}/output-folder/google-picker",
            json={"folder_id": folder_id},
            headers=write_headers,
        )
        assert folder_response.status_code == 200

        create_response = client.post(
            f"/api/projects/{project_id}/jobs/batch",
            json={
                "provider_credential_id": credential_id,
                "items": [{"source_id": source_id, "output_folder_id": folder_id, "title": "E2E transcript"}],
            },
            headers={**write_headers, "Idempotency-Key": f"processing-e2e-{uuid.uuid4().hex}"},
        )
        assert create_response.status_code == 200
        assert create_response.json()["replayed"] is False
        job_id = create_response.json()["jobs"][0]["id"]

        with SessionLocal() as worker_db:
            result = claim_next_and_orchestrate_processing_job(
                worker_db,
                lease_owner_id=f"e2e-worker-{uuid.uuid4().hex}",
                lease_ttl=timedelta(minutes=10),
                settings=studio_main.settings,
                orchestrator=e2e_orchestrator,
                heartbeat_session_factory=None,
            )
        assert result is not None
        assert result.job_id == job_id
        assert result.final_job_status == JobStatus.completed
        assert result.completion_occurred is True
        assert result.required_source_count == 1
        assert result.persisted_output_count == 1
        assert calls == {"provider": 1, "google": 1}

        job_response = client.get(f"/api/jobs/{job_id}")
        assert job_response.status_code == 200
        assert job_response.json()["status"] == "completed"
        assert job_response.json()["attempt_count"] == 1

        output_response = client.get(f"/api/jobs/{job_id}/outputs")
        assert output_response.status_code == 200
        output_payload = output_response.json()
        assert output_payload["job_id"] == job_id
        assert output_payload["job_status"] == "completed"
        assert output_payload["output_count"] == 1
        assert set(output_payload["outputs"][0]) == SAFE_OUTPUT_KEYS
        assert output_payload["outputs"][0]["web_view_url"] == document_url
        assert output_payload["outputs"][0]["link_available"] is True
        assert not {
            "document_id",
            "output_drive_folder_id",
            "provider_credential_id",
            "lease_owner_id",
            "transcript",
        } & set(output_payload["outputs"][0])

    with SessionLocal() as db:
        assert db.get(TranscriptionJob, job_id).status == JobStatus.completed
        assert db.query(TranscriptionJobOutput).filter_by(job_id=job_id).count() == 1
        attempts = db.query(TranscriptionJobSourceAttempt).filter_by(job_id=job_id).all()
        assert len(attempts) == 1
        assert attempts[0].retry_disposition == SourceAttemptRetryDisposition.completed
        assert attempts[0].completed_at is not None
        reconciliation = db.query(TranscriptionOutputReconciliation).filter_by(job_id=job_id).one()
        assert reconciliation.status == OutputReconciliationStatus.resolved

        assert claim_next_and_orchestrate_processing_job(
            db,
            lease_owner_id=f"e2e-worker-{uuid.uuid4().hex}",
            lease_ttl=timedelta(minutes=10),
            settings=studio_main.settings,
            orchestrator=e2e_orchestrator,
            heartbeat_session_factory=None,
        ) is None
        assert db.query(TranscriptionJobOutput).filter_by(job_id=job_id).count() == 1
    assert calls == {"provider": 1, "google": 1}
