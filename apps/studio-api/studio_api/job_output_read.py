from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


_ALLOWED_GOOGLE_WEB_VIEW_HOSTS = {"docs.google.com", "drive.google.com"}
OUTPUT_ENTRY_KEYS = {
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


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _iso_or_none(value):
    return value.isoformat() if value is not None else None


def normalize_google_web_view_url(value) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw or raw.startswith("//"):
        return None
    try:
        parsed = urlsplit(raw)
        if parsed.scheme.lower() != "https":
            return None
        hostname = parsed.hostname
        if hostname is None or hostname != hostname.lower() or hostname not in _ALLOWED_GOOGLE_WEB_VIEW_HOSTS:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        host_port = parsed.netloc.rsplit("@", 1)[-1]
        if host_port.endswith(":"):
            return None
        if parsed.port is not None:
            return None
    except (TypeError, ValueError):
        return None
    return urlunsplit(("https", hostname, parsed.path, parsed.query, parsed.fragment))


def normalize_output_web_view_url(value, output_kind) -> str | None:
    from .transcript_docx import DOCX_OUTPUT_KIND
    if output_kind != DOCX_OUTPUT_KIND:
        return normalize_google_web_view_url(value)
    if not isinstance(value, str) or len(value) > 50000:
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.netloc != "disk.yandex.ru"
                or not parsed.path.startswith("/client/disk/") or parsed.query or parsed.fragment):
            return None
        return urlunsplit(("https", "disk.yandex.ru", parsed.path, "", ""))
    except ValueError:
        return None


def browser_job_output_payload(output, job_source, source) -> dict:
    web_view_url = normalize_output_web_view_url(output.web_view_url, output.output_kind)
    return {
        "source_id": job_source.source_id,
        "source_position": job_source.position,
        "source_name": source.original_filename,
        "source_type": _enum_value(source.source_type),
        "output_kind": _enum_value(output.output_kind),
        "transcript_standard": _enum_value(output.transcript_standard),
        "web_view_url": web_view_url,
        "link_available": web_view_url is not None,
        "document_character_count": output.document_character_count,
        "document_created_at": _iso_or_none(output.document_created_at),
        "persisted_at": _iso_or_none(output.persisted_at),
    }


def load_browser_job_output_rows(db, job_id: str):
    from .models import Source, TranscriptionJobOutput, TranscriptionJobSource

    return (
        db.query(TranscriptionJobOutput, TranscriptionJobSource, Source)
        .filter(TranscriptionJobOutput.job_id == job_id)
        .filter(TranscriptionJobOutput.job_source_id == TranscriptionJobSource.id)
        .filter(TranscriptionJobSource.job_id == job_id)
        .filter(TranscriptionJobSource.source_id == Source.id)
        .order_by(
            TranscriptionJobSource.position.asc(),
            TranscriptionJobOutput.persisted_at.asc(),
            TranscriptionJobOutput.id.asc(),
        )
        .all()
    )


def load_primary_output_urls(db, *, owner_user_id: str, job_ids: list[str]) -> dict[str, str]:
    """One bounded owner-scoped query; listing history never fetches each job."""
    from .models import TranscriptionJob, TranscriptionJobOutput, TranscriptionJobSource
    if not job_ids:
        return {}
    rows = (db.query(TranscriptionJobOutput.job_id, TranscriptionJobOutput.web_view_url, TranscriptionJobOutput.output_kind)
        .join(TranscriptionJob, TranscriptionJob.id == TranscriptionJobOutput.job_id)
        .join(TranscriptionJobSource, TranscriptionJobSource.id == TranscriptionJobOutput.job_source_id)
        .filter(TranscriptionJob.owner_user_id == owner_user_id,
                TranscriptionJob.id.in_(job_ids), TranscriptionJobSource.job_id == TranscriptionJob.id)
        .order_by(TranscriptionJobSource.position, TranscriptionJobOutput.persisted_at,
                  TranscriptionJobOutput.id).all())
    result = {}
    for job_id, raw_url, output_kind in rows:
        url = normalize_output_web_view_url(raw_url, output_kind)
        if url:
            result.setdefault(job_id, url)
    return result
