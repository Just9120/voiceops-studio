from functools import lru_cache
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote_plus
from pydantic import EmailStr, Field, IPvAnyAddress, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STUDIO_", env_file=".env", extra="ignore")
    environment: str = "production"
    database_url: str | None = None
    database_scheme: str = "postgresql+psycopg"
    database_host: str = "postgres"
    database_port: int = 5432
    database_name: str = "studio"
    database_user: str = "studio"
    # The PostgreSQL password is read from a mounted secret file, not stored in the source tree.
    postgres_password_file: str = "/run/secrets/studio_postgres_password"
    redis_url: str = "redis://redis:6379/0"
    app_origin: str = "https://studio.cloud-nodes.net"
    cookie_name: str = "__Host-studio_session"
    cookie_secure: bool = True
    session_days: int = 14
    recent_auth_seconds: int = Field(default=600, ge=60, le=3600)
    session_last_seen_write_interval_seconds: int = Field(default=300, ge=60, le=3600)
    auth_cleanup_interval_seconds: int = Field(default=3600, ge=60, le=86400)
    auth_cleanup_batch_size: int = Field(default=500, ge=1, le=1000)
    credential_master_key_file: str = "/run/secrets/studio_credential_master_key"
    credential_key_id: str = "studio-v1"
    enable_api_docs: bool = False
    trusted_proxy_ip: IPvAnyAddress = IPvAnyAddress("127.0.0.1")
    source_s3_endpoint_url: str | None = None
    source_s3_region: str = "auto"
    source_s3_bucket: str | None = None
    source_s3_access_key_id_file: str | None = None
    source_s3_secret_access_key_file: str | None = None
    source_s3_lifecycle_rule_id: str | None = None
    audio_reference_s3_endpoint_url: str | None = None
    audio_reference_s3_region: str = "auto"
    audio_reference_s3_bucket: str | None = None
    audio_reference_s3_access_key_id_file: str | None = None
    audio_reference_s3_secret_access_key_file: str | None = None
    audio_reference_s3_lifecycle_rule_id: str | None = None
    source_upload_ttl_seconds: int = Field(default=3600, ge=900, le=86400)
    source_presign_ttl_seconds: int = Field(default=900, ge=60, le=900)
    source_max_upload_bytes: int = Field(default=536870912, ge=1, le=2147483647)
    media_duration_warning_seconds: int = Field(default=14400, ge=60, le=604800)
    media_max_duration_seconds: int = Field(default=43200, ge=60, le=604800)
    source_multipart_threshold_bytes: int = Field(default=16777216, ge=5242880, le=2147483647)
    source_multipart_part_size_bytes: int = Field(default=8388608, ge=5242880, le=134217728)
    storage_orphan_min_age_seconds: int = Field(default=86400, ge=3600, le=2592000)
    storage_reconciliation_scan_limit: int = Field(default=500, ge=1, le=5000)
    storage_reconciliation_page_size: int = Field(default=100, ge=1, le=1000)
    storage_reconciliation_plan_ttl_seconds: int = Field(default=600, ge=60, le=1800)
    storage_reconciliation_apply_limit: int = Field(default=100, ge=1, le=500)
    audio_preparation_max_input_bytes: int = Field(default=1073741824, ge=1, le=2147483647)
    audio_preparation_max_scratch_bytes: int = Field(default=3221225472, ge=134217728, le=8589934592)
    audio_preparation_max_output_bytes: int = Field(default=2147483647, ge=1, le=2147483647)
    google_oauth_client_id: str | None = None
    google_oauth_client_secret_file: str | None = None
    google_oauth_redirect_uri: str | None = None
    google_oauth_scopes: str = (
        "openid email "
        "https://www.googleapis.com/auth/drive.file "
        "https://www.googleapis.com/auth/drive.readonly"
    )
    google_oauth_state_ttl_seconds: int = 600
    google_maintenance_oauth_client_id: str | None = None
    google_maintenance_oauth_client_secret_file: str | None = None
    google_maintenance_oauth_redirect_uri: str | None = None
    google_maintenance_oauth_scopes: str = (
        "openid email "
        "https://www.googleapis.com/auth/drive.metadata.readonly "
        "https://www.googleapis.com/auth/documents"
    )
    google_picker_api_key: str | None = None
    google_picker_app_id: str | None = None
    worker_poll_interval_seconds: int = Field(default=5, ge=1, le=60)
    worker_error_backoff_seconds: int = Field(default=5, ge=1, le=300)
    worker_lease_ttl_seconds: int = Field(default=3600, ge=300, le=86400)
    worker_lease_heartbeat_interval_seconds: int = Field(default=60, ge=5)
    # Deprecated compatibility input; unfinished text no longer expires.
    provider_part_checkpoint_ttl_seconds: int = Field(default=86400, ge=3600, le=86400)
    elevenlabs_byok_enabled: bool = True
    yandex_byok_enabled: bool = False
    elevenlabs_economic_model: str = Field(default="scribe_v2", min_length=1, max_length=80)
    elevenlabs_standard_model: str = Field(default="scribe_v2", min_length=1, max_length=80)
    elevenlabs_premium_model: str = Field(default="scribe_v2", min_length=1, max_length=80)
    elevenlabs_realtime_model: str = Field(default="scribe_v2_realtime", min_length=1, max_length=80)
    yandex_economic_model: str = Field(default="deferred-general", min_length=1, max_length=80)
    yandex_standard_model: str = Field(default="general", min_length=1, max_length=80)
    yandex_premium_model: str = Field(default="general", min_length=1, max_length=80)
    yandex_realtime_model: str = Field(default="general", min_length=1, max_length=80)
    yandex_stt_api_base_url: str = "https://stt.api.cloud.yandex.net"
    yandex_operations_api_base_url: str = "https://operation.api.cloud.yandex.net"
    yandex_stt_grpc_endpoint: str = "stt.api.cloud.yandex.net:443"
    yandex_operation_poll_interval_seconds: int = Field(default=5, ge=1, le=60)
    yandex_operation_timeout_seconds: int = Field(default=14400, ge=30, le=14400)
    stt_health_failure_threshold: int = Field(default=3, ge=2, le=20)
    stt_health_cooldown_seconds: int = Field(default=300, ge=30, le=3600)
    elevenlabs_scribe_v2_rate_per_hour_usd: Decimal | None = Field(default=None, gt=0, le=100)
    elevenlabs_pricing_effective_date: date | None = None
    elevenlabs_pricing_source: str | None = Field(default=None, max_length=80)
    yandex_async_rate_per_hour_usd: Decimal | None = Field(default=None, gt=0, le=100)
    yandex_pricing_effective_date: date | None = None
    yandex_pricing_source: str | None = Field(default=None, max_length=80)
    realtime_draft_max_count: int = Field(default=20, ge=1, le=100)
    audio_delivery_directory: str = Field(default="/run/studio-audio-delivery", min_length=1, max_length=1024)
    realtime_draft_max_storage_bytes: int = Field(default=33554432, ge=1048576, le=134217728)
    # Deprecated compatibility input; Live is retained until owner clear.
    realtime_draft_ttl_seconds: int = Field(default=259200, ge=259200, le=259200)
    realtime_webhook_allowed_hosts: str = Field(default="", max_length=2000)
    diagnostic_retention_days: int = Field(default=14, ge=1, le=30)
    diagnostic_debug_retention_hours: int = Field(default=24, ge=1, le=24)
    diagnostic_cleanup_interval_seconds: int = Field(default=3600, ge=60, le=86400)
    diagnostic_cleanup_batch_size: int = Field(default=500, ge=1, le=1000)
    runtime_component: str = Field(default="unknown", max_length=20)
    runtime_release_version: str = Field(default="unknown", max_length=120)
    runtime_commit_sha: str = Field(default="unknown", max_length=40)
    runtime_build_id: str = Field(default="unknown", max_length=120)
    runtime_worker_heartbeat_interval_seconds: int = Field(default=30, ge=5, le=300)
    runtime_worker_stale_after_seconds: int = Field(default=120, ge=30, le=900)
    diagnostic_report_max_events: int = Field(default=5000, ge=1, le=5000)
    alert_evaluation_interval_seconds: int = Field(default=60, ge=30, le=3600)
    alert_signal_window_seconds: int = Field(default=900, ge=300, le=86400)
    alert_stuck_queue_seconds: int = Field(default=900, ge=300, le=86400)
    alert_provider_failure_threshold: int = Field(default=3, ge=2, le=20)
    alert_limit_remaining_percent: int = Field(default=15, ge=1, le=50)
    alert_storage_limit_bytes: int | None = Field(default=None, ge=1048576, le=109951162777600)
    # Deprecated compatibility input. Cloudkeep owns regular backup freshness;
    # Studio still records owner-scoped protected pre-migration backup outcomes.
    backup_monitor_owner_user_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
    alert_incident_cooldown_seconds: int = Field(default=1800, ge=300, le=86400)
    alert_delivery_retry_seconds: int = Field(default=300, ge=60, le=3600)
    alert_delivery_max_attempts: int = Field(default=3, ge=1, le=5)
    alert_telegram_enabled: bool = False
    alert_telegram_bot_token_file: str | None = None
    alert_telegram_chat_id_file: str | None = None
    alert_telegram_timeout_seconds: int = Field(default=5, ge=1, le=15)
    job_notification_retry_seconds: int = Field(default=60, ge=30, le=3600)
    job_notification_max_attempts: int = Field(default=3, ge=1, le=5)
    job_notification_claim_seconds: int = Field(default=60, ge=15, le=300)
    job_web_push_enabled: bool = False
    job_web_push_vapid_public_key: str | None = None
    job_web_push_vapid_private_key_file: str | None = None
    job_web_push_vapid_subject: str | None = None
    job_web_push_timeout_seconds: int = Field(default=5, ge=1, le=15)
    job_email_enabled: bool = False
    job_smtp_host: str | None = None
    job_smtp_port: int = Field(default=587, ge=1, le=65535)
    job_smtp_username: str | None = None
    job_smtp_password_file: str | None = None
    job_smtp_from_email: EmailStr | None = None
    job_smtp_use_ssl: bool = False
    job_smtp_starttls: bool = True
    job_smtp_timeout_seconds: int = Field(default=10, ge=1, le=30)
    security_email_enabled: bool = False
    security_email_sender_domain: str | None = None
    job_telegram_enabled: bool = False
    job_telegram_owner_user_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
    job_telegram_bot_token_file: str | None = None
    job_telegram_chat_id_file: str | None = None
    job_telegram_timeout_seconds: int = Field(default=5, ge=1, le=15)

    @field_validator("yandex_async_rate_per_hour_usd", "yandex_pricing_effective_date", "yandex_pricing_source", mode="before")
    @classmethod
    def empty_optional_yandex_tariff(cls, value):
        return None if value == "" else value

    @field_validator("trusted_proxy_ip")
    @classmethod
    def validate_trusted_proxy_ip(cls, value: IPvAnyAddress):
        if value.is_unspecified or value.is_multicast:
            raise ValueError("trusted proxy must be one specific unicast IP")
        return value

    @field_validator("alert_storage_limit_bytes", mode="before")
    @classmethod
    def normalize_optional_storage_alert_limit(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("job_smtp_from_email", "backup_monitor_owner_user_id", "job_telegram_owner_user_id", mode="before")
    @classmethod
    def normalize_optional_email(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_worker_lease_heartbeat(self):
        if self.worker_lease_heartbeat_interval_seconds * 3 > self.worker_lease_ttl_seconds:
            raise ValueError("worker lease heartbeat interval must be at most one third of worker lease ttl")
        if self.runtime_worker_heartbeat_interval_seconds * 2 > self.runtime_worker_stale_after_seconds:
            raise ValueError("runtime worker stale threshold must cover at least two heartbeat intervals")
        pricing = (
            self.elevenlabs_scribe_v2_rate_per_hour_usd,
            self.elevenlabs_pricing_effective_date,
            self.elevenlabs_pricing_source,
        )
        if any(item is not None for item in pricing) and not all(item is not None for item in pricing):
            raise ValueError("ElevenLabs pricing snapshot must be complete")
        if self.elevenlabs_pricing_source not in {None, "elevenlabs_public_api_pricing"}:
            raise ValueError("unsupported ElevenLabs pricing source")
        yandex_pricing = (self.yandex_async_rate_per_hour_usd, self.yandex_pricing_effective_date, self.yandex_pricing_source)
        if any(item is not None for item in yandex_pricing) and not all(item is not None for item in yandex_pricing):
            raise ValueError("Yandex pricing snapshot must be complete")
        if self.yandex_pricing_source not in {None, "yandex_public_api_pricing"}:
            raise ValueError("unsupported Yandex pricing source")
        if self.source_multipart_part_size_bytes > self.source_multipart_threshold_bytes:
            raise ValueError("multipart part size must not exceed multipart threshold")
        if self.storage_reconciliation_apply_limit > self.storage_reconciliation_scan_limit:
            raise ValueError("reconciliation apply limit must not exceed scan limit")
        if self.media_duration_warning_seconds >= self.media_max_duration_seconds:
            raise ValueError("media duration warning must be below the hard limit")
        telegram_files = (
            self.alert_telegram_bot_token_file,
            self.alert_telegram_chat_id_file,
        )
        if self.alert_telegram_enabled and not all(telegram_files):
            raise ValueError("Telegram alerts require bot token and chat id secret files")
        if all(telegram_files) and telegram_files[0] == telegram_files[1]:
            raise ValueError("Telegram alert secret files must be distinct")
        push = (
            self.job_web_push_vapid_public_key,
            self.job_web_push_vapid_private_key_file,
            self.job_web_push_vapid_subject,
        )
        if self.job_web_push_enabled and not all(push):
            raise ValueError("Web Push notifications require public/private VAPID keys and subject")
        if self.job_web_push_vapid_public_key and not re.fullmatch(
            r"[A-Za-z0-9_-]{80,120}", self.job_web_push_vapid_public_key
        ):
            raise ValueError("Web Push VAPID public key is invalid")
        if self.job_web_push_vapid_subject and not (
            self.job_web_push_vapid_subject.startswith("mailto:")
            or self.job_web_push_vapid_subject.startswith("https://")
        ):
            raise ValueError("Web Push VAPID subject must be mailto or HTTPS")
        if self.job_smtp_username and not self.job_smtp_password_file:
            raise ValueError("SMTP username requires a password file")
        if self.job_email_enabled and not (
            self.job_smtp_host and self.job_smtp_from_email
        ):
            raise ValueError("Email notifications require SMTP host and from address")
        if self.job_email_enabled and self.job_smtp_use_ssl == self.job_smtp_starttls:
            raise ValueError("Email notifications require exactly one TLS mode")
        job_telegram_files = (
            self.job_telegram_bot_token_file,
            self.job_telegram_chat_id_file,
        )
        if self.job_telegram_enabled and not all(job_telegram_files):
            raise ValueError("Job Telegram notifications require bot token and chat id files")
        if all(job_telegram_files) and job_telegram_files[0] == job_telegram_files[1]:
            raise ValueError("Job Telegram secret files must be distinct")
        return self

    def master_key_b64(self) -> str:
        return Path(self.credential_master_key_file).read_text(encoding="utf-8").strip()

    def postgres_password(self) -> str:
        return Path(self.postgres_password_file).read_text(encoding="utf-8").strip()

    def source_storage_configured(self) -> bool:
        return bool(
            self.source_s3_endpoint_url
            and self.source_s3_bucket
            and self.source_s3_access_key_id_file
            and self.source_s3_secret_access_key_file
        )

    def audio_reference_storage_configured(self) -> bool:
        return bool(
            self.audio_reference_s3_endpoint_url
            and self.audio_reference_s3_bucket
            and self.audio_reference_s3_access_key_id_file
            and self.audio_reference_s3_secret_access_key_file
        )

    def reference_storage_isolation_configured(self) -> bool:
        transcription_lifecycle = (self.source_s3_lifecycle_rule_id or "").strip()
        audio_lifecycle = (self.audio_reference_s3_lifecycle_rule_id or "").strip()
        return bool(
            self.source_storage_configured()
            and self.audio_reference_storage_configured()
            and self.source_s3_bucket != self.audio_reference_s3_bucket
            and self.source_s3_access_key_id_file
            != self.audio_reference_s3_access_key_id_file
            and self.source_s3_secret_access_key_file
            != self.audio_reference_s3_secret_access_key_file
            and transcription_lifecycle
            and audio_lifecycle
            and transcription_lifecycle != audio_lifecycle
        )

    def google_picker_configured(self) -> bool:
        return bool((self.google_picker_api_key or "").strip() and (self.google_picker_app_id or "").strip())

    def telegram_alerts_configured(self) -> bool:
        try:
            self.telegram_alert_credentials()
        except (OSError, RuntimeError, UnicodeError):
            return False
        return True

    def telegram_alert_credentials(self) -> tuple[str, str]:
        if not (
            self.alert_telegram_enabled
            and self.alert_telegram_bot_token_file
            and self.alert_telegram_chat_id_file
        ):
            raise RuntimeError("Telegram alerts are not configured")
        token = Path(self.alert_telegram_bot_token_file or "").read_text(encoding="utf-8").strip()
        chat_id = Path(self.alert_telegram_chat_id_file or "").read_text(encoding="utf-8").strip()
        if not (20 <= len(token) <= 256 and ":" in token):
            raise RuntimeError("Telegram bot token secret is invalid")
        if not (1 <= len(chat_id) <= 32 and chat_id.lstrip("-").isdigit()):
            raise RuntimeError("Telegram chat id secret is invalid")
        return token, chat_id

    def job_web_push_configured(self) -> bool:
        if not (
            self.job_web_push_enabled
            and self.job_web_push_vapid_public_key
            and self.job_web_push_vapid_private_key_file
            and self.job_web_push_vapid_subject
        ):
            return False
        try:
            return bool(Path(self.job_web_push_vapid_private_key_file).read_text(encoding="utf-8").strip())
        except (OSError, UnicodeError):
            return False

    def job_email_configured(self) -> bool:
        if not (self.job_email_enabled and self.job_smtp_host and self.job_smtp_from_email):
            return False
        if self.job_smtp_use_ssl == self.job_smtp_starttls:
            return False
        if not self.job_smtp_username:
            return True
        try:
            return bool(Path(self.job_smtp_password_file or "").read_text(encoding="utf-8").strip())
        except (OSError, UnicodeError):
            return False

    def security_email_configured(self) -> bool:
        domain = (self.security_email_sender_domain or "").strip().lower()
        address = str(self.job_smtp_from_email or "")
        if not (self.security_email_enabled and self.job_smtp_host and domain and
                address.rpartition("@")[2].lower() == domain and
                self.job_smtp_use_ssl != self.job_smtp_starttls):
            return False
        try:
            return not self.job_smtp_username or bool(self.job_smtp_password())
        except (OSError, RuntimeError, UnicodeError):
            return False

    def job_smtp_password(self) -> str | None:
        if not self.job_smtp_username:
            return None
        value = Path(self.job_smtp_password_file or "").read_text(encoding="utf-8").strip()
        if not value or len(value) > 4096:
            raise RuntimeError("SMTP password secret is invalid")
        return value

    def job_telegram_configured(self) -> bool:
        try:
            self.job_telegram_credentials()
        except (OSError, RuntimeError, UnicodeError):
            return False
        return True

    def job_telegram_credentials(self) -> tuple[str, str]:
        if not (
            self.job_telegram_enabled
            and self.job_telegram_bot_token_file
            and self.job_telegram_chat_id_file
        ):
            raise RuntimeError("Job Telegram notifications are not configured")
        token = Path(self.job_telegram_bot_token_file).read_text(encoding="utf-8").strip()
        chat_id = Path(self.job_telegram_chat_id_file).read_text(encoding="utf-8").strip()
        if not (20 <= len(token) <= 256 and ":" in token):
            raise RuntimeError("Job Telegram bot token secret is invalid")
        if not (1 <= len(chat_id) <= 32 and chat_id.lstrip("-").isdigit()):
            raise RuntimeError("Job Telegram chat id secret is invalid")
        return token, chat_id

    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        password = quote_plus(self.postgres_password())
        user = quote_plus(self.database_user)
        name = quote_plus(self.database_name)
        return f"{self.database_scheme}://{user}:{password}@{self.database_host}:{self.database_port}/{name}"

@lru_cache
def get_settings() -> Settings:
    return Settings()
