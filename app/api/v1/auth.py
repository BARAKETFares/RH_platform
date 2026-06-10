"""
API REST v1 — Authentification
JWT stateless, pas de session Flask.

Endpoints :
  POST /api/v1/auth/login           → access_token + refresh_token
  POST /api/v1/auth/logout          → révocation de la session courante
  POST /api/v1/auth/refresh         → nouvel access_token
  POST /api/v1/auth/forgot-password → envoi email de réinitialisation
  POST /api/v1/auth/reset-password  → confirmation du reset avec token

Format de réponse uniforme :
  Succès : { "data": {...} }
  Erreur : { "error": { "code": N, "message": "...", "details": {...} } }
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_jwt_extended import (
    get_jwt,
    get_jwt_identity,
    jwt_required,
)

from app.extensions import limiter
from app.services.auth_service import (
    authenticate,
    authenticate_2fa,
    confirm_password_reset,
    logout,
    refresh_access_token,
    request_password_reset,
)
from app.utils.exceptions import (
    AuthenticationError,
    BusinessRuleError,
    ValidationError,
)

bp = Blueprint("api_auth", __name__)


# =============================================================================
# Helpers
# =============================================================================

def _ok(data: dict, status: int = 200):
    return jsonify({"data": data}), status


def _err(message: str, code: int, details: dict | None = None):
    payload: dict = {"error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = details
    return jsonify(payload), code


def _client_ip() -> str:
    return (
        request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")
        .split(",")[0]
        .strip()
    )


# =============================================================================
# POST /login
# =============================================================================

@bp.post("/login")
@limiter.limit("10 per minute; 3 per second")
def login():
    """
    Authentifie un utilisateur avec email + mot de passe.

    Body JSON :
        {
            "email":    "utilisateur@entreprise.fr",
            "password": "MonMotDePasse1!"
        }

    Réponses :

        200 — Connexion complète :
            {
                "data": {
                    "access_token":  "<jwt>",
                    "refresh_token": "<jwt>",
                    "token_type":    "Bearer",
                    "user": {
                        "id": 1, "email": "...", "role": "manager", ...
                    }
                }
            }

        200 — 2FA requis (pas encore de tokens) :
            {
                "data": {
                    "requires_2fa": true,
                    "user_id": 42
                }
            }

            → Le client doit appeler POST /login/2fa avec user_id + code TOTP.

        200 — Changement de mot de passe forcé :
            {
                "data": {
                    "requires_password_change": true,
                    "user_id": 42
                }
            }

        400 — Champs manquants.
        401 — Identifiants incorrects, compte verrouillé ou inactif.
    """
    body     = request.get_json(silent=True) or {}
    email    = str(body.get("email", "")).strip()
    password = str(body.get("password", ""))

    if not email or not password:
        return _err("Les champs email et password sont obligatoires.", 400)

    try:
        result = authenticate(
            email=email,
            password=password,
            ip_address=_client_ip(),
            user_agent=request.user_agent.string,
        )
    except AuthenticationError as exc:
        return _err(str(exc), 401)

    return _ok(result)


# =============================================================================
# POST /login/2fa
# =============================================================================

@bp.post("/login/2fa")
@limiter.limit("10 per minute")
def login_2fa():
    """
    Finalise la connexion après vérification du code TOTP.

    Appelé uniquement si POST /login a retourné { "requires_2fa": true }.

    Body JSON :
        {
            "user_id": 42,
            "code":    "123456"
        }

    Réponses :

        200 — Connexion complète (même structure que /login succès).
        400 — Champs manquants ou format de code invalide.
        401 — Code TOTP incorrect.
    """
    body    = request.get_json(silent=True) or {}
    user_id = body.get("user_id")
    code    = str(body.get("code", "")).strip()

    if not user_id or not code:
        return _err("Les champs user_id et code sont obligatoires.", 400)

    if not code.isdigit() or len(code) != 6:
        return _err("Le code doit contenir exactement 6 chiffres.", 400)

    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        return _err("user_id invalide.", 400)

    try:
        result = authenticate_2fa(
            user_id=user_id,
            totp_code=code,
            ip_address=_client_ip(),
            user_agent=request.user_agent.string,
        )
    except AuthenticationError as exc:
        return _err(str(exc), 401)

    return _ok(result)


# =============================================================================
# POST /logout
# =============================================================================

@bp.post("/logout")
@jwt_required()
def logout_route():
    """
    Révoque la session courante de l'utilisateur authentifié.

    La révocation est côté serveur : même si le client conserve le token,
    la session associée (session_id dans les claims) est invalidée en base.
    Le token expirera naturellement selon JWT_ACCESS_TOKEN_EXPIRES.

    Header requis :
        Authorization: Bearer <access_token>

    Body JSON (optionnel) :
        { "all_devices": true }   → révoque TOUTES les sessions actives.

    Réponses :

        200 — Session révoquée.
        401 — Token absent, invalide ou expiré.
    """
    claims     = get_jwt()
    user_id    = int(get_jwt_identity())
    session_id = claims.get("session_id")

    body        = request.get_json(silent=True) or {}
    all_devices = bool(body.get("all_devices", False))

    # all_devices=True → on passe session_id=None pour tout révoquer
    logout(user_id, session_id=None if all_devices else session_id)

    message = (
        "Déconnecté de tous les appareils."
        if all_devices
        else "Déconnexion réussie."
    )
    return _ok({"message": message})


# =============================================================================
# POST /refresh
# =============================================================================

@bp.post("/refresh")
@jwt_required(refresh=True)
def refresh():
    """
    Émet un nouvel access_token à partir d'un refresh_token valide.

    Le refresh_token doit être fourni dans le header Authorization.
    La session en base est vérifiée : si elle a été révoquée (logout),
    le refresh est rejeté même si le JWT n'a pas expiré.

    Header requis :
        Authorization: Bearer <refresh_token>

    Réponses :

        200 :
            {
                "data": {
                    "access_token": "<nouveau_jwt>",
                    "token_type":   "Bearer"
                }
            }

        401 — Refresh token absent, invalide, expiré ou session révoquée.
    """
    claims     = get_jwt()
    user_id    = int(get_jwt_identity())
    session_id = claims.get("session_id")

    if not session_id:
        return _err("Session introuvable dans le token.", 401)

    try:
        result = refresh_access_token(user_id, session_id)
    except AuthenticationError as exc:
        return _err(str(exc), 401)

    return _ok(result)


# =============================================================================
# POST /forgot-password
# =============================================================================

@bp.post("/forgot-password")
@limiter.limit("5 per hour; 2 per minute")
def forgot_password():
    """
    Déclenche l'envoi d'un email de réinitialisation de mot de passe.

    Réponse toujours identique (200) que l'email existe ou non :
    évite l'énumération d'adresses email (timing-safe).

    Body JSON :
        { "email": "utilisateur@entreprise.fr" }

    Réponses :

        200 :
            {
                "data": {
                    "message": "Si un compte existe avec cette adresse,
                                un email a été envoyé."
                }
            }

        400 — Champ email manquant ou format invalide.
    """
    body  = request.get_json(silent=True) or {}
    email = str(body.get("email", "")).strip()

    if not email:
        return _err("Le champ email est obligatoire.", 400)

    # Validation basique du format avant d'appeler le service
    import re
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return _err("Format d'adresse email invalide.", 400)

    # Appel silencieux — ne jamais propager d'erreur indiquant si l'email existe
    request_password_reset(email)

    return _ok({
        "message": (
            "Si un compte est associé à cette adresse, "
            "vous recevrez un email contenant un lien valide 1 heure."
        )
    })


# =============================================================================
# POST /reset-password
# =============================================================================

@bp.post("/reset-password")
@limiter.limit("10 per hour")
def reset_password():
    """
    Confirme la réinitialisation du mot de passe avec le token reçu par email.

    Le token est à usage unique et expire après PASSWORD_RESET_EXPIRY_HOURS.
    Toutes les sessions actives sont révoquées après le reset.

    Body JSON :
        {
            "token":            "<token_reçu_par_email>",
            "password":         "NouveauMotDePasse1!",
            "password_confirm": "NouveauMotDePasse1!"
        }

    Réponses :

        200 :
            {
                "data": {
                    "message": "Mot de passe réinitialisé. Vous pouvez vous connecter."
                }
            }

        400 — Champs manquants.
        422 — Token invalide/expiré, mots de passe non concordants
              ou mot de passe trop faible :
            {
                "error": {
                    "code":    422,
                    "message": "...",
                    "details": { "errors": ["Au moins 10 caractères requis.", ...] }
                }
            }
    """
    body     = request.get_json(silent=True) or {}
    token    = str(body.get("token", "")).strip()
    password = str(body.get("password", ""))
    confirm  = str(body.get("password_confirm", ""))

    if not token or not password or not confirm:
        return _err(
            "Les champs token, password et password_confirm sont obligatoires.",
            400,
        )

    if password != confirm:
        return _err("Les mots de passe ne correspondent pas.", 422)

    try:
        confirm_password_reset(token, password)
    except ValidationError as exc:
        return _err(str(exc), 422, exc.details or None)

    return _ok({
        "message": "Mot de passe réinitialisé avec succès. Vous pouvez vous connecter."
    })