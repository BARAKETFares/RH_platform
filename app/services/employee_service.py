"""
Service : Employee

Logique métier de gestion des employés, séparée des routes (testabilité).

Règles d'architecture :
  - Aucun objet `request` Flask ici.
  - Les erreurs métier sont des exceptions (app.utils.exceptions).
  - Les commits SQLAlchemy sont faits dans ce service.
  - delete_employee() effectue une suppression LOGIQUE (status=terminated),
    jamais physique — un dossier RH ne se supprime pas pour des raisons
    légales et d'audit.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from sqlalchemy import func, or_, select

from app.extensions import db
from app.models.department import Department
from app.models.employee import Employee
from app.models.position import Position
from app.utils.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.utils.pagination import PaginationResult, paginate

logger = logging.getLogger(__name__)


# =============================================================================
# create_employee
# =============================================================================

def create_employee(data: dict, created_by_id: Optional[int] = None) -> Employee:
    """
    Crée un nouvel employé.

    Args:
        data: Dictionnaire validé (cf. EmployeeCreateSchema) contenant
              au minimum company_id, first_name, last_name, hire_date.
        created_by_id: ID de l'utilisateur à l'origine de la création (audit).

    Returns:
        L'instance Employee créée et persistée.

    Raises:
        ValidationError: champs obligatoires manquants ou incohérents.
        NotFoundError:    department_id, position_id, site_id ou manager_id
                          référencé n'existe pas.
        ConflictError:    employee_number déjà utilisé.
    """
    _validate_required_fields(data)

    if data.get("employee_number"):
        _ensure_employee_number_unique(data["employee_number"])

    _validate_foreign_keys(
        department_id=data.get("department_id"),
        position_id=data.get("position_id"),
        site_id=data.get("site_id"),
        manager_id=data.get("manager_id"),
    )

    employee = Employee(
        company_id=data["company_id"],
        department_id=data.get("department_id"),
        position_id=data.get("position_id"),
        site_id=data.get("site_id"),
        manager_id=data.get("manager_id"),
        employee_number=data.get("employee_number"),
        first_name=data["first_name"],
        last_name=data["last_name"],
        maiden_name=data.get("maiden_name"),
        gender=data.get("gender"),
        birth_date=data.get("birth_date"),
        birth_place=data.get("birth_place"),
        nationality=data.get("nationality", "FR"),
        personal_email=data.get("personal_email"),
        personal_phone=data.get("personal_phone"),
        professional_phone=data.get("professional_phone"),
        address_line1=data.get("address_line1"),
        address_line2=data.get("address_line2"),
        city=data.get("city"),
        postal_code=data.get("postal_code"),
        country=data.get("country", "FR"),
        emergency_contact_name=data.get("emergency_contact_name"),
        emergency_contact_phone=data.get("emergency_contact_phone"),
        emergency_contact_relationship=data.get("emergency_contact_relationship"),
        hire_date=data["hire_date"],
        probation_end_date=data.get("probation_end_date"),
        annual_gross_salary=data.get("annual_gross_salary"),
        status=data.get("status", Employee.STATUS_ACTIVE),
        notes=data.get("notes"),
    )
    # national_id_number, iban, bic are hybrid_property setters that encrypt
    # before writing to the underlying _field column — they can't be passed to
    # the SQLAlchemy-generated __init__, so we set them after construction.
    if data.get("national_id_number"):
        employee.national_id_number = data["national_id_number"]
    if data.get("iban"):
        employee.iban = data["iban"]
    if data.get("bic"):
        employee.bic = data["bic"]

    db.session.add(employee)
    db.session.commit()

    logger.info(
        "Employé créé",
        extra={"employee_id": employee.id, "created_by": created_by_id},
    )
    return employee


# =============================================================================
# get_employee
# =============================================================================

def get_employee(employee_id: int) -> Employee:
    """
    Récupère un employé par son ID.

    Args:
        employee_id: ID interne de l'employé.

    Returns:
        L'instance Employee.

    Raises:
        NotFoundError: aucun employé avec cet ID.
    """
    employee = db.session.get(Employee, employee_id)
    if employee is None:
        raise NotFoundError(f"Employé introuvable (id={employee_id}).")
    return employee


def get_employee_by_uuid(employee_uuid: str) -> Employee:
    """Récupère un employé par son UUID public."""
    employee = Employee.get_by_uuid(employee_uuid)
    if employee is None:
        raise NotFoundError("Employé introuvable.")
    return employee


# =============================================================================
# list_employees
# =============================================================================

def list_employees(
    company_id: int,
    *,
    department_id: Optional[int] = None,
    position_id: Optional[int] = None,
    manager_id: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    page: Optional[int] = None,
    per_page: Optional[int] = None,
) -> PaginationResult:
    """
    Liste paginée des employés d'une entreprise, avec filtres optionnels.

    Args:
        company_id:    ID de l'entreprise (obligatoire — isolation multi-tenant).
        department_id: Filtre par département.
        position_id:   Filtre par poste.
        manager_id:    Filtre par manager (équipe directe).
        status:        Filtre par statut (active, on_leave, probation, ...).
        search:        Recherche textuelle sur nom/prénom/matricule/email.
        page, per_page: Paramètres de pagination (cf. app.utils.pagination).

    Returns:
        PaginationResult contenant les employés correspondants.

    Raises:
        ValidationError: valeur de `status` invalide.
    """
    if status is not None and status not in Employee.STATUSES:
        raise ValidationError(
            f"Statut de filtre invalide : '{status}'.",
            details={"allowed": list(Employee.STATUSES)},
        )

    query = select(Employee).where(Employee.company_id == company_id)

    if department_id is not None:
        query = query.where(Employee.department_id == department_id)
    if position_id is not None:
        query = query.where(Employee.position_id == position_id)
    if manager_id is not None:
        query = query.where(Employee.manager_id == manager_id)
    if status is not None:
        query = query.where(Employee.status == status)
    if search:
        term = f"%{search.strip().lower()}%"
        query = query.where(
            or_(
                func.lower(Employee.first_name).like(term),
                func.lower(Employee.last_name).like(term),
                func.lower(Employee.employee_number).like(term),
                func.lower(Employee.personal_email).like(term),
            )
        )

    query = query.order_by(Employee.last_name, Employee.first_name)

    return paginate(query, page=page, per_page=per_page)


# =============================================================================
# update_employee
# =============================================================================

def update_employee(
    employee_id: int,
    data: dict,
    updated_by_id: Optional[int] = None,
) -> Employee:
    """
    Met à jour un employé existant (mise à jour partielle — PATCH).

    Seuls les champs présents dans `data` sont modifiés.

    Args:
        employee_id:   ID de l'employé à modifier.
        data:           Dictionnaire validé (cf. EmployeeUpdateSchema).
        updated_by_id:  ID de l'utilisateur à l'origine de la modification (audit).

    Returns:
        L'instance Employee mise à jour.

    Raises:
        NotFoundError:   employé ou référence (department/position/site/manager) introuvable.
        ConflictError:    employee_number déjà utilisé par un autre employé.
        BusinessRuleError: manager_id pointe vers l'employé lui-même,
                            ou vers un de ses subordonnés (cycle hiérarchique).
    """
    employee = get_employee(employee_id)

    if "employee_number" in data and data["employee_number"] != employee.employee_number:
        if data["employee_number"]:
            _ensure_employee_number_unique(data["employee_number"], exclude_id=employee_id)

    if "manager_id" in data and data["manager_id"] is not None:
        _validate_manager_assignment(employee_id, data["manager_id"])

    _validate_foreign_keys(
        department_id=data.get("department_id"),
        position_id=data.get("position_id"),
        site_id=data.get("site_id"),
        manager_id=data.get("manager_id"),
    )

    _validate_date_coherence(employee, data)

    # Champs autorisés en mise à jour partielle
    updatable_fields = (
        "department_id", "position_id", "site_id", "manager_id",
        "employee_number",
        "first_name", "last_name", "maiden_name", "gender",
        "birth_date", "birth_place", "nationality", "national_id_number",
        "personal_email", "personal_phone", "professional_phone",
        "address_line1", "address_line2", "city", "postal_code", "country",
        "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relationship",
        "iban", "bic",
        "hire_date", "termination_date", "termination_reason", "probation_end_date",
        "annual_gross_salary", "status", "notes",
    )

    for field in updatable_fields:
        if field in data:
            setattr(employee, field, data[field])

    db.session.commit()

    logger.info(
        "Employé mis à jour",
        extra={"employee_id": employee.id, "updated_by": updated_by_id, "fields": list(data.keys())},
    )
    return employee


# =============================================================================
# delete_employee
# =============================================================================

def delete_employee(
    employee_id: int,
    *,
    termination_date: Optional[date] = None,
    termination_reason: Optional[str] = None,
    deleted_by_id: Optional[int] = None,
    hard_delete: bool = False,
) -> Employee:
    """
    Supprime un employé.

    Par défaut, effectue une suppression LOGIQUE : le statut passe à
    'terminated' et le dossier est conservé (obligation légale de
    conservation des données RH, traçabilité d'audit).

    Args:
        employee_id:         ID de l'employé à supprimer.
        termination_date:    Date de départ (défaut : aujourd'hui).
        termination_reason:  Motif du départ (optionnel).
        deleted_by_id:        ID de l'utilisateur à l'origine de l'action (audit).
        hard_delete:          Si True, supprime physiquement la ligne en base.
                              Réservé aux cas d'erreur de saisie (doublon créé
                              par erreur, jamais utilisé) — JAMAIS pour un
                              départ réel d'employé.

    Returns:
        L'instance Employee (statut 'terminated') si suppression logique,
        ou None si suppression physique.

    Raises:
        NotFoundError:    employé introuvable.
        BusinessRuleError: l'employé est manager d'un département ou
                           encadre des subordonnés (hard_delete uniquement).
    """
    employee = get_employee(employee_id)

    if hard_delete:
        return _hard_delete_employee(employee, deleted_by_id)

    return _soft_delete_employee(
        employee,
        termination_date=termination_date or date.today(),
        termination_reason=termination_reason,
        deleted_by_id=deleted_by_id,
    )


def _soft_delete_employee(
    employee: Employee,
    *,
    termination_date: date,
    termination_reason: Optional[str],
    deleted_by_id: Optional[int],
) -> Employee:
    """Suppression logique : marque l'employé comme parti (status=terminated)."""
    if employee.is_terminated:
        raise BusinessRuleError("Cet employé est déjà marqué comme parti.")

    try:
        employee.terminate(termination_date, termination_reason)
    except ValueError as exc:
        raise BusinessRuleError(str(exc)) from exc

    db.session.commit()

    logger.info(
        "Employé désactivé (départ)",
        extra={"employee_id": employee.id, "deleted_by": deleted_by_id},
    )
    return employee


def _hard_delete_employee(employee: Employee, deleted_by_id: Optional[int]) -> None:
    """
    Suppression physique — réservée aux erreurs de saisie.
    Refuse si l'employé est référencé comme manager ou a des subordonnés,
    afin de ne pas casser l'intégrité de l'organigramme.
    """
    if employee.subordinates.count() > 0:
        raise BusinessRuleError(
            "Impossible de supprimer définitivement cet employé : "
            "il encadre des subordonnés. Réassignez-les d'abord."
        )

    managed_departments = db.session.execute(
        select(func.count(Department.id)).where(Department.manager_id == employee.id)
    ).scalar_one()
    if managed_departments > 0:
        raise BusinessRuleError(
            "Impossible de supprimer définitivement cet employé : "
            "il est désigné comme manager d'un département."
        )

    employee_id = employee.id
    db.session.delete(employee)
    db.session.commit()

    logger.warning(
        "Employé supprimé définitivement",
        extra={"employee_id": employee_id, "deleted_by": deleted_by_id},
    )


# =============================================================================
# Helpers privés
# =============================================================================

def _validate_required_fields(data: dict) -> None:
    """Vérifie la présence des champs strictement obligatoires."""
    required = ("company_id", "first_name", "last_name", "hire_date")
    missing = [f for f in required if not data.get(f)]
    if missing:
        raise ValidationError(
            "Champs obligatoires manquants.",
            details={"missing_fields": missing},
        )
    if not data["first_name"].strip() or not data["last_name"].strip():
        raise ValidationError("Le prénom et le nom ne peuvent pas être vides.")


def _ensure_employee_number_unique(employee_number: str, exclude_id: Optional[int] = None) -> None:
    """Vérifie qu'aucun autre employé n'utilise déjà ce matricule."""
    query = select(Employee).where(Employee.employee_number == employee_number)
    if exclude_id is not None:
        query = query.where(Employee.id != exclude_id)
    existing = db.session.execute(query).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(
            f"Le matricule '{employee_number}' est déjà utilisé par un autre employé."
        )


def _validate_foreign_keys(
    *,
    department_id: Optional[int],
    position_id: Optional[int],
    site_id: Optional[int],
    manager_id: Optional[int],
) -> None:
    """Vérifie que toutes les références fournies existent en base."""
    if department_id is not None and db.session.get(Department, department_id) is None:
        raise NotFoundError(f"Département introuvable (id={department_id}).")

    if position_id is not None:
        position = db.session.get(Position, position_id)
        if position is None:
            raise NotFoundError(f"Poste introuvable (id={position_id}).")
        if department_id is not None and position.department_id != department_id:
            raise ValidationError(
                "Le poste sélectionné n'appartient pas au département indiqué."
            )

    if site_id is not None:
        from app.models.organization import Site
        if db.session.get(Site, site_id) is None:
            raise NotFoundError(f"Site introuvable (id={site_id}).")

    if manager_id is not None and db.session.get(Employee, manager_id) is None:
        raise NotFoundError(f"Manager introuvable (id={manager_id}).")


def _validate_manager_assignment(employee_id: int, manager_id: int) -> None:
    """
    Empêche les cycles hiérarchiques :
      - un employé ne peut pas être son propre manager
      - un employé ne peut pas avoir pour manager un de ses subordonnés
    """
    if employee_id == manager_id:
        raise BusinessRuleError("Un employé ne peut pas être son propre manager.")

    candidate_manager = db.session.get(Employee, manager_id)
    if candidate_manager is None:
        return  # Sera levé par _validate_foreign_keys

    # Le futur manager ne doit pas être un subordonné (direct ou indirect)
    # de l'employé concerné, sous peine de cycle dans l'organigramme.
    current = candidate_manager.manager
    while current is not None:
        if current.id == employee_id:
            raise BusinessRuleError(
                "Cette assignation créerait un cycle hiérarchique : "
                "le manager désigné est subordonné à cet employé."
            )
        current = current.manager


def _validate_date_coherence(employee: Employee, data: dict) -> None:
    """Vérifie la cohérence des dates en tenant compte des valeurs déjà en base."""
    hire_date = data.get("hire_date", employee.hire_date)
    termination_date = data.get("termination_date", employee.termination_date)
    probation_end_date = data.get("probation_end_date", employee.probation_end_date)

    if termination_date and hire_date and termination_date < hire_date:
        raise ValidationError(
            "La date de départ ne peut pas précéder la date d'embauche."
        )
    if probation_end_date and hire_date and probation_end_date < hire_date:
        raise ValidationError(
            "La fin de période d'essai ne peut pas précéder la date d'embauche."
        )