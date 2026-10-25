import hashlib, json, logging, re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, WebSocket, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response as FastAPIResponse, FileResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictBool, StrictInt, field_validator, model_validator
from sqlalchemy import and_, text, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from .audit import audit
from .auth_retention import cleanup_expired_auth_state
from .collection_pagination import CollectionCursorError, DEFAULT_COLLECTION_PAGE_SIZE, MAX_COLLECTION_CURSOR_LENGTH, MAX_COLLECTION_PAGE_SIZE, decode_collection_cursor, page_envelope
from .config import get_settings
from .db import Base, engine, get_db, SessionLocal
from .audio_downloads import AudioDownloadError, AudioDownloadManager, stream_audio_download
from .deps import current_session, get_client_ip, require_csrf, require_same_origin
from .integration_ports import get_authorization_provider, get_cloud_files_provider, AuthorizationProvider
from .models import *
from .rate_limit import RateLimiter
from .http_limits import RequestBodyLimitMiddleware
from .oauth_session import lock_oauth_initiator
from .security import *
from .source_storage import (
    get_reference_storage,
    normalize_source_display_filename,
    reference_storage_bucket,
    reference_storage_isolation_configured,
    source_reference_class,
)
from .source_creation import parse_authoritative_source_created_at
from .media_context import prepared_audio_context_payload, known_prepared_duration_seconds
from .source_policy import SOURCE_RETENTION_TTL_OPTIONS_SECONDS, UploadedObjectMetadataIssue, browser_source_upload_policy, effective_source_retention_seconds, is_supported_source_mime_type, normalize_source_mime_type, uploaded_object_metadata_issue, validate_source_size
from .google_connection_access import GoogleConnectionAccessError, GoogleConnectionAccessReason, active_google_connection_for_user, google_maintenance_token_aad, google_token_aad, require_drive_file_scope, require_drive_readonly_scope, require_picker_browser_scope_boundary
from .google_scopes import has_maintenance_server_scope_boundary, has_picker_browser_scope_boundary
from .job_lifecycle import safe_failure_metadata_value
from .job_attention import confirmed_later_results_query, recent_attention_candidates
from .job_processing_lifecycle import request_job_cancellation
from .diagnostics import REGISTRY, cleanup_expired_diagnostics, cursor_context, decode_cursor_payload, encode_cursor, new_correlation_id, new_request_id, sanitize_build_id, sanitize_inbound_correlation, valid_correlation_id, valid_uuid, write_diagnostic_event
from .trace_context import reset_current_trace_id, sanitize_inbound_trace, set_current_trace_id, valid_trace_id
from .operational_alerts import acknowledge_incident, incident_payload
from .diagnostic_reports import build_diagnostic_report, serialize_diagnostic_report
from .job_output_read import browser_job_output_payload, load_browser_job_output_rows, load_primary_output_urls
from .job_progress import load_browser_job_progress_payloads
from .realtime_capability import RealtimeCapabilityError, RealtimeCapabilityReason, create_realtime_capability
from .realtime_drafts import (
    RealtimeDraftError,
    RealtimeDraftReason,
    delete_realtime_draft,
    load_latest_realtime_draft,
    save_realtime_draft,
)
from .speaker_identity import (
    job_speaker_payload,
    normalize_profile_name,
    normalize_profile_role,
    speaker_profile_payload,
)
from .speaker_sample import (
    SpeakerSampleError,
    SpeakerSampleReason,
    create_speaker_sample_audio,
)
from .speaker_assignment import (
    SpeakerAssignmentError,
    SpeakerAssignmentReason,
    assign_speaker_profile,
)
from .session_control import (
    list_active_sessions,
    revoke_all_owned_other_sessions,
    revoke_owned_other_session,
)
from .trusted_device import (
    clear_trusted_device_cookie,
    current_trusted_device,
    remember_current_browser,
    revoke_all_browsers,
    revoke_current_browser,
)
from .endpoint_group import diagnostic_endpoint_group
from .transcription_analytics import load_transcription_analytics_payload
from .elevenlabs_account import ElevenLabsAccountTransport
from .provider_account_sync import (
    provider_account_payload,
    sync_elevenlabs_account,
    unavailable_provider_account_payload,
)
from .provider_usage_accounting import job_usage_cost_payload
from .job_output_reconciliation import OutputReconciliationError, OutputReconciliationReason, check_job_output_reconciliation, reconciliation_status_payload
from .job_retry_recovery import compute_explicit_retry_readiness, queue_retry, requires_provider_cost_confirmation
from .job_notifications import (
    notification_preference,
    notification_preferences_payload,
    revoke_web_push_subscription,
)
from .google_docs_output import OUTPUT_RECONCILIATION_APP_PROPERTY
from .google_drive import GoogleDriveReconciliationError, list_reconciliation_candidates
from .job_output_folder_selection import VerifiedOutputFolderSelection, verify_output_folder_selection
from .media_clip import MediaClipRangeError, normalize_media_clip_range, validate_known_clip_duration
from .batch_preflight import build_batch_preflight_payload
from .source_deletion import (
    SourceDeletionReason,
    bulk_source_deletion_preview,
    validate_bulk_source_selection,
    is_source_expired,
    request_source_deletion,
)
from .transcript_catalog import (
    ExistingResultMatchStatus,
    GOOGLE_DOCS_TRANSCRIPT_OUTPUT_KIND,
    ProviderAttemptAuthorityStatus,
    current_effective_settings,
    elevenlabs_effective_settings,
    load_existing_result_matches,
    load_provider_attempt_authorities,
    lock_catalog_source_identities,
)
from .transcription_options import DEFAULT_TRANSCRIPTION_LANGUAGE_MODE, EXISTING_RESULT_REPROCESS_AUTHORITY_OPTION, TranscriptionLanguageMode, browser_language_mode, job_diarization_enabled, provider_language_code, stored_language_mode, stored_transcription_options
from .stt_provider import SttCapabilityError, SttOperatingMode, SttProvider, catalog_payload, resolve_capability, validate_selection
from .stt_provider_health import provider_health, record_provider_failure, record_provider_success
from .stt_dictionaries import (
    DictionaryEntryKind,
    dictionary_payload,
    load_owned_dictionaries,
    normalize_dictionary_entries,
    normalize_dictionary_name,
    replace_dictionary_entries,
    snapshot_dictionary_terms,
)
from .yandex_realtime_relay import create_yandex_realtime_capability, relay_yandex_realtime
from .realtime_consumers import (
    RealtimeConsumerError,
    RealtimeConsumerKind,
    deliver_realtime_caption,
    validate_realtime_consumer_target,
)
from .transcript_catalog_routes import router as transcript_catalog_router
from .audio_preparation import AudioPreparationError
from .direct_drive_upload import (
    DIRECT_DRIVE_UPLOAD_CAPABILITY_MAX_LENGTH,
    DIRECT_DRIVE_UPLOAD_CAPABILITY_SECONDS,
    DIRECT_DRIVE_UPLOAD_MAX_FILES,
    DirectDriveUploadError,
    DirectDriveUploadReason,
    decode_direct_drive_upload_capability,
    direct_drive_upload_descriptor_digest,
    direct_drive_upload_policy,
    encode_direct_drive_upload_capability,
    normalize_direct_drive_upload_descriptor,
    validate_direct_drive_upload_batch,
    verify_direct_drive_upload_result,
)
from .audio_preparation_service import (
    AudioPreparationServiceError,
    audio_preparation_payload,
    recover_audio_preparation_output,
    cancel_audio_preparation_job,
    create_audio_preparation_job,
    list_owned_audio_preparation_jobs,
    load_owned_audio_preparation_job,
    start_audio_preparation_job,
    queue_audio_drive_export,
)
from .runtime_observability import (
    check_database_readiness,
    coherent_release_version,
    database_schema_revision,
    load_web_runtime_identity,
    load_worker_runtime_status,
    queue_runtime_status,
    runtime_identity_payload,
    settings_runtime_identity,
    source_storage_runtime_status,
    stt_provider_runtime_status,
)
from .storage_reconciliation import (
    StorageReconciliationError,
    StorageReconciliationReason,
    apply_reconciliation_plan,
    issue_reconciliation_plan,
    scan_owner_storage,
    storage_lifecycle_payload,
)
from .account_security import (
    generate_recovery_codes,
    generate_totp_secret,
    recovery_code_hash,
    totp_factor_aad,
    totp_qr_data_uri,
    totp_uri,
    consume_totp_code,
)

settings=get_settings()
@asynccontextmanager
async def app_lifespan(application):
    audio_downloads.start()
    try:
        yield
    finally:
        audio_downloads.close()

app=FastAPI(docs_url="/docs" if settings.enable_api_docs else None, redoc_url=None, openapi_url="/openapi.json" if settings.enable_api_docs else None, lifespan=app_lifespan)
app.include_router(transcript_catalog_router)
limiter=RateLimiter()
audio_downloads = AudioDownloadManager(SessionLocal, settings)
LOGGER=logging.getLogger("studio_api.api")
REALTIME_DRAFT_SAVE_LIMIT_PER_HOUR = 7_200
REALTIME_DRAFT_ROUTE_PATTERN = re.compile(
    r"^/api/projects/[^/]+/realtime/drafts/[^/]+$"
)


def _is_realtime_draft_route(path: str) -> bool:
    return REALTIME_DRAFT_ROUTE_PATTERN.fullmatch(path) is not None


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(request: Request, exc: RequestValidationError):
    if not _is_realtime_draft_route(request.url.path):
        return await request_validation_exception_handler(request, exc)
    response = JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": [
                {
                    "type": error.get("type", "validation_error"),
                    "loc": list(error.get("loc", ())),
                }
                for error in exc.errors()
            ]
        },
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response

app.add_middleware(RequestBodyLimitMiddleware)

@app.middleware("http")
async def request_correlation_middleware(request: Request, call_next):
    request_id = new_request_id()
    correlation_id = sanitize_inbound_correlation(request.headers.get("x-correlation-id"))
    trace_id = sanitize_inbound_trace(request.headers.get("x-trace-id"))
    trace_token = set_current_trace_id(trace_id)
    request.state.request_id = request_id
    request.state.correlation_id = correlation_id
    request.state.trace_id = trace_id
    request.state.owner_user_id = None
    try:
        try:
            response = await call_next(request)
        except Exception:
            endpoint_group=diagnostic_endpoint_group(request.url.path)
            LOGGER.error("api_unhandled_exception request_id=%s correlation_id=%s trace_id=%s endpoint_group=%s", request_id, correlation_id, trace_id, endpoint_group)
            owner_user_id=getattr(request.state, "owner_user_id", None)
            if owner_user_id:
                try:
                    write_diagnostic_event(owner_user_id=owner_user_id, component="api", event_code="API_UNHANDLED_EXCEPTION", trace_id=trace_id, correlation_id=correlation_id, request_id=request_id, metadata={"endpoint_group":endpoint_group, "http_status_category":"5xx"})
                except Exception:
                    LOGGER.warning("api_unhandled_diagnostic_write_failed request_id=%s correlation_id=%s trace_id=%s endpoint_group=%s", request_id, correlation_id, trace_id, endpoint_group)
            response = JSONResponse({"detail": "Internal server error"}, status_code=500)
        if _is_realtime_draft_route(request.url.path):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Trace-ID"] = trace_id
        return response
    finally:
        reset_current_trace_id(trace_token)


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str=Field(min_length=1, max_length=1024)
    login_csrf_token: str=Field(min_length=1, max_length=256)
    verification_code: str|None=Field(default=None, max_length=32)
    recovery_code: str|None=Field(default=None, max_length=64)

class ReauthenticateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str=Field(min_length=1,max_length=1024)
    verification_code: str|None=Field(default=None,max_length=32)
    recovery_code: str|None=Field(default=None,max_length=64)
    remember_device: StrictBool=False

class TrustedDeviceRevokeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    all_devices: StrictBool=False

class TotpConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verification_code: str=Field(min_length=6,max_length=32)

class TotpDisableIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verification_code: str|None=Field(default=None,max_length=32)
    recovery_code: str|None=Field(default=None,max_length=64)

class PasswordResetRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr

class PasswordResetConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str=Field(min_length=32,max_length=256)
    new_password: str=Field(min_length=12,max_length=1024)
class CredentialIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: CredentialProvider
    label: str=Field(min_length=1,max_length=120)
    raw_value: str=Field(min_length=8,max_length=4096)
    folder_id: str|None=Field(default=None,min_length=1,max_length=256)

    @model_validator(mode="after")
    def validate_provider_config(self):
        folder_id = self.folder_id.strip() if isinstance(self.folder_id, str) else None
        if self.provider == CredentialProvider.yandex and not folder_id:
            raise ValueError("Для Yandex укажите ID каталога")
        if self.provider != CredentialProvider.yandex and folder_id:
            raise ValueError("ID каталога поддерживается только для Yandex")
        self.folder_id = folder_id
        return self

class SttDictionaryEntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: DictionaryEntryKind
    value: str=Field(min_length=1,max_length=160)

class SttDictionaryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str=Field(min_length=1,max_length=120)
    entries: list[SttDictionaryEntryIn]=Field(min_length=1,max_length=500)
class ProjectIn(BaseModel): title: str=Field(min_length=1,max_length=160); description: str|None=Field(default=None,max_length=2000)
class ProjectPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str|None=Field(default=None,min_length=1,max_length=160)
    description: str|None=Field(default=None,max_length=2000)

class GooglePickerSourceSelectionIn(BaseModel):
    file_ids: list[str]=Field(min_length=1,max_length=50)

    @field_validator("file_ids")
    @classmethod
    def unique_file_ids(cls, value):
        cleaned=[]
        for item in value:
            if not isinstance(item, str):
                raise ValueError("Некорректный ID файла Google Drive")
            normalized=item.strip()
            if not normalized:
                raise ValueError("Некорректный ID файла Google Drive")
            cleaned.append(normalized)
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("Повторяющиеся Google Drive файлы не допускаются")
        return cleaned

class GooglePickerOutputFolderIn(BaseModel):
    folder_id: str=Field(min_length=1,max_length=256)

class GoogleDriveFolderPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folder_id: str=Field(min_length=1,max_length=256)

class GoogleDriveFolderApplyIn(GoogleDriveFolderPreviewIn):
    preview_token: str=Field(pattern=r"^[a-f0-9]{64}$")

class GoogleDriveSourceIn(BaseModel):
    drive_file_id: str=Field(min_length=1,max_length=256)
    drive_file_url: str|None=Field(default=None,max_length=2000)
    original_filename: str=Field(min_length=1,max_length=255)
    mime_type: str|None=Field(default=None,max_length=255)
    size_bytes: int|None=Field(default=None,ge=0)

class LocalUploadInitiateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    original_filename: str=Field(min_length=1,max_length=255)
    mime_type: str=Field(min_length=1,max_length=255)
    size_bytes: int=Field(ge=1)
    reference_class: SourceReferenceClass
    audio_retention_days: StrictInt|None=None
    delete_after_transcripts: StrictBool=False

    @model_validator(mode="after")
    def audio_retention_is_valid(self):
        if self.delete_after_transcripts and self.reference_class != SourceReferenceClass.transcription:
            raise ValueError("Автоудаление после документов применяется только к исходнику транскрибации")
        if self.audio_retention_days is not None and (
            self.reference_class != SourceReferenceClass.audio_processing
            or self.audio_retention_days not in (3, 7, 30)
        ):
            raise ValueError("Срок хранения исходников аудио: 3, 7 или 30 дней")
        return self


class StorageReconciliationApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_token: str=Field(min_length=40,max_length=1600,pattern=r"^[A-Za-z0-9_-]+$")
    confirm: StrictBool

    @model_validator(mode="after")
    def require_confirmation(self):
        if self.confirm is not True:
            raise ValueError("Требуется явное подтверждение")
        return self


def _multipart_part_count(size_bytes: int, part_size_bytes: int) -> int:
    return (size_bytes + part_size_bytes - 1) // part_size_bytes


def _multipart_parts_match_source(
    *,
    expected_size_bytes: int | None,
    part_size_bytes: int | None,
    part_count: int | None,
    parts,
) -> bool:
    if (
        part_count is None
        or part_size_bytes is None
        or expected_size_bytes is None
        or len(parts) != part_count
    ):
        return False
    expected_last_size = expected_size_bytes - (part_size_bytes * (part_count - 1))
    if expected_last_size < 1 or expected_last_size > part_size_bytes:
        return False
    for index, part in enumerate(parts, start=1):
        expected_size = (
            expected_last_size
            if index == part_count
            else part_size_bytes
        )
        if part.part_number != index or part.size_bytes != expected_size:
            return False
    return True

class DirectDriveUploadFileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str=Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
    original_filename: str=Field(min_length=1,max_length=255)
    mime_type: str=Field(min_length=1,max_length=255)
    size_bytes: StrictInt=Field(ge=1)

class DirectDriveUploadSessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folder_id: str=Field(min_length=1,max_length=256)
    files: list[DirectDriveUploadFileIn]=Field(min_length=1,max_length=DIRECT_DRIVE_UPLOAD_MAX_FILES)

class DirectDriveUploadCompleteIn(DirectDriveUploadFileIn):
    folder_id: str=Field(min_length=1,max_length=256)
    file_id: str=Field(min_length=1,max_length=256)
    capability: str=Field(min_length=80,max_length=DIRECT_DRIVE_UPLOAD_CAPABILITY_MAX_LENGTH)

class AudioPreparationCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str=Field(min_length=1,max_length=160)
    source_ids: list[str]=Field(min_length=1,max_length=50)
    ephemeral_source_ids: list[str]=Field(default_factory=list,max_length=50)
    manual_order: StrictBool=False
    options: dict=Field(default_factory=dict)
    output_destination: str=Field(pattern=r"^(download|google_drive)$")
    output_drive_folder_id: str|None=Field(default=None,min_length=1,max_length=256)

    @model_validator(mode="after")
    def destination_and_sources_are_consistent(self):
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("Повторяющиеся источники не допускаются")
        if len(self.ephemeral_source_ids) != len(set(self.ephemeral_source_ids)):
            raise ValueError("Повторяющиеся временные источники не допускаются")
        if not set(self.ephemeral_source_ids).issubset(set(self.source_ids)):
            raise ValueError("Временный источник должен входить в список входных файлов")
        if (self.output_destination == "google_drive") != bool(self.output_drive_folder_id):
            raise ValueError("Для Google Drive выберите целевую папку")
        return self

class AccountPreferencesPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_retention_ttl_seconds: int|None=None
    accent_color: str|None=Field(default=None, max_length=20)

    @field_validator("source_retention_ttl_seconds")
    @classmethod
    def retention_must_be_supported(cls, value):
        if value is None:
            return value
        if value not in SOURCE_RETENTION_TTL_OPTIONS_SECONDS:
            raise ValueError("Выберите поддерживаемый срок хранения")
        return value

    @field_validator("accent_color")
    @classmethod
    def accent_must_be_supported(cls, value):
        if value is None:
            return value
        if value not in {"blue", "violet", "teal", "rose"}:
            raise ValueError("Выберите поддерживаемый цвет интерфейса")
        return value

    @model_validator(mode="after")
    def at_least_one_preference(self):
        if self.source_retention_ttl_seconds is None and self.accent_color is None:
            raise ValueError("Укажите изменяемую настройку")
        return self

class NotificationPreferencesPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    web_push_enabled: StrictBool|None=None
    email_enabled: StrictBool|None=None
    telegram_enabled: StrictBool|None=None

    @model_validator(mode="after")
    def at_least_one_channel(self):
        if all(
            value is None
            for value in (
                self.web_push_enabled,
                self.email_enabled,
                self.telegram_enabled,
            )
        ):
            raise ValueError("Укажите изменяемый канал уведомлений")
        return self

class WebPushSubscriptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str=Field(min_length=20,max_length=2048)
    p256dh: str=Field(min_length=40,max_length=256)
    auth: str=Field(min_length=12,max_length=64)

class SpeakerProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str=Field(min_length=1,max_length=160)
    role: str=Field(min_length=1,max_length=120)

class SpeakerProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str|None=Field(default=None,min_length=1,max_length=160)
    role: str|None=Field(default=None,min_length=1,max_length=120)

    @model_validator(mode="after")
    def at_least_one_field(self):
        if self.display_name is None and self.role is None:
            raise ValueError("Укажите изменяемое поле")
        return self

class SpeakerAssignmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: str=Field(min_length=1,max_length=36)

class ConfirmedClearIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_clear: StrictBool

    @field_validator("confirm_clear")
    @classmethod
    def clear_must_be_confirmed(cls, value):
        if value is not True:
            raise ValueError("Подтвердите очистку")
        return value


class ConfirmedBulkSourceDeletionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_delete: StrictBool
    expected_preview_token: str = Field(pattern="^[a-f0-9]{64}$")
    expected_eligible_count: StrictInt = Field(ge=0)
    expected_blocked_count: StrictInt = Field(ge=0)
    source_ids: list[str] | None = Field(default=None, min_length=1, max_length=50)

    @field_validator("source_ids")
    @classmethod
    def validate_selection(cls, value):
        return validate_bulk_source_selection(value)

    @field_validator("confirm_delete")
    @classmethod
    def deletion_must_be_confirmed(cls, value):
        if value is not True:
            raise ValueError("Подтвердите удаление")
        return value


class JobAttentionResolutionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution: str = Field(pattern="^(acknowledged_no_result|linked_later_result)$")
    linked_job_id: str | None = Field(default=None, max_length=36)
    confirm_possible_spend: StrictBool

    @model_validator(mode="after")
    def validate_resolution(self):
        if self.confirm_possible_spend is not True:
            raise ValueError("Подтвердите возможное списание у провайдера")
        if self.resolution == "linked_later_result" and not valid_uuid(self.linked_job_id):
            raise ValueError("Выберите подтверждённую более позднюю задачу")
        if self.resolution == "acknowledged_no_result" and self.linked_job_id is not None:
            raise ValueError("Связанная задача здесь не используется")
        return self

class BatchJobItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str=Field(min_length=1,max_length=36)
    output_folder_id: str=Field(min_length=1,max_length=256)
    title: str|None=Field(default=None,max_length=160)
    reprocess_existing: StrictBool=False
    media_clip_start_seconds: StrictInt|None=Field(default=None, ge=0, le=604800)
    media_clip_end_seconds: StrictInt|None=Field(default=None, ge=1, le=604800)

    @model_validator(mode="after")
    def valid_media_clip_range(self):
        try:
            normalize_media_clip_range(
                self.media_clip_start_seconds,
                self.media_clip_end_seconds,
            )
        except MediaClipRangeError as exc:
            raise ValueError("Некорректный диапазон части файла") from exc
        return self

class TranscriptionJobOptionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    diarize: StrictBool=False
    dictionary_ids: list[str]=Field(default_factory=list,max_length=10)

    @field_validator("dictionary_ids")
    @classmethod
    def unique_dictionary_ids(cls, value):
        cleaned=[item.strip() for item in value]
        if any(not item or len(item)>36 for item in cleaned) or len(cleaned)!=len(set(cleaned)):
            raise ValueError("Некорректный список словарей")
        return cleaned

class JobRetryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_remaining_provider_cost: StrictBool=False
    confirm_long_duration_cost: StrictBool=False
    long_duration_confirmation_token: str | None = Field(default=None, min_length=64, max_length=64, pattern="^[a-f0-9]{64}$")

class RealtimeCapabilityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_credential_id: str|None=Field(default=None, max_length=36)
    language: TranscriptionLanguageMode=DEFAULT_TRANSCRIPTION_LANGUAGE_MODE
    provider: SttProvider=SttProvider.elevenlabs

class RealtimeConsumerDeliveryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: RealtimeConsumerKind
    endpoint: str=Field(min_length=12,max_length=2048)
    text: str=Field(min_length=1,max_length=2000)
    sequence: StrictInt=Field(ge=0,le=2147483647)

class RealtimeDraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: StrictInt=Field(ge=1, le=2147483647)
    committed_segments: list[str]=Field(max_length=5000)
    segment_metadata: list[dict | None] | None=Field(default=None, max_length=5000)
    partial: str=Field(default="", max_length=20000)

class TranscriptionJobBatchCreateIn(BaseModel):
    provider: SttProvider=SttProvider.elevenlabs
    operating_mode: SttOperatingMode=SttOperatingMode.standard
    provider_credential_id: str|None=Field(default=None, max_length=36)
    language: TranscriptionLanguageMode=DEFAULT_TRANSCRIPTION_LANGUAGE_MODE
    options: TranscriptionJobOptionsIn=Field(default_factory=TranscriptionJobOptionsIn)
    items: list[BatchJobItemIn]=Field(min_length=1,max_length=50)

class DiagnosticDebugSessionIn(BaseModel):
    duration_minutes: int=Field(ge=1, le=30)

class PwaDiagnosticEventIn(BaseModel):
    event_code: str=Field(min_length=1, max_length=80)
    level: str|None=Field(default=None, min_length=1, max_length=10)
    correlation_id: str|None=Field(default=None, max_length=128)
    project_id: str|None=Field(default=None, min_length=36, max_length=36)
    job_id: str|None=Field(default=None, min_length=36, max_length=36)
    metadata: dict|None=Field(default=None)

class PwaDiagnosticsIn(BaseModel):
    events: list[PwaDiagnosticEventIn]=Field(min_length=1, max_length=20)

class DiagnosticReportIn(BaseModel):
    start: datetime|None=None
    end: datetime|None=None
    level: str|None=Field(default=None, min_length=1, max_length=10)
    component: str|None=Field(default=None, min_length=1, max_length=20)
    event_code: str|None=Field(default=None, min_length=1, max_length=80)
    project_id: str|None=Field(default=None, min_length=36, max_length=36)
    job_id: str|None=Field(default=None, min_length=36, max_length=36)
    problem_description: str|None=Field(default=None, max_length=1000)
    operation_reference: str|None=Field(default=None, max_length=160)

