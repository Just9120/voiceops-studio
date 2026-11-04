import json
import re
from dataclasses import dataclass
from enum import Enum
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .google_oauth import GoogleOAuthConfig, TOKEN_URL

DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_SIZE_PATTERN = re.compile(r"^(0|[1-9][0-9]*)$")
GOOGLE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
SAFE_DRIVE_METADATA_FIELDS = "id,name,mimeType,size,webViewLink,createdTime,modifiedTime,headRevisionId,md5Checksum"
SAFE_DRIVE_CHILDREN_FIELDS = f"nextPageToken,files({SAFE_DRIVE_METADATA_FIELDS})"
DEFAULT_DRIVE_FOLDER_CHILDREN_PAGE_SIZE = 50
MAX_DRIVE_FOLDER_CHILDREN_PAGE_SIZE = 100


@dataclass(frozen=True)
class GoogleDriveMetadata:
    id: str
    name: str | None
    mime_type: str | None
    size_bytes: int | None
    web_view_link: str | None
    created_time: str | None
    modified_time: str | None
    is_folder: bool
    head_revision_id: str | None = None
    md5_checksum: str | None = None


class GoogleDriveMetadataReason(str, Enum):
    not_found = "not_found"
    unavailable = "unavailable"


class GoogleDriveMetadataError(RuntimeError):
    def __init__(self, reason: GoogleDriveMetadataReason):
        self.reason = reason
        super().__init__(reason.value)


class GoogleAccessTokenRefreshReason(str, Enum):
    authentication_rejected = "authentication_rejected"
    unavailable = "unavailable"
    malformed_response = "malformed_response"


class GoogleAccessTokenRefreshError(RuntimeError):
    def __init__(self, reason: GoogleAccessTokenRefreshReason):
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True)
class GoogleDriveFolderChildren:
    folder_id: str
    items: list[GoogleDriveMetadata]
    next_page_token: str | None


