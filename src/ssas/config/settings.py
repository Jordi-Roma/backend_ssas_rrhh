import os
from pathlib import Path

from pydantic import Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_cv_files_directory() -> str:
    mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    return str(Path(mount) / "cv") if mount else "uploads/cv"


class Settings(BaseSettings):
    app_env: str = "development"
    app_debug: bool = False
    app_secret_key: str
    app_audit_encryption_key: str | None = Field(default=None, validate_default=True)
    app_algorithm: str = "HS256"
    app_access_token_expire_minutes: int = 15
    app_refresh_token_expire_days: int = 7
    app_password_reset_expire_minutes: int = 30
    app_email_verification_expire_minutes: int = 1440
    app_max_login_attempts: int = Field(default=5, ge=1, le=20)
    app_login_lock_minutes: int = Field(default=15, ge=1, le=1440)
    app_frontend_url: str = "http://localhost:3000"
    app_cors_origins: str = "http://localhost:3000,http://localhost:5173,"
    app_cors_origin_regex: str = ""
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_from_name: str = "SSAS RRHH"
    smtp_use_tls: bool = True
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    backup_storage_bucket: str = "respaldos"
    r2_backup_bucket: str = "rrhh-backups"
    r2_s3_endpoint_url: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: SecretStr | None = None
    r2_region: str = "auto"
    tenant_backup_enabled: bool = False
    tenant_backup_retention_days: int = Field(default=30, ge=1, le=365)
    backup_restore_enabled: bool = False
    backup_restore_confirmation: str = "RESTAURAR BASE DE DATOS"
    backup_files_directory: str = Field(default_factory=_default_cv_files_directory)
    pg_dump_path: str = "pg_dump"
    pg_restore_path: str = "pg_restore"
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_checkout_success_url: str | None = None
    stripe_checkout_cancel_url: str | None = None
    stripe_portal_return_url: str | None = None
    subscription_grace_days: int = Field(default=3, ge=0, le=30)
    database_url: str = "postgresql+psycopg://user:password@localhost:5432/app_db"
    db_echo: bool = False
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    openai_api_key: SecretStr | None = None
    ia_model: str = Field(default="gpt-4o-mini", min_length=1, max_length=120)
    gemini_api_key: SecretStr | None = None
    gemini_help_embedding_model: str = Field(default="gemini-embedding-001", pattern=r"^gemini-[a-z0-9.-]+$")
    gemini_help_model: str = Field(default="gemini-3.5-flash-lite", pattern=r"^gemini-[a-z0-9.-]+$")
    gemini_report_model: str = Field(
        default="gemini-3.5-flash-lite", pattern=r"^gemini-[a-z0-9.-]+$"
    )
    gemini_cv_model: str = Field(default="gemini-3.5-flash-lite", pattern=r"^gemini-[a-z0-9.-]+$")
    help_ai_enabled: bool = False
    help_ai_timeout_seconds: float = Field(default=10, gt=0, le=30)
    ia_timeout_seconds: float = Field(default=60, gt=0, le=300)
    ia_max_cv_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=20 * 1024 * 1024)
    ia_max_cv_text_chars: int = Field(default=60000, ge=100, le=200000)
    ia_extraction_timeout_seconds: float = Field(default=15, gt=0, le=60)
    ia_max_output_tokens: int = Field(default=4000, ge=500, le=16000)
    ia_max_concurrent_analyses: int = Field(default=2, ge=1, le=32)
    cv_storage_directory: str = Field(default_factory=_default_cv_files_directory)
    db_pool_recycle_seconds: int = Field(default=1800, ge=30)

    @field_validator("app_secret_key")
    @classmethod
    def validate_secret_key(cls, value: str, info: ValidationInfo) -> str:
        if info.data.get("app_env") == "production" and len(value) < 32:
            raise ValueError("APP_SECRET_KEY debe tener al menos 32 caracteres en producción")
        return value

    @field_validator("app_audit_encryption_key")
    @classmethod
    def validate_audit_key(cls, value: str | None, info: ValidationInfo) -> str | None:
        if info.data.get("app_env") == "production" and value is None:
            raise ValueError("APP_AUDIT_ENCRYPTION_KEY es obligatoria en producción")
        if value is not None:
            try:
                decoded = bytes.fromhex(value)
            except ValueError as exc:
                raise ValueError("APP_AUDIT_ENCRYPTION_KEY debe ser hexadecimal") from exc
            if len(decoded) != 32:
                raise ValueError(
                    "APP_AUDIT_ENCRYPTION_KEY debe contener 64 caracteres hexadecimales"
                )
        return value

    @field_validator("stripe_secret_key")
    @classmethod
    def validate_stripe_test_key(cls, value: str | None) -> str | None:
        if value and not value.startswith("sk_test_"):
            raise ValueError("STRIPE_SECRET_KEY debe ser una clave de Sandbox sk_test_...")
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        """Adapta la URL estándar de PostgreSQL al driver asíncrono de SQLAlchemy."""
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return value.replace(prefix, "postgresql+psycopg://", 1)
        if value.startswith("postgresql+psycopg://"):
            return value
        raise ValueError(
            "DATABASE_URL debe ser una conexión PostgreSQL y no la URL HTTPS del proyecto"
        )

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip().rstrip("/")
            for origin in self.app_cors_origins.split(",")
            if origin.strip()
        ]

    @property
    def cors_origin_regex(self) -> str | None:
        # Subdominios de despliegue de Railway (producción y previews).
        return self.app_cors_origin_regex or r"^https://[a-z0-9-]+\.up\.railway\.app$"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings(_env_file=os.getenv("SETTINGS_ENV_FILE", ".env"))
