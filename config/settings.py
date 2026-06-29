"""
Configurations par environnement.

Hiérarchie :
    BaseConfig
        ├── DevelopmentConfig
        ├── TestingConfig
        ├── StagingConfig
        └── ProductionConfig

Toutes les valeurs sensibles sont lues depuis des variables d'environnement.
Ne jamais hardcoder de secrets dans ce fichier.
"""
from __future__ import annotations

import os
import secrets
from datetime import timedelta
from pathlib import Path

# Racine du projet (deux niveaux au-dessus de ce fichier)
BASE_DIR = Path(__file__).resolve().parent.parent


# =============================================================================
# Base — Paramètres communs à tous les environnements
# =============================================================================

class BaseConfig:
    """Paramètres communs. Ne pas instancier directement."""

    # ── Application ──────────────────────────────────────────────────────────
    APP_NAME: str = "Plateforme RH"
    APP_VERSION: str = "1.0.0"
    SECRET_KEY: str = os.environ.get("SECRET_KEY", secrets.token_hex(32))
    WTF_CSRF_ENABLED: bool = True
    WTF_CSRF_TIME_LIMIT: int = 3600  # secondes

    # ── Internationalisation ──────────────────────────────────────────────────
    BABEL_DEFAULT_LOCALE: str = "fr"
    BABEL_DEFAULT_TIMEZONE: str = "Europe/Paris"
    SUPPORTED_LANGUAGES: list[str] = ["fr", "en"]

    # ── Base de données ───────────────────────────────────────────────────────
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:0000@localhost:5432/schema_rh",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_ECHO: bool = False
    SQLALCHEMY_ENGINE_OPTIONS: dict = {
        "pool_size":       10,
        "max_overflow":    20,
        "pool_timeout":    30,
        "pool_recycle":    1800,
        "pool_pre_ping":   True,  # Vérifie la connexion avant usage
    }

    # ── Migrations ────────────────────────────────────────────────────────────
    ALEMBIC_SCRIPT_LOCATION: str = str(BASE_DIR / "migrations")

    # ── JWT ───────────────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = os.environ.get("JWT_SECRET_KEY", secrets.token_hex(32))
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRES: timedelta  = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES: timedelta = timedelta(days=30)
    JWT_TOKEN_LOCATION: list[str] = ["headers", "cookies"]
    JWT_COOKIE_SECURE: bool = True
    JWT_COOKIE_SAMESITE: str = "Lax"
    JWT_COOKIE_CSRF_PROTECT: bool = True
    JWT_HEADER_NAME: str = "Authorization"
    JWT_HEADER_TYPE: str = "Bearer"
    JWT_BLACKLIST_ENABLED: bool = True
    JWT_BLACKLIST_TOKEN_CHECKS: list[str] = ["access", "refresh"]

    # ── Sessions Flask ────────────────────────────────────────────────────────
    SESSION_COOKIE_NAME: str = "hr_session"
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SECURE: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"
    PERMANENT_SESSION_LIFETIME: timedelta = timedelta(hours=8)

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    RATELIMIT_DEFAULT: str = "200 per day;50 per hour"
    RATELIMIT_STORAGE_URL: str = os.environ.get(
        "REDIS_URL", "redis://localhost:6379/1"
    )
    RATELIMIT_STRATEGY: str = "fixed-window"

    # ── Cache (Redis) ─────────────────────────────────────────────────────────
    CACHE_TYPE: str = "RedisCache"
    CACHE_REDIS_URL: str = os.environ.get(
        "REDIS_URL", "redis://localhost:6379/0"
    )
    CACHE_DEFAULT_TIMEOUT: int = 300  # 5 minutes

    # ── Celery ────────────────────────────────────────────────────────────────
    CELERY_BROKER_URL: str = os.environ.get(
        "REDIS_URL", "redis://localhost:6379/2"
    )
    CELERY_RESULT_BACKEND: str = os.environ.get(
        "REDIS_URL", "redis://localhost:6379/2"
    )
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_RESULT_SERIALIZER: str = "json"
    CELERY_ACCEPT_CONTENT: list[str] = ["json"]
    CELERY_TIMEZONE: str = "Europe/Paris"
    CELERY_ENABLE_UTC: bool = True
    CELERY_TASK_TRACK_STARTED: bool = True
    CELERY_TASK_TIME_LIMIT: int = 300  # 5 min max par tâche
    CELERY_BEAT_SCHEDULE: dict = {
        # Calcul mensuel des congés acquis (1er de chaque mois, 1h du matin)
        "accrue-monthly-leave": {
            "task":     "app.tasks.leave_tasks.accrue_monthly_leave",
            "schedule": "0 1 1 * *",
        },
    }

    # ── Email ─────────────────────────────────────────────────────────────────
    MAIL_SERVER: str  = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT: int    = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS: bool = True
    MAIL_USE_SSL: bool = False
    MAIL_USERNAME: str = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD: str = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER: tuple = (
        os.environ.get("MAIL_SENDER_NAME", "Plateforme RH"),
        os.environ.get("MAIL_SENDER_ADDRESS", "noreply@hr-platform.fr"),
    )
    MAIL_MAX_EMAILS: int = 50

    # ── Upload de fichiers ────────────────────────────────────────────────────
    UPLOAD_FOLDER: Path = BASE_DIR / "storage" / "uploads"
    MAX_CONTENT_LENGTH: int = 10 * 1024 * 1024  # 10 Mo
    ALLOWED_EXTENSIONS: set[str] = {
        "pdf", "png", "jpg", "jpeg", "doc", "docx", "xls", "xlsx"
    }

    # ── Pagination ────────────────────────────────────────────────────────────
    DEFAULT_PAGE_SIZE: int = 25
    MAX_PAGE_SIZE: int = 100

    # ── Sécurité ──────────────────────────────────────────────────────────────
    BCRYPT_LOG_ROUNDS: int = 12
    PASSWORD_MIN_LENGTH: int = 10
    PASSWORD_RESET_EXPIRY_HOURS: int = 1
    MAX_LOGIN_ATTEMPTS: int = 5
    ACCOUNT_LOCKOUT_MINUTES: int = 15
    TOTP_ISSUER_NAME: str = "Plateforme RH"

    # ── Chiffrement données sensibles ─────────────────────────────────────────
    FIELD_ENCRYPTION_KEY: str = os.environ.get("FIELD_ENCRYPTION_KEY", "")

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # 'json' | 'text'
    LOG_FILE: Path = BASE_DIR / "logs" / "app.log"

    # ── RGPD ──────────────────────────────────────────────────────────────────
    AUDIT_LOG_RETENTION_YEARS: int = 5
    DATA_EXPORT_TOKEN_EXPIRY_HOURS: int = 24


