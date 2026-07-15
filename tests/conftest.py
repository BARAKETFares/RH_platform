"""
Fixtures pytest globales — HR Platform.

Hiérarchie des scopes
─────────────────────
session  : app, db, seed_org, seed_users
           (créés une seule fois par run pytest, contre schema_rh_test)
function : db_session, client, runner
           admin_client / rh_client / manager_client / employee_client
           (recréés pour chaque test)

Isolation DB
────────────
- Base dédiée : schema_rh_test (TEST_DATABASE_URL dans .env)
- Tables créées en début de session (db.create_all), supprimées à la fin
  (db.drop_all).
- db_session : rollback automatique après chaque test.
  Contrainte : dans les tests directs (sans HTTP), préférer flush() à
  commit() pour que le rollback soit efficace. Les tests HTTP (*_client)
  commitent via les routes ; leurs données restent jusqu'à drop_all.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import load_dotenv

# Charge .env avant toute importation d'app pour que TestingConfig
# lise TEST_DATABASE_URL correctement (sinon fallback sur rh_user:rh_pass).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app import create_app
from app.extensions import db as _db


# =============================================================================
# Identifiants des comptes de test
# =============================================================================

TEST_PASSWORD = "Test1234!"

#: (email, mot de passe, nom de rôle) pour chaque profil.
TEST_USERS: dict[str, tuple[str, str, str]] = {
    "admin":    ("admin@fixtures.hr-test.com",    "Admin1234!", "admin"),
    "rh":       ("rh@fixtures.hr-test.com",       TEST_PASSWORD, "rh"),
    "manager":  ("manager@fixtures.hr-test.com",  TEST_PASSWORD, "manager"),
    "employee": ("employee@fixtures.hr-test.com", TEST_PASSWORD, "employee"),
}


# =============================================================================
# Scope SESSION — un seul exemplaire par run pytest
# =============================================================================

@pytest.fixture(scope="session")
def app():
    """Instance Flask en config Testing (DB schema_rh_test, CSRF désactivé)."""
    return create_app("testing")


@pytest.fixture(scope="session")
def db(app):
    """
    Gère le cycle de vie de la base de données de test.

    Séquence :
      1. Repart d'un schéma vierge (DROP/CREATE SCHEMA)
      2. create_all()                  — crée toutes les tables
      3. _seed_roles_and_permissions() — insère les 4 rôles système
      4. yield _db                     — tests s'exécutent
      5. Libère le pool puis DROP SCHEMA — nettoie tout

    Note : les clients de test (function-scoped) laissent des connexions
    'idle in transaction' dans le pool SQLAlchemy. Elles verrouillent les
    tables et bloqueraient DROP SCHEMA CASCADE. On dispose donc le pool
    (engine.dispose) avant chaque DROP, et on neutralise par sécurité toute
    connexion fantôme laissée par un run précédemment interrompu.
    """
    from sqlalchemy import text

    def _reset_public_schema() -> None:
        # Ferme la session courante et vide le pool : aucune connexion ne
        # détient plus de verrou sur les tables → DROP SCHEMA ne bloque pas.
        _db.session.remove()
        _db.engine.dispose()
        with _db.engine.connect() as conn:
            # Filet de sécurité : tue toute connexion fantôme d'un run tué.
            conn.execute(text("""
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND pid != pg_backend_pid()
                  AND state = 'idle in transaction'
            """))
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
            conn.commit()

    with app.app_context():
        _reset_public_schema()
        _db.create_all()
        _seed_roles_and_permissions()
        yield _db
        _reset_public_schema()


@pytest.fixture(scope="session")
def seed_org(app, db):
    """
    Crée Company + Department + Position minimaux (committed une fois).

    Retourne ``{"company_id": int, "dept_id": int, "pos_id": int}``
    utilisable dans les factories Employee des tests.
    """
    with app.app_context():
        from app.models.department import Department
        from app.models.organization import Company
        from app.models.position import Position

        company = Company(name="Test Corp SA", country="FR")
        _db.session.add(company)
        _db.session.flush()

        dept = Department(company_id=company.id, name="Informatique", code="IT-TEST")
        _db.session.add(dept)
        _db.session.flush()

        pos = Position(department_id=dept.id, title="Développeur Test")
        _db.session.add(pos)
        _db.session.commit()

        return {
            "company_id": company.id,
            "dept_id":    dept.id,
            "pos_id":     pos.id,
        }


@pytest.fixture(scope="session")
def seed_users(app, db):
    """
    Crée (ou remet à zéro) un User par rôle (admin / rh / manager / employee).

    Retourne ``{"admin": {"email": ..., "password": ...}, ...}``.
    Idempotent : si le compte existe déjà, le mot de passe est réinitialisé.
    """
    with app.app_context():
        from app.models.role import Role
        from app.models.user import User

        created: dict[str, dict[str, str]] = {}

        for key, (email, password, role_name) in TEST_USERS.items():
            user = User.get_by_email(email)

            if user is None:
                role = _db.session.execute(
                    _db.select(Role).where(Role.name == role_name)
                ).scalar_one_or_none()
                if role is None:
                    pytest.skip(
                        f"Rôle '{role_name}' absent de la DB de test — "
                        "vérifiez _seed_roles_and_permissions()."
                    )
                user = User(
                    email=email,
                    role_id=role.id,
                    _is_active=True,
                    is_email_verified=True,
                    force_password_change=False,
                    preferred_language="fr",
                )
            else:
                user._is_active = True
                user.force_password_change = False

            user.set_password(password)
            _db.session.add(user)
            _db.session.commit()

            created[key] = {"email": email, "password": password}

        return created


# =============================================================================
# Scope FUNCTION — recréés pour chaque test
# =============================================================================

@pytest.fixture(scope="function")
def db_session(app, db):
    """
    Session DB avec rollback automatique en teardown.

    Usage dans les tests directs (sans HTTP) :
        def test_quelque_chose(db_session):
            obj = MonModel(...)
            db_session.add(obj)
            db_session.flush()   # PAS commit — le rollback effacera obj
            assert obj.id is not None
    """
    with app.app_context():
        yield _db.session
        _db.session.rollback()
        _db.session.remove()


@pytest.fixture(scope="session", autouse=True)
def _reset_login_user_cache(app):
    """Vide g._login_user avant chaque requête HTTP de test.

    En Flask 3.x, `g` est stocké dans l'AppContext (partagé entre toutes les
    requêtes qui réutilisent le même contexte). Flask-Login met en cache
    current_user dans g._login_user. Sans ce reset, un utilisateur authentifié
    dans un test précédent (admin_client, etc.) reste visible dans g pour les
    requêtes suivantes — y compris celles du client non authentifié.
    """
    from flask import g as flask_g

    @app.before_request
    def _clear_login_cache() -> None:
        flask_g.pop("_login_user", None)


@pytest.fixture(scope="function")
def client(app):
    """Client HTTP Flask non authentifié (sans preserve_context)."""
    return app.test_client()


@pytest.fixture(scope="function")
def runner(app):
    """Runner CLI Flask (pour tester les commandes Click)."""
    return app.test_cli_runner()


# =============================================================================
# Clients authentifiés par rôle
# =============================================================================

def _login(c, email: str, password: str) -> None:
    """Authentifie le client de test via POST /auth/login."""
    resp = c.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302), (
        f"Login échoué pour {email!r} — HTTP {resp.status_code}"
    )
    if resp.status_code == 302:
        c.get(resp.headers["Location"], follow_redirects=True)


@pytest.fixture(scope="function")
def admin_client(app, seed_users):
    """Client de test connecté en tant qu'admin."""
    creds = seed_users["admin"]
    c = app.test_client()
    _login(c, creds["email"], creds["password"])
    yield c


