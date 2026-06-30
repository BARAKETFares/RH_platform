"""
Factory pour créer des Employee de test.

Pré-requis : la fixture ``seed_org`` doit avoir tourné pour que
Company / Department / Position existent en DB.

Deux interfaces disponibles :

1. Fonction utilitaire ``make_employee()`` — simple, sans Factory Boy.
2. Classe ``EmployeeFactory``              — Factory Boy.

Exemple d'utilisation dans un test :

    from tests.fixtures.employees import make_employee

    def test_employee_actif(db_session, seed_org):
        emp = make_employee(seed_org)
        db_session.flush()
        assert emp.status == "active"
        assert emp.company_id == seed_org["company_id"]
"""
from __future__ import annotations

import uuid as _uuid_module
from datetime import date

import factory
from faker import Faker

from app.extensions import db
from app.models.employee import Employee

_faker = Faker("fr_FR")


# =============================================================================
# Fonction utilitaire
# =============================================================================

def make_employee(
    org: dict[str, int],
    *,
    first_name: str | None = None,
    last_name: str | None = None,
    hire_date: date | None = None,
    status: str = Employee.STATUS_ACTIVE,
    user_id: int | None = None,
    position_id: int | None = None,
) -> Employee:
    """
    Crée et ajoute un Employee à la session courante (flush, pas commit).

    Args:
        org: dict issu de la fixture ``seed_org`` :
             ``{"company_id": int, "dept_id": int, "pos_id": int}``
        first_name: prénom ; généré par Faker si None.
        last_name:  nom    ; généré par Faker si None.
        hire_date:  date d'embauche ; aujourd'hui si None.
        status:     statut RH (défaut : "active").
        user_id:    lien vers un User (optionnel).
        position_id: écrase ``org["pos_id"]`` si fourni.

    Returns:
        Instance ``Employee`` avec ``id`` populé par le flush.
    """
    emp = Employee(
        company_id=org["company_id"],
        department_id=org["dept_id"],
        position_id=position_id if position_id is not None else org.get("pos_id"),
        user_id=user_id,
        first_name=first_name or _faker.first_name(),
        last_name=last_name  or _faker.last_name(),
        hire_date=hire_date  or date.today(),
        status=status,
    )
    db.session.add(emp)
    db.session.flush()
    return emp


# =============================================================================
# Factory Boy
# =============================================================================

class EmployeeFactory(factory.Factory):
    """
    Factory Factory Boy pour créer des Employee de test.

    Délègue à ``make_employee()`` pour le flush SQLAlchemy.
    ``org`` (dict issu de seed_org) est obligatoire et intercepté dans _create.

    Usage :
        emp = EmployeeFactory(org=seed_org)
        emp = EmployeeFactory(org=seed_org, status="probation")
        emp = EmployeeFactory(org=seed_org, first_name="Alice", last_name="Dupont")
    """

    class Meta:
        model = Employee
        # Pas d'exclude : _create intercepte tous les kwargs avant qu'ils
        # n'atteignent le constructeur du modèle.

    org        = factory.LazyFunction(dict)   # doit être passé explicitement
    first_name = factory.LazyFunction(_faker.first_name)
    last_name  = factory.LazyFunction(_faker.last_name)
    hire_date  = factory.LazyFunction(date.today)
    status     = Employee.STATUS_ACTIVE
    user_id    = None
    position_id = None

    @classmethod
    def _create(cls, model_class, *args, **kwargs):  # type: ignore[override]
        org         = kwargs.pop("org", {})
        first_name  = kwargs.pop("first_name", None)
        last_name   = kwargs.pop("last_name",  None)
        hire_date   = kwargs.pop("hire_date",  None)
        status      = kwargs.pop("status",     Employee.STATUS_ACTIVE)
        user_id     = kwargs.pop("user_id",    None)
        position_id = kwargs.pop("position_id", None)
        return make_employee(
            org,
            first_name=first_name,
            last_name=last_name,
            hire_date=hire_date,
            status=status,
            user_id=user_id,
            position_id=position_id,
        )

    @classmethod
    def _build(cls, model_class, *args, **kwargs):  # type: ignore[override]
        org = kwargs.pop("org", {})
        return Employee(
            company_id=org.get("company_id", 0),
            department_id=org.get("dept_id", 0),
            position_id=kwargs.pop("position_id", None) or org.get("pos_id"),
            user_id=kwargs.pop("user_id", None),
            first_name=kwargs.pop("first_name", None) or _faker.first_name(),
            last_name=kwargs.pop("last_name",  None) or _faker.last_name(),
            hire_date=kwargs.pop("hire_date",  None) or date.today(),
            status=kwargs.pop("status", Employee.STATUS_ACTIVE),
        )
