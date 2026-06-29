"""
Tests unitaires — leave_service

Couvre le pipeline complet : création, approbation, rejet, soldes.
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


def _make_leave_type(*, impacts_balance=True, requires_document=False,
                     requires_justification=False, min_advance_days=0,
                     max_consecutive_days=None):
    lt = MagicMock()
    lt.id = 1
    lt.name = "Congés payés"
    lt.impacts_leave_balance = impacts_balance
    lt.requires_document = requires_document
    lt.requires_justification = requires_justification
    lt.validate_duration.return_value = None   # no error by default
    lt.validate_advance_notice.return_value = None
    return lt


def _make_employee(eid=1, manager_id=None, company_id=1):
    emp = MagicMock()
    emp.id = eid
    emp.company_id = company_id
    emp.manager_id = manager_id
    return emp


def _make_balance(*, available=25.0, pending=0.0):
    bal = MagicMock()
    bal.available = available
    bal.pending = pending
    bal.can_take.side_effect = lambda days: available >= days
    return bal


def _make_leave_request(status="pending_manager", *, leave_type=None, working_days=5.0,
                        employee_id=1, start_date=None):
    lr = MagicMock()
    lr.id = 1
    lr.status = status
    lr.employee_id = employee_id
    lr.leave_type_id = 1
    lr.working_days = working_days
    lr.start_date = start_date or FUTURE
    lr.leave_type = leave_type or _make_leave_type()
    return lr


# =============================================================================
# create_leave_request
# =============================================================================

class TestCreateLeaveRequest:

    def _base_data(self, **kwargs):
        return {
            "employee_id": 1,
            "leave_type_id": 1,
            "start_date": FUTURE,
            "end_date": FUTURE2,
            **kwargs,
        }

    def _setup_happy_path(self, mock_db, balance=None):
        emp = _make_employee()
        lt = _make_leave_type()
        mock_db.session.get.side_effect = lambda model, pk: {
            (None, 1): emp,  # fallback
        }.get((None, pk), {1: emp, 2: lt}.get(pk))

        # Discriminate by which model class is passed
        def session_get(model_cls, pk):
            from app.models.employee import Employee
            from app.models.leave_type import LeaveType
            if model_cls is Employee:
                return emp
            if model_cls is LeaveType:
                return lt
            return None

        mock_db.session.get.side_effect = session_get
        # No overlap
        mock_db.session.execute.return_value.first.return_value = None
        # Balance
        bal = balance or _make_balance(available=25.0)
        with patch("app.services.leave_service.LeaveBalance") as mock_bal_cls:
            mock_bal_cls.get_or_create.return_value = bal
            yield emp, lt, bal

    def test_employee_not_found_raises(self, mock_db):
        from app.services.leave_service import create_leave_request
        mock_db.session.get.return_value = None
        with pytest.raises(NotFoundError, match="[Ee]mployé"):
            create_leave_request(self._base_data())

    def test_leave_type_not_found_raises(self, mock_db):
        from app.services.leave_service import create_leave_request
        emp = _make_employee()

        def session_get(cls, pk):
            from app.models.employee import Employee
            return emp if cls is Employee else None

        mock_db.session.get.side_effect = session_get
        with pytest.raises(NotFoundError, match="[Tt]ype d'absence"):
            create_leave_request(self._base_data())

    def test_end_before_start_raises(self, mock_db):
        from app.services.leave_service import create_leave_request
        emp = _make_employee()
        lt = _make_leave_type()

        def session_get(cls, pk):
            from app.models.employee import Employee
            from app.models.leave_type import LeaveType
            if cls is Employee:
                return emp
            if cls is LeaveType:
                return lt
            return None

        mock_db.session.get.side_effect = session_get
        with pytest.raises(ValidationError, match="fin"):
            create_leave_request(self._base_data(start_date=FUTURE2, end_date=FUTURE))

    def test_past_date_raises(self, mock_db):
        from app.services.leave_service import create_leave_request
        emp = _make_employee()
        lt = _make_leave_type()

        def session_get(cls, pk):
            from app.models.employee import Employee
            from app.models.leave_type import LeaveType
            if cls is Employee:
                return emp
            if cls is LeaveType:
                return lt
            return None

        mock_db.session.get.side_effect = session_get
        past = TODAY - timedelta(days=3)
        with pytest.raises(ValidationError, match="antérieure"):
            create_leave_request(self._base_data(start_date=past, end_date=TODAY))

    def test_overlap_raises(self, mock_db):
        from app.services.leave_service import create_leave_request
        emp = _make_employee()
        lt = _make_leave_type()

        def session_get(cls, pk):
            from app.models.employee import Employee
            from app.models.leave_type import LeaveType
            if cls is Employee:
                return emp
            if cls is LeaveType:
                return lt
            return None

        mock_db.session.get.side_effect = session_get
        # existing row found → overlap
        mock_db.session.execute.return_value.first.return_value = MagicMock()

        with patch("app.services.leave_service.LeaveRequest") as mock_lr_cls:
            mock_lr_cls.overlapping_for_employee.return_value = MagicMock()
            with pytest.raises(ConflictError, match="chevauche"):
                create_leave_request(self._base_data())

    def test_document_required_raises(self, mock_db):
        from app.services.leave_service import create_leave_request
        emp = _make_employee()
        lt = _make_leave_type(requires_document=True)

        def session_get(cls, pk):
            from app.models.employee import Employee
            from app.models.leave_type import LeaveType
            if cls is Employee:
                return emp
            if cls is LeaveType:
                return lt
            return None

        mock_db.session.get.side_effect = session_get
        mock_db.session.execute.return_value.first.return_value = None

        with patch("app.services.leave_service.LeaveRequest") as mock_lr_cls, \
             patch("app.services.leave_service._calculate_working_days", return_value=3.0):
            mock_lr_cls.overlapping_for_employee.return_value = MagicMock()
            with pytest.raises(ValidationError, match="justificatif"):
                create_leave_request(self._base_data())

    def test_insufficient_balance_raises(self, mock_db):
        from app.services.leave_service import create_leave_request
        emp = _make_employee()
        lt = _make_leave_type(impacts_balance=True)

        def session_get(cls, pk):
            from app.models.employee import Employee
            from app.models.leave_type import LeaveType
            if cls is Employee:
                return emp
            if cls is LeaveType:
                return lt
            return None

        mock_db.session.get.side_effect = session_get
        mock_db.session.execute.return_value.first.return_value = None

        bal = _make_balance(available=2.0)

        with patch("app.services.leave_service.LeaveRequest") as mock_lr_cls, \
             patch("app.services.leave_service._calculate_working_days", return_value=5.0), \
             patch("app.services.leave_service.LeaveBalance") as mock_bal_cls:
            mock_lr_cls.overlapping_for_employee.return_value = MagicMock()
            mock_lr_cls.STATUS_DRAFT = "draft"
            mock_bal_cls.get_or_create.return_value = bal
            with pytest.raises(BusinessRuleError, match="[Ss]olde insuffisant"):
                create_leave_request(self._base_data())

    def test_success_submits_and_reserves(self, mock_db):
        from app.services.leave_service import create_leave_request
        emp = _make_employee()
        lt = _make_leave_type(impacts_balance=True)

        def session_get(cls, pk):
            from app.models.employee import Employee
            from app.models.leave_type import LeaveType
            if cls is Employee:
                return emp
            if cls is LeaveType:
                return lt
            return None

        mock_db.session.get.side_effect = session_get
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

            result = create_leave_request(self._base_data())

        fake_lr.submit.assert_called_once()
        bal.reserve.assert_called_once_with(5.0)
        mock_db.session.commit.assert_called_once()
        assert result is fake_lr


# =============================================================================
# approve_leave
# =============================================================================

class TestApproveLeave:

    def test_invalid_role_raises(self, mock_db):
        from app.services.leave_service import approve_leave
        with pytest.raises(ValidationError, match="[Rr]ôle"):
            approve_leave(1, approver_id=1, approver_role="ceo")

    def test_not_found_raises(self, mock_db):
        from app.services.leave_service import approve_leave
        mock_db.session.get.return_value = None
        with pytest.raises(NotFoundError):
            approve_leave(999, approver_id=1, approver_role="manager")

    def test_manager_approval_calls_method(self, mock_db):
        from app.services.leave_service import approve_leave
        lr = _make_leave_request(status="pending_manager")
        lr.status = "pending_hr"  # after approve_by_manager stays in pending_hr
        mock_db.session.get.return_value = lr

        result = approve_leave(1, approver_id=2, approver_role="manager",
                               requires_hr_validation=True)

        lr.approve_by_manager.assert_called_once_with(2, comment=None, requires_hr_validation=True)
        mock_db.session.commit.assert_called_once()
        assert result is lr

    def test_hr_final_approval_consumes_balance(self, mock_db):
        from app.services.leave_service import approve_leave
        from app.models.leave_request import LeaveRequest as RealLR
        lr = _make_leave_request(status="approved")
        lt = _make_leave_type(impacts_balance=True)
        lr.leave_type = lt
        lr.working_days = 5.0
        lr.start_date = FUTURE

        def side_effect_approve(*args, **kwargs):
            lr.status = "approved"

        lr.approve_by_hr.side_effect = side_effect_approve
        lr.status = "pending_hr"
        mock_db.session.get.return_value = lr

        bal = _make_balance(available=25.0)

        with patch("app.services.leave_service.LeaveBalance") as mock_bal_cls:
            mock_bal_cls.get_or_create.return_value = bal
            # After approve_by_hr sets status to approved:
            def session_get(cls, pk):
                return lr

            mock_db.session.get.side_effect = session_get

            result = approve_leave(1, approver_id=3, approver_role="hr")

        lr.approve_by_hr.assert_called_once()
        mock_db.session.commit.assert_called_once()


# =============================================================================
# reject_leave
# =============================================================================

class TestRejectLeave:

    def test_empty_comment_raises(self, mock_db):
        from app.services.leave_service import reject_leave
        with pytest.raises(ValidationError, match="[Mm]otif"):
            reject_leave(1, approver_id=1, approver_role="manager", comment="")

    def test_invalid_role_raises(self, mock_db):
        from app.services.leave_service import reject_leave
        with pytest.raises(ValidationError, match="[Rr]ôle"):
            reject_leave(1, approver_id=1, approver_role="ceo", comment="Raison valide")

    def test_not_found_raises(self, mock_db):
        from app.services.leave_service import reject_leave
        mock_db.session.get.return_value = None
        with pytest.raises(NotFoundError):
            reject_leave(999, approver_id=1, approver_role="manager", comment="Raison")

    def test_reject_releases_balance(self, mock_db):
        from app.services.leave_service import reject_leave
        lr = _make_leave_request(status="pending_manager")
        lr.leave_type = _make_leave_type(impacts_balance=True)
        lr.working_days = 5.0
        lr.start_date = FUTURE
        mock_db.session.get.return_value = lr

        bal = _make_balance()
        with patch("app.services.leave_service.LeaveBalance") as mock_bal_cls:
            mock_bal_cls.get_for_employee.return_value = bal
            result = reject_leave(1, approver_id=2, approver_role="manager", comment="Trop court")

        lr.reject_by_manager.assert_called_once_with(2, comment="Trop court")
        bal.release_reservation.assert_called_once_with(5.0)
        mock_db.session.commit.assert_called_once()
        assert result is lr

    def test_reject_no_balance_impact(self, mock_db):
        """Rejet d'un type sans impact solde — release_reservation ne doit pas être appelé."""
        from app.services.leave_service import reject_leave
        lr = _make_leave_request(status="pending_hr")
        lr.leave_type = _make_leave_type(impacts_balance=False)
        lr.working_days = 1.0
        lr.start_date = FUTURE
        mock_db.session.get.return_value = lr

        with patch("app.services.leave_service.LeaveBalance") as mock_bal_cls:
            reject_leave(1, approver_id=3, approver_role="hr", comment="Raison")
            mock_bal_cls.get_for_employee.assert_not_called()

        mock_db.session.commit.assert_called_once()


