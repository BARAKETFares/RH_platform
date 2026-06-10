"""
Configuration production.
Toutes les valeurs sensibles DOIVENT venir des variables d'environnement.
Aucune valeur par défaut pour les secrets.
"""
import os
from .base import BaseConfig


class ProductionConfig(BaseConfig):
    ENV: str = "production"
    DEBUG: bool = False
    TESTING: bool = False

    # Sécurité renforcée
    SESSION_COOKIE_SECURE: bool = True
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "Strict"
    PREFERRED_URL_SCHEME: str = "https"

    # JWT — cookies sécurisés HTTPS uniquement
    JWT_COOKIE_SECURE: bool = True
    JWT_COOKIE_CSRF_PROTECT: bool = True

    # BDD — Pool plus large pour la charge production
    SQLALCHEMY_ENGINE_OPTIONS: dict = {
        **BaseConfig.SQLALCHEMY_ENGINE_OPTIONS,
        "pool_size": 20,
        "max_overflow": 40,
    }

    # Logs JSON structurés vers stdout (collecte par ELK / Loki)
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "WARNING")
    LOG_FORMAT: str = "json"

    # HSTS — à configurer aussi dans Nginx
    SEND_FILE_MAX_AGE_DEFAULT: int = 31536000             # 1 an pour les assets statiques

    # Validation obligatoire des variables d'environnement critiques
    @classmethod
    def validate(cls) -> None:
        required = [
            "SECRET_KEY", "JWT_SECRET_KEY", "DATABASE_URL",
            "REDIS_URL", "MAIL_USERNAME", "MAIL_PASSWORD",
        ]
        missing = [var for var in required if not os.environ.get(var)]
        if missing:
            raise EnvironmentError(
                f"Variables d'environnement manquantes en production : {', '.join(missing)}"
            )
