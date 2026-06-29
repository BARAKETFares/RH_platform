"""
Routes SSR du module Recrutement.

Pages couvertes :
    GET       /recruitment/                              → liste des offres
    GET/POST  /recruitment/new                           → créer une offre (admin/rh)
    GET       /recruitment/<id>                          → détail offre + candidatures
    GET/POST  /recruitment/<id>/edit                     → modifier une offre (admin/rh)
    POST      /recruitment/<id>/action                   → changer le statut de l'offre
    GET/POST  /recruitment/<id>/apply                    → ajouter une candidature
    GET       /recruitment/applications/<id>             → détail d'une candidature
    POST      /recruitment/applications/<id>/decision    → décision finale (pipeline)
    GET/POST  /recruitment/applications/<id>/interview   → planifier un entretien
    GET       /recruitment/interviews/<id>               → détail d'un entretien
    POST      /recruitment/interviews/<id>/result        → saisir le résultat

Accès :
    admin / rh  → toutes les routes
    manager     → lecture (offres, candidatures, entretiens) + saisie de ses résultats
"""
from __future__ import annotations

import logging
from datetime import date

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.employee import Employee
from app.models.recruitment import Application, Interview, JobPosting
from app.services.recruitment_service import (
    create_candidate,
    create_job_posting,
    get_application,
    get_interview,
    get_job_posting,
    list_applications_for_posting,
    list_interviews_for_application,
    list_job_postings,
    prepare_employee_data_from_application,
    schedule_interview,
    submit_application,
    update_application_status,
    update_interview,
    update_job_posting,
)
from app.utils.decorators import require_role
from app.utils.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from . import bp
from .forms import (
    ApplicationDecisionForm,
    CandidateApplicationForm,
    InterviewResultForm,
    InterviewScheduleForm,
    JobPostingForm,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Helpers privés
# =============================================================================

def _get_company_id() -> int:
    """Retourne le company_id courant ; pour admin sans profil employé, prend le premier."""
    if current_user.employee:
        return current_user.employee.company_id
    from app.models.organization import Company
    company = db.session.execute(db.select(Company).limit(1)).scalar_one_or_none()
    if company is None:
        abort(500, description="Aucune entreprise configurée.")
    return company.id


def _role() -> str:
    return current_user.role.name if current_user.role else "employee"


def _is_manager_interviewer(interview: Interview) -> bool:
    """Vérifie que le manager courant est l'interviewer assigné à cet entretien."""
    return (
        current_user.employee is not None
        and interview.interviewer_id == current_user.employee.id
    )


# =============================================================================
# Liste des offres d'emploi
# =============================================================================

@bp.get("/")
@login_required
@require_role("admin", "rh", "manager")
def list_postings():
    """Catalogue des offres, filtrables par statut."""
    company_id    = _get_company_id()
    status_filter = request.args.get("status") or None

    try:
        postings = list_job_postings(company_id=company_id, status=status_filter)
    except ValidationError as exc:
        flash(str(exc), "warning")
        postings = []

    return render_template(
        "recruitment/postings.html",
        postings=postings,
        current_status=status_filter,
        today=date.today(),
        JOB_STATUSES=JobPosting.STATUSES,
        STATUS_LABELS={
            "draft":     "Brouillon",
            "open":      "Ouverte",
            "closed":    "Clôturée",
            "cancelled": "Annulée",
        },
    )


# =============================================================================
# Création d'une offre
# =============================================================================

@bp.route("/new", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh")
def new_posting():
    """Formulaire de création d'une nouvelle offre d'emploi."""
    company_id = _get_company_id()
    form = JobPostingForm()
    form.populate_departments(company_id)
    form.populate_positions(company_id)

    if form.validate_on_submit():
        dept_id = form.department_id.data or None
        pos_id  = form.position_id.data  or None
        data = {
            "company_id":     company_id,
            "created_by_id":  current_user.id,
            "title":          form.title.data,
            "description":    form.description.data or None,
            "requirements":   form.requirements.data or None,
            "department_id":  dept_id if dept_id != 0 else None,
            "position_id":    pos_id  if pos_id  != 0 else None,
            "location":       form.location.data or None,
            "contract_type":  form.contract_type.data or None,
            "salary_min":     float(form.salary_min.data) if form.salary_min.data else None,
            "salary_max":     float(form.salary_max.data) if form.salary_max.data else None,
            "headcount":      form.headcount.data or 1,
            "closing_date":   form.closing_date.data,
            "status":         "draft",
        }
        try:
            posting = create_job_posting(data)
            flash(f"Offre « {posting.title} » créée (brouillon).", "success")
            return redirect(url_for("recruitment.posting_detail", posting_id=posting.id))
        except (ValidationError, NotFoundError) as exc:
            flash(str(exc), "danger")

    return render_template("recruitment/posting_form.html",
                           form=form, title="Nouvelle offre d'emploi", posting=None)


# =============================================================================
# Détail d'une offre + liste des candidatures
# =============================================================================

@bp.get("/<int:posting_id>")
@login_required
@require_role("admin", "rh", "manager")
def posting_detail(posting_id: int):
    """
    Fiche d'une offre avec la liste de ses candidatures.
    Le manager voit toutes les candidatures (filtrables par statut).
    """
    posting       = JobPosting.get_or_404(posting_id)
    status_filter = request.args.get("status") or None

    try:
        applications = list_applications_for_posting(posting_id, status=status_filter)
    except (NotFoundError, ValidationError) as exc:
        flash(str(exc), "warning")
        applications = []

    decision_form = ApplicationDecisionForm()

    # Données pré-remplies pour le bouton "Créer fiche employé" (statut embauchee)
    hired_prefill: dict[int, dict] = {}
    if _role() in ("admin", "rh"):
        for app_ in applications:
            if app_.status == Application.STATUS_HIRED and app_.hired_employee_id is None:
                try:
                    hired_prefill[app_.id] = prepare_employee_data_from_application(app_.id)
                except BusinessRuleError:
                    pass

    return render_template(
        "recruitment/applications.html",
        posting=posting,
        applications=applications,
        current_status=status_filter,
        decision_form=decision_form,
        hired_prefill=hired_prefill,
        today=date.today(),
        APPLICATION_STATUSES=Application.STATUSES,
        STATUS_LABELS=Application.STATUS_LABELS,
        role_name=_role(),
    )


# =============================================================================
# Modification d'une offre
# =============================================================================

@bp.route("/<int:posting_id>/edit", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh")
def edit_posting(posting_id: int):
    """Formulaire d'édition d'une offre existante."""
    posting    = JobPosting.get_or_404(posting_id)
    company_id = _get_company_id()
    form       = JobPostingForm(obj=posting)
    form.populate_departments(company_id)
    form.populate_positions(company_id)

    if form.validate_on_submit():
        dept_id = form.department_id.data or None
        pos_id  = form.position_id.data  or None
        data = {
            "title":        form.title.data,
            "description":  form.description.data or None,
            "requirements": form.requirements.data or None,
            "department_id": dept_id if dept_id != 0 else None,
            "position_id":   pos_id  if pos_id  != 0 else None,
            "location":      form.location.data or None,
            "contract_type": form.contract_type.data or None,
            "salary_min":    float(form.salary_min.data) if form.salary_min.data else None,
            "salary_max":    float(form.salary_max.data) if form.salary_max.data else None,
            "headcount":     form.headcount.data or 1,
            "closing_date":  form.closing_date.data,
        }
        try:
            update_job_posting(posting_id, data)
            flash(f"Offre « {posting.title} » mise à jour.", "success")
            return redirect(url_for("recruitment.posting_detail", posting_id=posting_id))
        except (NotFoundError, ValidationError, BusinessRuleError) as exc:
            flash(str(exc), "danger")

    return render_template("recruitment/posting_form.html",
                           form=form, title="Modifier l'offre", posting=posting)


# =============================================================================
# Changement de statut de l'offre (open / close / cancel)
# =============================================================================

@bp.post("/<int:posting_id>/action")
@login_required
@require_role("admin", "rh")
def posting_action(posting_id: int):
    """
    Change le statut d'une offre selon l'action demandée dans `action`.

    Valeurs acceptées pour le champ `action` du formulaire :
        open    → publier (draft → open)
        close   → clôturer (open → closed)
        cancel  → annuler (tout → cancelled)
    """
    action = request.form.get("action", "")
    target_map = {
        "open":   "open",
        "close":  "closed",
        "cancel": "cancelled",
    }
    target_status = target_map.get(action)
    if not target_status:
        flash("Action non reconnue.", "warning")
        return redirect(url_for("recruitment.posting_detail", posting_id=posting_id))

    try:
        update_job_posting(posting_id, {"status": target_status})
        label = {"open": "publiée", "closed": "clôturée", "cancelled": "annulée"}[target_status]
        flash(f"Offre {label} avec succès.", "success")
    except (NotFoundError, BusinessRuleError) as exc:
        flash(str(exc), "danger")

    return redirect(url_for("recruitment.posting_detail", posting_id=posting_id))


# =============================================================================
# Ajout d'une candidature à une offre
# =============================================================================

@bp.route("/<int:posting_id>/apply", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh")
def add_application(posting_id: int):
    """
    Crée un candidat (ou identifie un candidat existant par email) et
    soumet sa candidature à l'offre indiquée.

    Si l'email est déjà présent dans le vivier, le candidat existant
    est réutilisé sans erreur (affichage d'un message d'information).
    """
    posting = JobPosting.get_or_404(posting_id)

    if posting.status != JobPosting.STATUS_OPEN:
        flash(
            f"L'offre « {posting.title} » n'est pas ouverte "
            f"(statut : {posting.status}). Publiez-la d'abord.",
            "warning",
        )
        return redirect(url_for("recruitment.posting_detail", posting_id=posting_id))

    form = CandidateApplicationForm()

    if form.validate_on_submit():
        email = form.email.data.strip().lower()

        # Trouver ou créer le candidat
        from app.models.recruitment import Candidate
        candidate = Candidate.find_by_email(email)
        if candidate is None:
            try:
                candidate = create_candidate({
                    "first_name": form.first_name.data.strip(),
                    "last_name":  form.last_name.data.strip(),
                    "email":      email,
                    "phone":      form.phone.data or None,
                    "source":     form.source.data,
                    "cv_text":    form.cv_text.data or None,
                    "notes":      form.notes.data or None,
                })
            except (ValidationError, ConflictError) as exc:
                flash(str(exc), "danger")
                return render_template("recruitment/application_form.html",
                                       posting=posting, form=form)
        else:
            flash(
                f"Candidat existant retrouvé : {candidate.full_name} ({email}).",
                "info",
            )

        # Soumettre la candidature
        try:
            application = submit_application({
                "candidate_id":   candidate.id,
                "job_posting_id": posting_id,
                "notes":          form.notes.data or None,
            })
            flash(
                f"Candidature de {candidate.full_name} enregistrée "
                f"(statut : reçue).",
                "success",
            )
            return redirect(
                url_for("recruitment.application_detail", application_id=application.id)
            )
        except (BusinessRuleError, ConflictError) as exc:
            flash(str(exc), "danger")
        except NotFoundError as exc:
            flash(str(exc), "warning")

    return render_template("recruitment/application_form.html",
                           posting=posting, form=form)


# =============================================================================
# Détail d'une candidature
# =============================================================================

@bp.get("/applications/<int:application_id>")
@login_required
@require_role("admin", "rh", "manager")
def application_detail(application_id: int):
    """Fiche complète d'une candidature avec ses entretiens."""
    try:
        application = get_application(application_id)
    except NotFoundError:
        abort(404, description="Candidature introuvable.")

    interviews    = list_interviews_for_application(application_id)
    decision_form = ApplicationDecisionForm()
    decision_form.set_choices_from_status(application.status)

    employee_prefill = None
    if (
        _role() in ("admin", "rh")
        and application.status == Application.STATUS_HIRED
        and application.hired_employee_id is None
    ):
        try:
            employee_prefill = prepare_employee_data_from_application(application_id)
        except BusinessRuleError:
            pass

    return render_template(
        "recruitment/application_detail.html",
        application=application,
        interviews=interviews,
        decision_form=decision_form,
        employee_prefill=employee_prefill,
        role_name=_role(),
        STATUS_LABELS=Application.STATUS_LABELS,
    )


# =============================================================================
# Décision finale sur une candidature (pipeline RH)
# =============================================================================

@bp.post("/applications/<int:application_id>/decision")
@login_required
@require_role("admin", "rh")
def update_application_decision(application_id: int):
    """
    Avance ou termine la candidature selon la décision RH.

    Transitions légales :
        reçue → présélectionnée → entretien → offre → embauchée
        tout sauf embauchée → refusée
    """
    try:
        application = get_application(application_id)
    except NotFoundError:
        abort(404)

    form = ApplicationDecisionForm()
    form.set_choices_from_status(application.status)

    if not form.validate_on_submit():
        errors = "; ".join(
            f"{f}: {', '.join(errs)}" for f, errs in form.errors.items()
        )
        flash(f"Formulaire invalide : {errors}", "danger")
        return redirect(
            url_for("recruitment.application_detail", application_id=application_id)
        )

    try:
        update_application_status(application_id, {
            "status":           form.status.data,
            "rejection_reason": form.rejection_reason.data or None,
            "notes":            form.notes.data or None,
        })
        new_label = Application.STATUS_LABELS.get(form.status.data, form.status.data)
        flash(f"Candidature passée au statut « {new_label} ».", "success")
    except (BusinessRuleError, ValidationError) as exc:
        flash(str(exc), "danger")
    except NotFoundError as exc:
        flash(str(exc), "warning")

    return redirect(
        url_for("recruitment.application_detail", application_id=application_id)
    )


# =============================================================================
# Planification d'un entretien
# =============================================================================

@bp.route("/applications/<int:application_id>/interview", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh")
def schedule_interview_view(application_id: int):
    """
    Planifie un entretien pour une candidature au statut 'entretien'.
    La candidature doit avoir été avancée au bon statut avant d'accéder
    à cette page (via update_application_decision).
    """
    try:
        application = get_application(application_id)
    except NotFoundError:
        abort(404)

    if application.status != Application.STATUS_INTERVIEW:
        flash(
            "La candidature doit être au statut « Entretien » pour planifier un rendez-vous. "
            "Appliquez d'abord la décision correspondante.",
            "warning",
        )
        return redirect(
            url_for("recruitment.application_detail", application_id=application_id)
        )

    company_id = _get_company_id()
    form       = InterviewScheduleForm()
    form.populate_interviewers(company_id)

    if form.validate_on_submit():
        interviewer_id = form.interviewer_id.data or None
        if interviewer_id == 0:
            interviewer_id = None

        try:
            interview = schedule_interview({
                "application_id":   application_id,
                "scheduled_at":     form.scheduled_at.data,
                "interview_type":   form.interview_type.data,
                "interviewer_id":   interviewer_id,
                "duration_minutes": form.duration_minutes.data or 60,
                "location":         form.location.data or None,
            })
            flash("Entretien planifié avec succès.", "success")
            return redirect(
                url_for("recruitment.interview_detail", interview_id=interview.id)
            )
        except (BusinessRuleError, NotFoundError, ValidationError) as exc:
            flash(str(exc), "danger")

    return render_template(
        "recruitment/interview_form.html",
        application=application,
        form=form,
        title="Planifier un entretien",
    )


# =============================================================================
# Détail d'un entretien
# =============================================================================

@bp.get("/interviews/<int:interview_id>")
@login_required
@require_role("admin", "rh", "manager")
def interview_detail(interview_id: int):
    """
    Fiche d'un entretien.

    Le manager ne peut consulter que les entretiens dont il est l'interviewer.
    """
    try:
        interview = get_interview(interview_id)
    except NotFoundError:
        abort(404)

    if _role() == "manager" and not _is_manager_interviewer(interview):
        abort(403, description="Vous n'êtes pas l'interviewer assigné à cet entretien.")

    result_form = InterviewResultForm()

    return render_template(
        "recruitment/interview_detail.html",
        interview=interview,
        result_form=result_form,
        can_submit_result=(
            not interview.is_completed
            and (_role() in ("admin", "rh") or _is_manager_interviewer(interview))
        ),
        role_name=_role(),
        DECISION_LABELS={
            "pending": "En attente",
            "proceed": "Poursuivre",
            "hold":    "À confirmer",
            "reject":  "Refuser",
        },
    )


# =============================================================================
# Résultat d'un entretien
# =============================================================================

@bp.post("/interviews/<int:interview_id>/result")
@login_required
@require_role("admin", "rh", "manager")
def update_interview_result(interview_id: int):
    """
    Enregistre le résultat d'un entretien (décision + note + notes).

    Accès : admin/rh + manager seulement s'il est l'interviewer.
    """
    try:
        interview = get_interview(interview_id)
    except NotFoundError:
        abort(404)

    if _role() == "manager" and not _is_manager_interviewer(interview):
        abort(403, description="Vous n'êtes pas l'interviewer assigné à cet entretien.")

    if interview.is_completed:
        flash("Le résultat de cet entretien a déjà été saisi.", "warning")
        return redirect(
            url_for("recruitment.interview_detail", interview_id=interview_id)
        )

    form = InterviewResultForm()

    if not form.validate_on_submit():
        errors = "; ".join(
            f"{f}: {', '.join(errs)}" for f, errs in form.errors.items()
        )
        flash(f"Formulaire invalide : {errors}", "danger")
        return redirect(
            url_for("recruitment.interview_detail", interview_id=interview_id)
        )

    rating = form.rating.data if form.rating.data and form.rating.data > 0 else None

    try:
        update_interview(interview_id, {
            "decision": form.decision.data,
            "rating":   rating,
            "notes":    form.notes.data or None,
        })
        flash("Résultat de l'entretien enregistré.", "success")
    except (BusinessRuleError, NotFoundError) as exc:
        flash(str(exc), "danger")

    return redirect(
        url_for("recruitment.interview_detail", interview_id=interview_id)
    )
