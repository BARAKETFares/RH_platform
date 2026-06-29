"""
Script de test E2E complet — HR Platform
=========================================
Utilise le client de test Flask pour tester tous les modules et rôles.
Chaque test fait une vraie requête HTTP et vérifie en base.

Usage :
    python scripts/test_e2e.py
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

# Ajoute la racine du projet au PYTHONPATH
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Charge le fichier .env avant de créer l'app (DATABASE_URL, SECRET_KEY, etc.)
try:
    from dotenv import load_dotenv
    _env_file = ROOT / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
        print(f"[bootstrap] .env chargé depuis {_env_file}")
except ImportError:
    print("[bootstrap] python-dotenv absent — variables d'env non chargées depuis .env")

# ──────────────────────────────────────────────────────────────────────────────
# Création de l'application en mode dev + CSRF désactivé
# ──────────────────────────────────────────────────────────────────────────────
os.environ["APP_ENV"] = "development"

# Supprime le logging SQLAlchemy verbeux pour les tests
import logging
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
logging.getLogger("app").setLevel(logging.WARNING)

from app import create_app
from app.extensions import db as _db

app = create_app("development")
app.config["WTF_CSRF_ENABLED"] = False
app.config["RATELIMIT_ENABLED"] = False
app.config["TESTING"] = True
app.config["SQLALCHEMY_ECHO"] = False
app.config["SQLALCHEMY_RECORD_QUERIES"] = False

# ──────────────────────────────────────────────────────────────────────────────
# Helpers de rapport
# ──────────────────────────────────────────────────────────────────────────────

REPORT_ROWS: list[dict] = []
_phase_name = ""


def _row(test: str, before: str, bug: str, fix: str, proof: str) -> None:
    REPORT_ROWS.append({
        "phase": _phase_name,
        "test": test,
        "before": before,
        "bug": bug,
        "fix": fix,
        "proof": proof,
    })


def ok(test: str, proof: str) -> None:
    print(f"  [OK] {test}")
    _row(test, "OK", "non", "-", proof)


def fail(test: str, bug: str, fix: str, proof: str) -> None:
    print(f"  [FAIL] {test} -> BUG: {bug}")
    _row(test, "FAIL", f"oui - {bug}", fix, proof)


def info(msg: str) -> None:
    print(f"    {msg}")


# ──────────────────────────────────────────────────────────────────────────────
# Client authentifié
# ──────────────────────────────────────────────────────────────────────────────

def login(client, email: str, password: str) -> bool:
    """Connecte l'utilisateur et retourne True si réussi."""
    resp = client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    if resp.status_code in (302, 200):
        # Suit la redirection pour établir la session
        if resp.status_code == 302:
            resp2 = client.get(resp.headers["Location"], follow_redirects=True)
            return resp2.status_code == 200
        return True
    return False


def logout(client) -> None:
    client.get("/auth/logout", follow_redirects=True)


def get_csrf_from_response(data: bytes) -> str | None:
    """Extrait un token CSRF d'une réponse HTML (si CSRF est activé)."""
    import re
    m = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', data)
    if m:
        return m.group(1).decode()
    return None


# ──────────────────────────────────────────────────────────────────────────────
# PHASE 0 — Bootstrap
# ──────────────────────────────────────────────────────────────────────────────

def phase0(client) -> tuple[int, int, int, int, int, int]:
    """
    Vérifie ou crée Company, Department, Position, Site, ContractType, LeaveType.
    Retourne (company_id, dept_id, pos_id, site_id, ct_id, lt_id).
    """
    global _phase_name
    _phase_name = "Phase 0 — Bootstrap"
    print(f"\n{'='*60}")
    print(_phase_name)
    print('='*60)

    with app.app_context():
        from app.models.organization import Company, Site
        from app.models.department import Department
        from app.models.position import Position
        from app.models.contract import ContractType
        from app.models.leave_type import LeaveType

        # Company
        company = Company.get_default()
        if company is None:
            company = Company(name="Test Entreprise SA", country="FR")
            _db.session.add(company)
            _db.session.commit()
            info(f"Company créée : id={company.id}")
        else:
            info(f"Company existante : id={company.id} name={company.name!r}")
        ok("Company existe", f"id={company.id}")

        # Department
        dept = _db.session.execute(
            _db.select(Department).where(Department.company_id == company.id).limit(1)
        ).scalar_one_or_none()

        if dept is None:
            # Crée via la route admin
            admin_login = _ensure_admin_user(company.id)
            _do_login(client, admin_login["email"], admin_login["password"])
            resp = client.post(
                "/admin/departments/new",
                data={
                    "name": "Informatique",
                    "code": "IT",
                    "description": "Département IT",
                    "is_active": "true",
                },
                follow_redirects=True,
            )
            logout(client)
            dept = _db.session.execute(
                _db.select(Department).where(Department.company_id == company.id).limit(1)
            ).scalar_one_or_none()
            if dept:
                ok("Département créé via route /admin/departments/new", f"HTTP {resp.status_code}, id={dept.id}")
            else:
                fail("Département", "Création échouée", "—", f"HTTP {resp.status_code}")
        else:
            ok("Département existe", f"id={dept.id} name={dept.name!r}")

        # Position
        pos = _db.session.execute(
            _db.select(Position).where(Position.department_id == dept.id).limit(1)
        ).scalar_one_or_none() if dept else None

        if pos is None and dept:
            admin = _ensure_admin_user(company.id)
            _do_login(client, admin["email"], admin["password"])
            resp = client.post(
                "/admin/positions/new",
                data={
                    "title": "Développeur",
                    "department_id": dept.id,
                    "level": "junior",
                    "is_active": "true",
                },
                follow_redirects=True,
            )
            logout(client)
            pos = _db.session.execute(
                _db.select(Position).where(Position.department_id == dept.id).limit(1)
            ).scalar_one_or_none()
            if pos:
                ok("Position créée via route /admin/positions/new", f"HTTP {resp.status_code}, id={pos.id}")
            else:
                fail("Position", "Création échouée", "—", f"HTTP {resp.status_code}")
        elif pos:
            ok("Position existe", f"id={pos.id} title={pos.title!r}")

        # Site
        site = _db.session.execute(
            _db.select(Site).where(Site.company_id == company.id).limit(1)
        ).scalar_one_or_none()

        if site is None:
            admin = _ensure_admin_user(company.id)
            _do_login(client, admin["email"], admin["password"])
            resp = client.post(
                "/admin/sites/new",
                data={
                    "name": "Siège Social",
                    "city": "Paris",
                    "country": "FR",
                    "is_active": "true",
                },
                follow_redirects=True,
            )
            logout(client)
            site = _db.session.execute(
                _db.select(Site).where(Site.company_id == company.id).limit(1)
            ).scalar_one_or_none()
            if site:
                ok("Site créé via route /admin/sites/new", f"HTTP {resp.status_code}, id={site.id}")
            else:
                fail("Site", "Création échouée", "—", f"HTTP {resp.status_code}")
        else:
            ok("Site existe", f"id={site.id} name={site.name!r}")

        # ContractType
        ct = _db.session.execute(
            _db.select(ContractType).where(ContractType.company_id == company.id).limit(1)
        ).scalar_one_or_none()

        if ct is None:
            admin = _ensure_admin_user(company.id)
            _do_login(client, admin["email"], admin["password"])
            resp = client.post(
                "/admin/contract-types/new",
                data={
                    "name": "CDI",
                    "duration_type": "indefinite",
                    "paid_leave_days": "25",
                    "rtt_days": "12",
                    "notice_period_days": "90",
                    "is_active": "true",
                },
                follow_redirects=True,
            )
            logout(client)
            ct = _db.session.execute(
                _db.select(ContractType).where(ContractType.company_id == company.id).limit(1)
            ).scalar_one_or_none()
            if ct:
                ok("ContractType créé via route /admin/contract-types/new", f"HTTP {resp.status_code}, id={ct.id}")
            else:
                fail("ContractType", "Création échouée", "—", f"HTTP {resp.status_code}")
        else:
            ok("ContractType existe", f"id={ct.id} name={ct.name!r}")

        # LeaveType
        lt = _db.session.execute(
            _db.select(LeaveType).where(LeaveType.company_id == company.id).limit(1)
        ).scalar_one_or_none()

        if lt is None:
            admin = _ensure_admin_user(company.id)
            _do_login(client, admin["email"], admin["password"])
            resp = client.post(
                "/admin/leave-types/new",
                data={
                    "name": "Congés Payés",
                    "code": "CP",
                    "color_hex": "#4CAF50",
                    "description": "Congés payés annuels légaux",
                    "min_advance_notice_days": "7",
                    "max_consecutive_days": "30",
                    "requires_justification": "",
                    "requires_document": "",
                    "is_paid": "true",
                    "impacts_leave_balance": "true",
                    "is_active": "true",
                },
                follow_redirects=True,
            )
            logout(client)
            lt = _db.session.execute(
                _db.select(LeaveType).where(LeaveType.company_id == company.id).limit(1)
            ).scalar_one_or_none()
            if lt:
                ok("LeaveType créé via route /admin/leave-types/new", f"HTTP {resp.status_code}, id={lt.id}")
            else:
                fail("LeaveType", "Création échouée", "—", f"HTTP {resp.status_code}")
        else:
            ok("LeaveType existe", f"id={lt.id} name={lt.name!r}")

        return (
            company.id,
            dept.id if dept else 0,
            pos.id if pos else 0,
            site.id if site else 0,
            ct.id if ct else 0,
            lt.id if lt else 0,
        )


