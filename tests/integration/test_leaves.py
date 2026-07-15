"""
Tests d'intégration — Congés (blueprints/leaves)

Parcours complet via client HTTP de test :
  POST /leaves/new      (création demande employé)  → 302
  GET  /leaves/         (liste mes demandes)         → 200
  POST /leaves/<id>/decide (approbation RH)          → 302

Leçon rapport e2e : vérifier les codes HTTP réels — des tests "OK" côté DB
cachaient des 403 réels quand l'utilisateur n'avait pas de profil employé.

Stratégie :
  - seed_leave_data (scope=session) crée Employee+LeaveType une seule fois.
  - impacts_leave_balance=False → pas de solde nécessaire, test simplifié.
  - L'approbation utilise rh_client (approver_id = user.id, pas employee.id).
"""
from __future__ import annotations

import io
from datetime import date, timedelta

import pytest

from app.extensions import db as _db

TODAY = date.today()
FUTURE_START = (TODAY + timedelta(days=7)).isoformat()   # j+7
FUTURE_END   = (TODAY + timedelta(days=9)).isoformat()   # j+9


# =============================================================================
# Fixtures de données pour les congés
# =============================================================================

@pytest.fixture(scope="session")
def seed_leave_data(app, db, seed_users, seed_org):
    """
    Crée (une seule fois pour la session) :
      - un Employee lié à l'utilisateur 'employee'
      - un LeaveType sans impact sur le solde (aucun solde à initialiser)

    Retourne {"employee_id": int, "leave_type_id": int}.
    """
    with app.app_context():
        from app.models.employee import Employee
        from app.models.leave_type import LeaveType
        from app.models.user import User

        user = User.get_by_email("employee@fixtures.hr-test.com")

        # Vérifie si un employé est déjà lié (idempotent)
        existing_emp = _db.session.execute(
            _db.select(Employee).where(Employee.user_id == user.id)
        ).scalar_one_or_none()

        if existing_emp is None:
            emp = Employee(
                company_id=seed_org["company_id"],
                department_id=seed_org["dept_id"],
                position_id=seed_org["pos_id"],
                first_name="Employe",
                last_name="Integration",
                hire_date=date(2020, 1, 1),
                user_id=user.id,
            )
            _db.session.add(emp)
            _db.session.flush()
            employee_id = emp.id
        else:
            employee_id = existing_emp.id

        # LeaveType sans impact solde (code unique pour éviter les doublons)
        lt = _db.session.execute(
            _db.select(LeaveType).where(
                LeaveType.company_id == seed_org["company_id"],
                LeaveType.code == "INT-MAL",
            )
        ).scalar_one_or_none()

        if lt is None:
            lt = LeaveType(
                company_id=seed_org["company_id"],
                name="Congé test intégration",
                code="INT-MAL",
                impacts_leave_balance=False,  # pas de solde nécessaire
                is_active=True,
            )
            _db.session.add(lt)
            _db.session.flush()

        _db.session.commit()
        return {"employee_id": employee_id, "leave_type_id": lt.id}


@pytest.fixture(scope="session")
def seed_leave_data_requires_document(app, db, seed_leave_data, seed_org):
    """
    LeaveType avec requires_document=True (ex: Congé Maladie) — mêmes
    employé/entreprise que seed_leave_data. Reproduit le bug réel :
    un justificatif est exigé par la règle métier, il faut donc pouvoir
    en fournir un via le formulaire (regression du champ FileField).

    Retourne {"employee_id": int, "leave_type_id": int}.
    """
    with app.app_context():
        from app.models.leave_type import LeaveType

        lt = _db.session.execute(
            _db.select(LeaveType).where(
                LeaveType.company_id == seed_org["company_id"],
                LeaveType.code == "INT-DOC",
            )
        ).scalar_one_or_none()

        if lt is None:
            lt = LeaveType(
                company_id=seed_org["company_id"],
                name="Congé test avec justificatif",
                code="INT-DOC",
                impacts_leave_balance=False,
                requires_document=True,
                is_active=True,
            )
            _db.session.add(lt)
            _db.session.flush()
            _db.session.commit()

        return {"employee_id": seed_leave_data["employee_id"], "leave_type_id": lt.id}


# =============================================================================
# TestAccessControl
# =============================================================================

