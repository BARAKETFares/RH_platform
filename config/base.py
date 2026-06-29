"""
Configuration de base — héritée par tous les environnements.
Ne jamais instancier directement : utiliser Development, Testing ou Production.
"""
import os
from datetime import timedelta


class BaseConfig:
    # -------------------------------------------------------------------------
    # Général
    # -------------------------------------------------------------------------
    APP_NAME: str = "Plateforme RH"
    APP_VERSION: str = "1.0.0"
    SUPPORTED_LANGUAGES: list = ["fr", "en"]
    DEFAULT_LOCALE: str = "fr"
    DEFAULT_TIMEZONE: str = "Europe/Paris"

    # -------------------------------------------------------------------------
    # Sécurité Flask
    # -------------------------------------------------------------------------
    SECRET_KEY: str = os.environ["SECRET_KEY"]           # Obligatoire — pas de défaut
    WTF_CSRF_ENABLED: bool = True
    WTF_CSRF_TIME_LIMIT: int = 3600                      # 1 heure
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"
    PERMANENT_SESSION_LIFETIME: timedelta = timedelta(hours=8)

    # -------------------------------------------------------------------------
    # Base de données (SQLAlchemy)
    # -------------------------------------------------------------------------
    SQLALCHEMY_DATABASE_URI: str = os.environ["DATABASE_URL"]
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_RECORD_QUERIES: bool = False
    SQLALCHEMY_ENGINE_OPTIONS: dict = {
        "pool_pre_ping": True,           # Vérifie la connexion avant usage
        "pool_size": 10,                 # Connexions permanentes dans le pool
        "max_overflow": 20,              # Connexions supplémentaires autorisées
        "pool_recycle": 3600,            # Recyclage des connexions toutes les 1h
        "pool_timeout": 30,              # Timeout d'attente d'une connexion libre
        "connect_args": {
            "connect_timeout": 10,
            "application_name": "hr_platform",
            "options": "-c timezone=UTC",
        },
    }

    # -------------------------------------------------------------------------
    # JWT (Flask-JWT-Extended) — pour l'API REST
    # -------------------------------------------------------------------------
    JWT_SECRET_KEY: str = os.environ["JWT_SECRET_KEY"]   # Obligatoire — clé dédiée JWT
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRES: timedelta = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES: timedelta = timedelta(days=30)
    JWT_TOKEN_LOCATION: list = ["headers", "cookies"]
    JWT_COOKIE_SECURE: bool = True                        # HTTPS uniquement en prod
    JWT_COOKIE_CSRF_PROTECT: bool = True
    JWT_COOKIE_SAMESITE: str = "Lax"
    JWT_HEADER_NAME: str = "Authorization"
    JWT_HEADER_TYPE: str = "Bearer"
    JWT_ERROR_MESSAGE_KEY: str = "error"
    JWT_BLACKLIST_ENABLED: bool = True
    JWT_BLACKLIST_TOKEN_CHECKS: list = ["access", "refresh"]

    # -------------------------------------------------------------------------
    # Redis (cache + broker Celery)
    # -------------------------------------------------------------------------
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CACHE_TYPE: str = "RedisCache"
    CACHE_REDIS_URL: str = REDIS_URL
    CACHE_DEFAULT_TIMEOUT: int = 300                     # 5 minutes
    CACHE_KEY_PREFIX: str = "hr_platform:"

    # -------------------------------------------------------------------------
    # Celery
    # -------------------------------------------------------------------------
    CELERY_BROKER_URL: str = REDIS_URL
    CELERY_RESULT_BACKEND: str = os.getenv("REDIS_URL", "redis://localhost:6379/1")
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_RESULT_SERIALIZER: str = "json"
    CELERY_ACCEPT_CONTENT: list = ["json"]
    CELERY_TIMEZONE: str = DEFAULT_TIMEZONE
    CELERY_ENABLE_UTC: bool = True
    CELERY_TASK_TRACK_STARTED: bool = True
    CELERY_TASK_TIME_LIMIT: int = 300                    # 5 min max par tâche
    CELERY_BEAT_SCHEDULE: dict = {}

    # -------------------------------------------------------------------------
    # Email (Flask-Mail)
    # -------------------------------------------------------------------------
    MAIL_SERVER: str = os.getenv("MAIL_SERVER", "localhost")
    MAIL_PORT: int = int(os.getenv("MAIL_PORT", 587))
    MAIL_USE_TLS: bool = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USE_SSL: bool = False
    MAIL_USERNAME: str | None = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD: str | None = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER: str = os.getenv("MAIL_DEFAULT_SENDER", "noreply@hr-platform.local")
    MAIL_MAX_EMAILS: int = 50
    MAIL_SUPPRESS_SEND: bool = False

    # -------------------------------------------------------------------------
    # Upload de fichiers
    # -------------------------------------------------------------------------
    UPLOAD_FOLDER: str = os.getenv("UPLOAD_FOLDER", "/var/hr_platform/uploads")
    MAX_CONTENT_LENGTH: int = 10 * 1024 * 1024           # 10 Mo maximum
    ALLOWED_EXTENSIONS: set = {"pdf", "png", "jpg", "jpeg", "doc", "docx", "xls", "xlsx"}
    UPLOAD_SUBFOLDERS: dict = {
        "employee_photos":    "employees/photos",
        "employee_documents": "employees/documents",
        "payslips":           "payroll/payslips",
        "contracts":          "employees/contracts",
    }

    # -------------------------------------------------------------------------
    # Pagination
    # -------------------------------------------------------------------------
    PAGINATION_DEFAULT_PAGE_SIZE: int = 25
    PAGINATION_MAX_PAGE_SIZE: int = 100

    # -------------------------------------------------------------------------
    # Rate Limiting (Flask-Limiter)
    # -------------------------------------------------------------------------
    RATELIMIT_STORAGE_URL: str = REDIS_URL
    RATELIMIT_DEFAULT: str = "200 per hour"
    RATELIMIT_LOGIN: str = "10 per minute"
    RATELIMIT_API: str = "1000 per hour"

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = "json"                              # json | text
    LOG_FILE: str | None = os.getenv("LOG_FILE")

    # -------------------------------------------------------------------------
    # Audit
    # -------------------------------------------------------------------------
    AUDIT_LOG_SENSITIVE_FIELDS: list = [
        "password_hash", "national_id_number", "iban", "bic",
        "totp_secret", "token_hash",
    ]
    AUDIT_RETENTION_YEARS: int = 5

    # -------------------------------------------------------------------------
    # Fonctionnalités métier
    # -------------------------------------------------------------------------
    LEAVE_DEFAULT_APPROVAL_WORKFLOW: list = ["manager", "hr"]
    LEAVE_BALANCE_CARRY_OVER_LIMIT_DAYS: int = 10
    PASSWORD_MIN_LENGTH: int = 12
    PASSWORD_REQUIRE_UPPERCASE: bool = True
    PASSWORD_REQUIRE_DIGIT: bool = True
    PASSWORD_REQUIRE_SPECIAL: bool = True
    ACCOUNT_LOCKOUT_ATTEMPTS: int = 5
    ACCOUNT_LOCKOUT_DURATION_MINUTES: int = 30
    SESSION_TIMEOUT_MINUTES: int = 480                   # 8h