# =============================================================================
# Développement
# =============================================================================

class DevelopmentConfig(BaseConfig):
    """Configuration locale. Debug activé, sécurité assouplie."""

    ENV: str = "development"
    DEBUG: bool = True
    TESTING: bool = False

    # Base de données locale
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg2://rh_user:rh_pass@localhost:5432/hr_platform_dev",
    )
    SQLALCHEMY_ECHO: bool = True  # Log des requêtes SQL en console

    # Pas de HTTPS en local
    SESSION_COOKIE_SECURE: bool = False
    JWT_COOKIE_SECURE: bool = False

    # Rate limiting désactivé en dev
    RATELIMIT_ENABLED: bool = False

    # Cache en mémoire (pas Redis obligatoire)
    CACHE_TYPE: str = "SimpleCache"

    # Emails capturés localement (MailHog ou console)
    MAIL_DEBUG: bool = True
    MAIL_SUPPRESS_SEND: bool = False  # Mettre True pour bloquer les envois

    # Bcrypt moins coûteux en dev
    BCRYPT_LOG_ROUNDS: int = 4

    # Tokens JWT plus longs pour le confort en dev
    JWT_ACCESS_TOKEN_EXPIRES: timedelta = timedelta(hours=8)

    # Reload des templates sans redémarrage
    TEMPLATES_AUTO_RELOAD: bool = True

    LOG_LEVEL: str = "DEBUG"
    LOG_FORMAT: str = "text"