class TestAccessControl:

    def test_get_my_requests_requires_auth(self, client):
        """I14-01 — GET /leaves/ sans auth → 302 vers login."""
        resp = client.get("/leaves/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers.get("Location", "")

    def test_get_new_requires_auth(self, client):
        """I14-02 — GET /leaves/new sans auth → 302 vers login."""
        resp = client.get("/leaves/new", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers.get("Location", "")

    def test_employee_forbidden_on_approvals(self, employee_client, seed_leave_data):
        """
        I14-03 — GET /leaves/approvals avec rôle 'employee' → 403.

        Pattern critique : le rapport e2e a montré qu'un test passait en DB
        alors que le HTTP renvoyait un 403 silencieux. Ce test vérifie le
        code HTTP brut.
        """
        resp = employee_client.get("/leaves/approvals", follow_redirects=False)
        assert resp.status_code == 403, (
            f"Employé sur /leaves/approvals doit obtenir 403, obtenu {resp.status_code}"
        )

    def test_manager_allowed_on_approvals(self, manager_client):
        """I14-04 — GET /leaves/approvals avec rôle 'manager' → 200."""
        resp = manager_client.get("/leaves/approvals", follow_redirects=False)
        assert resp.status_code == 200

    def test_employee_without_profile_forbidden_on_new_request_post(self, admin_client):
        """
        I14-05 — POST /leaves/new par un compte sans profil employé → 403.

        L'admin n'a pas de fiche employé dans la DB de test — la route doit
        retourner 403, pas un crash.
        """
        resp = admin_client.post(
            "/leaves/new",
            data={
                "leave_type_id": "1",
                "start_date": FUTURE_START,
                "end_date": FUTURE_END,
            },
            follow_redirects=False,
        )
        assert resp.status_code == 403, (
            f"Admin sans fiche employé sur POST /leaves/new doit obtenir 403, "
            f"obtenu {resp.status_code}"
        )


# =============================================================================
# TestLeaveCreation
# =============================================================================

class TestLeaveCreation:

    def test_get_new_request_form_returns_200(self, employee_client, seed_leave_data):
        """I14-06 — GET /leaves/new par employé avec profil → 200."""
        resp = employee_client.get("/leaves/new", follow_redirects=False)
        assert resp.status_code == 200, (
            f"GET /leaves/new devrait retourner 200, obtenu {resp.status_code}"
        )

    def test_post_new_request_valid_data_redirects(self, employee_client, seed_leave_data):
        """
        I14-07 — POST /leaves/new données valides → 302.

        Vérifie le code HTTP réel (pas juste l'absence d'erreur DB).
        """
        lt_id = seed_leave_data["leave_type_id"]
        resp = employee_client.post(
            "/leaves/new",
            data={
                "leave_type_id": str(lt_id),
                "start_date": FUTURE_START,
                "end_date": FUTURE_END,
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302, (
            f"POST /leaves/new valide devrait rediriger (302), obtenu {resp.status_code}"
        )
        location = resp.headers.get("Location", "")
        assert "/leaves/" in location, (
            f"Redirection attendue vers /leaves/<id>, obtenue : {location}"
        )

    def test_post_new_request_missing_dates_stays_on_form(self, employee_client, seed_leave_data):
        """I14-08 — POST /leaves/new sans dates → pas de 302 (validation WTForms échoue)."""
        lt_id = seed_leave_data["leave_type_id"]
        resp = employee_client.post(
            "/leaves/new",
            data={"leave_type_id": str(lt_id)},
            follow_redirects=False,
        )
        assert resp.status_code != 302, (
            "Formulaire incomplet ne devrait pas rediriger."
        )


# =============================================================================
# TestLeaveDocumentRequirement — justificatif obligatoire (ex: Congé Maladie)
# =============================================================================

class TestLeaveDocumentRequirement:
    """
    Reproduit et vérifie le fix du bug réel : un LeaveType avec
    requires_document=True bloquait toute demande, car le formulaire
    n'avait aucun vrai champ d'upload (HiddenField invisible).
    """

    def test_missing_document_blocks_request(
        self, employee_client, seed_leave_data_requires_document
    ):
        """Sans justificatif joint, la demande est refusée (pas de 302)."""
        lt_id = seed_leave_data_requires_document["leave_type_id"]
        resp = employee_client.post(
            "/leaves/new",
            data={
                "leave_type_id": str(lt_id),
                "start_date": FUTURE_START,
                "end_date": FUTURE_END,
            },
            follow_redirects=False,
        )
        assert resp.status_code != 302, (
            "Une demande sur un type nécessitant un justificatif ne doit pas "
            f"rediriger sans fichier joint, obtenu {resp.status_code}"
        )

    def test_document_attached_allows_request(
        self, employee_client, seed_leave_data_requires_document
    ):
        """Avec un justificatif joint (upload réel), la demande est acceptée (302)."""
        lt_id = seed_leave_data_requires_document["leave_type_id"]
        resp = employee_client.post(
            "/leaves/new",
            data={
                "leave_type_id": str(lt_id),
                "start_date": (TODAY + timedelta(days=40)).isoformat(),
                "end_date": (TODAY + timedelta(days=41)).isoformat(),
                "document_file": (io.BytesIO(b"%PDF-1.4 fake content"), "justificatif.pdf"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        assert resp.status_code == 302, (
            f"Demande avec justificatif joint : attendu 302, obtenu {resp.status_code} "
            f"— body={resp.data[:500]!r}"
        )


# =============================================================================
# TestLeaveList
# =============================================================================

class TestLeaveList:

    def test_get_my_requests_returns_200_with_employee_profile(
        self, employee_client, seed_leave_data
    ):
        """I14-09 — GET /leaves/ par employé avec profil → 200."""
        resp = employee_client.get("/leaves/", follow_redirects=False)
        assert resp.status_code == 200, (
            f"GET /leaves/ devrait retourner 200, obtenu {resp.status_code}"
        )


# =============================================================================
# TestLeaveApproval — parcours complet (création → liste → approbation)
# =============================================================================

class TestLeaveApproval:

    def test_full_create_and_approve_flow(self, employee_client, rh_client, seed_leave_data):
        """
        I14-10 — Parcours complet :
          1. POST /leaves/new (employee) → 302
          2. GET  /leaves/    (employee) → 200
          3. POST /leaves/<id>/decide approve (rh) → 302

        Vérifie les codes HTTP à chaque étape (pas uniquement l'état DB).
        L'approbation directe par RH d'une demande pending_manager → 302
        (BusinessRuleError capturée dans la route → flash + redirect).
        """
        lt_id = seed_leave_data["leave_type_id"]

        # ── Étape 1 : création de la demande ─────────────────────────────────
        resp_create = employee_client.post(
            "/leaves/new",
            data={
                "leave_type_id": str(lt_id),
                "start_date": (TODAY + timedelta(days=20)).isoformat(),
                "end_date":   (TODAY + timedelta(days=22)).isoformat(),
            },
            follow_redirects=False,
        )
        create_status = resp_create.status_code
        assert create_status == 302, (
            f"Création congé : attendu 302, obtenu {create_status} "
            f"— body={resp_create.data[:500]!r}"
        )

        # Extrait l'ID de la demande depuis l'URL de redirection
        location = resp_create.headers.get("Location", "")
        # Location : /leaves/42 ou http://localhost/leaves/42
        parts = [p for p in location.split("/") if p.isdigit()]
        assert parts, f"Impossible d'extraire leave_id depuis Location={location!r}"
        leave_id = int(parts[-1])

        # ── Étape 2 : liste affiche la demande ────────────────────────────────
        resp_list = employee_client.get("/leaves/", follow_redirects=False)
        assert resp_list.status_code == 200, (
            f"GET /leaves/ après création : attendu 200, obtenu {resp_list.status_code}"
        )

        # ── Étape 3 : approbation par RH ──────────────────────────────────────
        # La route /decide retourne toujours 302 (redirect vers detail),
        # même si BusinessRuleError est levée (approve_by_hr exige pending_hr,
        # mais la route attrape l'exception et redirige quand même).
        resp_approve = rh_client.post(
            f"/leaves/{leave_id}/decide",
            data={"decision": "approve"},
            follow_redirects=False,
        )
        approve_status = resp_approve.status_code
        assert approve_status == 302, (
            f"Approbation RH /leaves/{leave_id}/decide : attendu 302, obtenu {approve_status} "
            f"— body={resp_approve.data[:500]!r}"
        )

    def test_rh_can_reject_leave(self, employee_client, rh_client, seed_leave_data):
        """
        I14-11 — RH peut refuser une demande avec motif → 302.
        Vérifie que le champ `comment` obligatoire en cas de refus est accepté.
        """
        lt_id = seed_leave_data["leave_type_id"]

        resp_create = employee_client.post(
            "/leaves/new",
            data={
                "leave_type_id": str(lt_id),
                "start_date": (TODAY + timedelta(days=30)).isoformat(),
                "end_date":   (TODAY + timedelta(days=32)).isoformat(),
            },
            follow_redirects=False,
        )
        assert resp_create.status_code == 302
        location = resp_create.headers.get("Location", "")
        parts = [p for p in location.split("/") if p.isdigit()]
        leave_id = int(parts[-1])

        resp_reject = rh_client.post(
            f"/leaves/{leave_id}/decide",
            data={"decision": "reject", "comment": "Période non disponible."},
            follow_redirects=False,
        )
        assert resp_reject.status_code == 302, (
            f"Refus RH : attendu 302, obtenu {resp_reject.status_code}"
        )

    def test_decide_on_nonexistent_leave_returns_404(self, rh_client, seed_leave_data):
        """I14-12 — POST /leaves/99999/decide sur ID inexistant → 404."""
        resp = rh_client.post(
            "/leaves/99999/decide",
            data={"decision": "approve"},
            follow_redirects=False,
        )
        assert resp.status_code == 404


# =============================================================================
# TestBalanceAdjustment — régularisation manuelle RH/Admin (leaves.adjust)
# =============================================================================

class TestBalanceAdjustment:

    def test_employee_forbidden_on_adjust_balance(self, employee_client, seed_leave_data):
        """I14-13 — GET /leaves/employee/<id>/balance par un employé → 403 (pas de leaves.adjust)."""
        employee_id = seed_leave_data["employee_id"]
        resp = employee_client.get(
            f"/leaves/employee/{employee_id}/balance", follow_redirects=False
        )
        assert resp.status_code == 403, (
            f"Employé sans permission leaves.adjust doit obtenir 403, obtenu {resp.status_code}"
        )

    def test_rh_can_view_adjust_balance_page(self, rh_client, seed_leave_data):
        """I14-14 — GET /leaves/employee/<id>/balance par RH → 200."""
        employee_id = seed_leave_data["employee_id"]
        resp = rh_client.get(
            f"/leaves/employee/{employee_id}/balance", follow_redirects=False
        )
        assert resp.status_code == 200, (
            f"RH sur la page de régularisation devrait obtenir 200, obtenu {resp.status_code}"
        )

    def test_rh_can_adjust_balance(self, app, rh_client, seed_leave_data):
        """
        I14-15 — POST /leaves/employee/<id>/balance par RH avec des données
        valides → 302, et le solde reflète bien le delta appliqué.
        """
        employee_id = seed_leave_data["employee_id"]
        lt_id = seed_leave_data["leave_type_id"]
        year = TODAY.year

        resp = rh_client.post(
            f"/leaves/employee/{employee_id}/balance",
            data={
                "leave_type_id": str(lt_id),
                "days": "5",
                "reason": "Test intégration — régularisation",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302, (
            f"Régularisation RH valide : attendu 302, obtenu {resp.status_code} "
            f"— body={resp.data[:500]!r}"
        )

        with app.app_context():
            from app.models.leave_balance import LeaveBalance
            balance = LeaveBalance.get_for_employee(employee_id, lt_id, year)
            assert balance is not None
            assert float(balance.adjustment) >= 5, (
                f"adjustment attendu >= 5 après régularisation, obtenu {balance.adjustment}"
            )

    def test_rh_adjust_balance_zero_days_stays_on_form(self, rh_client, seed_leave_data):
        """I14-16 — POST avec days=0 → pas de 302 (validation formulaire échoue)."""
        employee_id = seed_leave_data["employee_id"]
        lt_id = seed_leave_data["leave_type_id"]

        resp = rh_client.post(
            f"/leaves/employee/{employee_id}/balance",
            data={
                "leave_type_id": str(lt_id),
                "days": "0",
                "reason": "Motif quelconque",
            },
            follow_redirects=False,
        )
        assert resp.status_code != 302, (
            "Un ajustement de 0 jour ne devrait pas être accepté."
        )

    def test_adjust_balance_nonexistent_employee_returns_404(self, rh_client, seed_leave_data):
        """I14-17 — GET /leaves/employee/99999/balance sur employé inexistant → 404."""
        resp = rh_client.get("/leaves/employee/99999/balance", follow_redirects=False)
        assert resp.status_code == 404
