"""
API REST v1 — Congés & Absences
JWT obligatoire sur tous les endpoints.

Endpoints :
  GET    /api/v1/leaves                      → liste paginée des demandes
  GET    /api/v1/leaves/<id>                  → détail d'une demande
  POST   /api/v1/leaves                       → soumission d'une nouvelle demande
  PUT    /api/v1/leaves/<id>                  → modification (statuts non terminaux)
  DELETE /api/v1/leaves/<id>                  → annulation d'une demande
  POST   /api/v1/leaves/<id>/approve          → approbation (manager ou RH)
  POST   /api/v1/leaves/<id>/reject           → refus (manager ou RH)
  GET    /api/v1/leaves/balances              → soldes de l'employé courant
  GET    /api/v1/leaves/balances/<employee_id> → soldes d'un employé donné

Permissions :
  GET (own data)      → toujours autorisé pour ses propres demandes/soldes
  GET (others)        → leave.read   (admin, rh, manager)
  POST                 → leave.write  (tous les rôles peuvent soumettre une demande)
  PUT / DELETE (own)    → leave.write  (sur ses propres demandes non terminales)
  POST .../approve|reject → leave.approve (manager, rh, admin)

Format de réponse uniforme :
  Succès : { "data": {...} }            ou  { "data": [...], "meta": {...} }
  Erreur : { "error": { "code": N, "message": "...", "details": {...} } }
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from app.extensions import db
from app.models.leave_request import LeaveRequest
from app.schemas.leave_schema import (
    leave_balances_schema,
    leave_request_cancel_schema,
    leave_request_create_schema,
    leave_request_decision_schema,
    leave_request_schema,
    leave_request_update_schema,
    leave_requests_schema,
)
from app.services.leave_service import (
    approve_leave,
    calculate_all_balances,
    create_leave_request,
    reject_leave,
)
from app.utils.decorators import require_permission
from app.utils.exceptions import (
    BusinessRuleError,
    ConflictError,
    HRPlatformError,
    NotFoundError,
    ValidationError,
)
from app.utils.pagination import paginate

bp = Blueprint("api_leaves", __name__)


# =============================================================================
# Helpers
# =============================================================================

def _ok(data, status: int = 200, meta: dict | None = None):
    payload: dict = {"data": data}
    if meta:
        payload["meta"] = meta
    return jsonify(payload), status


def _err(message: str, code: int, details: dict | None = None):
    payload: dict = {"error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = details
    return jsonify(payload), code


def _current_user_id() -> int:
    return int(get_jwt_identity())


def _current_role() -> str:
    return get_jwt().get("role", "")


def _current_employee_id() -> int | None:
    """Récupère l'employee_id de l'utilisateur courant depuis les claims JWT."""
    return get_jwt().get("employee_id")


def _is_privileged() -> bool:
    """True si le rôle courant peut voir/agir sur les demandes d'autrui."""
    return _current_role() in ("admin", "rh", "manager")


def _ensure_can_view(leave_request: LeaveRequest) -> bool:
    """Vérifie que l'utilisateur courant peut consulter cette demande."""
    if _is_privileged():
        return True
    return leave_request.employee_id == _current_employee_id()


def _ensure_can_modify(leave_request: LeaveRequest) -> bool:
    """Vérifie que l'utilisateur courant peut modifier/annuler cette demande."""
    if _current_role() in ("admin", "rh"):
        return True
    return leave_request.employee_id == _current_employee_id()


# =============================================================================
# GET /leaves — liste paginée
# =============================================================================

