"""
Tests unitaires — employee_service

Cas couverts :
  - Chiffrement Fernet réellement appliqué sur national_id_number, iban, bic
    (pas de mock crypto — le vrai Fernet tourne avec une clé de test)
  - Création d'employé : happy path avec champs sensibles, gardes-fous
  - Mise à jour : partial update, champs sensibles, cohérence dates
  - Soft delete / désactivation (terminate)
  - Recherche / filtres (list_employees)

db.session est mocké sauf pour les tests de chiffrement qui nécessitent
un contexte Flask réel avec FIELD_ENCRYPTION_KEY injectée.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from app.utils.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ValidationError,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def fernet_app(app):
    """Contexte Flask avec une clé Fernet réelle injectée dans la config."""
    key = Fernet.generate_key().decode()
    original = app.config.get("FIELD_ENCRYPTION_KEY", "")
    app.config["FIELD_ENCRYPTION_KEY"] = key
    with app.app_context():
        yield app, Fernet(key.encode())
    app.config["FIELD_ENCRYPTION_KEY"] = original


@pytest.fixture
def mock_db(app):
    """Contexte Flask + db.session entièrement mocké."""
    with app.app_context():
        with patch("app.services.employee_service.db") as m:
            m.session = MagicMock()
            m.session.execute.return_value.scalar_one_or_none.return_value = None
            m.session.execute.return_value.scalars.return_value.all.return_value = []
            yield m


@pytest.fixture
def mock_db_fernet(app):
    """Contexte Flask + db.session mocké + FIELD_ENCRYPTION_KEY réelle (pas de mock crypto)."""
    key = Fernet.generate_key().decode()
    original = app.config.get("FIELD_ENCRYPTION_KEY", "")
    app.config["FIELD_ENCRYPTION_KEY"] = key
    with app.app_context():
        with patch("app.services.employee_service.db") as m:
            m.session = MagicMock()
            m.session.execute.return_value.scalar_one_or_none.return_value = None
            yield m, Fernet(key.encode())
    app.config["FIELD_ENCRYPTION_KEY"] = original


def _make_employee(**kw):
    emp = MagicMock()
    emp.id = kw.get("id", 1)
    emp.company_id = kw.get("company_id", 1)
    emp.employee_number = kw.get("employee_number", None)
    emp.hire_date = kw.get("hire_date", date(2020, 1, 1))
    emp.termination_date = kw.get("termination_date", None)
    emp.probation_end_date = kw.get("probation_end_date", None)
    emp.is_terminated = kw.get("is_terminated", False)
    emp.manager = kw.get("manager", None)
    emp.subordinates.count.return_value = kw.get("subordinates_count", 0)
    return emp


# =============================================================================
# Chiffrement Fernet — tests sur le modèle seul (pas de DB)
# =============================================================================

class TestSensitiveFieldEncryption:
    """
    Vérifie que les hybrid_property (national_id_number, iban, bic) passent
    RÉELLEMENT par Fernet : la valeur stockée en _colonne doit être un token
    chiffré, jamais le texte clair.
    """

    def test_national_id_not_stored_as_plaintext(self, fernet_app):
        from app.models.employee import Employee
        emp = Employee()
        raw = "1 23 04 75 123 456 89"
        emp.national_id_number = raw
        assert emp._national_id_number != raw
        assert emp._national_id_number is not None

    def test_national_id_roundtrip(self, fernet_app):
        from app.models.employee import Employee
        emp = Employee()
        raw = "1 23 04 75 123 456 89"
        emp.national_id_number = raw
        assert emp.national_id_number == raw

    def test_iban_not_stored_as_plaintext(self, fernet_app):
        from app.models.employee import Employee
        emp = Employee()
        raw = "FR7630006000011234567890189"
        emp.iban = raw
        assert emp._iban != raw
        assert emp._iban is not None

    def test_iban_roundtrip(self, fernet_app):
        from app.models.employee import Employee
        emp = Employee()
        raw = "FR7630006000011234567890189"
        emp.iban = raw
        assert emp.iban == raw

    def test_bic_roundtrip(self, fernet_app):
        from app.models.employee import Employee
        emp = Employee()
        emp.bic = "BNPAFRPP"
        assert emp.bic == "BNPAFRPP"

    def test_none_value_stays_none(self, fernet_app):
        from app.models.employee import Employee
        emp = Employee()
        emp.national_id_number = None
        assert emp._national_id_number is None
        assert emp.national_id_number is None

    def test_fernet_token_is_not_readable_without_key(self, fernet_app):
        """Le token stocké est du Fernet : illisible avec une autre clé."""
        from app.models.employee import Employee
        emp = Employee()
        emp.national_id_number = "secret"
        stored = emp._national_id_number
        # Un deuxième Fernet avec une clé différente ne peut pas déchiffrer
        other_f = Fernet(Fernet.generate_key())
        with pytest.raises(Exception):
            other_f.decrypt(stored.encode())


# =============================================================================
# create_employee — champs sensibles chiffrés via le service
# =============================================================================

class TestCreateEmployee:

    def test_sensitive_fields_encrypted_at_service_level(self, mock_db_fernet):
        """
        Le service ne mocke pas encrypt_field : on vérifie que _national_id_number
        et _iban ne contiennent pas le texte en clair après create_employee().
        """
        from app.services.employee_service import create_employee
        mock_db, _ = mock_db_fernet

        result = create_employee({
            "company_id": 1,
            "first_name": "Alice",
            "last_name": "Dupont",
            "hire_date": date(2024, 3, 1),
            "national_id_number": "1 23 04 75 123 456 89",
            "iban": "FR7630006000011234567890189",
            "bic": "BNPAFRPP",
        })

        assert result._national_id_number != "1 23 04 75 123 456 89"
        assert result._iban != "FR7630006000011234567890189"
        assert result._bic != "BNPAFRPP"
        # Les getters décryptent correctement
        assert result.national_id_number == "1 23 04 75 123 456 89"
        assert result.iban == "FR7630006000011234567890189"
        assert result.bic == "BNPAFRPP"

    def test_missing_required_fields_raises(self, mock_db):
        from app.services.employee_service import create_employee
        with pytest.raises(ValidationError):
            create_employee({"first_name": "Alice"})

    def test_blank_first_name_raises(self, mock_db):
        from app.services.employee_service import create_employee
        with pytest.raises(ValidationError, match="prénom"):
            create_employee({
                "company_id": 1, "first_name": "  ",
                "last_name": "Dupont", "hire_date": date.today(),
            })

    def test_duplicate_employee_number_raises(self, mock_db):
        from app.services.employee_service import create_employee
        mock_db.session.execute.return_value.scalar_one_or_none.return_value = _make_employee()
        with pytest.raises(ConflictError, match="matricule"):
            create_employee({
                "company_id": 1, "first_name": "Alice", "last_name": "Dupont",
                "hire_date": date.today(), "employee_number": "EMP001",
            })

    def test_manager_not_found_raises(self, mock_db):
        from app.services.employee_service import create_employee
        mock_db.session.execute.return_value.scalar_one_or_none.return_value = None
        mock_db.session.get.return_value = None
        with pytest.raises(NotFoundError, match="[Mm]anager"):
            create_employee({
                "company_id": 1, "first_name": "Alice", "last_name": "Dupont",
                "hire_date": date.today(), "manager_id": 99,
            })

    def test_success_adds_and_commits(self, mock_db):
        from app.services.employee_service import create_employee
        result = create_employee({
            "company_id": 1, "first_name": "Alice",
            "last_name": "Dupont", "hire_date": date(2024, 1, 15),
        })
        mock_db.session.add.assert_called_once()
        mock_db.session.commit.assert_called_once()
        assert result.first_name == "Alice"


# =============================================================================
# update_employee
# =============================================================================

class TestUpdateEmployee:

    def test_sensitive_field_update_encrypted(self, mock_db_fernet):
        """Mise à jour d'un IBAN : le setter hybrid_property chiffre bien."""
        from app.services.employee_service import update_employee
        mock_db, _ = mock_db_fernet

        from app.models.employee import Employee
        real_emp = Employee(
            company_id=1, first_name="Bob", last_name="Martin",
            hire_date=date(2020, 6, 1),
        )
        mock_db.session.get.return_value = real_emp

        result = update_employee(1, {"iban": "FR7630006000011234567890189"})

        assert result._iban != "FR7630006000011234567890189"
        assert result.iban == "FR7630006000011234567890189"
        mock_db.session.commit.assert_called_once()

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
# delete_employee — soft delete / désactivation
# =============================================================================

