"""
Instanciation centralisée des extensions Flask.
"""
from __future__ import annotations

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_mail import Mail
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_babel import Babel
from celery import Celery

# ── SQLAlchemy ────────────────────────────────────────────────────────────────
db: SQLAlchemy = SQLAlchemy(
    engine_options={
        "pool_pre_ping": True,
        "pool_recycle":  1800,
        "pool_size":     10,
        "max_overflow":  20,
    }
)

# ── Flask-Migrate ─────────────────────────────────────────────────────────────
migrate: Migrate = Migrate()

# ── JWT ───────────────────────────────────────────────────────────────────────
jwt: JWTManager = JWTManager()

# ── Flask-Login ───────────────────────────────────────────────────────────────
login_manager: LoginManager = LoginManager()
login_manager.login_view              = "auth.login_get"  # type: ignore[assignment]
login_manager.login_message           = "Veuillez vous connecter pour accéder à cette page."
login_manager.login_message_category  = "warning"
login_manager.session_protection      = "strong"

# ── CSRF ──────────────────────────────────────────────────────────────────────
csrf: CSRFProtect = CSRFProtect()

# ── Mail ──────────────────────────────────────────────────────────────────────
mail: Mail = Mail()

# ── Cache ─────────────────────────────────────────────────────────────────────
cache: Cache = Cache()

# ── Rate Limiting ─────────────────────────────────────────────────────────────
limiter: Limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)

# ── Babel ─────────────────────────────────────────────────────────────────────
babel: Babel = Babel()

# ── Celery ────────────────────────────────────────────────────────────────────
celery: Celery = Celery()