"""
Décorateurs de contrôle d'accès.

Deux modes selon le contexte de la route :

  SSR (pages HTML, Flask-Login)
    @login_required          ← Flask-Login, toujours en premier
    @require_role("admin")

  API REST (JWT stateless)
    @jwt_required()          ← Flask-JWT-Extended, toujours en premier
    @require_role("admin")   ← lit les claims JWT si current_user absent

Les deux décorateurs fonctionnent dans les deux contextes :
ils détectent automatiquement si un JWT est présent dans la requête
ou si c'est une session Flask-Login qui est active.

Ordre de déclaration obligatoire :
    @bp.route(...)           1. route
    @jwt_required()          2. auth (JWT ou login_required)
    @require_role(...)       3. rôle
    @require_permission(...) 4. permission (optionnel, plus fin que le rôle)
"""
from __future__ import annotations

import functools
import logging
from typing import Callable

from flask import abort, request

logger = logging.getLogger(__name__)


# =============================================================================
# Helpers internes
# =============================================================================

def _get_current_role() -> str | None:
    """
    Retourne le nom du rôle de l'utilisateur courant.

    Stratégie de détection (par ordre de priorité) :
      1. Claims JWT  — route API appelée avec @jwt_required()
      2. Flask-Login — route SSR avec session active

    Retourne None si aucune identité n'est disponible.
    """
    # ── Tentative JWT ─────────────────────────────────────────────────────────
    try:
        from flask_jwt_extended import get_jwt, verify_jwt_in_request
        verify_jwt_in_request(optional=True)
        claims = get_jwt()
        if claims:
            return claims.get("role")
    except Exception:
        pass

    # ── Tentative Flask-Login ─────────────────────────────────────────────────
    try:
        from flask_login import current_user
        if current_user and current_user.is_authenticated:
            return current_user.role.name if current_user.role else None
    except Exception:
        pass

    return None


def _get_current_permissions() -> set[str]:
    """
    Retourne l'ensemble des codes de permission de l'utilisateur courant.

    Même stratégie de détection que _get_current_role() :
      1. Claims JWT  (champ "permissions" injecté à la création du token)
      2. Flask-Login (délégation à user.role.permission_codes)

    Retourne un ensemble vide si aucune identité n'est disponible.
    """
    # ── Tentative JWT ─────────────────────────────────────────────────────────
    try:
        from flask_jwt_extended import get_jwt, verify_jwt_in_request
        verify_jwt_in_request(optional=True)
        claims = get_jwt()
        if claims and "permissions" in claims:
            return set(claims["permissions"])
    except Exception:
        pass

    # ── Tentative Flask-Login ─────────────────────────────────────────────────
    try:
        from flask_login import current_user
        if current_user and current_user.is_authenticated and current_user.role:
            return current_user.role.permission_codes
    except Exception:
        pass

    return set()


def _is_authenticated() -> bool:
    """
    Retourne True si une identité valide est présente dans la requête,
    que ce soit via JWT ou via une session Flask-Login.
    """
    # ── JWT ───────────────────────────────────────────────────────────────────
    try:
        from flask_jwt_extended import verify_jwt_in_request
        verify_jwt_in_request(optional=True)
        from flask_jwt_extended import get_jwt_identity
        if get_jwt_identity() is not None:
            return True
    except Exception:
        pass

    # ── Flask-Login ───────────────────────────────────────────────────────────
    try:
        from flask_login import current_user
        if current_user and current_user.is_authenticated:
            return True
    except Exception:
        pass

    return False


def _log_access_denied(reason: str, required: str | list[str]) -> None:
    """Log uniforme des refus d'accès (niveau WARNING)."""
    try:
        from flask_jwt_extended import get_jwt_identity
        identity = get_jwt_identity()
    except Exception:
        try:
            from flask_login import current_user
            identity = current_user.id if current_user.is_authenticated else "anonymous"
        except Exception:
            identity = "unknown"

    logger.warning(
        "Accès refusé — %s",
        reason,
        extra={
            "identity":  identity,
            "required":  required,
            "endpoint":  request.endpoint,
            "method":    request.method,
            "path":      request.path,
        },
    )


