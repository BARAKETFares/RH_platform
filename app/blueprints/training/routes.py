"""
Routes SSR du module Training (Formations & Inscriptions).

Pages couvertes :
    GET       /training/                         → catalogue des formations
    GET/POST  /training/new                      → créer une formation (admin/rh)
    GET       /training/<id>                     → détail d'une formation
    GET/POST  /training/<id>/edit                → modifier une formation (admin/rh)
    POST      /training/<id>/toggle              → activer/désactiver (admin/rh)
    GET/POST  /training/<id>/enroll              → inscrire un employé
    GET       /training/me                       → mes formations (vue employé)
    GET       /training/team                     → suivi de l'équipe (manager/rh/admin)
    GET       /training/enrollments/<id>         → détail d'une inscription
    POST      /training/enrollments/<id>/status  → changer le statut d'une inscription
"""
from __future__ import annotations

import logging

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.employee import Employee
from app.models.training import Enrollment, Training
from app.services.training_service import (
    create_training,
    enroll_employee,
    list_enrollments_for_employee,
    list_enrollments_for_training,
    list_trainings,
    update_enrollment_status,
    update_training,
)
from app.utils.decorators import require_role
from app.utils.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from . import bp
from .forms import EnrollForm, EnrollmentStatusForm, TrainingForm

logger = logging.getLogger(__name__)


# =============================================================================
# Helpers privés
# =============================================================================

def _require_employee_profile() -> int:
    """Retourne l'id employé courant ou lève 403 si le compte n'a pas de profil."""
    if current_user.employee is None:
        abort(403, description="Votre compte n'est pas lié à un profil employé.")
    return current_user.employee.id


def _get_company_id() -> int:
    """
    Retourne le company_id de l'utilisateur courant.
    Pour un admin sans profil employé, utilise la première entreprise disponible.
    """
    if current_user.employee:
        return current_user.employee.company_id
    from app.models.organization import Company
    company = db.session.execute(db.select(Company).limit(1)).scalar_one_or_none()
    if company is None:
        abort(500, description="Aucune entreprise configurée.")
    return company.id


def _is_team_member(employee_id: int, manager_employee_id: int) -> bool:
    """Retourne True si l'employé est un membre direct de l'équipe du manager."""
    return db.session.execute(
        db.select(Employee).where(
            Employee.id == employee_id,
            Employee.manager_id == manager_employee_id,
        )
    ).scalar_one_or_none() is not None


# =============================================================================
# Catalogue des formations
# =============================================================================

@bp.get("/")
@login_required
def list_trainings_view():
    """Catalogue des formations actives. Filtre optionnel via query param `type`."""
    company_id = _get_company_id()
    training_type = request.args.get("type") or None

    try:
        trainings = list_trainings(
            company_id=company_id,
            active_only=True,
            training_type=training_type,
        )
    except ValidationError as exc:
        flash(str(exc), "warning")
        trainings = []

    return render_template(
        "training/list.html",
        trainings=trainings,
        current_type=training_type,
        TRAINING_TYPES=Training.VALID_TYPES,
    )


# =============================================================================
# Création d'une formation
# =============================================================================

