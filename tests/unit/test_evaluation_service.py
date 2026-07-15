"""
Tests unitaires — evaluation_service

Couvre le cycle complet d'évaluation :
  - Création de campagne
  - Lancement (paires employé/évaluateur)
  - Workflow Evaluation : draft → in_progress → employee_review → completed → archived
  - Objectifs : création, progression, notation

db.session est mocké — aucune base de données réelle.
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
# Fixture principale
# =============================================================================

@pytest.fixture
def mock_db(app):
    with app.app_context():
        with patch("app.services.evaluation_service.db") as m:
            m.session = MagicMock()
            m.select = MagicMock()
            m.session.execute.return_value.scalar_one_or_none.return_value = None
            m.session.execute.return_value.scalars.return_value.all.return_value = []
            yield m


def _make_campaign(cid=1, company_id=1):
    c = MagicMock()
    c.id = cid
    c.company_id = company_id
    c.name = "Éval 2025"
    c.start_date = date(2025, 1, 1)
    c.end_date = date(2025, 12, 31)
    return c


def _make_evaluation(eid=1, status="draft", employee_id=1, evaluator_id=2, campaign_id=1):
    ev = MagicMock()
    ev.id = eid
    ev.status = status
    ev.employee_id = employee_id
    ev.evaluator_id = evaluator_id
    ev.campaign_id = campaign_id
    ev.overall_score = None
    ev.strengths = None
    ev.areas_for_improvement = None
    ev.development_plan = None
    ev.manager_overall_comment = None
    return ev


def _make_objective(oid=1, status="active", employee_id=1):
    obj = MagicMock()
    obj.id = oid
    obj.status = status
    obj.employee_id = employee_id
    obj.completion_pct = 0
    return obj


# =============================================================================
# create_campaign
# =============================================================================

class TestCreateCampaign:

    def test_end_before_start_raises(self, mock_db):
        from app.services.evaluation_service import create_campaign
        with pytest.raises(ValidationError, match="fin"):
            create_campaign({
                "company_id": 1,
                "name": "Test",
                "period_year": 2025,
                "start_date": date(2025, 6, 1),
                "end_date": date(2025, 1, 1),
            }, created_by_id=1)

    def test_success_adds_and_commits(self, mock_db):
        from app.services.evaluation_service import create_campaign
        result = create_campaign({
            "company_id": 1,
            "name": "Éval annuelle 2025",
            "period_year": 2025,
            "start_date": date(2025, 1, 1),
            "end_date": date(2025, 12, 31),
        }, created_by_id=1)
        mock_db.session.add.assert_called_once()
        mock_db.session.commit.assert_called_once()
        assert result.name == "Éval annuelle 2025"


# =============================================================================
# get_campaign
# =============================================================================

class TestGetCampaign:

    def test_not_found_raises(self, mock_db):
        from app.services.evaluation_service import get_campaign
        mock_db.session.get.return_value = None
        with pytest.raises(NotFoundError, match="[Cc]ampagne"):
            get_campaign(999)

    def test_found_returns_campaign(self, mock_db):
        from app.services.evaluation_service import get_campaign
        c = _make_campaign(cid=5)
        mock_db.session.get.return_value = c
        assert get_campaign(5) is c


# =============================================================================
# launch_campaign_for_employees
# =============================================================================

class TestLaunchCampaign:

    def test_self_evaluator_raises(self, mock_db):
        from app.services.evaluation_service import launch_campaign_for_employees
        campaign = _make_campaign()
        mock_db.session.get.return_value = campaign
        with pytest.raises(BusinessRuleError, match="propre évaluateur"):
            launch_campaign_for_employees(1, [(10, 10)])

    def test_duplicate_raises(self, mock_db):
        from app.services.evaluation_service import launch_campaign_for_employees
        campaign = _make_campaign()
        mock_db.session.get.return_value = campaign
        # existing evaluation found
        mock_db.session.execute.return_value.scalar_one_or_none.return_value = _make_evaluation()
        with pytest.raises(ConflictError, match="[Ee]valuation|existe déjà"):
            launch_campaign_for_employees(1, [(10, 11)])

    def test_success_creates_and_sends(self, mock_db):
        from app.services.evaluation_service import launch_campaign_for_employees
        campaign = _make_campaign()
        mock_db.session.get.return_value = campaign
        mock_db.session.execute.return_value.scalar_one_or_none.return_value = None

        ev = _make_evaluation(status="draft")

        # select() de SQLAlchemy valide ses arguments à l'appel ; quand
        # Evaluation est un MagicMock, il faut patcher select aussi.
        with patch("app.services.evaluation_service.Evaluation") as mock_ev_cls, \
             patch("app.services.evaluation_service.select"):
            mock_ev_cls.STATUS_DRAFT = "draft"
            mock_ev_cls.return_value = ev
            result = launch_campaign_for_employees(1, [(1, 2), (3, 4)])

        assert mock_ev_cls.call_count == 2
        assert ev.send_to_evaluator.call_count == 2
        mock_db.session.commit.assert_called_once()
        assert len(result) == 2


# =============================================================================
# create_evaluation
# =============================================================================

class TestCreateEvaluation:

    def _setup(self, mock_db, *, employee_exists=True, evaluator_exists=True,
               duplicate=False):
        campaign = _make_campaign()
        emp = MagicMock()
        evaluator = MagicMock()

        def session_get(cls, pk):
            from app.models.evaluation import EvaluationCampaign
            from app.models.employee import Employee
            if cls is EvaluationCampaign:
                return campaign
            if cls is Employee:
                if pk == 1:
                    return emp if employee_exists else None
                if pk == 2:
                    return evaluator if evaluator_exists else None
            return None

        mock_db.session.get.side_effect = session_get
        if duplicate:
            mock_db.session.execute.return_value.scalar_one_or_none.return_value = _make_evaluation()
        else:
            mock_db.session.execute.return_value.scalar_one_or_none.return_value = None

        return campaign, emp, evaluator

    def test_self_evaluator_raises(self, mock_db):
        from app.services.evaluation_service import create_evaluation
        self._setup(mock_db)
        with pytest.raises(BusinessRuleError, match="propre évaluateur"):
            create_evaluation({"campaign_id": 1, "employee_id": 1, "evaluator_id": 1})

    def test_employee_not_found_raises(self, mock_db):
        from app.services.evaluation_service import create_evaluation
        campaign = _make_campaign()
        mock_db.session.get.side_effect = lambda cls, pk: campaign if pk == 1 and cls.__name__ == "EvaluationCampaign" else None
        with pytest.raises(NotFoundError, match="[Ee]mployé"):
            create_evaluation({"campaign_id": 1, "employee_id": 99, "evaluator_id": 2})

    def test_duplicate_raises(self, mock_db):
        from app.services.evaluation_service import create_evaluation
        self._setup(mock_db, duplicate=True)
        with pytest.raises(ConflictError, match="existe déjà"):
            create_evaluation({"campaign_id": 1, "employee_id": 1, "evaluator_id": 2})

    def test_success_creates_at_draft(self, mock_db):
        from app.services.evaluation_service import create_evaluation
        campaign = _make_campaign()
        emp = MagicMock()
        evaluator = MagicMock()

        def session_get(cls, pk):
            from app.models.evaluation import EvaluationCampaign
            from app.models.employee import Employee
            if cls is EvaluationCampaign:
                return campaign
            if cls is Employee:
                return emp if pk in (1, 2) else None
            return None

        mock_db.session.get.side_effect = session_get
        mock_db.session.execute.return_value.scalar_one_or_none.return_value = None

        ev = _make_evaluation(status="draft")
        # select() de SQLAlchemy valide ses arguments à l'appel ; quand
        # Evaluation est un MagicMock, il faut patcher select aussi.
        with patch("app.services.evaluation_service.Evaluation") as mock_ev_cls, \
             patch("app.services.evaluation_service.select"):
            mock_ev_cls.STATUS_DRAFT = "draft"
            mock_ev_cls.return_value = ev
            result = create_evaluation({"campaign_id": 1, "employee_id": 1, "evaluator_id": 2})

        mock_db.session.add.assert_called_once_with(ev)
        mock_db.session.commit.assert_called_once()
        assert result is ev


# =============================================================================
# Workflow Evaluation
# =============================================================================

class TestEvaluationWorkflow:
    """Teste le cycle draft → in_progress → employee_review → completed → archived."""

    def _get_eval_mock(self, mock_db, status):
        ev = _make_evaluation(status=status)
        mock_db.session.get.return_value = ev
        return ev

    def test_send_to_evaluator_draft_to_in_progress(self, mock_db):
        from app.services.evaluation_service import send_to_evaluator
        ev = self._get_eval_mock(mock_db, "draft")

        def do_send():
            ev.status = "in_progress"

        ev.send_to_evaluator.side_effect = do_send
        result = send_to_evaluator(1)

        ev.send_to_evaluator.assert_called_once()
        mock_db.session.commit.assert_called_once()
        assert result.status == "in_progress"

    def test_send_to_evaluator_bad_transition_raises(self, mock_db):
        from app.services.evaluation_service import send_to_evaluator
        ev = self._get_eval_mock(mock_db, "completed")
        ev.send_to_evaluator.side_effect = ValueError("Transition invalide")

        with pytest.raises(BusinessRuleError):
            send_to_evaluator(1)

    def test_submit_by_evaluator_sets_fields(self, mock_db):
        from app.services.evaluation_service import submit_by_evaluator
        ev = self._get_eval_mock(mock_db, "in_progress")

        def do_submit():
            ev.status = "employee_review"

        ev.submit_by_evaluator.side_effect = do_submit

        content = {
            "overall_score": 4,
            "manager_overall_comment": "Bon travail",
            "strengths": "Réactivité",
            "areas_for_improvement": "Gestion du temps",
        }
        result = submit_by_evaluator(1, content)

        assert ev.overall_score == 4
        assert ev.manager_overall_comment == "Bon travail"
        ev.submit_by_evaluator.assert_called_once()
        mock_db.session.commit.assert_called_once()

    def test_acknowledge_by_employee_records_comment(self, mock_db):
        from app.services.evaluation_service import acknowledge_by_employee
        ev = self._get_eval_mock(mock_db, "employee_review")

        result = acknowledge_by_employee(1, employee_comment="Je suis d'accord", sign=False)

        assert ev.employee_overall_comment == "Je suis d'accord"
        ev.acknowledge_by_employee.assert_called_once()
        mock_db.session.commit.assert_called_once()

    def test_finalize_completes_evaluation(self, mock_db):
        from app.services.evaluation_service import finalize_evaluation
        ev = self._get_eval_mock(mock_db, "employee_review")

        def do_finalize(sig):
            ev.status = "completed"

        ev.finalize.side_effect = do_finalize

        result = finalize_evaluation(1, sign=False)

        ev.finalize.assert_called_once()
        mock_db.session.commit.assert_called_once()
        assert result.status == "completed"

    def test_finalize_bad_transition_raises(self, mock_db):
        from app.services.evaluation_service import finalize_evaluation
        ev = self._get_eval_mock(mock_db, "draft")
        ev.finalize.side_effect = ValueError("Transition invalide depuis draft")

        with pytest.raises(BusinessRuleError):
            finalize_evaluation(1, sign=False)

    def test_archive_completed_to_archived(self, mock_db):
        from app.services.evaluation_service import archive_evaluation
        ev = self._get_eval_mock(mock_db, "completed")

        def do_archive():
            ev.status = "archived"

        ev.archive.side_effect = do_archive

        result = archive_evaluation(1)

        ev.archive.assert_called_once()
        mock_db.session.commit.assert_called_once()
        assert result.status == "archived"

    def test_archive_wrong_status_raises(self, mock_db):
        from app.services.evaluation_service import archive_evaluation
        ev = self._get_eval_mock(mock_db, "in_progress")
        ev.archive.side_effect = ValueError("Impossible d'archiver depuis in_progress")

        with pytest.raises(BusinessRuleError):
            archive_evaluation(1)


# =============================================================================
# Objectifs
# =============================================================================

class TestObjectives:

    def test_create_objective_self_assignment_raises(self, mock_db):
        from app.services.evaluation_service import create_objective
        emp = MagicMock()
        mock_db.session.get.return_value = emp
        with pytest.raises(BusinessRuleError, match="propre objectif"):
            create_objective({"employee_id": 5, "title": "Objectif"}, set_by_id=5)

    def test_create_objective_employee_not_found_raises(self, mock_db):
        from app.services.evaluation_service import create_objective
        mock_db.session.get.return_value = None
        with pytest.raises(NotFoundError, match="[Ee]mployé"):
            create_objective({"employee_id": 99, "title": "Objectif"}, set_by_id=1)

    def test_create_objective_success(self, mock_db):
        from app.services.evaluation_service import create_objective
        emp = MagicMock()
        mock_db.session.get.return_value = emp

        obj = _make_objective()
        with patch("app.services.evaluation_service.Objective") as mock_obj_cls:
            mock_obj_cls.STATUS_DRAFT = "draft"
            mock_obj_cls.return_value = obj
            result = create_objective(
                {"employee_id": 1, "title": "Atteindre 95 % de satisfaction client"},
                set_by_id=2,
            )

        obj.activate.assert_called_once()
        mock_db.session.add.assert_called_once_with(obj)
        mock_db.session.commit.assert_called_once()
        assert result is obj

    def test_update_objective_progress_auto_complete_at_100(self, mock_db):
        from app.services.evaluation_service import update_objective_progress
        obj = _make_objective(status="active")

        from app.models.objective import Objective as RealObjective
        with patch("app.services.evaluation_service.Objective") as mock_obj_cls:
            mock_obj_cls.ACTIVE_STATUSES = ("active", "at_risk")
            mock_db.session.get.return_value = obj
            result = update_objective_progress(1, completion_pct=100)

        assert obj.completion_pct == 100
        obj.complete.assert_called_once_with(completion_pct=100)
        mock_db.session.commit.assert_called_once()

    def test_update_objective_progress_partial(self, mock_db):
        from app.services.evaluation_service import update_objective_progress
        obj = _make_objective(status="active")

        with patch("app.services.evaluation_service.Objective") as mock_obj_cls:
            mock_obj_cls.ACTIVE_STATUSES = ("active", "at_risk")
            mock_db.session.get.return_value = obj
            result = update_objective_progress(1, completion_pct=60)

        assert obj.completion_pct == 60
        obj.complete.assert_not_called()
        mock_db.session.commit.assert_called_once()

    def test_update_objective_wrong_status_raises(self, mock_db):
        from app.services.evaluation_service import update_objective_progress
        obj = _make_objective(status="completed")

        with patch("app.services.evaluation_service.Objective") as mock_obj_cls:
            mock_obj_cls.ACTIVE_STATUSES = ("active", "at_risk")
            mock_db.session.get.return_value = obj
            with pytest.raises(BusinessRuleError, match="[Ss]tatut"):
                update_objective_progress(1, completion_pct=80)

    def test_submit_objective_rating_invalid_rated_by(self, mock_db):
        from app.services.evaluation_service import submit_objective_rating
        with pytest.raises(ValidationError, match="rated_by"):
            submit_objective_rating(1, rating=4, comment=None, rated_by="ceo")

    def test_submit_manager_rating(self, mock_db):
        from app.services.evaluation_service import submit_objective_rating
        obj = _make_objective()
        mock_db.session.get.return_value = obj

        result = submit_objective_rating(1, rating=5, comment="Excellent", rated_by="manager")

        obj.submit_manager_rating.assert_called_once_with(5, "Excellent")
        mock_db.session.commit.assert_called_once()

    def test_submit_employee_rating(self, mock_db):
        from app.services.evaluation_service import submit_objective_rating
        obj = _make_objective()
        mock_db.session.get.return_value = obj

        result = submit_objective_rating(1, rating=3, comment="Partiellement atteint", rated_by="employee")

        obj.submit_employee_rating.assert_called_once_with(3, "Partiellement atteint")
        mock_db.session.commit.assert_called_once()