# =============================================================================
# calculate_balance / adjust_balance
# =============================================================================

class TestBalanceFunctions:

    def test_calculate_balance_invalid_year_too_low(self, mock_db):
        from app.services.leave_service import calculate_balance
        with pytest.raises(ValidationError, match="[Aa]nnée"):
            calculate_balance(1, 1, year=1999)

    def test_calculate_balance_invalid_year_too_high(self, mock_db):
        from app.services.leave_service import calculate_balance
        with pytest.raises(ValidationError, match="[Aa]nnée"):
            calculate_balance(1, 1, year=2200)

    def test_calculate_balance_employee_not_found(self, mock_db):
        from app.services.leave_service import calculate_balance
        mock_db.session.get.return_value = None
        with pytest.raises(NotFoundError, match="[Ee]mployé"):
            calculate_balance(999, 1, year=2025)

    def test_calculate_balance_returns_balance(self, mock_db):
        from app.services.leave_service import calculate_balance
        emp = _make_employee()
        lt = MagicMock()

        def session_get(cls, pk):
            from app.models.employee import Employee
            from app.models.leave_type import LeaveType
            if cls is Employee:
                return emp
            if cls is LeaveType:
                return lt
            return None

        mock_db.session.get.side_effect = session_get
        bal = _make_balance(available=20.0)

        with patch("app.services.leave_service.LeaveBalance") as mock_bal_cls:
            mock_bal_cls.get_or_create.return_value = bal
            result = calculate_balance(1, 1, year=2025)

        assert result is bal
        mock_db.session.commit.assert_called_once()

    def test_adjust_balance_zero_delta_raises(self, mock_db):
        from app.services.leave_service import adjust_balance
        with pytest.raises(ValidationError, match="[Zz]éro|zéro|égal à zéro"):
            adjust_balance(1, 1, year=2025, days=0, reason="Test")

    def test_adjust_balance_empty_reason_raises(self, mock_db):
        from app.services.leave_service import adjust_balance
        with pytest.raises(ValidationError, match="[Mm]otif"):
            adjust_balance(1, 1, year=2025, days=2.0, reason="   ")

    def test_adjust_balance_success(self, mock_db):
        from app.services.leave_service import adjust_balance
        emp = _make_employee()
        lt = MagicMock()

        def session_get(cls, pk):
            from app.models.employee import Employee
            from app.models.leave_type import LeaveType
            if cls is Employee:
                return emp
            if cls is LeaveType:
                return lt
            return None

        mock_db.session.get.side_effect = session_get
        bal = _make_balance(available=20.0)

        with patch("app.services.leave_service.LeaveBalance") as mock_bal_cls:
            mock_bal_cls.get_or_create.return_value = bal
            result = adjust_balance(1, 1, year=2025, days=2.5, reason="Régularisation annuelle")

        bal.apply_adjustment.assert_called_once_with(2.5, reason="Régularisation annuelle")
        assert mock_db.session.commit.call_count >= 1


