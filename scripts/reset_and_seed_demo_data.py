"""
Réinitialise les données de test et initialise des données réalistes pour
une démonstration professionnelle de la plateforme RH.

IMPORTANT : ce script supprime irréversiblement toutes les données
opérationnelles (employés, comptes, contrats, congés, évaluations, paie,
formations) puis recrée un jeu de données de référence minimal + 2 comptes
utilisateurs. Un backup pg_dump doit avoir été effectué AVANT toute
exécution.

Ordre de suppression respectant les contraintes FK (vérifié par
introspection du schéma live, cf. docs/rapport_ui_ux.md) :
    pay_elements, payslips, leave_requests, leave_balances, enrollments,
    evaluation_items, evaluations, objectives, evaluation_campaigns,
    contracts, employees, users, leave_types, trainings,
    positions, departments, contract_types, sites.

Les tables companies, roles, permissions, role_permissions ne sont PAS
touchées (infrastructure RBAC / entité juridique racine).

Usage :
    python scripts/reset_and_seed_demo_data.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

# Ajoute la racine du projet au PYTHONPATH
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv()

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402

DELETE_ORDER = [
    "pay_elements", "payslips",
    "leave_requests", "leave_balances", "enrollments",
    "evaluation_items", "evaluations", "objectives", "evaluation_campaigns",
    "contracts",
    "employees", "users",
    "leave_types", "trainings",
    "positions", "departments",
    "contract_types", "sites",
]

EXPECTED_FINAL_COUNTS = {
    "employees": 1, "users": 2, "leave_types": 7, "trainings": 3,
    "departments": 3, "positions": 13, "contract_types": 5, "sites": 1,
    "leave_requests": 0, "leave_balances": 0, "payslips": 0,
    "enrollments": 0, "evaluations": 0,
}


def _count(table: str) -> int:
    return db.session.execute(db.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()


def step1_delete_test_data() -> None:
    print("=== ÉTAPE 1 — Suppression des données de test (ordre FK-safe) ===")
    for table in DELETE_ORDER:
        before = _count(table)
        try:
            db.session.execute(db.text(f"DELETE FROM {table}"))
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            print(f"  ÉCHEC sur {table} ({before} lignes) : {exc}")
            raise
        after = _count(table)
        print(f"  {table}: {before} -> {after} lignes")
        assert after == 0, f"{table} n'est pas vide après suppression ({after} lignes restantes)"


def step2_seed_reference_data() -> dict:
    print("\n=== ÉTAPE 2 — Création des données de référence réalistes ===")
    from app.models.contract import ContractType
    from app.models.department import Department
    from app.models.leave_type import LeaveType
    from app.models.organization import Company, Site
    from app.models.position import Position
    from app.models.training import Training

    company = db.session.execute(db.select(Company)).scalar_one()

    # A. Site
    site = Site(company_id=company.id, name="Siège Social", city="Paris", country="FR")
    db.session.add(site)
    db.session.flush()
    print(f"  Site créé : {site.name} ({site.city})")

    # B. Départements + postes
    depts_spec = {
        "Ressources Humaines": [
            ("Responsable RH", "manager"),
            ("Chargé(e) de recrutement", "intermediate"),
            ("Assistant(e) RH", "junior"),
        ],
        "Informatique & Systèmes": [
            ("Directeur Technique (CTO)", "executive"),
            ("Développeur Full Stack", "intermediate"),
            ("Développeur Backend", "intermediate"),
            ("Développeur Frontend", "intermediate"),
            ("DevOps Engineer", "senior"),
            ("Chef de Projet IT", "manager"),
        ],
        "Finance & Comptabilité": [
            ("Directeur Financier (CFO)", "executive"),
            ("Comptable Senior", "senior"),
            ("Contrôleur de Gestion", "senior"),
            ("Analyste Financier", "intermediate"),
        ],
    }
    departments: dict[str, Department] = {}
    positions: dict[str, Position] = {}
    for dept_name, pos_list in depts_spec.items():
        dept = Department(company_id=company.id, name=dept_name)
        db.session.add(dept)
        db.session.flush()
        departments[dept_name] = dept
        for title, level in pos_list:
            pos = Position(department_id=dept.id, title=title, level=level)
            db.session.add(pos)
            positions[title] = pos
        print(f"  Département créé : {dept_name} ({len(pos_list)} postes)")
    db.session.flush()

    # C. Types de congés (conformes au droit du travail français)
    leave_types_spec = [
        # name, code, is_paid, impacts_balance, max_consecutive_days, requires_document, description
        ("Congés Payés",    "CP",  True,  True,  None, False, "25 jours/an"),
        ("RTT",             "RTT", True,  True,  None, False, "10 jours/an"),
        ("Congé Maladie",   "MAL", True,  False, None, True,  "Illimité, sur justificatif"),
        ("Congé Maternité", "MAT", True,  False, 112,  True,  "16 semaines (légal)"),
        ("Congé Paternité", "PAT", True,  False, 25,   True,  "25 jours"),
        ("Congé Sans Solde","CSS", False, False, None, False, "Selon accord"),
        ("Congé Formation", "CIF", True,  False, None, False, "Selon plan de formation (CIF/CPF)"),
    ]
    for name, code, is_paid, impacts, max_days, req_doc, desc in leave_types_spec:
        db.session.add(LeaveType(
            company_id=company.id, name=name, code=code, is_paid=is_paid,
            impacts_leave_balance=impacts, max_consecutive_days=max_days,
            requires_document=req_doc, description=desc,
        ))
    print(f"  {len(leave_types_spec)} types de congés créés")

    # D. Formations (durée convertie jours -> heures, base 7h/jour)
    trainings_spec = [
        ("RGPD", "CNIL / Prestataire certifié", 2 * 7, "presentiel", 800),
        ("Management et Leadership", "Institut du Management", 3 * 7, "presentiel", 1200),
        ("Excel Avancé & Power BI", "Microsoft Learning Partner", 1 * 7, "e_learning", 350),
    ]
    for title, organisme, duration_hours, ttype, cost in trainings_spec:
        db.session.add(Training(
            company_id=company.id, title=title, organisme=organisme,
            duration_hours=duration_hours, training_type=ttype, cost=cost,
        ))
    print(f"  {len(trainings_spec)} formations créées")

    # E. Types de contrats
    # NB : seuls 4 types étaient explicitement nommés dans la mission (CDI Cadre,
    # CDI Non-cadre, Stage, Alternance) alors que la vérification finale attend 5.
    # "CDD" a été ajouté comme 5e type par déduction (déjà supporté nativement par
    # ContractType.DURATION_CDD) — à confirmer/ajuster si ce n'était pas l'intention.
    contract_types_spec = [
        ("CDI (Cadre)", ContractType.DURATION_CDI, 25, 10, 90),
        ("CDI (Non-cadre)", ContractType.DURATION_CDI, 25, 10, 30),
        ("CDD", ContractType.DURATION_CDD, 25, 0, 15),
        ("Stage / Convention de stage", ContractType.DURATION_INTERNSHIP, 0, 0, 0),
        ("Alternance (Apprentissage)", ContractType.DURATION_APPRENTICESHIP, 25, 0, 30),
    ]
    for name, duration_type, cp_days, rtt_days, notice in contract_types_spec:
        db.session.add(ContractType(
            company_id=company.id, name=name, duration_type=duration_type,
            paid_leave_days=cp_days, rtt_days=rtt_days, notice_period_days=notice,
        ))
    print(f"  {len(contract_types_spec)} types de contrats créés")

    db.session.commit()
    return {"company": company, "departments": departments, "positions": positions, "site": site}


def step3_create_accounts(ctx: dict) -> None:
    print("\n=== ÉTAPE 3 — Création des comptes utilisateurs ===")
    from app.models.employee import Employee
    from app.models.role import Role
    from app.models.user import User

    admin_role = db.session.execute(db.select(Role).where(Role.name == "admin")).scalar_one()
    rh_role = db.session.execute(db.select(Role).where(Role.name == "rh")).scalar_one()

    admin_password = "Admin@2024!"
    admin = User(
        email="admin@hrplatform.com", role_id=admin_role.id,
        _is_active=True, is_email_verified=True, force_password_change=False,
    )
    admin.set_password(admin_password)
    db.session.add(admin)

    sophie_password = "RH@2024Sophie!"
    sophie_user = User(
        email="sophie.martin@hrplatform.com", role_id=rh_role.id,
        _is_active=True, is_email_verified=True, force_password_change=False,
    )
    sophie_user.set_password(sophie_password)
    db.session.add(sophie_user)
    db.session.flush()

    rh_dept = ctx["departments"]["Ressources Humaines"]
    rh_position = ctx["positions"]["Responsable RH"]
    db.session.add(Employee(
        company_id=ctx["company"].id, department_id=rh_dept.id,
        position_id=rh_position.id, site_id=ctx["site"].id,
        user_id=sophie_user.id,
        first_name="Sophie", last_name="Martin",
        hire_date=date.today(), status=Employee.STATUS_ACTIVE,
    ))
    db.session.commit()

    print("  Compte admin créé : admin@hrplatform.com")
    print(f"  Mot de passe (à noter maintenant, ne sera plus réaffiché) : {admin_password}")
    print("  Compte RH créé : sophie.martin@hrplatform.com (+ fiche employé liée)")
    print(f"  Mot de passe (à noter maintenant, ne sera plus réaffiché) : {sophie_password}")


def step4_verify() -> bool:
    print("\n=== ÉTAPE 4 — Vérification finale ===")
    all_ok = True
    for table, expected_count in EXPECTED_FINAL_COUNTS.items():
        actual = _count(table)
        ok = actual == expected_count
        all_ok = all_ok and ok
        print(f"  {table}: {actual} (attendu {expected_count}) [{'OK' if ok else 'MISMATCH'}]")
    return all_ok


def main() -> None:
    app = create_app("development")
    with app.app_context():
        step1_delete_test_data()
        ctx = step2_seed_reference_data()
        step3_create_accounts(ctx)
        ok = step4_verify()
        if not ok:
            raise SystemExit("Au moins un compteur final ne correspond pas à l'attendu.")


if __name__ == "__main__":
    main()