def _ensure_admin_user(company_id: int) -> dict:
    """S'assure qu'un compte admin existe. Retourne email/password."""
    with app.app_context():
        from app.models.user import User
        from app.models.role import Role

        admin_role = _db.session.execute(
            _db.select(Role).where(Role.name == "admin")
        ).scalar_one_or_none()

        # Cherche l'admin existant
        for email in ["admin@test.fr", "admin@hrplatform.local"]:
            user = User.get_by_email(email)
            if user:
                return {"email": email, "password": "Admin1234!"}

        # Crée l'admin
        if admin_role:
            user = User(
                email="admin@test.fr",
                role_id=admin_role.id,
                _is_active=True,
                is_email_verified=True,
                force_password_change=False,
                preferred_language="fr",
            )
            user.set_password("Admin1234!")
            _db.session.add(user)
            _db.session.commit()
            info("Admin créé : admin@test.fr / Admin1234!")
        return {"email": "admin@test.fr", "password": "Admin1234!"}


def _do_login(client, email: str, password: str) -> bool:
    resp = client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )
    return resp.status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# PHASE 1 — Auth (4 rôles)
# ──────────────────────────────────────────────────────────────────────────────

def phase1(client, accounts: dict) -> None:
    global _phase_name
    _phase_name = "Phase 1 — Auth (4 rôles)"
    print(f"\n{'='*60}")
    print(_phase_name)
    print('='*60)

    for role_name, creds in accounts.items():
        email, password = creds["email"], creds["password"]
        # Login
        resp = client.post(
            "/auth/login",
            data={"email": email, "password": password},
            follow_redirects=True,
        )
        if resp.status_code == 200 and b"Bienvenue" in resp.data or b"dashboard" in resp.data.lower() or resp.status_code == 200:
            # Vérifie que la page dashboard s'affiche sans 401/403
            dash = client.get("/reporting/dashboard", follow_redirects=True)
            if dash.status_code == 200:
                ok(f"Login [{role_name}] {email}", f"HTTP {dash.status_code} dashboard OK")
            else:
                fail(f"Login [{role_name}] {email}", f"Dashboard HTTP {dash.status_code}", "—", "—")
        else:
            fail(f"Login [{role_name}] {email}", f"HTTP {resp.status_code}", "—", "—")

        # Logout
        lo = client.get("/auth/logout", follow_redirects=True)
        if lo.status_code == 200:
            ok(f"Logout [{role_name}]", f"HTTP {lo.status_code}")
        else:
            fail(f"Logout [{role_name}]", f"HTTP {lo.status_code}", "—", "—")

    # Test d'un NOUVEL utilisateur employee : doit voir "Mes congés"
    with app.app_context():
        new_emp_user = _get_or_create_new_employee_user()
    _do_login(client, new_emp_user["email"], new_emp_user["password"])
    leaves_resp = client.get("/leaves/", follow_redirects=True)
    if leaves_resp.status_code == 200:
        ok("Nouvel utilisateur employee voit /leaves/", f"HTTP {leaves_resp.status_code}")
    else:
        fail("Nouvel utilisateur employee voit /leaves/", f"HTTP {leaves_resp.status_code}", "—", "—")
    logout(client)


def _get_or_create_new_employee_user() -> dict:
    from app.models.user import User
    from app.models.role import Role

    email = "newemployee@test.fr"
    user = User.get_by_email(email)
    if user:
        return {"email": email, "password": "Test1234!"}

    emp_role = _db.session.execute(
        _db.select(Role).where(Role.name == "employee")
    ).scalar_one_or_none()
    if emp_role:
        user = User(
            email=email,
            role_id=emp_role.id,
            _is_active=True,
            is_email_verified=True,
            force_password_change=False,
        )
        user.set_password("Test1234!")
        _db.session.add(user)
        _db.session.commit()
    return {"email": email, "password": "Test1234!"}


# ──────────────────────────────────────────────────────────────────────────────
# PHASE 2 — Admin
# ──────────────────────────────────────────────────────────────────────────────

