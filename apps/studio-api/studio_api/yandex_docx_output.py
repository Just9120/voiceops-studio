"""Create-only DOCX upload and content-verified recovery after a lost response.

Callers persist the receipt hashes, path and opaque reconciliation token before
calling ensure_document. Merely finding a file at that path is never success.
"""
from dataclasses import dataclass, field
import hashlib
import unicodedata

from .transcript_docx import DOCX_MIME_TYPE, render_transcript_docx
from .yandex_disk import DiskResource, YandexDiskError, normalize_disk_path


@dataclass(frozen=True)
class DocxUpload:
    path: str = field(repr=False)
    content: bytes = field(repr=False)
    sha256: str
    md5: str
    character_count: int

    @property
    def size_bytes(self):
        return len(self.content)


def prepare_document_upload(*, folder_path: str, title: str, document_text: str,
                            reconciliation_token: str) -> DocxUpload:
    folder = normalize_disk_path(folder_path)
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160:
        raise YandexDiskError("invalid_document_title")
    name = "".join("_" if char in "/\\" or unicodedata.category(char).startswith("C") else char
                   for char in unicodedata.normalize("NFC", title)).strip(" .")
    if not name:
        raise YandexDiskError("invalid_document_title")
    if not name.lower().endswith(".docx"):
        name += ".docx"
    path = normalize_disk_path(folder.rstrip("/") + "/" + name)
    content = render_transcript_docx(document_text, reconciliation_token=reconciliation_token)
    return DocxUpload(path, content, hashlib.sha256(content).hexdigest(),
                      hashlib.md5(content, usedforsecurity=False).hexdigest(), len(document_text))


class _HashSink:
    def __init__(self):
        self.digest = hashlib.sha256()

    def write(self, chunk):
        self.digest.update(chunk)
        return len(chunk)


def bind_document_receipt(case, upload: DocxUpload) -> None:
    """Bind once inside the caller's locked, owner-verified case transaction."""
    if case.expected_output_provider != "yandex_disk":
        raise YandexDiskError("receipt_scope_mismatch")
    values = {
        "expected_docx_path": upload.path,
        "expected_document_sha256": upload.sha256,
        "expected_document_md5": upload.md5,
        "expected_document_size_bytes": upload.size_bytes,
    }
    old = {key: getattr(case, key) for key in values}
    if any(value is not None for value in old.values()) and old != values:
        raise YandexDiskError("document_conflict")
    for key, value in values.items():
        setattr(case, key, value)


def verify_document(client, resource: DiskResource, *, path: str, size_bytes: int,
                    sha256: str, md5: str, check=lambda: None) -> None:
    if (resource.path != path or resource.is_folder or resource.size_bytes != size_bytes
            or resource.mime_type != DOCX_MIME_TYPE
            or (resource.md5 is not None and resource.md5 != md5)
            or (resource.sha256 is not None and resource.sha256 != sha256)):
        raise YandexDiskError("document_conflict")
    if resource.sha256 is None:
        # Older Disk metadata may expose only MD5. Download to a hash sink so a
        # modified file cannot be accepted on filename/size or weak hash alone.
        sink = _HashSink()
        client.download_to(resource, sink, maximum_bytes=size_bytes, check=check)
        if sink.digest.hexdigest() != sha256:
            raise YandexDiskError("document_conflict")
    check()


def ensure_document(client, upload: DocxUpload, *, check=lambda: None) -> DiskResource:
    check()
    try:
        resource = client.metadata(upload.path)
    except YandexDiskError as error:
        if error.reason != "not_found":
            raise
        check()
        try:
            resource = client.upload_new(upload.path, upload.content)
        except YandexDiskError as error:
            # Another retry may have completed the same create-only operation.
            # Readback still must prove the exact persisted receipt.
            if error.reason != "conflict":
                raise
            resource = client.metadata(upload.path)
    verify_document(client, resource, path=upload.path, size_bytes=upload.size_bytes,
                    sha256=upload.sha256, md5=upload.md5, check=check)
    return resource
