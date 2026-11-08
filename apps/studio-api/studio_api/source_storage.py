from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from urllib.parse import quote, urlparse

from botocore.exceptions import ClientError

from .config import Settings


class SourceStorageError(RuntimeError):
    pass


TRANSCRIPTION_REFERENCE_CLASS = "transcription"
AUDIO_PROCESSING_REFERENCE_CLASS = "audio_processing"
REFERENCE_CLASSES = frozenset(
    {TRANSCRIPTION_REFERENCE_CLASS, AUDIO_PROCESSING_REFERENCE_CLASS}
)


@dataclass(frozen=True)
class ReferenceStorageSettings:
    source_s3_endpoint_url: str | None
    source_s3_region: str
    source_s3_bucket: str | None
    source_s3_access_key_id_file: str | None
    source_s3_secret_access_key_file: str | None
    source_s3_lifecycle_rule_id: str | None

    def source_storage_configured(self) -> bool:
        return bool(
            self.source_s3_endpoint_url
            and self.source_s3_bucket
            and self.source_s3_access_key_id_file
            and self.source_s3_secret_access_key_file
        )


def normalize_reference_class(value: str | None) -> str:
    normalized = value or TRANSCRIPTION_REFERENCE_CLASS
    if normalized not in REFERENCE_CLASSES:
        raise SourceStorageError("Неизвестный класс reference storage")
    return normalized


def source_reference_class(source) -> str:
    return normalize_reference_class(getattr(source, "reference_class", None))


def reference_storage_settings(settings, reference_class: str) -> ReferenceStorageSettings:
    normalized = normalize_reference_class(reference_class)
    prefix = (
        "audio_reference_s3"
        if normalized == AUDIO_PROCESSING_REFERENCE_CLASS
        else "source_s3"
    )
    return ReferenceStorageSettings(
        source_s3_endpoint_url=getattr(settings, f"{prefix}_endpoint_url", None),
        source_s3_region=getattr(settings, f"{prefix}_region", "auto"),
        source_s3_bucket=getattr(settings, f"{prefix}_bucket", None),
        source_s3_access_key_id_file=getattr(
            settings, f"{prefix}_access_key_id_file", None
        ),
        source_s3_secret_access_key_file=getattr(
            settings, f"{prefix}_secret_access_key_file", None
        ),
        source_s3_lifecycle_rule_id=getattr(
            settings, f"{prefix}_lifecycle_rule_id", None
        ),
    )


def reference_storage_bucket(settings, reference_class: str) -> str | None:
    return reference_storage_settings(settings, reference_class).source_s3_bucket


def reference_storage_isolation_configured(settings) -> bool:
    configured = getattr(settings, "reference_storage_isolation_configured", None)
    if callable(configured):
        return bool(configured())
    transcription = reference_storage_settings(
        settings, TRANSCRIPTION_REFERENCE_CLASS
    )
    audio = reference_storage_settings(settings, AUDIO_PROCESSING_REFERENCE_CLASS)
    return bool(
        transcription.source_storage_configured()
        and audio.source_storage_configured()
        and transcription.source_s3_bucket != audio.source_s3_bucket
        and transcription.source_s3_access_key_id_file
        != audio.source_s3_access_key_id_file
        and transcription.source_s3_secret_access_key_file
        != audio.source_s3_secret_access_key_file
        and (transcription.source_s3_lifecycle_rule_id or "").strip()
        and (audio.source_s3_lifecycle_rule_id or "").strip()
        and transcription.source_s3_lifecycle_rule_id
        != audio.source_s3_lifecycle_rule_id
    )


class SourceObjectReadReason(str, Enum):
    missing = "missing"
    unavailable = "unavailable"


class SourceObjectReadError(RuntimeError):
    def __init__(self, reason: SourceObjectReadReason):
        self.reason = reason
        super().__init__(reason.value)


@dataclass
class SourceObjectStream:
    body: object
    content_type: str | None
    content_length: int | None

    def iter_chunks(self, chunk_size: int):
        while True:
            chunk = self.body.read(chunk_size)
            if not chunk:
                break
            yield chunk

    def close(self) -> None:
        close = getattr(self.body, "close", None)
        if close:
            close()


@dataclass(frozen=True)
class ObjectHead:
    size_bytes: int | None
    content_type: str | None
    etag: str | None = None
    last_modified: datetime | None = None


