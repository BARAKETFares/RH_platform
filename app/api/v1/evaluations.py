"""
API REST v1 — Évaluations & Objectifs
JWT obligatoire sur tous les endpoints.

Endpoints :
  GET    /api/v1/evaluations/campaigns              → liste des campagnes
  POST   /api/v1/evaluations/campaigns               → création d'une campagne
  GET    /api/v1/evaluations/campaigns/<id>           → détail d'une campagne
  POST   /api/v1/evaluations/campaigns/<id>/launch     → lance la campagne pour des paires employé/évaluateur

  GET    /api/v1/evaluations                            → liste des évaluations
  POST   /api/v1/evaluations                             → création (statut draft)
  GET    /api/v1/evaluations/<id>                          → détail (avec items)
  POST   /api/v1/evaluations/<id>/items                     → ajout d'un critère
  PUT    /api/v1/evaluations/items/<item_id>/score            → notation d'un critère
  POST   /api/v1/evaluations/<id>/send                          → draft → in_progress
  PUT    /api/v1/evaluations/<id>/submit                          → in_progress → employee_review
  PUT    /api/v1/evaluations/<id>/acknowledge                       → accusé réception employé
  POST   /api/v1/evaluations/<id>/finalize                            → employee_review → completed
  POST   /api/v1/evaluations/<id>/archive                               → completed → archived

  GET    /api/v1/evaluations/objectives                                   → mes objectifs (ou ceux d'un employé)
  POST   /api/v1/evaluations/objectives                                    → création d'un objectif
  PUT    /api/v1/evaluations/objectives/<id>/progress                       → mise à jour de l'avancement
  PUT    /api/v1/evaluations/objectives/<id>/rating                          → soumission d'une note

Permissions :
  GET (own data)         → toujours autorisé pour ses propres objectifs/évaluations
  GET (others), POST,
  campaigns.*             → evaluation.write / evaluation.campaign (admin, rh)
  PUT items/score,
  send/submit/finalize     → evaluation.write (manager pour ses subordonnés, rh, admin)

Format de réponse uniforme :
  Succès : { "data": {...} }            ou  { "data": [...], "meta": {...} }
  Erreur : { "error": { "code": N, "message": "...", "details": {...} } }
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from app.extensions import db
from app.models.evaluation import Evaluation, EvaluationCampaign
from app.models.objective import Objective
from app.schemas.evaluation_schema import (
    evaluation_campaign_create_schema,
    evaluation_campaign_schema,
    evaluation_campaigns_schema,
    evaluation_content_update_schema,
    evaluation_create_schema,
    evaluation_item_create_schema,
    evaluation_item_score_schema,
    evaluation_schema,
    evaluations_schema,
    objective_create_schema,
    objective_rating_schema,
    objective_schema,
    objectives_schema,
)
from app.services.evaluation_service import (
    acknowledge_by_employee,
    add_evaluation_item,
    archive_evaluation,
    create_campaign,
    create_evaluation,
    create_objective,
    finalize_evaluation,
    get_campaign,
    get_evaluation,
    launch_campaign_for_employees,
    list_evaluations_for_employee,
    list_objectives_for_employee,
    list_pending_employee_review,
    list_pending_for_evaluator,
    score_evaluation_item,
    send_to_evaluator,
    submit_by_evaluator,
    submit_objective_rating,
    update_objective_progress,
)
from app.utils.decorators import require_permission
from app.utils.exceptions import (
    BusinessRuleError,
    ConflictError,
    HRPlatformError,
    NotFoundError,
    ValidationError,
)

bp = Blueprint("api_evaluations", __name__)


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
    return get_jwt().get("employee_id")


def _is_privileged() -> bool:
    return _current_role() in ("admin", "rh")


# =============================================================================
# Campagnes — CRUD
# =============================================================================

@bp.get("/evaluations/campaigns")
@jwt_required()
@require_permission("evaluation.read")
def list_campaigns_route():
    """Liste des campagnes d'évaluation de l'entreprise courante."""
    claims = get_jwt()
    company_id = claims.get("company_id")
    if not company_id:
        return _err("Aucune entreprise associée à cet utilisateur.", 400)

    campaigns = db.session.execute(
        EvaluationCampaign.active_in_company(company_id)
    ).scalars().all()

    return _ok(evaluation_campaigns_schema.dump(campaigns))


@bp.post("/evaluations/campaigns")
@jwt_required()
@require_permission("evaluation.campaign")
def create_campaign_route():
    """Crée une nouvelle campagne d'évaluation."""
    body = request.get_json(silent=True)
    if body is None:
        return _err("Corps de requête JSON requis.", 400)

    errors = evaluation_campaign_create_schema.validate(body)
    if errors:
        return _err("Données invalides.", 422, {"errors": errors})

    validated = evaluation_campaign_create_schema.load(body)

    try:
        campaign = create_campaign(validated, created_by_id=_current_user_id())
    except ValidationError as exc:
        return _err(str(exc), 422, exc.details)

    return _ok(evaluation_campaign_schema.dump(campaign), status=201)


