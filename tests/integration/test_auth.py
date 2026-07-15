"""
Tests d'intégration — Authentification (blueprints/auth)

Vérifie les codes HTTP réels retournés par le serveur Flask de test :
  - Login correct       → 302 (redirect vers dashboard)
  - Login mauvais MDP   → 401 (formulaire avec message d'erreur)
  - Login email inconnu → 401
  - Accès route protégée sans auth → 302 vers /auth/login
  - Accès route hors rôle (403) avec employee → /leaves/approvals
  - Logout authentifié → 302 vers /auth/login
  - Accès après logout → 302 (session effacée)

Leçon rapport e2e : ne pas se fier uniquement à la DB — vérifier
systématiquement le status_code HTTP.

Notes sur le setup :
  - /admin/ redirige (302) vers /admin/users/ — le test utilise /admin/users/.
  - Le rôle manager nécessite un Employee lié pour accéder à /leaves/approvals
    (la route appelle _require_employee_profile()). La fixture seed_manager_profile
    crée ce profil une seule fois pour la session.
"""
from __future__ import annotations

from datetime import date

import pytest
from app.extensions import db as _db


# =============================================================================
# Fixtures — profil employé pour le manager
# =============================================================================

@pytest.fixture(scope="session")
def seed_manager_profile(app, db, seed_users, seed_org):
    """
    Crée (une seule fois par session) un Employee lié au compte manager,
    requis par la route /leaves/approvals (qui appelle _require_employee_profile()).
    Idempotent : réutilise le profil existant si déjà créé.
    """
    with app.app_context():
        from app.models.employee import Employee
        from app.models.user import User

        user = User.get_by_email("manager@fixtures.hr-test.com")

        existing = _db.session.execute(
            _db.select(Employee).where(Employee.user_id == user.id)
        ).scalar_one_or_none()

        if existing is None:
            emp = Employee(
                company_id=seed_org["company_id"],
                department_id=seed_org["dept_id"],
                position_id=seed_org["pos_id"],
                first_name="Manager",
                last_name="Integration",
                hire_date=date(2018, 1, 1),
                user_id=user.id,
            )
            _db.session.add(emp)
            _db.session.commit()
            return emp.id

        return existing.id


# =============================================================================
# Helpers
# =============================================================================

def _login(c, email: str, password: str):
    return c.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


# =============================================================================
# TestLogin
# =============================================================================

class TestLogin:

    def test_get_login_page_returns_200(self, client):
        """I13-01 — GET /auth/login accessible sans auth → 200."""
        resp = client.get("/auth/login")
        assert resp.status_code == 200

    def test_login_page_renders_password_toggle_script(self, client):
        """
        Régression (15/07/2026) : base_auth.html n'avait pas de
        {% block extra_js %} — le script du toggle mot de passe de
        login.html (et ceux de forgot_password.html/reset_password.html)
        était silencieusement ignoré par Jinja2, jamais rendu dans le HTML,
        quel que soit son contenu. Aucune erreur, juste absent.
        """
        resp = client.get("/auth/login")
        html = resp.data.decode("utf-8")
        assert 'id="togglePassword"' in html, "Le bouton toggle doit être présent"
        assert "getElementById('togglePassword')" in html, (
            "Le script du toggle mot de passe doit être rendu dans le HTML "
            "(régression : bloc extra_js manquant dans base_auth.html)"
        )

    def test_valid_credentials_redirect(self, client, seed_users):
        """I13-02 — Login correct → 302 (redirect vers dashboard ou next)."""
        creds = seed_users["employee"]
        resp = _login(client, creds["email"], creds["password"])
        assert resp.status_code == 302, (
            f"Login valide devrait rediriger (302), obtenu {resp.status_code}"
        )

    def test_admin_valid_credentials_redirect(self, client, seed_users):
        """I13-03 — Login admin correct → 302."""
        creds = seed_users["admin"]
        resp = _login(client, creds["email"], creds["password"])
        assert resp.status_code == 302

    def test_wrong_password_returns_401(self, client, seed_users):
        """I13-04 — Mauvais mot de passe → 401 (pas un 302 ni 200 silencieux)."""
        creds = seed_users["employee"]
        resp = _login(client, creds["email"], "MauvaisMotDePasse!")
        assert resp.status_code == 401, (
            f"Mauvais MDP devrait renvoyer 401, obtenu {resp.status_code}"
        )

    def test_unknown_email_returns_401(self, client):
        """I13-05 — Email inconnu → 401."""
        resp = _login(client, "inconnu@nulle.part", "Test1234!")
        assert resp.status_code == 401

    def test_blank_email_returns_422(self, client):
        """I13-06 — Email vide → 422 (validation WTForms échoue)."""
        resp = _login(client, "", "Test1234!")
        assert resp.status_code == 422

    def test_blank_password_returns_422(self, client):
        """I13-07 — Mot de passe vide → 422."""
        resp = _login(client, "admin@fixtures.hr-test.com", "")
        assert resp.status_code == 422


# =============================================================================
# TestUnauthenticatedAccess
# =============================================================================

