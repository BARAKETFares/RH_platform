"""
Routes SSR du module Leaves (Congés & Absences).

Toutes les routes retournent du HTML via Jinja2 ou des redirections.
Les routes JSON/JWT équivalentes sont dans app/api/v1/leaves.py.

Pages couvertes :
    GET  /leaves/                      → mes demandes d'absence
    GET  /leaves/new                    → formulaire de soumission
    POST /leaves/new                     → traitement de la soumission
    GET  /leaves/<id>                     → détail d'une demande
    POST /leaves/<id>/cancel                → annulation d'une demande
    GET  /leaves/approvals                   → file d'approbation (manager/RH)
    POST /leaves/<id>/decide                  → traitement d'une décision

Toutes les routes nécessitent une session authentifiée (Flask-Login).
La logique métier est entièrement déléguée à app.services.leave_service —
ce fichier ne fait que recevoir la requête, appeler le service, et
formater la réponse (rendu de template ou redirection + flash).
"""
from __future__ import annotations

import logging

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.employee import Employee
from app.models.leave_request import LeaveRequest
from app.services.leave_service import (
    adjust_balance,
    approve_leave,
    calculate_all_balances,
    create_leave_request,
    reject_leave,
)
from app.utils.decorators import require_permission, require_role
from app.utils.file_utils import save_upload
from app.utils.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.utils.pagination import paginate
from . import bp
from .forms import LeaveBalanceAdjustForm, LeaveCancelForm, LeaveDecisionForm, LeaveRequestForm

logger = logging.getLogger(__name__)


# =============================================================================
# Helpers
# =============================================================================

def _require_employee_profile() -> int:
    """
    Retourne l'employee_id de l'utilisateur connecté.
    Interrompt la requête (403) si aucun profil employé n'est associé
    au compte — un compte purement administratif sans fiche RH ne peut
    pas soumettre de demande d'absence.
    """
    if not current_user.employee:
        abort(403, description="Aucun profil employé associé à ce compte.")
    return current_user.employee.id


def _is_privileged() -> bool:
    """True si le rôle courant a accès aux demandes d'autres employés."""
    return current_user.role.name in ("admin", "rh", "manager")


def _ensure_can_view(leave_request: LeaveRequest) -> None:
    """Vérifie que l'utilisateur courant peut consulter cette demande, sinon 403."""
    if _is_privileged():
        return
    own_id = _require_employee_profile()
    if leave_request.employee_id != own_id:
        abort(403, description="Vous n'avez pas accès à cette demande.")


def _ensure_can_modify(leave_request: LeaveRequest) -> None:
    """Vérifie que l'utilisateur courant peut modifier/annuler cette demande, sinon 403."""
    if current_user.role.name in ("admin", "rh"):
        return
    own_id = _require_employee_profile()
    if leave_request.employee_id != own_id:
        abort(403, description="Vous ne pouvez agir que sur vos propres demandes.")


# =============================================================================
# GET /leaves/ — mes demandes d'absence
# =============================================================================

@bp.get("/")
@login_required
def my_requests():
    """
    Liste paginée des demandes d'absence de l'utilisateur connecté,
    accompagnée de ses soldes de congés de l'année en cours.
    """
    if not current_user.employee:
        flash(
            "Votre compte n'est pas encore lié à une fiche employé. "
            "Contactez un administrateur pour finaliser votre profil.",
            "warning",
        )
        return redirect(url_for("reporting.dashboard"))
    employee_id = current_user.employee.id

    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in LeaveRequest.STATUSES:
        flash(f"Filtre de statut invalide : '{status_filter}'.", "warning")
        status_filter = None

    query = db.select(LeaveRequest).where(LeaveRequest.employee_id == employee_id)
    if status_filter:
        query = query.where(LeaveRequest.status == status_filter)
    query = query.order_by(LeaveRequest.created_at.desc())

    pagination = paginate(query, page=request.args.get("page", type=int))

    try:
        balances = calculate_all_balances(employee_id, _current_year())
    except NotFoundError:
        balances = []

    return render_template(
        "leaves/my_requests.html",
        leave_requests=pagination.items,
        pagination=pagination,
        balances=balances,
        status_filter=status_filter,
        statuses=LeaveRequest.STATUSES,
    )


# =============================================================================
# GET/POST /leaves/new — soumission d'une nouvelle demande
# =============================================================================

