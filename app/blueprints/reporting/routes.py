"""
Routes SSR du module Reporting.

Route unique pour l'instant :
    GET /reporting/dashboard

Affiche les KPIs RH principaux : effectif total, demandes de congés en
attente, taux d'absentéisme du mois en cours. Les données sont calculées
directement ici (pas de report_service.py encore créé) — à extraire vers
un service dédié si la logique grandit au-delà de ces trois indicateurs.

Accessible à tous les rôles connectés ; le contenu affiché est filtré
selon le rôle (un employé standard ne voit pas les KPIs globaux de
l'entreprise, seulement ses propres informations résumées).
"""
from __future__ import annotations

from datetime import date

from flask import render_template
from flask_login import current_user, login_required
from sqlalchemy import func, select

from app.extensions import db
from app.models.employee import Employee
from app.models.leave_request import LeaveRequest
from . import bp


def _current_company_id() -> int | None:
    """Récupère l'entreprise de l'utilisateur connecté.

    Priorité :
    1. Fiche employé liée au compte (cas normal : employé / manager / RH).
    2. Première entreprise disponible en base (cas admin sans fiche employé).
    """
    if current_user.employee:
        return current_user.employee.company_id
    from app.models.organization import Company
    company = Company.get_default()
    return company.id if company else None


@bp.get("/dashboard")
@login_required
def dashboard():
    """
    Tableau de bord principal.

    Pour admin/rh : KPIs globaux de l'entreprise.
    Pour manager : KPIs limités à son équipe directe.
    Pour employee : résumé personnel uniquement (pas de KPIs agrégés).
    """
    role = current_user.role.name
    company_id = _current_company_id()

    context: dict = {
        "role": role,
        "show_company_kpis": role in ("admin", "rh"),
        "show_team_kpis": role == "manager",
    }

    employee = current_user.employee

    if role in ("admin", "rh"):
        # Admin sans fiche employé : on prend la première entreprise ou on agrège tout
        effective_company_id = company_id
        if effective_company_id is None:
            from app.models.organization import Company
            first = Company.get_default()
            effective_company_id = first.id if first else None
        if effective_company_id is not None:
            context.update(_company_wide_kpis(effective_company_id))
        else:
            context.update({
                "total_employees": 0,
                "pending_leaves": 0,
                "absenteeism_rate": 0.0,
                "status_breakdown": {},
            })
    elif role == "manager" and employee:
        context.update(_team_kpis(employee.id))
    elif role != "manager" and employee:
        context.update(_personal_kpis(employee.id))
    else:
        context.update({
            "total_employees": None,
            "pending_leaves": 0,
            "absenteeism_rate": None,
            "status_breakdown": {},
        })

    return render_template("dashboard/index.html", **context)


# =============================================================================
# Helpers de calcul des KPIs
# =============================================================================

def _company_wide_kpis(company_id: int) -> dict:
    """KPIs sur l'ensemble de l'entreprise — réservé admin/rh."""
    today = date.today()
    month_start = today.replace(day=1)

    # ── Effectif total (actifs + en congé + période d'essai) ─────────────────
    total_employees = db.session.execute(
        select(func.count(Employee.id)).where(
            Employee.company_id == company_id,
            Employee.status.in_((
                Employee.STATUS_ACTIVE,
                Employee.STATUS_ON_LEAVE,
                Employee.STATUS_PROBATION,
            )),
        )
    ).scalar_one()

    # ── Demandes de congés en attente (toute l'entreprise) ────────────────────
    pending_leaves = db.session.execute(
        select(func.count(LeaveRequest.id))
        .join(Employee, LeaveRequest.employee_id == Employee.id)
        .where(
            Employee.company_id == company_id,
            LeaveRequest.status.in_(LeaveRequest.PENDING_STATUSES),
        )
    ).scalar_one()

    # ── Taux d'absentéisme du mois (jours d'absence approuvés / effectif) ────
    absent_days_this_month = db.session.execute(
        select(func.coalesce(func.sum(LeaveRequest.working_days), 0))
        .join(Employee, LeaveRequest.employee_id == Employee.id)
        .where(
            Employee.company_id == company_id,
            LeaveRequest.status == LeaveRequest.STATUS_APPROVED,
            LeaveRequest.start_date >= month_start,
            LeaveRequest.start_date <= today,
        )
    ).scalar_one()

    absenteeism_rate = 0.0
    if total_employees > 0:
        # Approximation simple : jours d'absence / (effectif × jours ouvrés écoulés du mois)
        working_days_elapsed = max(1, sum(
            1 for d in range(1, today.day + 1)
            if date(today.year, today.month, d).weekday() < 5
        ))
        absenteeism_rate = round(
            (float(absent_days_this_month) / (total_employees * working_days_elapsed)) * 100, 1
        )

    # ── Répartition des employés par statut (pour le donut chart) ────────────
    status_breakdown = dict(db.session.execute(
        select(Employee.status, func.count(Employee.id))
        .where(Employee.company_id == company_id)
        .group_by(Employee.status)
    ).all())

    return {
        "total_employees": total_employees,
        "pending_leaves": pending_leaves,
        "absenteeism_rate": absenteeism_rate,
        "status_breakdown": status_breakdown,
    }


def _team_kpis(manager_employee_id: int) -> dict:
    """KPIs limités à l'équipe directe d'un manager."""
    team_size = db.session.execute(
        select(func.count(Employee.id)).where(
            Employee.manager_id == manager_employee_id,
            Employee.status.in_((Employee.STATUS_ACTIVE, Employee.STATUS_ON_LEAVE)),
        )
    ).scalar_one()

    pending_leaves = db.session.execute(
        select(func.count(LeaveRequest.id)).where(
            LeaveRequest.manager_id == manager_employee_id,
            LeaveRequest.status == LeaveRequest.STATUS_PENDING_MANAGER,
        )
    ).scalar_one()

    return {
        "total_employees": team_size,
        "pending_leaves": pending_leaves,
        "absenteeism_rate": None,
        "status_breakdown": {},
    }


def _personal_kpis(employee_id: int) -> dict:
    """Résumé personnel pour un employé standard (pas de KPIs agrégés)."""
    my_pending = db.session.execute(
        select(func.count(LeaveRequest.id)).where(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status.in_(LeaveRequest.PENDING_STATUSES),
        )
    ).scalar_one()

    return {
        "total_employees": None,
        "pending_leaves": my_pending,
        "absenteeism_rate": None,
        "status_breakdown": {},
    }