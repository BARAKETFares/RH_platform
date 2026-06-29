"""
Tests unitaires — employee_service

Couvre les règles métier des fonctions principales sans toucher
la base de données (db.session est mocké).
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, call, patch

import pytest

from app.utils.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ValidationError,
)


# =============================================================================
# Fixture : contexte Flask + db.session mocké
# =============================================================================

@pytest.fixture
def mock_db(app):
    """Contexte Flask + session SQLAlchemy entièrement mockée."""
    with app.app_context():
        with patch("app.services.employee_service.db") as m:
            m.session = MagicMock()
            # scalars chaîné pour list_employees
            m.session.execute.return_value.scalar_one_or_none.return_value = None
            m.session.execute.return_value.scalars.return_value.all.return_value = []
            yield m


def _make_employee(**kwargs):
    """Retourne un MagicMock simulant un Employee avec les valeurs par défaut."""
    emp = MagicMock()
    emp.id = kwargs.get("id", 1)
    emp.company_id = kwargs.get("company_id", 1)
    emp.employee_number = kwargs.get("employee_number", None)
    emp.hire_date = kwargs.get("hire_date", date(2020, 1, 1))
    emp.termination_date = kwargs.get("termination_date", None)
    emp.probation_end_date = kwargs.get("probation_end_date", None)
    emp.is_terminated = kwargs.get("is_terminated", False)
    emp.manager = kwargs.get("manager", None)
    emp.subordinates.count.return_value = kwargs.get("subordinates_count", 0)
    return emp


# =============================================================================
# create_employee
# =============================================================================

class TestCreateEmployee:

    def test_missing_company_id_raises(self, mock_db):
        from app.services.employee_service import create_employee
        with pytest.raises(ValidationError):
            create_employee({"first_name": "Alice", "last_name": "Smith", "hire_date": date.today()})

    def test_missing_first_name_raises(self, mock_db):
        from app.services.employee_service import create_employee
        with pytest.raises(ValidationError):
            create_employee({"company_id": 1, "last_name": "Smith", "hire_date": date.today()})

    def test_blank_first_name_raises(self, mock_db):
        from app.services.employee_service import create_employee
        with pytest.raises(ValidationError, match="prénom"):
            create_employee({"company_id": 1, "first_name": "  ", "last_name": "Smith", "hire_date": date.today()})

    def test_duplicate_employee_number_raises(self, mock_db):
        from app.services.employee_service import create_employee
        # simulate existing employee with same number
        mock_db.session.execute.return_value.scalar_one_or_none.return_value = _make_employee()
        with pytest.raises(ConflictError, match="matricule"):
            create_employee({
                "company_id": 1,
                "first_name": "Alice",
                "last_name": "Smith",
                "hire_date": date.today(),
                "employee_number": "EMP001",
            })

    def test_department_not_found_raises(self, mock_db):
        from app.services.employee_service import create_employee
        mock_db.session.execute.return_value.scalar_one_or_none.return_value = None  # no dup number
        mock_db.session.get.return_value = None  # department not found
        with pytest.raises(NotFoundError, match="[Dd]épartement"):
            create_employee({
                "company_id": 1,
                "first_name": "Alice",
                "last_name": "Smith",
                "hire_date": date.today(),
                "department_id": 99,
            })

    def test_manager_not_found_raises(self, mock_db):
        from app.services.employee_service import create_employee
        mock_db.session.execute.return_value.scalar_one_or_none.return_value = None
        mock_db.session.get.return_value = None  # manager not found
        with pytest.raises(NotFoundError, match="[Mm]anager"):
            create_employee({
                "company_id": 1,
                "first_name": "Alice",
                "last_name": "Smith",
                "hire_date": date.today(),
                "manager_id": 99,
            })

    def test_success_adds_and_commits(self, mock_db):
        from app.services.employee_service import create_employee
        # No FK refs → no db.session.get needed for FKs
        result = create_employee({
            "company_id": 1,
            "first_name": "Alice",
            "last_name": "Smith",
            "hire_date": date(2024, 1, 15),
        })
        mock_db.session.add.assert_called_once()
        mock_db.session.commit.assert_called_once()
        assert result.first_name == "Alice"
        assert result.last_name == "Smith"


# =============================================================================
# get_employee
# =============================================================================

class TestGetEmployee:

    def test_not_found_raises(self, mock_db):
        from app.services.employee_service import get_employee
        mock_db.session.get.return_value = None
        with pytest.raises(NotFoundError, match="introuvable"):
            get_employee(999)

    def test_found_returns_employee(self, mock_db):
        from app.services.employee_service import get_employee
        emp = _make_employee(id=42)
        mock_db.session.get.return_value = emp
        result = get_employee(42)
        assert result.id == 42


# =============================================================================
# update_employee
# =============================================================================

class TestUpdateEmployee:

    def test_self_manager_raises(self, mock_db):
        from app.services.employee_service import update_employee
        emp = _make_employee(id=5)
        mock_db.session.get.return_value = emp
        with pytest.raises(BusinessRuleError, match="propre manager"):
            update_employee(5, {"manager_id": 5})

    def test_termination_before_hire_raises(self, mock_db):
        from app.services.employee_service import update_employee
        emp = _make_employee(id=3, hire_date=date(2022, 6, 1))
        mock_db.session.get.return_value = emp
        with pytest.raises(ValidationError, match="départ"):
            update_employee(3, {"termination_date": date(2021, 1, 1)})

    def test_probation_before_hire_raises(self, mock_db):
        from app.services.employee_service import update_employee
        emp = _make_employee(id=3, hire_date=date(2022, 6, 1))
        mock_db.session.get.return_value = emp
        with pytest.raises(ValidationError, match="période d'essai"):
            update_employee(3, {"probation_end_date": date(2022, 5, 1)})

    def test_success_commits(self, mock_db):
        from app.services.employee_service import update_employee
        emp = _make_employee(id=7)
        mock_db.session.get.return_value = emp
        result = update_employee(7, {"first_name": "Bob"})
        mock_db.session.commit.assert_called_once()
        assert result is emp


# =============================================================================
# delete_employee
# =============================================================================

class TestDeleteEmployee:

    def test_soft_delete_calls_terminate(self, mock_db):
        from app.services.employee_service import delete_employee
        emp = _make_employee(id=10, is_terminated=False)
        mock_db.session.get.return_value = emp
        result = delete_employee(10, termination_date=date(2025, 6, 1))
        emp.terminate.assert_called_once()
        mock_db.session.commit.assert_called_once()
        assert result is emp

    def test_already_terminated_raises(self, mock_db):
        from app.services.employee_service import delete_employee
        emp = _make_employee(id=10, is_terminated=True)
        mock_db.session.get.return_value = emp
        with pytest.raises(BusinessRuleError, match="déjà marqué"):
            delete_employee(10)

    def test_hard_delete_with_subordinates_raises(self, mock_db):
        from app.services.employee_service import delete_employee
        emp = _make_employee(id=11, subordinates_count=2)
        mock_db.session.get.return_value = emp
        mock_db.session.execute.return_value.scalar_one.return_value = 0  # no dept
        with pytest.raises(BusinessRuleError, match="subordonné"):
            delete_employee(11, hard_delete=True)

    def test_hard_delete_manages_dept_raises(self, mock_db):
        from app.services.employee_service import delete_employee
        emp = _make_employee(id=12, subordinates_count=0)
        mock_db.session.get.return_value = emp
        mock_db.session.execute.return_value.scalar_one.return_value = 1  # manages 1 dept
        with pytest.raises(BusinessRuleError, match="[Dd]épartement"):
            delete_employee(12, hard_delete=True)

    def test_hard_delete_clean_removes(self, mock_db):
        from app.services.employee_service import delete_employee
        emp = _make_employee(id=13, subordinates_count=0)
        mock_db.session.get.return_value = emp
        mock_db.session.execute.return_value.scalar_one.return_value = 0
        delete_employee(13, hard_delete=True)
        mock_db.session.delete.assert_called_once_with(emp)
        mock_db.session.commit.assert_called_once()


# =============================================================================
# list_employees
# =============================================================================

class TestListEmployees:

    def test_invalid_status_raises(self, mock_db):
        from app.services.employee_service import list_employees
        with pytest.raises(ValidationError, match="[Ss]tatut"):
            list_employees(company_id=1, status="flying")
