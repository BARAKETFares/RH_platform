"""
Routes SSR du module Auth.

Toutes les routes retournent du HTML via Jinja2 ou des redirections.
Les routes JSON/JWT sont dans app/api/v1/auth.py.

Flux de connexion :
    GET  /auth/login
    POST /auth/login  ──► (2FA ?)──► GET /auth/2fa
                      └──► (direct)──► redirect dashboard

Flux reset password :
    GET  /auth/forgot-password
    POST /auth/forgot-password  ──► email envoyé
    GET  /auth/reset-password/<token>
    POST /auth/reset-password/<token> ──► redirect login

Flux 2FA :
    GET  /auth/2fa
    POST /auth/2fa ──► redirect dashboard

Flux changement mot de passe :
    GET  /auth/password/change
    POST /auth/password/change ──► redirect dashboard
"""
from __future__ import annotations

import logging

from flask import (
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import (
    current_user,
    login_required,
    login_user,
    logout_user as _flask_logout,
)

from app.extensions import limiter
from app.models.user import PasswordResetToken, User
from app.services.auth_service import (
    authenticate,
    authenticate_2fa,
    change_password,
    confirm_password_reset,
    logout,
    request_password_reset,
)
from app.utils.decorators import require_permission, require_role
from app.utils.exceptions import AuthenticationError, BusinessRuleError, ValidationError
from . import bp
from .forms import (
    ChangePasswordForm,
    DisableTwoFactorForm,
    LoginForm,
    PasswordResetConfirmForm,
    PasswordResetRequestForm,
    TwoFactorForm,
    TwoFactorSetupConfirmForm,
)

logger = logging.getLogger(__name__)

# Clés de session temporaire utilisées pendant les flux multi-étapes
_SESSION_2FA_USER_ID  = "_auth_2fa_user_id"
_SESSION_2FA_REMEMBER = "_auth_2fa_remember"


# =============================================================================
# Helpers
# =============================================================================

def _safe_next() -> str:
    """
    Retourne l'URL cible après connexion.
    Accepte uniquement les redirections relatives (prévention open redirect).

    TEMPORAIRE : redirige vers /leaves/ en attendant que le dashboard
    (reporting.dashboard) soit implémenté — cf. roadmap Bloc E.
    """
    next_url = request.args.get("next", "")
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return url_for("reporting.dashboard")


def _redirect_if_authenticated():
    """Redirige un utilisateur déjà connecté vers le dashboard."""
    if current_user.is_authenticated:
        return redirect(_safe_next())
    return None


# =============================================================================
# Login
# =============================================================================

@bp.get("/login")
def login_get():
    """Affiche la page de connexion."""
    redir = _redirect_if_authenticated()
    if redir:
        return redir
    return render_template("auth/login.html", form=LoginForm())


@bp.post("/login")
@limiter.limit("20 per minute; 5 per second")
def login_post():
    """
    Traite la soumission du formulaire de connexion.

    Cas possibles après authenticate() :
      - requires_2fa              → session temporaire + redirect /auth/2fa
      - requires_password_change  → redirect /auth/password/change
      - succès direct             → login_user() + redirect dashboard
    """
    redir = _redirect_if_authenticated()
    if redir:
        return redir

    form = LoginForm()
    if not form.validate_on_submit():
        return render_template("auth/login.html", form=form), 422

    try:
        result = authenticate(
            email=form.email.data,
            password=form.password.data,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string,
        )
    except AuthenticationError as exc:
        flash(str(exc), "error")
        return render_template("auth/login.html", form=form), 401

    # ── 2FA requis ────────────────────────────────────────────────────────────
    if result.get("requires_2fa"):
        session[_SESSION_2FA_USER_ID]  = result["user_id"]
        session[_SESSION_2FA_REMEMBER] = form.remember_me.data
        return redirect(url_for("auth.two_factor_get"))

    # ── Changement de mot de passe forcé ──────────────────────────────────────
    if result.get("requires_password_change"):
        user = db_get_user(result["user_id"])
        if user:
            login_user(user, remember=False)
        flash("Vous devez changer votre mot de passe avant de continuer.", "warning")
        return redirect(url_for("auth.change_password_get"))

    # ── Connexion directe ─────────────────────────────────────────────────────
    user = db_get_user(result["user"]["id"])
    if not user:
        flash("Une erreur inattendue s'est produite.", "error")
        return render_template("auth/login.html", form=form), 500

    login_user(user, remember=form.remember_me.data)
    flash(f"Bienvenue, {user.email} !", "success")
    return redirect(_safe_next())


def db_get_user(user_id: int) -> User | None:
    from app.extensions import db
    return db.session.get(User, user_id)


# =============================================================================
# 2FA
# =============================================================================

@bp.get("/2fa")
def two_factor_get():
    """Affiche le formulaire de saisie du code TOTP."""
    if not session.get(_SESSION_2FA_USER_ID):
        return redirect(url_for("auth.login_get"))
    return render_template("auth/2fa.html", form=TwoFactorForm())


@bp.post("/2fa")
@limiter.limit("10 per minute")
def two_factor_post():
    """
    Vérifie le code TOTP et finalise la connexion.
    Nettoie les clés de session temporaires après usage.
    """
    user_id = session.get(_SESSION_2FA_USER_ID)
    if not user_id:
        return redirect(url_for("auth.login_get"))

    form = TwoFactorForm()
    if not form.validate_on_submit():
        return render_template("auth/2fa.html", form=form), 422

    try:
        result = authenticate_2fa(
            user_id=user_id,
            totp_code=form.code.data,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string,
        )
    except AuthenticationError as exc:
        flash(str(exc), "error")
        return render_template("auth/2fa.html", form=form), 401

    remember = session.pop(_SESSION_2FA_REMEMBER, False)
    session.pop(_SESSION_2FA_USER_ID, None)

    user = db_get_user(result["user"]["id"])
    if not user:
        flash("Une erreur inattendue s'est produite.", "error")
        return redirect(url_for("auth.login_get"))

    login_user(user, remember=remember)
    return redirect(_safe_next())


# =============================================================================
# Logout
# =============================================================================

@bp.get("/logout")
@login_required
def logout_get():
    """
    Déconnecte l'utilisateur :
      1. Révoque la session en base.
      2. Efface la session Flask-Login.
      3. Redirige vers la page de connexion.
    """
    user_id = current_user.id
    _flask_logout()
    logout(user_id)
    flash("Vous avez été déconnecté.", "info")
    return redirect(url_for("auth.login_get"))


# =============================================================================
# Forgot password
# =============================================================================

@bp.get("/forgot-password")
def forgot_password_get():
    """Affiche le formulaire de demande de réinitialisation."""
    redir = _redirect_if_authenticated()
    if redir:
        return redir
    return render_template("auth/forgot_password.html", form=PasswordResetRequestForm())


@bp.post("/forgot-password")
@limiter.limit("5 per hour")
def forgot_password_post():
    """
    Traite la demande de reset.
    Répond toujours avec un message générique (timing-safe).
    """
    redir = _redirect_if_authenticated()
    if redir:
        return redir

    form = PasswordResetRequestForm()
    if not form.validate_on_submit():
        return render_template("auth/forgot_password.html", form=form), 422

    request_password_reset(form.email.data)

    flash(
        "Si un compte est associé à cette adresse, "
        "vous recevrez un email contenant un lien valide 1 heure.",
        "info",
    )
    return redirect(url_for("auth.login_get"))


# =============================================================================
# Reset password
# =============================================================================

@bp.get("/reset-password/<token>")
def reset_password_get(token: str):
    """
    Affiche le formulaire de saisie du nouveau mot de passe.
    Vérifie la validité du token avant d'afficher le formulaire.
    """
    redir = _redirect_if_authenticated()
    if redir:
        return redir

    if not PasswordResetToken.find_valid(token):
        flash(
            "Ce lien est invalide ou a expiré. Veuillez faire une nouvelle demande.",
            "error",
        )
        return redirect(url_for("auth.forgot_password_get"))

    return render_template(
        "auth/reset_password.html",
        form=PasswordResetConfirmForm(),
        token=token,
    )


@bp.post("/reset-password/<token>")
@limiter.limit("10 per hour")
def reset_password_post(token: str):
    """
    Applique le nouveau mot de passe.
    Redirige vers le login en cas de succès.
    """
    redir = _redirect_if_authenticated()
    if redir:
        return redir

    form = PasswordResetConfirmForm()
    if not form.validate_on_submit():
        return render_template("auth/reset_password.html", form=form, token=token), 422

    try:
        confirm_password_reset(token, form.password.data)
    except ValidationError as exc:
        flash(str(exc), "error")
        return render_template("auth/reset_password.html", form=form, token=token), 422

    flash("Mot de passe mis à jour. Vous pouvez maintenant vous connecter.", "success")
    return redirect(url_for("auth.login_get"))


# =============================================================================
# Change password (utilisateur connecté)
# =============================================================================

@bp.get("/password/change")
@login_required
def change_password_get():
    """Affiche le formulaire de changement de mot de passe."""
    return render_template("auth/change_password.html", form=ChangePasswordForm())


@bp.post("/password/change")
@login_required
def change_password_post():
    """
    Applique le changement de mot de passe.
    Déconnecte l'utilisateur après le changement (sessions révoquées en base).
    """
    form = ChangePasswordForm()
    if not form.validate_on_submit():
        return render_template("auth/change_password.html", form=form), 422

    try:
        change_password(
            user_id=current_user.id,
            current_password=form.current_password.data,
            new_password=form.new_password.data,
        )
    except AuthenticationError as exc:
        flash(str(exc), "error")
        return render_template("auth/change_password.html", form=form), 401
    except (ValidationError, BusinessRuleError) as exc:
        flash(str(exc), "error")
        return render_template("auth/change_password.html", form=form), 422

    _flask_logout()
    flash("Mot de passe modifié. Veuillez vous reconnecter.", "success")
    return redirect(url_for("auth.login_get"))


# =============================================================================
# 2FA Setup (activation)
# =============================================================================

@bp.get("/2fa/setup")
@login_required
def setup_2fa_get():
    """Génère un secret TOTP et affiche le QR code."""
    if current_user.totp_enabled:
        flash("Le 2FA est déjà activé sur votre compte.", "info")
        return redirect(url_for("auth.profile_get"))

    from app.services.auth_service import setup_2fa
    totp_data = setup_2fa(current_user.id)
    session["_totp_uri"]    = totp_data["otpauth_uri"]
    session["_totp_secret"] = totp_data["secret"]

    return render_template(
        "auth/setup_2fa.html",
        form=TwoFactorSetupConfirmForm(),
        otpauth_uri=totp_data["otpauth_uri"],
        secret=totp_data["secret"],
    )


@bp.post("/2fa/setup")
@login_required
@limiter.limit("10 per minute")
def setup_2fa_post():
    """Confirme l'activation du 2FA avec le premier code valide."""
    if current_user.totp_enabled:
        return redirect(url_for("auth.profile_get"))

    form = TwoFactorSetupConfirmForm()
    if not form.validate_on_submit():
        return render_template(
            "auth/setup_2fa.html",
            form=form,
            otpauth_uri=session.get("_totp_uri", ""),
            secret=session.get("_totp_secret", ""),
        ), 422

    from app.services.auth_service import confirm_2fa_setup
    if not confirm_2fa_setup(current_user.id, form.code.data):
        flash("Code invalide. Vérifiez votre application d'authentification.", "error")
        return render_template(
            "auth/setup_2fa.html",
            form=form,
            otpauth_uri=session.get("_totp_uri", ""),
            secret=session.get("_totp_secret", ""),
        ), 422

    session.pop("_totp_uri", None)
    session.pop("_totp_secret", None)
    flash("Authentification à deux facteurs activée.", "success")
    return redirect(url_for("auth.profile_get"))


# =============================================================================
# 2FA Disable (désactivation)
# =============================================================================

@bp.get("/2fa/disable")
@login_required
def disable_2fa_get():
    """Affiche la confirmation de désactivation du 2FA."""
    if not current_user.totp_enabled:
        flash("Le 2FA n'est pas activé sur votre compte.", "info")
        return redirect(url_for("auth.profile_get"))
    return render_template("auth/disable_2fa.html", form=DisableTwoFactorForm())


@bp.post("/2fa/disable")
@login_required
def disable_2fa_post():
    """Désactive le 2FA après vérification du mot de passe."""
    form = DisableTwoFactorForm()
    if not form.validate_on_submit():
        return render_template("auth/disable_2fa.html", form=form), 422

    from app.services.auth_service import disable_2fa
    try:
        disable_2fa(current_user.id, form.password.data)
    except AuthenticationError as exc:
        flash(str(exc), "error")
        return render_template("auth/disable_2fa.html", form=form), 401

    flash("Authentification à deux facteurs désactivée.", "success")
    return redirect(url_for("auth.profile_get"))


# =============================================================================
# Profil
# =============================================================================

@bp.get("/profile")
@login_required
def profile_get():
    """Page de profil de l'utilisateur connecté."""
    pending_leaves = None
    leave_balances = []

    if current_user.employee and current_user.role.name in ("employee", "manager"):
        from datetime import date

        from app.extensions import db
        from app.models.leave_request import LeaveRequest
        from app.services.leave_service import calculate_all_balances
        from app.utils.exceptions import NotFoundError

        employee_id = current_user.employee.id
        pending_leaves = db.session.execute(
            db.select(db.func.count(LeaveRequest.id)).where(
                LeaveRequest.employee_id == employee_id,
                LeaveRequest.status.in_(LeaveRequest.PENDING_STATUSES),
            )
        ).scalar_one()
        try:
            leave_balances = calculate_all_balances(employee_id, date.today().year)
        except NotFoundError:
            leave_balances = []

    return render_template(
        "auth/profile.html",
        user=current_user,
        pending_leaves=pending_leaves,
        leave_balances=leave_balances,
    )


# =============================================================================
# Health check
# =============================================================================

@bp.get("/health")
def health():
    """Endpoint de santé (sans authentification). Utilisé par Docker / LB."""
    return {"status": "ok"}, 200