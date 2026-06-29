"""
Routes SSR du module Performance (Évaluations & Objectifs).

Pages couvertes :
    GET  /performance/                          → mes objectifs + mes évaluations
    GET  /performance/objectives/new              → formulaire nouvel objectif (manager)
    POST /performance/objectives/new                → traitement création
    PUT  /performance/objectives/<id>/progress         → mise à jour avancement (AJAX-friendly)
    POST /performance/objectives/<id>/rating              → soumission d'une note

    GET  /performance/campaigns                              → liste des campagnes (admin/rh)
    GET  /performance/campaigns/new                            → formulaire nouvelle campagne
    POST /performance/campaigns/new                              → traitement création
    GET  /performance/campaigns/<id>                               → détail + lancement

    GET  /performance/evaluations/<id>                              → détail d'une évaluation
    POST /performance/evaluations/<id>/send                            → manager : envoi (draft→in_progress)
    POST /performance/evaluations/<id>/submit                            → manager : soumission contenu
    POST /performance/evaluations/<id>/acknowledge                         → employé : accusé réception
    POST /performance/evaluations/<id>/finalize                              → manager : finalisation

Toutes les routes nécessitent une session authentifiée. La logique
métier est entièrement déléguée à evaluation_service.
"""
from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.evaluation import Evaluation, EvaluationCampaign
from app.models.objective import Objective
from app.services.evaluation_service import (
    acknowledge_by_employee,
    archive_evaluation,
    create_campaign,
    create_evaluation,
    create_objective,
    finalize_evaluation,
    get_campaign,
    get_evaluation,
    list_all_campaigns_overview,
    list_evaluations_for_employee,
    list_objectives_for_employee,
    list_objectives_set_by,
    list_pending_employee_review,
    list_pending_for_evaluator,
    list_submitted_awaiting_employee,
    send_to_evaluator,
    submit_by_evaluator,
    submit_objective_rating,
    update_objective_progress,
)
from app.utils.decorators import require_role
from app.utils.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
)
from . import bp
from .forms import (
    AddEvaluationForm,
    EvaluationAcknowledgeForm,
    EvaluationCampaignForm,
    EvaluationContentForm,
    ObjectiveForm,
    ObjectiveProgressForm,
    ObjectiveRatingForm,
)


def _require_employee_profile() -> int:
    if not current_user.employee:
        abort(403, description="Aucun profil employé associé à ce compte.")
    return current_user.employee.id


def _current_company_id() -> int | None:
    """Retourne la company_id de l'utilisateur.
    Priorité : fiche employé → première Company en base → None.
    """
    if current_user.employee:
        return current_user.employee.company_id
    from app.models.organization import Company
    company = Company.get_default()
    return company.id if company else None


# =============================================================================
# GET /performance/ — vue d'ensemble personnelle
# =============================================================================

@bp.get("/")
@login_required
def index():
    """
    Vue d'ensemble : mes objectifs, mes évaluations, et (si manager)
    les évaluations à rédiger pour mon équipe.
    """
    role = current_user.role.name
    employee = current_user.employee
    own_id: int | None = employee.id if employee else None

    # KPIs personnels — nécessitent une fiche employé
    if own_id:
        objectives = list_objectives_for_employee(own_id, active_only=True)
        my_evaluations = list_evaluations_for_employee(own_id)
        pending_my_review = list_pending_employee_review(own_id)
    else:
        objectives = []
        my_evaluations = []
        pending_my_review = []

    pending_to_write = []
    pending_employee_ack = []
    team_objectives = []
    campaigns_overview = []

    if role in ("manager", "rh", "admin") and own_id:
        pending_to_write = list_pending_for_evaluator(own_id)
        pending_employee_ack = list_submitted_awaiting_employee(own_id)
        team_objectives = list_objectives_set_by(own_id)

    if role in ("rh", "admin"):
        company_id = _current_company_id()
        if company_id:
            campaigns_overview = list_all_campaigns_overview(company_id)

    return render_template(
        "performance/index.html",
        objectives=objectives,
        my_evaluations=my_evaluations,
        pending_my_review=pending_my_review,
        pending_to_write=pending_to_write,
        pending_employee_ack=pending_employee_ack,
        team_objectives=team_objectives,
        campaigns_overview=campaigns_overview,
        progress_form=ObjectiveProgressForm(),
    )