@bp.get("/leaves")
@jwt_required()
def list_leaves_route():
    """
    Liste paginée des demandes d'absence.

    Comportement selon le rôle :
        - employee : voit uniquement ses propres demandes (employee_id forcé).
        - manager/rh/admin : voit toutes les demandes, filtrables.

    Query params :
        page, per_page    (pagination)
        employee_id         (int, ignoré si rôle = employee)
        status               (str, optionnel)
        manager_id            (int, optionnel — filtre "mon équipe")

    Réponses :
        200 : { "data": [...], "meta": {...} }
        422 : valeur de `status` invalide.
    """
    employee_id = request.args.get("employee_id", type=int)
    status = request.args.get("status")
    manager_id = request.args.get("manager_id", type=int)

    if status is not None and status not in LeaveRequest.STATUSES:
        return _err(f"Statut de filtre invalide : '{status}'.", 422)

    query = db.select(LeaveRequest)

    if not _is_privileged():
        # Un employé standard ne voit que ses propres demandes
        own_id = _current_employee_id()
        if not own_id:
            return _err("Aucun employé associé à cet utilisateur.", 400)
        query = query.where(LeaveRequest.employee_id == own_id)
    else:
        if employee_id is not None:
            query = query.where(LeaveRequest.employee_id == employee_id)
        if manager_id is not None:
            query = query.where(LeaveRequest.manager_id == manager_id)

    if status is not None:
        query = query.where(LeaveRequest.status == status)

    query = query.order_by(LeaveRequest.created_at.desc())

    result = paginate(query, page=request.args.get("page", type=int),
                       per_page=request.args.get("per_page", type=int))

    return _ok(leave_requests_schema.dump(result.items), meta=result.to_dict()["meta"])


# =============================================================================
# GET /leaves/<id> — détail
# =============================================================================

@bp.get("/leaves/<int:leave_id>")
@jwt_required()
def get_leave_route(leave_id: int):
    """
    Détail d'une demande d'absence.

    Réponses :
        200 : { "data": {...} }
        403 : tentative de consultation d'une demande appartenant à un autre employé
              sans permission elevée.
        404 : demande introuvable.
    """
    leave_request = db.session.get(LeaveRequest, leave_id)
    if leave_request is None:
        return _err("Demande d'absence introuvable.", 404)

    if not _ensure_can_view(leave_request):
        return _err("Accès refusé à cette demande.", 403)

    return _ok(leave_request_schema.dump(leave_request))


# =============================================================================
# POST /leaves — soumission
# =============================================================================

@bp.post("/leaves")
@jwt_required()
@require_permission("leave.write")
def create_leave_route():
    """
    Soumet une nouvelle demande d'absence.

    Body JSON : cf. LeaveRequestCreateSchema
        Champs requis : employee_id, leave_type_id, start_date, end_date

    Un employé standard ne peut soumettre une demande que pour lui-même —
    employee_id est forcé à son propre id si le rôle n'est pas privilégié.

    Réponses :
        201 : { "data": {...} }
        400 : corps de requête absent ou non-JSON.
        403 : tentative de création pour un autre employé sans permission élevée.
        404 : employee_id ou leave_type_id introuvable.
        409 : chevauchement avec une demande active existante.
        422 : validation du schéma échouée, ou règle métier violée
              (durée max, délai de prévenance, justificatif manquant).
    """
    body = request.get_json(silent=True)
    if body is None:
        return _err("Corps de requête JSON requis.", 400)

    errors = leave_request_create_schema.validate(body)
    if errors:
        return _err("Données invalides.", 422, {"errors": errors})

    validated = leave_request_create_schema.load(body)

    if not _is_privileged():
        own_id = _current_employee_id()
        if not own_id:
            return _err("Aucun employé associé à cet utilisateur.", 400)
        if validated["employee_id"] != own_id:
            return _err("Vous ne pouvez soumettre une demande que pour vous-même.", 403)

    try:
        leave_request = create_leave_request(validated, created_by_id=_current_user_id())
    except NotFoundError as exc:
        return _err(str(exc), 404)
    except ConflictError as exc:
        return _err(str(exc), 409)
    except BusinessRuleError as exc:
        return _err(str(exc), 422)
    except ValidationError as exc:
        return _err(str(exc), 422, exc.details)

    return _ok(leave_request_schema.dump(leave_request), status=201)


# =============================================================================
# PUT /leaves/<id> — modification
# =============================================================================

