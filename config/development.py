"""Configuration développement local."""
import os
from .base import BaseConfig


class DevelopmentConfig(BaseConfig):
    ENV: str = "development"
    DEBUG: bool = True
    TESTING: bool = False

    # BDD locale — valeur par défaut si DATABASE_URL absent
    SQLALCHEMY_DATABASE_URI: str = os.getenv(
        "DATABASE_URL",
        "postgresql://hr_user:hr_password@localhost:5432/hr_platform_dev",
    )
    SQLALCHEMY_RECORD_QUERIES: bool = True               # Log des requêtes lentes
    SQLALCHEMY_ENGINE_OPTIONS: dict = {
        **BaseConfig.SQLALCHEMY_ENGINE_OPTIONS,
        "pool_size": 5,
        "echo": False,                                   # Passer à True pour debugger SQL
    }

    # JWT — cookies non sécurisés acceptable en dev (HTTP local)
    JWT_COOKIE_SECURE: bool = False
    JWT_ACCESS_TOKEN_EXPIRES_SECONDS: int = 3600 * 8    # 8h en dev pour le confort

    # Cache — peut fonctionner sans Redis en dev
    CACHE_TYPE: str = os.getenv("CACHE_TYPE", "SimpleCache")

    # Emails — interceptés par Mailhog en dev
    MAIL_SERVER: str = os.getenv("MAIL_SERVER", "localhost")
    MAIL_PORT: int = int(os.getenv("MAIL_PORT", 1025))
    MAIL_USE_TLS: bool = False

    # Upload en local
    UPLOAD_FOLDER: str = os.getenv("UPLOAD_FOLDER", "/tmp/hr_platform/uploads")

    # Sécurité allégée en dev
    WTF_CSRF_ENABLED: bool = os.getenv("WTF_CSRF_ENABLED", "true").lower() == "true"
    SESSION_COOKIE_SECURE: bool = False

    # Logs verbeux
    LOG_LEVEL: str = "DEBUG"
    LOG_FORMAT: str = "text"

    # Rate limiting désactivé en dev
    RATELIMIT_ENABLED: bool = False
