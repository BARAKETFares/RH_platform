"""
Tâche Celery — Accrual mensuel des congés

Calcule et crédite les jours de congés acquis pour tous les employés
éligibles de toutes les entreprises.

Planification (CELERY_BEAT_SCHEDULE) :
    "0 1 1 * *"  →  le 1er de chaque mois à 1h00 (Europe/Paris)

Période créditée :
    Le mois précédant la date d'exécution.
    Exemple : exécution le 2025-02-01 → crédite janvier 2025.

Règles d'acquisition :
    CP  (Congés Payés)   : 2,0833 j/mois (= 25 j / 12, norme légale française)
    RTT                  : 1,00   j/mois (convention d'entreprise courante)
    Autres types impactant un solde : 0 (crédités en lump-sum via initial_balance)

Éligibilité :
    Statuts actifs uniquement : active, probation, on_leave.
    Pro-rata automatique si l'employé a été embauché en cours du mois accrué.

Idempotence :
    Les appels manuels (year, month explicites) permettent de rejouer un mois
    précis. Le beat schedule garantit une exécution unique par mois ; re-jouer
    le même mois sans nécessité crédite une seconde fois.
"""
from __future__ import annotations

import calendar
import logging
from datetime import date
from typing import Optional

from sqlalchemy import select

from app.extensions import celery, db
from app.models.employee import Employee
from app.models.leave_balance import LeaveBalance
from app.models.leave_type import LeaveType
from app.models.organization import Company

logger = logging.getLogger(__name__)

# =============================================================================
# Taux d'acquisition mensuels par code de type d'absence
# =============================================================================

#: Jours crédités par mois pour un mois complet travaillé.
#: Les types absents de ce dict ne bénéficient pas d'acquisition mensuelle
#: (leurs droits sont attribués en une fois via LeaveBalance.initial_balance).
MONTHLY_ACCRUAL_RATES: dict[str, float] = {
    LeaveType.CODE_PAID_LEAVE: round(25 / 12, 4),  # ≈ 2.0833 j
    LeaveType.CODE_RTT:        1.0,                 # 1 RTT / mois
}

#: Statuts RH ouvrant droit à l'acquisition mensuelle.
ACCRUAL_ELIGIBLE_STATUSES: tuple[str, ...] = (
    Employee.STATUS_ACTIVE,
    Employee.STATUS_PROBATION,
    Employee.STATUS_ON_LEAVE,
)


# =============================================================================
# Tâche principale
# =============================================================================