class TestUnauthenticatedAccess:

    def test_protected_leaves_list_redirects_to_login(self, client):
        """I13-08 — GET /leaves/ sans auth → 302 vers /auth/login."""
        resp = client.get("/leaves/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers.get("Location", ""), (
            f"Redirection attendue vers /auth/login, obtenue : {resp.headers.get('Location')}"
        )

    def test_protected_admin_redirects_to_login(self, client):
        """I13-09 — GET /admin/ sans auth → 302 vers /auth/login."""
        resp = client.get("/admin/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers.get("Location", "")

    def test_protected_approvals_redirects_to_login(self, client):
        """I13-10 — GET /leaves/approvals sans auth → 302 vers /auth/login."""
        resp = client.get("/leaves/approvals", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers.get("Location", "")


# =============================================================================
# TestRoleBasedAccess
# =============================================================================

class TestRoleBasedAccess:

    def test_employee_cannot_access_approvals_403(self, employee_client):
        """
        I13-11 — Employé accède à /leaves/approvals → 403.

        Pattern appris lors du rapport e2e : un test DB 'OK' cachait un 403
        réel. Ce test vérifie le code HTTP brut.
        """
        resp = employee_client.get("/leaves/approvals", follow_redirects=False)
        assert resp.status_code == 403, (
            f"Employé sur /leaves/approvals devrait obtenir 403, obtenu {resp.status_code}"
        )

    def test_employee_cannot_access_admin_users_403(self, employee_client):
        """I13-12 — Employé sur /admin/users/ → 403."""
        resp = employee_client.get("/admin/users/", follow_redirects=False)
        assert resp.status_code == 403

    def test_manager_can_access_approvals_200(self, manager_client, seed_manager_profile):
        """
        I13-13 — Manager sur /leaves/approvals → 200.
        Requiert un Employee lié au compte manager (seed_manager_profile).
        """
        resp = manager_client.get("/leaves/approvals", follow_redirects=False)
        assert resp.status_code == 200, (
            f"Manager sur /leaves/approvals devrait obtenir 200, obtenu {resp.status_code}"
        )

    def test_rh_can_access_approvals_200(self, rh_client):
        """I13-14 — RH sur /leaves/approvals → 200."""
        resp = rh_client.get("/leaves/approvals", follow_redirects=False)
        assert resp.status_code == 200

    def test_admin_can_access_admin_users_200(self, admin_client):
        """
        I13-15 — Admin sur /admin/users/ → 200.
        Note : /admin/ redirige (302) vers /admin/users/ — on cible directement
        la liste utilisateurs pour vérifier l'accès au panneau admin.
        """
        resp = admin_client.get("/admin/users/", follow_redirects=False)
        assert resp.status_code == 200


# =============================================================================
# TestLogout
# =============================================================================

class TestLogout:

    def test_logout_redirects_to_login(self, employee_client):
        """I13-16 — GET /auth/logout → 302 vers /auth/login."""
        resp = employee_client.get("/auth/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers.get("Location", ""), (
            f"Logout devrait rediriger vers /auth/login, obtenu : {resp.headers.get('Location')}"
        )

    def test_after_logout_protected_route_redirects(self, employee_client):
        """I13-17 — Après logout, accès à route protégée → 302 (session effacée)."""
        employee_client.get("/auth/logout", follow_redirects=True)
        resp = employee_client.get("/leaves/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers.get("Location", "")

    def test_unauthenticated_logout_redirects(self, client):
        """I13-18 — GET /auth/logout sans session → 302 vers login (login_required)."""
        resp = client.get("/auth/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers.get("Location", "")


# =============================================================================
# TestTwoFactorNeutralized — régression du bug templates 2FA manquants
# =============================================================================

class TestTwoFactorNeutralized:
    """
    Bug réel trouvé le 15/07/2026 : le bouton "Activer" visible sur la page
    profil pointait vers une route qui rendait un template inexistant
    (auth/setup_2fa.html) → crash 500. Neutralisé en flash + redirect plutôt
    que de construire la fonctionnalité complète juste avant la soutenance.
    Ces tests vérifient qu'aucune des 6 routes 2FA ne peut plus jamais
    renvoyer 500, quel que soit l'état du compte.
    """

    def test_setup_2fa_get_redirects_not_crashes(self, employee_client):
        resp = employee_client.get("/auth/2fa/setup", follow_redirects=False)
        assert resp.status_code == 302, (
            f"GET /auth/2fa/setup ne doit plus jamais crasher (500), obtenu {resp.status_code}"
        )

    def test_setup_2fa_post_redirects_not_crashes(self, employee_client):
        resp = employee_client.post("/auth/2fa/setup", data={}, follow_redirects=False)
        assert resp.status_code == 302, (
            f"POST /auth/2fa/setup ne doit plus jamais crasher (500), obtenu {resp.status_code}"
        )

    def test_disable_2fa_get_redirects_not_crashes(self, employee_client):
        resp = employee_client.get("/auth/2fa/disable", follow_redirects=False)
        assert resp.status_code == 302, (
            f"GET /auth/2fa/disable ne doit plus jamais crasher (500), obtenu {resp.status_code}"
        )

    def test_disable_2fa_post_redirects_not_crashes(self, employee_client):
        resp = employee_client.post("/auth/2fa/disable", data={}, follow_redirects=False)
        assert resp.status_code == 302, (
            f"POST /auth/2fa/disable ne doit plus jamais crasher (500), obtenu {resp.status_code}"
        )

    def test_two_factor_get_redirects_not_crashes(self, client):
        resp = client.get("/auth/2fa", follow_redirects=False)
        assert resp.status_code == 302, (
            f"GET /auth/2fa ne doit plus jamais crasher (500), obtenu {resp.status_code}"
        )

    def test_two_factor_post_redirects_not_crashes(self, client):
        resp = client.post("/auth/2fa", data={}, follow_redirects=False)
        assert resp.status_code == 302, (
            f"POST /auth/2fa ne doit plus jamais crasher (500), obtenu {resp.status_code}"
        )
