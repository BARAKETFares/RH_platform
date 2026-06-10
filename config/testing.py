"""Configuration pour la suite de tests (pytest)."""
import os
from .base import BaseConfig


class TestingConfig(BaseConfig):
    ENV: str = "testing"
    DEBUG: bool = False
    TESTING: bool = True

    # BDD de test — isolée et recréée à chaque run
    SQLALCHEMY_DATABASE_URI: str = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql://hr_user:hr_password@localhost:5432/hr_platform_test",
    )
    SQLALCHEMY_ENGINE_OPTIONS: dict = {
        "pool_pre_ping": True,
        "pool_size": 2,
    }

    # Désactivations pour les tests
    WTF_CSRF_ENABLED: bool = False
    JWT_COOKIE_SECURE: bool = False
    RATELIMIT_ENABLED: bool = False
    MAIL_SUPPRESS_SEND: bool = True

    # Cache en mémoire (pas besoin de Redis)
    CACHE_TYPE: str = "SimpleCache"

    # Celery — exécution synchrone dans les tests
    CELERY_TASK_ALWAYS_EAGER: bool = True
    CELERY_TASK_EAGER_PROPAGATES: bool = True

    # Tokens JWT très courts en test
    JWT_ACCESS_TOKEN_EXPIRES_SECONDS: int = 60

    # Upload vers dossier temporaire
    UPLOAD_FOLDER: str = "/tmp/hr_platform_test/uploads"

    # Logs minimaux
    LOG_LEVEL: str = "ERROR"
    LOG_FORMAT: str = "text"

    # Clés secrètes fixes pour la reproductibilité des tests
    SECRET_KEY: str = "test-secret-key-not-for-production-use"
    JWT_SECRET_KEY: str = "test-jwt-secret-key-not-for-production-use"
