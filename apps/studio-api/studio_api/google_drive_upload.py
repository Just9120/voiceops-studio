from __future__ import annotations

import json
import re
import hashlib
import time
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse

import httpx


DRIVE_RESUMABLE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
DRIVE_UPLOAD_FIELDS = "id,name,mimeType,size,webViewLink,parents,appProperties,sha256Checksum,headRevisionId"
DRIVE_UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"


class GoogleDriveUploadReason(str, Enum):
    authentication_rejected = "authentication_rejected"
    unavailable = "unavailable"
    malformed_response = "malformed_response"
    content_mismatch = "content_mismatch"


class GoogleDriveUploadError(RuntimeError):
    def __init__(self, reason: GoogleDriveUploadReason):
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True)
class GoogleDriveUploadResult:
    file_id: str
    web_view_url: str
    name: str
    sha256_checksum: str | None = None
    head_revision_id: str | None = None


def upload_file_resumable(
    access_token: str,
    *,
    folder_id: str,
    path: Path,
    filename: str,
    mime_type: str,
    idempotency_key: str,
    client_factory=httpx.Client,
    check_cancelled=None,
    progress_callback=None,
    app_property_key="studioAudioPreparationJobId",
) -> GoogleDriveUploadResult:
    size = path.stat().st_size
    if size <= 0:
        raise GoogleDriveUploadError(GoogleDriveUploadReason.malformed_response)
    expected_sha256 = _file_sha256(path, size=size, check=check_cancelled)
    metadata = {
        "name": filename,
        "parents": [folder_id],
        "appProperties": {app_property_key: idempotency_key},
    }
    params = urlencode(
        {
            "uploadType": "resumable",
            "supportsAllDrives": "true",
            "fields": DRIVE_UPLOAD_FIELDS,
        }
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": mime_type,
        "X-Upload-Content-Length": str(size),
    }
    try:
        with client_factory(timeout=httpx.Timeout(60.0), follow_redirects=False) as client:
            if check_cancelled:
                check_cancelled()
            existing = _find_existing_upload(
                client,
                access_token=access_token,
                folder_id=folder_id,
                idempotency_key=idempotency_key,
                expected_size=size,
                expected_sha256=expected_sha256,
                check_cancelled=check_cancelled,
                app_property_key=app_property_key,
            )
            if existing is not None:
                return existing
            start = client.post(
                f"{DRIVE_RESUMABLE_UPLOAD_URL}?{params}",
                headers=headers,
                content=json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
            )
            _raise_status(start)
            location = start.headers.get("Location")
            if not _safe_upload_location(location):
                raise GoogleDriveUploadError(GoogleDriveUploadReason.malformed_response)
            with path.open("rb") as stream:
                offset = 0
                interruptions = 0
                stalled = 0
                while offset < size:
                    if check_cancelled:
                        check_cancelled()
                    stream.seek(offset)
                    chunk = stream.read(min(DRIVE_UPLOAD_CHUNK_SIZE, size - offset))
                    if not chunk:
                        raise GoogleDriveUploadError(GoogleDriveUploadReason.malformed_response)
                    end = offset + len(chunk)
                    try:
                        result = client.put(location, headers={
                            "Authorization": f"Bearer {access_token}",
                            "Content-Type": mime_type,
                            "Content-Length": str(len(chunk)),
                            "Content-Range": f"bytes {offset}-{end - 1}/{size}",
                        }, content=chunk)
                    except httpx.HTTPError:
                        result = None
                    if result is None or result.status_code >= 500:
                        interruptions += 1
                        if interruptions > 3:
                            raise GoogleDriveUploadError(GoogleDriveUploadReason.unavailable)
                        if check_cancelled:
                            check_cancelled()
                        # The last chunk may have arrived even if its response
                        # was lost. Query the same session before sending bytes.
                        result = client.put(location, headers={
                            "Authorization": f"Bearer {access_token}",
                            "Content-Length": "0", "Content-Range": f"bytes */{size}",
                        }, content=b"")
                    if result.status_code in {200, 201}:
                        # Preserve confirmed success even if cancellation was
                        # requested while the final request was in flight.
                        # Read-only confirmation continues after a final ACK even
                        # when cancellation arrived while that request was in flight.
                        return _verified_result(client, result.json(), access_token=access_token,
                            expected_parent=folder_id, expected_size=size, expected_sha256=expected_sha256)
                    if result.status_code != 308:
                        _raise_status(result)
                        raise GoogleDriveUploadError(GoogleDriveUploadReason.malformed_response)
                    received = _received_offset(result.headers.get("Range"), size=size)
                    if received < offset or received > end:
                        raise GoogleDriveUploadError(GoogleDriveUploadReason.malformed_response)
                    stalled = stalled + 1 if received == offset else 0
                    if stalled >= 3:
                        raise GoogleDriveUploadError(GoogleDriveUploadReason.unavailable)
                    offset = received
                    if progress_callback and offset:
                        progress_callback(offset, size)
                raise GoogleDriveUploadError(GoogleDriveUploadReason.malformed_response)
    except GoogleDriveUploadError:
        raise
    except (OSError, httpx.HTTPError, json.JSONDecodeError) as exc:
        raise GoogleDriveUploadError(GoogleDriveUploadReason.unavailable) from exc