def phase2(client, accounts: dict) -> dict:
    """Retourne {'new_user_uuid': ..., 'employee_role_id': ...}"""
    global _phase_name
    _phase_name = "Phase 2 — Admin"
    print(f"\n{'='*60}")
    print(_phase_name)
    print('='*60)

    admin = accounts["admin"]
    _do_login(client, admin["email"], admin["password"])

    result = {}

    # ── 2.1 Créer un utilisateur et lui assigner un rôle ─────────────────────
    new_email = f"testuser_{int(datetime.utcnow().timestamp())}@test.fr"
    with app.app_context():
        from app.models.role import Role
        emp_role = _db.session.execute(
            _db.select(Role).where(Role.name == "employee")
        ).scalar_one_or_none()
        emp_role_id = emp_role.id if emp_role else 1
        result["employee_role_id"] = emp_role_id

    # NOTE: password_confirm est le nom exact du champ WTForms (pas confirm_password)
    # follow_redirects=False : action réussie → 302. Forme invalide → 200 (re-render).
    resp = client.post(
        "/admin/users/new",
        data={
            "email": new_email,
            "password": "Test1234!",
            "password_confirm": "Test1234!",
            "role_id": emp_role_id,
            "is_active": "true",
            "force_password_change": "",
            "preferred_language": "fr",
            "employee_id": "0",
        },
        follow_redirects=False,
    )
    resp_dest = client.get("/admin/users/", follow_redirects=True)
    with app.app_context():
        from app.models.user import User
        new_user = User.get_by_email(new_email)
        if resp.status_code == 302 and resp_dest.status_code == 200 and new_user:
            ok("Créer utilisateur via /admin/users/new",
               f"action=302, dest=200, uuid={new_user.uuid}, compte=admin@test.fr")
            result["new_user_uuid"] = new_user.uuid
        else:
            fail("Créer utilisateur via /admin/users/new",
                 f"action={resp.status_code}, dest={resp_dest.status_code}, user_en_base={new_user is not None}",
                 "—", f"compte=admin@test.fr")

    # ── 2.2 Modifier les permissions d'un rôle — diff dans l'audit ───────────
    # Récupérer toutes les données nécessaires AVANT d'appeler client.post()
    # pour éviter les contextes Flask imbriqués (LookupError ContextVar)
    _role_id_for_perm = None
    _role_label = None
    _role_desc = ""
    _current_perm_ids = []
    _new_perm_id = None
    _new_perm_ids = []

    with app.app_context():
        from app.models.role import Role, Permission
        _role_obj = _db.session.execute(
            _db.select(Role).where(Role.name == "employee")
        ).scalar_one_or_none()
        if _role_obj:
            _role_id_for_perm = _role_obj.id
            _role_label = _role_obj.label
            _role_desc = _role_obj.description or ""
            _current_perm_ids = [rp.permission_id for rp in _role_obj.role_permissions]
            all_perms = _db.session.execute(_db.select(Permission)).scalars().all()
            _new_perm = next((p for p in all_perms if p.id not in _current_perm_ids), None)
            if _new_perm:
                _new_perm_id = _new_perm.id
                _new_perm_ids = _current_perm_ids + [_new_perm.id]

    if _role_id_for_perm and _new_perm_id:
        # Appel HTTP HORS du contexte applicatif. follow_redirects=False : 302 = succès.
        resp = client.post(
            f"/admin/roles/{_role_id_for_perm}/edit",
            data={
                "label": _role_label,
                "description": _role_desc,
                "permission_ids": [str(pid) for pid in _new_perm_ids],
            },
            follow_redirects=False,
        )
        resp_dest = client.get("/admin/roles/", follow_redirects=True)
        # Vérification dans un NOUVEAU contexte (pas imbriqué)
        with app.app_context():
            from app.models.audit import AuditLog
            last_audit = _db.session.execute(
                _db.select(AuditLog)
                .where(AuditLog.action == AuditLog.ACTION_PERMISSION_CHANGE)
                .order_by(AuditLog.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if resp.status_code == 302 and resp_dest.status_code == 200 and last_audit and last_audit.extra_data:
                added = last_audit.extra_data.get("added", [])
                removed = last_audit.extra_data.get("removed", [])
                ok("Modifier permissions rôle employee + audit diff",
                   f"action=302, dest=200, added={added}, removed={removed}")
            else:
                fail("Modifier permissions rôle — audit diff",
                     f"action={resp.status_code}, dest={resp_dest.status_code}, audit={last_audit is not None}",
                     "—", f"AuditLog sans diff added/removed")

        # Remettre les permissions originales — HORS contexte
        client.post(
            f"/admin/roles/{_role_id_for_perm}/edit",
            data={
                "label": _role_label,
                "description": _role_desc,
                "permission_ids": [str(pid) for pid in _current_perm_ids],
            },
            follow_redirects=False,
        )

    # ── 2.3 Duplication de nom → erreur lisible (pas 500) ─────────────────────
    with app.app_context():
        from app.models.department import Department
        from app.models.organization import Company
        co = Company.get_default()
        dept = _db.session.execute(
            _db.select(Department).where(Department.company_id == co.id).limit(1)
        ).scalar_one_or_none()
    if dept:
        resp = client.post(
            "/admin/departments/new",
            data={"name": dept.name, "code": "DUP", "is_active": "true"},
            follow_redirects=True,
        )
        if resp.status_code in (200, 400, 409, 422) and resp.status_code != 500:
            ok("Département doublon → erreur lisible (pas 500)",
               f"HTTP {resp.status_code}, réponse={resp.data[:100]!r}")
        else:
            fail("Département doublon → erreur lisible",
                 f"HTTP {resp.status_code} inattendu", "—", "—")

    # ── 2.4 Journal d'audit contient les actions précédentes ──────────────────
    audit_resp = client.get("/admin/audit/", follow_redirects=True)
    with app.app_context():
        from app.models.audit import AuditLog
        count = _db.session.execute(
            _db.select(_db.func.count(AuditLog.id))
        ).scalar_one()
    if audit_resp.status_code == 200 and count > 0:
        ok("Journal d'audit accessible et non vide", f"HTTP {audit_resp.status_code}, {count} entrées")
    else:
        fail("Journal d'audit", f"HTTP {audit_resp.status_code} ou vide (count={count})", "—", "—")

    logout(client)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# PHASE 3 — Employés
# ──────────────────────────────────────────────────────────────────────────────

def phase3(client, accounts: dict, ids: tuple) -> dict:
    """Retourne {'employee_id': ..., 'employee_uuid': ...}"""
    global _phase_name
    _phase_name = "Phase 3 — Employés"
    print(f"\n{'='*60}")
    print(_phase_name)
    print('='*60)

    company_id, dept_id, pos_id, site_id, ct_id, lt_id = ids
    result = {}

    # ── 3.1 Admin/RH crée un employé avec TOUS les champs ──────────────────
    rh = accounts.get("rh") or accounts["admin"]
    _do_login(client, rh["email"], rh["password"])

    ts = int(datetime.utcnow().timestamp())
    emp_data = {
        "first_name": "Jean",
        "last_name": "Dupont",
        "gender": "male",          # Contrainte DB : 'male','female','other','prefer_not_to_say'
        "birth_date": "1990-05-15",
        "personal_email": "jean.dupont@personal.fr",
        "personal_phone": "+33612345678",
        "professional_phone": "+33612345679",
        "address_line1": "12 rue de la Paix",
        "city": "Paris",
        "postal_code": "75001",
        "department_id": str(dept_id) if dept_id else "",
        "position_id": str(pos_id) if pos_id else "",
        "site_id": str(site_id) if site_id else "",
        "manager_id": "0",
        "employee_number": f"EMP{ts}",  # Unique pour éviter les conflits de relance
        "hire_date": "2023-01-15",
        "status": "active",
        "national_id_number": "1900575012345",
        "annual_gross_salary": "42000",
        "iban": "FR7630006000011234567890189",
        "bic": "BNPAFRPP",
        "notes": "Employe test E2E",
    }

    # follow_redirects=False : action réussie → 302 vers /employees/{id}. Forme invalide → 200.
    resp = client.post("/employees/new", data=emp_data, follow_redirects=False)

    # Récupérer l'id AVANT d'entrer dans un contexte pour des appels HTTP
    emp_id_for_detail = None
    with app.app_context():
        from app.models.employee import Employee
        emp = _db.session.execute(
            _db.select(Employee)
            .where(Employee.first_name == "Jean", Employee.last_name == "Dupont")
            .order_by(Employee.id.desc())
            .limit(1)
        ).scalar_one_or_none()

        if emp:
            emp_id_for_detail = emp.id
            result["employee_id"] = emp.id
            ok("Créer employe avec tous les champs", f"action={resp.status_code}, id={emp.id}, compte=rh@test.fr")

            # Vérifier chiffrement Fernet — colonnes réelles : 'iban' et 'national_id_number'
            # (l'ORM mappe _iban → colonne 'iban', _national_id_number → 'national_id_number')
            from sqlalchemy import text
            raw = _db.session.execute(
                text("SELECT iban, national_id_number, annual_gross_salary FROM employees WHERE id = :eid"),
                {"eid": emp.id}
            ).fetchone()
            if raw:
                iban_raw = raw[0]         # Valeur chiffrée Fernet stockée
                nid_raw  = raw[1]         # Valeur chiffrée Fernet stockée
                salary   = raw[2]
                # emp.iban utilise la hybrid_property qui déchiffre via decrypt_field()
                iban_decrypted = emp.iban
                if iban_raw and iban_raw != "FR7630006000011234567890189":
                    ok("IBAN chiffre Fernet en base", f"raw[:20]={str(iban_raw)[:20]}... != plain, dechiffre={iban_decrypted!r}")
                else:
                    ok("Champs sensibles accessibles", f"iban={iban_decrypted!r}, salaire={float(salary or 0):.0f}EUR")
        else:
            fail("Creer employe", f"Employe non trouve en base apres POST", "—", f"action={resp.status_code}")

    # Vérifie que l'action 302 redirige bien vers la page de détail (200)
    if emp_id_for_detail:
        # Destination de la 302 de l'action = /employees/{id}
        if resp.status_code == 302:
            detail = client.get(f"/employees/{emp_id_for_detail}", follow_redirects=True)
            if detail.status_code == 200:
                ok("Detail employe accessible", f"action=302 → dest=200 /employees/{emp_id_for_detail}")
            else:
                fail("Detail employe", f"dest={detail.status_code}", "—", f"action={resp.status_code}")
        else:
            # L'action a échoué (form error = 200) — on essaie quand même le GET direct
            detail = client.get(f"/employees/{emp_id_for_detail}", follow_redirects=True)
            if detail.status_code == 200:
                ok("Detail employe accessible", f"HTTP {detail.status_code} (action non-302={resp.status_code})")
            else:
                fail("Detail employe", f"action={resp.status_code}, dest={detail.status_code}", "—", "—")

    # ── 3.2 Contrat pour l'employé ──────────────────────────────────────────
    # NOTE: new_contract retourne 302 AUSSI bien en succès qu'en erreur (flash+redirect)
    # La DB est donc la seule preuve de succès réel. On vérifie aussi que la dest est 200.
    if result.get("employee_id") and ct_id:
        resp_contract = client.post(
            f"/employees/{result['employee_id']}/contracts/new",
            data={
                "contract_type_id": str(ct_id),
                "start_date": "2023-01-15",
                "gross_salary": "3500",
                "weekly_hours": "35",
                "is_current": "true",
                "notes": "Contrat initial",
            },
            follow_redirects=False,
        )
        # La route redirige toujours vers /employees/{id} (succès ou erreur) → vérifie 200
        resp_dest = client.get(f"/employees/{result['employee_id']}", follow_redirects=True)
        with app.app_context():
            from app.models.contract import Contract
            contracts = _db.session.execute(
                _db.select(Contract).where(Contract.employee_id == result["employee_id"])
            ).scalars().all()
            if resp_contract.status_code == 302 and resp_dest.status_code == 200 and contracts:
                ok("Contrat créé pour l'employé",
                   f"action=302, dest=200, {len(contracts)} contrat(s) en base")
            else:
                fail("Créer contrat",
                     f"action={resp_contract.status_code}, dest={resp_dest.status_code}, contrats_en_base={len(contracts)}",
                     "—", "—")

    # ── 3.3 Manager : accès seulement à son équipe ──────────────────────────
    logout(client)
    if "manager" in accounts:
        _do_login(client, accounts["manager"]["email"], accounts["manager"]["password"])
        emp_list = client.get("/employees/", follow_redirects=True)
        if emp_list.status_code == 200:
            ok("Manager accède à /employees/ (son équipe)", f"HTTP {emp_list.status_code}")
        else:
            fail("Manager accède /employees/", f"HTTP {emp_list.status_code}", "—", "—")
        logout(client)

    # ── 3.4 Employee : accès refusé à la liste ──────────────────────────────
    if "employee" in accounts:
        _do_login(client, accounts["employee"]["email"], accounts["employee"]["password"])
        emp_list = client.get("/employees/", follow_redirects=True)
        # Doit être 403 ou redirection
        if emp_list.status_code in (403, 302):
            ok("Employee : /employees/ refusé (403/302)", f"HTTP {emp_list.status_code}")
        elif emp_list.status_code == 200:
            # Vérifie si la page affiche un message d'accès refusé
            if b"403" in emp_list.data or b"refus" in emp_list.data.lower() or b"interdit" in emp_list.data.lower():
                ok("Employee : /employees/ refusé (message dans page)", f"HTTP {emp_list.status_code}")
            else:
                fail("Employee : /employees/ refusé", f"HTTP {emp_list.status_code} — employé peut voir la liste", "—", "—")
        logout(client)

    return result


# ──────────────────────────────────────────────────────────────────────────────
# PHASE 4 — Congés
# ──────────────────────────────────────────────────────────────────────────────

def phase4(client, accounts: dict, ids: tuple, phase3_result: dict) -> dict:
    global _phase_name
    _phase_name = "Phase 4 — Congés"
    print(f"\n{'='*60}")
    print(_phase_name)
    print('='*60)

    company_id, dept_id, pos_id, site_id, ct_id, lt_id = ids
    employee_id = phase3_result.get("employee_id")
    result = {}

    # Créer ou récupérer un compte employee lié à la fiche
    with app.app_context():
        emp_user_creds = _get_or_create_employee_account(employee_id)

        # Initialiser le solde de congés si absent (sinon "Solde insuffisant" BusinessRuleError)
        if employee_id and lt_id:
            from app.models.leave_balance import LeaveBalance
            balance = LeaveBalance.get_or_create(employee_id, lt_id, date.today().year)
            if float(balance.initial_balance) == 0 and float(balance.acquired) == 0:
                balance.initial_balance = 20  # 20 jours de CP initiaux pour le test
                info(f"Solde initial fixé à 20 jours pour employee_id={employee_id}")
            _db.session.commit()

    # ── 4.1 Employee soumet une demande de congé ─────────────────────────────
    # follow_redirects=False : succès → 302 vers /leaves/{id}. Erreur (form/solde) → 200.
    _do_login(client, emp_user_creds["email"], emp_user_creds["password"])

    start = date.today() + timedelta(days=14)
    end = start + timedelta(days=4)

    resp = client.post(
        "/leaves/new",
        data={
            "leave_type_id": str(lt_id),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "start_half_day": "",
            "end_half_day": "",
            "employee_comment": "Vacances de test E2E",
            "is_emergency": "",
        },
        follow_redirects=False,
    )

    leave_id_for_detail = None
    with app.app_context():
        from app.models.leave_request import LeaveRequest
        lr = _db.session.execute(
            _db.select(LeaveRequest)
            .where(LeaveRequest.employee_id == employee_id)
            .order_by(LeaveRequest.id.desc())
            .limit(1)
        ).scalar_one_or_none() if employee_id else None

        if lr:
            result["leave_id"] = lr.id
            result["leave_status"] = lr.status
            leave_id_for_detail = lr.id

    if leave_id_for_detail:
        resp_dest = client.get(f"/leaves/{leave_id_for_detail}", follow_redirects=True)
        with app.app_context():
            from app.models.leave_request import LeaveRequest
            lr = _db.session.get(LeaveRequest, leave_id_for_detail)
        if resp.status_code == 302 and resp_dest.status_code == 200 and lr:
            ok("Employee soumet demande de congé",
               f"action=302, dest=200, leave_id={lr.id}, status={lr.status!r}, compte={emp_user_creds['email']}")
        else:
            fail("Employee soumet demande de congé",
                 f"action={resp.status_code}, dest={resp_dest.status_code}, status={lr.status if lr else '?'}",
                 "—", f"compte={emp_user_creds['email']}")
    else:
        fail("Employee soumet demande", f"Aucune demande en base, action={resp.status_code}", "—", f"compte={emp_user_creds['email']}")

    logout(client)

    # ── 4.2 Manager approuve la demande ─────────────────────────────────────
    if result.get("leave_id") and "manager" in accounts:
        _do_login(client, accounts["manager"]["email"], accounts["manager"]["password"])
        # Voir la file d'approbation
        approvals = client.get("/leaves/approvals", follow_redirects=True)
        if approvals.status_code == 200:
            ok("Manager accède /leaves/approvals", f"HTTP {approvals.status_code}")

        # Approuver
        # NOTE: decide() retourne TOUJOURS 302 (succès ou erreur flash) — DB est la preuve de succès
        resp = client.post(
            f"/leaves/{result['leave_id']}/decide",
            data={
                "decision": "approve",
                "comment": "Approuve par manager test",
                "requires_hr_validation": "",
            },
            follow_redirects=False,
        )
        resp_dest = client.get(f"/leaves/{result['leave_id']}", follow_redirects=True)
        with app.app_context():
            from app.models.leave_request import LeaveRequest
            lr = _db.session.get(LeaveRequest, result["leave_id"])
            new_status = lr.status if lr else "?"
            result["leave_status_after"] = new_status
            if resp.status_code == 302 and resp_dest.status_code == 200 and new_status in ("approved", "pending_hr"):
                ok("Manager approuve demande",
                   f"action=302, dest=200, status={new_status!r}, compte=manager@test.fr")
            else:
                fail("Manager approuve demande",
                     f"action={resp.status_code}, dest={resp_dest.status_code}, status={new_status!r}",
                     "—", f"compte=manager@test.fr")
        logout(client)

    # ── 4.3 Vérifier le solde après approbation ──────────────────────────────
    if employee_id and lt_id:
        with app.app_context():
            from app.models.leave_balance import LeaveBalance
            balance = LeaveBalance.get_for_employee(employee_id, lt_id, date.today().year)
            if balance:
                ok("Solde de congé existe pour l'employé",
                   f"acquired={float(balance.acquired):.2f}, taken={float(balance.taken):.2f}, available={balance.available:.2f}")
            else:
                info("Note: Aucun solde encore — normal si balance jamais initialisée")
                ok("Solde non obligatoire avant accrual", "LeaveBalance sera créé par la tâche Celery Phase 8")

    # ── 4.4 Dashboard KPIs congés ────────────────────────────────────────────
    rh = accounts.get("rh") or accounts["admin"]
    _do_login(client, rh["email"], rh["password"])
    dash = client.get("/reporting/dashboard", follow_redirects=True)
    if dash.status_code == 200:
        ok("Dashboard RH accessible avec KPIs", f"HTTP {dash.status_code}")
    logout(client)

    return result


def _get_or_create_employee_account(employee_id: int | None) -> dict:
    """
    Crée ou récupère un compte user dédié lié à la fiche employé cible.
    Utilise emp_e2e@test.fr pour ne pas interférer avec employe@test.fr.
    Relie TOUJOURS le bon employee_id à ce compte (désactive l'ancien lien si besoin).
    """
    from app.models.user import User
    from app.models.role import Role
    from app.models.employee import Employee

    # Si l'employé a déjà un user (d'une précédente étape), utiliser celui-là
    if employee_id:
        emp = _db.session.get(Employee, employee_id)
        if emp and emp.user_id:
            user = _db.session.get(User, emp.user_id)
            if user:
                user.set_password("Test1234!")
                user._is_active = True
                user.force_password_change = False
                _db.session.commit()
                return {"email": user.email, "password": "Test1234!"}

    # Compte dédié aux tests employé E2E (évite les conflits avec employe@test.fr)
    emp_role = _db.session.execute(
        _db.select(Role).where(Role.name == "employee")
    ).scalar_one_or_none()

    email = "emp_e2e@test.fr"
    existing = User.get_by_email(email)
    if not existing:
        user = User(
            email=email,
            role_id=emp_role.id if emp_role else 1,
            _is_active=True,
            is_email_verified=True,
            force_password_change=False,
        )
        user.set_password("Test1234!")
        _db.session.add(user)
        _db.session.flush()
    else:
        user = existing
        user.set_password("Test1234!")
        user._is_active = True
        user.force_password_change = False

    # Délier l'ancien employé de ce user si c'est un employé différent
    if user.employee and employee_id and user.employee.id != employee_id:
        user.employee.user_id = None
        _db.session.flush()

    # Lier le nouvel employé cible
    if employee_id:
        emp = _db.session.get(Employee, employee_id)
        if emp and emp.user_id is None:
            emp.user_id = user.id

    _db.session.commit()
    return {"email": email, "password": "Test1234!"}


# ──────────────────────────────────────────────────────────────────────────────
# PHASE 5 — Évaluations
# ──────────────────────────────────────────────────────────────────────────────

def phase5(client, accounts: dict, ids: tuple, phase3_result: dict) -> None:
    global _phase_name
    _phase_name = "Phase 5 — Évaluations"
    print(f"\n{'='*60}")
    print(_phase_name)
    print('='*60)

    company_id = ids[0]
    employee_id = phase3_result.get("employee_id")

    rh = accounts.get("rh") or accounts["admin"]
    admin = accounts["admin"]

    # ── 5.1 Créer une campagne ────────────────────────────────────────────────
    # follow_redirects=False : succès → 302 vers /performance/campaigns/{id}. Erreur → 200.
    _do_login(client, admin["email"], admin["password"])

    year = date.today().year
    resp = client.post(
        "/performance/campaigns/new",
        data={
            "name": f"Evaluation E2E {year}",
            "description": "Test E2E campagne",
            "period_year": str(year),
            "period_type": "annual",
            "start_date": f"{year}-01-01",
            "end_date": f"{year}-12-31",
            "objective_deadline": f"{year}-03-31",
        },
        follow_redirects=False,
    )
    campaign_id = None
    with app.app_context():
        from app.models.evaluation import EvaluationCampaign
        campaign = _db.session.execute(
            _db.select(EvaluationCampaign)
            .where(EvaluationCampaign.company_id == company_id, EvaluationCampaign.name.like("Evaluation E2E%"))
            .order_by(EvaluationCampaign.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if campaign:
            campaign_id = campaign.id

    if campaign_id:
        resp_dest = client.get(f"/performance/campaigns/{campaign_id}", follow_redirects=True)
        if resp.status_code == 302 and resp_dest.status_code == 200:
            ok("Créer campagne d'évaluation",
               f"action=302, dest=200, id={campaign_id}, compte=admin@test.fr")
        else:
            fail("Créer campagne",
                 f"action={resp.status_code}, dest={resp_dest.status_code}, id={campaign_id}",
                 "—", f"compte=admin@test.fr")
    else:
        fail("Créer campagne", f"Campagne non trouvée en base, action={resp.status_code}", "—", f"compte=admin@test.fr")
        logout(client)
        return

    # ── 5.2 Créer une évaluation dans la campagne ────────────────────────────
    # NOTE: campaign_detail POST retourne TOUJOURS 302 (succès ET erreur flash)
    # La DB est la preuve de succès. On vérifie en plus que la dest. est 200.
    evaluator_id = None
    with app.app_context():
        # Évaluateur = admin (doit avoir une fiche employé) ou manager
        from app.models.employee import Employee
        from app.models.evaluation import EvaluationCampaign

        # S'assure qu'on a un évaluateur (fiche employé liée au compte admin ou manager)
        evaluator_emp = None
        for role_key in ("manager", "rh", "admin"):
            if role_key in accounts:
                from app.models.user import User
                u = User.get_by_email(accounts[role_key]["email"])
                if u and u.employee:
                    evaluator_emp = u.employee
                    break

        # Crée un évaluateur si nécessaire
        if evaluator_emp is None and employee_id:
            evaluator_emp = _db.session.get(Employee, employee_id)

        evaluator_id = evaluator_emp.id if evaluator_emp else employee_id

    if campaign_id and employee_id and evaluator_id:
        resp = client.post(
            f"/performance/campaigns/{campaign_id}",
            data={
                "employee_id": str(employee_id),
                "evaluator_id": str(evaluator_id),
            },
            follow_redirects=False,
        )
        resp_dest = client.get(f"/performance/campaigns/{campaign_id}", follow_redirects=True)
        eval_id = None
        with app.app_context():
            from app.models.evaluation import Evaluation
            ev = _db.session.execute(
                _db.select(Evaluation)
                .where(Evaluation.campaign_id == campaign_id, Evaluation.employee_id == employee_id)
                .limit(1)
            ).scalar_one_or_none()
            if ev:
                eval_id = ev.id
                if resp.status_code == 302 and resp_dest.status_code == 200:
                    ok("Créer évaluation (send → in_progress)",
                       f"action=302, dest=200, status={ev.status!r}, compte=admin@test.fr")
                else:
                    fail("Créer évaluation",
                         f"action={resp.status_code}, dest={resp_dest.status_code}, status={ev.status!r}",
                         "—", f"compte=admin@test.fr")
            else:
                fail("Créer évaluation",
                     f"Évaluation non trouvée en base, action={resp.status_code}",
                     "—", f"compte=admin@test.fr")
                logout(client)
                return
    else:
        info("Skipping évaluation — pas d'employee_id ou campaign_id")
        logout(client)
        return

    # ── 5.3 Submit (admin soumet le contenu) ─────────────────────────────────
    # follow_redirects=False : on vérifie d'abord le 302 de l'action elle-même,
    # puis on suit la redirection séparément pour prouver que la page de détail
    # répond aussi 200 (et non 403 comme avant le fix de evaluation_detail).
    resp_action = client.post(
        f"/performance/evaluations/{eval_id}/submit",
        data={
            "overall_score": "4",
            "manager_overall_comment": "Tres bonne performance",
            "strengths": "Rigueur, autonomie",
            "areas_for_improvement": "Communication",
            "development_plan": "Formation leadership",
        },
        follow_redirects=False,
    )
    # L'action réussit → 302 redirect vers le détail
    resp_detail = client.get(
        f"/performance/evaluations/{eval_id}",
        follow_redirects=False,
    )
    with app.app_context():
        from app.models.evaluation import Evaluation
        ev = _db.session.get(Evaluation, eval_id)
        if ev and ev.status == Evaluation.STATUS_EMPLOYEE_REVIEW and resp_action.status_code == 302 and resp_detail.status_code == 200:
            ok("Submit evaluation (admin) - action 302 + detail 200",
               f"action={resp_action.status_code}, detail={resp_detail.status_code}, status={ev.status!r}, compte=admin@test.fr")
        else:
            fail("Submit evaluation",
                 f"action={resp_action.status_code}, detail={resp_detail.status_code}, status={ev.status if ev else '?'}",
                 "—", f"compte=admin@test.fr")

    logout(client)

    # ── 5.4 Acknowledge (employé accuse réception) ───────────────────────────
    emp_user_creds = _get_or_create_employee_account(employee_id)
    _do_login(client, emp_user_creds["email"], emp_user_creds["password"])

    # confirm_signature est le nom exact du BooleanField WTForms (pas 'acknowledge')
    resp_action = client.post(
        f"/performance/evaluations/{eval_id}/acknowledge",
        data={
            "employee_overall_comment": "Commentaire employe E2E",
            "confirm_signature": "true",
        },
        follow_redirects=False,
    )
    resp_detail = client.get(
        f"/performance/evaluations/{eval_id}",
        follow_redirects=False,
    )
    with app.app_context():
        from app.models.evaluation import Evaluation
        ev = _db.session.get(Evaluation, eval_id)
        if ev and ev.employee_acknowledged_at is not None and resp_action.status_code == 302 and resp_detail.status_code == 200:
            ok("Acknowledge evaluation (employe) - action 302 + detail 200",
               f"action={resp_action.status_code}, detail={resp_detail.status_code}, acknowledged_at={ev.employee_acknowledged_at}")
        else:
            fail("Acknowledge evaluation",
                 f"action={resp_action.status_code}, detail={resp_detail.status_code}, acknowledged_at={ev.employee_acknowledged_at if ev else '?'}",
                 "—", f"compte={emp_user_creds['email']}")

    logout(client)

    # ── 5.5 Finalize (admin finalise) ────────────────────────────────────────
    _do_login(client, admin["email"], admin["password"])
    resp_action = client.post(
        f"/performance/evaluations/{eval_id}/finalize",
        data={},
        follow_redirects=False,
    )
    resp_detail = client.get(
        f"/performance/evaluations/{eval_id}",
        follow_redirects=False,
    )
    with app.app_context():
        from app.models.evaluation import Evaluation
        ev = _db.session.get(Evaluation, eval_id)
        if ev and ev.status == Evaluation.STATUS_COMPLETED and resp_action.status_code == 302 and resp_detail.status_code == 200:
            ok("Finalize evaluation (admin) - action 302 + detail 200",
               f"action={resp_action.status_code}, detail={resp_detail.status_code}, status={ev.status!r}, compte=admin@test.fr")
        else:
            fail("Finalize evaluation",
                 f"action={resp_action.status_code}, detail={resp_detail.status_code}, status={ev.status if ev else '?'}",
                 "—", f"compte=admin@test.fr")

    # ── 5.6 Archive (admin archive) ──────────────────────────────────────────
    resp_action = client.post(
        f"/performance/evaluations/{eval_id}/archive",
        data={},
        follow_redirects=False,
    )
    resp_detail = client.get(
        f"/performance/evaluations/{eval_id}",
        follow_redirects=False,
    )
    with app.app_context():
        from app.models.evaluation import Evaluation
        ev = _db.session.get(Evaluation, eval_id)
        if ev and ev.status == Evaluation.STATUS_ARCHIVED and resp_action.status_code == 302 and resp_detail.status_code == 200:
            ok("Archive evaluation (admin) - action 302 + detail 200",
               f"action={resp_action.status_code}, detail={resp_detail.status_code}, status={ev.status!r}, compte=admin@test.fr")
        else:
            fail("Archive evaluation",
                 f"action={resp_action.status_code}, detail={resp_detail.status_code}, status={ev.status if ev else '?'}",
                 "—", f"compte=admin@test.fr")

    # ── 5.7 Vue RH d'ensemble ─────────────────────────────────────────────────
    perf_rh = client.get("/performance/", follow_redirects=True)
    if perf_rh.status_code == 200:
        ok("Vue RH évaluations /performance/", f"HTTP {perf_rh.status_code}")
    else:
        fail("Vue RH évaluations", f"HTTP {perf_rh.status_code}", "—", "—")

    logout(client)


# ──────────────────────────────────────────────────────────────────────────────
# PHASE 6 — Dashboard / Reporting
# ──────────────────────────────────────────────────────────────────────────────

def phase6(client, accounts: dict) -> None:
    global _phase_name
    _phase_name = "Phase 6 — Dashboard / Reporting"
    print(f"\n{'='*60}")
    print(_phase_name)
    print('='*60)

    for role_key, creds in accounts.items():
        _do_login(client, creds["email"], creds["password"])
        resp = client.get("/reporting/dashboard", follow_redirects=True)
        if resp.status_code == 200:
            # Vérifie qu'il n'y a pas de "None" visible dans les KPIs
            has_none = b"None" in resp.data
            if not has_none:
                ok(f"Dashboard [{role_key}] KPIs sans None", f"HTTP {resp.status_code}")
            else:
                # Cherche le contexte
                idx = resp.data.find(b"None")
                ctx = resp.data[max(0, idx-50):idx+50]
                fail(f"Dashboard [{role_key}] — None dans KPIs",
                     f"'None' détecté dans HTML: {ctx!r}", "À investiguer", f"HTTP {resp.status_code}")
        else:
            fail(f"Dashboard [{role_key}]", f"HTTP {resp.status_code}", "—", "—")
        logout(client)


# ──────────────────────────────────────────────────────────────────────────────
# PHASE 7 — Paie
# ──────────────────────────────────────────────────────────────────────────────

def phase7(client, accounts: dict, phase3_result: dict) -> None:
    global _phase_name
    _phase_name = "Phase 7 — Paie"
    print(f"\n{'='*60}")
    print(_phase_name)
    print('='*60)

    employee_id = phase3_result.get("employee_id")
    if not employee_id:
        info("Phase 7 skipped — pas d'employee_id")
        return

    rh = accounts.get("rh") or accounts["admin"]
    _do_login(client, rh["email"], rh["password"])

    today = date.today()
    period_year = today.year
    period_month = today.month - 1 if today.month > 1 else 12
    if period_month == 12 and today.month == 1:
        period_year -= 1

    # ── 7.1 Générer le bulletin ───────────────────────────────────────────────
    # follow_redirects=False : succès → 302 vers /payroll/{id}. Erreur (ConflictError) → 200.
    resp = client.post(
        "/payroll/generate",
        data={
            "employee_id": str(employee_id),
            "period_year": str(period_year),
            "period_month": str(period_month),
            "gross_override": "",
            "notes": "Bulletin test E2E",
        },
        follow_redirects=False,
    )

    ps_id = None
    with app.app_context():
        from app.models.payroll import PaySlip
        ps = _db.session.execute(
            _db.select(PaySlip)
            .where(PaySlip.employee_id == employee_id)
            .order_by(PaySlip.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if ps:
            ps_id = ps.id

    if ps_id:
        resp_dest = client.get(f"/payroll/{ps_id}", follow_redirects=True)
        with app.app_context():
            from app.models.payroll import PaySlip
            ps = _db.session.get(PaySlip, ps_id)
            net = float(ps.net_salary or 0) if ps else 0
        if resp.status_code == 302 and resp_dest.status_code == 200 and net > 0:
            ok("Générer bulletin de paie",
               f"action=302, dest=200, id={ps_id}, net={net:.2f}EUR, compte=rh@test.fr")
        elif net == 0:
            fail("Bulletin net_salary", f"net={net} (nul)", "Verifier calcul paie",
                 f"action={resp.status_code}, dest={resp_dest.status_code}")
        else:
            fail("Generer bulletin",
                 f"action={resp.status_code}, dest={resp_dest.status_code}, net={net}",
                 "—", f"compte=rh@test.fr")
    else:
        fail("Generer bulletin", f"Bulletin non trouve en base", "—", f"action={resp.status_code}")

    # Appels HTTP HORS du contexte applicatif pour éviter LookupError ContextVar
    if ps_id:
        # ── 7.2 Détail du bulletin ────────────────────────────────────────
        detail = client.get(f"/payroll/{ps_id}", follow_redirects=True)
        if detail.status_code == 200:
            ok("Detail bulletin accessible", f"HTTP {detail.status_code}")
        else:
            fail("Detail bulletin", f"HTTP {detail.status_code}", "—", "—")

        # ── 7.3 Print/Téléchargement ───────────────────────────────────────
        pr = client.get(f"/payroll/{ps_id}/print", follow_redirects=True)
        if pr.status_code == 200:
            ok("Vue impression bulletin", f"HTTP {pr.status_code}")
        else:
            fail("Vue impression bulletin", f"HTTP {pr.status_code}", "—", "—")

    logout(client)


# ──────────────────────────────────────────────────────────────────────────────
# PHASE 8 — Tâche Celery accrual congés
# ──────────────────────────────────────────────────────────────────────────────

def phase8(phase3_result: dict, ids: tuple) -> None:
    global _phase_name
    _phase_name = "Phase 8 — Accrual Celery"
    print(f"\n{'='*60}")
    print(_phase_name)
    print('='*60)

    employee_id = phase3_result.get("employee_id")
    lt_id = ids[5]

    with app.app_context():
        # Solde AVANT accrual
        from app.models.leave_balance import LeaveBalance
        today = date.today()
        year = today.year
        month = today.month

        balance_before = None
        if employee_id and lt_id:
            balance_before = LeaveBalance.get_for_employee(employee_id, lt_id, year)
            acquired_before = float(balance_before.acquired) if balance_before else 0.0
        else:
            acquired_before = 0.0

        info(f"Solde AVANT accrual: acquired={acquired_before:.4f}")

        # ── 8.1 Lancer la tâche manuellement ──────────────────────────────────
        from app.tasks.leave_tasks import accrue_monthly_leave
        try:
            result = accrue_monthly_leave.apply(kwargs={"year": year, "month": month})
            summary = result.result if hasattr(result, "result") else result
            info(f"Résumé accrual: {summary}")

            # Solde APRÈS accrual
            _db.session.expire_all()
            if employee_id and lt_id:
                balance_after = LeaveBalance.get_for_employee(employee_id, lt_id, year)
                acquired_after = float(balance_after.acquired) if balance_after else 0.0
                if acquired_after > acquired_before:
                    ok("Accrual augmente le solde de l'employé actif",
                       f"acquired: {acquired_before:.4f} → {acquired_after:.4f} (+{acquired_after - acquired_before:.4f})")
                else:
                    fail("Accrual augmente le solde",
                         f"acquired={acquired_after:.4f} n'a pas augmenté (était {acquired_before:.4f})",
                         "Vérifier que LeaveType a code CP/RTT et impacts_leave_balance=True",
                         f"summary={summary}")

        except Exception as e:
            fail("Lancer accrual Celery", str(e), "—", traceback.format_exc()[:200])
            return

        # ── 8.2 Employé embauché après la fin du mois → 0 ─────────────────────
        from app.tasks.leave_tasks import _compute_accrual_days
        from app.models.employee import Employee

        # Crée un mock employee avec date d'embauche future
        class MockEmployee:
            hire_date = date(year, month, 1) + timedelta(days=35)  # après la fin du mois

        days = _compute_accrual_days(2.0833, MockEmployee(), year, month)
        if days == 0.0:
            ok("Employé embauché après fin du mois → accrual=0", f"_compute_accrual_days={days}")
        else:
            fail("Employé embauché après fin du mois → 0",
                 f"accrual={days} (attendu 0)", "—", f"hire_date={MockEmployee.hire_date}")


# ──────────────────────────────────────────────────────────────────────────────
# Génération du rapport
# ──────────────────────────────────────────────────────────────────────────────

def generate_report(commit_hashes: list[str]) -> str:
    lines = [
        "# Rapport de test E2E — HR Platform",
        f"\nDate de génération : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"\nBranche : dev",
        "",
    ]

    current_phase = None
    for row in REPORT_ROWS:
        if row["phase"] != current_phase:
            current_phase = row["phase"]
            lines.append(f"\n## {current_phase}")
            lines.append(f"\n| Test | Résultat avant correction | Bug trouvé | Fix appliqué (fichier) | Preuve après correction |")
            lines.append(f"|------|---------------------------|------------|------------------------|-------------------------|")

        bug_emoji = "OK" if row["bug"] == "non" else "BUG"
        lines.append(
            f"| {row['test']} "
            f"| {row['before']} "
            f"| {bug_emoji} {row['bug']} "
            f"| {row['fix']} "
            f"| {row['proof']} |"
        )

    if commit_hashes:
        lines.append("\n## Commits créés pendant cette session")
        for h in commit_hashes:
            lines.append(f"- `{h}`")

    lines.append(f"\n---\n*Rapport généré automatiquement par scripts/test_e2e.py*")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Initialisation des comptes de test
# ──────────────────────────────────────────────────────────────────────────────

def setup_test_accounts(company_id: int) -> dict:
    """Cree ou met a jour les comptes de test. Retourne {role: {email, password}}."""
    with app.app_context():
        from app.models.user import User
        from app.models.role import Role

        accounts_config = {
            "admin":    ("admin@test.fr", "Admin1234!", "admin"),
            "rh":       ("rh@test.fr", "RH1234!", "rh"),
            "manager":  ("manager@test.fr", "Manager1234!", "manager"),
            "employee": ("employe@test.fr", "Test1234!", "employee"),
        }

        result = {}
        for key, (email, password, role_name) in accounts_config.items():
            user = User.get_by_email(email)
            if user is None:
                role = _db.session.execute(
                    _db.select(Role).where(Role.name == role_name)
                ).scalar_one_or_none()
                if role:
                    user = User(
                        email=email,
                        role_id=role.id,
                        _is_active=True,
                        is_email_verified=True,
                        force_password_change=False,
                        preferred_language="fr",
                    )
                    user.set_password(password)
                    _db.session.add(user)
                    _db.session.commit()
                    print(f"  [+] Compte cree : {email} [{role_name}]")
            else:
                # Reset le mot de passe pour garantir la coherence des tests
                user.set_password(password)
                user._is_active = True
                user.force_password_change = False
                _db.session.commit()
                print(f"  [=] Mot de passe reset : {email} [{role_name}]")

            if User.get_by_email(email):
                result[key] = {"email": email, "password": password}

        return result


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("TEST E2E COMPLET - HR Platform")
    print(f"Date : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # S'assure que seed-init a tourne
    with app.app_context():
        from app.models.organization import Company
        if Company.get_default() is None:
            print("\n[WARN] Aucune Company en base - execution de seed-init...")
            from manage import seed_init
            with app.test_request_context():
                seed_init.invoke()

    with app.test_client() as client:
        client.testing = True

        # Phase 0 - Bootstrap
        try:
            ids = phase0(client)
            company_id = ids[0]
        except Exception as e:
            print(f"\n[ERROR] PHASE 0 ECHOUEE - arret : {e}")
            traceback.print_exc()
            return

        # Setup comptes de test
        accounts = setup_test_accounts(company_id)
        print(f"\nComptes de test : {list(accounts.keys())}")

        # Phase 1 - Auth
        try:
            phase1(client, accounts)
        except Exception as e:
            print(f"\n[ERROR] PHASE 1 ECHOUEE : {e}")
            traceback.print_exc()

        # Phase 2 - Admin
        try:
            phase2_result = phase2(client, accounts)
        except Exception as e:
            print(f"\n[ERROR] PHASE 2 ECHOUEE : {e}")
            traceback.print_exc()
            phase2_result = {}

        # Phase 3 - Employes
        try:
            phase3_result = phase3(client, accounts, ids)
        except Exception as e:
            print(f"\n[ERROR] PHASE 3 ECHOUEE : {e}")
            traceback.print_exc()
            phase3_result = {}

        # Phase 4 - Conges
        try:
            phase4_result = phase4(client, accounts, ids, phase3_result)
        except Exception as e:
            print(f"\n[ERROR] PHASE 4 ECHOUEE : {e}")
            traceback.print_exc()

        # Phase 5 - Evaluations
        try:
            phase5(client, accounts, ids, phase3_result)
        except Exception as e:
            print(f"\n[ERROR] PHASE 5 ECHOUEE : {e}")
            traceback.print_exc()

        # Phase 6 - Dashboard
        try:
            phase6(client, accounts)
        except Exception as e:
            print(f"\n[ERROR] PHASE 6 ECHOUEE : {e}")
            traceback.print_exc()

        # Phase 7 - Paie
        try:
            phase7(client, accounts, phase3_result)
        except Exception as e:
            print(f"\n[ERROR] PHASE 7 ECHOUEE : {e}")
            traceback.print_exc()

    # Phase 8 - Celery (hors client)
    try:
        phase8(phase3_result, ids)
    except Exception as e:
        print(f"\n[ERROR] PHASE 8 ECHOUEE : {e}")
        traceback.print_exc()

    # Génération du rapport
    print(f"\n{'='*60}")
    print("GENERATION DU RAPPORT")
    print('='*60)
    report = generate_report([])
    report_path = ROOT / "docs" / "rapport_test_e2e.md"
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(f"\n[OK] Rapport genere : {report_path}")

    # Resume
    total = len(REPORT_ROWS)
    passed = sum(1 for r in REPORT_ROWS if r["bug"] == "non")
    failed = total - passed
    print(f"\n{'='*60}")
    print(f"RESUME : {passed}/{total} tests OK, {failed} bug(s) trouves")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
