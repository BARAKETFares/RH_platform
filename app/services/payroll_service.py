"""
Service : Payroll (Paie)

Logique métier de génération et de gestion des bulletins de paie.

Règles d'architecture :
  - Aucun objet `request` Flask ici.
  - Les erreurs métier sont des exceptions (app.utils.exceptions).
  - Les commits SQLAlchemy sont faits dans ce service.
  - calculate_net_from_gross() applique des taux de cotisations fixes
    (barème simplifié 2024 — pas de moteur de paie réel, pas de plafond
    de la Sécurité sociale, pas de tranches de retraite complémentaire).

Workflow d'un bulletin :
    generate_payslip()  → status=draft
    validate_payslip()  → status=validated
    pay_payslip()       → status=paid
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import select

from app.extensions import db
from app.models.contract import Contract
from app.models.employee import Employee
from app.models.payroll import PayElement, PaySlip
from app.utils.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Barème de cotisations sociales (simplifié, France 2024)
# =============================================================================

# Chaque entrée : (libellé, taux salarial %, taux patronal %)
# Les taux s'appliquent sur le salaire brut total (assiette = brut).
# Un moteur de paie réel appliquerait plafonds, tranches et assiettes spécifiques.

CONTRIBUTION_RATES: list[tuple[str, float, float]] = [
    # label                                 sal %   pat %
    ("Sécurité sociale – Maladie",          0.75,   7.00),
    ("Retraite plafonnée",                  6.90,   8.55),
    ("Retraite déplafonnée",                0.40,   1.90),
    ("Assurance chômage",                   2.40,   4.05),
    ("Retraite complémentaire Tr. A",       3.15,   4.72),
    ("Accidents du travail",                0.00,   1.50),
    ("Allocations familiales",              0.00,   3.45),
    ("CSG déductible",                      6.80,   0.00),
    ("CSG / CRDS non déductible",           3.40,   0.00),
]

# Taux globaux (pour référence rapide)
TOTAL_EMPLOYEE_RATE: float = sum(r[1] for r in CONTRIBUTION_RATES)
TOTAL_EMPLOYER_RATE: float = sum(r[2] for r in CONTRIBUTION_RATES)

_TWO_PLACES = Decimal("0.01")


def _round2(value: Decimal) -> Decimal:
    return value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


# =============================================================================
# calculate_net_from_gross
# =============================================================================

def calculate_net_from_gross(gross: Decimal) -> dict:
    """
    Calcule le salaire net et les cotisations à partir du brut mensuel.

    Logique simplifiée : chaque taux s'applique directement sur `gross`.
    Pas de plafond SS, pas de tranche, pas d'abattement CSG.

    Args:
        gross: Salaire brut mensuel (Decimal).

    Returns:
        dict avec les clés :
          gross_salary                 (Decimal)
          net_salary                   (Decimal)
          total_employee_contributions (Decimal)
          total_employer_contributions (Decimal)
          elements (list[dict]) — une entrée par ligne de CONTRIBUTION_RATES :
            { label, rate_employee, rate_employer,
              employee_amount, employer_amount }

    Raises:
        ValueError: si gross <= 0.
    """
    if gross <= 0:
        raise ValueError("Le salaire brut doit être strictement positif.")

    gross = _round2(gross)
    elements: list[dict] = []
    total_employee = Decimal("0.00")
    total_employer = Decimal("0.00")

    for label, rate_sal, rate_pat in CONTRIBUTION_RATES:
        rate_sal_d = Decimal(str(rate_sal))
        rate_pat_d = Decimal(str(rate_pat))

        emp_amount = _round2(gross * rate_sal_d / Decimal("100"))
        pat_amount = _round2(gross * rate_pat_d / Decimal("100"))

        total_employee += emp_amount
        total_employer += pat_amount

        elements.append({
            "label":           label,
            "rate_employee":   rate_sal,
            "rate_employer":   rate_pat,
            "employee_amount": emp_amount,
            "employer_amount": pat_amount,
        })

    net = _round2(gross - total_employee)

    return {
        "gross_salary":                  gross,
        "net_salary":                    net,
        "total_employee_contributions":  total_employee,
        "total_employer_contributions":  total_employer,
        "elements":                      elements,
    }


# =============================================================================
# generate_payslip
# =============================================================================

def generate_payslip(
    employee_id: int,
    period_year: int,
    period_month: int,
    gross_override: Optional[Decimal] = None,
    notes: Optional[str] = None,
) -> PaySlip:
    """
    Génère un bulletin de paie au statut `draft` pour la période donnée.

    Sources du salaire brut (par ordre de priorité) :
      1. `gross_override` si fourni (saisie manuelle).
      2. Le contrat actif (is_current=True) de l'employé.
      3. `Employee.annual_gross_salary / 12` si aucun contrat actif.

    Args:
        employee_id:    ID de l'employé.
        period_year:    Année de la période (ex. 2025).
        period_month:   Mois de la période (1–12).
        gross_override: Remplace le brut du contrat actif si fourni.
        notes:          Note libre attachée au bulletin.

    Returns:
        Le PaySlip créé au statut `draft`.

    Raises:
        NotFoundError:    employé introuvable.
        ConflictError:    un bulletin existe déjà pour cette période.
        BusinessRuleError: impossible de déterminer le salaire brut.
    """
    employee = db.session.get(Employee, employee_id)
    if employee is None:
        raise NotFoundError(f"Employé introuvable (id={employee_id}).")

    # ── Unicité de la période ─────────────────────────────────────────────────
    existing = db.session.execute(
        select(PaySlip).where(
            PaySlip.employee_id == employee_id,
            PaySlip.period_year == period_year,
            PaySlip.period_month == period_month,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(
            f"Un bulletin existe déjà pour {employee.full_name} "
            f"({period_month:02d}/{period_year}). "
            "Supprimez-le avant de le regénérer."
        )

    # ── Détermination du brut mensuel ─────────────────────────────────────────
    active_contract: Optional[Contract] = db.session.execute(
        select(Contract).where(
            Contract.employee_id == employee_id,
            Contract.is_current.is_(True),
        )
    ).scalar_one_or_none()

    if gross_override is not None:
        gross = _round2(gross_override)
        contract_id = active_contract.id if active_contract else None
    elif active_contract is not None:
        gross = _round2(Decimal(str(active_contract.gross_salary)))
        contract_id = active_contract.id
    elif employee.annual_gross_salary is not None:
        gross = _round2(employee.annual_gross_salary / Decimal("12"))
        contract_id = None
    else:
        raise BusinessRuleError(
            f"Impossible de générer le bulletin de {employee.full_name} : "
            "aucun contrat actif ni salaire annuel renseigné sur la fiche employé."
        )

    # ── Calcul cotisations ────────────────────────────────────────────────────
    calc = calculate_net_from_gross(gross)

    # ── Création du bulletin ──────────────────────────────────────────────────
    payslip = PaySlip(
        employee_id=employee_id,
        contract_id=contract_id,
        period_year=period_year,
        period_month=period_month,
        gross_salary=calc["gross_salary"],
        total_employee_contributions=calc["total_employee_contributions"],
        total_employer_contributions=calc["total_employer_contributions"],
        net_salary=calc["net_salary"],
        status=PaySlip.STATUS_DRAFT,
        notes=notes,
    )
    db.session.add(payslip)
    db.session.flush()  # obtient payslip.id avant d'ajouter les éléments

    # ── Lignes de cotisations ─────────────────────────────────────────────────
    for entry in calc["elements"]:
        if entry["employee_amount"] > 0:
            db.session.add(PayElement(
                payslip_id=payslip.id,
                element_type=PayElement.TYPE_CONTRIBUTION,
                label=entry["label"],
                is_employer=False,
                amount=entry["employee_amount"],
                rate=Decimal(str(entry["rate_employee"])),
                base_amount=gross,
            ))
        if entry["employer_amount"] > 0:
            db.session.add(PayElement(
                payslip_id=payslip.id,
                element_type=PayElement.TYPE_CONTRIBUTION,
                label=entry["label"],
                is_employer=True,
                amount=entry["employer_amount"],
                rate=Decimal(str(entry["rate_employer"])),
                base_amount=gross,
            ))

    db.session.commit()
    logger.info(
        "Bulletin généré : employee_id=%s période=%s-%02s net=%s",
        employee_id, period_year, period_month, calc["net_salary"],
    )
    return payslip


# =============================================================================
# validate_payslip
# =============================================================================

def validate_payslip(payslip_id: int) -> PaySlip:
    """
    Passe un bulletin de `draft` à `validated`.

    Raises:
        NotFoundError:    bulletin introuvable.
        BusinessRuleError: bulletin non draft.
    """
    payslip = db.session.get(PaySlip, payslip_id)
    if payslip is None:
        raise NotFoundError(f"Bulletin introuvable (id={payslip_id}).")

    if payslip.status != PaySlip.STATUS_DRAFT:
        raise BusinessRuleError(
            f"Le bulletin est au statut « {payslip.status_label} » "
            "et ne peut pas être validé (seul un bulletin 'draft' est validable)."
        )

    payslip.status = PaySlip.STATUS_VALIDATED
    payslip.validated_at = datetime.now(timezone.utc)
    db.session.commit()
    logger.info("Bulletin validé : id=%s", payslip_id)
    return payslip


# =============================================================================
# pay_payslip
# =============================================================================

def pay_payslip(
    payslip_id: int,
    payment_reference: Optional[str] = None,
) -> PaySlip:
    """
    Passe un bulletin de `validated` à `paid`.

    Args:
        payslip_id:        ID du bulletin.
        payment_reference: Référence du virement (optionnelle).

    Raises:
        NotFoundError:    bulletin introuvable.
        BusinessRuleError: bulletin non validé.
    """
    payslip = db.session.get(PaySlip, payslip_id)
    if payslip is None:
        raise NotFoundError(f"Bulletin introuvable (id={payslip_id}).")

    if payslip.status != PaySlip.STATUS_VALIDATED:
        raise BusinessRuleError(
            f"Le bulletin est au statut « {payslip.status_label} » "
            "et ne peut pas être marqué payé (seul un bulletin 'validated' est payable)."
        )

    payslip.status = PaySlip.STATUS_PAID
    payslip.paid_at = datetime.now(timezone.utc)
    if payment_reference:
        payslip.payment_reference = payment_reference
    db.session.commit()
    logger.info("Bulletin payé : id=%s ref=%s", payslip_id, payment_reference)
    return payslip


# =============================================================================
# get_payslip
# =============================================================================

def get_payslip(payslip_id: int) -> PaySlip:
    """
    Retourne un bulletin par son ID.

    Raises:
        NotFoundError: bulletin introuvable.
    """
    payslip = db.session.get(PaySlip, payslip_id)
    if payslip is None:
        raise NotFoundError(f"Bulletin introuvable (id={payslip_id}).")
    return payslip


# =============================================================================
# list_payslips
# =============================================================================

def list_payslips(
    employee_id: Optional[int] = None,
    company_id: Optional[int] = None,
    period_year: Optional[int] = None,
    period_month: Optional[int] = None,
    status: Optional[str] = None,
) -> list[PaySlip]:
    """
    Retourne la liste des bulletins filtrée selon les critères fournis.

    Args:
        employee_id:  Filtre sur l'employé.
        company_id:   Filtre sur l'entreprise (via jointure Employee).
        period_year:  Filtre sur l'année.
        period_month: Filtre sur le mois.
        status:       Filtre sur le statut ('draft', 'validated', 'paid').

    Returns:
        Liste de PaySlip, du plus récent au plus ancien.
    """
    query = select(PaySlip).order_by(
        PaySlip.period_year.desc(),
        PaySlip.period_month.desc(),
        PaySlip.employee_id,
    )

    if employee_id is not None:
        query = query.where(PaySlip.employee_id == employee_id)

    if company_id is not None:
        query = query.join(Employee, PaySlip.employee_id == Employee.id).where(
            Employee.company_id == company_id
        )

    if period_year is not None:
        query = query.where(PaySlip.period_year == period_year)

    if period_month is not None:
        query = query.where(PaySlip.period_month == period_month)

    if status is not None:
        if status not in PaySlip.STATUSES:
            raise BusinessRuleError(
                f"Statut de filtre invalide : '{status}'. "
                f"Valeurs acceptées : {PaySlip.STATUSES}"
            )
        query = query.where(PaySlip.status == status)

    return list(db.session.execute(query).scalars().all())


# =============================================================================
# add_pay_element
# =============================================================================

def add_pay_element(payslip_id: int, data: dict) -> PayElement:
    """
    Ajoute manuellement une ligne (prime, retenue) à un bulletin draft.

    Recalcule les totaux du bulletin (gross, net, contributions) en fonction
    du type et du sens de l'élément ajouté.

    Args:
        payslip_id: ID du bulletin (doit être au statut 'draft').
        data:       Dict validé par PayElementCreateSchema.

    Returns:
        Le PayElement créé.

    Raises:
        NotFoundError:    bulletin introuvable.
        BusinessRuleError: bulletin non draft.
    """
    payslip = db.session.get(PaySlip, payslip_id)
    if payslip is None:
        raise NotFoundError(f"Bulletin introuvable (id={payslip_id}).")

    if not payslip.is_editable:
        raise BusinessRuleError(
            f"Le bulletin est au statut « {payslip.status_label} » "
            "et n'accepte plus de modification (seul un bulletin 'draft' est modifiable)."
        )

    amount = _round2(Decimal(str(data["amount"])))
    rate = Decimal(str(data["rate"])) if data.get("rate") is not None else None
    base = _round2(Decimal(str(data["base_amount"]))) if data.get("base_amount") is not None else None

    element = PayElement(
        payslip_id=payslip_id,
        element_type=data["element_type"],
        label=data["label"],
        is_employer=data.get("is_employer", False),
        amount=amount,
        rate=rate,
        base_amount=base,
    )
    db.session.add(element)

    # ── Mise à jour des totaux du bulletin ────────────────────────────────────
    etype = element.element_type

    if etype == PayElement.TYPE_BONUS:
        payslip.gross_salary = _round2(payslip.gross_salary + amount)
        payslip.net_salary   = _round2(payslip.net_salary + amount)
    elif etype == PayElement.TYPE_DEDUCTION:
        payslip.net_salary = _round2(payslip.net_salary - amount)
    elif etype == PayElement.TYPE_CONTRIBUTION and not element.is_employer:
        payslip.total_employee_contributions = _round2(
            payslip.total_employee_contributions + amount
        )
        payslip.net_salary = _round2(payslip.net_salary - amount)
    elif etype == PayElement.TYPE_CONTRIBUTION and element.is_employer:
        payslip.total_employer_contributions = _round2(
            payslip.total_employer_contributions + amount
        )

    db.session.commit()
    return element