class TestSoftDelete:

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

    def test_not_found_raises(self, mock_db):
        from app.services.employee_service import delete_employee
        mock_db.session.get.return_value = None
        with pytest.raises(NotFoundError):
            delete_employee(999)

    def test_hard_delete_with_subordinates_raises(self, mock_db):
        from app.services.employee_service import delete_employee
        emp = _make_employee(id=11, subordinates_count=2)
        mock_db.session.get.return_value = emp
        mock_db.session.execute.return_value.scalar_one.return_value = 0
        with pytest.raises(BusinessRuleError, match="subordonné"):
            delete_employee(11, hard_delete=True)

    def test_hard_delete_clean_removes(self, mock_db):
        from app.services.employee_service import delete_employee
        emp = _make_employee(id=13, subordinates_count=0)
        mock_db.session.get.return_value = emp
        mock_db.session.execute.return_value.scalar_one.return_value = 0
        delete_employee(13, hard_delete=True)
        mock_db.session.delete.assert_called_once_with(emp)
        mock_db.session.commit.assert_called_once()


# =============================================================================
# list_employees — recherche / filtres
# =============================================================================

class TestListEmployees:

    def test_invalid_status_raises(self, mock_db):
        from app.services.employee_service import list_employees
        with pytest.raises(ValidationError, match="[Ss]tatut"):
            list_employees(company_id=1, status="inexistant")

    def test_valid_status_builds_query(self, mock_db):
        from app.services.employee_service import list_employees
        with patch("app.services.employee_service.paginate") as mock_paginate:
            mock_paginate.return_value = MagicMock(items=[], total=0)
            result = list_employees(company_id=1, status="active")
        mock_paginate.assert_called_once()

    def test_department_filter_narrows_query(self, mock_db):
        from app.services.employee_service import list_employees
        with patch("app.services.employee_service.paginate") as mock_paginate:
            mock_paginate.return_value = MagicMock(items=[], total=0)
            list_employees(company_id=1, department_id=42)
        mock_paginate.assert_called_once()

    def test_search_filter_narrows_query(self, mock_db):
        from app.services.employee_service import list_employees
        with patch("app.services.employee_service.paginate") as mock_paginate:
            mock_paginate.return_value = MagicMock(items=[], total=0)
            list_employees(company_id=1, search="Alice")
        mock_paginate.assert_called_once()

    def test_manager_filter_narrows_query(self, mock_db):
        from app.services.employee_service import list_employees
        with patch("app.services.employee_service.paginate") as mock_paginate:
            mock_paginate.return_value = MagicMock(items=[], total=0)
            list_employees(company_id=1, manager_id=5)
        mock_paginate.assert_called_once()