# =============================================================================
# require_role
# =============================================================================

def require_role(*roles: str) -> Callable:
    """
    Vérifie que l'utilisateur courant possède au moins un des rôles spécifiés.

    Compatible JWT et Flask-Login.
    Doit être placé APRÈS @jwt_required() ou @login_required.

    Args:
        *roles: Un ou plusieurs noms de rôle acceptés.
                Ex : "admin", "rh", "manager", "employee"

    Comportement :
        - 401 si aucune identité n'est détectée.
        - 403 si le rôle de l'utilisateur n'est pas dans la liste.
        - Passe la main à la vue si le rôle est autorisé.

    Usage :
        # API — un seul rôle autorisé
        @bp.post("/employees")
        @jwt_required()
        @require_role("admin", "rh")
        def create_employee(): ...

        # SSR — plusieurs rôles autorisés
        @bp.get("/leave/approve")
        @login_required
        @require_role("admin", "rh", "manager")
        def approve_leave(): ...
    """
    if not roles:
        raise ValueError("require_role() attend au moins un nom de rôle.")

    def decorator(f: Callable) -> Callable:
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            if not _is_authenticated():
                _log_access_denied("non authentifié", list(roles))
                abort(401)

            current_role = _get_current_role()

            if current_role not in roles:
                _log_access_denied(
                    f"rôle '{current_role}' non autorisé",
                    list(roles),
                )
                abort(403)

            return f(*args, **kwargs)

        return wrapped

    return decorator


# =============================================================================
# require_permission
# =============================================================================

def require_permission(*permissions: str, match: str = "any") -> Callable:
    """
    Vérifie que l'utilisateur courant possède les permissions spécifiées.

    Compatible JWT (lit le champ "permissions" des claims)
    et Flask-Login (délègue à user.role.permission_codes).

    Doit être placé APRÈS @jwt_required() ou @login_required,
    et après @require_role() si les deux sont combinés.

    Args:
        *permissions: Un ou plusieurs codes de permission.
                      Format : "<module>.<action>"
                      Ex : "leave.approve", "payroll.read", "employees.write"

        match:        Stratégie de correspondance :
                        "any" (défaut) — l'utilisateur doit posséder
                                         AU MOINS UNE des permissions listées.
                        "all"          — l'utilisateur doit posséder
                                         TOUTES les permissions listées.

    Comportement :
        - 401 si aucune identité n'est détectée.
        - 403 si la condition `match` n'est pas satisfaite.

    Raises:
        ValueError: si aucune permission n'est fournie ou si match est invalide.

    Usage :
        # Au moins une permission parmi celles listées (match="any", défaut)
        @bp.get("/payslips")
        @jwt_required()
        @require_permission("payroll.read", "payroll.write")
        def list_payslips(): ...

        # Toutes les permissions requises (match="all")
        @bp.post("/payroll/run")
        @jwt_required()
        @require_permission("payroll.write", "payroll.export", match="all")
        def run_payroll(): ...

        # Combiné avec require_role (rôle vérifié en premier)
        @bp.delete("/employees/<int:employee_id>")
        @jwt_required()
        @require_role("admin", "rh")
        @require_permission("employees.delete")
        def delete_employee(employee_id: int): ...
    """
    if not permissions:
        raise ValueError("require_permission() attend au moins un code de permission.")

    if match not in ("any", "all"):
        raise ValueError(f"Paramètre match invalide : '{match}'. Valeurs acceptées : 'any', 'all'.")

    def decorator(f: Callable) -> Callable:
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            if not _is_authenticated():
                _log_access_denied("non authentifié", list(permissions))
                abort(401)

            user_permissions = _get_current_permissions()

            if match == "any":
                granted = any(p in user_permissions for p in permissions)
            else:
                granted = all(p in user_permissions for p in permissions)

            if not granted:
                missing = [p for p in permissions if p not in user_permissions]
                _log_access_denied(
                    f"permission(s) manquante(s) [{match}] : {missing}",
                    list(permissions),
                )
                abort(403)

            return f(*args, **kwargs)

        return wrapped

    return decorator