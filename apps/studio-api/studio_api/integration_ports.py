"""Capability boundaries. Implementations own external I/O, never owner policy.

Callers retain CSRF, same-origin, owner/lease checks and transaction boundaries.
FastAPI dependencies and explicit worker arguments can replace implementations.
No plugin import paths or caller-selected implementations are accepted from HTTP.
"""
from typing import Protocol


class AuthorizationProvider(Protocol):
    def resolve_session(self, db, *, token_hash: str, now): ...
    def authenticate(self, db, *, email: str, password: str): ...
    def verify_password(self, encoded: str, password: str) -> bool: ...
    def hash_password(self, password: str) -> str: ...


class CloudFilesProvider(Protocol):
    def access_token(self, db, *, user_id: str, settings) -> str: ...
    def metadata(self, token: str, resource_id: str, *, revision_id: str | None = None): ...
    def content(self, token: str, resource_id: str, *, revision_id: str | None = None): ...
    def folder_children(self, token: str, folder_id: str, **kwargs): ...


class TranscriptDocumentProvider(Protocol):
    def create_transcript_document(self, *, access_token: str, folder_id: str,
        title: str, document_text: str, reconciliation_token: str | None = None): ...


def get_authorization_provider() -> AuthorizationProvider:
    from .local_authorization import LocalAuthorizationProvider
    return LocalAuthorizationProvider()


def get_cloud_files_provider() -> CloudFilesProvider:
    from .google_integration import GoogleFilesProvider
    return GoogleFilesProvider()


def get_document_provider() -> TranscriptDocumentProvider:
    from .google_docs_output import GoogleDocsTranscriptTransport
    return GoogleDocsTranscriptTransport()
