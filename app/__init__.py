"""
Factory de l'application Flask (Application Factory Pattern).

Usage :
    from app import create_app
    app = create_app("development")

La séparation entre instanciation des extensions et liaison à l'app
permet les tests unitaires sans démarrer un serveur complet.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path        # ← ajouter cette ligne
from typing import Optional

from flask import Flask

from config import config_registry
from .extensions import (
    db, migrate, jwt, login_manager,
    csrf, mail, cache, limiter, babel, celery,
)


def create_app(env: Optional[str] = None) -> Flask:
    """
    Crée et configure une instance Flask.

    Args:
        env: Nom de l'environnement ('development', 'testing',
             'staging', 'production'). Si None, lit APP_ENV ou 'development'.

    Returns:
        Instance Flask configurée et prête à être servie.
    """
    
    env = env or os.getenv("APP_ENV", "development")
    cfg = config_registry.get(env, config_registry["default"])

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    # ── 1. Chargement de la configuration ────────────────────────────────────
    app.config.from_object(cfg)

    # Variables d'env préfixées HR_ écrasent la config (optionnel)
    app.config.from_prefixed_env(prefix="HR")

    # ── 2. Création des dossiers nécessaires ─────────────────────────────────
    _ensure_directories(app)

    # ── 3. Initialisation des extensions ─────────────────────────────────────
    _init_extensions(app)

    # ── 4. Configuration de Celery ────────────────────────────────────────────
    _configure_celery(app)

    # ── 5. Enregistrement des Blueprints ─────────────────────────────────────
    _register_blueprints(app)

    # ── 6. Enregistrement de l'API REST ──────────────────────────────────────
    _register_api(app)

    # ── 7. Gestionnaires d'erreurs ────────────────────────────────────────────
    _register_error_handlers(app)

    # ── 8. Filtres et fonctions Jinja2 ────────────────────────────────────────
    _register_template_filters(app)

    # ── 9. Configuration du logging ───────────────────────────────────────────
    _configure_logging(app)

    # ── 10. Hooks de requête ──────────────────────────────────────────────────
    _register_request_hooks(app)

    app.logger.info(
        "Application démarrée",
        extra={"env": env, "debug": app.debug},
    )

    # Route racine → redirect vers login
    @app.route("/")
    def index():
        from flask import redirect, url_for
        return redirect(url_for("auth.login_get"))

    app.logger.info("Application démarrée [env=%s]", env)
    
    return app

def _load_dotenv() -> None:
    """Charge .env depuis la racine du projet si python-dotenv est installé."""
    try:
        from dotenv import load_dotenv
        env_file = Path(__file__).resolve().parent.parent / ".env"
        if env_file.exists():
            load_dotenv(env_file)
    except ImportError:
        pass
# =============================================================================
# Sous-routines privées
# =============================================================================

def _ensure_directories(app: Flask) -> None:
    """Crée les dossiers runtime si absents."""
    from pathlib import Path
    dirs = [
        app.config.get("UPLOAD_FOLDER"),
        app.config.get("LOG_FILE", Path("logs/app.log")).parent,
    ]
    for d in dirs:
        if d:
            Path(d).mkdir(parents=True, exist_ok=True)


def _init_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db, directory="migrations")

    # ── Flask-Login — user_loader enregistré AVANT init_app ──────────────────
    from .services.auth_service import load_user_by_id

    @login_manager.user_loader
    def user_loader(user_id: str):
        return load_user_by_id(user_id)

    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import jsonify, redirect, request, url_for
        if request.path.startswith("/api/"):
            return jsonify({"error": {"code": 401, "message": "Authentification requise."}}), 401
        return redirect(url_for("auth.login_get", next=request.url))

    login_manager.init_app(app)

    # ── JWT ───────────────────────────────────────────────────────────────────
    jwt.init_app(app)

    from .services.auth_service import load_user_from_jwt
    jwt.user_lookup_loader(load_user_from_jwt)

    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_data):
        from flask import jsonify
        return jsonify({"error": {"code": 401, "message": "Token expiré."}}), 401

    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        from flask import jsonify
        return jsonify({"error": {"code": 401, "message": "Token invalide."}}), 401

    @jwt.unauthorized_loader
    def missing_token_callback(error):
        from flask import jsonify
        return jsonify({"error": {"code": 401, "message": "Token manquant."}}), 401

    @jwt.revoked_token_loader
    def revoked_token_callback(jwt_header, jwt_data):
        from flask import jsonify
        return jsonify({"error": {"code": 401, "message": "Token révoqué."}}), 401

    # ── Autres extensions ─────────────────────────────────────────────────────
    csrf.init_app(app)
    csrf.exempt("app.api")
    mail.init_app(app)
    cache.init_app(app)
    limiter.init_app(app)
    babel.init_app(app)


def _configure_celery(app: Flask) -> None:
    """
    Configure Celery avec le contexte Flask.

    Les tâches peuvent utiliser les extensions Flask (db, mail…)
    grâce au ContextTask qui pousse un app_context automatiquement.
    """
    celery.config_from_object({
        "broker_url":          app.config["CELERY_BROKER_URL"],
        "result_backend":      app.config["CELERY_RESULT_BACKEND"],
        "task_serializer":     app.config["CELERY_TASK_SERIALIZER"],
        "result_serializer":   app.config["CELERY_RESULT_SERIALIZER"],
        "accept_content":      app.config["CELERY_ACCEPT_CONTENT"],
        "timezone":            app.config["CELERY_TIMEZONE"],
        "enable_utc":          app.config["CELERY_ENABLE_UTC"],
        "task_track_started":  app.config["CELERY_TASK_TRACK_STARTED"],
        "task_time_limit":     app.config["CELERY_TASK_TIME_LIMIT"],
        "beat_schedule":       app.config["CELERY_BEAT_SCHEDULE"],
    })

    # ContextTask : assure qu'un app_context Flask est actif dans chaque tâche
    class ContextTask(celery.Task):  # type: ignore[misc]
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    app.extensions["celery"] = celery


def _register_blueprints(app: Flask) -> None:
    """Enregistre tous les Blueprints SSR avec leur préfixe URL."""
    from .blueprints.auth        import bp as auth_bp
    from .blueprints.employees   import bp as employees_bp
    from .blueprints.absences    import bp as absences_bp
    from .blueprints.recruitment import bp as recruitment_bp
    from .blueprints.performance import bp as performance_bp
    from .blueprints.payroll     import bp as payroll_bp
    from .blueprints.training    import bp as training_bp
    from .blueprints.reporting   import bp as reporting_bp
    from .blueprints.admin       import bp as admin_bp

    app.register_blueprint(auth_bp,        url_prefix="/auth")
    app.register_blueprint(employees_bp,   url_prefix="/employees")
    app.register_blueprint(absences_bp,    url_prefix="/absences")
    app.register_blueprint(recruitment_bp, url_prefix="/recruitment")
    app.register_blueprint(performance_bp, url_prefix="/performance")
    app.register_blueprint(payroll_bp,     url_prefix="/payroll")
    app.register_blueprint(training_bp,    url_prefix="/training")
    app.register_blueprint(reporting_bp,   url_prefix="/reporting")
    app.register_blueprint(admin_bp,       url_prefix="/admin")


def _register_api(app: Flask) -> None:
    """Enregistre le Blueprint de l'API REST v1."""
    from .api.v1 import bp as api_v1_bp
    app.register_blueprint(api_v1_bp, url_prefix="/api/v1")


def _register_error_handlers(app: Flask) -> None:
    """Gestionnaires d'erreurs HTTP centralisés."""
    from .utils.error_handlers import (
        handle_400, handle_403, handle_404,
        handle_405, handle_422, handle_429, handle_500,
    )
    app.register_error_handler(400, handle_400)
    app.register_error_handler(403, handle_403)
    app.register_error_handler(404, handle_404)
    app.register_error_handler(405, handle_405)
    app.register_error_handler(422, handle_422)
    app.register_error_handler(429, handle_429)
    app.register_error_handler(500, handle_500)


def _register_template_filters(app: Flask) -> None:
    """Filtres Jinja2 personnalisés disponibles dans tous les templates."""
    from .utils.template_filters import register_filters
    register_filters(app)


def _configure_logging(app: Flask) -> None:
    """Configure le logging structuré (JSON en prod, texte en dev)."""
    from .utils.logging_config import configure_logging
    configure_logging(app)


def _register_request_hooks(app: Flask) -> None:
    """
    Before/after request hooks globaux :
    - Injection de l'utilisateur courant dans g
    - En-têtes de sécurité sur chaque réponse
    """
    from .utils.security_headers import add_security_headers

    @app.after_request
    def apply_security_headers(response):
        return add_security_headers(response)