def _find_existing_upload(client, *, access_token: str, folder_id: str, idempotency_key: str, expected_size: int,
                          expected_sha256: str, check_cancelled=None, app_property_key="studioAudioPreparationJobId") -> GoogleDriveUploadResult | None:
    if not _safe_drive_identifier(folder_id) or not _safe_drive_identifier(idempotency_key) or app_property_key not in {"studioAudioPreparationJobId", "studioManifestSnapshot"}:
        raise GoogleDriveUploadError(GoogleDriveUploadReason.malformed_response)
    query = (
        f"'{folder_id}' in parents and trashed = false and "
        f"appProperties has {{ key='{app_property_key}' and value='{idempotency_key}' }}"
    )
    response = client.get(
        DRIVE_FILES_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "q": query,
            "spaces": "drive",
            "pageSize": "2",
            "fields": f"files({DRIVE_UPLOAD_FIELDS}),nextPageToken",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        },
    )
    _raise_status(response)
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise GoogleDriveUploadError(GoogleDriveUploadReason.malformed_response) from exc
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list) or len(files) > 1 or payload.get("nextPageToken"):
        raise GoogleDriveUploadError(GoogleDriveUploadReason.malformed_response)
    return _verified_result(client, files[0], access_token=access_token, expected_parent=folder_id,
        expected_size=expected_size, expected_sha256=expected_sha256, check_cancelled=check_cancelled) if files else None


def _file_sha256(path, *, size, check):
    digest = hashlib.sha256()
    read = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            if check: check()
            read += len(chunk)
            if read > size:
                raise GoogleDriveUploadError(GoogleDriveUploadReason.content_mismatch)
            digest.update(chunk)
    if read != size:
        raise GoogleDriveUploadError(GoogleDriveUploadReason.content_mismatch)
    return digest.hexdigest()


def _verified_result(client, payload, *, access_token, expected_parent, expected_size, expected_sha256, check_cancelled=None):
    result = _normalize_result(payload, expected_parent=expected_parent, expected_size=expected_size)
    if result.sha256_checksum is not None:
        if result.sha256_checksum != expected_sha256:
            raise GoogleDriveUploadError(GoogleDriveUploadReason.content_mismatch)
        return result
    # Binary Drive files normally expose SHA256. Where unavailable, verify the
    # actual bounded content, preferably its captured immutable revision.
    path = f"{DRIVE_FILES_URL}/{quote(result.file_id, safe='')}"
    params = {"alt": "media", "supportsAllDrives": "true"}
    if result.head_revision_id:
        path += f"/revisions/{quote(result.head_revision_id, safe='')}"
        params.pop("supportsAllDrives")
    digest = hashlib.sha256()
    received = 0
    deadline = time.monotonic() + 1800
    with client.stream("GET", path, headers={"Authorization": f"Bearer {access_token}"}, params=params) as response:
        _raise_status(response)
        for chunk in response.iter_bytes(1024 * 1024):
            if check_cancelled: check_cancelled()
            if time.monotonic() > deadline:
                raise GoogleDriveUploadError(GoogleDriveUploadReason.unavailable)
            from .worker_progress import touch_worker_progress
            touch_worker_progress()
            received += len(chunk)
            if received > expected_size:
                raise GoogleDriveUploadError(GoogleDriveUploadReason.content_mismatch)
            digest.update(chunk)
    if received != expected_size or digest.hexdigest() != expected_sha256:
        raise GoogleDriveUploadError(GoogleDriveUploadReason.content_mismatch)
    return replace(result, sha256_checksum=expected_sha256)


def _safe_drive_identifier(value: str) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value) is not None


def _received_offset(value: str | None, *, size: int) -> int:
    if value is None:
        return 0
    match = re.fullmatch(r"bytes=0-(\d+)", value)
    if match is None:
        raise GoogleDriveUploadError(GoogleDriveUploadReason.malformed_response)
    offset = int(match.group(1)) + 1
    if offset >= size:
        raise GoogleDriveUploadError(GoogleDriveUploadReason.malformed_response)
    return offset


def _raise_status(response) -> None:
    if response.status_code in {401, 403}:
        raise GoogleDriveUploadError(GoogleDriveUploadReason.authentication_rejected)
    if response.status_code < 200 or response.status_code >= 300:
        raise GoogleDriveUploadError(GoogleDriveUploadReason.unavailable)


def _safe_upload_location(value: str | None) -> bool:
    if not isinstance(value, str) or len(value) > 4096:
        return False
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "www.googleapis.com"
        and parsed.path == "/upload/drive/v3/files"
        and "upload_id=" in parsed.query
        and parsed.username is None
        and parsed.password is None
        and parsed.port is None
    )


def _normalize_result(payload, *, expected_parent: str | None = None, expected_size: int) -> GoogleDriveUploadResult:
    if not isinstance(payload, dict):
        raise GoogleDriveUploadError(GoogleDriveUploadReason.malformed_response)
    file_id = payload.get("id")
    web_view_url = payload.get("webViewLink")
    name = payload.get("name")
    parents = payload.get("parents")
    sha256 = payload.get("sha256Checksum")
    revision = payload.get("headRevisionId")
    if (
        not _safe_drive_identifier(file_id)
        or not isinstance(web_view_url, str)
        or not web_view_url.startswith("https://drive.google.com/")
        or len(web_view_url) > 2000
        or not isinstance(name, str)
        or not name
        or len(name) > 255
        or not isinstance(parents, list)
        or len(parents) != 1
        or not isinstance(parents[0], str)
        or (expected_parent is not None and parents[0] != expected_parent)
        or str(payload.get("size")) != str(expected_size)
        or (sha256 is not None and (not isinstance(sha256, str) or re.fullmatch(r"[a-fA-F0-9]{64}", sha256) is None))
        or (revision is not None and not _safe_drive_identifier(revision))
    ):
        raise GoogleDriveUploadError(GoogleDriveUploadReason.malformed_response)
    return GoogleDriveUploadResult(file_id=file_id, web_view_url=web_view_url, name=name,
        sha256_checksum=sha256.lower() if sha256 is not None else None, head_revision_id=revision)