@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_request():
    """
    Formulaire de soumission d'une nouvelle demande d'absence.
    Le SelectField des types d'absence est peuplé dynamiquement à partir
    de l'entreprise de l'employé connecté, avant validation du formulaire.
    """
    employee_id = _require_employee_profile()
    company_id = current_user.employee.company_id

    form = LeaveRequestForm()
    form.populate_leave_types(company_id)

    if form.validate_on_submit():
        document_path = None
        if form.document_file.data:
            try:
                document_path = save_upload(form.document_file.data, "leave_documents")
            except ValueError as exc:
                flash(str(exc), "error")
                return render_template("leaves/request_form.html", form=form)

        payload = {
            "employee_id": employee_id,
            "leave_type_id": form.leave_type_id.data,
            "start_date": form.start_date.data,
            "end_date": form.end_date.data,
            "start_half_day": form.start_half_day.data,
            "end_half_day": form.end_half_day.data,
            "employee_comment": form.employee_comment.data,
            "document_path": document_path,
            "is_emergency": form.is_emergency.data,
        }

        try:
            leave_request = create_leave_request(payload, created_by_id=current_user.id)
        except NotFoundError as exc:
            flash(str(exc), "error")
        except ConflictError as exc:
            flash(str(exc), "error")
        except BusinessRuleError as exc:
            flash(str(exc), "error")
        except ValidationError as exc:
            flash(str(exc), "error")
        else:
            flash("Votre demande d'absence a été soumise avec succès.", "success")
            return redirect(url_for("leaves.detail", leave_id=leave_request.id))

    return render_template("leaves/request_form.html", form=form)


# =============================================================================
# GET /leaves/<id> — détail d'une demande
# =============================================================================

@bp.get("/<int:leave_id>")
@login_required
def detail(leave_id: int):
    """Détail d'une demande d'absence, avec actions contextuelles selon le rôle."""
    leave_request = db.session.get(LeaveRequest, leave_id)
    if leave_request is None:
        abort(404, description="Demande d'absence introuvable.")

    _ensure_can_view(leave_request)

    can_modify = False
    try:
        _ensure_can_modify(leave_request)
        can_modify = leave_request.is_cancellable
    except Exception:
        can_modify = False

    can_decide = (
        _is_privileged()
        and leave_request.is_pending
        and _can_decide_on(leave_request)
    )

    cancel_form = LeaveCancelForm()
    decision_form = LeaveDecisionForm()

    return render_template(
        "leaves/detail.html",
        leave_request=leave_request,
        can_modify=can_modify,
        can_decide=can_decide,
        cancel_form=cancel_form,
        decision_form=decision_form,
    )


def _can_decide_on(leave_request: LeaveRequest) -> bool:
    """
    Détermine si l'utilisateur courant peut se prononcer sur cette demande
    à l'étape actuelle de son workflow.
        - manager : uniquement si status == pending_manager
        - rh/admin : uniquement si status == pending_hr (ou pending_manager
          en cas d'intervention directe, autorisée pour ces rôles)
    """
    role = current_user.role.name
    if role == "manager":
        return leave_request.status == LeaveRequest.STATUS_PENDING_MANAGER
    if role in ("rh", "admin"):
        return leave_request.status in (
            LeaveRequest.STATUS_PENDING_MANAGER,
            LeaveRequest.STATUS_PENDING_HR,
        )
    return False


# =============================================================================
# POST /leaves/<id>/cancel — annulation
# =============================================================================

@bp.post("/<int:leave_id>/cancel")
@login_required
def cancel_request(leave_id: int):
    """Annule une demande d'absence et libère le solde réservé/consommé."""
    leave_request = db.session.get(LeaveRequest, leave_id)
    if leave_request is None:
        abort(404, description="Demande d'absence introuvable.")

    _ensure_can_modify(leave_request)

    form = LeaveCancelForm()
    if not form.validate_on_submit():
        flash("Erreur de validation du formulaire d'annulation.", "error")
        return redirect(url_for("leaves.detail", leave_id=leave_id))

    was_approved = leave_request.status == LeaveRequest.STATUS_APPROVED
    impacts_balance = (
        leave_request.leave_type.impacts_leave_balance if leave_request.leave_type else False
    )

    try:
        leave_request.cancel(reason=form.reason.data or None)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("leaves.detail", leave_id=leave_id))

    if impacts_balance and leave_request.working_days is not None:
        from app.models.leave_balance import LeaveBalance
        balance = LeaveBalance.get_for_employee(
            leave_request.employee_id,
            leave_request.leave_type_id,
            leave_request.start_date.year,
        )
        if balance is not None:
            if was_approved:
                balance.restore(float(leave_request.working_days))
            else:
                balance.release_reservation(float(leave_request.working_days))

    db.session.commit()
    flash("La demande a été annulée.", "info")
    return redirect(url_for("leaves.detail", leave_id=leave_id))