@bp.put("/leaves/<int:leave_id>")
@jwt_required()
@require_permission("leave.write")
def update_leave_route(leave_id: int):
    """
    Modifie une demande d'absence non encore traitée (draft ou pending_manager).

    Body JSON : cf. LeaveRequestUpdateSchema (tous champs optionnels)

    Réponses :
        200 : { "data": {...} }
        400 : corps de requête absent ou non-JSON.
        403 : tentative de modification de la demande d'un autre employé.
        404 : demande introuvable.
        422 : demande déjà traitée (statut non modifiable), ou validation échouée.
    """
    leave_request = db.session.get(LeaveRequest, leave_id)
    if leave_request is None:
        return _err("Demande d'absence introuvable.", 404)

    if not _ensure_can_modify(leave_request):
        return _err("Vous ne pouvez modifier que vos propres demandes.", 403)

    if leave_request.status not in (LeaveRequest.STATUS_DRAFT, LeaveRequest.STATUS_PENDING_MANAGER):
        return _err(
            f"Cette demande ne peut plus être modifiée (statut : '{leave_request.status}').",
            422,
        )

    body = request.get_json(silent=True)
    if body is None:
        return _err("Corps de requête JSON requis.", 400)

    errors = leave_request_update_schema.validate(body)
    if errors:
        return _err("Données invalides.", 422, {"errors": errors})

    validated = leave_request_update_schema.load(body)

    updatable_fields = (
        "leave_type_id", "start_date", "end_date",
        "start_half_day", "end_half_day",
        "employee_comment", "document_path", "is_emergency",
    )
    for field in updatable_fields:
        if field in validated:
            setattr(leave_request, field, validated[field])

    db.session.commit()

    return _ok(leave_request_schema.dump(leave_request))


# =============================================================================
# DELETE /leaves/<id> — annulation
# =============================================================================

@bp.delete("/leaves/<int:leave_id>")
@jwt_required()
@require_permission("leave.write")
def cancel_leave_route(leave_id: int):
    """
    Annule une demande d'absence (statut → 'cancelled').
    Libère automatiquement le solde réservé ou consommé.

    Body JSON (optionnel) : { "reason": "..." }

    Réponses :
        200 : { "data": {...} }
        403 : tentative d'annulation de la demande d'un autre employé.
        404 : demande introuvable.
        422 : la demande n'est plus annulable (déjà refusée ou déjà annulée).
    """
    leave_request = db.session.get(LeaveRequest, leave_id)
    if leave_request is None:
        return _err("Demande d'absence introuvable.", 404)

    if not _ensure_can_modify(leave_request):
        return _err("Vous ne pouvez annuler que vos propres demandes.", 403)

    body = request.get_json(silent=True) or {}
    errors = leave_request_cancel_schema.validate(body)
    if errors:
        return _err("Données invalides.", 422, {"errors": errors})

    was_approved = leave_request.status == LeaveRequest.STATUS_APPROVED
    was_pending_balance = leave_request.leave_type.impacts_leave_balance if leave_request.leave_type else False

    try:
        leave_request.cancel(reason=body.get("reason"))
    except ValueError as exc:
        return _err(str(exc), 422)

    # Libère le solde, qu'il ait été réservé (pending) ou déjà consommé (taken)
    if was_pending_balance and leave_request.working_days is not None:
        from app.models.leave_balance import LeaveBalance
        balance = LeaveBalance.get_for_employee(
            leave_request.employee_id, leave_request.leave_type_id, leave_request.start_date.year
        )
        if balance is not None:
            if was_approved:
                balance.restore(float(leave_request.working_days))
            else:
                balance.release_reservation(float(leave_request.working_days))

    db.session.commit()

    return _ok(leave_request_schema.dump(leave_request))


# =============================================================================
# POST /leaves/<id>/approve — approbation
# =============================================================================

@bp.post("/leaves/<int:leave_id>/approve")
@jwt_required()
@require_permission("leave.approve")
def approve_leave_route(leave_id: int):
    """
    Approuve une demande d'absence au niveau manager ou RH selon le rôle courant.

    Body JSON (optionnel) :
        { "comment": "...", "requires_hr_validation": true }

    Le rôle courant détermine l'approver_role :
        manager → approbation niveau 1 (passe en pending_hr si requires_hr_validation)
        rh, admin → approbation niveau 2 (statut final 'approved')

    Réponses :
        200 : { "data": {...} }
        404 : demande introuvable.
        422 : transition impossible depuis le statut actuel.
    """
    body = request.get_json(silent=True) or {}
    role = _current_role()
    approver_role = "manager" if role == "manager" else "hr"
    approver_id = _current_employee_id() if approver_role == "manager" else _current_user_id()

    if approver_id is None:
        return _err("Impossible de déterminer l'identité de l'approbateur.", 400)

    try:
        leave_request = approve_leave(
            leave_id,
            approver_id,
            approver_role=approver_role,
            comment=body.get("comment"),
            requires_hr_validation=body.get("requires_hr_validation", True),
        )
    except NotFoundError as exc:
        return _err(str(exc), 404)
    except (BusinessRuleError, ValidationError) as exc:
        return _err(str(exc), 422)

    return _ok(leave_request_schema.dump(leave_request))