@pytest.fixture(scope="function")
def rh_client(app, seed_users):
    """Client de test connecté en tant que RH."""
    creds = seed_users["rh"]
    c = app.test_client()
    _login(c, creds["email"], creds["password"])
    yield c


@pytest.fixture(scope="function")
def manager_client(app, seed_users):
    """Client de test connecté en tant que manager."""
    creds = seed_users["manager"]
    c = app.test_client()
    _login(c, creds["email"], creds["password"])
    yield c


@pytest.fixture(scope="function")
def employee_client(app, seed_users):
    """Client de test connecté en tant qu'employé."""
    creds = seed_users["employee"]
    c = app.test_client()
    _login(c, creds["email"], creds["password"])
    yield c


# =============================================================================
# Helpers privés
# =============================================================================

def _seed_roles_and_permissions() -> None:
    """
    Insère les rôles système et leurs permissions dans la DB de test.

    Miroir de ``flask seed-init`` (manage.py) — maintenir les deux en
    cohérence si des permissions sont ajoutées.
    Idempotent : ignore les entrées déjà présentes.
    """
    from app.models.role import Permission, Role, RolePermission

    ALL_PERMISSIONS: list[tuple[str, str, str, str]] = [
        ("employees.read",       "employees",   "read",     "Lire les fiches employés"),
        ("employees.write",      "employees",   "write",    "Créer / modifier des employés"),
        ("employees.delete",     "employees",   "delete",   "Désactiver / supprimer un employé"),
        ("leaves.read",          "leaves",      "read",     "Voir les demandes d'absence"),
        ("leaves.write",         "leaves",      "write",    "Soumettre une demande d'absence"),
        ("leaves.approve",       "leaves",      "approve",  "Approuver / rejeter une demande"),
        ("leaves.adjust",        "leaves",      "adjust",   "Ajuster manuellement un solde de congés"),
        ("performance.read",     "performance", "read",     "Voir les évaluations"),
        ("performance.write",    "performance", "write",    "Créer / modifier des évaluations"),
        ("performance.finalize", "performance", "finalize", "Finaliser une évaluation"),
        ("payroll.read",         "payroll",     "read",     "Consulter les données de paie"),
        ("payroll.write",        "payroll",     "write",    "Saisir les éléments de paie"),
        ("contracts.read",       "contracts",   "read",     "Voir les contrats"),
        ("contracts.write",      "contracts",   "write",    "Créer / modifier des contrats"),
        ("admin.users",          "admin",       "users",    "Gérer les comptes utilisateurs"),
        ("admin.roles",          "admin",       "roles",    "Gérer les rôles et permissions"),
        ("admin.org",            "admin",       "org",      "Gérer l'organisation"),
        ("admin.audit",          "admin",       "audit",    "Consulter le journal d'audit"),
    ]

    perm_map: dict[str, Permission] = {}
    for code, module, action, description in ALL_PERMISSIONS:
        perm = _db.session.execute(
            _db.select(Permission).where(Permission.code == code)
        ).scalar_one_or_none()
        if perm is None:
            perm = Permission(
                code=code, module=module, action=action, description=description
            )
            _db.session.add(perm)
            _db.session.flush()
        perm_map[code] = perm

    ROLES: list[tuple[str, str, str, list[str]]] = [
        (
            Role.EMPLOYEE, "Employé", "Accès espace personnel.",
            ["leaves.read", "leaves.write", "performance.read"],
        ),
        (
            Role.MANAGER, "Manager", "Gestion équipe directe.",
            [
                "employees.read",
                "leaves.read", "leaves.write", "leaves.approve",
                "performance.read", "performance.write",
                "contracts.read",
            ],
        ),
        (
            Role.RH, "Ressources Humaines", "Gestion RH complète.",
            [
                "employees.read", "employees.write", "employees.delete",
                "leaves.read", "leaves.write", "leaves.approve", "leaves.adjust",
                "performance.read", "performance.write", "performance.finalize",
                "payroll.read",
                "contracts.read", "contracts.write",
                "admin.org",
            ],
        ),
        (
            Role.ADMIN, "Administrateur", "Accès complet.",
            list(perm_map.keys()),
        ),
    ]

    for name, label, description, perm_codes in ROLES:
        role = _db.session.execute(
            _db.select(Role).where(Role.name == name)
        ).scalar_one_or_none()
        if role is None:
            role = Role(name=name, label=label, description=description, is_system=True)
            _db.session.add(role)
            _db.session.flush()

        existing_perm_ids = {rp.permission_id for rp in role.role_permissions}
        for code in perm_codes:
            perm = perm_map.get(code)
            if perm and perm.id not in existing_perm_ids:
                _db.session.add(RolePermission(role_id=role.id, permission_id=perm.id))
                existing_perm_ids.add(perm.id)

    _db.session.commit()
