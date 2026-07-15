"""
Tests unitaires — leave_service

Cas couverts (miroir des validations manuelles / e2e) :
  - création de demande de congé (happy path + erreurs métier)
  - calcul de solde
  - chevauchement de dates refusé (ConflictError)
  - solde insuffisant refusé (BusinessRuleError)
  - approbation manager
  - refus manager

db.session est mocké — aucune base de données réelle.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.utils.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ValidationError,
)

TODAY = date.today()
FUTURE = TODAY + timedelta(days=10)
FUTURE2 = TODAY + timedelta(days=15)


# =============================================================================
# Fixture principale
# =============================================================================

@pytest.fixture
def mock_db(app):
    with app.app_context():
        with patch("app.services.leave_service.db") as m:
            m.session = MagicMock()
            yield m


def _make_leave_type(*, impacts_balance=True, requires_document=False):
    lt = MagicMock()
    lt.id = 1
    lt.name = "Congés payés"
    lt.impacts_leave_balance = impacts_balance
    lt.requires_document = requires_document
    lt.requires_justification = False
    lt.validate_duration.return_value = None
    lt.validate_advance_notice.return_value = None
    return lt


def _make_employee(eid=1, manager_id=None, company_id=1):
    emp = MagicMock()
    emp.id = eid
    emp.company_id = company_id
    emp.manager_id = manager_id
    return emp


def _make_balance(*, available=25.0):
    bal = MagicMock()
    bal.available = available
    bal.pending = 0.0
    bal.can_take.side_effect = lambda days: available >= days
    return bal


def _make_leave_request(status="pending_manager", *, leave_type=None, working_days=5.0,
                        employee_id=1):
    lr = MagicMock()
    lr.id = 1
    lr.status = status
    lr.employee_id = employee_id
    lr.leave_type_id = 1
    lr.working_days = working_days
    lr.start_date = FUTURE
    lr.leave_type = leave_type or _make_leave_type()
    return lr


def _session_get_factory(emp, lt):
    """Retourne un side_effect qui dispatche par modèle."""
    def _get(cls, pk):
        from app.models.employee import Employee
        from app.models.leave_type import LeaveType
        if cls is Employee:
            return emp
        if cls is LeaveType:
            return lt
        return None
    return _get


# =============================================================================
# create_leave_request
# =============================================================================

class TestCreateLeaveRequest:

    def _data(self, **kw):
        return {"employee_id": 1, "leave_type_id": 1,
                "start_date": FUTURE, "end_date": FUTURE2, **kw}

    def test_employee_not_found(self, mock_db):
        from app.services.leave_service import create_leave_request
        mock_db.session.get.return_value = None
        with pytest.raises(NotFoundError, match="[Ee]mployé"):
            create_leave_request(self._data())

    def test_leave_type_not_found(self, mock_db):
        from app.services.leave_service import create_leave_request
        emp = _make_employee()

        def _get(cls, pk):
            from app.models.employee import Employee
            return emp if cls is Employee else None

        mock_db.session.get.side_effect = _get
        with pytest.raises(NotFoundError, match="[Tt]ype d'absence"):
            create_leave_request(self._data())

    def test_overlap_raises_conflict(self, mock_db):
        from app.services.leave_service import create_leave_request
        emp, lt = _make_employee(), _make_leave_type()
        mock_db.session.get.side_effect = _session_get_factory(emp, lt)
        mock_db.session.execute.return_value.first.return_value = MagicMock()

        with patch("app.services.leave_service.LeaveRequest") as mock_lr_cls:
            mock_lr_cls.overlapping_for_employee.return_value = MagicMock()
            with pytest.raises(ConflictError, match="chevauche"):
                create_leave_request(self._data())

    def test_insufficient_balance_raises_business_rule(self, mock_db):
        from app.services.leave_service import create_leave_request
        emp = _make_employee()
        lt = _make_leave_type(impacts_balance=True)
        mock_db.session.get.side_effect = _session_get_factory(emp, lt)
        mock_db.session.execute.return_value.first.return_value = None

        bal = _make_balance(available=2.0)

        with patch("app.services.leave_service.LeaveRequest") as mock_lr_cls, \
             patch("app.services.leave_service._calculate_working_days", return_value=5.0), \
             patch("app.services.leave_service.LeaveBalance") as mock_bal_cls:
            mock_lr_cls.overlapping_for_employee.return_value = MagicMock()
            mock_lr_cls.STATUS_DRAFT = "draft"
            mock_bal_cls.get_or_create.return_value = bal
            with pytest.raises(BusinessRuleError, match="[Ss]olde insuffisant"):
                create_leave_request(self._data())

    def test_success_creates_and_reserves(self, mock_db):
        from app.services.leave_service import create_leave_request
        emp = _make_employee()
        lt = _make_leave_type(impacts_balance=True)
        mock_db.session.get.side_effect = _session_get_factory(emp, lt)
        mock_db.session.execute.return_value.first.return_value = None

        bal = _make_balance(available=25.0)
        fake_lr = MagicMock()
        fake_lr.id = 1

        with patch("app.services.leave_service.LeaveRequest") as mock_lr_cls, \
             patch("app.services.leave_service._calculate_working_days", return_value=5.0), \
             patch("app.services.leave_service.LeaveBalance") as mock_bal_cls:
            mock_lr_cls.overlapping_for_employee.return_value = MagicMock()
            mock_lr_cls.STATUS_DRAFT = "draft"
            mock_lr_cls.return_value = fake_lr
            mock_bal_cls.get_or_create.return_value = bal

            result = create_leave_request(self._data())

        fake_lr.submit.assert_called_once()
        bal.reserve.assert_called_once_with(5.0)
        mock_db.session.commit.assert_called_once()
        assert result is fake_lr


# =============================================================================
# calculate_balance
# =============================================================================

class TestCalculateBalance:

    def test_invalid_year_raises(self, mock_db):
        from app.services.leave_service import calculate_balance
        with pytest.raises(ValidationError, match="[Aa]nnée"):
            calculate_balance(1, 1, year=1999)

    def test_employee_not_found_raises(self, mock_db):
        from app.services.leave_service import calculate_balance
        mock_db.session.get.return_value = None
        with pytest.raises(NotFoundError, match="[Ee]mployé"):
            calculate_balance(999, 1, year=2025)

    def test_returns_balance(self, mock_db):
        from app.services.leave_service import calculate_balance
        emp, lt = _make_employee(), MagicMock()
        mock_db.session.get.side_effect = _session_get_factory(emp, lt)

        bal = _make_balance(available=20.0)
        with patch("app.services.leave_service.LeaveBalance") as mock_bal_cls:
            mock_bal_cls.get_or_create.return_value = bal
            result = calculate_balance(1, 1, year=2025)

        assert result is bal
        mock_db.session.commit.assert_called_once()


# =============================================================================
# approve_leave — approbation manager
# =============================================================================

class TestApproveLeave:

    def test_manager_approval(self, mock_db):
        from app.services.leave_service import approve_leave
        lr = _make_leave_request(status="pending_manager")
        mock_db.session.get.return_value = lr

        result = approve_leave(1, approver_id=2, approver_role="manager",
                               requires_hr_validation=True)

        lr.approve_by_manager.assert_called_once_with(2, comment=None,
                                                      requires_hr_validation=True)
        mock_db.session.commit.assert_called_once()
        assert result is lr

    def test_invalid_role_raises(self, mock_db):
        from app.services.leave_service import approve_leave
        with pytest.raises(ValidationError, match="[Rr]ôle"):
            approve_leave(1, approver_id=1, approver_role="ceo")

    def test_not_found_raises(self, mock_db):
        from app.services.leave_service import approve_leave
        mock_db.session.get.return_value = None
        with pytest.raises(NotFoundError):
            approve_leave(999, approver_id=1, approver_role="manager")


# =============================================================================
# reject_leave — refus manager
# =============================================================================

class TestRejectLeave:

    def test_manager_reject_releases_balance(self, mock_db):
        from app.services.leave_service import reject_leave
        lr = _make_leave_request(status="pending_manager")
        lr.leave_type = _make_leave_type(impacts_balance=True)
        lr.working_days = 5.0
        mock_db.session.get.return_value = lr

        bal = _make_balance()
        with patch("app.services.leave_service.LeaveBalance") as mock_bal_cls:
            mock_bal_cls.get_for_employee.return_value = bal
            result = reject_leave(1, approver_id=2, approver_role="manager",
                                  comment="Période trop chargée")

        lr.reject_by_manager.assert_called_once_with(2, comment="Période trop chargée")
        bal.release_reservation.assert_called_once_with(5.0)
        mock_db.session.commit.assert_called_once()
        assert result is lr

    def test_empty_comment_raises(self, mock_db):
        from app.services.leave_service import reject_leave
        with pytest.raises(ValidationError, match="[Mm]otif"):
            reject_leave(1, approver_id=1, approver_role="manager", comment="")

    def test_invalid_role_raises(self, mock_db):
        from app.services.leave_service import reject_leave
        with pytest.raises(ValidationError, match="[Rr]ôle"):
            reject_leave(1, approver_id=1, approver_role="ceo", comment="Raison")

    def test_not_found_raises(self, mock_db):
        from app.services.leave_service import reject_leave
        mock_db.session.get.return_value = None
        with pytest.raises(NotFoundError):
            reject_leave(999, approver_id=1, approver_role="manager", comment="Raison")