@bp.get("/evaluations/campaigns/<int:campaign_id>")
@jwt_required()
@require_permission("evaluation.read")
def get_campaign_route(campaign_id: int):
    """Détail d'une campagne d'évaluation, avec statistiques."""
    try:
        campaign = get_campaign(campaign_id)
    except NotFoundError as exc:
        return _err(str(exc), 404)

    data = evaluation_campaign_schema.dump(campaign)
    data["evaluation_count"] = campaign.evaluation_count
    data["completed_count"] = campaign.completed_count
    data["completion_rate_pct"] = campaign.completion_rate_pct

    return _ok(data)


@bp.post("/evaluations/campaigns/<int:campaign_id>/launch")
@jwt_required()
@require_permission("evaluation.campaign")
def launch_campaign_route(campaign_id: int):
    """
    Lance la campagne en créant une Evaluation pour chaque paire fournie.

    Body JSON :
        { "pairs": [ { "employee_id": 1, "evaluator_id": 2 }, ... ] }
    """
    body = request.get_json(silent=True)
    if not body or "pairs" not in body:
        return _err("Le champ 'pairs' est requis.", 400)

    try:
        pairs = [(p["employee_id"], p["evaluator_id"]) for p in body["pairs"]]
    except (KeyError, TypeError):
        return _err("Format de 'pairs' invalide. Attendu : liste de {employee_id, evaluator_id}.", 422)

    try:
        evaluations = launch_campaign_for_employees(campaign_id, pairs)
    except NotFoundError as exc:
        return _err(str(exc), 404)
    except ConflictError as exc:
        return _err(str(exc), 409)
    except BusinessRuleError as exc:
        return _err(str(exc), 422)

    return _ok(evaluations_schema.dump(evaluations), status=201)


# =============================================================================
# Évaluations — CRUD et workflow
# =============================================================================

@bp.get("/evaluations")
@jwt_required()
def list_evaluations_route():
    """
    Liste des évaluations.

    Comportement selon le rôle :
        - employee : ses propres évaluations.
        - manager  : les évaluations qu'il doit rédiger (pending_for_evaluator).
        - rh/admin : toutes les évaluations de l'entreprise (filtre employee_id optionnel).
    """
    role = _current_role()
    own_id = _current_employee_id()

    if role == "employee":
        if not own_id:
            return _err("Aucun employé associé à cet utilisateur.", 400)
        try:
            evaluations = list_evaluations_for_employee(own_id)
        except NotFoundError as exc:
            return _err(str(exc), 404)
    elif role == "manager":
        if not own_id:
            return _err("Aucun employé associé à cet utilisateur.", 400)
        evaluations = list_pending_for_evaluator(own_id)
    else:
        employee_id = request.args.get("employee_id", type=int)
        if employee_id:
            try:
                evaluations = list_evaluations_for_employee(employee_id)
            except NotFoundError as exc:
                return _err(str(exc), 404)
        else:
            return _err("Le paramètre employee_id est requis pour ce rôle.", 400)

    return _ok(evaluations_schema.dump(evaluations))


@bp.post("/evaluations")
@jwt_required()
@require_permission("evaluation.write")
def create_evaluation_route():
    """Crée une nouvelle fiche d'évaluation (statut draft)."""
    body = request.get_json(silent=True)
    if body is None:
        return _err("Corps de requête JSON requis.", 400)

    errors = evaluation_create_schema.validate(body)
    if errors:
        return _err("Données invalides.", 422, {"errors": errors})

    validated = evaluation_create_schema.load(body)

    try:
        evaluation = create_evaluation(validated)
    except NotFoundError as exc:
        return _err(str(exc), 404)
    except ConflictError as exc:
        return _err(str(exc), 409)
    except BusinessRuleError as exc:
        return _err(str(exc), 422)

    return _ok(evaluation_schema.dump(evaluation), status=201)


