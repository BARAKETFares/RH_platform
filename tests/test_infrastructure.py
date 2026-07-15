"""
Tests de validation de l'infrastructure pytest.

Ces tests vérifient que la config de test tourne correctement :
- app Flask créée et en mode Testing
- DB schema_rh_test accessible et tables créées
- Rôles système seedés
- Comptes de test créés et loginables
- db_session rollback fonctionne
- Fixtures employees et users utilisables
"""
from __future__ import annotations

import pytest


# =============================================================================
# App et config
# =============================================================================

class TestAppConfig:
    def test_app_exists(self, app):
        assert app is not None

    def test_testing_mode(self, app):
        assert app.config["TESTING"] is True

    def test_csrf_disabled(self, app):
        assert app.config["WTF_CSRF_ENABLED"] is False

    def test_uses_test_database(self, app):
        uri = app.config["SQLALCHEMY_DATABASE_URI"]
        assert "schema_rh_test" in uri, (
            f"La DB de test devrait être schema_rh_test, got: {uri}"
        )


# =============================================================================
# Base de données
# =============================================================================

class TestDatabase:
    def test_tables_created(self, app, db):
        """Vérifie que les tables principales ont bien été créées."""
        with app.app_context():
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            for expected in ("users", "roles", "employees", "companies"):
                assert expected in tables, f"Table '{expected}' manquante"

    def test_roles_seeded(self, app, db):
        """Vérifie que les 4 rôles système sont présents."""
        with app.app_context():
            from app.models.role import Role
            from app.extensions import db as _db

            role_names = [
                r.name for r in _db.session.execute(_db.select(Role)).scalars().all()
            ]
            for expected in ("admin", "rh", "manager", "employee"):
                assert expected in role_names, f"Rôle '{expected}' manquant"


# =============================================================================
# Isolation db_session
# =============================================================================

class TestDbSession:
    def test_flush_without_commit(self, app, db_session):
        """Un objet flushed a bien un id, mais n'est pas commité."""
        with app.app_context():
            from app.models.organization import Company
            company = Company(name="Rollback Test Corp", country="FR")
            db_session.add(company)
            db_session.flush()
            assert company.id is not None
        # Après le test, db_session rollback → Company disparaît de la DB.

    def test_rollback_does_not_leak(self, app, db):
        """Vérifie que le rollback du test précédent n'a pas laissé de trace."""
        with app.app_context():
            from app.models.organization import Company
            from app.extensions import db as _db

            result = _db.session.execute(
                _db.select(Company).where(Company.name == "Rollback Test Corp")
            ).scalar_one_or_none()
            assert result is None, "La Company de test précédent n'a pas été rollbackée !"


# =============================================================================
# Seed org et users
# =============================================================================

class TestSeedFixtures:
    def test_seed_org_returns_ids(self, seed_org):
        assert "company_id" in seed_org
        assert "dept_id"    in seed_org
        assert "pos_id"     in seed_org
        assert seed_org["company_id"] > 0

    def test_seed_users_returns_all_roles(self, seed_users):
        assert set(seed_users.keys()) == {"admin", "rh", "manager", "employee"}
        for key, creds in seed_users.items():
            assert "email"    in creds
            assert "password" in creds


# =============================================================================
# Clients authentifiés
# =============================================================================

class TestAuthenticatedClients:
    def test_admin_client_reaches_dashboard(self, admin_client):
        resp = admin_client.get("/reporting/dashboard", follow_redirects=True)
        assert resp.status_code == 200

    def test_rh_client_reaches_dashboard(self, rh_client):
        resp = rh_client.get("/reporting/dashboard", follow_redirects=True)
        assert resp.status_code == 200

    def test_manager_client_reaches_dashboard(self, manager_client):
        resp = manager_client.get("/reporting/dashboard", follow_redirects=True)
        assert resp.status_code == 200

    def test_employee_client_reaches_dashboard(self, employee_client):
        resp = employee_client.get("/reporting/dashboard", follow_redirects=True)
        assert resp.status_code == 200

    def test_unauthenticated_redirects_to_login(self, client):
        resp = client.get("/reporting/dashboard", follow_redirects=False)
        assert resp.status_code in (301, 302), (
            f"Expected 301/302 redirect to login, got HTTP {resp.status_code}. "
            f"Body: {resp.data[:300]!r}"
        )
        location = resp.headers.get("Location", "")
        assert "login" in location or "auth" in location, (
            f"Expected 'login' or 'auth' in Location, got: {location!r}"
        )


# =============================================================================
# Factories
# =============================================================================

class TestFactories:
    def test_make_user(self, app, db_session):
        from tests.fixtures.users import make_user
        with app.app_context():
            user = make_user("rh")
            db_session.flush()
            assert user.id is not None
            assert user.role.name == "rh"
            assert user.email.endswith("@fixture.hr-test.com")

    def test_make_employee(self, app, db_session, seed_org):
        from tests.fixtures.employees import make_employee
        with app.app_context():
            emp = make_employee(seed_org)
            db_session.flush()
            assert emp.id is not None
            assert emp.company_id == seed_org["company_id"]
            assert emp.status == "active"

    def test_user_factory(self, app, db_session):
        from tests.fixtures.users import UserFactory
        with app.app_context():
            user = UserFactory(role_name="manager")
            assert user.email.endswith("@fixture.hr-test.com")

    def test_employee_factory(self, app, db_session, seed_org):
        from tests.fixtures.employees import EmployeeFactory
        with app.app_context():
            emp = EmployeeFactory(org=seed_org, status="probation")
            assert emp.status == "probation"
            assert emp.company_id == seed_org["company_id"]


# =============================================================================
# TestCspNonce — régression du bug nonce CSP jamais substitué (15/07/2026)
# =============================================================================

class TestCspNonce:
    """
    Bug réel trouvé par test navigateur (Playwright) : la CSP contenait la
    chaîne littérale 'nonce-{nonce}' (jamais substituée), ce qui bloquait
    tout <script> inline — dont le graphique Chart.js du dashboard, qui
    s'affichait comme un carré vide dans le vrai navigateur (pytest seul
    ne l'aurait jamais détecté, car il ne vérifie pas le rendu visuel).
    """

    def test_csp_header_has_no_literal_placeholder(self, client):
        resp = client.get("/auth/login")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "{nonce}" not in csp, (
            "La CSP contient encore le placeholder littéral jamais substitué"
        )

    def test_csp_header_has_a_real_nonce(self, client):
        resp = client.get("/auth/login")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "'nonce-" in csp and "'nonce-{nonce}'" not in csp, (
            f"La CSP devrait contenir un vrai nonce généré, obtenu : {csp}"
        )

    def test_two_requests_get_different_nonces(self, client):
        """Le nonce doit être régénéré à chaque requête, pas figé une fois pour toutes."""
        csp1 = client.get("/auth/login").headers.get("Content-Security-Policy", "")
        csp2 = client.get("/auth/login").headers.get("Content-Security-Policy", "")
        assert csp1 != csp2, "Deux requêtes différentes ne devraient pas partager le même nonce"
