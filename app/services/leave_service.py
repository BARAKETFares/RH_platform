"""
Service : Leave (Congés & Absences)

Logique métier de gestion des demandes d'absence et des soldes de congés.

Règles d'architecture :
  - Aucun objet `request` Flask ici.
  - Les erreurs métier sont des exceptions (app.utils.exceptions).
  - Les commits SQLAlchemy sont faits dans ce service.
  - Le calcul des jours ouvrés exclut week-ends et jours fériés (via
    PublicHoliday si le modèle existe, sinon fallback week-ends seuls).
  - Toute transition de statut sur LeaveRequest est répercutée immédiatement
    sur le LeaveBalance correspondant (réservation / consommation / libération).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select

from app.extensions import db
from app.models.employee import Employee
from app.models.leave_balance import LeaveBalance
from app.models.leave_request import LeaveRequest
from app.models.leave_type import LeaveType
from app.utils.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ValidationError,
)

logger = logging.getLogger(__name__)


# =============================================================================
# create_leave_request
# =============================================================================

def create_leave_request(data: dict, created_by_id: Optional[int] = None) -> LeaveRequest:
    """
    Crée et soumet une nouvelle demande d'absence.

    Pipeline de validation :
        1. Existence de l'employé et du type d'absence.
        2. Cohérence des dates (fin >= début, pas dans le passé).
        3. Détection de chevauchement avec une demande active existante.
        4. Calcul des jours ouvrés de la période.
        5. Respect des règles du LeaveType (durée max, délai de prévenance,
           justificatif obligatoire).
        6. Vérification du solde disponible (si impacts_leave_balance=True).
        7. Réservation du solde (passage en `pending`) et soumission
           (statut → pending_manager).

    Args:
        data: dict validé (cf. LeaveRequestCreateSchema) contenant au minimum
              employee_id, leave_type_id, start_date, end_date.
        created_by_id: ID de l'utilisateur à l'origine de la création (audit).

    Returns:
        L'instance LeaveRequest créée, au statut 'pending_manager'.

    Raises:
        NotFoundError:     employee_id ou leave_type_id introuvable.
        ValidationError:   dates incohérentes, ou règle du LeaveType violée
                            (durée max, délai de prévenance, justificatif manquant).
        ConflictError:      chevauchement avec une demande active existante.
        BusinessRuleError:  solde insuffisant pour ce type d'absence.
    """
    employee = db.session.get(Employee, data["employee_id"])
    if employee is None:
        raise NotFoundError(f"Employé introuvable (id={data['employee_id']}).")

    leave_type = db.session.get(LeaveType, data["leave_type_id"])
    if leave_type is None:
        raise NotFoundError(f"Type d'absence introuvable (id={data['leave_type_id']}).")

    start_date: date = data["start_date"]
    end_date: date = data["end_date"]
    start_half_day = data.get("start_half_day", False)
    end_half_day = data.get("end_half_day", False)

    if end_date < start_date:
        raise ValidationError("La date de fin ne peut pas précéder la date de début.")

    if start_date < date.today() and not data.get("is_emergency", False):
        raise ValidationError(
            "La date de début ne peut pas être antérieure à aujourd'hui.",
        )

    # ── Détection de chevauchement ────────────────────────────────────────────
    overlap_query = LeaveRequest.overlapping_for_employee(employee.id, start_date, end_date)
    if db.session.execute(overlap_query).first() is not None:
        raise ConflictError(
            "Cette période chevauche une demande d'absence déjà existante."
        )

    # ── Calcul des jours ouvrés ────────────────────────────────────────────────
    working_days = _calculate_working_days(
        employee.company_id, start_date, end_date, start_half_day, end_half_day
    )

    # ── Règles métier du LeaveType ─────────────────────────────────────────────
    duration_error = leave_type.validate_duration(working_days)
    if duration_error:
        raise ValidationError(duration_error)

    if not data.get("is_emergency", False):
        days_until_start = (start_date - date.today()).days
        notice_error = leave_type.validate_advance_notice(days_until_start)
        if notice_error:
            raise ValidationError(notice_error)

    if leave_type.requires_document and not data.get("document_path"):
        raise ValidationError(
            f"Un justificatif est obligatoire pour le type d'absence '{leave_type.name}'."
        )

    if leave_type.requires_justification and not (data.get("employee_comment") or "").strip():
        raise ValidationError(
            f"Un motif est obligatoire pour le type d'absence '{leave_type.name}'."
        )

    # ── Vérification et réservation du solde ──────────────────────────────────
    balance: Optional[LeaveBalance] = None
    if leave_type.impacts_leave_balance:
        balance = LeaveBalance.get_or_create(employee.id, leave_type.id, start_date.year)
        if not balance.can_take(working_days):
            raise BusinessRuleError(
                f"Solde insuffisant : {balance.available:.1f} jour(s) disponible(s) "
                f"pour {working_days:.1f} jour(s) demandé(s)."
            )

    # ── Création de la demande ────────────────────────────────────────────────
    # manager_id est pré-rempli avec le responsable hiérarchique de l'employé
    # (Employee.manager_id), afin que la demande apparaisse dans la file
    # d'approbation du bon manager dès sa soumission. Ce champ sera ensuite
    # mis à jour avec l'identité réelle de l'approbateur au moment de la
    # décision (cf. approve_by_manager / reject_by_manager).
    leave_request = LeaveRequest(
        employee_id=employee.id,
        leave_type_id=leave_type.id,
        start_date=start_date,
        end_date=end_date,
        start_half_day=start_half_day,
        end_half_day=end_half_day,
        working_days=working_days,
        employee_comment=data.get("employee_comment"),
        document_path=data.get("document_path"),
        is_emergency=data.get("is_emergency", False),
        status=LeaveRequest.STATUS_DRAFT,
        manager_id=employee.manager_id,
    )
    db.session.add(leave_request)

    leave_request.submit()  # draft → pending_manager

    if balance is not None:
        balance.reserve(working_days)

    db.session.commit()

    logger.info(
        "Demande d'absence créée",
        extra={
            "leave_request_id": leave_request.id,
            "employee_id": employee.id,
            "working_days": working_days,
            "created_by": created_by_id,
        },
    )
    return leave_request


# =============================================================================
# approve_leave
# =============================================================================

def approve_leave(
    request_id: int,
    approver_id: int,
    *,
    approver_role: str,
    comment: Optional[str] = None,
    requires_hr_validation: bool = True,
) -> LeaveRequest:
    """
    Approuve une demande d'absence, au niveau manager ou RH selon le rôle.

    Args:
        request_id:              ID de la demande à approuver.
        approver_id:               ID de l'approbateur (Employee.id si manager,
                                   User.id si RH/Admin).
        approver_role:              'manager' ou 'hr' — détermine quelle étape
                                    du workflow est traitée.
        comment:                    Commentaire optionnel de l'approbateur.
        requires_hr_validation:      Si True et approver_role='manager', la
                                    demande passe en 'pending_hr' plutôt qu'en
                                    'approved' directement. Ignoré si approver_role='hr'.

    Returns:
        L'instance LeaveRequest mise à jour.

    Raises:
        NotFoundError:      demande introuvable.
        ValidationError:    approver_role invalide.
        BusinessRuleError:  transition impossible depuis le statut actuel
                            (ex : demande déjà traitée).
    """
    if approver_role not in ("manager", "hr"):
        raise ValidationError(f"Rôle d'approbateur invalide : '{approver_role}'.")

    leave_request = db.session.get(LeaveRequest, request_id)
    if leave_request is None:
        raise NotFoundError(f"Demande d'absence introuvable (id={request_id}).")

    try:
        if approver_role == "manager":
            leave_request.approve_by_manager(
                approver_id, comment=comment, requires_hr_validation=requires_hr_validation
            )
        else:
            leave_request.approve_by_hr(approver_id, comment=comment)
    except ValueError as exc:
        raise BusinessRuleError(str(exc)) from exc

    # Si la demande atteint le statut final 'approved', on consomme le solde
    if leave_request.status == LeaveRequest.STATUS_APPROVED:
        _consume_balance_on_final_approval(leave_request)

    db.session.commit()

    logger.info(
        "Demande d'absence approuvée",
        extra={
            "leave_request_id": leave_request.id,
            "approver_id": approver_id,
            "approver_role": approver_role,
            "new_status": leave_request.status,
        },
    )
    return leave_request


# =============================================================================
# reject_leave
# =============================================================================

def reject_leave(
    request_id: int,
    approver_id: int,
    *,
    approver_role: str,
    comment: str,
) -> LeaveRequest:
    """
    Rejette une demande d'absence, au niveau manager ou RH selon le rôle.
    Libère systématiquement le solde réservé (`pending`) lors du rejet.

    Args:
        request_id:      ID de la demande à rejeter.
        approver_id:       ID de l'approbateur (Employee.id si manager, User.id si RH).
        approver_role:      'manager' ou 'hr'.
        comment:             Motif du refus — obligatoire.

    Returns:
        L'instance LeaveRequest mise à jour (statut 'rejected').

    Raises:
        NotFoundError:      demande introuvable.
        ValidationError:    approver_role invalide, ou motif absent/vide.
        BusinessRuleError:  transition impossible depuis le statut actuel.
    """
    if approver_role not in ("manager", "hr"):
        raise ValidationError(f"Rôle d'approbateur invalide : '{approver_role}'.")

    if not (comment or "").strip():
        raise ValidationError("Un motif est obligatoire en cas de refus.")

    leave_request = db.session.get(LeaveRequest, request_id)
    if leave_request is None:
        raise NotFoundError(f"Demande d'absence introuvable (id={request_id}).")

    try:
        if approver_role == "manager":
            leave_request.reject_by_manager(approver_id, comment=comment)
        else:
            leave_request.reject_by_hr(approver_id, comment=comment)
    except ValueError as exc:
        raise BusinessRuleError(str(exc)) from exc

    _release_balance_reservation(leave_request)

    db.session.commit()

    logger.info(
        "Demande d'absence refusée",
        extra={
            "leave_request_id": leave_request.id,
            "approver_id": approver_id,
            "approver_role": approver_role,
        },
    )
    return leave_request


# =============================================================================
# calculate_balance
# =============================================================================

def calculate_balance(employee_id: int, leave_type_id: int, year: int) -> LeaveBalance:
    """
    Calcule (ou récupère) le solde de congés d'un employé pour un type et
    une année donnés. Crée l'enregistrement à zéro s'il n'existe pas encore.

    Cette fonction est le point d'entrée unique pour consulter un solde —
    elle garantit qu'un LeaveBalance existe toujours pour tout triplet
    (employee_id, leave_type_id, year) interrogé, évitant les erreurs
    "solde introuvable" côté UI.

    Args:
        employee_id:    ID de l'employé.
        leave_type_id:   ID du type d'absence.
        year:             Année civile concernée.

    Returns:
        L'instance LeaveBalance (existante ou nouvellement créée).

    Raises:
        NotFoundError:    employee_id ou leave_type_id introuvable.
        ValidationError:  année hors plage valide (2000-2100).
    """
    if not (2000 <= year <= 2100):
        raise ValidationError(f"Année invalide : {year}.")

    if db.session.get(Employee, employee_id) is None:
        raise NotFoundError(f"Employé introuvable (id={employee_id}).")

    if db.session.get(LeaveType, leave_type_id) is None:
        raise NotFoundError(f"Type d'absence introuvable (id={leave_type_id}).")

    balance = LeaveBalance.get_or_create(employee_id, leave_type_id, year)
    db.session.commit()

    return balance


def calculate_all_balances(employee_id: int, year: int) -> list[LeaveBalance]:
    """
    Calcule (ou récupère) les soldes d'un employé pour TOUS les types
    d'absence actifs impactant un solde, pour une année donnée.
    Utile pour afficher le dashboard "Mes congés" en une seule fonction.

    Args:
        employee_id: ID de l'employé.
        year:          Année civile concernée.

    Returns:
        Liste des LeaveBalance (un par LeaveType actif impactant un solde).

    Raises:
        NotFoundError: employee_id introuvable.
    """
    employee = db.session.get(Employee, employee_id)
    if employee is None:
        raise NotFoundError(f"Employé introuvable (id={employee_id}).")

    leave_types = db.session.execute(
        LeaveType.balance_impacting_in_company(employee.company_id)
    ).scalars().all()

    balances = [
        LeaveBalance.get_or_create(employee_id, lt.id, year) for lt in leave_types
    ]
    db.session.commit()

    return balances


def adjust_balance(
    employee_id: int,
    leave_type_id: int,
    year: int,
    days: float,
    reason: str,
    adjusted_by_id: Optional[int] = None,
) -> LeaveBalance:
    """
    Applique une régularisation manuelle (RH/Admin) sur un solde de congés.

    Args:
        employee_id:     ID de l'employé concerné.
        leave_type_id:    ID du type d'absence concerné.
        year:              Année civile concernée.
        days:               Delta à appliquer (positif ou négatif), non nul.
        reason:             Motif de la régularisation — obligatoire pour l'audit.
        adjusted_by_id:     ID de l'utilisateur RH/Admin à l'origine de l'action.

    Returns:
        L'instance LeaveBalance mise à jour.

    Raises:
        NotFoundError:    employee_id ou leave_type_id introuvable.
        ValidationError:  days == 0, ou motif vide.
    """
    if days == 0:
        raise ValidationError("Le delta d'ajustement ne peut pas être égal à zéro.")
    if not (reason or "").strip():
        raise ValidationError("Le motif de régularisation est obligatoire.")

    balance = calculate_balance(employee_id, leave_type_id, year)
    balance.apply_adjustment(days, reason=reason)
    db.session.commit()

    logger.info(
        "Ajustement manuel de solde",
        extra={
            "leave_balance_id": balance.id,
            "employee_id": employee_id,
            "days": days,
            "reason": reason,
            "adjusted_by": adjusted_by_id,
        },
    )
    return balance


# =============================================================================
# Helpers privés
# =============================================================================

def _calculate_working_days(
    company_id: int,
    start_date: date,
    end_date: date,
    start_half_day: bool,
    end_half_day: bool,
) -> float:
    """
    Calcule le nombre de jours ouvrés entre deux dates incluses, en excluant
    les week-ends et les jours fériés de l'entreprise (si PublicHoliday existe),
    puis ajuste pour les demi-journées de début/fin.
    """
    holidays = _get_company_holidays(company_id, start_date, end_date)

    working_days = 0
    current = start_date
    while current <= end_date:
        if current.weekday() < 5 and current not in holidays:  # 0-4 = lundi-vendredi
            working_days += 1
        current += timedelta(days=1)

    if working_days == 0:
        return 0.0

    if start_half_day and start_date.weekday() < 5 and start_date not in holidays:
        working_days -= 0.5
    if end_half_day and end_date != start_date and end_date.weekday() < 5 and end_date not in holidays:
        working_days -= 0.5

    return max(working_days, 0.5)


def _get_company_holidays(company_id: int, start_date: date, end_date: date) -> set[date]:
    """
    Récupère les jours fériés de l'entreprise sur la période, si le modèle
    PublicHoliday existe déjà dans le projet. Retourne un set vide sinon
    (fallback : seuls les week-ends sont exclus).
    """
    try:
        from app.models.calendar import PublicHoliday  # Import tardif — module optionnel
        rows = db.session.execute(
            select(PublicHoliday.holiday_date).where(
                PublicHoliday.company_id == company_id,
                PublicHoliday.holiday_date >= start_date,
                PublicHoliday.holiday_date <= end_date,
            )
        ).scalars().all()
        return set(rows)
    except ImportError:
        return set()


def _consume_balance_on_final_approval(leave_request: LeaveRequest) -> None:
    """
    Consomme le solde réservé lorsqu'une demande atteint le statut final
    'approved'. Ne fait rien si le type d'absence n'impacte pas de solde.
    """
    if not leave_request.leave_type.impacts_leave_balance:
        return
    if leave_request.working_days is None:
        return

    balance = LeaveBalance.get_or_create(
        leave_request.employee_id,
        leave_request.leave_type_id,
        leave_request.start_date.year,
    )
    balance.consume(float(leave_request.working_days), from_pending=True)


def _release_balance_reservation(leave_request: LeaveRequest) -> None:
    """
    Libère la réservation de solde (`pending`) lors d'un rejet.
    Ne fait rien si le type d'absence n'impacte pas de solde, ou si la
    demande n'avait pas encore réservé de solde (cas improbable mais
    défensif : working_days non calculé).
    """
    if not leave_request.leave_type.impacts_leave_balance:
        return
    if leave_request.working_days is None:
        return

    balance = LeaveBalance.get_for_employee(
        leave_request.employee_id,
        leave_request.leave_type_id,
        leave_request.start_date.year,
    )
    if balance is not None:
        balance.release_reservation(float(leave_request.working_days))