@bp.get("/evaluations/<int:evaluation_id>")
@jwt_required()
def get_evaluation_route(evaluation_id: int):
    """Détail d'une évaluation, avec ses critères détaillés."""
    try:
        evaluation = get_evaluation(evaluation_id)
    except NotFoundError as exc:
        return _err(str(exc), 404)

    own_id = _current_employee_id()
    if not _is_privileged() and own_id not in (evaluation.employee_id, evaluation.evaluator_id):
        return _err("Accès refusé à cette évaluation.", 403)

    return _ok(evaluation_schema.dump(evaluation, include_items=True))


@bp.post("/evaluations/<int:evaluation_id>/items")
@jwt_required()
@require_permission("evaluation.write")
def add_item_route(evaluation_id: int):
    """Ajoute un critère détaillé à une évaluation en cours de rédaction."""
    body = request.get_json(silent=True)
    if body is None:
        return _err("Corps de requête JSON requis.", 400)

    errors = evaluation_item_create_schema.validate(body)
    if errors:
        return _err("Données invalides.", 422, {"errors": errors})

    validated = evaluation_item_create_schema.load(body)

    try:
        item = add_evaluation_item(evaluation_id, validated)
    except NotFoundError as exc:
        return _err(str(exc), 404)
    except BusinessRuleError as exc:
        return _err(str(exc), 422)

    from app.schemas.evaluation_schema import evaluation_item_schema
    return _ok(evaluation_item_schema.dump(item), status=201)


@bp.put("/evaluations/items/<int:item_id>/score")
@jwt_required()
@require_permission("evaluation.write")
def score_item_route(item_id: int):
    """Renseigne la notation manager et/ou employé d'un critère."""
    body = request.get_json(silent=True)
    if body is None:
        return _err("Corps de requête JSON requis.", 400)

    errors = evaluation_item_score_schema.validate(body)
    if errors:
        return _err("Données invalides.", 422, {"errors": errors})

    validated = evaluation_item_score_schema.load(body)

    try:
        item = score_evaluation_item(item_id, validated)
    except NotFoundError as exc:
        return _err(str(exc), 404)

    from app.schemas.evaluation_schema import evaluation_item_schema
    return _ok(evaluation_item_schema.dump(item))


@bp.post("/evaluations/<int:evaluation_id>/send")
@jwt_required()
@require_permission("evaluation.write")
def send_evaluation_route(evaluation_id: int):
    """Transition : draft → in_progress."""
    try:
        evaluation = send_to_evaluator(evaluation_id)
    except NotFoundError as exc:
        return _err(str(exc), 404)
    except BusinessRuleError as exc:
        return _err(str(exc), 422)

    return _ok(evaluation_schema.dump(evaluation))


@bp.put("/evaluations/<int:evaluation_id>/submit")
@jwt_required()
@require_permission("evaluation.write")
def submit_evaluation_route(evaluation_id: int):
    """
    Transition : in_progress → employee_review.
    Enregistre le contenu rédigé par l'évaluateur (score, commentaires, PDI).
    """
    body = request.get_json(silent=True) or {}

    errors = evaluation_content_update_schema.validate(body)
    if errors:
        return _err("Données invalides.", 422, {"errors": errors})

    validated = evaluation_content_update_schema.load(body)

    try:
        evaluation = submit_by_evaluator(evaluation_id, validated)
    except NotFoundError as exc:
        return _err(str(exc), 404)
    except BusinessRuleError as exc:
        return _err(str(exc), 422)

    return _ok(evaluation_schema.dump(evaluation))


@bp.put("/evaluations/<int:evaluation_id>/acknowledge")
@jwt_required()
def acknowledge_evaluation_route(evaluation_id: int):
    """
    Accusé de réception par l'employé concerné.
    Accessible uniquement par l'employé évalué lui-même (vérifié ici,
    pas via @require_permission qui ne distingue pas "ses propres données").
    """
    try:
        evaluation = get_evaluation(evaluation_id)
    except NotFoundError as exc:
        return _err(str(exc), 404)

    own_id = _current_employee_id()
    if own_id != evaluation.employee_id:
        return _err("Seul l'employé concerné peut accuser réception de cette évaluation.", 403)

    body = request.get_json(silent=True) or {}
    comment = body.get("employee_overall_comment")
    sign = bool(body.get("sign", False))

    try:
        evaluation = acknowledge_by_employee(evaluation_id, comment, sign)
    except BusinessRuleError as exc:
        return _err(str(exc), 422)

    return _ok(evaluation_schema.dump(evaluation))