# =============================================================================
# GET /leaves/approvals — file d'approbation (manager / RH)
# =============================================================================

@bp.get("/approvals")
@login_required
@require_role("manager", "rh", "admin")
def approvals():
    """
    File des demandes en attente d'action pour le rôle courant.
        - manager : demandes de son équipe directe (manager_id = son employee_id)
        - rh/admin : toutes les demandes en attente de validation RH
    """
    role = current_user.role.name

    if role == "manager":
        own_id = _require_employee_profile()
        query = db.select(LeaveRequest).where(
            LeaveRequest.manager_id == own_id,
            LeaveRequest.status == LeaveRequest.STATUS_PENDING_MANAGER,
        )
    else:  # rh, admin
        query = db.select(LeaveRequest).where(
            LeaveRequest.status.in_(
                (LeaveRequest.STATUS_PENDING_MANAGER, LeaveRequest.STATUS_PENDING_HR)
            )
        )

    query = query.order_by(LeaveRequest.created_at.asc())
    pagination = paginate(query, page=request.args.get("page", type=int))

    return render_template(
        "leaves/approvals.html",
        leave_requests=pagination.items,
        pagination=pagination,
    )


# =============================================================================
# POST /leaves/<id>/decide — approbation ou refus
# =============================================================================

@bp.post("/<int:leave_id>/decide")
@login_required
@require_role("manager", "rh", "admin")
def decide(leave_id: int):
    """
    Traite une décision d'approbation ou de refus soumise depuis le
    détail d'une demande ou la file d'approbation.
    """
    leave_request = db.session.get(LeaveRequest, leave_id)
    if leave_request is None:
        abort(404, description="Demande d'absence introuvable.")

    if not _can_decide_on(leave_request):
        flash("Cette demande n'est plus à votre niveau d'approbation.", "warning")
        return redirect(url_for("leaves.detail", leave_id=leave_id))

    form = LeaveDecisionForm()
    if not form.validate_on_submit():
        flash("Erreur de validation du formulaire de décision.", "error")
        return redirect(url_for("leaves.detail", leave_id=leave_id))

    role = current_user.role.name
    approver_role = "manager" if role == "manager" else "hr"
    approver_id = _require_employee_profile() if approver_role == "manager" else current_user.id

    try:
        if form.decision.data == "approve":
            approve_leave(
                leave_id,
                approver_id,
                approver_role=approver_role,
                comment=form.comment.data or None,
                requires_hr_validation=form.requires_hr_validation.data,
            )
            flash("La demande a été approuvée.", "success")
        else:
            reject_leave(
                leave_id,
                approver_id,
                approver_role=approver_role,
                comment=form.comment.data or "",
            )
            flash("La demande a été refusée.", "info")
    except NotFoundError as exc:
        flash(str(exc), "error")
    except (BusinessRuleError, ValidationError) as exc:
        flash(str(exc), "error")

    return redirect(url_for("leaves.detail", leave_id=leave_id))


# =============================================================================
# GET/POST /leaves/employee/<employee_id>/balance — régularisation RH/Admin
# =============================================================================

@bp.route("/employee/<int:employee_id>/balance", methods=["GET", "POST"])
@login_required
@require_permission("leaves.adjust")
def adjust_balance_route(employee_id: int):
    """
    Affiche les soldes de congés d'un employé (année en cours) et permet
    à RH/Admin d'appliquer une régularisation manuelle via adjust_balance().
    """
    employee = db.session.get(Employee, employee_id)
    if employee is None:
        abort(404, description="Employé introuvable.")

    year = _current_year()

    form = LeaveBalanceAdjustForm()
    form.populate_leave_types(employee.company_id)

    if form.validate_on_submit():
        try:
            adjust_balance(
                employee_id=employee_id,
                leave_type_id=form.leave_type_id.data,
                year=year,
                days=float(form.days.data),
                reason=form.reason.data,
                adjusted_by_id=current_user.id,
            )
        except NotFoundError as exc:
            flash(str(exc), "error")
        except ValidationError as exc:
            flash(str(exc), "error")
        else:
            flash(f"Solde ajusté avec succès pour {employee.full_name}.", "success")
            return redirect(url_for("leaves.adjust_balance_route", employee_id=employee_id))

    balances = calculate_all_balances(employee_id, year)

    return render_template(
        "leaves/adjust_balance.html",
        employee=employee,
        balances=balances,
        form=form,
        year=year,
    )


# =============================================================================
# Helper interne
# =============================================================================

def _current_year() -> int:
    from datetime import date
    return date.today().year