# =============================================================================
# Tests
# =============================================================================

class TestingConfig(BaseConfig):
    """Configuration pour la suite pytest. BDD isolée, pas de mail."""

    ENV: str = "testing"
    DEBUG: bool = False
    TESTING: bool = True

    # Base de données dédiée aux tests (écrasée à chaque run)
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg2://rh_user:rh_pass@localhost:5432/hr_platform_test",
    )
    SQLALCHEMY_ECHO: bool = False

    # CSRF désactivé pour simplifier les tests de formulaires
    WTF_CSRF_ENABLED: bool = False

    # Tokens courts pour tester l'expiration rapidement
    JWT_ACCESS_TOKEN_EXPIRES: timedelta  = timedelta(seconds=30)
    JWT_REFRESH_TOKEN_EXPIRES: timedelta = timedelta(minutes=5)

    # Cache en mémoire
    CACHE_TYPE: str = "SimpleCache"

    # Bloquer tous les envois email
    MAIL_SUPPRESS_SEND: bool = True
    MAIL_TESTING: bool = True

    # Celery synchrone (les tâches s'exécutent en ligne pendant les tests)
    CELERY_TASK_ALWAYS_EAGER: bool = True
    CELERY_TASK_EAGER_PROPAGATES: bool = True

    # Bcrypt minimal pour la vitesse des tests
    BCRYPT_LOG_ROUNDS: int = 4

    # Dossier d'upload temporaire
    UPLOAD_FOLDER: Path = Path("/tmp/hr_platform_test_uploads")

    SESSION_COOKIE_SECURE: bool = False
    JWT_COOKIE_SECURE: bool = False
    RATELIMIT_ENABLED: bool = False

    LOG_LEVEL: str = "WARNING"


# =============================================================================
# Staging (pré-production)
# =============================================================================

class StagingConfig(BaseConfig):
    """Miroir de production avec logs debug et envois email réels vers sandbox."""

    ENV: str = "staging"
    DEBUG: bool = False
    TESTING: bool = False

    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
    "STAGING_DATABASE_URL",
    os.environ.get("DATABASE_URL", "postgresql+psycopg2://rh_user:rh_pass@localhost:5432/hr_platform"),
)

    # Debug SQL uniquement si activé manuellement
    SQLALCHEMY_ECHO: bool = os.environ.get("STAGING_SQL_ECHO", "false").lower() == "true"

    LOG_LEVEL: str = "DEBUG"
    LOG_FORMAT: str = "json"


# =============================================================================
# Production
# =============================================================================

class ProductionConfig(BaseConfig):
    """Configuration de production. Sécurité maximale. Toutes les vars requises."""

    ENV: str = "production"
    DEBUG: bool = False
    TESTING: bool = False

    # Toutes ces variables DOIVENT être définies en production
    SQLALCHEMY_DATABASE_URI: str = os.environ.get("DATABASE_URL", "")
    SECRET_KEY: str              = os.environ.get("SECRET_KEY", "")
    JWT_SECRET_KEY: str          = os.environ.get("JWT_SECRET_KEY", "")
    FIELD_ENCRYPTION_KEY: str    = os.environ.get("FIELD_ENCRYPTION_KEY", "")

    SQLALCHEMY_ENGINE_OPTIONS: dict = {
        **BaseConfig.SQLALCHEMY_ENGINE_OPTIONS,
        "pool_size":     20,
        "max_overflow":  40,
    }

    # HTTPS strict
    SESSION_COOKIE_SECURE: bool = True
    SESSION_COOKIE_SAMESITE: str = "Strict"
    JWT_COOKIE_SECURE: bool = True
    JWT_COOKIE_SAMESITE: str = "Strict"

    # Sécurité renforcée
    BCRYPT_LOG_ROUNDS: int = 14
    MAX_LOGIN_ATTEMPTS: int = 3
    ACCOUNT_LOCKOUT_MINUTES: int = 30

    LOG_LEVEL: str = "WARNING"
    LOG_FORMAT: str = "json"
