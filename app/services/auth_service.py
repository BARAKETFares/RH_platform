"""
Service d'authentification.

Responsabilités :
  - Vérification des identifiants (email + mot de passe)
  - Création et révocation des tokens JWT
  - Réinitialisation du mot de passe
  - Déconnexion (révocation de session)

Règles d'architecture :
  - Aucun objet `request` Flask ici → testabilité garantie
  - Les erreurs sont des exceptions métier (app.utils.exceptions)
  - Les commits SQLAlchemy sont faits dans ce service
  - L'audit log est non-bloquant (échec silencieux)
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from flask import current_app, render_template, url_for
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_jti,
)
from flask_mail import Message

from app.extensions import db, mail
from app.models.user import PasswordResetToken, User, UserSession
from app.utils.exceptions import (
    AuthenticationError,
    BusinessRuleError,
    ValidationError,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================================
# Connexion
# =============================================================================

def authenticate(
    email: str,
    password: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict:
    """
    Authentifie un utilisateur par email + mot de passe.

    Gère le verrouillage de compte, la détection du 2FA requis
    et le changement de mot de passe forcé.

    Args:
        email:      Adresse email (insensible à la casse).
        password:   Mot de passe en clair.
        ip_address: IP du client (pour l'audit et la session).
        user_agent: User-Agent du client (pour la session).

    Returns:
        Dict contenant les tokens JWT et le profil utilisateur,
        ou un flag intermédiaire si une étape supplémentaire est requise :

        Connexion complète :
            {
                "access_token":  str,
                "refresh_token": str,
                "token_type":    "Bearer",
                "user":          dict,
            }

        2FA requis :
            { "requires_2fa": True, "user_id": int }

        Changement de mot de passe forcé :
            { "requires_password_change": True, "user_id": int }

    Raises:
        AuthenticationError: identifiants incorrects, compte inactif ou verrouillé.
    """
    user = User.get_by_email(email)

    # Message générique intentionnel — ne pas indiquer si l'email existe
    _generic_error = "Email ou mot de passe incorrect."

    if user is None:
        _audit("login_failed", None, email, ip_address)
        logger.warning("Tentative login email inconnu", extra={"email": email})
        raise AuthenticationError(_generic_error)

    if user.is_locked:
        remaining = user.lockout_remaining_seconds
        raise AuthenticationError(
            f"Compte verrouillé. Réessayez dans {remaining // 60} min {remaining % 60} s."
        )

    if not user._is_active:
        raise AuthenticationError(
            "Ce compte est désactivé. Contactez votre administrateur."
        )

    if not user.check_password(password):
        user.record_failed_login()
        db.session.commit()
        _audit("login_failed", user.id, user.email, ip_address)
        logger.warning("Échec mot de passe", extra={"user_id": user.id})
        raise AuthenticationError(_generic_error)

    # ── Étape supplémentaire requise ? ────────────────────────────────────────
    if user.totp_enabled:
        logger.debug("2FA requis", extra={"user_id": user.id})
        return {"requires_2fa": True, "user_id": user.id}

    if user.force_password_change:
        user.record_successful_login(ip_address)
        db.session.commit()
        return {"requires_password_change": True, "user_id": user.id}

    return _finalize_login(user, ip_address, user_agent)


def authenticate_2fa(
    user_id: int,
    totp_code: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict:
    """
    Finalise la connexion après vérification du code TOTP.

    Args:
        user_id:    ID de l'utilisateur (fourni lors de l'étape 1).
        totp_code:  Code TOTP à 6 chiffres.
        ip_address: IP du client.
        user_agent: User-Agent du client.

    Returns:
        Même structure que `authenticate()` en cas de succès complet.

    Raises:
        AuthenticationError: code TOTP invalide ou utilisateur introuvable.
    """
    user = db.session.get(User, user_id)
    if not user or not user._is_active:
        raise AuthenticationError("Utilisateur introuvable.")

    if not user.verify_totp(totp_code):
        user.record_failed_login()
        db.session.commit()
        _audit("login_failed", user.id, user.email, ip_address)
        raise AuthenticationError("Code d'authentification incorrect.")

    return _finalize_login(user, ip_address, user_agent)


def _finalize_login(
    user: User,
    ip_address: Optional[str],
    user_agent: Optional[str],
) -> dict:
    """
    Étape finale commune : enregistre la session, génère les tokens JWT.

    Returns:
        { access_token, refresh_token, token_type, user }
    """
    refresh_ttl: timedelta = current_app.config.get(
        "JWT_REFRESH_TOKEN_EXPIRES", timedelta(days=30)
    )

    # Enregistrement de la session en base
    session = UserSession(
        user_id=user.id,
        ip_address=ip_address or "unknown",
        user_agent=user_agent,
        expires_at=_utcnow() + refresh_ttl,
    )
    db.session.add(session)

    user.record_successful_login(ip_address)
    db.session.commit()

    # Génération des tokens JWT avec claims personnalisés
    access_token, refresh_token = _create_token_pair(user, session.id)

    _audit("login", user.id, user.email, ip_address)
    logger.info("Connexion réussie", extra={"user_id": user.id})

    return {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "token_type":    "Bearer",
        "user":          user.to_dict(include_permissions=True),
    }


# =============================================================================
# Création des tokens JWT
# =============================================================================

def _create_token_pair(user: User, session_id: str) -> tuple[str, str]:
    """
    Crée un access token et un refresh token pour l'utilisateur.

    Claims supplémentaires injectés dans le JWT :
      - role        : nom du rôle (ex: "manager")
      - permissions : liste des codes de permission du rôle
      - session_id  : ID de la UserSession en base (révocation côté serveur)

    Args:
        user:       Instance User authentifiée.
        session_id: ID de la session enregistrée en base.

    Returns:
        Tuple (access_token, refresh_token) encodés en JWT signé.
    """
    additional_claims = {
        "role":        user.role.name,
        "permissions": list(user.role.permission_codes),
        "session_id":  session_id,
    }

    access_token = create_access_token(
        identity=str(user.id),
        additional_claims=additional_claims,
    )
    refresh_token = create_refresh_token(
        identity=str(user.id),
        additional_claims={"session_id": session_id},
    )

    return access_token, refresh_token


def refresh_access_token(user_id: int, session_id: str) -> dict:
    """
    Émet un nouvel access token à partir d'un refresh token valide.

    Vérifie que la session en base est toujours active (non révoquée).
    Met à jour le timestamp de dernière activité de la session.

    Args:
        user_id:    Extrait de jwt_identity (get_jwt_identity()).
        session_id: Extrait des claims du refresh token.

    Returns:
        { access_token: str, token_type: "Bearer" }

    Raises:
        AuthenticationError: session expirée, révoquée ou utilisateur inactif.
    """
    user = db.session.get(User, user_id)
    if not user or not user._is_active:
        raise AuthenticationError("Utilisateur introuvable ou inactif.")

    session = UserSession.get_active(session_id, user_id)
    if not session:
        raise AuthenticationError("Session expirée. Veuillez vous reconnecter.")

    session.touch()
    db.session.commit()

    additional_claims = {
        "role":        user.role.name,
        "permissions": list(user.role.permission_codes),
        "session_id":  session_id,
    }
    access_token = create_access_token(
        identity=str(user.id),
        additional_claims=additional_claims,
    )

    return {"access_token": access_token, "token_type": "Bearer"}


# =============================================================================
# Déconnexion
# =============================================================================

def logout(user_id: int, session_id: Optional[str] = None) -> None:
    """
    Révoque la session de l'utilisateur.

    Si session_id est fourni, révoque uniquement cette session (déconnexion
    du device courant). Sinon, révoque toutes les sessions actives
    (déconnexion globale de tous les appareils).

    Args:
        user_id:    ID de l'utilisateur connecté.
        session_id: ID de la session à révoquer (optionnel).
    """
    if session_id:
        session = UserSession.get_active(session_id, user_id)
        if session:
            session.revoke()
    else:
        UserSession.revoke_all_for_user(user_id)

    db.session.commit()
    _audit("logout", user_id)
    logger.info("Déconnexion", extra={"user_id": user_id, "session_id": session_id})


# =============================================================================
# Vérification du mot de passe
# =============================================================================

def verify_password(user_id: int, plain_password: str) -> bool:
    """
    Vérifie le mot de passe actuel d'un utilisateur sans le modifier.

    Utilisé pour les opérations sensibles nécessitant une reconfirmation
    (désactivation 2FA, suppression de compte, export de données…).

    Args:
        user_id:        ID de l'utilisateur.
        plain_password: Mot de passe en clair à vérifier.

    Returns:
        True si le mot de passe est correct, False sinon.
    """
    user = db.session.get(User, user_id)
    if not user:
        return False
    return user.check_password(plain_password)


def change_password(
    user_id: int,
    current_password: str,
    new_password: str,
) -> None:
    """
    Change le mot de passe d'un utilisateur authentifié.

    Révoque toutes les sessions existantes après le changement (sécurité),
    sauf la session courante dont l'ID peut être passé si on souhaite
    la conserver (non implémenté ici pour la simplicité).

    Args:
        user_id:          ID de l'utilisateur.
        current_password: Mot de passe actuel (vérification obligatoire).
        new_password:     Nouveau mot de passe.

    Raises:
        AuthenticationError: mot de passe actuel incorrect.
        ValidationError:     nouveau mot de passe trop faible.
        BusinessRuleError:   nouveau mot de passe identique à l'ancien.
    """
    user = User.get_or_404(user_id)

    if not user.check_password(current_password):
        raise AuthenticationError("Mot de passe actuel incorrect.")

    if current_password == new_password:
        raise BusinessRuleError(
            "Le nouveau mot de passe doit être différent de l'actuel."
        )

    _validate_password_strength(new_password)

    user.set_password(new_password)
    user.force_password_change = False

    # Révoquer toutes les sessions (l'utilisateur devra se reconnecter)
    UserSession.revoke_all_for_user(user_id)

    db.session.commit()
    _audit("password_change", user.id, user.email)
    logger.info("Mot de passe modifié", extra={"user_id": user_id})


# =============================================================================
# Réinitialisation du mot de passe
# =============================================================================

def request_password_reset(email: str) -> None:
    """
    Déclenche l'envoi d'un email de réinitialisation de mot de passe.

    Comportement timing-safe : ne lève jamais d'erreur que l'email
    existe ou non (prévient l'énumération d'adresses email).

    Args:
        email: Adresse email de l'utilisateur.
    """
    user = User.get_by_email(email)

    if not user or not user._is_active:
        # Sortie silencieuse — ne pas révéler si l'email est connu
        logger.info("Reset demandé pour email inconnu/inactif", extra={"email": email})
        return

    token_obj, raw_token = PasswordResetToken.create_for_user(user)
    db.session.commit()

    _send_reset_email(user, raw_token)
    logger.info("Email de reset envoyé", extra={"user_id": user.id})


def confirm_password_reset(raw_token: str, new_password: str) -> None:
    """
    Valide le token de reset et applique le nouveau mot de passe.

    Après le reset :
      - Le token est marqué comme utilisé (usage unique)
      - Toutes les sessions actives sont révoquées
      - force_password_change est remis à False

    Args:
        raw_token:    Token brut reçu dans le lien email.
        new_password: Nouveau mot de passe choisi par l'utilisateur.

    Raises:
        ValidationError: token invalide/expiré ou mot de passe trop faible.
    """
    token_obj = PasswordResetToken.find_valid(raw_token)
    if not token_obj:
        raise ValidationError(
            "Ce lien de réinitialisation est invalide ou a expiré. "
            "Veuillez effectuer une nouvelle demande."
        )

    _validate_password_strength(new_password)

    user = token_obj.user
    user.set_password(new_password)
    user.force_password_change = False
    token_obj.mark_used()

    # Invalider toutes les sessions (changement de credential = révocation globale)
    UserSession.revoke_all_for_user(user.id)

    db.session.commit()
    _audit("password_change", user.id, user.email)
    logger.info("Mot de passe réinitialisé via token", extra={"user_id": user.id})


# =============================================================================
# Chargement utilisateur (callbacks Flask-Login / JWT)
# =============================================================================

def load_user_by_id(user_id: str) -> Optional[User]:
    """
    Callback Flask-Login (@login_manager.user_loader).

    Charge l'utilisateur depuis son ID de session.
    Retourne None si le compte est inactif ou verrouillé
    (Flask-Login traitera l'utilisateur comme non authentifié).

    Args:
        user_id: Chaîne retournée par User.get_id().
    """
    try:
        user = db.session.get(User, int(user_id))
        return user if (user and user.is_active) else None
    except (ValueError, TypeError):
        return None


def load_user_from_jwt(jwt_header: dict, jwt_data: dict) -> Optional[User]:
    """
    Callback JWT-Extended (@jwt.user_lookup_loader).

    Charge l'utilisateur depuis les claims JWT et vérifie
    que la session associée est toujours active en base.

    Args:
        jwt_header: En-tête du JWT décodé.
        jwt_data:   Payload du JWT décodé (claims).

    Returns:
        Instance User si tout est valide, None sinon.
    """
    try:
        user_id    = int(jwt_data["sub"])
        session_id = jwt_data.get("session_id")

        user = db.session.get(User, user_id)
        if not user or not user.is_active:
            return None

        # Vérification de la révocation côté serveur via la session
        if session_id:
            session = UserSession.get_active(session_id, user_id)
            if not session:
                return None

        return user

    except (ValueError, TypeError, KeyError):
        return None


# =============================================================================
# Helpers privés
# =============================================================================

def _validate_password_strength(password: str) -> None:
    """
    Valide la robustesse d'un mot de passe.
    Lève ValidationError si les critères ne sont pas satisfaits.
    """
    import re

    min_length = current_app.config.get("PASSWORD_MIN_LENGTH", 10)
    errors: list[str] = []

    if len(password) < min_length:
        errors.append(f"Au moins {min_length} caractères requis.")
    if not re.search(r"[A-Z]", password):
        errors.append("Au moins une lettre majuscule requise.")
    if not re.search(r"[a-z]", password):
        errors.append("Au moins une lettre minuscule requise.")
    if not re.search(r"\d", password):
        errors.append("Au moins un chiffre requis.")
    if not re.search(r"[!@#$%^&*()\-_=+\[\]{};:'\",.<>/?\\|`~]", password):
        errors.append("Au moins un caractère spécial requis.")

    if errors:
        raise ValidationError(
            "Le mot de passe ne satisfait pas les exigences de sécurité.",
            details={"errors": errors},
        )


def _send_reset_email(user: User, raw_token: str) -> None:
    """
    Envoie l'email contenant le lien de réinitialisation.
    Les erreurs d'envoi sont loguées mais ne propagent pas d'exception
    (évite de révéler l'existence du compte via un code d'erreur 500).
    """
    try:
        reset_url = url_for(
            "auth.reset_password_confirm",
            token=raw_token,
            _external=True,
        )
        expiry_hours = current_app.config.get("PASSWORD_RESET_EXPIRY_HOURS", 1)

        msg = Message(
            subject="Réinitialisation de votre mot de passe",
            recipients=[user.email],
            html=render_template(
                "auth/emails/password_reset.html",
                user=user,
                reset_url=reset_url,
                expiry_hours=expiry_hours,
            ),
        )
        mail.send(msg)

    except Exception as exc:
        logger.error(
            "Échec envoi email reset",
            extra={"user_id": user.id, "error": str(exc)},
            exc_info=True,
        )


def _audit(
    action: str,
    user_id: Optional[int],
    email: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> None:
    """
    Enregistre un événement dans le journal d'audit.
    Toujours non-bloquant : une erreur d'audit ne doit jamais
    interrompre une opération d'authentification.
    """
    try:
        from app.models.audit import AuditLog
        log = AuditLog(
            user_id=user_id,
            user_email=email,
            action=action,
            entity_type="users",
            entity_id=user_id,
            ip_address=ip_address,
        )
        db.session.add(log)
        db.session.flush()
    except Exception as exc:
        logger.debug("Audit non enregistré (non bloquant)", exc_info=exc)