class TranscriptionJobCreateIn(BaseModel):
    source_ids: list[str]=Field(min_length=1, max_length=50)
    provider_credential_id: str|None=Field(default=None, max_length=36)
    title: str|None=Field(default=None, max_length=160)
    language: str|None=Field(default=None, max_length=40)
    options: dict|None=None

    @field_validator("provider_credential_id", mode="before")
    @classmethod
    def normalize_provider_credential_id(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            value=value.strip()
            return value or None
        return value

    @field_validator("source_ids")
    @classmethod
    def unique_source_ids(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Повторяющиеся источники не допускаются")
        return value

def client_id(request: Request):
    return get_client_ip(request, settings)

def set_cookie(resp: Response, token: str):
    resp.set_cookie(settings.cookie_name, token, max_age=settings.session_days*86400, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/")
def clear_cookie(resp: Response): resp.delete_cookie(settings.cookie_name, path="/")

def session_payload(sess, user): return {"authenticated": True, "csrf_token": getattr(sess,"_raw_csrf", None), "user": {"id": user.id, "email": user.email, "role": user.role.value, "accent_color": user.accent_color}}

def _active_totp_factor(db: Session, user_id: str) -> UserTotpFactor|None:
    factor=db.get(UserTotpFactor,user_id)
    if not factor or factor.confirmed_at is None or factor.disabled_at is not None:
        return None
    return factor

def _totp_secret(factor: UserTotpFactor) -> str:
    if factor.key_id != settings.credential_key_id:
        raise HTTPException(503,"Защита аккаунта временно недоступна")
    try:
        return decrypt(
            factor.secret_ciphertext,
            factor.secret_nonce,
            key(),
            totp_factor_aad(factor.user_id),
        )
    except Exception:
        raise HTTPException(503,"Защита аккаунта временно недоступна") from None

def _verify_second_factor(
    db: Session,
    *,
    user: User,
    verification_code: str|None,
    recovery_code: str|None,
    now: datetime,
) -> bool:
    factor=_active_totp_factor(db,user.id)
    if factor is None:
        return True
    if verification_code and consume_totp_code(db, factor=factor, secret=_totp_secret(factor), code=verification_code):
        return True
    if recovery_code:
        row=(
            db.query(UserTotpRecoveryCode)
            .filter_by(
                user_id=user.id,
                code_hash=recovery_code_hash(recovery_code),
                used_at=None,
            )
            .with_for_update()
            .first()
        )
        if row:
            row.used_at=now
            audit(
                db,
                "auth.totp_recovery_consumed",
                actor_user_id=user.id,
                subject_user_id=user.id,
            )
            db.flush()
            return True
    return False

def _recent_auth_deadline(sess: Session) -> datetime|None:
    if sess.reauthenticated_at is None:
        return None
    return sess.reauthenticated_at+timedelta(seconds=settings.recent_auth_seconds)

def require_recent_auth(pair, *, request: Request|None=None, db: Session|None=None) -> tuple[Session,User]:
    sess,user=pair
    deadline=_recent_auth_deadline(sess)
    now=utcnow()
    if deadline is None or deadline <= now:
        if request is not None and db is not None and current_trusted_device(
            db, request=request, user_id=user.id, now=now,
        ) is not None:
            return sess,user
        raise HTTPException(
            409,
            detail={
                "reason":"recent_reauthentication_required",
                "valid_for_seconds":settings.recent_auth_seconds,
            },
            headers={"Cache-Control":"no-store","Pragma":"no-cache"},
        )
    return sess,user

@app.get("/api/livez")
def livez():
    return {"ok": True, "status": "alive"}


def _readiness(db: Session):
    try:
        payload = check_database_readiness(db)
        if not limiter.redis.ping():
            raise RuntimeError("redis_unavailable")
        return {"ok": True, **payload, "redis": "reachable"}
    except Exception:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "service unavailable")


@app.get("/api/readyz")
def readyz(db: Session=Depends(get_db)):
    return _readiness(db)


@app.get("/api/healthz")
def healthz(db: Session=Depends(get_db)):
    return _readiness(db)

@app.get("/api/auth/bootstrap-status")
def bootstrap_status(db: Session=Depends(get_db)):
    limiter.check("bootstrap-status", 60, 60)
    active_admin=db.query(User).filter_by(role=UserRole.admin, status=UserStatus.active).first()
    return {"bootstrap_required": active_admin is None}

@app.post("/api/auth/login-context")
def login_context(request: Request, db: Session=Depends(get_db), _=Depends(require_same_origin)):
    limiter.check("login-context:"+rate_key_part(client_id(request)), 20, 300)
    cleanup_expired_auth_state()
    raw=new_token(); ctx=LoginContext(csrf_hash=token_hash(raw), expires_at=utcnow()+timedelta(minutes=10)); db.add(ctx); db.commit(); return {"login_csrf_token": raw}

@app.post("/api/auth/login")
def login(data: LoginIn, request: Request, response: Response, db: Session=Depends(get_db), _=Depends(require_same_origin), authorization: AuthorizationProvider=Depends(get_authorization_provider)):
    email=normalize_email(data.email); limiter.check("login:account:"+rate_key_part(email), 10, 300); limiter.check("login:"+rate_key_part(client_id(request))+":"+rate_key_part(email), 5, 300)
    ctx=db.query(LoginContext).filter_by(csrf_hash=token_hash(data.login_csrf_token), used_at=None).first()
    if not ctx or ctx.expires_at <= utcnow(): raise HTTPException(403, "Не удалось выполнить вход")
    user=authorization.authenticate(db, email=email, password=data.password)
    if not user:
        audit(db,"auth.login_failed",outcome="rejected"); db.commit(); raise HTTPException(401, "Неверная почта или пароль")
    now=utcnow()
    if _active_totp_factor(db,user.id) is not None:
        limiter.check("totp:login:"+rate_key_part(client_id(request))+":"+rate_key_part(user.id),5,300)
        if not data.verification_code and not data.recovery_code:
            raise HTTPException(409,detail={"reason":"second_factor_required"})
        if not _verify_second_factor(db,user=user,verification_code=data.verification_code,recovery_code=data.recovery_code,now=now):
            audit(db,"auth.login_failed",outcome="rejected",reason="second_factor_invalid"); db.commit()
            raise HTTPException(401,"Не удалось подтвердить вход")
    ctx.used_at=now
    raw_session, raw_csrf = new_token(), new_token()
    sess=Session(user_id=user.id, token_hash=token_hash(raw_session), csrf_hash=token_hash(raw_csrf), expires_at=expires(settings.session_days), rotated_at=now, reauthenticated_at=now)
    db.add(sess); audit(db,"auth.login", actor_user_id=user.id, subject_user_id=user.id); db.commit(); sess._raw_csrf=raw_csrf; set_cookie(response, raw_session); return session_payload(sess,user)

@app.post("/api/auth/logout")
def logout(response: Response, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    sess,user=pair; sess.revoked_at=utcnow(); audit(db,"auth.logout", actor_user_id=user.id, subject_user_id=user.id, session_id=sess.id); db.commit(); clear_cookie(response); return {"ok": True}

@app.get("/api/auth/session")
def session(pair=Depends(current_session)):
    sess,user=pair; deadline=_recent_auth_deadline(sess); return {"authenticated": True, "user": {"id": user.id,"email": user.email,"role": user.role.value,"accent_color": user.accent_color}, "session": {"expires_at": sess.expires_at.isoformat(),"recent_auth_expires_at":deadline.isoformat() if deadline and deadline > utcnow() else None}}

@app.post("/api/auth/csrf")
def refresh_csrf(pair=Depends(current_session), db: Session=Depends(get_db), _=Depends(require_same_origin)):
    sess,user=pair; raw_csrf=new_token(); sess.csrf_hash=token_hash(raw_csrf); sess.rotated_at=utcnow(); audit(db,"auth.csrf_refreshed", actor_user_id=user.id, subject_user_id=user.id, session_id=sess.id); db.commit(); return {"csrf_token": raw_csrf, "user": {"id": user.id,"email": user.email,"role": user.role.value,"accent_color": user.accent_color}, "session": {"expires_at": sess.expires_at.isoformat()}}

@app.get("/api/account")
def account(pair=Depends(current_session)): return session(pair)

@app.get("/api/auth/security")
def account_security_status(request: Request,response: Response,pair=Depends(current_session),db: Session=Depends(get_db),_=Depends(require_same_origin)):
    sess,user=pair; limiter.check("auth:security:get:"+user.id,120,3600); _browser_capability_cache_headers(response)
    factor=db.get(UserTotpFactor,user.id); deadline=_recent_auth_deadline(sess)
    now=utcnow()
    device=current_trusted_device(db,request=request,user_id=user.id,now=now)
    trusted_count=db.query(TrustedDevice).filter(
        TrustedDevice.user_id==user.id,TrustedDevice.revoked_at.is_(None),TrustedDevice.expires_at>now,
    ).count()
    return {
        "totp_enabled":bool(factor and factor.confirmed_at is not None and factor.disabled_at is None),
        "totp_enrollment_pending":bool(factor and factor.confirmed_at is None and factor.disabled_at is None),
        "recent_auth_expires_at":deadline.isoformat() if deadline and deadline > utcnow() else None,
        "trusted_device_expires_at":device.expires_at.isoformat() if device else None,
        "trusted_device_count":trusted_count,
        "password_reset_delivery":"configured" if settings.security_email_configured() else "not_configured",
    }

@app.post("/api/auth/reauth")
def reauthenticate(data: ReauthenticateIn,request: Request,response: Response,pair=Depends(require_csrf),db: Session=Depends(get_db),authorization: AuthorizationProvider=Depends(get_authorization_provider)):
    sess,user=pair
    limiter.check("auth:reauth:account:"+rate_key_part(user.id),10,300)
    limiter.check("auth:reauth:"+rate_key_part(client_id(request))+":"+rate_key_part(user.id),5,300)
    ident=db.get(LocalIdentity,user.id); now=utcnow()
    valid=bool(ident and authorization.verify_password(ident.password_hash,data.password))
    if valid and _active_totp_factor(db,user.id) is not None:
        valid=_verify_second_factor(db,user=user,verification_code=data.verification_code,recovery_code=data.recovery_code,now=now)
    if not valid:
        audit(db,"auth.reauthentication_failed",actor_user_id=user.id,subject_user_id=user.id,outcome="rejected")
        db.commit(); raise HTTPException(401,"Не удалось подтвердить личность")
    sess.reauthenticated_at=now
    trusted=None
    if data.remember_device:
        trusted=remember_current_browser(
            db,request=request,response=response,user_id=user.id,now=now,settings=settings,
        )
        audit(db,"auth.trusted_device_created",actor_user_id=user.id,subject_user_id=user.id)
    audit(db,"auth.reauthenticated",actor_user_id=user.id,subject_user_id=user.id,session_id=sess.id)
    db.commit(); _browser_capability_cache_headers(response)
    return {"ok":True,"recent_auth_expires_at":_recent_auth_deadline(sess).isoformat(),
            "trusted_device_expires_at":trusted.expires_at.isoformat() if trusted else None}

@app.post("/api/auth/trusted-device/revoke")
def revoke_trusted_device(data: TrustedDeviceRevokeIn,request: Request,response: Response,pair=Depends(require_csrf),db: Session=Depends(get_db)):
    _,user=pair
    limiter.check("auth:trusted-device:revoke:"+user.id,10,3600)
    now=utcnow()
    if data.all_devices:
        count=revoke_all_browsers(db,user_id=user.id,now=now)
        clear_trusted_device_cookie(response,settings=settings)
    else:
        count=int(revoke_current_browser(db,request=request,response=response,user_id=user.id,now=now,settings=settings))
    audit(db,"auth.trusted_device_revoked",actor_user_id=user.id,subject_user_id=user.id,reason="all" if data.all_devices else "current")
    db.commit(); _browser_capability_cache_headers(response)
    return {"ok":True,"revoked_count":count}

@app.post("/api/auth/totp/enroll")
def enroll_totp(response: Response,pair=Depends(require_csrf),db: Session=Depends(get_db)):
    sess,user=require_recent_auth(pair); limiter.check("totp:enroll:"+user.id,5,3600)
    current=_active_totp_factor(db,user.id)
    if current is not None:
        raise HTTPException(409,"Двухфакторная защита уже включена")
    secret=generate_totp_secret(); ciphertext,nonce=encrypt(secret,key(),totp_factor_aad(user.id)); now=utcnow()
    factor=db.get(UserTotpFactor,user.id)
    if factor is None:
        factor=UserTotpFactor(user_id=user.id,secret_ciphertext=ciphertext,secret_nonce=nonce,key_id=settings.credential_key_id,created_at=now,updated_at=now)
        db.add(factor)
    else:
        factor.secret_ciphertext=ciphertext; factor.secret_nonce=nonce; factor.key_id=settings.credential_key_id; factor.last_used_counter=None; factor.confirmed_at=None; factor.disabled_at=None; factor.updated_at=now
    db.query(UserTotpRecoveryCode).filter_by(user_id=user.id,used_at=None).delete(synchronize_session=False)
    audit(db,"auth.totp_enrollment_started",actor_user_id=user.id,subject_user_id=user.id)
    db.commit(); _browser_capability_cache_headers(response)
    uri=totp_uri(secret=secret,email=user.email)
    return {"secret":secret,"otpauth_uri":uri,"qr_svg_data_uri":totp_qr_data_uri(uri),"algorithm":"SHA1","digits":6,"period_seconds":30}

@app.post("/api/auth/totp/confirm")
def confirm_totp(data: TotpConfirmIn,request: Request,response: Response,pair=Depends(require_csrf),db: Session=Depends(get_db)):
    sess,user=require_recent_auth(pair)
    limiter.check("totp:confirm:"+rate_key_part(client_id(request))+":"+rate_key_part(user.id),5,300)
    factor=db.get(UserTotpFactor,user.id)
    if not factor or factor.disabled_at is not None or factor.confirmed_at is not None:
        raise HTTPException(409,"Нет ожидающей настройки TOTP")
    if not consume_totp_code(db, factor=factor, secret=_totp_secret(factor), code=data.verification_code):
        raise HTTPException(422,"Неверный одноразовый код")
    now=utcnow(); factor.confirmed_at=now; factor.updated_at=now
    recovery_codes=generate_recovery_codes()
    db.query(UserTotpRecoveryCode).filter_by(user_id=user.id).delete(synchronize_session=False)
    db.add_all([UserTotpRecoveryCode(user_id=user.id,code_hash=recovery_code_hash(code),created_at=now) for code in recovery_codes])
    sess.reauthenticated_at=now
    revoke_all_owned_other_sessions(db,owner_user_id=user.id,current_session_id=sess.id,now=now)
    revoke_all_browsers(db,user_id=user.id,now=now)
    clear_trusted_device_cookie(response,settings=settings)
    audit(db,"auth.totp_enabled",actor_user_id=user.id,subject_user_id=user.id)
    db.commit(); _browser_capability_cache_headers(response)
    return {"enabled":True,"recovery_codes":recovery_codes}

@app.post("/api/auth/totp/recovery-codes")
def rotate_totp_recovery_codes(response: Response,pair=Depends(require_csrf),db: Session=Depends(get_db)):
    sess,user=require_recent_auth(pair); limiter.check("totp:recovery:rotate:"+user.id,3,3600)
    if _active_totp_factor(db,user.id) is None:
        raise HTTPException(409,"Двухфакторная защита не включена")
    now=utcnow(); codes=generate_recovery_codes()
    db.query(UserTotpRecoveryCode).filter_by(user_id=user.id).delete(synchronize_session=False)
    db.add_all([UserTotpRecoveryCode(user_id=user.id,code_hash=recovery_code_hash(code),created_at=now) for code in codes])
    revoke_all_browsers(db,user_id=user.id,now=now)
    clear_trusted_device_cookie(response,settings=settings)
    revoke_all_owned_other_sessions(db,owner_user_id=user.id,current_session_id=sess.id,now=now)
    audit(db,"auth.totp_recovery_rotated",actor_user_id=user.id,subject_user_id=user.id)
    db.commit(); _browser_capability_cache_headers(response)
    return {"recovery_codes":codes}

@app.delete("/api/auth/totp")
def disable_totp(data: TotpDisableIn,request: Request,response: Response,pair=Depends(require_csrf),db: Session=Depends(get_db)):
    sess,user=require_recent_auth(pair)
    limiter.check("totp:disable:"+rate_key_part(client_id(request))+":"+rate_key_part(user.id),5,300)
    factor=_active_totp_factor(db,user.id)
    if factor is None:
        return {"enabled":False}
    now=utcnow()
    if not _verify_second_factor(db,user=user,verification_code=data.verification_code,recovery_code=data.recovery_code,now=now):
        raise HTTPException(422,"Неверный одноразовый или резервный код")
    factor.disabled_at=now; factor.updated_at=now
    db.query(UserTotpRecoveryCode).filter_by(user_id=user.id,used_at=None).delete(synchronize_session=False)
    revoke_all_owned_other_sessions(db,owner_user_id=user.id,current_session_id=sess.id,now=now)
    revoke_all_browsers(db,user_id=user.id,now=now)
    clear_trusted_device_cookie(response,settings=settings)
    audit(db,"auth.totp_disabled",actor_user_id=user.id,subject_user_id=user.id)
    db.commit(); _browser_capability_cache_headers(response)
    return {"enabled":False}

@app.post("/api/auth/password-reset/request")
def request_password_reset(data: PasswordResetRequestIn,request: Request,response: Response,db: Session=Depends(get_db),_=Depends(require_same_origin)):
    _browser_capability_cache_headers(response)
    email=normalize_email(data.email); ip_key=rate_key_part(client_id(request)); account_key=rate_key_part(email)
    limiter.check("password-reset:request:ip:"+ip_key,5,3600)
    limiter.check("password-reset:request:account:"+account_key,3,3600)
    user=db.query(User).filter_by(email=email,status=UserStatus.active).first()
    from .security_email import request_reset_delivery
    request_reset_delivery(db, settings=settings, user=user, fingerprint=ip_key, now=utcnow())
    audit(db,"auth.password_reset_requested",subject_user_id=user.id if user else None,outcome="success")
    db.commit()
    return {"accepted":True,"delivery":"configured" if settings.security_email_configured() else "not_configured"}

@app.post("/api/auth/password-reset/confirm")
def confirm_password_reset(data: PasswordResetConfirmIn,request: Request,response: Response,db: Session=Depends(get_db),_=Depends(require_same_origin),authorization: AuthorizationProvider=Depends(get_authorization_provider)):
    _browser_capability_cache_headers(response)
    limiter.check("password-reset:confirm:ip:"+rate_key_part(client_id(request)),10,3600)
    hashed=token_hash(data.token); limiter.check("password-reset:confirm:token:"+hashed[:24],5,3600); now=utcnow()
    challenge=db.query(PasswordResetChallenge).filter_by(token_hash=hashed,used_at=None).with_for_update().first()
    if not challenge or challenge.expires_at <= now:
        raise HTTPException(422,"Ссылка сброса недействительна или устарела")
    user=db.get(User,challenge.user_id); ident=db.get(LocalIdentity,challenge.user_id)
    if not user or user.status != UserStatus.active or not ident:
        raise HTTPException(422,"Ссылка сброса недействительна или устарела")
    ident.password_hash=authorization.hash_password(data.new_password); challenge.used_at=now
    db.query(Session).filter(Session.user_id==user.id,Session.revoked_at.is_(None)).update({Session.revoked_at:now},synchronize_session=False)
    revoke_all_browsers(db,user_id=user.id,now=now)
    clear_trusted_device_cookie(response,settings=settings)
    audit(db,"auth.password_reset_completed",actor_user_id=user.id,subject_user_id=user.id)
    db.commit(); return {"ok":True}

def account_preferences_payload(user: User):
    return {
        "source_retention_ttl_seconds": effective_source_retention_seconds(user.source_retention_ttl_seconds),
        "allowed_source_retention_ttl_seconds": list(SOURCE_RETENTION_TTL_OPTIONS_SECONDS),
        "accent_color": user.accent_color,
        "allowed_accent_colors": ["blue", "violet", "teal", "rose"],
    }

@app.get("/api/account/preferences")
def account_preferences(pair=Depends(current_session)):
    _,user=pair
    return account_preferences_payload(user)

@app.patch("/api/account/preferences")
def update_account_preferences(data: AccountPreferencesPatch, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair
    limiter.check("account:preferences:"+user.id, 30, 3600)
    changed=[]
    if data.source_retention_ttl_seconds is not None and user.source_retention_ttl_seconds != data.source_retention_ttl_seconds:
        user.source_retention_ttl_seconds=data.source_retention_ttl_seconds
        changed.append("source_retention_ttl_seconds")
    if data.accent_color is not None and user.accent_color != data.accent_color:
        user.accent_color=data.accent_color
        changed.append("accent_color")
    if changed:
        user.updated_at=utcnow()
        audit(db,"account.preferences_updated",actor_user_id=user.id,subject_user_id=user.id,changed_fields=changed)
        db.commit()
    return account_preferences_payload(user)

@app.get("/api/notifications/preferences")
def get_notification_preferences(
    response: Response,
    pair=Depends(current_session),
    db: Session=Depends(get_db),
    _=Depends(require_same_origin),
):
    _,user=pair
    limiter.check("notifications:preferences:get:"+user.id,120,3600)
    _browser_capability_cache_headers(response)
    return notification_preferences_payload(db,owner_user_id=user.id,settings=settings)

@app.patch("/api/notifications/preferences")
def update_notification_preferences(
    data: NotificationPreferencesPatch,
    response: Response,
    pair=Depends(require_csrf),
    db: Session=Depends(get_db),
):
    _,user=pair
    limiter.check("notifications:preferences:update:"+user.id,30,3600)
    if data.web_push_enabled is True or data.email_enabled is True:
        raise HTTPException(410,"Для уведомлений о задачах используется только Telegram")
    from .job_notifications import telegram_owner_allowed
    if data.telegram_enabled is True and not telegram_owner_allowed(settings, user.id):
        raise HTTPException(409,"Telegram-уведомления пока не настроены администратором")
    preference=notification_preference(db,owner_user_id=user.id)
    changed=[]
    for field_name in ("web_push_enabled","email_enabled","telegram_enabled"):
        value=getattr(data,field_name)
        if value is not None and getattr(preference,field_name) != value:
            setattr(preference,field_name,value)
            changed.append(field_name)
    if changed:
        preference.updated_at=utcnow()
        audit(db,"notifications.preferences_updated",actor_user_id=user.id,subject_user_id=user.id,changed_fields=changed)
    db.commit()
    _browser_capability_cache_headers(response)
    return notification_preferences_payload(db,owner_user_id=user.id,settings=settings)

@app.post("/api/notifications/web-push/subscriptions")
def create_web_push_subscription(
    data: WebPushSubscriptionIn,
    response: Response,
    pair=Depends(require_csrf),
    db: Session=Depends(get_db),
):
    _,user=pair
    limiter.check("notifications:web-push:subscribe:"+user.id,20,3600)
    raise HTTPException(410,"Для уведомлений о задачах используется только Telegram")

@app.delete("/api/notifications/web-push/subscriptions")
def delete_web_push_subscriptions(
    response: Response,
    pair=Depends(require_csrf),
    db: Session=Depends(get_db),
):
    _,user=pair
    limiter.check("notifications:web-push:unsubscribe:"+user.id,20,3600)
    subscriptions=db.query(WebPushSubscription).filter_by(owner_user_id=user.id,revoked_at=None).all()
    for subscription in subscriptions:
        revoke_web_push_subscription(
            db,
            owner_user_id=user.id,
            subscription_id=subscription.id,
        )
    preference=notification_preference(db,owner_user_id=user.id)
    preference.web_push_enabled=False
    preference.updated_at=utcnow()
    audit(db,"notifications.web_push_unsubscribed",actor_user_id=user.id,subject_user_id=user.id,subscription_count=len(subscriptions))
    db.commit()
    _browser_capability_cache_headers(response)
    return notification_preferences_payload(db,owner_user_id=user.id,settings=settings)

@app.get("/api/auth/sessions")
def get_active_sessions(
    response: Response,
    pair=Depends(current_session),
    db: Session=Depends(get_db),
    _=Depends(require_same_origin),
):
    sess,user=pair
    limiter.check("auth:sessions:list:"+user.id, 120, 3600)
    _browser_capability_cache_headers(response)
    return list_active_sessions(
        db,
        owner_user_id=user.id,
        current_session_id=sess.id,
        now=utcnow(),
    )


@app.delete("/api/auth/sessions/{session_id}")
def revoke_active_session(
    session_id: str,
    response: Response,
    pair=Depends(require_csrf),
    db: Session=Depends(get_db),
):
    sess,user=require_recent_auth(pair)
    limiter.check("auth:sessions:revoke:"+user.id, 30, 3600)
    _browser_capability_cache_headers(response)
    if session_id == sess.id:
        raise HTTPException(
            409,
            detail={"reason": "current_session_requires_logout"},
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
    revoked=revoke_owned_other_session(
        db,
        owner_user_id=user.id,
        current_session_id=sess.id,
        target_session_id=session_id,
        now=utcnow(),
    )
    if revoked:
        audit(
            db,
            "auth.session_revoked",
            actor_user_id=user.id,
            subject_user_id=user.id,
            session_id=session_id,
            reason="owner_requested",
        )
        db.commit()
    return {"revoked": revoked, "active": False}


@app.post("/api/auth/sessions/revoke-other")
def revoke_other(
    response: Response,
    pair=Depends(require_csrf),
    db: Session=Depends(get_db),
):
    sess,user=require_recent_auth(pair)
    limiter.check("auth:sessions:revoke-other:"+user.id, 10, 3600)
    _browser_capability_cache_headers(response)
    now=utcnow()
    revoked=revoke_all_owned_other_sessions(
        db,
        owner_user_id=user.id,
        current_session_id=sess.id,
        now=now,
    )
    if revoked:
        audit(
            db,
            "auth.sessions_revoked",
            actor_user_id=user.id,
            subject_user_id=user.id,
            reason="owner_requested",
        )
        db.commit()
    return {"revoked": revoked}

def project_payload(p: Project):
    return {"id": p.id, "title": p.title, "description": p.description, "output_drive_folder_id": p.output_drive_folder_id, "output_drive_folder_url": p.output_drive_folder_url, "output_drive_folder_name": p.output_drive_folder_name, "created_at": p.created_at.isoformat(), "updated_at": p.updated_at.isoformat(), "archived_at": p.archived_at.isoformat() if p.archived_at else None}

def source_payload(s: Source):
    return {**({"prepared_audio": context} if (context := prepared_audio_context_payload(s.prepared_audio_context_json)) else {}), "id": s.id, "project_id": s.project_id, "source_type": s.source_type.value, "original_filename": s.original_filename, "mime_type": s.mime_type, "size_bytes": s.size_bytes, "drive_file_url": s.drive_file_url, "upload_status": s.upload_status.value, "uploaded_at": s.uploaded_at.isoformat() if s.uploaded_at else None, "source_created_at": s.source_created_at.isoformat() if s.source_created_at else None, "source_created_at_provenance": s.source_created_at_provenance, "expires_at": s.expires_at.isoformat() if s.expires_at else None, "deleted_at": s.deleted_at.isoformat() if s.deleted_at else None, "delete_reason": s.delete_reason, "created_at": s.created_at.isoformat(), "updated_at": s.updated_at.isoformat()}

def _completed_source_retention_seconds(source: Source, user: User) -> int:
    if source_reference_class(source) == SourceReferenceClass.audio_processing.value:
        days = source.audio_retention_days or 7
        if days not in (3, 7, 30):
            raise HTTPException(409, "Срок хранения исходника аудио не подтверждён")
        return days * 86400
    return effective_source_retention_seconds(user.source_retention_ttl_seconds)

def output_folder_favorite_payload(row: OutputFolderFavorite):
    return {"id": row.id, "drive_folder_id": row.drive_folder_id, "name": row.name, "web_view_url": row.web_view_url, "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()}

def verified_output_folder_url(folder_id: str, web_view_url: str | None) -> str:
    return web_view_url or f"https://drive.google.com/drive/folders/{folder_id}"

def clean_project_title(title: str) -> str:
    value=title.strip()
    if not value: raise HTTPException(422, "Название проекта обязательно")
    if len(value)>160: raise HTTPException(422, "Название проекта слишком длинное")
    return value

def clean_project_description(description: str|None) -> str|None:
    if description is None: return None
    value=description.strip()
    if len(value)>2000: raise HTTPException(422, "Описание проекта слишком длинное")
    return value or None

def clean_drive_id(value: str|None, label="ID Google Drive") -> str|None:
    if value is None: return None
    value=value.strip()
    if not value: return None
    if len(value)>256 or not all(ch.isalnum() or ch in "_-" for ch in value): raise HTTPException(422, f"Некорректный {label}")
    return value

def clean_drive_url(value: str|None) -> str|None:
    if value is None: return None
    value=value.strip()
    if not value: return None
    if len(value)>2000 or not (value.startswith("https://drive.google.com/") or value.startswith("https://docs.google.com/")):
        raise HTTPException(422, "Некорректная ссылка Google Drive")
    return value

def clean_optional_name(value: str|None) -> str|None:
    if value is None: return None
    value=value.strip()
    return value[:512] or None

def clean_job_title(value: str|None) -> str|None:
    if value is None: return None
    value=value.strip()
    if len(value)>160: raise HTTPException(422, "Название задания слишком длинное")
    return value or None

def clean_job_language(value: str|None) -> str|None:
    if value is None: return None
    value=value.strip().lower()
    if not value: return None
    if len(value)>40 or not all(ch.isalnum() or ch in "_-" for ch in value): raise HTTPException(422, "Некорректный язык задания")
    return value

def safe_job_options(value: dict|None) -> str|None:
    if value is None: return None
    if EXISTING_RESULT_REPROCESS_AUTHORITY_OPTION in value:
        raise HTTPException(422, "Параметры задания содержат служебное поле")
    encoded=json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(encoded)>4000: raise HTTPException(422, "Параметры задания слишком большие")
    lowered=encoded.lower()
    forbidden=("secret", "token", "api_key", "apikey", "password", "credential", "authorization", "refresh")
    if any(word in lowered for word in forbidden): raise HTTPException(422, "Параметры задания содержат недопустимые поля")
    return encoded

def job_source_payload(js: TranscriptionJobSource):
    data=source_payload(js.source)
    data.pop("drive_file_url", None)
    data["position"]=js.position
    data["job_source_status"]=js.status.value
    return data

def safe_job_output_folder_payload(job: TranscriptionJob):
    if not job.output_drive_folder_id:
        return None
    try:
        url=clean_drive_url(job.output_drive_folder_url)
    except HTTPException:
        url=None
    return {"name": clean_optional_name(job.output_drive_folder_name) or "Папка Google Drive", "web_view_url": url}

def browser_batch_reference(job: TranscriptionJob):
    key=getattr(job,"batch_idempotency_key",None)
    position=getattr(job,"batch_position",None)
    if not key or position is None:
        return None
    identity="\0".join(("studio-multi-transcription-v1",job.owner_user_id,job.project_id,key))
    digest=hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return {"id": f"multi_{digest}", "position": int(position)}

def job_payload(job: TranscriptionJob, include_sources=False):
    clip_start=getattr(job,"media_clip_start_seconds",None); clip_end=getattr(job,"media_clip_end_seconds",None)
    media_clip=None if clip_start is None and clip_end is None else {"start_seconds":clip_start,"end_seconds":clip_end}
    terminal_dismissed_at=getattr(job,"terminal_dismissed_at",None)
    attention_resolved_at=getattr(job,"history_attention_resolved_at",None)
    payload={"id": job.id, "project_id": job.project_id, "status": job.status.value, "title": job.title, "provider": job.provider, "operating_mode": getattr(job,"operating_mode","standard"), "language_mode": browser_language_mode(getattr(job, "language", None)), "diarization_enabled": job_diarization_enabled(getattr(job, "options_json", None)), "media_clip": media_clip, "terminal_dismissed_at": terminal_dismissed_at.isoformat() if terminal_dismissed_at else None, "history_attention_resolved_at": attention_resolved_at.isoformat() if attention_resolved_at else None, "history_attention_resolution": getattr(job,"history_attention_resolution",None), "history_attention_linked_job_id": getattr(job,"history_attention_linked_job_id",None), "source_count": len(job.sources), "created_at": job.created_at.isoformat(), "updated_at": job.updated_at.isoformat(), "cancelled_at": job.cancelled_at.isoformat() if job.cancelled_at else None, "cancel_requested_at": job.cancel_requested_at.isoformat() if job.cancel_requested_at else None, "attempt_count": job.attempt_count or 0, "started_at": job.started_at.isoformat() if job.started_at else None, "finished_at": job.finished_at.isoformat() if job.finished_at else None, "error_code": safe_failure_metadata_value(job.error_code), "error_message": safe_failure_metadata_value(job.error_message), "output_folder": safe_job_output_folder_payload(job), "speaker_identities": [job_speaker_payload(row) for row in sorted(getattr(job, "speakers", ()), key=lambda row: row.display_ordinal)], "usage_cost": job_usage_cost_payload(job)}
    payload["source_names"]=[entry.source.original_filename for entry in sorted(job.sources, key=lambda item: item.position)[:3]]
    batch=browser_batch_reference(job)
    if batch is not None: payload["batch"]=batch
    if include_sources: payload["sources"]=[job_source_payload(s) for s in sorted(job.sources, key=lambda item: item.position)]
    return payload

def owned_job_or_404(db: Session, user: User, job_id: str) -> TranscriptionJob:
    job=db.get(TranscriptionJob, job_id)
    if not job or job.owner_user_id!=user.id: raise HTTPException(404, "Не найдено")
    return job

def validate_job_sources(db: Session, project_id: str, source_ids: list[str], *, lock: bool=False, lock_mode: str|None=None, now: datetime|None=None) -> list[Source]:
    stmt=select(Source).where(Source.id.in_(source_ids), Source.project_id==project_id)
    if lock or lock_mode:
        stmt=stmt.order_by(Source.id.asc())
        if lock_mode == "no_key_update":
            # PostgreSQL FOR NO KEY UPDATE serializes source lifecycle UPDATE/DELETE
            # while allowing FK KEY SHARE access from concurrent job-source inserts.
            stmt=stmt.with_for_update(key_share=True)
        else:
            stmt=stmt.with_for_update()
        stmt=stmt.execution_options(populate_existing=True)
    rows=list(db.execute(stmt).scalars().all())
    by_id={r.id:r for r in rows}
    ordered=[]
    now=now or utcnow()
    for sid in source_ids:
        src=by_id.get(sid)
        if not src or src.deleted_at is not None:
            raise HTTPException(422, "Один или несколько источников недоступны для задания")
        if src.source_type in {SourceType.google_drive, SourceType.yandex_disk}:
            usable=bool(src.drive_file_id) and src.upload_status==SourceUploadStatus.uploaded
        elif src.source_type==SourceType.local_upload:
            usable=src.upload_status==SourceUploadStatus.uploaded and src.s3_object_key is not None
        else:
            usable=False
        if is_source_expired(src, now):
            usable=False
        if not usable:
            raise HTTPException(422, "Один или несколько источников недоступны для задания")
        ordered.append(src)
    return ordered

def validate_upload(mime_type: str, size_bytes: int):
    m=normalize_source_mime_type(mime_type)
    if not is_supported_source_mime_type(m): raise HTTPException(422, "Неподдерживаемый тип файла")
    if not validate_source_size(size_bytes, settings.source_max_upload_bytes): raise HTTPException(422, "Файл слишком большой")
    return m

def owned_project_or_404(db: Session, user: User, project_id: str) -> Project:
    p=db.get(Project, project_id)
    if not p or p.owner_user_id!=user.id or p.archived_at is not None: raise HTTPException(404,"Не найдено")
    return p

def _locked_owned_project_for_archive(
    db: Session,
    user: User,
    project_id: str,
) -> Project:
    project = db.execute(
        select(Project)
        .where(
            Project.id == project_id,
            Project.owner_user_id == user.id,
            Project.archived_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(404, "Не найдено")
    # Output persistence locks its job before reading the project. Archive uses
    # the same mutable boundary, so it waits for in-flight persistence without
    # granting the worker UPDATE on the read-only projects table.
    db.execute(
        select(TranscriptionJob.id)
        .where(TranscriptionJob.project_id == project.id)
        .order_by(TranscriptionJob.id)
        .with_for_update()
    ).all()
    return project

@app.get("/api/projects")
def list_projects(
    cursor: str|None=Query(None, max_length=MAX_COLLECTION_CURSOR_LENGTH),
    page_size: int=Query(DEFAULT_COLLECTION_PAGE_SIZE, ge=1, le=MAX_COLLECTION_PAGE_SIZE),
    pair=Depends(current_session),
    db: Session=Depends(get_db),
):
    sess,user=pair
    try:
        position=decode_collection_cursor(cursor, secret=sess.csrf_hash, owner_user_id=user.id, surface="projects")
    except CollectionCursorError:
        raise HTTPException(422, "Invalid projects cursor") from None
    query=db.query(Project).filter(Project.owner_user_id==user.id, Project.archived_at.is_(None))
    if position:
        updated_at,row_id=position
        query=query.filter((Project.updated_at < updated_at) | ((Project.updated_at == updated_at) & (Project.id < row_id)))
    rows=query.order_by(Project.updated_at.desc(), Project.id.desc()).limit(page_size+1).all()
    rows,next_cursor=page_envelope(rows, page_size=page_size, timestamp_attribute="updated_at", secret=sess.csrf_hash, owner_user_id=user.id, surface="projects")
    return {"projects":[project_payload(p) for p in rows], "next_cursor": next_cursor, "page_size": page_size}

@app.post("/api/transcriptions/workspace")
def ensure_transcription_workspace(
    pair=Depends(require_csrf),
    db: Session=Depends(get_db),
):
    _, user = pair
    limiter.check("transcription:workspace:ensure:" + user.id, 30, 3600)
    db.execute(select(User).where(User.id == user.id).with_for_update()).scalar_one()
    project = db.execute(
        select(Project)
        .where(
            Project.owner_user_id == user.id,
            Project.archived_at.is_(None),
        )
        .order_by(Project.updated_at.desc(), Project.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    created = project is None
    if project is None:
        project = Project(
            owner_user_id=user.id,
            title="Транскрибации",
            description=None,
        )
        db.add(project)
        db.flush()
        audit(
            db,
            "transcription_workspace.created",
            actor_user_id=user.id,
            subject_user_id=user.id,
        )
    db.commit()
    return {"project": project_payload(project), "created": created}

@app.post("/api/projects")
def create_project(data: ProjectIn, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("project:create:"+user.id, 60, 3600)
    p=Project(owner_user_id=user.id, title=clean_project_title(data.title), description=clean_project_description(data.description))
    db.add(p); db.flush(); audit(db,"project.created",actor_user_id=user.id,subject_user_id=user.id); db.commit(); return project_payload(p)

@app.patch("/api/projects/{project_id}")
def update_project(project_id: str, data: ProjectPatch, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("project:update:"+user.id, 120, 3600); p=owned_project_or_404(db,user,project_id)
    if data.title is not None: p.title=clean_project_title(data.title)
    if data.description is not None: p.description=clean_project_description(data.description)
    p.updated_at=utcnow(); audit(db,"project.updated",actor_user_id=user.id,subject_user_id=user.id); db.commit(); return project_payload(p)

@app.post("/api/projects/{project_id}/archive")
def archive_project(project_id: str, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("project:archive:"+user.id, 120, 3600); p=_locked_owned_project_for_archive(db,user,project_id)
    now=utcnow(); p.archived_at=now; p.updated_at=now; audit(db,"project.archived",actor_user_id=user.id,subject_user_id=user.id); db.commit(); return {"ok": True}



def owned_source_or_404(db: Session, user: User, source_id: str) -> Source:
    src=db.get(Source, source_id)
    if not src: raise HTTPException(404,"Не найдено")
    p=db.get(Project, src.project_id)
    if not p or p.owner_user_id!=user.id or p.archived_at is not None: raise HTTPException(404,"Не найдено")
    return src

@app.get("/api/projects/{project_id}/sources")
def list_sources(
    project_id: str,
    cursor: str|None=Query(None, max_length=MAX_COLLECTION_CURSOR_LENGTH),
    page_size: int=Query(DEFAULT_COLLECTION_PAGE_SIZE, ge=1, le=MAX_COLLECTION_PAGE_SIZE),
    pair=Depends(current_session),
    db: Session=Depends(get_db),
):
    sess,user=pair; p=owned_project_or_404(db,user,project_id)
    scope={"project_id": p.id}
    try:
        position=decode_collection_cursor(cursor, secret=sess.csrf_hash, owner_user_id=user.id, surface="sources", scope=scope)
    except CollectionCursorError:
        raise HTTPException(422, "Invalid sources cursor") from None
    now=utcnow()
    query=db.query(Source).filter(
        Source.project_id==p.id,
        Source.deleted_at.is_(None),
        or_(
            Source.source_type!=SourceType.local_upload,
            and_(
                Source.upload_status!=SourceUploadStatus.expired,
                or_(Source.expires_at.is_(None), Source.expires_at>now),
            ),
        ),
    )
    if position:
        created_at,row_id=position
        query=query.filter((Source.created_at < created_at) | ((Source.created_at == created_at) & (Source.id < row_id)))
    rows=query.order_by(Source.created_at.desc(), Source.id.desc()).limit(page_size+1).all()
    rows,next_cursor=page_envelope(rows, page_size=page_size, timestamp_attribute="created_at", secret=sess.csrf_hash, owner_user_id=user.id, surface="sources", scope=scope)
    return {"sources":[source_payload(r) for r in rows], "next_cursor": next_cursor, "page_size": page_size}
def _browser_capability_cache_headers(response: Response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"

@app.get("/api/sources/upload-policy")
def get_source_upload_policy(response: Response, pair=Depends(current_session)):
    _browser_capability_cache_headers(response)
    policy=browser_source_upload_policy(
        settings.source_max_upload_bytes,
        local_upload_enabled=reference_storage_isolation_configured(settings),
        multipart_threshold_bytes=settings.source_multipart_threshold_bytes,
        multipart_part_size_bytes=settings.source_multipart_part_size_bytes,
    )
    return {
        **policy,
        "media_duration_warning_seconds":settings.media_duration_warning_seconds,
        "media_max_duration_seconds":settings.media_max_duration_seconds,
    }


@app.get("/api/storage/lifecycle")
def get_storage_lifecycle(response: Response, pair=Depends(current_session)):
    _,user=pair; _browser_capability_cache_headers(response)
    return storage_lifecycle_payload(user,settings)


@app.post("/api/storage/reconciliation/preview")
def preview_storage_reconciliation(response: Response, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    sess,user=pair; limiter.check("storage:reconciliation:preview:"+user.id,30,3600); _browser_capability_cache_headers(response)
    now=utcnow()
    try:
        scan=scan_owner_storage(db,owner_user_id=user.id,settings=settings,now=now)
    except StorageReconciliationError as exc:
        raise HTTPException(503,"Проверка хранилища временно недоступна") from exc
    except Exception as exc:
        raise HTTPException(503,"Проверка хранилища временно недоступна") from exc
    token,expires_at=issue_reconciliation_plan(owner_user_id=user.id,scan=scan,secret=sess.token_hash,now=now,ttl_seconds=settings.storage_reconciliation_plan_ttl_seconds)
    return {
        "status":"truncated" if scan.truncated else "ready",
        "scanned_count":scan.scanned_count,
        "protected_recent_count":scan.protected_recent_count,
        "orphan_count":len(scan.candidates),
        "orphan_bytes":scan.candidate_bytes,
        "plan_token":token,
        "plan_expires_at":expires_at.isoformat() if expires_at else None,
        "apply_available":bool(token is not None and len(scan.candidates) <= settings.storage_reconciliation_apply_limit),
    }


@app.post("/api/storage/reconciliation/apply")
def apply_storage_reconciliation(data: StorageReconciliationApplyIn, request: Request, response: Response, pair=Depends(require_csrf), db: Session=Depends(get_db), _=Depends(require_same_origin)):
    sess,user=pair; limiter.check("storage:reconciliation:apply:"+user.id,10,3600); _browser_capability_cache_headers(response)
    now=utcnow()
    try:
        result=apply_reconciliation_plan(db,owner_user_id=user.id,plan_token=data.plan_token,secret=sess.token_hash,settings=settings,now=now)
    except StorageReconciliationError as exc:
        status_code=409 if exc.reason in {StorageReconciliationReason.plan_changed,StorageReconciliationReason.plan_invalid,StorageReconciliationReason.scan_truncated} else 503
        raise HTTPException(status_code,"План проверки изменился; выполните dry-run заново") from exc
    except Exception as exc:
        raise HTTPException(503,"Очистку хранилища не удалось подтвердить") from exc
    audit(db,"storage.reconciliation_applied",actor_user_id=user.id,subject_user_id=user.id,outcome="success" if result.failed_count == 0 else "partial",planned_count=result.planned_count,deleted_count=result.deleted_count,failed_count=result.failed_count,deleted_bytes=result.deleted_bytes)
    write_diagnostic_event(owner_user_id=user.id,component="api",event_code="STORAGE_RECONCILIATION_APPLIED",request_id=getattr(request.state,"request_id",None),correlation_id=getattr(request.state,"correlation_id",None),metadata={"planned_count":result.planned_count,"deleted_count":result.deleted_count,"failed_count":result.failed_count,"deleted_bytes":result.deleted_bytes,"boundary":"storage_reconciliation"})
    db.commit()
    return {"status":"completed" if result.failed_count == 0 else "partial","planned_count":result.planned_count,"deleted_count":result.deleted_count,"failed_count":result.failed_count,"deleted_bytes":result.deleted_bytes}

def _raise_google_picker_session_failure(
    request: Request,
    user: User,
    *,
    reason: str,
    status_code: int,
    retryable: bool,
) -> None:
    write_diagnostic_event(
        owner_user_id=user.id,
        component="api",
        event_code="GOOGLE_PICKER_SESSION_FAILED",
        request_id=getattr(request.state, "request_id", None),
        correlation_id=getattr(request.state, "correlation_id", None),
        metadata={
            "reason": reason,
            "retryable": retryable,
            "http_status_category": f"{status_code // 100}xx",
        },
    )
    raise HTTPException(status_code, reason)


@app.post("/api/google/picker/session")
def create_google_picker_session(request: Request, response: Response, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("google:picker:session:"+user.id, 30, 300); _browser_capability_cache_headers(response)
    if not settings.google_picker_configured():
        _raise_google_picker_session_failure(
            request,
            user,
            reason="google_picker_not_configured",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            retryable=False,
        )
    try:
        conn=active_google_connection_for_user(db, user_id=user.id)
        require_picker_browser_scope_boundary(conn)
        access_token=get_cloud_files_provider().access_token(db, user_id=user.id, settings=settings)
    except GoogleConnectionAccessError as exc:
        status_code, retryable = {
            GoogleConnectionAccessReason.missing: (404, False),
            GoogleConnectionAccessReason.inactive: (409, False),
            GoogleConnectionAccessReason.reauthorization_required: (409, False),
            GoogleConnectionAccessReason.scope_unavailable: (409, False),
            GoogleConnectionAccessReason.config_unavailable: (
                status.HTTP_503_SERVICE_UNAVAILABLE,
                False,
            ),
            GoogleConnectionAccessReason.token_unavailable: (502, True),
        }[exc.reason]
        _raise_google_picker_session_failure(
            request,
            user,
            reason=exc.reason.value,
            status_code=status_code,
            retryable=retryable,
        )
    return {"access_token": access_token, "api_key": settings.google_picker_api_key.strip(), "app_id": settings.google_picker_app_id.strip(), "scope_ready": True}

def _validated_drive_metadata_for_picker(db: Session, user: User, drive_id: str, *, access_token: str | None = None):
    from .google_drive import GoogleDriveMetadataError, fetch_drive_file_metadata
    clean_id=clean_drive_id(drive_id, "ID Google Drive")
    if not clean_id: raise HTTPException(422, "Некорректный ID Google Drive")
    try:
        access_token=access_token or refreshed_google_drive_access_token(db, user)
        meta=get_cloud_files_provider().metadata(access_token, clean_id)
        if not isinstance(meta.id, str) or meta.id.strip() != clean_id:
            raise HTTPException(502, "Google Drive metadata is unavailable")
        return meta
    except HTTPException:
        raise
    except GoogleDriveMetadataError:
        raise HTTPException(422, "Выбранный ресурс Google Drive недоступен")
    except Exception:
        raise HTTPException(502, "Google Drive metadata is unavailable")

def _validated_google_drive_source_metadata(db: Session, user: User, drive_id: str, *, access_token: str | None = None):
    meta=(_validated_drive_metadata_for_picker(db, user, drive_id) if access_token is None
          else _validated_drive_metadata_for_picker(db, user, drive_id, access_token=access_token))
    if meta.is_folder:
        raise HTTPException(422, "Папки Google Drive нельзя добавить как source")
    mime=normalize_source_mime_type(meta.mime_type or "")
    if not is_supported_source_mime_type(mime):
        raise HTTPException(422, "Неподдерживаемый тип файла")
    if meta.size_bytes is not None and not validate_source_size(meta.size_bytes, settings.source_max_upload_bytes):
        raise HTTPException(422, "Файл слишком большой")
    return meta,mime

def _new_google_drive_source(project_id: str, meta, mime: str, uploaded_at: datetime) -> Source:
    source_created_at=parse_authoritative_source_created_at(meta.created_time)
    if source_created_at is None:
        raise HTTPException(502, "Google Drive creation time is unavailable")
    return Source(project_id=project_id, source_type=SourceType.google_drive, original_filename=normalize_source_display_filename(meta.name or f"Google Drive source {meta.id}"), mime_type=mime, size_bytes=meta.size_bytes, drive_file_id=clean_drive_id(meta.id, "ID файла Google Drive"), drive_file_url=clean_drive_url(meta.web_view_link), upload_status=SourceUploadStatus.uploaded, uploaded_at=uploaded_at, source_created_at=source_created_at, source_created_at_provenance="google_drive_created_time", storage_cleanup_status=SourceStorageCleanupStatus.not_applicable)

def _inspect_google_drive_source_folder(db: Session, user: User, folder_id: str):
    from .google_drive_folder_intake import (
        DriveFolderIntakeError,
        DriveFolderIntakeReason,
        inspect_drive_source_folder,
    )
    clean_id=clean_drive_id(folder_id, "ID папки Google Drive")
    if not clean_id:
        raise HTTPException(422, "Некорректный ID папки Google Drive")
    try:
        conn=active_google_connection_for_user(db, user_id=user.id)
        require_drive_readonly_scope(conn)
        access_token=refreshed_google_drive_access_token(db, user)
        return inspect_drive_source_folder(
            access_token,
            clean_id,
            max_upload_bytes=settings.source_max_upload_bytes,
        )
    except GoogleConnectionAccessError as exc:
        if exc.reason == GoogleConnectionAccessReason.missing:
            raise HTTPException(404, exc.reason.value) from exc
        if exc.reason in {
            GoogleConnectionAccessReason.inactive,
            GoogleConnectionAccessReason.reauthorization_required,
            GoogleConnectionAccessReason.scope_unavailable,
        }:
            raise HTTPException(409, exc.reason.value) from exc
        if exc.reason == GoogleConnectionAccessReason.config_unavailable:
            raise HTTPException(503, exc.reason.value) from exc
        raise HTTPException(502, exc.reason.value) from exc
    except HTTPException:
        raise
    except DriveFolderIntakeError as exc:
        if exc.reason == DriveFolderIntakeReason.root_not_folder:
            raise HTTPException(422, "google_drive_source_folder_required") from exc
        if exc.reason == DriveFolderIntakeReason.unavailable:
            raise HTTPException(502, "google_drive_folder_unavailable") from exc
        raise HTTPException(409, f"google_drive_folder_{exc.reason.value}") from exc
    except Exception as exc:
        raise HTTPException(502, "google_drive_folder_unavailable") from exc

def _google_drive_folder_preview_payload(preview, *, owner_user_id: str, project_id: str):
    from .google_drive_folder_intake import drive_folder_preview_token
    token=(
        drive_folder_preview_token(
            preview,
            owner_user_id=owner_user_id,
            project_id=project_id,
        )
        if preview.complete and preview.blocker is None
        else None
    )
    return {
        "folder": {"id": preview.folder_id, "name": preview.folder_name},
        "total_file_count": preview.total_file_count,
        "folder_count": preview.folder_count,
        "supported_count": preview.supported_count,
        "skipped_count": len(preview.skipped),
        "accepted": [
            {
                "id": item.metadata.id,
                "name": item.metadata.name or "Файл Google Drive",
                "mime_type": item.mime_type,
                "size_bytes": item.metadata.size_bytes,
                "created_time": item.metadata.created_time,
                "relative_path": item.relative_path,
            }
            for item in preview.accepted
        ],
        "skipped": [
            {
                "relative_path": item.relative_path,
                "reason": item.reason.value,
            }
            for item in preview.skipped
        ],
        "blocker": preview.blocker,
        "complete": preview.complete,
        "preview_token": token,
    }

@app.post("/api/projects/{project_id}/sources/google-picker")
def create_google_picker_sources(project_id: str, data: GooglePickerSourceSelectionIn, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("source:gpicker:create:"+user.id, 60, 3600); p=owned_project_or_404(db,user,project_id)
    metas=[]
    for raw_id in data.file_ids:
        metas.append(_validated_google_drive_source_metadata(db, user, raw_id))
    now=utcnow(); created=[]
    try:
        for meta,mime in metas:
            src=_new_google_drive_source(p.id, meta, mime, now)
            db.add(src); created.append(src)
        audit(db,"source.google_picker.created",actor_user_id=user.id,subject_user_id=user.id,project_id=p.id,source_count=len(created)); db.commit()
    except Exception:
        db.rollback(); raise
    return {"sources":[source_payload(src) for src in created]}

@app.post("/api/projects/{project_id}/sources/google-folder/preview")
def preview_google_drive_source_folder(project_id: str, data: GoogleDriveFolderPreviewIn, response: Response, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("source:gfolder:preview:"+user.id, 120, 3600); p=owned_project_or_404(db,user,project_id)
    preview=_inspect_google_drive_source_folder(db, user, data.folder_id)
    response.headers["Cache-Control"]="no-store"
    response.headers["Pragma"]="no-cache"
    return _google_drive_folder_preview_payload(preview, owner_user_id=user.id, project_id=p.id)

@app.post("/api/projects/{project_id}/sources/google-folder/apply")
def apply_google_drive_source_folder(project_id: str, data: GoogleDriveFolderApplyIn, response: Response, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    from .google_drive_folder_intake import drive_folder_preview_token
    _,user=pair; limiter.check("source:gfolder:apply:"+user.id, 30, 3600); p=owned_project_or_404(db,user,project_id)
    preview=_inspect_google_drive_source_folder(db, user, data.folder_id)
    if preview.blocker == "over_limit":
        raise HTTPException(422, "google_drive_folder_over_limit")
    if preview.blocker == "empty" or not preview.accepted:
        raise HTTPException(422, "google_drive_folder_empty")
    actual_token=drive_folder_preview_token(preview, owner_user_id=user.id, project_id=p.id)
    if not safe_eq(actual_token, data.preview_token):
        raise HTTPException(409, "google_drive_folder_changed")
    now=utcnow(); created=[]
    try:
        for item in preview.accepted:
            src=_new_google_drive_source(p.id, item.metadata, item.mime_type, now)
            db.add(src); created.append(src)
        audit(db,"source.google_folder.created",actor_user_id=user.id,subject_user_id=user.id,project_id=p.id,source_count=len(created)); db.commit()
        for src in created: db.refresh(src)
    except Exception:
        db.rollback(); raise
    response.headers["Cache-Control"]="no-store"
    response.headers["Pragma"]="no-cache"
    return {"sources":[source_payload(src) for src in created]}

@app.post("/api/projects/{project_id}/output-folder/google-picker")
def set_google_picker_output_folder(project_id: str, data: GooglePickerOutputFolderIn, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("project:gpicker:folder:"+user.id, 60, 3600); p=owned_project_or_404(db,user,project_id)
    access_token=refreshed_google_drive_access_token(db, user)
    verified=verify_output_folder_selection(access_token, data.folder_id)
    p.output_drive_folder_id=verified.id
    p.output_drive_folder_url=verified.web_view_url
    p.output_drive_folder_name=verified.name
    p.updated_at=utcnow(); audit(db,"project.output_folder.google_picker_set",actor_user_id=user.id,subject_user_id=user.id,project_id=p.id); db.commit(); db.refresh(p)
    return project_payload(p)


@app.post("/api/projects/{project_id}/output-folders/google-picker/verify")
def verify_google_picker_output_folder(project_id: str, data: GooglePickerOutputFolderIn, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("project:gpicker:folder:verify:"+user.id, 120, 3600); owned_project_or_404(db,user,project_id)
    access_token=refreshed_google_drive_access_token(db, user)
    verified=verify_output_folder_selection(access_token, data.folder_id)
    return {"name": verified.name or "Папка Google Drive", "web_view_url": verified.web_view_url}


def _direct_drive_upload_access_token(db: Session, user: User) -> str:
    try:
        connection=active_google_connection_for_user(db, user_id=user.id)
        require_drive_file_scope(connection)
        require_picker_browser_scope_boundary(connection)
        return get_cloud_files_provider().access_token(
            db, user_id=user.id, settings=settings
        )
    except GoogleConnectionAccessError as exc:
        status_code={
            GoogleConnectionAccessReason.missing: 404,
            GoogleConnectionAccessReason.inactive: 409,
            GoogleConnectionAccessReason.reauthorization_required: 409,
            GoogleConnectionAccessReason.scope_unavailable: 409,
            GoogleConnectionAccessReason.config_unavailable: status.HTTP_503_SERVICE_UNAVAILABLE,
            GoogleConnectionAccessReason.token_unavailable: 502,
        }[exc.reason]
        raise HTTPException(status_code, exc.reason.value) from None


def _direct_drive_upload_descriptors(
    files: list[DirectDriveUploadFileIn],
):
    try:
        descriptors=[
            normalize_direct_drive_upload_descriptor(
                item.operation_id,
                item.original_filename,
                item.mime_type,
                item.size_bytes,
                max_file_bytes=settings.source_max_upload_bytes,
            )
            for item in files
        ]
        validate_direct_drive_upload_batch(descriptors)
        return descriptors
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@app.post("/api/projects/{project_id}/direct-drive-uploads/session")
def create_direct_drive_upload_session(
    project_id: str,
    data: DirectDriveUploadSessionIn,
    response: Response,
    pair=Depends(require_csrf),
    db: Session=Depends(get_db),
):
    sess,user=pair
    limiter.check("audio:direct-drive:session:"+user.id, 30, 300)
    _browser_capability_cache_headers(response)
    project=owned_project_or_404(db,user,project_id)
    descriptors=_direct_drive_upload_descriptors(data.files)
    access_token=_direct_drive_upload_access_token(db,user)
    verified=verify_output_folder_selection(access_token,data.folder_id)
    capabilities=[
        {
            "operation_id": descriptor.operation_id,
            "capability": encode_direct_drive_upload_capability(
                descriptor,
                owner_user_id=user.id,
                project_id=project.id,
                folder_id=verified.id,
                secret=sess.csrf_hash,
                now=utcnow(),
            ),
        }
        for descriptor in descriptors
    ]
    return {
        "access_token": access_token,
        "expires_in": DIRECT_DRIVE_UPLOAD_CAPABILITY_SECONDS,
        "folder": {"name": verified.name or "Папка Google Drive"},
        "policy": direct_drive_upload_policy(settings.source_max_upload_bytes),
        "uploads": capabilities,
    }


@app.post("/api/projects/{project_id}/direct-drive-uploads/complete")
def complete_direct_drive_upload(
    project_id: str,
    data: DirectDriveUploadCompleteIn,
    response: Response,
    pair=Depends(require_csrf),
    db: Session=Depends(get_db),
):
    sess,user=pair
    limiter.check("audio:direct-drive:complete:"+user.id, 120, 3600)
    _browser_capability_cache_headers(response)
    project=owned_project_or_404(db,user,project_id)
    descriptor=_direct_drive_upload_descriptors([data])[0]
    capability=decode_direct_drive_upload_capability(
        data.capability,
        secret=sess.csrf_hash,
        now=utcnow(),
    )
    if (
        capability is None
        or capability.owner_user_id != user.id
        or capability.project_id != project.id
        or capability.folder_id != data.folder_id
        or capability.operation_id != descriptor.operation_id
        or not safe_eq(
            capability.descriptor_digest,
            direct_drive_upload_descriptor_digest(descriptor),
        )
    ):
        raise HTTPException(409,"direct_drive_upload_capability_invalid")
    access_token=_direct_drive_upload_access_token(db,user)
    verify_output_folder_selection(access_token,capability.folder_id)
    try:
        result=verify_direct_drive_upload_result(
            access_token,
            file_id=data.file_id,
            folder_id=capability.folder_id,
            descriptor=descriptor,
        )
    except DirectDriveUploadError as exc:
        if exc.reason == DirectDriveUploadReason.not_found:
            raise HTTPException(409,"direct_drive_upload_result_not_found") from None
        if exc.reason == DirectDriveUploadReason.metadata_mismatch:
            raise HTTPException(409,"direct_drive_upload_metadata_mismatch") from None
        if exc.reason == DirectDriveUploadReason.authentication_rejected:
            raise HTTPException(409,"google_reauthorization_required") from None
        raise HTTPException(502,"direct_drive_upload_verification_unavailable") from None
    audit(
        db,
        "audio.direct_drive_upload.verified",
        actor_user_id=user.id,
        subject_user_id=user.id,
        project_id=project.id,
    )
    db.commit()
    return {
        "name": result.name,
        "mime_type": result.mime_type,
        "size_bytes": result.size_bytes,
        "web_view_url": result.web_view_url,
    }

@app.get("/api/output-folder-favorites")
def list_output_folder_favorites(pair=Depends(current_session), db: Session=Depends(get_db)):
    _,user=pair
    rows=db.query(OutputFolderFavorite).filter(OutputFolderFavorite.owner_user_id==user.id).order_by(OutputFolderFavorite.updated_at.desc(), OutputFolderFavorite.id.asc()).all()
    return {"favorites":[output_folder_favorite_payload(row) for row in rows]}

@app.post("/api/output-folder-favorites/google-picker")
def save_output_folder_favorite(data: GooglePickerOutputFolderIn, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("output-folder-favorite:save:"+user.id, 120, 3600)
    access_token=refreshed_google_drive_access_token(db, user)
    verified=verify_output_folder_selection(access_token, data.folder_id)
    favorite_url=verified_output_folder_url(verified.id, verified.web_view_url)
    row=db.query(OutputFolderFavorite).filter(OutputFolderFavorite.owner_user_id==user.id, OutputFolderFavorite.drive_folder_id==verified.id).one_or_none()
    now=utcnow()
    if row is None:
        row=OutputFolderFavorite(owner_user_id=user.id, drive_folder_id=verified.id, name=verified.name or "Папка Google Drive", web_view_url=favorite_url, created_at=now, updated_at=now)
        db.add(row)
        event_type="output_folder_favorite.created"
    else:
        row.name=verified.name or "Папка Google Drive"
        row.web_view_url=favorite_url
        row.updated_at=now
        event_type="output_folder_favorite.refreshed"
    audit(db,event_type,actor_user_id=user.id,subject_user_id=user.id)
    db.commit(); db.refresh(row)
    return output_folder_favorite_payload(row)

@app.delete("/api/output-folder-favorites/{favorite_id}")
def delete_output_folder_favorite(favorite_id: str, pair=Depends(require_csrf), db: Session=Depends(get_db), _=Depends(require_same_origin)):
    _,user=pair; limiter.check("output-folder-favorite:delete:"+user.id, 120, 3600)
    row=db.query(OutputFolderFavorite).filter(OutputFolderFavorite.id==favorite_id, OutputFolderFavorite.owner_user_id==user.id).one_or_none()
    if row is None:
        raise HTTPException(404, "Не найдено")
    db.delete(row)
    audit(db,"output_folder_favorite.deleted",actor_user_id=user.id,subject_user_id=user.id)
    db.commit()
    return {"ok": True}


def _clean_speaker_profile_values(display_name: str, role: str) -> tuple[str, str, str]:
    try:
        clean_name, normalized_name = normalize_profile_name(display_name)
        clean_role = normalize_profile_role(role)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return clean_name, normalized_name, clean_role


@app.get("/api/speaker-profiles")
def list_speaker_profiles(pair=Depends(current_session), db: Session=Depends(get_db)):
    _,user=pair
    rows=(
        db.query(SpeakerProfile)
        .filter(SpeakerProfile.owner_user_id==user.id, SpeakerProfile.active.is_(True))
        .order_by(SpeakerProfile.display_name.asc(), SpeakerProfile.id.asc())
        .all()
    )
    return {"profiles":[speaker_profile_payload(row) for row in rows]}


@app.post("/api/speaker-profiles")
def create_speaker_profile(data: SpeakerProfileIn, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("speaker-profile:create:"+user.id, 120, 3600)
    display_name,normalized_name,role=_clean_speaker_profile_values(data.display_name,data.role)
    row=(
        db.query(SpeakerProfile)
        .filter(SpeakerProfile.owner_user_id==user.id, SpeakerProfile.normalized_name==normalized_name)
        .one_or_none()
    )
    now=utcnow()
    if row is None:
        row=SpeakerProfile(owner_user_id=user.id,display_name=display_name,normalized_name=normalized_name,role=role,active=True,created_at=now,updated_at=now)
        db.add(row)
        event_type="speaker_profile.created"
    elif row.active:
        raise HTTPException(409,"Профиль спикера с таким именем уже существует")
    else:
        row.display_name=display_name; row.role=role; row.active=True; row.updated_at=now
        event_type="speaker_profile.reactivated"
    try:
        db.flush()
    except IntegrityError:
        db.rollback(); raise HTTPException(409,"Профиль спикера с таким именем уже существует") from None
    audit(db,event_type,actor_user_id=user.id,subject_user_id=user.id)
    db.commit(); db.refresh(row)
    return speaker_profile_payload(row)


@app.patch("/api/speaker-profiles/{profile_id}")
def update_speaker_profile(profile_id: str, data: SpeakerProfilePatch, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("speaker-profile:update:"+user.id, 240, 3600)
    row=(
        db.query(SpeakerProfile)
        .filter(SpeakerProfile.id==profile_id,SpeakerProfile.owner_user_id==user.id,SpeakerProfile.active.is_(True))
        .one_or_none()
    )
    if row is None:
        raise HTTPException(404,"Не найдено")
    display_name=data.display_name if data.display_name is not None else row.display_name
    role=data.role if data.role is not None else row.role
    display_name,normalized_name,role=_clean_speaker_profile_values(display_name,role)
    row.display_name=display_name; row.normalized_name=normalized_name; row.role=role; row.updated_at=utcnow()
    try:
        db.flush()
    except IntegrityError:
        db.rollback(); raise HTTPException(409,"Профиль спикера с таким именем уже существует") from None
    audit(db,"speaker_profile.updated",actor_user_id=user.id,subject_user_id=user.id)
    db.commit(); db.refresh(row)
    return speaker_profile_payload(row)


@app.delete("/api/speaker-profiles/{profile_id}")
def deactivate_speaker_profile(profile_id: str, pair=Depends(require_csrf), db: Session=Depends(get_db), _=Depends(require_same_origin)):
    _,user=pair; limiter.check("speaker-profile:delete:"+user.id, 120, 3600)
    row=(
        db.query(SpeakerProfile)
        .filter(SpeakerProfile.id==profile_id,SpeakerProfile.owner_user_id==user.id,SpeakerProfile.active.is_(True))
        .one_or_none()
    )
    if row is None:
        raise HTTPException(404,"Не найдено")
    row.active=False; row.updated_at=utcnow()
    audit(db,"speaker_profile.deactivated",actor_user_id=user.id,subject_user_id=user.id)
    db.commit()
    return {"ok":True}

_IDEMPOTENCY_RE=re.compile(r"^[A-Za-z0-9_.-]{8,128}$")
def _clean_idempotency_key(value: str|None) -> str:
    key=(value or "").strip()
    if not _IDEMPOTENCY_RE.fullmatch(key):
        raise HTTPException(422, "Некорректный Idempotency-Key")
    return key

def _load_existing_batch(db, user_id, project_id, key):
    return db.query(TranscriptionJob).filter(TranscriptionJob.owner_user_id==user_id, TranscriptionJob.project_id==project_id, TranscriptionJob.batch_idempotency_key==key).order_by(TranscriptionJob.batch_position.asc(), TranscriptionJob.id.asc()).all()

def _batch_hash(project_id, provider_credential_id, language, options_json, items, *, provider="elevenlabs", operating_mode="standard"):
    canonical={"project_id":project_id,"provider_credential_id":provider_credential_id,"provider":provider,"operating_mode":operating_mode,"language":language,"options":json.loads(options_json) if options_json else None,"items":items}
    return hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _provider_label(provider: str | SttProvider | CredentialProvider) -> str:
    value=getattr(provider,"value",provider)
    return "Yandex SpeechKit" if value == "yandex" else "ElevenLabs"


def _resolve_active_stt_credential_id(
    db,
    user,
    requested_credential_id,
    provider: str | SttProvider,
    operating_mode: str | SttOperatingMode = SttOperatingMode.standard,
) -> str:
    provider_value=SttProvider(getattr(provider,"value",provider))
    try:
        resolve_capability(settings,provider_value,operating_mode)
    except SttCapabilityError as exc:
        raise HTTPException(422,detail={"reason":exc.reason.value}) from None
    credential_provider=CredentialProvider(provider_value.value)
    label=_provider_label(provider_value)
    requested = requested_credential_id.strip() if isinstance(requested_credential_id, str) and requested_credential_id.strip() else None
    if requested:
        credential = db.get(ProviderCredential, requested)
        if (
            not credential
            or credential.user_id != user.id
            or credential.provider != credential_provider
            or credential.status != CredentialStatus.active
            or credential.deleted_at is not None
        ):
            raise HTTPException(422, f"Выберите активный профиль {label}.")
        return credential.id
    credentials = db.query(ProviderCredential).filter(
        ProviderCredential.user_id == user.id,
        ProviderCredential.provider == credential_provider,
        ProviderCredential.status == CredentialStatus.active,
        ProviderCredential.deleted_at.is_(None),
    ).all()
    if len(credentials) == 1:
        return credentials[0].id
    if len(credentials) == 0:
        raise HTTPException(422, f"Добавьте активный ключ {label} в настройках.")
    raise HTTPException(422, f"Выберите профиль подключения {label}.")


def _resolve_active_elevenlabs_credential_id(db, user, requested_credential_id) -> str:
    return _resolve_active_stt_credential_id(db,user,requested_credential_id,SttProvider.elevenlabs)

def _open_active_stt_api_key(
    db: Session,
    user: User,
    credential_id: str,
    provider: str | SttProvider,
) -> str:
    provider_value=SttProvider(getattr(provider,"value",provider))
    credential_provider=CredentialProvider(provider_value.value)
    label=_provider_label(provider_value)
    credential = db.get(ProviderCredential, credential_id)
    if (
        not credential
        or credential.user_id != user.id
        or credential.provider != credential_provider
        or credential.status != CredentialStatus.active
        or credential.deleted_at is not None
        or not credential.active_version_id
    ):
        raise HTTPException(422, f"Выберите активный профиль {label}.")
    version = db.get(ProviderCredentialVersion, credential.active_version_id)
    if (
        not version
        or version.credential_id != credential.id
        or version.revoked_at is not None
        or version.deleted_at is not None
        or version.ciphertext is None
        or version.nonce is None
        or version.key_id != settings.credential_key_id
    ):
        raise HTTPException(503, f"Профиль {label} временно недоступен.")
    try:
        return decrypt(
            version.ciphertext,
            version.nonce,
            master_key_from_b64(settings.master_key_b64()),
            aad(user.id, credential.id, version.id, credential.provider.value),
        )
    except Exception as exc:
        raise HTTPException(
            503,
            f"Профиль {label} временно недоступен.",
        ) from exc


def _open_active_elevenlabs_api_key(db: Session,user: User,credential_id: str) -> str:
    return _open_active_stt_api_key(db,user,credential_id,SttProvider.elevenlabs)

def _raise_realtime_capability_failure(
    request: Request,
    user: User,
    *,
    reason: RealtimeCapabilityReason,
) -> None:
    status_code, retryable = {
        RealtimeCapabilityReason.provider_authentication_rejected: (422, False),
        RealtimeCapabilityReason.provider_request_rejected: (422, False),
        RealtimeCapabilityReason.provider_rate_limited: (429, True),
        RealtimeCapabilityReason.provider_timeout: (504, True),
        RealtimeCapabilityReason.provider_unavailable: (502, True),
        RealtimeCapabilityReason.malformed_provider_response: (502, True),
    }[reason]
    _write_realtime_diagnostic_event(
        request,
        user,
        event_code="REALTIME_CAPABILITY_FAILED",
        metadata={
            "reason": reason.value,
            "retryable": retryable,
            "http_status_category": f"{status_code // 100}xx",
        },
    )
    raise HTTPException(status_code, {"reason": reason.value})


def _write_realtime_diagnostic_event(
    request: Request,
    user: User,
    *,
    event_code: str,
    metadata: dict,
    project_id: str | None = None,
) -> None:
    request_id = getattr(request.state, "request_id", None)
    correlation_id = getattr(request.state, "correlation_id", None)
    try:
        write_diagnostic_event(
            owner_user_id=user.id,
            component="api",
            event_code=event_code,
            project_id=project_id,
            request_id=request_id,
            correlation_id=correlation_id,
            metadata=metadata,
        )
    except Exception:
        LOGGER.warning(
            "realtime_diagnostic_write_failed request_id=%s correlation_id=%s event_code=%s",
            request_id,
            correlation_id,
            event_code,
        )

def _raise_realtime_draft_failure(exc: RealtimeDraftError) -> None:
    status_code = {
        RealtimeDraftReason.storage_limit: status.HTTP_409_CONFLICT,
        RealtimeDraftReason.scope_conflict: status.HTTP_404_NOT_FOUND,
        RealtimeDraftReason.revision_conflict: status.HTTP_409_CONFLICT,
        RealtimeDraftReason.payload_too_large: status.HTTP_422_UNPROCESSABLE_ENTITY,
        RealtimeDraftReason.payload_invalid: status.HTTP_422_UNPROCESSABLE_ENTITY,
        RealtimeDraftReason.crypto_failed: status.HTTP_503_SERVICE_UNAVAILABLE,
    }[exc.reason]
    raise HTTPException(status_code, {"reason": exc.reason.value}) from exc

def _realtime_draft_payload(draft, *, include_text: bool) -> dict:
    payload = {
        "client_session_id": draft.client_session_id,
        "revision": draft.revision,
        "updated_at": draft.updated_at.isoformat(),
        "expires_at": None,
    }
    if include_text:
        payload.update(
            {
                "committed_segments": list(draft.committed_segments),
                **({"segment_metadata": list(draft.segment_metadata)} if draft.segment_metadata is not None else {}),
                "partial": draft.partial,
            }
        )
    return payload

@app.put("/api/projects/{project_id}/realtime/drafts/{client_session_id}")
def put_project_realtime_draft(
    project_id: str,
    client_session_id: str,
    data: RealtimeDraftIn,
    response: Response,
    pair=Depends(require_csrf),
    db: Session=Depends(get_db),
):
    _, user = pair
    # The client may checkpoint partial text every 750 ms while audio is active.
    limiter.check(
        "realtime:draft:save:" + user.id,
        REALTIME_DRAFT_SAVE_LIMIT_PER_HOUR,
        3600,
    )
    project = owned_project_or_404(db, user, project_id)
    _browser_capability_cache_headers(response)

    def save() -> object:
        return save_realtime_draft(
            db,
            owner_user_id=user.id,
            project=project,
            client_session_id=client_session_id,
            revision=data.revision,
            committed_segments=data.committed_segments,
            segment_metadata=data.segment_metadata,
            partial=data.partial,
            settings=settings,
            now=utcnow(),
        )

    try:
        draft = save()
        db.commit()
    except RealtimeDraftError as exc:
        db.rollback()
        _raise_realtime_draft_failure(exc)
    except IntegrityError:
        db.rollback()
        try:
            # A concurrent identical first write can win the unique insert race.
            # Reload once after rollback so that the existing idempotence contract
            # decides between success and a genuine revision conflict.
            draft = save()
            db.commit()
        except RealtimeDraftError as exc:
            db.rollback()
            _raise_realtime_draft_failure(exc)
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"reason": RealtimeDraftReason.revision_conflict.value},
            ) from exc
    return {"draft": _realtime_draft_payload(draft, include_text=False)}

@app.get("/api/projects/{project_id}/realtime/drafts/latest")
def get_project_latest_realtime_draft(
    project_id: str,
    response: Response,
    pair=Depends(current_session),
    db: Session=Depends(get_db),
):
    _, user = pair
    limiter.check("realtime:draft:load:" + user.id, 240, 3600)
    project = owned_project_or_404(db, user, project_id)
    _browser_capability_cache_headers(response)
    try:
        draft = load_latest_realtime_draft(
            db,
            owner_user_id=user.id,
            project=project,
            settings=settings,
            now=utcnow(),
        )
        db.commit()
    except RealtimeDraftError as exc:
        db.rollback()
        _raise_realtime_draft_failure(exc)
    return {
        "draft": _realtime_draft_payload(draft, include_text=True)
        if draft is not None
        else None
    }

@app.delete("/api/projects/{project_id}/realtime/drafts/{client_session_id}")
def delete_project_realtime_draft(
    project_id: str,
    client_session_id: str,
    response: Response,
    pair=Depends(require_csrf),
    db: Session=Depends(get_db),
    _=Depends(require_same_origin),
):
    _, user = pair
    limiter.check("realtime:draft:delete:" + user.id, 120, 3600)
    project = owned_project_or_404(db, user, project_id)
    _browser_capability_cache_headers(response)
    try:
        deleted = delete_realtime_draft(
            db,
            owner_user_id=user.id,
            project=project,
            client_session_id=client_session_id,
        )
        if deleted:
            audit(
                db,
                "realtime_draft.deleted",
                actor_user_id=user.id,
                subject_user_id=user.id,
            )
        db.commit()
    except RealtimeDraftError as exc:
        db.rollback()
        _raise_realtime_draft_failure(exc)
    return {"ok": True, "deleted": deleted}

@app.post("/api/projects/{project_id}/realtime/capability")
def create_project_realtime_capability(
    project_id: str,
    data: RealtimeCapabilityIn,
    request: Request,
    response: Response,
    pair=Depends(require_csrf),
    db: Session=Depends(get_db),
):
    _, user = pair
    limiter.check("realtime:capability:" + user.id, 20, 300)
    project = owned_project_or_404(db, user, project_id)
    _browser_capability_cache_headers(response)
    try:
        mode_capability=resolve_capability(settings,data.provider,SttOperatingMode.realtime)
    except SttCapabilityError as exc:
        raise HTTPException(422,detail={"reason":exc.reason.value}) from None
    health=provider_health(db,provider=data.provider.value,operating_mode="realtime",now=utcnow().replace(tzinfo=None))
    if not health.available:
        raise HTTPException(503,detail={"reason":"provider_mode_unavailable","retry_after_seconds":health.retry_after_seconds})
    credential_id = _resolve_active_stt_credential_id(
        db,
        user,
        data.provider_credential_id,
        data.provider,
        SttOperatingMode.realtime,
    )
    if data.provider == SttProvider.yandex:
        credential=db.get(ProviderCredential,credential_id)
        version=db.get(ProviderCredentialVersion,credential.active_version_id) if credential and credential.active_version_id else None
        try:
            config=json.loads(credential.config_json or "{}") if credential else {}
        except (TypeError,ValueError):
            config={}
        folder_id=str(config.get("folder_id") or "").strip()
        if version is None or not folder_id:
            raise HTTPException(503,detail={"reason":"credential_unavailable"})
        capability=create_yandex_realtime_capability(
            owner_user_id=user.id,
            project_id=project.id,
            credential_id=credential.id,
            credential_version_id=version.id,
            folder_id=folder_id,
            language_code={"ru":"ru-RU","en":"en-US"}.get(data.language.value),
            model=mode_capability.model,
            settings=settings,
        )
        _write_realtime_diagnostic_event(request,user,event_code="REALTIME_CAPABILITY_ISSUED",project_id=project.id,metadata={"provider":"yandex","model":mode_capability.model,"expires_in_seconds":capability["expires_in_seconds"]})
        return capability
    api_key = _open_active_stt_api_key(db,user,credential_id,data.provider)
    try:
        capability = create_realtime_capability(
            api_key,
            language_code=provider_language_code(data.language.value),
        )
    except RealtimeCapabilityError as exc:
        try:
            db.rollback()
            record_provider_failure(
                db,
                provider="elevenlabs",
                operating_mode="realtime",
                failure_code=exc.reason.value,
                threshold=settings.stt_health_failure_threshold,
                cooldown_seconds=settings.stt_health_cooldown_seconds,
                now=utcnow().replace(tzinfo=None),
            )
            db.commit()
        except Exception:
            db.rollback()
        _raise_realtime_capability_failure(
            request,
            user,
            reason=exc.reason,
        )
    try:
        record_provider_success(
            db,
            provider="elevenlabs",
            operating_mode="realtime",
            now=utcnow().replace(tzinfo=None),
        )
        db.commit()
    except Exception:
        db.rollback()
    _write_realtime_diagnostic_event(
        request,
        user,
        event_code="REALTIME_CAPABILITY_ISSUED",
        project_id=project.id,
        metadata={
            "model": capability.model_id,
            "expires_in_seconds": capability.expires_in_seconds,
        },
    )
    return capability.browser_payload()


@app.websocket("/api/realtime/yandex")
async def yandex_realtime_websocket(websocket: WebSocket,capability: str=Query(...,min_length=80,max_length=1600)):
    await relay_yandex_realtime(websocket,capability=capability,settings=settings)


@app.post("/api/projects/{project_id}/realtime/consumers/deliver")
def deliver_project_realtime_caption(
    project_id: str,
    data: RealtimeConsumerDeliveryIn,
    pair=Depends(require_csrf),
    db: Session=Depends(get_db),
    _=Depends(require_same_origin),
):
    _,user=pair
    limiter.check("realtime:consumer:"+user.id,600,3600)
    owned_project_or_404(db,user,project_id)
    try:
        target=validate_realtime_consumer_target(
            data.kind,
            data.endpoint,
            webhook_allowed_hosts=settings.realtime_webhook_allowed_hosts,
        )
        deliver_realtime_caption(
            target,
            text=" ".join(data.text.split()),
            sequence=data.sequence,
        )
    except RealtimeConsumerError as exc:
        status_code=422 if str(exc) in {
            "unsupported_consumer",
            "invalid_consumer_endpoint",
            "invalid_youtube_endpoint",
            "webhook_host_not_allowed",
            "consumer_endpoint_not_public",
            "invalid_caption_text",
            "invalid_caption_sequence",
        } else 502
        raise HTTPException(status_code,detail={"reason":str(exc)}) from None
    return {"ok":True}

def _existing_batch_is_complete(existing, request_hash: str, expected_count: int) -> bool:
    if len(existing) != expected_count:
        return False
    positions=[job.batch_position for job in existing]
    return positions == list(range(expected_count)) and all(job.batch_request_hash == request_hash for job in existing)

def _normalize_batch_creation_input(data: TranscriptionJobBatchCreateIn):
    language=stored_language_mode(data.language)
    options_payload={"diarize":bool(data.options.diarize),"dictionary_ids":list(data.options.dictionary_ids)}
    options_json=json.dumps(options_payload,sort_keys=True,separators=(",",":"))
    explicit_provider_credential_id=data.provider_credential_id.strip() if isinstance(data.provider_credential_id, str) and data.provider_credential_id.strip() else None
    pairs=set(); duplicate_pair_found=False; source_ids=[]; folder_ids=[]; titles=[]; reprocess_existing=[]; media_clips=[]
    for item in data.items:
        sid=item.source_id.strip(); fid=clean_drive_id(item.output_folder_id, "ID папки Google Drive")
        clip=normalize_media_clip_range(item.media_clip_start_seconds, item.media_clip_end_seconds)
        pair_key=(sid,fid,clip.start_seconds,clip.end_seconds)
        if pair_key in pairs: duplicate_pair_found=True
        pairs.add(pair_key); source_ids.append(sid); folder_ids.append(fid); titles.append(clean_job_title(item.title)); reprocess_existing.append(item.reprocess_existing); media_clips.append(clip)
    hash_items=[]
    for sid,fid,title,reprocess,clip in zip(source_ids,folder_ids,titles,reprocess_existing,media_clips):
        hash_item={"source_id": sid, "output_folder_id": fid, "title": title}
        # Preserve hashes created before the optional decision field existed.
        # An affirmative reprocess decision must still produce a distinct hash.
        if reprocess:
            hash_item["reprocess_existing"]=True
        if not clip.is_full_source:
            hash_item["media_clip_start_seconds"]=clip.start_seconds
            hash_item["media_clip_end_seconds"]=clip.end_seconds
        hash_items.append(hash_item)
    return language, options_json, explicit_provider_credential_id, duplicate_pair_found, source_ids, folder_ids, titles, reprocess_existing, media_clips, hash_items

def _validate_new_batch_targets(db: Session, user: User, project: Project, *, provider, operating_mode, language, diarization_enabled, dictionary_ids, explicit_provider_credential_id, duplicate_pair_found, source_ids, folder_ids, media_clips):
    try:
        capability=validate_selection(settings,provider=provider,mode=operating_mode,language=language,diarization=diarization_enabled,dictionary_count=len(dictionary_ids))
    except SttCapabilityError as exc:
        raise HTTPException(422,detail={"reason":exc.reason.value}) from None
    health=provider_health(db,provider=provider.value,operating_mode=operating_mode.value,now=utcnow().replace(tzinfo=None))
    if not health.available:
        raise HTTPException(503,detail={"reason":"provider_mode_unavailable","retry_after_seconds":health.retry_after_seconds})
    provider_credential_id=_resolve_active_stt_credential_id(
        db,
        user,
        explicit_provider_credential_id,
        provider,
        operating_mode,
    )
    try:
        dictionaries=load_owned_dictionaries(db,owner_user_id=user.id,dictionary_ids=dictionary_ids)
    except ValueError as exc:
        raise HTTPException(422,detail={"reason":str(exc)}) from None
    if duplicate_pair_found:
        raise HTTPException(422, "Повторяющиеся source/folder пары не допускаются")
    sources=validate_job_sources(db, project.id, source_ids)
    _require_known_batch_clip_bounds(sources, media_clips)
    unique_folders=list(dict.fromkeys(folder_ids))
    access_token=refreshed_google_drive_access_token(db, user)
    verified_by_id={fid: verify_output_folder_selection(access_token, fid) for fid in unique_folders}
    return provider_credential_id, sources, verified_by_id, capability, snapshot_dictionary_terms(dictionaries)

def _require_known_batch_clip_bounds(sources, media_clips):
    for source, clip in zip(sources, media_clips, strict=True):
        try:
            validate_known_clip_duration(clip, known_prepared_duration_seconds(source))
        except MediaClipRangeError:
            raise HTTPException(422, "Границы фрагмента выходят за длительность выбранной подготовленной записи") from None

def _batch_target_settings(*, provider: str, model: str, language: str, diarization_enabled: bool, media_clip):
    return current_effective_settings(
        provider=provider,
        model=model,
        language_mode=language,
        diarization_enabled=diarization_enabled,
        media_clip_start_seconds=media_clip.start_seconds,
        media_clip_end_seconds=media_clip.end_seconds,
    )

def _batch_decision_key(source, media_clip) -> str:
    return f"{source.id}:{media_clip.start_seconds}:{media_clip.end_seconds}"

def _require_catalog_identity_locks(db: Session, user: User, sources):
    locked = lock_catalog_source_identities(
        db,
        owner_user_id=user.id,
        sources=sources,
    )
    selected_ids = {source.id for source in sources}
    if not selected_ids.issubset({source.id for source in locked}):
        raise HTTPException(
            409,
            detail={"reason": "catalog_query_budget_exceeded"},
        )
    return locked

def _load_batch_existing_result_matches(db: Session, user: User, sources, media_clips, *, provider: str="elevenlabs", model: str="scribe_v2", language: str, diarization_enabled: bool):
    decisions={}
    for source,media_clip in zip(sources,media_clips,strict=True):
        match=load_existing_result_matches(db,owner_user_id=user.id,sources=(source,),target_settings=_batch_target_settings(provider=provider,model=model,language=language,diarization_enabled=diarization_enabled,media_clip=media_clip)).get(source.id)
        decisions[_batch_decision_key(source,media_clip)]=match
    return decisions

def _load_batch_provider_attempt_authorities(db: Session, user: User, sources, media_clips, *, provider: str="elevenlabs", model: str="scribe_v2", language: str, diarization_enabled: bool, attention_job_ids: dict[str, str] | None = None):
    decisions={}
    for source,media_clip in zip(sources,media_clips,strict=True):
        attention_for_source={} if attention_job_ids is not None else None
        authority=load_provider_attempt_authorities(db,owner_user_id=user.id,sources=(source,),target_settings=_batch_target_settings(provider=provider,model=model,language=language,diarization_enabled=diarization_enabled,media_clip=media_clip),attention_job_ids=attention_for_source).get(source.id)
        decision_key=_batch_decision_key(source,media_clip)
        decisions[decision_key]=authority
        if attention_job_ids is not None and attention_for_source and source.id in attention_for_source:
            attention_job_ids[decision_key]=attention_for_source[source.id]
    return decisions

def _require_batch_preflight_decisions(sources, media_clips, matches, provider_attempt_authorities, reprocess_existing):
    unresolved=0
    for source,media_clip,reprocess in zip(sources,media_clips,reprocess_existing,strict=True):
        match=matches.get(_batch_decision_key(source,media_clip))
        if match is None or (
            match.status != ExistingResultMatchStatus.no_match and not reprocess
        ):
            unresolved+=1
    if unresolved:
        raise HTTPException(409, "Для существующего результата требуется явное решение")
    provider_conflicts=sum(
        provider_attempt_authorities.get(_batch_decision_key(source,media_clip))
        != ProviderAttemptAuthorityStatus.available
        for source,media_clip in zip(sources,media_clips,strict=True)
    )
    if provider_conflicts:
        raise HTTPException(
            409,
            detail={"reason": "provider_authority_conflict"},
        )

@app.post("/api/projects/{project_id}/jobs/batch/preflight")
def preflight_transcription_jobs_batch(project_id: str, data: TranscriptionJobBatchCreateIn, request: Request, response: Response, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("job:batch:preflight:"+user.id, 60, 3600); _browser_capability_cache_headers(response); p=owned_project_or_404(db,user,project_id)
    language, _options_json, explicit_provider_credential_id, duplicate_pair_found, source_ids, folder_ids, titles, reprocess_existing, media_clips, _hash_items=_normalize_batch_creation_input(data)
    _provider_credential_id, sources, verified_by_id, capability, dictionary_terms=_validate_new_batch_targets(db,user,p,provider=data.provider,operating_mode=data.operating_mode,language=language,diarization_enabled=data.options.diarize,dictionary_ids=data.options.dictionary_ids,explicit_provider_credential_id=explicit_provider_credential_id,duplicate_pair_found=duplicate_pair_found,source_ids=source_ids,folder_ids=folder_ids,media_clips=media_clips)
    existing_result_matches=_load_batch_existing_result_matches(db,user,sources,media_clips,provider=data.provider.value,model=capability.model,language=language,diarization_enabled=data.options.diarize)
    include_attention_job_id=request.headers.get("x-studio-preflight-recovery") == "1"
    attention_job_ids={} if include_attention_job_id else None
    provider_attempt_authorities=_load_batch_provider_attempt_authorities(db,user,sources,media_clips,provider=data.provider.value,model=capability.model,language=language,diarization_enabled=data.options.diarize,attention_job_ids=attention_job_ids)
    return build_batch_preflight_payload(
        sources=sources,
        output_folders=[verified_by_id[fid] for fid in folder_ids],
        titles=titles,
        language_mode=language,
        diarization_enabled=data.options.diarize,
        provider=data.provider.value,
        model=capability.model,
        operating_mode=data.operating_mode.value,
        dictionary_term_count=len(dictionary_terms),
        existing_result_matches=existing_result_matches,
        reprocess_existing=reprocess_existing,
        provider_attempt_authorities=provider_attempt_authorities,
        attention_job_ids=attention_job_ids,
        include_attention_job_id=include_attention_job_id,
        decision_keys=[_batch_decision_key(source,media_clip) for source,media_clip in zip(sources,media_clips,strict=True)],
        media_clips=media_clips,
    )

@app.post("/api/projects/{project_id}/jobs/batch")
def create_transcription_jobs_batch(project_id: str, data: TranscriptionJobBatchCreateIn, request: Request, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("job:batch:create:"+user.id, 30, 3600); p=owned_project_or_404(db,user,project_id)
    key=_clean_idempotency_key(request.headers.get("Idempotency-Key"))
    language, options_json, explicit_provider_credential_id, duplicate_pair_found, source_ids, folder_ids, titles, reprocess_existing, media_clips, hash_items=_normalize_batch_creation_input(data)
    existing=_load_existing_batch(db,user.id,p.id,key)
    if existing:
        replay_credential_id = explicit_provider_credential_id or existing[0].provider_credential_id
        request_hash=_batch_hash(p.id,replay_credential_id,language,options_json,hash_items,provider=data.provider.value,operating_mode=data.operating_mode.value)
        if not _existing_batch_is_complete(existing, request_hash, len(data.items)):
            raise HTTPException(409, "Idempotency-Key already used with a different request")
        return {"jobs":[job_payload(j, include_sources=True) for j in existing], "created_count": len(existing), "replayed": True}
    provider_credential_id, sources, verified_by_id, capability, dictionary_terms=_validate_new_batch_targets(db,user,p,provider=data.provider,operating_mode=data.operating_mode,language=language,diarization_enabled=data.options.diarize,dictionary_ids=data.options.dictionary_ids,explicit_provider_credential_id=explicit_provider_credential_id,duplicate_pair_found=duplicate_pair_found,source_ids=source_ids,folder_ids=folder_ids,media_clips=media_clips)
    request_hash=_batch_hash(p.id,provider_credential_id,language,options_json,hash_items,provider=data.provider.value,operating_mode=data.operating_mode.value)
    try:
        jobs=[]
        _require_catalog_identity_locks(db, user, sources)
        sources=validate_job_sources(db, p.id, source_ids, lock_mode="no_key_update")
        _require_known_batch_clip_bounds(sources, media_clips)
        existing_result_matches=_load_batch_existing_result_matches(db,user,sources,media_clips,provider=data.provider.value,model=capability.model,language=language,diarization_enabled=data.options.diarize)
        provider_attempt_authorities=_load_batch_provider_attempt_authorities(db,user,sources,media_clips,provider=data.provider.value,model=capability.model,language=language,diarization_enabled=data.options.diarize)
        _require_batch_preflight_decisions(sources,media_clips,existing_result_matches,provider_attempt_authorities,reprocess_existing)
        for idx,(src,fid,title,media_clip) in enumerate(zip(sources,folder_ids,titles,media_clips,strict=True)):
            vf=verified_by_id[fid]
            job_options_json=stored_transcription_options(
                data.options.diarize,
                existing_result_reprocess_authorized=reprocess_existing[idx],
                dictionary_terms=dictionary_terms,
                model=capability.model,
            )
            job=TranscriptionJob(project_id=p.id, owner_user_id=user.id, trace_id=getattr(request.state,"trace_id",None), status=JobStatus.queued, provider=data.provider.value, operating_mode=data.operating_mode.value, provider_credential_id=provider_credential_id, title=title, language=language, options_json=job_options_json, batch_idempotency_key=key, batch_request_hash=request_hash, batch_position=idx, media_clip_start_seconds=media_clip.start_seconds, media_clip_end_seconds=media_clip.end_seconds)
            job.apply_output_folder_snapshot(folder_id=vf.id, folder_url=vf.web_view_url, folder_name=vf.name)
            db.add(job); db.flush(); db.add(TranscriptionJobSource(job_id=job.id, source_id=src.id, position=0, status=JobSourceStatus.queued)); jobs.append(job)
        audit(db,"job.batch_created",actor_user_id=user.id,subject_user_id=user.id,project_id=p.id,created_count=len(jobs))
        db.commit()
        for job in jobs:
            write_diagnostic_event(owner_user_id=user.id, component="api", event_code="JOB_CREATED", project_id=p.id, job_id=job.id, request_id=getattr(request.state,"request_id",None), correlation_id=getattr(request.state,"correlation_id",None), metadata={"source_count": 1, "batch_position": job.batch_position or 0, "credential_selected": bool(provider_credential_id)})
    except IntegrityError:
        db.rollback(); existing=_load_existing_batch(db,user.id,p.id,key)
        if _existing_batch_is_complete(existing, request_hash, len(data.items)):
            return {"jobs":[job_payload(j, include_sources=True) for j in existing], "created_count": len(existing), "replayed": True}
        raise HTTPException(409, "Idempotency-Key already used with a different request")
    for job in jobs: db.refresh(job)
    return {"jobs":[job_payload(j, include_sources=True) for j in sorted(jobs, key=lambda j: j.batch_position or 0)], "created_count": len(jobs), "replayed": False}

@app.post("/api/projects/{project_id}/sources/google-drive", deprecated=True)
def create_google_drive_source(project_id: str, data: GoogleDriveSourceIn, response: Response, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("source:gdrive:create:"+user.id, 120, 3600); p=owned_project_or_404(db,user,project_id)
    meta,mime=_validated_google_drive_source_metadata(db, user, data.drive_file_id)
    src=_new_google_drive_source(p.id, meta, mime, utcnow())
    db.add(src); audit(db,"source.google_drive.created",actor_user_id=user.id,subject_user_id=user.id,project_id=p.id); db.commit()
    response.headers["Deprecation"]="true"
    response.headers["Link"]=f'</api/projects/{p.id}/sources/google-picker>; rel="successor-version"'
    return source_payload(src)

@app.post("/api/projects/{project_id}/sources/local-upload/initiate")
def initiate_local_upload(project_id: str, data: LocalUploadInitiateIn, response: Response, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("source:local:initiate:"+user.id, 60, 3600); _browser_capability_cache_headers(response); p=owned_project_or_404(db,user,project_id)
    mime=validate_upload(data.mime_type, data.size_bytes)
    if not reference_storage_isolation_configured(settings): raise HTTPException(503, "Хранилища Studio не настроены")
    reference_class=data.reference_class.value
    bucket=reference_storage_bucket(settings, reference_class)
    if not bucket: raise HTTPException(503, "Хранилище Studio не настроено")
    multipart=data.size_bytes >= settings.source_multipart_threshold_bytes
    # The row must be flushed to obtain the source id before its object key can
    # be derived. Keep the additive schema's valid single-put state until the
    # provider has actually created the multipart session, then persist the
    # complete multipart authority atomically with the response.
    now=utcnow(); src=Source(project_id=p.id, source_type=SourceType.local_upload, original_filename=normalize_source_display_filename(data.original_filename), mime_type=mime, size_bytes=data.size_bytes, reference_class=reference_class, upload_protocol=SourceUploadProtocol.single_put.value, upload_status=SourceUploadStatus.pending, expires_at=now+timedelta(seconds=settings.source_upload_ttl_seconds))
    if reference_class == SourceReferenceClass.audio_processing.value:
        src.audio_retention_days = data.audio_retention_days or 7
    src.delete_after_transcripts = data.delete_after_transcripts
    db.add(src); db.flush(); src.s3_bucket=bucket; src.s3_object_key=f"{reference_class}/users/{user.id}/projects/{p.id}/sources/{src.id}/source"
    storage=get_reference_storage(settings, reference_class)
    upload_id=None
    try:
        if multipart:
            part_size=settings.source_multipart_part_size_bytes
            part_count=_multipart_part_count(data.size_bytes, part_size)
            if part_count < 1 or part_count > 10_000:
                raise HTTPException(422, "Файл нельзя безопасно разделить на части")
            upload_id=storage.create_multipart_upload(src.s3_object_key, mime)
            src.upload_protocol=SourceUploadProtocol.multipart.value
            src.multipart_upload_id=upload_id
            src.multipart_part_size_bytes=part_size
            src.multipart_part_count=part_count
            upload={"mode":"multipart", "part_size_bytes":part_size, "part_count":part_count, "expires_in":settings.source_upload_ttl_seconds}
        else:
            url=storage.presigned_put_url(src.s3_object_key, mime, settings.source_presign_ttl_seconds, data.size_bytes)
            upload={"mode":"single", "method":"PUT", "url":url, "headers":{"Content-Type":mime}, "expires_in":settings.source_presign_ttl_seconds}
        audit(db,"source.local_upload.initiated",actor_user_id=user.id,subject_user_id=user.id,upload_protocol=src.upload_protocol)
        db.commit()
    except Exception:
        db.rollback()
        if upload_id and src.s3_object_key:
            try:
                storage.abort_multipart_upload(src.s3_object_key, upload_id)
            except Exception:
                LOGGER.warning("source_multipart_initiation_compensation_failed", extra={"event":"source_multipart_initiation_compensation_failed"})
        raise
    return {"source_id":src.id, "upload":upload, "expires_at":src.expires_at.isoformat()}


def _pending_multipart_snapshot(source: Source, user: User, *, now: datetime) -> dict[str, object]:
    project = source.project
    if (
        source.source_type != SourceType.local_upload
        or source.upload_protocol != SourceUploadProtocol.multipart.value
        or source.upload_status != SourceUploadStatus.pending
        or source.deleted_at is not None
        or is_source_expired(source, now)
        or project is None
        or project.owner_user_id != user.id
        or project.archived_at is not None
        or not source.s3_bucket
        or not source.s3_object_key
        or not source.multipart_upload_id
        or not source.multipart_part_size_bytes
        or not source.multipart_part_count
        or source.size_bytes is None
        or not source.mime_type
    ):
        raise HTTPException(404, "Не найдено")
    reference_class=source_reference_class(source)
    if (
        not reference_storage_isolation_configured(settings)
        or source.s3_bucket != reference_storage_bucket(settings, reference_class)
    ):
        raise HTTPException(409, "Хранилище источника не совпадает с его классом")
    return {
        "source_id":source.id,
        "project_id":source.project_id,
        "bucket":source.s3_bucket,
        "key":source.s3_object_key,
        "reference_class":reference_class,
        "upload_id":source.multipart_upload_id,
        "part_size_bytes":source.multipart_part_size_bytes,
        "part_count":source.multipart_part_count,
        "size_bytes":source.size_bytes,
        "mime_type":source.mime_type,
    }


@app.post("/api/sources/{source_id}/local-upload/multipart/parts/{part_number}")
def issue_local_upload_part(source_id: str, part_number: int, response: Response, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("source:multipart:part:"+user.id, 1200, 3600); _browser_capability_cache_headers(response)
    source=owned_source_or_404(db,user,source_id)
    snapshot=_pending_multipart_snapshot(source,user,now=utcnow())
    if part_number < 1 or part_number > int(snapshot["part_count"]):
        raise HTTPException(422, "Некорректный номер части")
    db.rollback()
    url=get_reference_storage(settings,str(snapshot["reference_class"])).presigned_upload_part_url(
        str(snapshot["key"]),str(snapshot["upload_id"]),part_number,settings.source_presign_ttl_seconds,
        min(int(snapshot["part_size_bytes"]), int(snapshot["size_bytes"]) - (part_number - 1) * int(snapshot["part_size_bytes"]))
    )
    return {"part_number":part_number,"upload":{"method":"PUT","url":url,"headers":{},"expires_in":settings.source_presign_ttl_seconds}}


@app.get("/api/sources/{source_id}/local-upload/multipart/status")
def get_local_upload_multipart_status(source_id: str, response: Response, pair=Depends(current_session), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("source:multipart:status:"+user.id, 1200, 3600); _browser_capability_cache_headers(response)
    source=owned_source_or_404(db,user,source_id)
    if source.upload_status == SourceUploadStatus.uploaded:
        return {"status":"completed","uploaded_parts":[]}
    snapshot=_pending_multipart_snapshot(source,user,now=utcnow())
    db.rollback()
    try:
        parts=get_reference_storage(settings,str(snapshot["reference_class"])).list_multipart_parts(str(snapshot["key"]),str(snapshot["upload_id"]))
    except FileNotFoundError:
        parts=()
    return {"status":"active","uploaded_parts":[part.part_number for part in parts]}


@app.post("/api/sources/{source_id}/local-upload/multipart/complete")
def complete_local_multipart_upload(source_id: str, response: Response, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("source:multipart:complete:"+user.id, 120, 3600); _browser_capability_cache_headers(response)
    source=owned_source_or_404(db,user,source_id)
    if source.upload_status == SourceUploadStatus.uploaded:
        if is_source_expired(source,utcnow()): raise HTTPException(404,"Не найдено")
        return source_payload(source)
    snapshot=_pending_multipart_snapshot(source,user,now=utcnow())
    db.rollback()
    storage=get_reference_storage(settings,str(snapshot["reference_class"]))
    completion_error=None
    try:
        parts=storage.list_multipart_parts(str(snapshot["key"]),str(snapshot["upload_id"]))
        if not _multipart_parts_match_source(
            expected_size_bytes=int(snapshot["size_bytes"]),
            part_size_bytes=int(snapshot["part_size_bytes"]),
            part_count=int(snapshot["part_count"]),
            parts=parts,
        ):
            raise HTTPException(409,"Загружены не все части файла")
        storage.complete_multipart_upload(str(snapshot["key"]),str(snapshot["upload_id"]),parts)
    except HTTPException:
        raise
    except Exception as exc:
        completion_error=exc
    try:
        head=storage.head_object(str(snapshot["key"]))
    except FileNotFoundError:
        if completion_error is not None:
            raise HTTPException(503,"Не удалось подтвердить завершение multipart upload") from completion_error
        raise HTTPException(409,"Загруженный объект источника не найден")
    metadata_issue=uploaded_object_metadata_issue(
        expected_size_bytes=int(snapshot["size_bytes"]),
        expected_mime_type=str(snapshot["mime_type"]),
        actual_size_bytes=head.size_bytes,
        actual_mime_type=head.content_type,
        max_bytes=settings.source_max_upload_bytes,
    )
    if metadata_issue is not None:
        raise HTTPException(409,"Метаданные multipart object не совпадают с заявленными")
    source=db.execute(select(Source).where(Source.id==source_id).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    now=utcnow(); project=db.get(Project,source.project_id) if source is not None else None
    if source is not None and source.upload_status == SourceUploadStatus.uploaded:
        db.rollback(); return source_payload(source)
    if (
        source is None
        or project is None
        or project.owner_user_id != user.id
        or project.archived_at is not None
        or source.project_id != snapshot["project_id"]
        or source.source_type != SourceType.local_upload
        or source.upload_protocol != SourceUploadProtocol.multipart.value
        or source.upload_status != SourceUploadStatus.pending
        or source.deleted_at is not None
        or is_source_expired(source,now)
        or source.s3_bucket != snapshot["bucket"]
        or source.s3_object_key != snapshot["key"]
        or source_reference_class(source) != snapshot["reference_class"]
        or source.multipart_upload_id != snapshot["upload_id"]
        or source.multipart_part_size_bytes != snapshot["part_size_bytes"]
        or source.multipart_part_count != snapshot["part_count"]
        or source.size_bytes != snapshot["size_bytes"]
        or source.mime_type != snapshot["mime_type"]
    ):
        raise HTTPException(404,"Не найдено")
    source.upload_status=SourceUploadStatus.uploaded; source.uploaded_at=now; source.multipart_completed_at=now
    source.expires_at=now+timedelta(seconds=_completed_source_retention_seconds(source,user)); source.updated_at=now
    audit(db,"source.local_upload.completed",actor_user_id=user.id,subject_user_id=user.id,upload_protocol=SourceUploadProtocol.multipart.value)
    db.commit(); return source_payload(source)


@app.post("/api/sources/{source_id}/local-upload/multipart/abort")
def abort_local_multipart_upload(source_id: str, response: Response, pair=Depends(require_csrf), db: Session=Depends(get_db), _=Depends(require_same_origin)):
    _,user=pair; limiter.check("source:multipart:abort:"+user.id,120,3600); _browser_capability_cache_headers(response)
    source=db.execute(select(Source).where(Source.id==source_id).with_for_update()).scalar_one_or_none()
    project=db.get(Project,source.project_id) if source is not None else None
    if source is None or project is None or project.owner_user_id != user.id or project.archived_at is not None:
        raise HTTPException(404,"Не найдено")
    if source.upload_protocol != SourceUploadProtocol.multipart.value or source.source_type != SourceType.local_upload:
        raise HTTPException(404,"Не найдено")
    if source.upload_status == SourceUploadStatus.uploaded:
        raise HTTPException(409,"Загрузка уже завершена")
    now=utcnow()
    if source.deleted_at is None:
        source.deleted_at=now; source.delete_reason="upload_aborted"; source.upload_status=SourceUploadStatus.deleted; source.updated_at=now
        source.storage_cleanup_status=SourceStorageCleanupStatus.pending
        source.storage_cleanup_requested_at=source.storage_cleanup_requested_at or now
        source.storage_cleanup_not_before_at=now
        source.storage_cleanup_error_code=None
        audit(db,"source.local_upload.multipart_abort_requested",actor_user_id=user.id,subject_user_id=user.id,project_id=project.id)
    db.commit()
    return {"ok":True,"source_state":source.upload_status.value,"storage_cleanup":"pending"}

@app.post("/api/sources/{source_id}/local-upload/complete")
def complete_local_upload(source_id: str, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; src=owned_source_or_404(db,user,source_id)
    if src.source_type!=SourceType.local_upload or src.deleted_at is not None: raise HTTPException(404,"Не найдено")
    if src.upload_status==SourceUploadStatus.uploaded:
        if is_source_expired(src, utcnow()): raise HTTPException(404,"Не найдено")
        return source_payload(src)
    if src.upload_protocol != SourceUploadProtocol.single_put.value: raise HTTPException(409,"Используйте multipart completion")
    if src.upload_status!=SourceUploadStatus.pending: raise HTTPException(404,"Не найдено")
    initial_project_id=src.project_id
    initial_type=src.source_type
    initial_status=src.upload_status
    initial_bucket=src.s3_bucket
    initial_key=src.s3_object_key
    initial_reference_class=source_reference_class(src)
    initial_size_bytes=src.size_bytes
    initial_mime_type=src.mime_type
    if not initial_bucket or not initial_key:
        raise HTTPException(404,"Не найдено")
    if (
        not reference_storage_isolation_configured(settings)
        or initial_bucket != reference_storage_bucket(settings, initial_reference_class)
    ):
        raise HTTPException(409, "Хранилище источника не совпадает с его классом")
    try:
        head=get_reference_storage(settings, initial_reference_class).head_object(initial_key)
    except FileNotFoundError:
        raise HTTPException(409, "Загруженный объект источника не найден")
    metadata_issue=uploaded_object_metadata_issue(
        expected_size_bytes=initial_size_bytes,
        expected_mime_type=initial_mime_type,
        actual_size_bytes=head.size_bytes,
        actual_mime_type=head.content_type,
        max_bytes=settings.source_max_upload_bytes,
    )
    if metadata_issue==UploadedObjectMetadataIssue.source_too_large: raise HTTPException(422, "Файл слишком большой")
    if metadata_issue==UploadedObjectMetadataIssue.unsupported_mime_type: raise HTTPException(422, "Неподдерживаемый тип файла")
    if metadata_issue==UploadedObjectMetadataIssue.metadata_unavailable: raise HTTPException(409, "Не удалось проверить метаданные загруженного объекта")
    if metadata_issue is not None: raise HTTPException(409, "Метаданные загруженного объекта не совпадают с заявленными")
    src=db.execute(select(Source).where(Source.id==source_id).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    now=utcnow()
    project=db.get(Project, src.project_id) if src is not None else None
    if (
        not src
        or project is None
        or src.project_id != initial_project_id
        or project.owner_user_id != user.id
        or project.archived_at is not None
        or src.source_type != initial_type
        or src.source_type != SourceType.local_upload
        or src.upload_status != initial_status
        or src.upload_status != SourceUploadStatus.pending
        or src.deleted_at is not None
        or is_source_expired(src, now)
        or src.s3_bucket != initial_bucket
        or src.s3_object_key != initial_key
        or source_reference_class(src) != initial_reference_class
        or src.size_bytes != initial_size_bytes
        or src.mime_type != initial_mime_type
    ):
        raise HTTPException(404,"Не найдено")
    src.upload_status=SourceUploadStatus.uploaded
    src.uploaded_at=now
    src.expires_at=now+timedelta(seconds=_completed_source_retention_seconds(src,user))
    src.updated_at=now
    audit(db,"source.local_upload.completed",actor_user_id=user.id,subject_user_id=user.id)
    db.commit()
    return source_payload(src)

@app.delete("/api/sources/{source_id}")
def delete_source(source_id: str, request: Request, pair=Depends(require_csrf), db: Session=Depends(get_db), _=Depends(require_same_origin)):
    _,user=pair; limiter.check("source:delete:"+user.id, 60, 3600)
    result=request_source_deletion(db, owner_user_id=user.id, source_id=source_id, now=utcnow(), discard_failed_retry=True)
    if result is None:
        raise HTTPException(404,"Не найдено")
    if not result.ok:
        db.commit()
        raise HTTPException(status_code=409, detail={"reason": result.reason.value})
    db.commit()
    return {"ok": True, "source_state": result.source_state, "storage_cleanup": result.storage_cleanup}


@app.get("/api/projects/{project_id}/sources/bulk-deletion/preview")
def preview_bulk_source_deletion(
    project_id: str,
    source_ids: list[str] | None = Query(default=None, min_length=1, max_length=50),
    pair=Depends(current_session),
    db: Session=Depends(get_db),
):
    _, user = pair
    limiter.check("source:bulk-delete:preview:" + user.id, 60, 3600)
    try:
        selection = validate_bulk_source_selection(source_ids)
    except ValueError:
        raise HTTPException(422, "Недопустимый набор выбранных файлов")
    preview = bulk_source_deletion_preview(
        db,
        owner_user_id=user.id,
        project_id=project_id,
        now=utcnow(),
        source_ids=selection,
    )
    if preview is None:
        raise HTTPException(404, "Не найдено")
    return preview.payload()


@app.post("/api/projects/{project_id}/sources/bulk-deletion")
def apply_bulk_source_deletion(
    project_id: str,
    data: ConfirmedBulkSourceDeletionIn,
    request: Request,
    pair=Depends(require_csrf),
    db: Session=Depends(get_db),
    _=Depends(require_same_origin),
):
    _, user = require_recent_auth(pair,request=request,db=db)
    limiter.check("source:bulk-delete:apply:" + user.id, 10, 3600)
    now = utcnow()
    preview = bulk_source_deletion_preview(
        db,
        owner_user_id=user.id,
        project_id=project_id,
        now=now,
        lock_sources=True,
        source_ids=data.source_ids,
    )
    if preview is None:
        raise HTTPException(404, "Не найдено")
    preview_payload = preview.payload()
    if (
        not safe_eq(preview_payload["preview_token"], data.expected_preview_token)
        or preview_payload["eligible_count"] != data.expected_eligible_count
        or preview_payload["blocked_count"] != data.expected_blocked_count
    ):
        raise HTTPException(
            409,
            detail={"reason": "preview_changed", "preview": preview_payload},
        )
    cleanup_counts: dict[str, int] = {}
    deleted_count = 0
    for source_id in preview.eligible_ids:
        result = request_source_deletion(
            db,
            owner_user_id=user.id,
            source_id=source_id,
            now=now,
            discard_failed_retry=True,
        )
        if result is None or not result.ok:
            db.rollback()
            raise HTTPException(
                409,
                detail={"reason": "preview_changed"},
            )
        deleted_count += 1
        cleanup_counts[result.storage_cleanup] = cleanup_counts.get(result.storage_cleanup, 0) + 1
    audit(
        db,
        "source.bulk_deletion_completed",
        actor_user_id=user.id,
        subject_user_id=user.id,
        project_id=project_id,
        deleted_count=deleted_count,
        blocked_count=preview_payload["blocked_count"],
    )
    db.commit()
    write_diagnostic_event(
        owner_user_id=user.id,
        component="api",
        event_code="SOURCE_BULK_DELETION_COMPLETED",
        project_id=project_id,
        request_id=getattr(request.state, "request_id", None),
        correlation_id=getattr(request.state, "correlation_id", None),
        metadata={
            "deleted_count": deleted_count,
            "blocked_count": preview_payload["blocked_count"],
            "boundary": "source_deletion",
        },
    )
    return {
        "ok": True,
        "deleted_count": deleted_count,
        "blocked_count": preview_payload["blocked_count"],
        "blocked_reasons": preview_payload["blocked_reasons"],
        "cleanup_counts": cleanup_counts,
        "google_drive_files_deleted": 0,
    }


@app.get("/api/sources/{source_id}")
def get_source(source_id: str, pair=Depends(current_session), db: Session=Depends(get_db)):
    _,user=pair
    return source_payload(owned_source_or_404(db,user,source_id))


def _raise_audio_preparation_error(exc: Exception) -> None:
    reason = getattr(getattr(exc, "reason", None), "value", "invalid_request")
    code = {
        "not_found": 404,
        "project_unavailable": 404,
        "source_unavailable": 422,
        "invalid_sources": 422,
        "invalid_destination": 422,
        "invalid_options": 422,
        "invalid_input": 422,
        "invalid_state": 409,
        "lease_unavailable": 409,
    }.get(reason, 422)
    raise HTTPException(code, detail={"reason": reason}) from None


@app.get("/api/projects/{project_id}/audio-preparations")
def list_audio_preparations(project_id: str, pair=Depends(current_session), db: Session=Depends(get_db)):
    _, user = pair
    try:
        rows = list_owned_audio_preparation_jobs(db, owner_user_id=user.id, project_id=project_id)
    except AudioPreparationServiceError as exc:
        _raise_audio_preparation_error(exc)
    return {"jobs": [audio_preparation_payload(row) for row in rows]}


@app.post("/api/projects/{project_id}/audio-preparations")
def create_audio_preparation(
    project_id: str,
    data: AudioPreparationCreateIn,
    request: Request,
    pair=Depends(require_csrf),
    db: Session=Depends(get_db),
    _=Depends(require_same_origin),
):
    _, user = pair
    limiter.check("audio-preparation:create:" + user.id, 30, 3600)
    folder = None
    if data.output_destination == "google_drive":
        try:
            access_token = get_cloud_files_provider().access_token(db, user_id=user.id, settings=settings)
            folder = verify_output_folder_selection(access_token, data.output_drive_folder_id)
        except GoogleConnectionAccessError as exc:
            raise HTTPException(409, detail={"reason": exc.reason.value}) from None
    try:
        job = create_audio_preparation_job(
            db,
            owner_user_id=user.id,
            project_id=project_id,
            title=data.title,
            source_ids=data.source_ids,
            ephemeral_source_ids=set(data.ephemeral_source_ids),
            manual_order=data.manual_order,
            options_payload=data.options,
            output_destination=data.output_destination,
            output_folder=folder,
            now=utcnow(),
            trace_id=getattr(request.state, "trace_id", None),
            max_total_input_bytes=settings.audio_preparation_max_input_bytes,
        )
        audit(db, "audio_preparation.created", actor_user_id=user.id, subject_user_id=user.id, project_id=project_id, job_id=job.id)
        db.commit()
        job = load_owned_audio_preparation_job(db, owner_user_id=user.id, job_id=job.id)
    except (AudioPreparationServiceError, AudioPreparationError) as exc:
        db.rollback()
        _raise_audio_preparation_error(exc)
    return audio_preparation_payload(job)


@app.get("/api/audio-preparations/{job_id}")
def get_audio_preparation(job_id: str, pair=Depends(current_session), db: Session=Depends(get_db)):
    _, user = pair
    try:
        job = load_owned_audio_preparation_job(db, owner_user_id=user.id, job_id=job_id)
    except AudioPreparationServiceError as exc:
        _raise_audio_preparation_error(exc)
    return audio_preparation_payload(job)


@app.post("/api/audio-preparations/{job_id}/start")
def start_audio_preparation(job_id: str, pair=Depends(require_csrf), db: Session=Depends(get_db), _=Depends(require_same_origin)):
    _, user = pair
    limiter.check("audio-preparation:start:" + user.id, 30, 3600)
    try:
        job = start_audio_preparation_job(db, owner_user_id=user.id, job_id=job_id)
        audit(db, "audio_preparation.started", actor_user_id=user.id, subject_user_id=user.id, project_id=job.project_id, job_id=job.id)
        db.commit()
        job = load_owned_audio_preparation_job(db, owner_user_id=user.id, job_id=job.id)
    except AudioPreparationServiceError as exc:
        db.rollback()
        _raise_audio_preparation_error(exc)
    return audio_preparation_payload(job)


@app.post("/api/audio-preparations/{job_id}/cancel")
def cancel_audio_preparation(job_id: str, pair=Depends(require_csrf), db: Session=Depends(get_db), _=Depends(require_same_origin)):
    _, user = pair
    limiter.check("audio-preparation:cancel:" + user.id, 60, 3600)
    try:
        job = cancel_audio_preparation_job(db, owner_user_id=user.id, job_id=job_id, now=utcnow())
        if job.status is AudioPreparationStatus.cancelled:
            for item in job.inputs:
                if item.ephemeral_reference:
                    request_source_deletion(db, owner_user_id=user.id, source_id=item.source_id, now=utcnow())
        audit(db, "audio_preparation.cancelled", actor_user_id=user.id, subject_user_id=user.id, project_id=job.project_id, job_id=job.id)
        db.commit()
        job = load_owned_audio_preparation_job(db, owner_user_id=user.id, job_id=job.id)
    except AudioPreparationServiceError as exc:
        db.rollback()
        _raise_audio_preparation_error(exc)
    return audio_preparation_payload(job)


@app.post("/api/audio-preparations/{job_id}/save-to-drive")
def save_audio_preparation_to_drive(job_id: str, data: GooglePickerOutputFolderIn, pair=Depends(require_csrf), db: Session=Depends(get_db), _=Depends(require_same_origin)):
    _, user = pair
    limiter.check("audio-preparation:export:" + user.id, 30, 3600)
    try:
        # Check ownership before any external request.
        load_owned_audio_preparation_job(db, owner_user_id=user.id, job_id=job_id)
        access_token = get_cloud_files_provider().access_token(db, user_id=user.id, settings=settings)
        folder = verify_output_folder_selection(access_token, data.folder_id)
        job = queue_audio_drive_export(db, owner_user_id=user.id, job_id=job_id, folder=folder, now=utcnow())
        audit(db, "audio_preparation.export_requested", actor_user_id=user.id, subject_user_id=user.id, project_id=job.project_id, job_id=job.id)
        db.commit()
        job = load_owned_audio_preparation_job(db, owner_user_id=user.id, job_id=job.id)
    except GoogleConnectionAccessError as exc:
        db.rollback()
        raise HTTPException(409, detail={"reason": exc.reason.value}) from None
    except AudioPreparationServiceError as exc:
        db.rollback()
        _raise_audio_preparation_error(exc)
    return audio_preparation_payload(job)


@app.post("/api/audio-preparations/{job_id}/recover-output")
def recover_audio_output(job_id: str, pair=Depends(require_csrf), db: Session=Depends(get_db), _=Depends(require_same_origin)):
    _, user = pair
    limiter.check("audio-preparation:recover:" + user.id, 30, 3600)
    try:
        job = recover_audio_preparation_output(db, owner_user_id=user.id, job_id=job_id, now=utcnow())
        audit(db, "audio_preparation.output_recovered", actor_user_id=user.id, subject_user_id=user.id, project_id=job.project_id, job_id=job.id)
        db.commit()
        job = load_owned_audio_preparation_job(db, owner_user_id=user.id, job_id=job.id)
    except AudioPreparationServiceError as exc:
        db.rollback()
        _raise_audio_preparation_error(exc)
    return audio_preparation_payload(job)


@app.post("/api/audio-preparations/{job_id}/reuse-source")
def reuse_prepared_audio(job_id: str, pair=Depends(require_csrf), db: Session=Depends(get_db), _=Depends(require_same_origin)):
    _, user = pair
    limiter.check("audio-preparation:reuse:" + user.id, 30, 3600)
    try:
        job = load_owned_audio_preparation_job(db, owner_user_id=user.id, job_id=job_id)
    except AudioPreparationServiceError as exc:
        _raise_audio_preparation_error(exc)
    owned_project_or_404(db, user, job.project_id)
    if job.status is not AudioPreparationStatus.completed or not job.output_drive_file_id:
        raise HTTPException(409, detail={"reason": "drive_copy_required"})
    drive_id = job.output_drive_file_id
    project_id = job.project_id
    access_token = refreshed_google_drive_access_token(db, user)
    db.commit()  # Persist token refresh and release the transaction before Drive I/O.
    meta, mime = _validated_google_drive_source_metadata(db, user, drive_id, access_token=access_token)
    job = db.execute(select(AudioPreparationJob).where(AudioPreparationJob.id == job_id,
        AudioPreparationJob.owner_user_id == user.id).with_for_update()).scalar_one_or_none()
    if job is None or job.status is not AudioPreparationStatus.completed or job.output_drive_file_id != drive_id:
        raise HTTPException(409, detail={"reason": "output_unavailable"})
    owned_project_or_404(db, user, project_id)
    source = db.execute(select(Source).where(Source.project_id == project_id,
        Source.source_type == SourceType.google_drive, Source.drive_file_id == drive_id,
        Source.deleted_at.is_(None)).order_by(Source.created_at, Source.id).limit(1)).scalar_one_or_none()
    if source is None:
        source = _new_google_drive_source(project_id, meta, mime, utcnow())
        db.add(source)
        db.flush()
        audit(db, "audio_preparation.reused", actor_user_id=user.id, subject_user_id=user.id,
              project_id=project_id, source_id=source.id, job_id=job.id)
    if job.output_size_bytes == meta.size_bytes and job.total_input_duration_ms and job.output_duration_ms:
        context = {"job_id": job.id, "input_duration_ms": job.total_input_duration_ms,
            "output_duration_ms": job.output_duration_ms,
            "pauses_removed": bool(json.loads(job.options_json).get("silence_enabled", False)) and job.output_duration_ms < job.total_input_duration_ms}
        source.prepared_audio_context_json = json.dumps(context, separators=(",", ":"))
    else:
        source.prepared_audio_context_json = None
    db.commit()
    return source_payload(source)


@app.post("/api/audio-preparations/{job_id}/preview-audio")
def prepare_audio_sample(job_id: str, pair=Depends(require_csrf), db: Session=Depends(get_db), _=Depends(require_same_origin)):
    _, user = pair
    limiter.check("audio-preparation:download:" + user.id, 30, 3600)
    try:
        return audio_downloads.prepare(db, owner=user.id, job_id=job_id, preview=True)
    except AudioPreparationServiceError as exc:
        db.rollback()
        _raise_audio_preparation_error(exc)
    except AudioDownloadError as exc:
        db.rollback()
        raise HTTPException(409, detail={"reason": exc.reason}) from None


@app.post("/api/audio-preparations/{job_id}/download")
def prepare_audio_download(job_id: str, pair=Depends(require_csrf), db: Session=Depends(get_db), _=Depends(require_same_origin)):
    _, user = pair
    limiter.check("audio-preparation:download:" + user.id, 30, 3600)
    try:
        job = load_owned_audio_preparation_job(db, owner_user_id=user.id, job_id=job_id)
        if job.output_source_id:
            return {"state": "ready", "percent": 100, "reason": None}
        return audio_downloads.prepare(db, owner=user.id, job_id=job_id)
    except AudioPreparationServiceError as exc:
        db.rollback()
        _raise_audio_preparation_error(exc)
    except AudioDownloadError as exc:
        raise HTTPException(409, detail={"reason": exc.reason}) from None


@app.get("/api/audio-preparations/{job_id}/download/status")
def audio_download_status(job_id: str, pair=Depends(current_session)):
    _, user = pair
    try:
        return audio_downloads.status(owner=user.id, job_id=job_id)
    except AudioDownloadError as exc:
        raise HTTPException(409, detail={"reason": exc.reason}) from None
    except AudioPreparationServiceError as exc:
        _raise_audio_preparation_error(exc)


@app.post("/api/audio-preparations/{job_id}/download/cancel")
def cancel_audio_download(job_id: str, pair=Depends(require_csrf), db: Session=Depends(get_db), _=Depends(require_same_origin)):
    _, user = pair
    try:
        return audio_downloads.cancel(db, owner=user.id, job_id=job_id)
    except AudioPreparationServiceError as exc:
        db.rollback()
        _raise_audio_preparation_error(exc)
    except AudioDownloadError as exc:
        db.rollback()
        raise HTTPException(409, detail={"reason": exc.reason}) from None


@app.get("/api/audio-preparations/{job_id}/listen")
def listen_audio_result(job_id: str, request: Request, pair=Depends(current_session), db: Session=Depends(get_db)):
    if request.headers.get("sec-fetch-site", "none") not in {"same-origin", "none"}:
        raise HTTPException(403, detail={"reason": "same_origin_required"})
    _, user = pair
    owner_id = user.id
    db.rollback()
    try:
        result = audio_downloads.listen(owner=owner_id, job_id=job_id)
    except AudioDownloadError as exc:
        raise HTTPException(409, detail={"reason": exc.reason}) from None
    except AudioPreparationServiceError as exc:
        _raise_audio_preparation_error(exc)
    # Native media controls use byte ranges; reads never extend the fixed TTL.
    return FileResponse(result.path, media_type=result.mime_type, headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff", "X-Accel-Buffering": "no"})


@app.get("/api/audio-preparations/{job_id}/download")
def download_audio_preparation(job_id: str, request: Request, pair=Depends(current_session), db: Session=Depends(get_db)):
    if request.headers.get("sec-fetch-site", "none") not in {"same-origin", "none"}:
        raise HTTPException(403, detail={"reason": "same_origin_required"})
    _, user = pair
    try:
        job = load_owned_audio_preparation_job(db, owner_user_id=user.id, job_id=job_id)
    except AudioPreparationServiceError as exc:
        _raise_audio_preparation_error(exc)
    if job.status is not AudioPreparationStatus.completed:
        raise HTTPException(409, detail={"reason": "output_unavailable"})
    if not job.output_source_id:
        owned_project_or_404(db, user, job.project_id)
        owner_id = user.id
        db.rollback()  # Do not pin the dependency's read transaction during a stream.
        try:
            return stream_audio_download(audio_downloads, owner=owner_id, job_id=job_id)
        except AudioDownloadError as exc:
            raise HTTPException(409, detail={"reason": exc.reason}) from None
        except AudioPreparationServiceError as exc:
            _raise_audio_preparation_error(exc)
    source = owned_source_or_404(db, user, job.output_source_id)
    if source.source_type is not SourceType.local_upload or not source.s3_object_key or is_source_expired(source, utcnow()):
        raise HTTPException(404, "Не найдено")
    reference_class=source_reference_class(source)
    if (
        not reference_storage_isolation_configured(settings)
        or source.s3_bucket != reference_storage_bucket(settings, reference_class)
    ):
        raise HTTPException(409, detail={"reason": "output_storage_unavailable"})
    url = get_reference_storage(settings, reference_class).presigned_get_url(
        source.s3_object_key,
        min(settings.source_presign_ttl_seconds, 300),
        download_name=source.original_filename,
    )
    response = RedirectResponse(url=url, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    return response



def history_attention_required_expression():
    accepted_output_exists = (
        select(TranscriptionJobOutput.id)
        .where(
            TranscriptionJobOutput.job_source_id
            == TranscriptionJobSourceAttempt.job_source_id,
            TranscriptionJobOutput.output_kind
            == GOOGLE_DOCS_TRANSCRIPT_OUTPUT_KIND,
        )
        .correlate(TranscriptionJobSourceAttempt)
        .exists()
    )
    return (
        select(TranscriptionJobSourceAttempt.id)
        .where(
            TranscriptionJobSourceAttempt.job_id == TranscriptionJob.id,
            TranscriptionJob.status.in_(
                [JobStatus.completed, JobStatus.failed, JobStatus.cancelled]
            ),
            TranscriptionJob.history_attention_resolved_at.is_(None),
            TranscriptionJobSourceAttempt.provider_request_started_at.is_not(
                None
            ),
            TranscriptionJobSourceAttempt.retry_disposition
            != SourceAttemptRetryDisposition.retry_safe,
            ~accepted_output_exists,
        )
        .correlate(TranscriptionJob)
        .exists()
    )


@app.get("/api/projects/{project_id}/jobs")
def list_project_jobs(
    project_id: str,
    cursor: str|None=Query(None, max_length=MAX_COLLECTION_CURSOR_LENGTH),
    page_size: int=Query(DEFAULT_COLLECTION_PAGE_SIZE, ge=1, le=MAX_COLLECTION_PAGE_SIZE),
    pair=Depends(current_session),
    db: Session=Depends(get_db),
):
    sess,user=pair; p=owned_project_or_404(db,user,project_id)
    scope={"project_id": p.id}
    try:
        position=decode_collection_cursor(cursor, secret=sess.csrf_hash, owner_user_id=user.id, surface="jobs", scope=scope)
    except CollectionCursorError:
        raise HTTPException(422, "Invalid jobs cursor") from None
    attention_required=history_attention_required_expression()
    query=db.query(TranscriptionJob).options(selectinload(TranscriptionJob.speakers), selectinload(TranscriptionJob.sources).selectinload(TranscriptionJobSource.source)).filter(TranscriptionJob.project_id==p.id, TranscriptionJob.owner_user_id==user.id)
    if p.history_reset_at is not None:
        query=query.filter(or_(TranscriptionJob.status.in_([JobStatus.queued, JobStatus.processing]), TranscriptionJob.finished_at > p.history_reset_at, attention_required))
    if position:
        created_at,row_id=position
        query=query.filter((TranscriptionJob.created_at < created_at) | ((TranscriptionJob.created_at == created_at) & (TranscriptionJob.id < row_id)))
    rows=query.order_by(TranscriptionJob.created_at.desc(), TranscriptionJob.id.desc()).limit(page_size+1).all()
    rows,next_cursor=page_envelope(rows, page_size=page_size, timestamp_attribute="created_at", secret=sess.csrf_hash, owner_user_id=user.id, surface="jobs", scope=scope)
    attention_job_ids = {
        row_id
        for (row_id,) in db.query(TranscriptionJob.id)
        .filter(
            TranscriptionJob.id.in_([row.id for row in rows]),
            history_attention_required_expression(),
        )
        .all()
    }
    primary_urls = load_primary_output_urls(db, owner_user_id=user.id, job_ids=[row.id for row in rows])
    payloads=[]
    for row in rows:
        payload=job_payload(row)
        payload["history_attention_required"]=row.id in attention_job_ids
        if row.id in primary_urls:
            payload["primary_output_url"] = primary_urls[row.id]
        payloads.append(payload)
    return {"jobs":payloads, "next_cursor": next_cursor, "page_size": page_size}

@app.post("/api/projects/{project_id}/history/clear")
def clear_project_history(project_id: str, data: ConfirmedClearIn, request: Request, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=require_recent_auth(pair,request=request,db=db); limiter.check("history:clear:"+user.id, 10, 3600); p=owned_project_or_404(db,user,project_id)
    reset_at=utcnow()
    terminal_scope=(
        TranscriptionJob.project_id==p.id,
        TranscriptionJob.owner_user_id==user.id,
        TranscriptionJob.status.in_([JobStatus.completed, JobStatus.failed, JobStatus.cancelled]),
        or_(TranscriptionJob.finished_at.is_(None), TranscriptionJob.finished_at <= reset_at),
    )
    attention_required=history_attention_required_expression()
    hidden_job_count=db.query(TranscriptionJob).filter(*terminal_scope, ~attention_required).count()
    preserved_job_count=db.query(TranscriptionJob).filter(*terminal_scope, attention_required).count()
    p.history_reset_at=reset_at; p.updated_at=reset_at
    audit(db,"history.cleared",actor_user_id=user.id,subject_user_id=user.id)
    db.commit()
    return {"ok": True, "reset_at": reset_at.isoformat(), "hidden_job_count": hidden_job_count, "preserved_job_count": preserved_job_count}

@app.get("/api/projects/{project_id}/jobs/progress")
def get_project_job_progress(response: Response, project_id: str, job_id: list[str]=Query(default=[]), pair=Depends(current_session), db: Session=Depends(get_db)):
    _,user=pair; p=owned_project_or_404(db,user,project_id); _browser_capability_cache_headers(response)
    if len(job_id)>50 or len(job_id)!=len(set(job_id)) or any(not valid_uuid(value) for value in job_id):
        raise HTTPException(422, "Invalid job progress scope")
    query=db.query(TranscriptionJob).filter(TranscriptionJob.project_id==p.id, TranscriptionJob.owner_user_id==user.id, TranscriptionJob.status.in_([JobStatus.queued, JobStatus.processing]))
    if job_id:
        query=query.filter(TranscriptionJob.id.in_(job_id))
    limit=len(job_id) if job_id else 100
    rows=query.order_by(TranscriptionJob.created_at.desc(), TranscriptionJob.id.desc()).limit(limit+1).all()
    truncated=len(rows)>limit
    rows=rows[:limit]
    try:
        return {"jobs": load_browser_job_progress_payloads(db, rows), "truncated": truncated, "limit": limit}
    except Exception:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Не удалось загрузить прогресс задач") from None

@app.get("/api/projects/{project_id}/transcription-analytics")
def get_project_transcription_analytics(response: Response, project_id: str, pair=Depends(current_session), db: Session=Depends(get_db)):
    _,user=pair; p=owned_project_or_404(db,user,project_id); _browser_capability_cache_headers(response)
    try:
        return load_transcription_analytics_payload(db, owner_user_id=user.id, project_id=p.id, since=p.analytics_reset_at)
    except Exception:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Не удалось загрузить аналитику транскрибаций") from None

@app.post("/api/projects/{project_id}/transcription-analytics/clear")
def clear_project_transcription_analytics(project_id: str, data: ConfirmedClearIn, request: Request, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=require_recent_auth(pair,request=request,db=db); limiter.check("analytics:clear:"+user.id, 10, 3600); p=owned_project_or_404(db,user,project_id)
    reset_at=utcnow()
    hidden_job_count=db.query(TranscriptionJob).filter(TranscriptionJob.project_id==p.id, TranscriptionJob.owner_user_id==user.id, TranscriptionJob.created_at <= reset_at).count()
    p.analytics_reset_at=reset_at; p.updated_at=reset_at
    audit(db,"analytics.cleared",actor_user_id=user.id,subject_user_id=user.id)
    db.commit()
    return {"ok": True, "reset_at": reset_at.isoformat(), "hidden_job_count": hidden_job_count}

@app.post("/api/projects/{project_id}/jobs", deprecated=True)
def create_transcription_job(project_id: str, data: TranscriptionJobCreateIn, request: Request, response: Response, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("job:create:"+user.id, 60, 3600); p=owned_project_or_404(db,user,project_id)
    output_folder_id=clean_drive_id(p.output_drive_folder_id, "ID папки Google Drive")
    if not output_folder_id:
        raise HTTPException(422, "Выберите папку Google Drive для результатов.")
    provider_credential_id=_resolve_active_elevenlabs_credential_id(db, user, data.provider_credential_id)
    language=clean_job_language(data.language)
    options_json=safe_job_options(data.options)
    sources=validate_job_sources(db, p.id, data.source_ids)
    _require_catalog_identity_locks(db, user, sources)
    sources=validate_job_sources(db, p.id, data.source_ids, lock_mode="no_key_update")
    existing_result_matches=load_existing_result_matches(
        db,
        owner_user_id=user.id,
        sources=sources,
        target_settings=elevenlabs_effective_settings(
            language_mode=browser_language_mode(language),
            diarization_enabled=job_diarization_enabled(options_json),
        ),
    )
    if any(
        existing_result_matches.get(source.id) is None
        or existing_result_matches[source.id].status
        != ExistingResultMatchStatus.no_match
        for source in sources
    ):
        raise HTTPException(409, "Используйте пакетную проверку для явного решения")
    job=TranscriptionJob(project_id=p.id, owner_user_id=user.id, trace_id=getattr(request.state,"trace_id",None), status=JobStatus.queued, provider_credential_id=provider_credential_id, title=clean_job_title(data.title), language=language, options_json=options_json)
    job.apply_output_folder_snapshot(folder_id=output_folder_id, folder_url=p.output_drive_folder_url, folder_name=p.output_drive_folder_name)
    db.add(job); db.flush()
    for idx, src in enumerate(sources):
        db.add(TranscriptionJobSource(job_id=job.id, source_id=src.id, position=idx, status=JobSourceStatus.queued))
    audit(db,"job.created",actor_user_id=user.id,subject_user_id=user.id,project_id=p.id,job_id=job.id,source_count=len(sources))
    db.commit(); write_diagnostic_event(owner_user_id=user.id, component="api", event_code="JOB_CREATED", project_id=p.id, job_id=job.id, request_id=getattr(request.state,"request_id",None), correlation_id=getattr(request.state,"correlation_id",None), metadata={"source_count": len(sources), "credential_selected": True}); db.refresh(job)
    response.headers["Deprecation"]="true"
    response.headers["Link"]=f'</api/projects/{p.id}/jobs/batch>; rel="successor-version"'
    return job_payload(job, include_sources=True)

@app.get("/api/jobs/{job_id}")
def get_transcription_job(job_id: str, pair=Depends(current_session), db: Session=Depends(get_db)):
    _,user=pair; job=owned_job_or_404(db,user,job_id)
    return job_payload(job, include_sources=True)

@app.post("/api/jobs/{job_id}/dismiss")
def dismiss_terminal_job(job_id: str, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("job:dismiss:"+user.id, 240, 3600); job=owned_job_or_404(db,user,job_id)
    if job.status not in (JobStatus.completed, JobStatus.failed, JobStatus.cancelled):
        raise HTTPException(409, "Только завершённую задачу можно убрать в историю")
    if db.query(TranscriptionJob.id).filter(
        TranscriptionJob.id == job.id,
        history_attention_required_expression(),
    ).first():
        raise HTTPException(409, "Сначала разрешите неопределённый результат задачи")
    if job.terminal_dismissed_at is None:
        now=utcnow(); job.terminal_dismissed_at=now; job.updated_at=now
        audit(db,"job.dismissed",actor_user_id=user.id,subject_user_id=user.id,project_id=job.project_id,job_id=job.id)
        db.commit(); db.refresh(job)
    return job_payload(job)


@app.post("/api/jobs/{job_id}/attention-resolution")
def resolve_job_history_attention(
    job_id: str,
    data: JobAttentionResolutionIn,
    request: Request,
    pair=Depends(require_csrf),
    db: Session=Depends(get_db),
    _=Depends(require_same_origin),
):
    _, user = require_recent_auth(pair,request=request,db=db)
    limiter.check("job:attention-resolution:" + user.id, 20, 3600)
    job = db.execute(
        select(TranscriptionJob)
        .where(
            TranscriptionJob.id == job_id,
            TranscriptionJob.owner_user_id == user.id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(404, "Не найдено")
    if job.history_attention_resolved_at is not None:
        if (
            job.history_attention_resolution == data.resolution
            and job.history_attention_linked_job_id == data.linked_job_id
        ):
            payload = job_payload(job)
            payload["history_attention_required"] = False
            return payload
        raise HTTPException(409, detail={"reason": "attention_resolution_conflict"})
    if not db.query(TranscriptionJob.id).filter(
        TranscriptionJob.id == job.id,
        history_attention_required_expression(),
    ).first():
        raise HTTPException(409, detail={"reason": "attention_not_required"})
    linked_job = None
    if data.resolution == "linked_later_result":
        linked_job = owned_job_or_404(db, user, data.linked_job_id or "")
        valid_link = confirmed_later_results_query(db, job).filter(
            TranscriptionJob.id == linked_job.id,
        ).first() is not None
        if not valid_link:
            raise HTTPException(409, detail={"reason": "linked_job_not_confirmed"})
    now = utcnow()
    job.history_attention_resolved_at = now
    job.history_attention_resolution = data.resolution
    job.history_attention_linked_job_id = linked_job.id if linked_job else None
    job.terminal_dismissed_at = now
    job.updated_at = now
    audit(
        db,
        "job.history_attention_resolved",
        actor_user_id=user.id,
        subject_user_id=user.id,
        project_id=job.project_id,
        job_id=job.id,
        resolution=data.resolution,
        linked_job_id=job.history_attention_linked_job_id,
        possible_provider_spend_acknowledged=True,
    )
    db.commit()
    db.refresh(job)
    payload = job_payload(job)
    payload["history_attention_required"] = False
    return payload

@app.get("/api/jobs/{job_id}/retry")
def get_job_retry(job_id: str, pair=Depends(current_session), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("job:retry:get:"+user.id, 120, 3600)
    job=owned_job_or_404(db,user,job_id)
    return compute_explicit_retry_readiness(db, job, now=utcnow().replace(tzinfo=None)).payload(job)

@app.post("/api/jobs/{job_id}/retry")
def post_job_retry(job_id: str, request: Request, data: JobRetryIn | None = None, pair=Depends(require_csrf), db: Session=Depends(get_db), _=Depends(require_same_origin)):
    _,user=pair; limiter.check("job:retry:post:"+user.id, 10, 3600)
    job=owned_job_or_404(db,user,job_id)
    initial_readiness = compute_explicit_retry_readiness(db, job, now=utcnow().replace(tzinfo=None))
    if job.error_code == "media_duration_too_long":
        raise HTTPException(
            409,
            detail={
                "reason": "media_duration_too_long",
                "max_seconds": settings.media_max_duration_seconds,
            },
        )
    if job.error_code == "media_duration_confirmation_required":
        from .long_media_preflight import long_media_preflight_payload
        duration_preflight = long_media_preflight_payload(job)
        if duration_preflight is None:
            # Old failures have no measured quote. The duration guard still
            # requires explicit confirmation for a long source before STT.
            job.long_duration_cost_confirmed=False
        elif not (data and data.confirm_long_duration_cost and
                  data.long_duration_confirmation_token == duration_preflight["confirmation_token"]):
            raise HTTPException(
                409,
                detail={
                    "reason": "long_duration_confirmation_required",
                    "warning_seconds": settings.media_duration_warning_seconds,
                    "max_seconds": settings.media_max_duration_seconds,
                    "preflight": duration_preflight,
                },
            )
        else:
            job.long_duration_cost_confirmed=True
        db.flush()
    if requires_provider_cost_confirmation(initial_readiness) and not (data and data.confirm_remaining_provider_cost):
        raise HTTPException(409, "Требуется подтверждение стоимости оставшихся частей")
    write_diagnostic_event(owner_user_id=user.id, component="api", event_code="JOB_RETRY_REQUESTED", project_id=job.project_id, job_id=job.id, request_id=getattr(request.state,"request_id",None), correlation_id=getattr(request.state,"correlation_id",None), metadata={"attempt_number": job.attempt_count or 0, "retry_available": False, "boundary":"retry_api"})
    audit(db,"job.retry_requested",actor_user_id=user.id,subject_user_id=user.id,project_id=job.project_id,job_id=job.id)
    result = queue_retry(db, owner_user_id=user.id, job_id=job.id, now=utcnow().replace(tzinfo=None))
    if result is None: raise HTTPException(404, "Не найдено")
    queued, ready = result.job, result.readiness
    if not ready.available or queued.status != JobStatus.queued:
        audit(db,"job.retry_blocked",actor_user_id=user.id,subject_user_id=user.id,outcome="rejected",project_id=job.project_id,job_id=job.id,retry_reason=ready.reason.value)
        db.commit()
        write_diagnostic_event(owner_user_id=user.id, component="api", event_code="JOB_RETRY_BLOCKED", project_id=job.project_id, job_id=job.id, request_id=getattr(request.state,"request_id",None), correlation_id=getattr(request.state,"correlation_id",None), metadata={"retry_reason": ready.reason.value, "retry_available": False, "retry_safe_source_count": ready.retry_safe_source_count, "missing_output_count": ready.missing_output_count, "boundary":"retry_api"})
        raise HTTPException(409, "Повтор недоступен")
    if result.transitioned:
        audit(db,"job.retry_queued",actor_user_id=user.id,subject_user_id=user.id,project_id=queued.project_id,job_id=queued.id)
    db.commit(); db.refresh(queued)
    if result.transitioned:
        write_diagnostic_event(owner_user_id=user.id, component="api", event_code="JOB_RETRY_QUEUED", project_id=queued.project_id, job_id=queued.id, request_id=getattr(request.state,"request_id",None), correlation_id=getattr(request.state,"correlation_id",None), metadata={"retry_reason":"available", "retry_available": True, "retry_safe_source_count": ready.retry_safe_source_count, "missing_output_count": ready.missing_output_count, "final_job_status": queued.status.value, "boundary":"retry_api"})
    return compute_explicit_retry_readiness(db, queued, now=utcnow().replace(tzinfo=None)).payload(queued)


@app.get("/api/jobs/{job_id}/outputs")
def get_transcription_job_outputs(job_id: str, pair=Depends(current_session), db: Session=Depends(get_db)):
    _,user=pair; job=owned_job_or_404(db,user,job_id)
    try:
        rows=load_browser_job_output_rows(db, job.id)
        outputs=[browser_job_output_payload(output, job_source, source) for output, job_source, source in rows]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Не удалось загрузить результаты задания") from None
    return {"job_id": job.id, "job_status": job.status.value, "output_count": len(outputs), "outputs": outputs}


@app.get("/api/jobs/{job_id}/speakers/{speaker_id}/sample")
def get_job_speaker_sample(job_id: str, speaker_id: str, pair=Depends(current_session), db: Session=Depends(get_db), _=Depends(require_same_origin)):
    _,user=pair; limiter.check("job:speaker-sample:"+user.id, 240, 3600)
    owned_job_or_404(db,user,job_id)
    try:
        sample=create_speaker_sample_audio(
            db,
            owner_user_id=user.id,
            job_id=job_id,
            speaker_id=speaker_id,
            settings=settings,
        )
    except SpeakerSampleError as exc:
        if exc.reason==SpeakerSampleReason.not_found:
            raise HTTPException(404,"Не найдено") from None
        if exc.reason==SpeakerSampleReason.source_unavailable:
            raise HTTPException(410,"Исходный файл больше недоступен") from None
        if exc.reason==SpeakerSampleReason.source_too_large:
            raise HTTPException(413,"Исходный файл слишком большой") from None
        raise HTTPException(503,"Не удалось подготовить фрагмент голоса") from None
    return FastAPIResponse(
        content=sample.content,
        media_type=sample.media_type,
        headers={"Cache-Control":"no-store","Pragma":"no-cache","Content-Disposition":"inline"},
    )


@app.put("/api/jobs/{job_id}/speakers/{speaker_id}/assignment")
def put_job_speaker_assignment(job_id: str, speaker_id: str, data: SpeakerAssignmentIn, pair=Depends(require_csrf), db: Session=Depends(get_db), _=Depends(require_same_origin)):
    _,user=pair; limiter.check("job:speaker-assignment:"+user.id, 120, 3600)
    job=owned_job_or_404(db,user,job_id)
    try:
        result=assign_speaker_profile(
            db,
            owner_user_id=user.id,
            job_id=job.id,
            speaker_id=speaker_id,
            profile_id=data.profile_id,
            settings=settings,
            now=utcnow(),
        )
    except SpeakerAssignmentError as exc:
        db.rollback()
        if exc.reason==SpeakerAssignmentReason.not_found:
            raise HTTPException(404,"Не найдено") from None
        if exc.reason==SpeakerAssignmentReason.profile_unavailable:
            raise HTTPException(422,"Профиль спикера недоступен") from None
        if exc.reason==SpeakerAssignmentReason.output_unavailable:
            raise HTTPException(409,"Результат транскрибации ещё недоступен") from None
        if exc.reason==SpeakerAssignmentReason.google_connection_unavailable:
            raise HTTPException(409,"Google Drive недоступен") from None
        if exc.reason==SpeakerAssignmentReason.document_changed:
            raise HTTPException(409,"Документ изменён и требует ручной проверки") from None
        raise HTTPException(502,"Не удалось обновить Google Docs") from None
    audit(db,"job.speaker_assigned",actor_user_id=user.id,subject_user_id=user.id,project_id=job.project_id,job_id=job.id)
    db.commit()
    return {"speaker":result.payload,"document_changed":result.document_changed}



@app.get("/api/jobs/{job_id}/output-reconciliation")
def get_output_reconciliation(job_id: str, pair=Depends(current_session), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("job:output-reconciliation:get:"+user.id, 120, 3600)
    try:
        payload = reconciliation_status_payload(db, owner_user_id=user.id, job_id=job_id)
        job = owned_job_or_404(db, user, job_id)
        attention_required = db.query(TranscriptionJob.id).filter(
            TranscriptionJob.id == job.id, history_attention_required_expression(),
        ).first() is not None
        payload["attention_candidates"] = recent_attention_candidates(db, job) if attention_required else []
        return payload
    except OutputReconciliationError:
        raise HTTPException(404, "Не найдено")

@app.post("/api/jobs/{job_id}/output-reconciliation/check")
def check_output_reconciliation(job_id: str, request: Request, pair=Depends(require_csrf), db: Session=Depends(get_db), _=Depends(require_same_origin)):
    _,user=pair; limiter.check("job:output-reconciliation:check:"+user.id, 10, 3600)
    job=owned_job_or_404(db,user,job_id)
    if job.status in {JobStatus.queued, JobStatus.processing}:
        raise HTTPException(409, "Output reconciliation unavailable")
    if not reconciliation_status_payload(db, owner_user_id=user.id, job_id=job.id)["available"]:
        # No lookup was possible: do not refresh Google credentials or claim not-found.
        return {"job_id": job.id, "checked": 0, "resolved": 0, "unresolved": 0, "conflicts": 0}
    try:
        conn=active_google_connection_for_user(db, user_id=user.id); require_drive_file_scope(conn)
        access_token=get_cloud_files_provider().access_token(db, user_id=user.id, settings=settings)
    except GoogleConnectionAccessError as exc:
        write_diagnostic_event(owner_user_id=user.id, component="api", event_code="OUTPUT_RECONCILIATION_FAILED", project_id=job.project_id, job_id=job.id, request_id=getattr(request.state,"request_id",None), correlation_id=getattr(request.state,"correlation_id",None), metadata={"case_status":"reconciliation_required","resolved":False})
        raise HTTPException(409, "Google connection unavailable")
    write_diagnostic_event(owner_user_id=user.id, component="api", event_code="OUTPUT_RECONCILIATION_CHECK_STARTED", project_id=job.project_id, job_id=job.id, request_id=getattr(request.state,"request_id",None), correlation_id=getattr(request.state,"correlation_id",None), metadata={"case_status":"reconciliation_required"})
    def lookup(token, folder_id):
        return list_reconciliation_candidates(access_token, folder_id=folder_id, app_property_key=OUTPUT_RECONCILIATION_APP_PROPERTY, token=token)
    try:
        result=check_job_output_reconciliation(db, owner_user_id=user.id, job_id=job.id, lookup=lookup, now=utcnow().replace(tzinfo=None))
        audit(db,"job.output_reconciliation_checked",actor_user_id=user.id,subject_user_id=user.id,project_id=job.project_id,job_id=job.id,checked=result.checked,resolved=result.resolved,unresolved=result.unresolved,conflicts=result.conflicts)
        db.commit()
    except GoogleDriveReconciliationError:
        db.rollback(); raise HTTPException(502, "Google Drive reconciliation unavailable")
    except OutputReconciliationError as exc:
        db.rollback(); raise HTTPException(409 if exc.reason!=OutputReconciliationReason.not_found else 404, "Output reconciliation unavailable")
    code = "OUTPUT_RECONCILIATION_RESOLVED" if result.resolved else "OUTPUT_RECONCILIATION_CONFLICT" if result.conflicts else "OUTPUT_RECONCILIATION_NOT_FOUND"
    write_diagnostic_event(owner_user_id=user.id, component="api", event_code=code, project_id=job.project_id, job_id=job.id, request_id=getattr(request.state,"request_id",None), correlation_id=getattr(request.state,"correlation_id",None), metadata={"case_status":"resolved" if result.resolved else "conflict" if result.conflicts else "reconciliation_required", "resolved": bool(result.resolved), "aggregate_count": result.checked})
    return {"job_id":job.id,"checked":result.checked,"resolved":result.resolved,"unresolved":result.unresolved,"conflicts":result.conflicts}

@app.post("/api/jobs/{job_id}/cancel")
def cancel_transcription_job(job_id: str, request: Request, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("job:cancel:"+user.id, 120, 3600); job=owned_job_or_404(db,user,job_id)
    _, changed, event_type = request_job_cancellation(db, job_id=job.id, now=utcnow())
    if changed and event_type:
        audit(db,event_type,actor_user_id=user.id,subject_user_id=user.id,project_id=job.project_id,job_id=job.id)
        db.commit(); db.refresh(job); event_code="JOB_CANCELLED" if job.status==JobStatus.cancelled else "JOB_CANCEL_REQUESTED"; write_diagnostic_event(owner_user_id=user.id, component="api", event_code=event_code, project_id=job.project_id, job_id=job.id, request_id=getattr(request.state,"request_id",None), correlation_id=getattr(request.state,"correlation_id",None), metadata={"final_job_status": job.status.value})
    return job_payload(job, include_sources=True)


def _diag_dt(value: datetime | None, default: datetime) -> datetime:
    if value is None: return default
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value

def _diag_filters(db: Session, user: User, *, start=None, end=None, level=None, component=None, event_code=None, project_id=None, job_id=None):
    now_dt=utcnow().replace(tzinfo=None); end_dt=_diag_dt(end, now_dt); start_dt=_diag_dt(start, end_dt-timedelta(days=1))
    if end_dt < start_dt or end_dt - start_dt > timedelta(days=7): raise HTTPException(422, "Diagnostic range must be at most 7 days")
    if level and level not in DiagnosticLevel.__members__: raise HTTPException(422, "Invalid diagnostic level")
    if component and component not in {c.value for c in DiagnosticComponent}: raise HTTPException(422, "Invalid diagnostic component")
    if event_code and event_code not in REGISTRY: raise HTTPException(422, "Invalid diagnostic event code")
    if project_id and not valid_uuid(project_id): raise HTTPException(422, "Invalid project id")
    if job_id and not valid_uuid(job_id): raise HTTPException(422, "Invalid job id")
    if project_id:
        p=db.get(Project, project_id)
        if not p or p.owner_user_id!=user.id: raise HTTPException(404, "Не найдено")
    if job_id:
        j=db.get(TranscriptionJob, job_id) or db.get(AudioPreparationJob, job_id)
        if not j or j.owner_user_id!=user.id: raise HTTPException(404, "Не найдено")
        if project_id and j.project_id != project_id: raise HTTPException(404, "Не найдено")
    q=db.query(DiagnosticEvent).filter(DiagnosticEvent.owner_user_id==user.id, DiagnosticEvent.first_occurred_at>=start_dt, DiagnosticEvent.first_occurred_at<=end_dt, DiagnosticEvent.expires_at>now_dt)
    if level: q=q.filter(DiagnosticEvent.level==DiagnosticLevel[level])
    if component: q=q.filter(DiagnosticEvent.component==DiagnosticComponent(component))
    if event_code: q=q.filter(DiagnosticEvent.event_code==event_code)
    if project_id: q=q.filter(DiagnosticEvent.project_id==project_id)
    if job_id: q=q.filter(or_(DiagnosticEvent.job_id==job_id, DiagnosticEvent.audio_preparation_job_id==job_id))
    return q, start_dt, end_dt

def _diag_payload(e: DiagnosticEvent):
    return {"id": e.id, "occurred_at": e.first_occurred_at.isoformat(), "last_occurred_at": e.last_occurred_at.isoformat(), "level": e.level.value, "component": e.component.value, "event_code": e.event_code, "trace_id": e.trace_id, "correlation_id": e.correlation_id, "request_id": e.request_id, "project_id": e.project_id, "job_id": e.operation_job_id, "metadata": json.loads(e.metadata_json or "{}"), "occurrence_count": e.occurrence_count}

def _owner_incident_summary(db: Session, user: User):
    rows=(
        db.query(OperationalIncident)
        .filter(OperationalIncident.owner_user_id==user.id)
        .order_by(
            OperationalIncident.status.in_(["pending","firing","acknowledged"]).desc(),
            OperationalIncident.updated_at.desc(),
            OperationalIncident.id.desc(),
        )
        .limit(20)
        .all()
    )
    deliveries={}
    if rows:
        for delivery in (
            db.query(OperationalAlertDelivery)
            .filter(OperationalAlertDelivery.incident_id.in_([row.id for row in rows]))
            .order_by(OperationalAlertDelivery.updated_at.desc(), OperationalAlertDelivery.id.desc())
            .all()
        ):
            deliveries.setdefault((delivery.incident_id,delivery.lifecycle_generation),delivery)
    return [incident_payload(row,delivery=deliveries.get((row.id,row.lifecycle_generation))) for row in rows]

def _system_summary(db: Session, user: User):
    conn=current_google_connection(db, user)
    active_creds=db.query(func.count(ProviderCredential.id)).filter(ProviderCredential.user_id==user.id, ProviderCredential.status==CredentialStatus.active, ProviderCredential.deleted_at.is_(None)).scalar() or 0
    api_identity=settings_runtime_identity(settings, expected_component="api")
    web_identity=load_web_runtime_identity()
    try:
        worker_status=load_worker_runtime_status(db, stale_after_seconds=settings.runtime_worker_stale_after_seconds)
    except Exception:
        worker_status={"status":"unavailable"}
    try:
        schema_revision=database_schema_revision(db)
    except Exception:
        schema_revision="unavailable"
    try:
        queue_status=queue_runtime_status(db)
    except Exception:
        queue_status={"status":"unavailable"}
    storage_status=source_storage_runtime_status(settings)
    try:
        provider_status=stt_provider_runtime_status(db, owner_user_id=user.id)
    except Exception:
        provider_status={"status":"unavailable", "availability":"unknown", "probe":"not_run"}
    provider_limit_available=(
        db.query(ProviderAccountSnapshot.id)
        .filter(
            ProviderAccountSnapshot.owner_user_id==user.id,
            ProviderAccountSnapshot.period_limit.is_not(None),
            ProviderAccountSnapshot.period_remaining.is_not(None),
        )
        .first()
        is not None
    )
    component_status={
        "web": runtime_identity_payload(web_identity),
        "api": runtime_identity_payload(api_identity),
        "worker": worker_status,
    }
    build={name: payload.get("build_id", "unavailable") for name,payload in component_status.items()}
    release_version=coherent_release_version(component_status)
    return {
        "environment": sanitize_build_id(settings.environment),
        "release_version": release_version,
        "schema_revision": schema_revision,
        "build": build,
        "components": component_status,
        "health": {
            "backend": "ready" if api_identity else "degraded",
            "database": "reachable",
            "queue": queue_status,
            "worker": {"status": worker_status.get("status", "unavailable")},
            "object_storage": storage_status,
            "stt_provider": provider_status,
            "email": {"status": "not_configured"},
        },
        "google_drive": {"connected": bool(conn and conn.status==GoogleConnectionStatus.active), "scope_ready": bool(conn and conn.status==GoogleConnectionStatus.active and has_picker_browser_scope_boundary(conn.scopes))},
        "provider_credentials": {"active_count": int(active_creds), "ready": int(active_creds)>0},
        "diagnostics": {"recording_enabled": True, "debug_recording": "inactive", "retention_days": settings.diagnostic_retention_days, "debug_retention_hours": settings.diagnostic_debug_retention_hours},
        "alerts": {
            "incident_monitoring": "enabled",
            "telegram": "ready" if settings.telegram_alerts_configured() else "not_configured",
            "email": "not_configured",
            "storage_limit": "configured" if settings.alert_storage_limit_bytes is not None else "not_configured",
            "api_limit": "configured" if provider_limit_available else "unavailable",
            "incidents": _owner_incident_summary(db,user),
        },
        "report_limits": {"max_days": 7, "max_timeline_events": settings.diagnostic_report_max_events},
    }


DEBUG_SESSION_MAX_MINUTES = 30
PWA_EVENT_CODES = frozenset({"PWA_APP_ERROR", "PWA_UNHANDLED_REJECTION", "PWA_API_REQUEST_FAILED", "PWA_ROUTE_ERROR", "PWA_SERVICE_WORKER_ERROR"})
PWA_METADATA_KEYS = frozenset({"boundary", "duration_ms", "error_code", "retryable", "http_status_category", "http_status", "endpoint_group", "upstream_request_id", "rejection_category"})

def _debug_now() -> datetime:
    return utcnow()

def _debug_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

def _active_debug_session(db: Session, user: User, now_dt: datetime | None = None) -> DiagnosticDebugSession | None:
    now_dt = now_dt or _debug_now()
    row = db.query(DiagnosticDebugSession).filter(DiagnosticDebugSession.owner_user_id==user.id).first()
    if not row or row.ended_at is not None:
        return None
    return row if _debug_aware(row.expires_at) > now_dt else None

def _debug_session_payload(row: DiagnosticDebugSession | None, now_dt: datetime | None = None):
    now_dt = now_dt or _debug_now()
    active = bool(row and row.ended_at is None and _debug_aware(row.expires_at) > now_dt)
    payload={"active": active, "max_duration_minutes": DEBUG_SESSION_MAX_MINUTES}
    if active:
        payload["started_at"] = _debug_aware(row.started_at).isoformat()
        payload["expires_at"] = _debug_aware(row.expires_at).isoformat()
    return payload

@app.get("/api/diagnostics/debug-session")
def diagnostics_debug_session(pair=Depends(current_session), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("diagnostics:debug-session:"+user.id, 120, 3600); return _debug_session_payload(_active_debug_session(db,user))

@app.post("/api/diagnostics/debug-session")
def start_diagnostics_debug_session(data: DiagnosticDebugSessionIn, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("diagnostics:debug-session:start:"+user.id, 10, 3600); now_dt=_debug_now(); existing=_active_debug_session(db,user,now_dt)
    if existing: raise HTTPException(409, _debug_session_payload(existing, now_dt))
    row=db.query(DiagnosticDebugSession).filter(DiagnosticDebugSession.owner_user_id==user.id).first()
    if row:
        row.started_at=now_dt; row.expires_at=now_dt+timedelta(minutes=data.duration_minutes); row.ended_at=None
    else:
        row=DiagnosticDebugSession(owner_user_id=user.id, started_at=now_dt, expires_at=now_dt+timedelta(minutes=data.duration_minutes))
        db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        conflict=_active_debug_session(db,user,now_dt)
        raise HTTPException(409, _debug_session_payload(conflict, now_dt))
    db.refresh(row); return _debug_session_payload(row, now_dt)

@app.delete("/api/diagnostics/debug-session")
def stop_diagnostics_debug_session(pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("diagnostics:debug-session:stop:"+user.id, 30, 3600); now_dt=_debug_now(); row=_active_debug_session(db,user,now_dt)
    if row:
        row.ended_at=now_dt; db.commit()
    return _debug_session_payload(None, now_dt)

def _validate_pwa_scope(db: Session, user: User, event: PwaDiagnosticEventIn):
    if event.project_id and not valid_uuid(event.project_id): raise HTTPException(422, "Invalid project id")
    if event.job_id and not valid_uuid(event.job_id): raise HTTPException(422, "Invalid job id")
    if event.project_id:
        p=db.get(Project,event.project_id)
        if not p or p.owner_user_id != user.id: raise HTTPException(404, "Не найдено")
    if event.job_id:
        j=db.get(TranscriptionJob,event.job_id)
        if not j or j.owner_user_id != user.id: raise HTTPException(404, "Не найдено")
        if event.project_id and j.project_id != event.project_id: raise HTTPException(404, "Не найдено")

@app.post("/api/diagnostics/pwa-events")
def ingest_pwa_diagnostics(data: PwaDiagnosticsIn, request: Request, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("diagnostics:pwa-ingest:"+user.id, 120, 3600); now_dt=_debug_now(); persisted=[]
    active_debug = _active_debug_session(db,user,now_dt) is not None
    for event in data.events:
        if event.event_code not in PWA_EVENT_CODES: raise HTTPException(422, "Invalid diagnostic event code")
        if event.metadata and (set(event.metadata) - PWA_METADATA_KEYS): raise HTTPException(422, "Invalid diagnostic metadata")
        level = event.level or REGISTRY[event.event_code].level
        if level == "DEBUG" and not active_debug: raise HTTPException(403, "DEBUG diagnostics session is not active")
        if level != REGISTRY[event.event_code].level and level != "DEBUG": raise HTTPException(422, "Invalid diagnostic level")
        _validate_pwa_scope(db,user,event)
        corr = event.correlation_id if event.correlation_id and valid_correlation_id(event.correlation_id) else None
        result=write_diagnostic_event(owner_user_id=user.id, component="web", event_code=event.event_code, level=level, project_id=event.project_id, job_id=event.job_id, correlation_id=corr, request_id=getattr(request.state,"request_id",None), metadata=event.metadata or {}, now=now_dt, allow_debug_override=(level == "DEBUG" and active_debug))
        if not result.accepted: raise HTTPException(422, "Invalid diagnostic event")
        if result.event_id: persisted.append(result.event_id)
    return {"accepted": len(data.events), "persisted": len(persisted)}

@app.get("/api/diagnostics/events")
def diagnostics_events(start: datetime|None=Query(None), end: datetime|None=Query(None), level: str|None=Query(None, min_length=1, max_length=10), component: str|None=Query(None, min_length=1, max_length=20), event_code: str|None=Query(None, min_length=1, max_length=80), project_id: str|None=Query(None, min_length=36, max_length=36), job_id: str|None=Query(None, min_length=36, max_length=36), cursor: str|None=Query(None, max_length=1200), page_size: int=Query(50, ge=1, le=200), pair=Depends(current_session), db: Session=Depends(get_db)):
    sess,user=pair; limiter.check("diagnostics:events:"+user.id, 120, 3600); cleanup_expired_diagnostics()
    cursor_position = None
    if cursor:
        decoded=decode_cursor_payload(cursor, sess.csrf_hash)
        if not decoded: raise HTTPException(422, "Invalid diagnostic cursor")
        cdt,cid,signed_ctx=decoded
        if signed_ctx.get("owner") != user.id: raise HTTPException(422, "Invalid diagnostic cursor")
        for name, supplied in {"level": level, "component": component, "event_code": event_code, "project_id": project_id, "job_id": job_id}.items():
            if supplied is not None and supplied != signed_ctx.get(name):
                raise HTTPException(422, "Invalid diagnostic cursor")
        if start is not None and _diag_dt(start, start).isoformat() != signed_ctx.get("start"):
            raise HTTPException(422, "Invalid diagnostic cursor")
        if end is not None and _diag_dt(end, end).isoformat() != signed_ctx.get("end"):
            raise HTTPException(422, "Invalid diagnostic cursor")
        start = datetime.fromisoformat(signed_ctx["start"]) if start is None else start
        end = datetime.fromisoformat(signed_ctx["end"]) if end is None else end
        level = signed_ctx.get("level") if level is None else level
        component = signed_ctx.get("component") if component is None else component
        event_code = signed_ctx.get("event_code") if event_code is None else event_code
        project_id = signed_ctx.get("project_id") if project_id is None else project_id
        job_id = signed_ctx.get("job_id") if job_id is None else job_id
        cursor_position = (cdt, cid, signed_ctx)
    q,start_dt,end_dt=_diag_filters(db,user,start=start,end=end,level=level,component=component,event_code=event_code,project_id=project_id,job_id=job_id)
    if cursor_position:
        cdt,cid,signed_ctx=cursor_position
        ctx=cursor_context(owner_user_id=user.id, start=start_dt, end=end_dt, level=level, component=component, event_code=event_code, project_id=project_id, job_id=job_id)
        if ctx != signed_ctx: raise HTTPException(422, "Invalid diagnostic cursor")
        q=q.filter((DiagnosticEvent.first_occurred_at < cdt) | ((DiagnosticEvent.first_occurred_at == cdt) & (DiagnosticEvent.id < cid)))
    rows=q.order_by(DiagnosticEvent.first_occurred_at.desc(), DiagnosticEvent.id.desc()).limit(page_size+1).all()
    next_cursor=None
    if len(rows)>page_size:
        last=rows[page_size-1]; ctx=cursor_context(owner_user_id=user.id, start=start_dt, end=end_dt, level=level, component=component, event_code=event_code, project_id=project_id, job_id=job_id); next_cursor=encode_cursor(last.first_occurred_at,last.id,ctx,sess.csrf_hash); rows=rows[:page_size]
    return {"events": [_diag_payload(r) for r in rows], "next_cursor": next_cursor, "period": {"start": start_dt.isoformat(), "end": end_dt.isoformat()}}

@app.get("/api/diagnostics/system")
def diagnostics_system(pair=Depends(current_session), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("diagnostics:system:"+user.id, 120, 3600); return _system_summary(db,user)

@app.get("/api/diagnostics/incidents")
def diagnostics_incidents(pair=Depends(current_session), db: Session=Depends(get_db)):
    _,user=pair
    limiter.check("diagnostics:incidents:"+user.id, 120, 3600)
    rows=(
        db.query(OperationalIncident)
        .filter(OperationalIncident.owner_user_id==user.id)
        .order_by(
            OperationalIncident.status.in_(["pending","firing","acknowledged"]).desc(),
            OperationalIncident.updated_at.desc(),
            OperationalIncident.id.desc(),
        )
        .limit(100)
        .all()
    )
    deliveries={}
    if rows:
        for delivery in (
            db.query(OperationalAlertDelivery)
            .filter(OperationalAlertDelivery.incident_id.in_([row.id for row in rows]))
            .order_by(OperationalAlertDelivery.updated_at.desc(), OperationalAlertDelivery.id.desc())
            .all()
        ):
            key=(delivery.incident_id, delivery.lifecycle_generation)
            deliveries.setdefault(key, delivery)
    return {
        "incidents":[incident_payload(row,delivery=deliveries.get((row.id,row.lifecycle_generation))) for row in rows],
        "transports":{
            "telegram":"ready" if settings.telegram_alerts_configured() else "not_configured",
            "email":"not_configured",
        },
        "evaluation":{
            "interval_seconds":settings.alert_evaluation_interval_seconds,
            "stuck_queue_seconds":settings.alert_stuck_queue_seconds,
            "provider_failure_threshold":settings.alert_provider_failure_threshold,
            "limit_remaining_percent":settings.alert_limit_remaining_percent,
        },
    }

@app.post("/api/diagnostics/incidents/{incident_id}/acknowledge")
def acknowledge_diagnostics_incident(incident_id: str, pair=Depends(require_csrf), db: Session=Depends(get_db), _=Depends(require_same_origin)):
    _,user=pair
    limiter.check("diagnostics:incident-ack:"+user.id, 30, 3600)
    if not valid_uuid(incident_id):
        raise HTTPException(404,"Не найдено")
    row=acknowledge_incident(db,owner_user_id=user.id,incident_id=incident_id,now=utcnow())
    if row is None:
        raise HTTPException(404,"Не найдено")
    audit(db,"operational_incident.acknowledged",actor_user_id=user.id,subject_user_id=user.id)
    db.commit(); db.refresh(row)
    delivery=(
        db.query(OperationalAlertDelivery)
        .filter(
            OperationalAlertDelivery.incident_id==row.id,
            OperationalAlertDelivery.lifecycle_generation==row.lifecycle_generation,
        )
        .order_by(OperationalAlertDelivery.updated_at.desc(),OperationalAlertDelivery.id.desc())
        .first()
    )
    return incident_payload(row,delivery=delivery)

DIAGNOSTIC_REPORT_OUTPUTS = {
    "md": ("text/markdown; charset=utf-8", "studio-diagnostics-report.md"),
    "json": ("application/json; charset=utf-8", "studio-diagnostics-report.json"),
    "yaml": ("application/yaml; charset=utf-8", "studio-diagnostics-report.yaml"),
    "toml": ("application/toml; charset=utf-8", "studio-diagnostics-report.toml"),
}

def _diagnostics_report_response(data: DiagnosticReportIn, pair, db: Session, report_format: str):
    _,user=pair; limiter.check("diagnostics:report:"+user.id, 10, 3600)
    q,start_dt,end_dt=_diag_filters(db,user,start=data.start,end=data.end,level=data.level,component=data.component,event_code=data.event_code,project_id=data.project_id,job_id=data.job_id)
    limit=settings.diagnostic_report_max_events
    rows=q.order_by(DiagnosticEvent.first_occurred_at.asc(), DiagnosticEvent.id.asc()).limit(limit+1).all(); truncated=len(rows)>limit; rows=rows[:limit]
    summary=_system_summary(db,user); generated=utcnow().replace(tzinfo=None).isoformat()
    report=build_diagnostic_report(
        generated_at=generated,
        start_at=start_dt.isoformat(),
        end_at=end_dt.isoformat(),
        system_summary=summary,
        events=[{
            "occurred_at": r.first_occurred_at.isoformat(),
            "level": r.level.value,
            "component": r.component.value,
            "event_code": r.event_code,
            "project_id": r.project_id,
            "job_id": r.operation_job_id,
            "trace_id": r.trace_id,
            "correlation_id": r.correlation_id,
            "request_id": r.request_id,
            "occurrence_count": r.occurrence_count,
            "metadata": json.loads(r.metadata_json or "{}"),
        } for r in rows],
        truncated=truncated,
        level=data.level,
        component=data.component,
        event_code=data.event_code,
        project_id=data.project_id,
        job_id=data.job_id,
        problem_description=data.problem_description,
        operation_reference=data.operation_reference,
    )
    media_type, filename=DIAGNOSTIC_REPORT_OUTPUTS[report_format]
    return FastAPIResponse(
        content=serialize_diagnostic_report(report, report_format),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )

@app.post("/api/diagnostics/report.md")
def diagnostics_report(data: DiagnosticReportIn, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    return _diagnostics_report_response(data, pair, db, "md")

@app.post("/api/diagnostics/report.json")
def diagnostics_report_json(data: DiagnosticReportIn, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    return _diagnostics_report_response(data, pair, db, "json")

@app.post("/api/diagnostics/report.yaml")
def diagnostics_report_yaml(data: DiagnosticReportIn, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    return _diagnostics_report_response(data, pair, db, "yaml")

@app.post("/api/diagnostics/report.toml")
def diagnostics_report_toml(data: DiagnosticReportIn, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    return _diagnostics_report_response(data, pair, db, "toml")

def google_connection_payload(c: GoogleConnection|None):
    picker_configured=settings.google_picker_configured()
    scope_ready=bool(c and c.status == GoogleConnectionStatus.active and has_picker_browser_scope_boundary(c.scopes))
    base={"connected": bool(c and c.status == GoogleConnectionStatus.active), "status": c.status.value if c else None, "google_email": c.google_email if c else None, "scopes": c.scopes if c else None, "connected_at": c.connected_at.isoformat() if c and c.connected_at else None, "revoked_at": c.revoked_at.isoformat() if c and c.revoked_at else None, "picker_configured": picker_configured, "picker_scope_ready": scope_ready, "picker_ready": bool(picker_configured and scope_ready)}
    if base["connected"] and not scope_ready:
        base["reconnect_required"] = True
    else:
        base["reconnect_required"] = False
    return base

def current_google_connection(db: Session, user: User) -> GoogleConnection|None:
    return db.query(GoogleConnection).filter_by(user_id=user.id, provider=GoogleProvider.google).first()

def google_config_or_503():
    from .google_oauth import GoogleOAuthConfigError, config_unavailable, load_google_oauth_config
    try:
        return load_google_oauth_config(settings)
    except GoogleOAuthConfigError:
        raise config_unavailable()

def google_maintenance_config_or_503():
    from .google_oauth import (
        GoogleOAuthConfigError,
        config_unavailable,
        load_google_maintenance_oauth_config,
    )
    try:
        return load_google_maintenance_oauth_config(settings)
    except GoogleOAuthConfigError:
        raise config_unavailable()

def google_maintenance_connection_payload(c: GoogleConnection|None):
    try:
        google_maintenance_config_or_503()
        configured=True
    except HTTPException:
        configured=False
    token_present=bool(
        c
        and c.maintenance_refresh_token_ciphertext
        and c.maintenance_refresh_token_nonce
        and c.maintenance_key_id
    )
    connected=bool(token_present and c and c.maintenance_revoked_at is None)
    account_match=bool(
        c
        and c.google_subject
        and c.maintenance_google_subject
        and c.google_subject == c.maintenance_google_subject
    )
    scope_ready=bool(
        c
        and has_maintenance_server_scope_boundary(c.maintenance_scopes)
    )
    primary_ready=bool(
        c
        and c.status == GoogleConnectionStatus.active
        and has_picker_browser_scope_boundary(c.scopes)
        and c.google_subject
    )
    ready=bool(
        configured
        and connected
        and account_match
        and scope_ready
        and primary_ready
    )
    if not c or (
        not token_present
        and c.maintenance_connected_at is None
        and c.maintenance_revoked_at is None
    ):
        connection_status=None
    elif c.maintenance_revoked_at is not None:
        connection_status="revoked"
    elif token_present:
        connection_status="active"
    else:
        connection_status="incomplete"
    return {
        "connected": connected,
        "status": connection_status,
        "google_email": c.maintenance_google_email if c else None,
        "scopes": c.maintenance_scopes if c else None,
        "connected_at": (
            c.maintenance_connected_at.isoformat()
            if c and c.maintenance_connected_at
            else None
        ),
        "revoked_at": (
            c.maintenance_revoked_at.isoformat()
            if c and c.maintenance_revoked_at
            else None
        ),
        "configured": configured,
        "account_match": account_match,
        "scope_ready": scope_ready,
        "ready": ready,
        "reconnect_required": bool(connection_status and not ready),
    }

@app.get("/api/google/connection")
def get_google_connection(pair=Depends(current_session), db: Session=Depends(get_db)):
    _,user=pair
    return google_connection_payload(current_google_connection(db, user))

@app.get("/api/google/maintenance/connection")
def get_google_maintenance_connection(pair=Depends(current_session), db: Session=Depends(get_db)):
    _,user=pair
    return google_maintenance_connection_payload(
        current_google_connection(db, user)
    )

def _start_google_oauth(
    *,
    db: Session,
    session,
    user: User,
    config,
    purpose: str,
    event_type: str,
):
    from .google_oauth import authorization_url
    raw_state=new_token()
    state=GoogleOAuthState(
        user_id=user.id,
        session_id=session.id,
        state_hash=token_hash(raw_state),
        purpose=purpose,
        expires_at=utcnow()+timedelta(
            seconds=settings.google_oauth_state_ttl_seconds
        ),
    )
    db.add(state)
    audit(
        db,
        event_type,
        actor_user_id=user.id,
        subject_user_id=user.id,
        session_id=session.id,
    )
    db.commit()
    return {
        "authorization_url": authorization_url(config, raw_state),
        "expires_at": state.expires_at.isoformat(),
    }

@app.post("/api/google/oauth/start")
def start_google_oauth(request: Request, response: Response, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    sess,user=require_recent_auth(pair,request=request,db=db); limiter.check("google:oauth:start:"+user.id, 20, 3600); _browser_capability_cache_headers(response)
    cleanup_expired_auth_state()
    cfg=google_config_or_503()
    from .google_oauth import PRIMARY_OAUTH_PURPOSE
    return _start_google_oauth(
        db=db,
        session=sess,
        user=user,
        config=cfg,
        purpose=PRIMARY_OAUTH_PURPOSE,
        event_type="google.oauth_started",
    )

@app.post("/api/google/maintenance/oauth/start")
def start_google_maintenance_oauth(request: Request, response: Response, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    sess,user=require_recent_auth(pair,request=request,db=db); limiter.check("google:maintenance:oauth:start:"+user.id, 20, 3600); _browser_capability_cache_headers(response)
    cleanup_expired_auth_state()
    conn=current_google_connection(db, user)
    if (
        not conn
        or conn.status != GoogleConnectionStatus.active
        or not conn.google_subject
        or not has_picker_browser_scope_boundary(conn.scopes)
    ):
        raise HTTPException(409, "google_primary_connection_required")
    cfg=google_maintenance_config_or_503()
    from .google_oauth import MAINTENANCE_OAUTH_PURPOSE
    return _start_google_oauth(
        db=db,
        session=sess,
        user=user,
        config=cfg,
        purpose=MAINTENANCE_OAUTH_PURPOSE,
        event_type="google.maintenance_oauth_started",
    )

GOOGLE_OAUTH_RESULTS = {
    "connected",
    "cancelled",
    "invalid_callback",
    "invalid_state",
    "exchange_failed",
    "offline_access_missing",
    "scope_unavailable",
    "account_identity_missing",
    "account_mismatch",
    "primary_connection_required",
}

def google_oauth_redirect(
    result: str,
    *,
    purpose: str="primary",
) -> RedirectResponse:
    from .google_oauth import MAINTENANCE_OAUTH_PURPOSE
    if result not in GOOGLE_OAUTH_RESULTS:
        result = "invalid_callback"
    query_key=(
        "google_maintenance_oauth"
        if purpose == MAINTENANCE_OAUTH_PURPOSE
        else "google_oauth"
    )
    base = settings.app_origin.rstrip("/")
    response = RedirectResponse(
        f"{base}/?{query_key}={result}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    response.headers["Cache-Control"] = "no-store"
    return response

def google_oauth_failed_redirect(
    db: Session,
    *,
    row: GoogleOAuthState|None,
    purpose: str,
    result: str,
) -> RedirectResponse:
    from .google_oauth import MAINTENANCE_OAUTH_PURPOSE
    audit(
        db,
        (
            "google.maintenance_oauth_failed"
            if purpose == MAINTENANCE_OAUTH_PURPOSE
            else "google.oauth_failed"
        ),
        actor_user_id=row.user_id if row else None,
        subject_user_id=row.user_id if row else None,
        outcome="failed",
        reason=result,
    )
    db.commit()
    return google_oauth_redirect(result, purpose=purpose)

@app.get("/api/google/oauth/callback")
def google_oauth_callback(request: Request, state: str|None=None, code: str|None=None, error: str|None=None, db: Session=Depends(get_db)):
    from .google_oauth import (
        GOOGLE_OAUTH_PURPOSES,
        MAINTENANCE_OAUTH_PURPOSE,
        PRIMARY_OAUTH_PURPOSE,
    )
    row=(
        db.query(GoogleOAuthState)
        .filter_by(state_hash=token_hash(state))
        .with_for_update()
        .first()
        if state
        else None
    )
    purpose=(
        row.purpose
        if row and row.purpose in GOOGLE_OAUTH_PURPOSES
        else PRIMARY_OAUTH_PURPOSE
    )
    if row and lock_oauth_initiator(db, state=row, raw_session=request.cookies.get(settings.cookie_name), now=utcnow()) is None:
        return google_oauth_redirect("invalid_state", purpose=purpose)
    if error:
        if (
            row
            and row.purpose in GOOGLE_OAUTH_PURPOSES
            and row.used_at is None
            and row.expires_at > utcnow()
        ):
            row.used_at=utcnow()
            return google_oauth_failed_redirect(
                db,
                row=row,
                purpose=purpose,
                result="cancelled",
            )
        return google_oauth_failed_redirect(
            db,
            row=None,
            purpose=purpose,
            result="cancelled",
        )
    if not state or not code:
        return google_oauth_redirect(
            "invalid_callback",
            purpose=purpose,
        )
    if (
        not row
        or row.purpose not in GOOGLE_OAUTH_PURPOSES
        or row.used_at is not None
        or row.expires_at <= utcnow()
    ):
        return google_oauth_redirect("invalid_state", purpose=purpose)
    cfg=(
        google_maintenance_config_or_503()
        if purpose == MAINTENANCE_OAUTH_PURPOSE
        else google_config_or_503()
    )
    from .google_oauth import exchange_code_for_tokens
    now=utcnow()
    row.used_at=now
    try:
        tokens=exchange_code_for_tokens(cfg, code)
    except Exception:
        return google_oauth_failed_redirect(
            db,
            row=row,
            purpose=purpose,
            result="exchange_failed",
        )
    if not tokens.refresh_token:
        return google_oauth_failed_redirect(
            db,
            row=row,
            purpose=purpose,
            result="offline_access_missing",
        )
    if not tokens.google_subject:
        return google_oauth_failed_redirect(
            db,
            row=row,
            purpose=purpose,
            result="account_identity_missing",
        )
    granted_scopes=tokens.scope or cfg.scopes
    scope_ready=(
        has_maintenance_server_scope_boundary(granted_scopes)
        if purpose == MAINTENANCE_OAUTH_PURPOSE
        else has_picker_browser_scope_boundary(granted_scopes)
    )
    if not scope_ready:
        return google_oauth_failed_redirect(
            db,
            row=row,
            purpose=purpose,
            result="scope_unavailable",
        )
    conn=db.query(GoogleConnection).filter_by(user_id=row.user_id, provider=GoogleProvider.google).first()
    if purpose == MAINTENANCE_OAUTH_PURPOSE:
        if not conn or conn.status != GoogleConnectionStatus.active:
            return google_oauth_failed_redirect(
                db,
                row=row,
                purpose=purpose,
                result="primary_connection_required",
            )
        if (
            not conn.google_subject
            or conn.google_subject != tokens.google_subject
        ):
            return google_oauth_failed_redirect(
                db,
                row=row,
                purpose=purpose,
                result="account_mismatch",
            )
        ct,nonce=encrypt(
            tokens.refresh_token,
            key(),
            google_maintenance_token_aad(row.user_id, conn.id),
        )
        conn.maintenance_google_subject=tokens.google_subject
        conn.maintenance_google_email=tokens.google_email
        conn.maintenance_scopes=granted_scopes
        conn.maintenance_refresh_token_ciphertext=ct
        conn.maintenance_refresh_token_nonce=nonce
        conn.maintenance_key_id=settings.credential_key_id
        conn.maintenance_connected_at=now
        conn.maintenance_revoked_at=None
        conn.updated_at=now
        audit(
            db,
            "google.maintenance_connected",
            actor_user_id=row.user_id,
            subject_user_id=row.user_id,
        )
        db.commit()
        return google_oauth_redirect("connected", purpose=purpose)
    if not conn:
        conn=GoogleConnection(user_id=row.user_id, provider=GoogleProvider.google, created_at=now)
        db.add(conn); db.flush()
    if (
        conn.maintenance_google_subject
        and conn.maintenance_google_subject != tokens.google_subject
    ):
        conn.maintenance_refresh_token_ciphertext=None
        conn.maintenance_refresh_token_nonce=None
        conn.maintenance_key_id=None
        conn.maintenance_revoked_at=now
    ct,nonce=encrypt(tokens.refresh_token, key(), google_token_aad(row.user_id, conn.id))
    conn.status=GoogleConnectionStatus.active; conn.google_subject=tokens.google_subject; conn.google_email=tokens.google_email; conn.scopes=granted_scopes; conn.refresh_token_ciphertext=ct; conn.refresh_token_nonce=nonce; conn.key_id=settings.credential_key_id; conn.connected_at=now; conn.revoked_at=None; conn.updated_at=now
    audit(db,"google.connected",actor_user_id=row.user_id,subject_user_id=row.user_id); db.commit()
    return google_oauth_redirect("connected", purpose=purpose)

@app.delete("/api/google/maintenance/connection")
def delete_google_maintenance_connection(request: Request, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=require_recent_auth(pair,request=request,db=db); limiter.check("google:maintenance:disconnect:"+user.id, 20, 3600)
    conn=current_google_connection(db, user)
    if not conn:
        return google_maintenance_connection_payload(None)
    now=utcnow()
    conn.maintenance_refresh_token_ciphertext=None
    conn.maintenance_refresh_token_nonce=None
    conn.maintenance_key_id=None
    conn.maintenance_revoked_at=now
    conn.updated_at=now
    audit(db,"google.maintenance_disconnected",actor_user_id=user.id,subject_user_id=user.id)
    db.commit()
    return google_maintenance_connection_payload(conn)

@app.delete("/api/google/connection")
def delete_google_connection(request: Request, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=require_recent_auth(pair,request=request,db=db); limiter.check("google:disconnect:"+user.id, 20, 3600)
    conn=current_google_connection(db, user)
    if not conn: return google_connection_payload(None)
    already_disconnected = (
        conn.status == GoogleConnectionStatus.revoked
        and conn.refresh_token_ciphertext is None
        and conn.refresh_token_nonce is None
        and conn.key_id is None
        and conn.maintenance_refresh_token_ciphertext is None
        and conn.maintenance_refresh_token_nonce is None
        and conn.maintenance_key_id is None
    )
    if already_disconnected:
        return google_connection_payload(conn)
    now=utcnow()
    conn.status=GoogleConnectionStatus.revoked
    conn.refresh_token_ciphertext=None
    conn.refresh_token_nonce=None
    conn.key_id=None
    conn.revoked_at=now
    conn.maintenance_refresh_token_ciphertext=None
    conn.maintenance_refresh_token_nonce=None
    conn.maintenance_key_id=None
    conn.maintenance_revoked_at=now
    conn.updated_at=now
    audit(db,"google.disconnected",actor_user_id=user.id,subject_user_id=user.id)
    db.commit()
    return google_connection_payload(conn)

def google_drive_metadata_payload(meta):
    return {"id": meta.id, "name": meta.name, "mime_type": meta.mime_type, "size_bytes": meta.size_bytes, "web_view_link": meta.web_view_link, "created_time": meta.created_time, "modified_time": meta.modified_time, "is_folder": meta.is_folder}

def refreshed_google_drive_access_token(db: Session, user: User) -> str:
    try:
        return get_cloud_files_provider().access_token(db, user_id=user.id, settings=settings)
    except GoogleConnectionAccessError as exc:
        if exc.reason == GoogleConnectionAccessReason.missing:
            raise HTTPException(404, "Google Drive connection is not connected")
        if exc.reason == GoogleConnectionAccessReason.inactive:
            raise HTTPException(409, "Google Drive connection is not active")
        if exc.reason == GoogleConnectionAccessReason.config_unavailable:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Google OAuth is not configured")
        raise HTTPException(502, "Google Drive metadata is unavailable")

@app.get("/api/google/drive/files/{drive_file_id}/metadata")
def get_google_drive_file_metadata(drive_file_id: str, pair=Depends(current_session), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("google:drive:metadata:"+user.id, 120, 3600)
    clean_id=clean_drive_id(drive_file_id, "ID файла Google Drive")
    if not clean_id: raise HTTPException(422, "Некорректный ID файла Google Drive")
    try:
        access_token=refreshed_google_drive_access_token(db, user)
        meta=get_cloud_files_provider().metadata(access_token, clean_id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502, "Google Drive metadata is unavailable")
    return google_drive_metadata_payload(meta)

@app.get("/api/google/drive/folders/{folder_id}/children")
def get_google_drive_folder_children(folder_id: str, page_size: int=Query(50, ge=1, le=100), page_token: str|None=Query(None, min_length=1, max_length=512), pair=Depends(current_session), db: Session=Depends(get_db)):
    _,user=pair; limiter.check("google:drive:folder-children:"+user.id, 120, 3600)
    clean_id=clean_drive_id(folder_id, "ID папки Google Drive")
    if not clean_id: raise HTTPException(422, "Некорректный ID папки Google Drive")
    try:
        conn=active_google_connection_for_user(db, user_id=user.id)
        require_drive_readonly_scope(conn)
        access_token=refreshed_google_drive_access_token(db, user)
        children=get_cloud_files_provider().folder_children(access_token, clean_id, page_size=page_size, page_token=page_token)
    except GoogleConnectionAccessError as exc:
        status_code = (
            404
            if exc.reason == GoogleConnectionAccessReason.missing
            else 409
        )
        raise HTTPException(status_code, exc.reason.value) from exc
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502, "Google Drive folder children are unavailable")
    return {"folder_id": children.folder_id, "items": [google_drive_metadata_payload(item) for item in children.items], "next_page_token": children.next_page_token}

@app.get("/api/credentials")
def list_credentials(pair=Depends(current_session), db: Session=Depends(get_db)):
    _,user=pair
    rows=db.query(ProviderCredential).filter(
        ProviderCredential.user_id==user.id,
        ProviderCredential.status!=CredentialStatus.deleted,
        ProviderCredential.deleted_at.is_(None),
    ).all()
    out=[]
    for c in rows:
        v=db.get(ProviderCredentialVersion, c.active_version_id) if c.active_version_id else None
        try:
            provider_config=json.loads(c.config_json or "{}")
        except (TypeError,ValueError):
            provider_config={}
        out.append({"id":c.id,"provider":c.provider.value,"label":c.label,"status":c.status.value,"active_version":v.version if v else None,"masked_value":v.masked_value if v else None,"folder_id":provider_config.get("folder_id") if c.provider==CredentialProvider.yandex else None,"created_at":c.created_at.isoformat()})
    return {"credentials": out}


@app.get("/api/stt/providers")
def list_stt_providers(response: Response,pair=Depends(current_session),db: Session=Depends(get_db)):
    _,user=pair
    limiter.check("stt:providers:"+user.id,240,3600)
    payload=catalog_payload(settings)
    current=utcnow().replace(tzinfo=None)
    for provider in payload["providers"]:
        for mode in provider["modes"]:
            health=provider_health(db,provider=provider["provider"],operating_mode=mode["mode"],now=current)
            mode["health"]={"available":health.available,"consecutive_failures":health.consecutive_failures,"retry_after_seconds":health.retry_after_seconds}
    _browser_capability_cache_headers(response)
    return payload


@app.get("/api/stt/dictionaries")
def list_stt_dictionaries(response: Response,pair=Depends(current_session),db: Session=Depends(get_db)):
    _,user=pair
    limiter.check("stt:dictionaries:list:"+user.id,240,3600)
    _browser_capability_cache_headers(response)
    return {"dictionaries":[dictionary_payload(row) for row in load_owned_dictionaries(db,owner_user_id=user.id)]}


@app.post("/api/stt/dictionaries")
def create_stt_dictionary(data: SttDictionaryIn,pair=Depends(require_csrf),db: Session=Depends(get_db),_=Depends(require_same_origin)):
    _,user=pair
    limiter.check("stt:dictionaries:create:"+user.id,60,3600)
    try:
        name,normalized_name=normalize_dictionary_name(data.name)
        entries=normalize_dictionary_entries(data.entries)
    except ValueError as exc:
        raise HTTPException(422,detail={"reason":str(exc)}) from None
    row=SttDictionary(owner_user_id=user.id,name=name,normalized_name=normalized_name)
    db.add(row)
    try:
        db.flush()
        replace_dictionary_entries(db,dictionary=row,entries=entries)
        audit(db,"stt_dictionary.created",actor_user_id=user.id,subject_user_id=user.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,detail={"reason":"dictionary_name_conflict"}) from None
    db.refresh(row)
    return dictionary_payload(load_owned_dictionaries(db,owner_user_id=user.id,dictionary_ids=(row.id,))[0])


@app.put("/api/stt/dictionaries/{dictionary_id}")
def update_stt_dictionary(dictionary_id: str,data: SttDictionaryIn,pair=Depends(require_csrf),db: Session=Depends(get_db),_=Depends(require_same_origin)):
    _,user=pair
    limiter.check("stt:dictionaries:update:"+user.id,120,3600)
    row=db.get(SttDictionary,dictionary_id)
    if row is None or row.owner_user_id!=user.id or not row.active:
        raise HTTPException(404,"Не найдено")
    try:
        row.name,row.normalized_name=normalize_dictionary_name(data.name)
        replace_dictionary_entries(db,dictionary=row,entries=normalize_dictionary_entries(data.entries))
        row.updated_at=utcnow()
        audit(db,"stt_dictionary.updated",actor_user_id=user.id,subject_user_id=user.id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422,detail={"reason":str(exc)}) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,detail={"reason":"dictionary_name_conflict"}) from None
    return dictionary_payload(load_owned_dictionaries(db,owner_user_id=user.id,dictionary_ids=(row.id,))[0])


@app.delete("/api/stt/dictionaries/{dictionary_id}")
def delete_stt_dictionary(dictionary_id: str,pair=Depends(require_csrf),db: Session=Depends(get_db),_=Depends(require_same_origin)):
    _,user=pair
    limiter.check("stt:dictionaries:delete:"+user.id,60,3600)
    row=db.get(SttDictionary,dictionary_id)
    if row is None or row.owner_user_id!=user.id:
        raise HTTPException(404,"Не найдено")
    db.delete(row)
    audit(db,"stt_dictionary.deleted",actor_user_id=user.id,subject_user_id=user.id)
    db.commit()
    return {"ok":True}


def _active_elevenlabs_credentials(db: Session, user: User):
    return (
        db.query(ProviderCredential)
        .filter(
            ProviderCredential.user_id == user.id,
            ProviderCredential.provider == CredentialProvider.elevenlabs,
            ProviderCredential.status == CredentialStatus.active,
            ProviderCredential.deleted_at.is_(None),
        )
        .order_by(ProviderCredential.label.asc(), ProviderCredential.id.asc())
        .all()
    )


def _refresh_elevenlabs_account_payload(
    db: Session,
    user: User,
    credential: ProviderCredential,
    *,
    now: datetime,
    force: bool,
):
    version = (
        db.get(ProviderCredentialVersion, credential.active_version_id)
        if credential.active_version_id
        else None
    )
    active_version = version.version if version is not None else None
    if (
        version is None
        or version.credential_id != credential.id
        or version.revoked_at is not None
        or version.deleted_at is not None
        or version.ciphertext is None
        or version.nonce is None
    ):
        return unavailable_provider_account_payload(
            credential=credential,
            active_version=active_version,
            now=now,
            error_code="credential_unavailable",
        )
    try:
        api_key = _open_active_elevenlabs_api_key(db, user, credential.id)
    except HTTPException:
        return unavailable_provider_account_payload(
            credential=credential,
            active_version=active_version,
            now=now,
            error_code="credential_unavailable",
        )
    try:
        row = sync_elevenlabs_account(
            db,
            owner_user_id=user.id,
            credential=credential,
            credential_version_id=version.id,
            api_key=api_key,
            now=now,
            force=force,
            transport=ElevenLabsAccountTransport(),
        )
    finally:
        api_key = ""
    return provider_account_payload(
        row,
        credential=credential,
        active_version=version.version,
        now=now,
    )


@app.get("/api/provider-accounts/elevenlabs")
def list_elevenlabs_accounts(
    response: Response,
    pair=Depends(current_session),
    db: Session=Depends(get_db),
):
    _, user = pair
    limiter.check("provider-account:list:" + user.id, 240, 3600)
    current = utcnow()
    accounts = [
        _refresh_elevenlabs_account_payload(
            db, user, credential, now=current, force=False
        )
        for credential in _active_elevenlabs_credentials(db, user)
    ]
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return {"accounts": accounts, "server_time": current.isoformat()}


@app.post("/api/provider-accounts/elevenlabs/{credential_id}/refresh")
def refresh_elevenlabs_account(
    credential_id: str,
    response: Response,
    pair=Depends(require_csrf),
    db: Session=Depends(get_db),
):
    _, user = pair
    limiter.check("provider-account:refresh:" + user.id, 30, 3600)
    credential = db.get(ProviderCredential, credential_id)
    if (
        credential is None
        or credential.user_id != user.id
        or credential.provider != CredentialProvider.elevenlabs
        or credential.status != CredentialStatus.active
        or credential.deleted_at is not None
    ):
        raise HTTPException(404, "Не найдено")
    current = utcnow()
    account = _refresh_elevenlabs_account_payload(
        db, user, credential, now=current, force=True
    )
    audit(
        db,
        "provider_account.refreshed",
        actor_user_id=user.id,
        subject_user_id=user.id,
        provider="elevenlabs",
        credential_id=credential.id,
        reason=account["state"],
    )
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return {"account": account, "server_time": current.isoformat()}

def key(): return master_key_from_b64(settings.master_key_b64())
def add_version(db,user,c,raw):
    nextv=(db.query(func.max(ProviderCredentialVersion.version)).filter_by(credential_id=c.id).scalar() or 0)+1
    v=ProviderCredentialVersion(credential_id=c.id, version=nextv, ciphertext=b"pending", nonce=b"pending", key_id=settings.credential_key_id, masked_value=mask_secret(raw), fingerprint=fingerprint(raw))
    db.add(v); db.flush(); ct,nonce=encrypt(raw,key(),aad(user.id,c.id,v.id,c.provider.value)); v.ciphertext=ct; v.nonce=nonce; c.active_version_id=v.id; c.status=CredentialStatus.active; return v

@app.post("/api/credentials")
def create_credential(data: CredentialIn, request: Request, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    sess,user=require_recent_auth(pair,request=request,db=db); limiter.check("cred:create:"+user.id, 20, 3600)
    config_json=json.dumps({"folder_id":data.folder_id},ensure_ascii=False,separators=(",",":")) if data.provider==CredentialProvider.yandex else None
    c=ProviderCredential(user_id=user.id, provider=data.provider, label=data.label.strip(),config_json=config_json); db.add(c); db.flush(); v=add_version(db,user,c,data.raw_value)
    audit(db,"credential.created",actor_user_id=user.id,subject_user_id=user.id,provider=c.provider.value,credential_id=c.id,version=v.version); db.commit(); return {"id": c.id, "provider": c.provider.value, "label": c.label, "status": c.status.value, "masked_value": v.masked_value}

@app.post("/api/credentials/{credential_id}/replace")
def replace_credential(credential_id: str, data: CredentialIn, request: Request, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=require_recent_auth(pair,request=request,db=db); limiter.check("cred:replace:"+user.id, 20, 3600); c=db.get(ProviderCredential, credential_id)
    if not c or c.user_id!=user.id or c.provider!=data.provider or c.status==CredentialStatus.deleted or c.deleted_at is not None: raise HTTPException(404,"Не найдено")
    c.label=data.label.strip()
    c.config_json=json.dumps({"folder_id":data.folder_id},ensure_ascii=False,separators=(",",":")) if data.provider==CredentialProvider.yandex else None
    v=add_version(db,user,c,data.raw_value); audit(db,"credential.replaced",actor_user_id=user.id,subject_user_id=user.id,provider=c.provider.value,credential_id=c.id,version=v.version); db.commit(); return {"ok": True, "active_version": v.version, "masked_value": v.masked_value}

@app.post("/api/credentials/{credential_id}/revoke")
def revoke_credential(credential_id: str, request: Request, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=require_recent_auth(pair,request=request,db=db); limiter.check("cred:revoke:"+user.id, 20, 3600); c=db.get(ProviderCredential, credential_id)
    if not c or c.user_id!=user.id or c.status==CredentialStatus.deleted or c.deleted_at is not None: raise HTTPException(404,"Не найдено")
    if c.status==CredentialStatus.revoked: return {"ok": True}
    c.status=CredentialStatus.revoked; audit(db,"credential.revoked",actor_user_id=user.id,subject_user_id=user.id,provider=c.provider.value,credential_id=c.id); db.commit(); return {"ok": True}

@app.delete("/api/credentials/{credential_id}")
def delete_credential(credential_id: str, request: Request, pair=Depends(require_csrf), db: Session=Depends(get_db)):
    _,user=require_recent_auth(pair,request=request,db=db); limiter.check("cred:delete:"+user.id, 20, 3600); c=db.get(ProviderCredential, credential_id)
    if not c or c.user_id!=user.id: raise HTTPException(404,"Не найдено")
    if c.status==CredentialStatus.deleted and c.deleted_at is not None: return {"ok": True}
    now=utcnow(); c.status=CredentialStatus.deleted; c.deleted_at=now
    for v in db.query(ProviderCredentialVersion).filter_by(credential_id=c.id): v.ciphertext=None; v.nonce=None; v.deleted_at=now
    audit(db,"credential.deleted",actor_user_id=user.id,subject_user_id=user.id,provider=c.provider.value,credential_id=c.id); db.commit(); return {"ok": True}

@app.get("/api/audit-events")
def audit_events(
    cursor: str|None=Query(None, max_length=MAX_COLLECTION_CURSOR_LENGTH),
    page_size: int=Query(DEFAULT_COLLECTION_PAGE_SIZE, ge=1, le=MAX_COLLECTION_PAGE_SIZE),
    pair=Depends(current_session),
    db: Session=Depends(get_db),
):
    sess,user=pair
    try:
        position=decode_collection_cursor(cursor, secret=sess.csrf_hash, owner_user_id=user.id, surface="audit-events")
    except CollectionCursorError:
        raise HTTPException(422, "Invalid audit cursor") from None
    query=db.query(AuditEvent).filter(AuditEvent.subject_user_id==user.id)
    if position:
        created_at,row_id=position
        query=query.filter((AuditEvent.created_at < created_at) | ((AuditEvent.created_at == created_at) & (AuditEvent.id < row_id)))
    rows=query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(page_size+1).all()
    rows,next_cursor=page_envelope(rows, page_size=page_size, timestamp_attribute="created_at", secret=sess.csrf_hash, owner_user_id=user.id, surface="audit-events")
    return {"events":[{"id":r.id,"type":r.event_type,"outcome":r.outcome or "legacy_unknown","trace_id":r.trace_id if valid_trace_id(r.trace_id) else None,"metadata":json.loads(r.metadata_json),"created_at":r.created_at.isoformat()} for r in rows], "next_cursor": next_cursor, "page_size": page_size}


from .yandex_disk_routes import build_router as build_yandex_disk_router
app.include_router(build_yandex_disk_router(recent_auth=require_recent_auth, limiter=limiter,
    project_loader=owned_project_or_404, source_serializer=source_payload))