@bp.post("/evaluations/<int:evaluation_id>/finalize")
@jwt_required()
@require_permission("evaluation.write")
def finalize_evaluation_route(evaluation_id: int):
    """Transition : employee_review → completed. Calcule le score si absent."""
    body = request.get_json(silent=True) or {}
    sign = bool(body.get("sign", True))

    try:
        evaluation = finalize_evaluation(evaluation_id, sign=sign)
    except NotFoundError as exc:
        return _err(str(exc), 404)
    except BusinessRuleError as exc:
        return _err(str(exc), 422)

    return _ok(evaluation_schema.dump(evaluation))


@bp.post("/evaluations/<int:evaluation_id>/archive")
@jwt_required()
@require_permission("evaluation.write")
def archive_evaluation_route(evaluation_id: int):
    """Transition : completed → archived."""
    try:
        evaluation = archive_evaluation(evaluation_id)
    except NotFoundError as exc:
        return _err(str(exc), 404)
    except BusinessRuleError as exc:
        return _err(str(exc), 422)

    return _ok(evaluation_schema.dump(evaluation))


# =============================================================================
# Objectifs — CRUD
# =============================================================================

@bp.get("/evaluations/objectives")
@jwt_required()
def list_objectives_route():
    """
    Liste des objectifs.

    Query params :
        employee_id   (int, requis pour rh/admin/manager ; ignoré pour employee)
        campaign_id   (int, optionnel)
        active_only   (bool, optionnel)
    """
    role = _current_role()
    own_id = _current_employee_id()

    if role == "employee":
        target_id = own_id
    else:
        target_id = request.args.get("employee_id", type=int) or own_id

    if not target_id:
        return _err("Impossible de déterminer l'employé cible.", 400)

    try:
        objectives = list_objectives_for_employee(
            target_id,
            campaign_id=request.args.get("campaign_id", type=int),
            active_only=request.args.get("active_only", "false").lower() == "true",
        )
    except NotFoundError as exc:
        return _err(str(exc), 404)

    return _ok(objectives_schema.dump(objectives))


@bp.post("/evaluations/objectives")
@jwt_required()
@require_permission("evaluation.write")
def create_objective_route():
    """Crée un nouvel objectif pour un employé."""
    body = request.get_json(silent=True)
    if body is None:
        return _err("Corps de requête JSON requis.", 400)

    errors = objective_create_schema.validate(body)
    if errors:
        return _err("Données invalides.", 422, {"errors": errors})

    validated = objective_create_schema.load(body)
    set_by_id = _current_employee_id()
    if not set_by_id:
        return _err("Aucun employé associé à cet utilisateur.", 400)

    try:
        objective = create_objective(validated, set_by_id=set_by_id)
    except NotFoundError as exc:
        return _err(str(exc), 404)
    except BusinessRuleError as exc:
        return _err(str(exc), 422)

    return _ok(objective_schema.dump(objective), status=201)


@bp.put("/evaluations/objectives/<int:objective_id>/progress")
@jwt_required()
def update_progress_route(objective_id: int):
    """
    Met à jour le pourcentage d'avancement d'un objectif.
    Accessible par l'employé concerné lui-même ou par un rôle privilégié.
    """
    body = request.get_json(silent=True) or {}
    completion_pct = body.get("completion_pct")

    if completion_pct is None or not (0 <= completion_pct <= 100):
        return _err("Le champ completion_pct doit être compris entre 0 et 100.", 422)

    try:
        objective = update_objective_progress(objective_id, completion_pct)
    except NotFoundError as exc:
        return _err(str(exc), 404)
    except BusinessRuleError as exc:
        return _err(str(exc), 422)

    return _ok(objective_schema.dump(objective))


@bp.put("/evaluations/objectives/<int:objective_id>/rating")
@jwt_required()
def rate_objective_route(objective_id: int):
    """
    Soumet une note sur un objectif.

    Body JSON : { "rating": 1-5, "comment": "...", "rated_by": "manager"|"employee" }
    """
    body = request.get_json(silent=True)
    if body is None:
        return _err("Corps de requête JSON requis.", 400)

    errors = objective_rating_schema.validate(body)
    if errors:
        return _err("Données invalides.", 422, {"errors": errors})

    rated_by = body.get("rated_by", "employee" if _current_role() == "employee" else "manager")

    try:
        objective = submit_objective_rating(
            objective_id, body["rating"], body.get("comment"), rated_by=rated_by
        )
    except NotFoundError as exc:
        return _err(str(exc), 404)
    except ValidationError as exc:
        return _err(str(exc), 422)

    return _ok(objective_schema.dump(objective))


# =============================================================================
# Gestionnaire d'erreur local
# =============================================================================

@bp.errorhandler(HRPlatformError)
def handle_hr_platform_error(exc: HRPlatformError):
    return _err(exc.message, exc.http_status, exc.details or None)