@bp.route("/new", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh")
def new_training():
    """Formulaire de création d'une nouvelle formation (admin/rh)."""
    company_id = _get_company_id()
    form = TrainingForm()

    if form.validate_on_submit():
        data = {
            "company_id":     company_id,
            "title":          form.title.data,
            "description":    form.description.data or None,
            "organisme":      form.organisme.data or None,
            "duration_hours": float(form.duration_hours.data) if form.duration_hours.data else None,
            "training_type":  form.training_type.data,
            "cost":           float(form.cost.data) if form.cost.data else None,
            "is_active":      form.is_active.data,
        }
        try:
            training = create_training(data)
            flash(f"Formation « {training.title} » créée avec succès.", "success")
            return redirect(url_for("training.training_detail", training_id=training.id))
        except ValidationError as exc:
            flash(str(exc), "danger")

    return render_template("training/form.html", form=form, title="Nouvelle formation",
                           training=None)


# =============================================================================
# Modification d'une formation  (FIX E-1)
# =============================================================================

@bp.route("/<int:training_id>/edit", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh")
def edit_training(training_id: int):
    """Formulaire d'édition d'une formation existante (admin/rh)."""
    training = Training.get_or_404(training_id)
    form = TrainingForm(obj=training)

    if form.validate_on_submit():
        data = {
            "title":          form.title.data,
            "description":    form.description.data or None,
            "organisme":      form.organisme.data or None,
            "duration_hours": float(form.duration_hours.data) if form.duration_hours.data else None,
            "training_type":  form.training_type.data,
            "cost":           float(form.cost.data) if form.cost.data else None,
            "is_active":      form.is_active.data,
        }
        try:
            update_training(training_id, data)
            flash(f"Formation « {training.title} » mise à jour.", "success")
            return redirect(url_for("training.training_detail", training_id=training_id))
        except (NotFoundError, ValidationError) as exc:
            flash(str(exc), "danger")

    return render_template("training/form.html", form=form,
                           title="Modifier la formation", training=training)


# =============================================================================
# Activer / désactiver une formation  (FIX E-2)
# =============================================================================

@bp.post("/<int:training_id>/toggle")
@login_required
@require_role("admin", "rh")
def toggle_training(training_id: int):
    """Bascule le statut actif/inactif d'une formation (admin/rh)."""
    training = Training.get_or_404(training_id)
    try:
        updated = update_training(training_id, {"is_active": not training.is_active})
        state = "activée" if updated.is_active else "désactivée"
        flash(f"Formation « {updated.title} » {state}.", "success")
    except (NotFoundError, ValidationError) as exc:
        flash(str(exc), "danger")
    return redirect(url_for("training.training_detail", training_id=training_id))


# =============================================================================
# Détail d'une formation
# =============================================================================

@bp.get("/<int:training_id>")
@login_required
def training_detail(training_id: int):
    """
    Fiche détaillée d'une formation.

    admin / rh / manager → voient toutes les inscriptions.
    employee             → voit uniquement ses propres inscriptions à cette formation.
    """
    training = Training.get_or_404(training_id)
    role_name = current_user.role.name if current_user.role else "employee"
    is_privileged = role_name in ("admin", "rh", "manager")

    if is_privileged:
        enrollments = list_enrollments_for_training(training_id)
    else:
        emp_id = current_user.employee.id if current_user.employee else None
        if emp_id:
            all_emp = list_enrollments_for_employee(emp_id, active_only=False)
            enrollments = [e for e in all_emp if e.training_id == training_id]
        else:
            enrollments = []

    # ID de l'employé courant pour masquer le bouton de statut sur sa propre inscription
    own_employee_id = current_user.employee.id if current_user.employee else None

    status_form = EnrollmentStatusForm()

    return render_template(
        "training/detail.html",
        training=training,
        enrollments=enrollments,
        status_form=status_form,
        is_privileged=is_privileged,
        own_employee_id=own_employee_id,
        role_name=role_name,
        Enrollment=Enrollment,
    )


# =============================================================================
# Inscription d'un employé
# =============================================================================

@bp.route("/<int:training_id>/enroll", methods=["GET", "POST"])
@login_required
def enroll(training_id: int):
    """
    Inscrit un employé à une formation.

    Accès :
        admin / rh  → tout employé de l'entreprise
        manager     → son équipe directe + lui-même  (FIX B-3)
        employee    → auto-inscription uniquement
    """
    training = Training.get_or_404(training_id)
    role_name = current_user.role.name if current_user.role else "employee"
    form = EnrollForm()

    if role_name in ("admin", "rh"):
        form.populate_employees_company(_get_company_id())
    elif role_name == "manager":
        emp_id = _require_employee_profile()
        form.populate_employees_team(emp_id)
        # Ajouter le manager lui-même pour qu'il puisse s'inscrire
        self_choice = (current_user.employee.id, current_user.employee.full_name + " (moi-même)")
        form.employee_id.choices = [self_choice] + list(form.employee_id.choices)
    else:
        emp_id = _require_employee_profile()
        form.populate_self(emp_id, current_user.employee.full_name)

    if form.validate_on_submit():
        data = {
            "employee_id": form.employee_id.data,
            "training_id": training_id,
            "start_date":  form.start_date.data,
            "end_date":    form.end_date.data,
        }
        try:
            enroll_employee(data)
            flash(f"Inscription à « {training.title} » enregistrée (statut : planifiée).", "success")
            return redirect(url_for("training.training_detail", training_id=training_id))
        except (NotFoundError, BusinessRuleError, ConflictError) as exc:
            flash(str(exc), "danger")
        except ValidationError as exc:
            flash(str(exc), "warning")

    return render_template(
        "training/enroll.html",
        training=training,
        form=form,
        role_name=role_name,
    )


# =============================================================================
# Mes formations (vue employé)
# =============================================================================

@bp.get("/me")
@login_required
def my_trainings():
    """
    Toutes les inscriptions de l'employé connecté.
    Requiert un profil employé ; abort 403 sinon.
    """
    emp_id = _require_employee_profile()
    status_filter = request.args.get("status") or None

    try:
        enrollments = list_enrollments_for_employee(
            emp_id, status=status_filter, active_only=False,
        )
    except (NotFoundError, ValidationError) as exc:
        flash(str(exc), "warning")
        enrollments = []

    status_form = EnrollmentStatusForm()

    return render_template(
        "training/my_trainings.html",
        enrollments=enrollments,
        current_status=status_filter,
        ENROLLMENT_STATUSES=Enrollment.STATUSES,
        status_form=status_form,
    )


# =============================================================================
# Suivi équipe (manager / rh / admin)
# =============================================================================

@bp.get("/team")
@login_required
@require_role("admin", "rh", "manager")
def team_trainings():
    """
    Vue de suivi des formations pour les membres de l'équipe.

    manager    → membres directs (manager_id = employé courant)
    admin / rh → tous les employés actifs de l'entreprise
    """
    role_name = current_user.role.name if current_user.role else ""
    status_filter = request.args.get("status") or None
    company_id = _get_company_id()

    if role_name == "manager":
        emp_id = _require_employee_profile()
        team_members = db.session.execute(
            db.select(Employee).where(
                Employee.manager_id == emp_id,
                Employee.status.in_((Employee.STATUS_ACTIVE, Employee.STATUS_PROBATION)),
            ).order_by(Employee.last_name, Employee.first_name)
        ).scalars().all()
    else:
        team_members = db.session.execute(
            db.select(Employee).where(
                Employee.company_id == company_id,
                Employee.status.in_((Employee.STATUS_ACTIVE, Employee.STATUS_PROBATION)),
            ).order_by(Employee.last_name, Employee.first_name)
        ).scalars().all()

    all_enrollments: list[Enrollment] = []
    for member in team_members:
        try:
            member_enrollments = list_enrollments_for_employee(
                member.id, status=status_filter, active_only=False,
            )
            all_enrollments.extend(member_enrollments)
        except NotFoundError:
            continue

    all_enrollments.sort(key=lambda e: e.created_at, reverse=True)

    status_form = EnrollmentStatusForm()

    return render_template(
        "training/team_trainings.html",
        team_members=team_members,
        enrollments=all_enrollments,
        current_status=status_filter,
        ENROLLMENT_STATUSES=Enrollment.STATUSES,
        status_form=status_form,
        role_name=role_name,
    )


# =============================================================================
# Détail d'une inscription
# =============================================================================

@bp.get("/enrollments/<int:enrollment_id>")
@login_required
def enrollment_detail(enrollment_id: int):
    """
    Fiche détaillée d'une inscription.

    Accès :
        admin / rh  → toutes les inscriptions
        manager     → équipe directe + sa propre inscription  (FIX A-2)
        employee    → uniquement ses propres inscriptions

    Abort 403 si aucun profil employé et pas admin/rh.  (FIX A-3)
    """
    enrollment = Enrollment.get_or_404(enrollment_id)
    role_name = current_user.role.name if current_user.role else "employee"

    can_update = False
    if role_name in ("admin", "rh"):
        can_update = True
    elif current_user.employee:
        own_id = current_user.employee.id
        if role_name == "manager":
            if _is_team_member(enrollment.employee_id, own_id):
                can_update = True
            elif enrollment.employee_id == own_id:
                # Manager consulte sa propre inscription (FIX A-2)
                can_update = enrollment.status in (
                    Enrollment.STATUS_PLANNED, Enrollment.STATUS_IN_PROGRESS
                )
            else:
                abort(403, description="Cet employé n'est pas membre de votre équipe.")
        else:
            if enrollment.employee_id != own_id:
                abort(403, description="Vous ne pouvez consulter que vos propres inscriptions.")
            can_update = enrollment.status in (
                Enrollment.STATUS_PLANNED, Enrollment.STATUS_IN_PROGRESS
            )
    else:
        # Authentifié sans profil employé et pas admin/rh → accès refusé  (FIX A-3)
        abort(403, description="Votre compte n'est pas lié à un profil employé.")

    status_form = EnrollmentStatusForm()

    return render_template(
        "training/enrollment_detail.html",
        enrollment=enrollment,
        status_form=status_form,
        can_update=can_update,
    )


# =============================================================================
# Mise à jour du statut d'une inscription
# =============================================================================

@bp.post("/enrollments/<int:enrollment_id>/status")
@login_required
def update_enrollment_status_view(enrollment_id: int):
    """
    Transition de statut d'une inscription.

    Accès :
        admin / rh  → toutes les inscriptions
        manager     → équipe directe + sa propre inscription  (FIX A-1)
        employee    → uniquement ses propres inscriptions
    """
    enrollment = Enrollment.get_or_404(enrollment_id)
    role_name = current_user.role.name if current_user.role else "employee"

    if role_name not in ("admin", "rh"):
        if current_user.employee is None:
            abort(403)
        own_id = current_user.employee.id
        if role_name == "manager":
            # Autorisé si membre de l'équipe OU inscription propre (FIX A-1)
            if not _is_team_member(enrollment.employee_id, own_id) \
                    and enrollment.employee_id != own_id:
                abort(403, description="Cet employé n'est pas membre de votre équipe.")
        else:
            if enrollment.employee_id != own_id:
                abort(403, description="Vous ne pouvez modifier que vos propres inscriptions.")

    form = EnrollmentStatusForm()
    if not form.validate_on_submit():
        errors = "; ".join(
            f"{f}: {', '.join(errs)}" for f, errs in form.errors.items()
        )
        flash(f"Formulaire invalide : {errors}", "danger")
        return redirect(request.referrer or url_for("training.my_trainings"))

    data = {
        "status":        form.status.data,
        "start_date":    form.start_date.data,
        "end_date":      form.end_date.data,
        "score":         float(form.score.data) if form.score.data is not None else None,
        "final_comment": form.final_comment.data or None,
    }

    try:
        update_enrollment_status(enrollment_id, data)
        flash("Statut de l'inscription mis à jour avec succès.", "success")
    except (BusinessRuleError, ValidationError) as exc:
        flash(str(exc), "danger")
    except NotFoundError as exc:
        flash(str(exc), "warning")

    referrer = request.referrer or ""
    if "/me" in referrer:
        return redirect(url_for("training.my_trainings"))
    if "/team" in referrer:
        return redirect(url_for("training.team_trainings"))
    return redirect(
        url_for("training.training_detail", training_id=enrollment.training_id)
    )
