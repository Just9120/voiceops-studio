import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/studio-api"))
os.environ.setdefault("STUDIO_DATABASE_URL", "sqlite+pysqlite:///:memory:")
from studio_api.deps import current_session, require_csrf
from studio_api.config import get_settings
from studio_api.db import get_db
from studio_api.integration_ports import get_authorization_provider
from studio_api.security import token_hash


def test_alternative_authorization_preserves_owner_csrf_and_same_origin():
    now = datetime.now(timezone.utc)
    session = SimpleNamespace(id="synthetic", csrf_hash=token_hash("csrf"), last_seen_at=now,
        expires_at=now + timedelta(minutes=10))
    user = SimpleNamespace(id="owner")
    calls = []
    class AlternativeAuthorization:
        def resolve_session(self, db, *, token_hash, now):
            calls.append(token_hash)
            return (session, user) if token_hash == globals()["token_hash"]("synthetic-cookie") else None
    app = FastAPI()
    @app.get("/owner")
    def owner(pair=Depends(current_session)): return {"owner": pair[1].id}
    @app.post("/mutation")
    def mutation(pair=Depends(require_csrf)): return {"owner": pair[1].id}
    app.dependency_overrides[get_authorization_provider] = AlternativeAuthorization
    app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    app.dependency_overrides[get_settings] = lambda: SimpleNamespace(cookie_name="test-session",
        app_origin="https://studio.example.test", session_last_seen_write_interval_seconds=300)
    with TestClient(app) as client:
        assert client.get("/owner").status_code == 401
        client.cookies.set("test-session", "synthetic-cookie")
        assert client.get("/owner").json() == {"owner": "owner"}
        assert client.post("/mutation", headers={"Origin": "https://studio.example.test"}).status_code == 403
        assert client.post("/mutation", headers={"Origin": "https://attacker.example.test", "X-CSRF-Token": "csrf"}).status_code == 403
        assert client.post("/mutation", headers={"Origin": "https://studio.example.test", "X-CSRF-Token": "csrf"}).json() == {"owner": "owner"}
    assert calls and all(value == token_hash("synthetic-cookie") for value in calls)


def test_alternative_cloud_boundary_uses_authenticated_owner_and_safe_projection(monkeypatch):
    from studio_api import main
    calls = []
    class AlternativeFiles:
        def access_token(self, db, *, user_id, settings):
            calls.append(("owner", user_id)); return "synthetic-memory-token"
        def metadata(self, token, resource_id):
            assert token == "synthetic-memory-token"
            calls.append(("metadata", resource_id))
            return SimpleNamespace(id=resource_id, name="Synthetic.wav", mime_type="audio/wav", size_bytes=42,
                web_view_link=None, created_time=None, modified_time=None, is_folder=False)
    monkeypatch.setattr(main, "get_cloud_files_provider", AlternativeFiles)
    monkeypatch.setattr(main.limiter, "check", lambda *args: None)
    main.app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    try:
        with TestClient(main.app) as client:
            assert client.get("/api/google/drive/files/synthetic/metadata").status_code == 401
            main.app.dependency_overrides[current_session] = lambda: (SimpleNamespace(), SimpleNamespace(id="synthetic-owner"))
            response = client.get("/api/google/drive/files/synthetic/metadata")
            assert response.status_code == 200
            assert response.json()["name"] == "Synthetic.wav"
            assert "token" not in response.text and calls == [("owner", "synthetic-owner"), ("metadata", "synthetic")]
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        main.app.dependency_overrides.pop(current_session, None)


@pytest.mark.parametrize("outcome", ["revoked", "timeout", "refused"])
def test_google_revocation_uses_form_data_and_reports_safe_outcome(monkeypatch, outcome):
    from studio_api import google_connection_access as access

    connection = SimpleNamespace(
        user_id="owner", id="connection", refresh_token_ciphertext=b"primary",
        refresh_token_nonce=b"nonce", maintenance_refresh_token_ciphertext=b"maintenance",
        maintenance_refresh_token_nonce=b"nonce",
    )
    seen = []
    real_client = httpx.Client
    monkeypatch.setattr(access, "master_key_from_b64", lambda value: b"key")
    monkeypatch.setattr(access, "decrypt", lambda data, nonce, key, aad: data.decode())

    def post(request):
        assert request.method == "POST"
        assert str(request.url) == "https://oauth2.googleapis.com/revoke"
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        seen.append(request.content)
        if outcome == "timeout":
            raise httpx.ReadTimeout("synthetic")
        if outcome == "refused":
            return httpx.Response(400, json={"error": "invalid_request"})
        if request.content == b"token=maintenance":
            return httpx.Response(400, json={"error": "invalid_token"})
        return httpx.Response(200)

    monkeypatch.setattr(
        access.httpx, "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(post), **kwargs),
    )
    status = access.revoke_google_connection_grants(connection, settings=SimpleNamespace(master_key_b64=lambda: ""))
    assert status == ("confirmed" if outcome == "revoked" else "unconfirmed")
    assert set(seen) == {b"token=primary", b"token=maintenance"}


def test_independent_document_boundary_preserves_creation_arguments(monkeypatch):
    from studio_api import integration_ports, google_docs_output, job_google_docs_output
    received = []
    class AlternativeDocuments:
        def create_transcript_document(self, **kwargs):
            received.append(kwargs); return SimpleNamespace(id="synthetic-document")
    monkeypatch.setattr(google_docs_output, "GoogleDocsTranscriptTransport", AlternativeDocuments)
    provider = integration_ports.get_document_provider()
    # The real worker dispatch boundary accepts this implementation; ownership
    # and lease checks still occur in its caller before handing over content.
    kwargs = dict(access_token="synthetic-token", folder_id="synthetic-folder", title="Synthetic", document_text="Synthetic text", reconciliation_token="synthetic-case")
    result = job_google_docs_output._call_transport(provider, **kwargs)
    assert result.id == "synthetic-document" and received == [kwargs]