@dataclass(frozen=True)
class MultipartPart:
    part_number: int
    etag: str
    size_bytes: int


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int
    etag: str | None
    last_modified: datetime


@dataclass(frozen=True)
class StoredObjectPage:
    objects: tuple[StoredObject, ...]
    next_token: str | None


class S3SourceStorage:
    def __init__(self, settings: Settings | ReferenceStorageSettings):
        self.settings = settings
        self.bucket = settings.source_s3_bucket
        if not settings.source_storage_configured():
            raise SourceStorageError("Временное хранилище источников не настроено")

        import boto3
        from botocore.config import Config

        self.client = boto3.client(
            "s3",
            config=Config(signature_version="s3v4"),
            endpoint_url=settings.source_s3_endpoint_url,
            region_name=settings.source_s3_region,
            aws_access_key_id=Path(settings.source_s3_access_key_id_file).read_text(encoding="utf-8").strip(),
            aws_secret_access_key=Path(settings.source_s3_secret_access_key_file).read_text(encoding="utf-8").strip(),
        )

    def presigned_put_url(self, key: str, content_type: str, expires_seconds: int, size_bytes: int) -> str:
        return self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type, "ContentLength": size_bytes},
            ExpiresIn=expires_seconds,
        )

    def create_multipart_upload(self, key: str, content_type: str) -> str:
        result = self.client.create_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            ContentType=content_type,
        )
        upload_id = result.get("UploadId")
        if not isinstance(upload_id, str) or not upload_id or len(upload_id) > 2048:
            raise SourceStorageError("Object storage не вернул upload session")
        return upload_id

    def presigned_upload_part_url(
        self,
        key: str,
        upload_id: str,
        part_number: int,
        expires_seconds: int,
        size_bytes: int,
    ) -> str:
        return self.client.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "UploadId": upload_id,
                "PartNumber": part_number,
                "ContentLength": size_bytes,
            },
            ExpiresIn=expires_seconds,
        )

    def list_multipart_parts(self, key: str, upload_id: str) -> tuple[MultipartPart, ...]:
        marker = 0
        parts: list[MultipartPart] = []
        while True:
            try:
                result = self.client.list_parts(
                    Bucket=self.bucket,
                    Key=key,
                    UploadId=upload_id,
                    PartNumberMarker=marker,
                    MaxParts=1000,
                )
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code in {"404", "NoSuchKey", "NoSuchUpload", "NotFound"}:
                    raise FileNotFoundError(upload_id) from exc
                raise
            for raw in result.get("Parts") or ():
                part_number = raw.get("PartNumber")
                etag = raw.get("ETag")
                size = raw.get("Size")
                if (
                    not isinstance(part_number, int)
                    or part_number < 1
                    or not isinstance(etag, str)
                    or not etag
                    or not isinstance(size, int)
                    or size < 0
                ):
                    raise SourceStorageError("Object storage вернул некорректный multipart state")
                parts.append(MultipartPart(part_number, etag, size))
            if not result.get("IsTruncated"):
                break
            next_marker = result.get("NextPartNumberMarker")
            if not isinstance(next_marker, int) or next_marker <= marker:
                raise SourceStorageError("Object storage не продолжил multipart listing")
            marker = next_marker
            if len(parts) > 10_000:
                raise SourceStorageError("Multipart session превышает допустимое число частей")
        return tuple(sorted(parts, key=lambda part: part.part_number))

    def complete_multipart_upload(
        self,
        key: str,
        upload_id: str,
        parts: tuple[MultipartPart, ...],
    ) -> None:
        if not parts:
            raise SourceStorageError("Multipart upload не содержит частей")
        self.client.complete_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={
                "Parts": [
                    {"PartNumber": part.part_number, "ETag": part.etag}
                    for part in parts
                ]
            },
        )

    def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        try:
            self.client.abort_multipart_upload(
                Bucket=self.bucket,
                Key=key,
                UploadId=upload_id,
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in {"404", "NoSuchKey", "NoSuchUpload", "NotFound"}:
                return
            raise

    def multipart_upload_absent(self, key: str, upload_id: str) -> bool:
        try:
            self.list_multipart_parts(key, upload_id)
        except FileNotFoundError:
            return True
        return False

    def presigned_get_url(self, key: str, expires_seconds: int, *, download_name: str | None = None) -> str:
        params = {"Bucket": self.bucket, "Key": key}
        if download_name:
            params["ResponseContentDisposition"] = attachment_content_disposition(download_name)
        return self.client.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expires_seconds,
        )

    def put_file(self, key: str, path: Path, content_type: str) -> None:
        self.client.upload_file(
            str(path),
            self.bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )

    def head_object(self, key: str) -> ObjectHead:
        try:
            result = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in {"404", "NoSuchKey", "NotFound"}:
                raise FileNotFoundError(key) from exc
            raise
        last_modified = result.get("LastModified")
        if isinstance(last_modified, datetime) and last_modified.tzinfo is None:
            last_modified = last_modified.replace(tzinfo=timezone.utc)
        return ObjectHead(
            size_bytes=result.get("ContentLength"),
            content_type=result.get("ContentType"),
            etag=result.get("ETag"),
            last_modified=last_modified if isinstance(last_modified, datetime) else None,
        )

    def list_objects_page(
        self,
        prefix: str,
        *,
        continuation_token: str | None = None,
        start_after: str | None = None,
        max_keys: int = 100,
    ) -> StoredObjectPage:
        params = {
            "Bucket": self.bucket,
            "Prefix": prefix,
            "MaxKeys": max(1, min(1000, max_keys)),
        }
        if continuation_token:
            params["ContinuationToken"] = continuation_token
        if start_after:
            params["StartAfter"] = start_after
        result = self.client.list_objects_v2(**params)
        objects: list[StoredObject] = []
        for raw in result.get("Contents") or ():
            key = raw.get("Key")
            size = raw.get("Size")
            modified = raw.get("LastModified")
            if (
                not isinstance(key, str)
                or not key
                or not isinstance(size, int)
                or size < 0
                or not isinstance(modified, datetime)
            ):
                raise SourceStorageError("Object storage вернул некорректный inventory")
            if modified.tzinfo is None:
                modified = modified.replace(tzinfo=timezone.utc)
            objects.append(
                StoredObject(
                    key=key,
                    size_bytes=size,
                    etag=raw.get("ETag") if isinstance(raw.get("ETag"), str) else None,
                    last_modified=modified,
                )
            )
        token = result.get("NextContinuationToken")
        if result.get("IsTruncated") and (not isinstance(token, str) or not token):
            raise SourceStorageError("Object storage не продолжил inventory listing")
        return StoredObjectPage(tuple(objects), token if result.get("IsTruncated") else None)

    def open_read(self, key: str) -> SourceObjectStream:
        try:
            result = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in {"404", "NoSuchKey", "NotFound"}:
                raise SourceObjectReadError(SourceObjectReadReason.missing) from exc
            raise SourceObjectReadError(SourceObjectReadReason.unavailable) from exc
        except Exception as exc:
            raise SourceObjectReadError(SourceObjectReadReason.unavailable) from exc
        return SourceObjectStream(result["Body"], result.get("ContentType"), result.get("ContentLength"))

    def delete_object(self, key: str, *, bucket: str | None = None) -> None:
        try:
            self.client.delete_object(Bucket=bucket or self.bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return
            raise

    def delete_object_verified(self, key: str, *, bucket: str | None = None) -> bool:
        selected_bucket = bucket or self.bucket
        # R2 does not implement object versioning. Only the provider's exact
        # documented endpoint is exempt; errors from generic S3 fail closed.
        endpoint = getattr(getattr(self, "settings", None), "source_s3_endpoint_url", "") or ""
        host = urlparse(endpoint).hostname or ""
        r2 = host.endswith(".r2.cloudflarestorage.com")
        versioned = False
        if not r2:
            status = self.client.get_bucket_versioning(Bucket=selected_bucket).get("Status")
            if status not in (None, "Enabled", "Suspended"):
                raise SourceStorageError("Object storage вернул неизвестный versioning state")
            # Suspended buckets can still retain historical versions.
            versioned = status in ("Enabled", "Suspended")
        self.delete_object(key, bucket=selected_bucket)
        if versioned:
            versions = self._object_versions(key, selected_bucket)
            for offset in range(0, len(versions), 1000):
                result = self.client.delete_objects(Bucket=selected_bucket, Delete={
                    "Objects": [{"Key": key, "VersionId": value} for value in versions[offset:offset + 1000]],
                    "Quiet": True,
                })
                if result.get("Errors"):
                    raise SourceStorageError("Object storage не подтвердил удаление всех версий")
            if self._object_versions(key, selected_bucket):
                return False
        try:
            self.client.head_object(Bucket=selected_bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return True
            raise
        return False

    def _object_versions(self, key: str, bucket: str) -> tuple[str, ...]:
        """Bounded exact-key enumeration, including delete markers."""
        params = {"Bucket": bucket, "Prefix": key, "MaxKeys": 1000}
        seen: set[tuple[str, str]] = set()
        versions: list[str] = []
        for _ in range(10):
            result = self.client.list_object_versions(**params)
            raw_entries = [*(result.get("Versions") or ()), *(result.get("DeleteMarkers") or ())]
            if len(raw_entries) > 1000:
                raise SourceStorageError("Object storage превысил version listing limit")
            for raw in raw_entries:
                entry_key, version_id = raw.get("Key"), raw.get("VersionId")
                if not isinstance(entry_key, str) or not entry_key.startswith(key):
                    raise SourceStorageError("Object storage нарушил version listing scope")
                if entry_key != key:
                    continue  # Prefix siblings never belong to this deletion.
                if not isinstance(version_id, str) or not version_id or len(version_id) > 2048:
                    raise SourceStorageError("Object storage вернул некорректную version identity")
                versions.append(version_id)
            if not result.get("IsTruncated"):
                return tuple(dict.fromkeys(versions))
            marker = (result.get("NextKeyMarker"), result.get("NextVersionIdMarker"))
            if (not isinstance(marker[0], str) or not marker[0]
                or marker[1] is not None and not isinstance(marker[1], str)
                or marker in seen):
                raise SourceStorageError("Object storage не продолжил version listing")
            seen.add(marker)
            params["KeyMarker"] = marker[0]
            if marker[1]:
                params["VersionIdMarker"] = marker[1]
            else:
                params.pop("VersionIdMarker", None)
        raise SourceStorageError("Object storage version listing превышает безопасный предел")


def get_source_storage(settings: Settings) -> S3SourceStorage:
    return S3SourceStorage(settings)


def get_reference_storage(settings, reference_class: str) -> S3SourceStorage:
    selected = reference_storage_settings(settings, reference_class)
    if not selected.source_storage_configured():
        raise SourceStorageError("Reference storage не настроено")
    return get_source_storage(selected)


SOURCE_DISPLAY_FILENAME_MAX_LENGTH = 255


def _truncate_preserving_extension(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    stem, dot, extension = value.rpartition(".")
    if dot and stem and 1 < len(extension) <= 24 and len(extension) + 1 < max_length:
        return f"{stem[: max_length - len(extension) - 1].rstrip()} .{extension}".replace(" .", ".")
    return value[:max_length].rstrip()


def normalize_source_display_filename(name: str, max_length: int = SOURCE_DISPLAY_FILENAME_MAX_LENGTH) -> str:
    value = unicodedata.normalize("NFC", name or "")
    cleaned = []
    for char in value.replace("\\", "_").replace("/", "_"):
        category = unicodedata.category(char)
        if char in {"\n", "\r", "\x00"} or category.startswith("C"):
            continue
        cleaned.append(char)
    value = "".join(cleaned).strip()
    value = re.sub(r"[ 	]+", " ", value)
    value = _truncate_preserving_extension(value or "source", max_length).strip()
    return value or "source"


def safe_filename(name: str) -> str:
    value = (name or "source").strip().replace("\\", "_").replace("/", "_")
    value = re.sub(r"[^A-Za-z0-9._ -]+", "_", value).strip(" ._")
    return (value or "source")[:180]


def attachment_content_disposition(name: str) -> str:
    display_name = normalize_source_display_filename(name)
    ascii_name = safe_filename(display_name)
    suffix = Path(display_name).suffix
    if (
        suffix
        and re.fullmatch(r"\.[A-Za-z0-9]{1,24}", suffix)
        and not ascii_name.casefold().endswith(suffix.casefold())
    ):
        ascii_name = f"download{suffix}"
    encoded_name = quote(display_name, safe="")
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_name}'