# =============================================================================
# GET/POST /performance/objectives/new — création d'un objectif
# =============================================================================

@bp.route("/objectives/new", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh", "manager")
def new_objective():
    """Formulaire de création d'un objectif pour un membre de l'équipe."""
    own_id = _require_employee_profile()
    company_id = current_user.employee.company_id

    form = ObjectiveForm()
    form.populate_employees(own_id)
    form.populate_campaigns(company_id)

    if form.validate_on_submit():
        payload = {
            "employee_id": form.employee_id.data,
            "campaign_id": form.campaign_id.data or None,
            "title": form.title.data,
            "description": form.description.data or None,
            "success_criteria": form.success_criteria.data or None,
            "weight": form.weight.data,
            "due_date": form.due_date.data,
        }

        try:
            objective = create_objective(payload, set_by_id=own_id)
        except (NotFoundError, BusinessRuleError) as exc:
            flash(str(exc), "error")
        else:
            flash(f"Objectif « {objective.title} » créé avec succès.", "success")
            return redirect(url_for("performance.index"))

    return render_template("performance/objective_form.html", form=form)


# =============================================================================
# POST /performance/objectives/<id>/progress — mise à jour avancement
# =============================================================================

@bp.post("/objectives/<int:objective_id>/progress")
@login_required
def update_progress(objective_id: int):
    """Met à jour le pourcentage d'avancement d'un objectif."""
    form = ObjectiveProgressForm()

    if not form.validate_on_submit():
        flash("Valeur d'avancement invalide.", "error")
        return redirect(url_for("performance.index"))

    try:
        update_objective_progress(objective_id, form.completion_pct.data)
    except NotFoundError:
        abort(404)
    except BusinessRuleError as exc:
        flash(str(exc), "error")
    else:
        flash("Avancement mis à jour.", "success")

    return redirect(url_for("performance.index"))


# =============================================================================
# POST /performance/objectives/<id>/rating — notation
# =============================================================================

@bp.post("/objectives/<int:objective_id>/rating")
@login_required
def rate_objective(objective_id: int):
    """Soumet une note sur un objectif (manager ou employé selon le rôle courant)."""
    form = ObjectiveRatingForm()

    if not form.validate_on_submit():
        flash("Erreur de validation de la note.", "error")
        return redirect(url_for("performance.index"))

    rated_by = "manager" if current_user.role.name in ("admin", "rh", "manager") else "employee"

    try:
        submit_objective_rating(
            objective_id, form.rating.data, form.comment.data or None, rated_by=rated_by
        )
    except NotFoundError:
        abort(404)
    else:
        flash("Note enregistrée.", "success")

    return redirect(url_for("performance.index"))


# =============================================================================
# GET /performance/campaigns — liste (admin/rh)
# =============================================================================

@bp.get("/campaigns")
@login_required
@require_role("admin", "rh", "manager")
def list_campaigns():
    """Liste des campagnes d'évaluation de l'entreprise."""
    company_id = _current_company_id()
    if company_id is None:
        abort(400, description="Aucune entreprise configurée. Lancez flask seed-init.")

    campaigns = db.session.execute(
        EvaluationCampaign.active_in_company(company_id)
    ).scalars().all()

    return render_template("performance/campaigns.html", campaigns=campaigns)


# =============================================================================
# GET/POST /performance/campaigns/new — création
# =============================================================================

@bp.route("/campaigns/new", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh", "manager")
def new_campaign():
    """Formulaire de création d'une campagne d'évaluation."""
    company_id = _current_company_id()
    if company_id is None:
        abort(400, description="Aucune entreprise configurée. Lancez flask seed-init.")

    form = EvaluationCampaignForm()

    if form.validate_on_submit():
        payload = {
            "company_id": company_id,
            "name": form.name.data,
            "description": form.description.data or None,
            "period_year": form.period_year.data,
            "period_type": form.period_type.data,
            "start_date": form.start_date.data,
            "end_date": form.end_date.data,
            "objective_deadline": form.objective_deadline.data,
        }

        try:
            campaign = create_campaign(payload, created_by_id=current_user.id)
        except Exception as exc:
            flash(str(exc), "error")
        else:
            flash(f"Campagne « {campaign.name} » créée avec succès.", "success")
            return redirect(url_for("performance.campaign_detail", campaign_id=campaign.id))

    return render_template("performance/campaign_form.html", form=form)


# =============================================================================
# GET/POST /performance/campaigns/<id> — détail + ajout de participant
# =============================================================================

@bp.route("/campaigns/<int:campaign_id>", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh", "manager")
def campaign_detail(campaign_id: int):
    """Détail d'une campagne avec ses statistiques, ses évaluations et l'ajout de participants."""
    try:
        campaign = get_campaign(campaign_id)
    except NotFoundError:
        abort(404, description="Campagne introuvable.")

    company_id = _current_company_id()

    evaluations = campaign.evaluations.all()
    already_evaluated_ids = {ev.employee_id for ev in evaluations}

    form = AddEvaluationForm()
    if company_id:
        form.populate_employees(company_id, exclude_employee_ids=already_evaluated_ids)

    if form.validate_on_submit():
        try:
            ev = create_evaluation({
                "campaign_id": campaign_id,
                "employee_id": form.employee_id.data,
                "evaluator_id": form.evaluator_id.data,
            })
            send_to_evaluator(ev.id)
            flash(
                f"Évaluation créée et envoyée à l'évaluateur pour {ev.employee.full_name}.",
                "success",
            )
        except (ConflictError, BusinessRuleError, NotFoundError) as exc:
            flash(str(exc), "error")

        return redirect(url_for("performance.campaign_detail", campaign_id=campaign_id))

    # Recharger après un éventuel ajout
    evaluations = campaign.evaluations.all()

    return render_template(
        "performance/campaign_detail.html",
        campaign=campaign,
        evaluations=evaluations,
        form=form,
    )


# =============================================================================
# GET /performance/evaluations/<id> — détail d'une évaluation
# =============================================================================

@bp.get("/evaluations/<int:evaluation_id>")
@login_required
def evaluation_detail(evaluation_id: int):
    """Détail d'une évaluation, avec actions contextuelles selon le rôle et le statut."""
    try:
        evaluation = get_evaluation(evaluation_id)
    except NotFoundError:
        abort(404, description="Évaluation introuvable.")

    is_privileged = current_user.role.name in ("admin", "rh")
    if is_privileged:
        own_id = current_user.employee.id if current_user.employee else None
    else:
        own_id = _require_employee_profile()
        if own_id not in (evaluation.employee_id, evaluation.evaluator_id):
            abort(403, description="Accès refusé à cette évaluation.")

    can_write_content = (
        own_id is not None
        and own_id == evaluation.evaluator_id
        and evaluation.status == Evaluation.STATUS_IN_PROGRESS
    )
    can_acknowledge = (
        own_id is not None
        and own_id == evaluation.employee_id
        and evaluation.status == Evaluation.STATUS_EMPLOYEE_REVIEW
        and evaluation.employee_acknowledged_at is None
    )
    already_acknowledged = (
        own_id is not None
        and own_id == evaluation.employee_id
        and evaluation.status == Evaluation.STATUS_EMPLOYEE_REVIEW
        and evaluation.employee_acknowledged_at is not None
    )
    can_finalize = (
        own_id is not None
        and own_id == evaluation.evaluator_id
        and evaluation.status == Evaluation.STATUS_EMPLOYEE_REVIEW
    )
    can_archive = (
        is_privileged
        and evaluation.status == Evaluation.STATUS_COMPLETED
    )

    content_form = EvaluationContentForm(obj=evaluation)
    acknowledge_form = EvaluationAcknowledgeForm()

    return render_template(
        "performance/evaluation_detail.html",
        evaluation=evaluation,
        can_write_content=can_write_content,
        can_acknowledge=can_acknowledge,
        already_acknowledged=already_acknowledged,
        can_finalize=can_finalize,
        can_archive=can_archive,
        content_form=content_form,
        acknowledge_form=acknowledge_form,
    )


# =============================================================================
# POST /performance/evaluations/<id>/send — draft → in_progress
# =============================================================================

@bp.post("/evaluations/<int:evaluation_id>/send")
@login_required
def send_evaluation(evaluation_id: int):
    try:
        evaluation = get_evaluation(evaluation_id)
    except NotFoundError:
        abort(404)

    if current_user.role.name not in ("admin", "rh", "manager"):
        abort(403)

    try:
        send_to_evaluator(evaluation.id)
    except BusinessRuleError as exc:
        flash(str(exc), "error")
    else:
        flash("Évaluation envoyée à l'évaluateur.", "success")

    return redirect(url_for("performance.evaluation_detail", evaluation_id=evaluation_id))


# =============================================================================
# POST /performance/evaluations/<id>/submit — soumission contenu manager
# =============================================================================

@bp.post("/evaluations/<int:evaluation_id>/submit")
@login_required
def submit_evaluation(evaluation_id: int):
    try:
        evaluation = get_evaluation(evaluation_id)
    except NotFoundError:
        abort(404)

    is_privileged = current_user.role.name in ("admin", "rh")
    if is_privileged:
        own_id = current_user.employee.id if current_user.employee else None
    else:
        own_id = _require_employee_profile()
        if own_id != evaluation.evaluator_id:
            abort(403)

    form = EvaluationContentForm()

    if not form.validate_on_submit():
        flash("Erreur de validation du contenu de l'évaluation.", "error")
        return redirect(url_for("performance.evaluation_detail", evaluation_id=evaluation_id))

    content = {
        "overall_score": form.overall_score.data,
        "manager_overall_comment": form.manager_overall_comment.data or None,
        "strengths": form.strengths.data or None,
        "areas_for_improvement": form.areas_for_improvement.data or None,
        "development_plan": form.development_plan.data or None,
    }

    try:
        submit_by_evaluator(evaluation.id, content)
    except BusinessRuleError as exc:
        flash(str(exc), "error")
    else:
        flash("Évaluation soumise à l'employé pour relecture.", "success")

    return redirect(url_for("performance.evaluation_detail", evaluation_id=evaluation_id))


# =============================================================================
# POST /performance/evaluations/<id>/acknowledge — accusé employé
# =============================================================================

@bp.post("/evaluations/<int:evaluation_id>/acknowledge")
@login_required
def acknowledge_evaluation(evaluation_id: int):
    try:
        evaluation = get_evaluation(evaluation_id)
    except NotFoundError:
        abort(404)

    own_id = _require_employee_profile()
    if own_id != evaluation.employee_id:
        abort(403)

    if evaluation.employee_acknowledged_at is not None:
        flash("Vous avez déjà signé cette évaluation.", "warning")
        return redirect(url_for("performance.evaluation_detail", evaluation_id=evaluation_id))

    form = EvaluationAcknowledgeForm()

    if not form.validate_on_submit():
        flash("Vous devez confirmer la prise de connaissance.", "error")
        return redirect(url_for("performance.evaluation_detail", evaluation_id=evaluation_id))

    try:
        acknowledge_by_employee(
            evaluation.id,
            form.employee_overall_comment.data or None,
            sign=True,
        )
    except BusinessRuleError as exc:
        flash(str(exc), "error")
    else:
        flash("Évaluation signée et transmise au manager.", "success")

    return redirect(url_for("performance.evaluation_detail", evaluation_id=evaluation_id))


# =============================================================================
# POST /performance/evaluations/<id>/finalize — finalisation manager
# =============================================================================

@bp.post("/evaluations/<int:evaluation_id>/finalize")
@login_required
def finalize_evaluation_route(evaluation_id: int):
    try:
        evaluation = get_evaluation(evaluation_id)
    except NotFoundError:
        abort(404)

    is_privileged = current_user.role.name in ("admin", "rh")
    if is_privileged:
        own_id = current_user.employee.id if current_user.employee else None
    else:
        own_id = _require_employee_profile()
        if own_id != evaluation.evaluator_id:
            abort(403)

    try:
        finalize_evaluation(evaluation.id, sign=True)
    except BusinessRuleError as exc:
        flash(str(exc), "error")
    else:
        flash("Évaluation finalisée avec succès.", "success")

    return redirect(url_for("performance.evaluation_detail", evaluation_id=evaluation_id))


# =============================================================================
# POST /performance/evaluations/<id>/archive — completed → archived
# =============================================================================

@bp.post("/evaluations/<int:evaluation_id>/archive")
@login_required
def archive_evaluation_route(evaluation_id: int):
    if current_user.role.name not in ("admin", "rh"):
        abort(403)

    try:
        evaluation = get_evaluation(evaluation_id)
        archive_evaluation(evaluation.id)
    except NotFoundError:
        abort(404)
    except BusinessRuleError as exc:
        flash(str(exc), "error")
    else:
        flash("Évaluation archivée.", "success")

    return redirect(url_for("performance.evaluation_detail", evaluation_id=evaluation_id))