"""
API REST v1 — Employés
JWT obligatoire sur tous les endpoints.

Endpoints :
  GET    /api/v1/employees           → liste paginée
  GET    /api/v1/employees/<id>      → détail
  POST   /api/v1/employees           → création
  PUT    /api/v1/employees/<id>      → mise à jour partielle
  DELETE /api/v1/employees/<id>      → suppression (logique par défaut)

Permissions :
  GET    → employees.read   (tous les rôles authentifiés en disposent ;
                              les champs sensibles sont filtrés selon le rôle)
  POST   → employees.write  (admin, rh)
  PUT    → employees.write  (admin, rh)
  DELETE → employees.delete (admin, rh)

Format de réponse uniforme :
  Succès : { "data": {...} }            ou  { "data": [...], "meta": {...} }
  Erreur : { "error": { "code": N, "message": "...", "details": {...} } }
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt

from app.schemas.employee_schema import (
    employee_create_schema,
    employee_public_schema,
    employee_schema,
    employee_update_schema,
    employees_public_schema,
    employees_schema,
)
from app.services.employee_service import (
    create_employee,
    delete_employee,
    get_employee,
    list_employees,
    update_employee,
)
from app.utils.decorators import require_permission
from app.utils.exceptions import (
    BusinessRuleError,
    ConflictError,
    HRPlatformError,
    NotFoundError,
    ValidationError,
)

bp = Blueprint("api_employees", __name__)


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


def _current_company_id() -> int | None:
    """
    Récupère le company_id de l'utilisateur courant depuis les claims JWT.
    Garantit l'isolation multi-tenant : un utilisateur ne voit que les
    employés de sa propre entreprise.
    """
    claims = get_jwt()
    return claims.get("company_id")


def _can_see_sensitive_fields() -> bool:
    """True si le rôle courant a accès aux champs sensibles (IBAN, salaire, notes)."""
    claims = get_jwt()
    return claims.get("role") in ("admin", "rh")


def _serialize_one(employee):
    schema = employee_schema if _can_see_sensitive_fields() else employee_public_schema
    return schema.dump(employee)


def _serialize_many(employees):
    schema = employees_schema if _can_see_sensitive_fields() else employees_public_schema
    return schema.dump(employees)


# =============================================================================
# GET /employees — liste paginée
# =============================================================================

@bp.get("/employees")
@jwt_required()
@require_permission("employees.read")
def list_employees_route():
    """
    Liste paginée des employés de l'entreprise courante.

    Query params :
        page            (int, défaut 1)
        per_page        (int, défaut DEFAULT_PAGE_SIZE)
        department_id   (int, optionnel)
        position_id     (int, optionnel)
        manager_id      (int, optionnel)
        status          (str, optionnel — active|on_leave|probation|terminated|suspended)
        search          (str, optionnel — recherche nom/prénom/matricule/email)

    Réponses :
        200 : { "data": [...], "meta": { "page", "per_page", "total", "pages", ... } }
        400 : company_id introuvable dans le contexte d'authentification.
        422 : valeur de `status` invalide.
    """
    company_id = _current_company_id()
    if not company_id:
        return _err("Aucune entreprise associée à cet utilisateur.", 400)

    try:
        result = list_employees(
            company_id=company_id,
            department_id=request.args.get("department_id", type=int),
            position_id=request.args.get("position_id", type=int),
            manager_id=request.args.get("manager_id", type=int),
            status=request.args.get("status"),
            search=request.args.get("search"),
            page=request.args.get("page", type=int),
            per_page=request.args.get("per_page", type=int),
        )
    except ValidationError as exc:
        return _err(str(exc), 422, exc.details)

    meta = result.to_dict()["meta"]
    return _ok(_serialize_many(result.items), meta=meta)


# =============================================================================
# GET /employees/<id> — détail
# =============================================================================

@bp.get("/employees/<int:employee_id>")
@jwt_required()
@require_permission("employees.read")
def get_employee_route(employee_id: int):
    """
    Détail d'un employé.

    Réponses :
        200 : { "data": {...} }
        404 : employé introuvable.
    """
    try:
        employee = get_employee(employee_id)
    except NotFoundError as exc:
        return _err(str(exc), 404)

    return _ok(_serialize_one(employee))


# =============================================================================
# POST /employees — création
# =============================================================================

@bp.post("/employees")
@jwt_required()
@require_permission("employees.write")
def create_employee_route():
    """
    Crée un nouvel employé.

    Body JSON : cf. EmployeeCreateSchema
        Champs requis : company_id, first_name, last_name, hire_date

    Réponses :
        201 : { "data": {...} }
        400 : corps de requête absent ou non-JSON.
        404 : department_id / position_id / site_id / manager_id référencé introuvable.
        409 : employee_number déjà utilisé.
        422 : validation du schéma échouée.
    """
    body = request.get_json(silent=True)
    if body is None:
        return _err("Corps de requête JSON requis.", 400)

    errors = employee_create_schema.validate(body)
    if errors:
        return _err("Données invalides.", 422, {"errors": errors})

    validated = employee_create_schema.load(body)
    claims = get_jwt()
    created_by_id = int(claims.get("sub")) if claims.get("sub") else None

    try:
        employee = create_employee(validated, created_by_id=created_by_id)
    except NotFoundError as exc:
        return _err(str(exc), 404)
    except ConflictError as exc:
        return _err(str(exc), 409)
    except ValidationError as exc:
        return _err(str(exc), 422, exc.details)

    return _ok(_serialize_one(employee), status=201)


# =============================================================================
# PUT /employees/<id> — mise à jour
# =============================================================================

@bp.put("/employees/<int:employee_id>")
@jwt_required()
@require_permission("employees.write")
def update_employee_route(employee_id: int):
    """
    Met à jour un employé existant (mise à jour partielle des champs fournis).

    Body JSON : cf. EmployeeUpdateSchema (tous champs optionnels)

    Réponses :
        200 : { "data": {...} }
        400 : corps de requête absent ou non-JSON.
        404 : employé ou référence (department/position/site/manager) introuvable.
        409 : employee_number déjà utilisé par un autre employé.
        422 : validation du schéma échouée, ou règle métier violée
              (ex : cycle hiérarchique sur manager_id).
    """
    body = request.get_json(silent=True)
    if body is None:
        return _err("Corps de requête JSON requis.", 400)

    errors = employee_update_schema.validate(body)
    if errors:
        return _err("Données invalides.", 422, {"errors": errors})

    validated = employee_update_schema.load(body)
    claims = get_jwt()
    updated_by_id = int(claims.get("sub")) if claims.get("sub") else None

    try:
        employee = update_employee(employee_id, validated, updated_by_id=updated_by_id)
    except NotFoundError as exc:
        return _err(str(exc), 404)
    except ConflictError as exc:
        return _err(str(exc), 409)
    except BusinessRuleError as exc:
        return _err(str(exc), 422)
    except ValidationError as exc:
        return _err(str(exc), 422, exc.details)

    return _ok(_serialize_one(employee))


# =============================================================================
# DELETE /employees/<id> — suppression
# =============================================================================

@bp.delete("/employees/<int:employee_id>")
@jwt_required()
@require_permission("employees.delete")
def delete_employee_route(employee_id: int):
    """
    Supprime un employé.

    Par défaut : suppression LOGIQUE (status → 'terminated').
    Passer hard=true en query string pour une suppression physique
    (réservée aux erreurs de saisie — refusée si l'employé encadre
    une équipe ou un département).

    Query params :
        hard                 (bool, défaut false)
        termination_date     (date ISO, défaut aujourd'hui — ignoré si hard=true)
        termination_reason   (str, optionnel — ignoré si hard=true)

    Réponses :
        200 : { "data": {...} }            — suppression logique
        204                                  — suppression physique (hard=true)
        404 : employé introuvable.
        422 : règle métier violée (déjà parti, manager d'un département,
              encadre des subordonnés, date de départ invalide).
    """
    hard = request.args.get("hard", "false").lower() == "true"

    termination_date = None
    raw_date = request.args.get("termination_date")
    if raw_date:
        from datetime import date as _date
        try:
            termination_date = _date.fromisoformat(raw_date)
        except ValueError:
            return _err("Format de termination_date invalide (attendu : YYYY-MM-DD).", 422)

    claims = get_jwt()
    deleted_by_id = int(claims.get("sub")) if claims.get("sub") else None

    try:
        result = delete_employee(
            employee_id,
            termination_date=termination_date,
            termination_reason=request.args.get("termination_reason"),
            deleted_by_id=deleted_by_id,
            hard_delete=hard,
        )
    except NotFoundError as exc:
        return _err(str(exc), 404)
    except BusinessRuleError as exc:
        return _err(str(exc), 422)

    if hard:
        return "", 204

    return _ok(_serialize_one(result))


# =============================================================================
# Gestionnaire d'erreur local — filet de sécurité pour exceptions non capturées
# =============================================================================

@bp.errorhandler(HRPlatformError)
def handle_hr_platform_error(exc: HRPlatformError):
    """Capture toute HRPlatformError non gérée explicitement dans une route."""
    return _err(exc.message, exc.http_status, exc.details or None)