# =============================================================================
# _calculate_working_days (helper isolé)
# =============================================================================

class TestCalculateWorkingDays:

    def test_full_week_5_days(self, app):
        from app.services.leave_service import _calculate_working_days
        with app.app_context():
            with patch("app.services.leave_service._get_company_holidays", return_value=set()):
                # Lundi–vendredi
                mon = date(2025, 6, 2)
                fri = date(2025, 6, 6)
                assert _calculate_working_days(1, mon, fri, False, False) == 5.0

    def test_weekend_excluded(self, app):
        from app.services.leave_service import _calculate_working_days
        with app.app_context():
            with patch("app.services.leave_service._get_company_holidays", return_value=set()):
                # Samedi–dimanche → 0 jours ouvrés
                sat = date(2025, 6, 7)
                sun = date(2025, 6, 8)
                assert _calculate_working_days(1, sat, sun, False, False) == 0.0

    def test_half_day_start(self, app):
        from app.services.leave_service import _calculate_working_days
        with app.app_context():
            with patch("app.services.leave_service._get_company_holidays", return_value=set()):
                mon = date(2025, 6, 2)
                wed = date(2025, 6, 4)
                # Lundi après-midi → 2.5 jours
                assert _calculate_working_days(1, mon, wed, True, False) == 2.5

    def test_public_holiday_excluded(self, app):
        from app.services.leave_service import _calculate_working_days
        with app.app_context():
            tue = date(2025, 6, 3)
            holidays = {tue}
            with patch("app.services.leave_service._get_company_holidays", return_value=holidays):
                mon = date(2025, 6, 2)
                wed = date(2025, 6, 4)
                # 3 jours - 1 férié = 2
                assert _calculate_working_days(1, mon, wed, False, False) == 2.0