@celery.task(
    bind=True,
    name="app.tasks.leave_tasks.accrue_monthly_leave",
    max_retries=3,
    default_retry_delay=300,   # 5 min entre les tentatives
)
def accrue_monthly_leave(
    self,
    *,
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> dict:
    """
    Crédite les jours de congés acquis pour la période indiquée.

    Args:
        year:  Année de la période à accruer (défaut : mois précédent).
        month: Mois de la période à accruer (1-12, défaut : mois précédent).

    Returns:
        Dictionnaire de résumé :
        {
            "period": "2025-01",
            "companies_processed": N,
            "employees_processed": N,
            "balances_updated": N,
            "errors": [{"employee_id": X, "error": "..."}],
        }
    """
    accrual_year, accrual_month = _resolve_period(year, month)
    period_label = f"{accrual_year}-{accrual_month:02d}"

    logger.info("Démarrage accrual mensuel — période %s", period_label)

    companies = db.session.execute(
        select(Company).order_by(Company.id)
    ).scalars().all()

    summary = {
        "period":               period_label,
        "companies_processed":  0,
        "employees_processed":  0,
        "balances_updated":     0,
        "errors":               [],
    }

    for company in companies:
        try:
            result = _accrue_for_company(company, accrual_year, accrual_month)
            summary["employees_processed"] += result["employees"]
            summary["balances_updated"]    += result["balances"]
            summary["companies_processed"] += 1
        except Exception as exc:
            logger.error(
                "Erreur accrual pour la société %s : %s",
                company.id, exc, exc_info=True,
            )
            summary["errors"].append({"company_id": company.id, "error": str(exc)})

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.critical("Échec du commit global accrual %s : %s", period_label, exc)
        raise self.retry(exc=exc)

    logger.info(
        "Accrual mensuel terminé — période %s | sociétés=%d | employés=%d | soldes=%d | erreurs=%d",
        period_label,
        summary["companies_processed"],
        summary["employees_processed"],
        summary["balances_updated"],
        len(summary["errors"]),
    )
    return summary


# =============================================================================
# Helpers
# =============================================================================

def _resolve_period(year: Optional[int], month: Optional[int]) -> tuple[int, int]:
    """
    Retourne (year, month) de la période à accruer.
    Si non fournis, utilise le mois calendaire précédant la date d'exécution.
    """
    if year is not None and month is not None:
        if not (1 <= month <= 12):
            raise ValueError(f"Mois invalide : {month}. Doit être compris entre 1 et 12.")
        if not (2000 <= year <= 2100):
            raise ValueError(f"Année invalide : {year}.")
        return year, month

    today = date.today()
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


def _accrue_for_company(company: Company, accrual_year: int, accrual_month: int) -> dict:
    """
    Crédite les jours acquis pour tous les employés éligibles d'une entreprise.

    Returns:
        {"employees": N, "balances": N}
    """
    # Types d'absence actifs avec impact sur le solde
    leave_types = db.session.execute(
        LeaveType.balance_impacting_in_company(company.id)
    ).scalars().all()

    if not leave_types:
        return {"employees": 0, "balances": 0}

    # Employés éligibles de l'entreprise
    employees = db.session.execute(
        select(Employee).where(
            Employee.company_id == company.id,
            Employee.status.in_(ACCRUAL_ELIGIBLE_STATUSES),
        ).order_by(Employee.id)
    ).scalars().all()

    balances_updated = 0

    for employee in employees:
        for leave_type in leave_types:
            days = _compute_accrual_days(
                MONTHLY_ACCRUAL_RATES.get(leave_type.code, 0.0),
                employee,
                accrual_year,
                accrual_month,
            )
            if days <= 0:
                continue

            balance = LeaveBalance.get_or_create(
                employee.id,
                leave_type.id,
                accrual_year,           # solde de l'année en cours
            )
            balance.acquired = float(balance.acquired) + days
            balances_updated += 1

            logger.debug(
                "Accrual employee=%d type=%s période=%d-%02d : +%.4f j (acquired=%.4f)",
                employee.id,
                leave_type.code,
                accrual_year,
                accrual_month,
                days,
                float(balance.acquired),
            )

    return {"employees": len(employees), "balances": balances_updated}


def _compute_accrual_days(
    base_rate: float,
    employee: Employee,
    accrual_year: int,
    accrual_month: int,
) -> float:
    """
    Calcule les jours acquis pour un employé sur un mois donné.

    Applique un pro-rata si l'employé a été embauché en cours de mois,
    en divisant les jours calendaires effectivement travaillés par le
    nombre total de jours du mois.

    Returns:
        0.0 si l'employé n'était pas encore en poste ce mois-ci.
        Montant arrondi à 4 décimales sinon.
    """
    if base_rate <= 0:
        return 0.0

    last_day_num = calendar.monthrange(accrual_year, accrual_month)[1]
    period_start = date(accrual_year, accrual_month, 1)
    period_end   = date(accrual_year, accrual_month, last_day_num)

    # Employé pas encore embauché ce mois-ci
    if employee.hire_date > period_end:
        return 0.0

    # Mois complet : embauché avant ou le 1er du mois
    if employee.hire_date <= period_start:
        return round(base_rate, 4)

    # Pro-rata : embauché en cours de mois
    days_in_company = (period_end - employee.hire_date).days + 1
    prorata = base_rate * days_in_company / last_day_num
    return round(prorata, 4)