def refresh_access_token(config: GoogleOAuthConfig, refresh_token: str) -> str:
    form = urlencode({
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode()
    req = Request(TOKEN_URL, data=form, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urlopen(req, timeout=10) as resp:  # nosec - Google OAuth endpoint; tests monkeypatch urlopen/helper.
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        reason = (
            GoogleAccessTokenRefreshReason.authentication_rejected
            if exc.code in {400, 401}
            else GoogleAccessTokenRefreshReason.unavailable
        )
        raise GoogleAccessTokenRefreshError(reason) from exc
    except (URLError, OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GoogleAccessTokenRefreshError(
            GoogleAccessTokenRefreshReason.unavailable
        ) from exc
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise GoogleAccessTokenRefreshError(
            GoogleAccessTokenRefreshReason.malformed_response
        )
    return access_token


def fetch_drive_file_metadata(access_token: str, drive_file_id: str, *, revision_id: str | None = None) -> GoogleDriveMetadata:
    path = quote(drive_file_id, safe="")
    parameters = {"fields": SAFE_DRIVE_METADATA_FIELDS, "supportsAllDrives": "true"}
    if revision_id is not None:
        path += f"/revisions/{quote(revision_id, safe='')}"
        parameters = {"fields": "id,mimeType,size,md5Checksum,modifiedTime"}
    params = urlencode(parameters)
    req = Request(
        f"{DRIVE_FILES_URL}/{path}?{params}",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    try:
        with urlopen(req, timeout=10) as resp:  # nosec - Google Drive endpoint; tests monkeypatch urlopen/helper.
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            raise GoogleDriveMetadataError(GoogleDriveMetadataReason.not_found) from exc
        raise GoogleDriveMetadataError(GoogleDriveMetadataReason.unavailable) from exc
    except (URLError, OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GoogleDriveMetadataError(GoogleDriveMetadataReason.unavailable) from exc
    if not isinstance(payload, dict):
        raise GoogleDriveMetadataError(GoogleDriveMetadataReason.unavailable)
    if revision_id is not None:
        if payload.get("id") != revision_id:
            raise GoogleDriveMetadataError(GoogleDriveMetadataReason.unavailable)
        payload = {**payload, "id": drive_file_id, "headRevisionId": revision_id}
    return normalize_drive_file_metadata(payload)


def list_drive_folder_children(
    access_token: str,
    folder_id: str,
    page_size: int = DEFAULT_DRIVE_FOLDER_CHILDREN_PAGE_SIZE,
    page_token: str | None = None,
) -> GoogleDriveFolderChildren:
    safe_page_size = max(1, min(page_size, MAX_DRIVE_FOLDER_CHILDREN_PAGE_SIZE))
    params = {
        "q": f"'{folder_id}' in parents and trashed = false",
        "fields": SAFE_DRIVE_CHILDREN_FIELDS,
        "pageSize": str(safe_page_size),
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }
    if page_token:
        params["pageToken"] = page_token
    req = Request(
        f"{DRIVE_FILES_URL}?{urlencode(params)}",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    try:
        with urlopen(req, timeout=10) as resp:  # nosec - Google Drive endpoint; tests monkeypatch urlopen/helper.
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            raise GoogleDriveMetadataError(GoogleDriveMetadataReason.not_found) from exc
        raise GoogleDriveMetadataError(GoogleDriveMetadataReason.unavailable) from exc
    except (URLError, OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GoogleDriveMetadataError(GoogleDriveMetadataReason.unavailable) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
        raise GoogleDriveMetadataError(GoogleDriveMetadataReason.unavailable)
    files = payload["files"]
    token = payload.get("nextPageToken")
    if token is not None and (not isinstance(token, str) or not token):
        raise GoogleDriveMetadataError(GoogleDriveMetadataReason.unavailable)
    items=[]
    for item in files:
        if not isinstance(item, dict):
            raise GoogleDriveMetadataError(GoogleDriveMetadataReason.unavailable)
        items.append(normalize_drive_file_metadata(item))
    return GoogleDriveFolderChildren(
        folder_id=folder_id,
        items=items,
        next_page_token=token,
    )


def normalize_drive_metadata(payload: dict) -> GoogleDriveMetadata:
    mime_type = payload.get("mimeType")
    raw_size = payload.get("size")
    size_bytes = None
    if raw_size is not None:
        try:
            size_bytes = int(raw_size)
        except (TypeError, ValueError):
            size_bytes = None
    return GoogleDriveMetadata(
        id=str(payload.get("id") or ""),
        name=payload.get("name") if isinstance(payload.get("name"), str) else None,
        mime_type=mime_type if isinstance(mime_type, str) else None,
        size_bytes=size_bytes,
        web_view_link=payload.get("webViewLink") if isinstance(payload.get("webViewLink"), str) else None,
        created_time=payload.get("createdTime") if isinstance(payload.get("createdTime"), str) else None,
        modified_time=payload.get("modifiedTime") if isinstance(payload.get("modifiedTime"), str) else None,
        is_folder=mime_type == GOOGLE_FOLDER_MIME_TYPE,
        head_revision_id=_optional_revision_id(payload.get("headRevisionId")),
        md5_checksum=_optional_md5(payload.get("md5Checksum")),
    )


def _optional_revision_id(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value):
        raise GoogleDriveMetadataError(GoogleDriveMetadataReason.unavailable)
    return value


def _optional_md5(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", value):
        raise GoogleDriveMetadataError(GoogleDriveMetadataReason.unavailable)
    return value.lower()


def normalize_drive_file_metadata(payload: dict) -> GoogleDriveMetadata:
    file_id = payload.get("id")
    mime_type = payload.get("mimeType")
    if not isinstance(file_id, str) or not file_id.strip():
        raise GoogleDriveMetadataError(GoogleDriveMetadataReason.unavailable)
    if not isinstance(mime_type, str) or not mime_type.strip():
        raise GoogleDriveMetadataError(GoogleDriveMetadataReason.unavailable)
    if "size" in payload:
        _parse_strict_drive_size(payload.get("size"))
    return normalize_drive_metadata(payload)


def _parse_strict_drive_size(raw_size) -> int:
    if isinstance(raw_size, bool):
        raise GoogleDriveMetadataError(GoogleDriveMetadataReason.unavailable)
    if isinstance(raw_size, int):
        if raw_size < 0:
            raise GoogleDriveMetadataError(GoogleDriveMetadataReason.unavailable)
        return raw_size
    if isinstance(raw_size, str):
        if not DRIVE_SIZE_PATTERN.fullmatch(raw_size):
            raise GoogleDriveMetadataError(GoogleDriveMetadataReason.unavailable)
        return int(raw_size)
    raise GoogleDriveMetadataError(GoogleDriveMetadataReason.unavailable)

class GoogleDriveContentReason(str, Enum):
    not_found = "not_found"
    unavailable = "unavailable"


class GoogleDriveContentError(RuntimeError):
    def __init__(self, reason: GoogleDriveContentReason):
        self.reason = reason
        super().__init__(reason.value)


@dataclass
class GoogleDriveContentStream:
    response: object
    content_type: str | None
    content_length: int | None

    def iter_chunks(self, chunk_size: int):
        while True:
            chunk = self.response.read(chunk_size)
            if not chunk:
                break
            yield chunk

    def close(self) -> None:
        close = getattr(self.response, "close", None)
        if close:
            close()


def fetch_drive_file_content(access_token: str, drive_file_id: str, *, revision_id: str | None = None) -> GoogleDriveContentStream:
    # A missing/expired historical revision must not fall back to today's bytes.
    path = quote(drive_file_id, safe="")
    parameters = {"alt": "media"}
    if revision_id is not None:
        path += f"/revisions/{quote(revision_id, safe='')}"
    else:
        parameters["supportsAllDrives"] = "true"
    params = urlencode(parameters)
    req = Request(
        f"{DRIVE_FILES_URL}/{path}?{params}",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "*/*"},
    )
    try:
        resp = urlopen(req, timeout=30)  # nosec - Google Drive endpoint; tests monkeypatch helper.
    except HTTPError as exc:
        if exc.code == 404:
            raise GoogleDriveContentError(GoogleDriveContentReason.not_found) from exc
        raise GoogleDriveContentError(GoogleDriveContentReason.unavailable) from exc
    except (URLError, OSError) as exc:
        raise GoogleDriveContentError(GoogleDriveContentReason.unavailable) from exc
    return GoogleDriveContentStream(
        resp,
        resp.headers.get("Content-Type") if getattr(resp, "headers", None) is not None else None,
        _content_length(resp.headers.get("Content-Length") if getattr(resp, "headers", None) is not None else None),
    )


def _content_length(value) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None

RECONCILIATION_DRIVE_FIELDS = "nextPageToken,files(id,mimeType,webViewLink,parents,createdTime,appProperties)"

class GoogleDriveReconciliationReason(str, Enum):
    unavailable = "unavailable"
    malformed = "malformed"
    authentication_rejected = "authentication_rejected"

class GoogleDriveReconciliationError(RuntimeError):
    def __init__(self, reason: GoogleDriveReconciliationReason):
        self.reason = reason; super().__init__(reason.value)

def list_reconciliation_candidates(access_token: str, *, folder_id: str, app_property_key: str, token: str):
    from datetime import datetime, timezone
    from .job_output_reconciliation import DriveReconciliationCandidate
    escaped_key = app_property_key.replace("'", "\\'")
    escaped_token = token.replace("'", "\\'")
    q = f"'{folder_id}' in parents and appProperties has {{ key='{escaped_key}' and value='{escaped_token}' }} and trashed = false"
    params = {"q": q, "fields": RECONCILIATION_DRIVE_FIELDS, "pageSize": "10", "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
    req = Request(f"{DRIVE_FILES_URL}?{urlencode(params)}", headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"})
    try:
        with urlopen(req, timeout=10) as resp:  # nosec - Google Drive endpoint; tests monkeypatch.
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in {401,403}: raise GoogleDriveReconciliationError(GoogleDriveReconciliationReason.authentication_rejected) from exc
        raise GoogleDriveReconciliationError(GoogleDriveReconciliationReason.unavailable) from exc
    except (URLError, OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GoogleDriveReconciliationError(GoogleDriveReconciliationReason.unavailable) from exc
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list): raise GoogleDriveReconciliationError(GoogleDriveReconciliationReason.malformed)
    out=[]
    for item in files:
        if not isinstance(item, dict): raise GoogleDriveReconciliationError(GoogleDriveReconciliationReason.malformed)
        created=item.get("createdTime")
        try: created_dt=datetime.fromisoformat(created.replace("Z","+00:00")).astimezone(timezone.utc).replace(tzinfo=None) if isinstance(created,str) else datetime.now(timezone.utc).replace(tzinfo=None)
        except Exception: raise GoogleDriveReconciliationError(GoogleDriveReconciliationReason.malformed)
        props=item.get("appProperties") if isinstance(item.get("appProperties"), dict) else {}
        out.append(DriveReconciliationCandidate(str(item.get("id") or ""), str(item.get("mimeType") or ""), str(item.get("webViewLink") or ""), tuple(p for p in (item.get("parents") or []) if isinstance(p,str)), created_dt, {str(k):str(v) for k,v in props.items()}))
    return out