# =============================================================================
# POST /leaves/<id>/reject — refus
# =============================================================================

@bp.post("/leaves/<int:leave_id>/reject")
@jwt_required()
@require_permission("leave.approve")
def reject_leave_route(leave_id: int):
    """
    Refuse une demande d'absence au niveau manager ou RH selon le rôle courant.

    Body JSON : { "comment": "..." }   — le commentaire est obligatoire.

    Réponses :
        200 : { "data": {...} }
        400 : corps de requête absent ou non-JSON.
        404 : demande introuvable.
        422 : motif manquant, ou transition impossible depuis le statut actuel.
    """
    body = request.get_json(silent=True)
    if body is None:
        return _err("Corps de requête JSON requis.", 400)

    errors = leave_request_decision_schema.validate({"decision": "reject", **body})
    if errors:
        return _err("Données invalides.", 422, {"errors": errors})

    role = _current_role()
    approver_role = "manager" if role == "manager" else "hr"
    approver_id = _current_employee_id() if approver_role == "manager" else _current_user_id()

    if approver_id is None:
        return _err("Impossible de déterminer l'identité de l'approbateur.", 400)

    try:
        leave_request = reject_leave(
            leave_id,
            approver_id,
            approver_role=approver_role,
            comment=body.get("comment", ""),
        )
    except NotFoundError as exc:
        return _err(str(exc), 404)
    except (BusinessRuleError, ValidationError) as exc:
        return _err(str(exc), 422)

    return _ok(leave_request_schema.dump(leave_request))


# =============================================================================
# GET /leaves/balances — soldes de l'employé courant
# =============================================================================

@bp.get("/leaves/balances")
@jwt_required()
def my_balances_route():
    """
    Retourne les soldes de congés de l'employé courant pour une année donnée.

    Query params :
        year   (int, défaut année courante)

    Réponses :
        200 : { "data": [...] }
        400 : aucun employé associé à l'utilisateur courant.
    """
    own_id = _current_employee_id()
    if not own_id:
        return _err("Aucun employé associé à cet utilisateur.", 400)

    from datetime import date as _date
    year = request.args.get("year", default=_date.today().year, type=int)

    try:
        balances = calculate_all_balances(own_id, year)
    except NotFoundError as exc:
        return _err(str(exc), 404)

    return _ok(leave_balances_schema.dump(balances))


# =============================================================================
# GET /leaves/balances/<employee_id> — soldes d'un employé donné
# =============================================================================

@bp.get("/leaves/balances/<int:employee_id>")
@jwt_required()
@require_permission("leave.read")
def employee_balances_route(employee_id: int):
    """
    Retourne les soldes de congés d'un employé donné (accès RH/Manager/Admin).

    Query params :
        year   (int, défaut année courante)

    Réponses :
        200 : { "data": [...] }
        404 : employé introuvable.
    """
    from datetime import date as _date
    year = request.args.get("year", default=_date.today().year, type=int)

    try:
        balances = calculate_all_balances(employee_id, year)
    except NotFoundError as exc:
        return _err(str(exc), 404)

    return _ok(leave_balances_schema.dump(balances))


# =============================================================================
# Gestionnaire d'erreur local — filet de sécurité pour exceptions non capturées
# =============================================================================

@bp.errorhandler(HRPlatformError)
def handle_hr_platform_error(exc: HRPlatformError):
    """Capture toute HRPlatformError non gérée explicitement dans une route."""
    return _err(exc.message, exc.http_status, exc.details or None)