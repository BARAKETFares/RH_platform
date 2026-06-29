"""
CLI Flask — commandes de gestion de l'application.

Usage :
    flask db init          # Initialise Alembic
    flask db migrate -m "msg"  # Génère une migration
    flask db upgrade       # Applique les migrations

    flask seed             # Injecte les données de référence
    flask create-admin     # Crée le premier compte Admin
    flask routes           # Liste toutes les routes enregistrées
"""
import click
from flask.cli import with_appcontext
from app import create_app
from app.extensions import db

app = create_app()


@app.cli.command("seed")
@with_appcontext
def seed_database():
    """Injecte les données de référence initiales."""
    from scripts.seed_db import run_seed
    run_seed()
    click.echo("Base de données initialisée avec les données de référence.")


@app.cli.command("create-admin")
@click.option("--email",    prompt="Email Admin",          help="Adresse email")
@click.option("--password", prompt=True, hide_input=True,
              confirmation_prompt=True,                     help="Mot de passe")
@with_appcontext
def create_admin(email: str, password: str):
    """Crée le premier compte Administrateur."""
    from scripts.create_admin import create_admin_user
    create_admin_user(email=email, password=password)
    click.echo(f"Compte Admin créé : {email}")


@app.cli.command("check-config")
@with_appcontext
def check_config():
    """Affiche la configuration active (sans les valeurs secrètes)."""
    from flask import current_app
    safe_keys = [k for k in current_app.config if not any(
        s in k for s in ["SECRET", "PASSWORD", "KEY", "TOKEN"]
    )]
    for key in sorted(safe_keys):
        click.echo(f"  {key:45s} = {current_app.config[key]}")


@app.cli.command("seed-init")
@with_appcontext
def seed_init():
    """
    Initialise la base de données avec les données minimales requises.

    Crée (seulement si absent) :
      - 1 Company par défaut
      - Les permissions atomiques de tous les modules
      - Les 4 rôles système (admin / rh / manager / employee) avec leurs permissions
      - 1 compte admin (email/mdp via SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD)

    Idempotent : aucune action si les données sont déjà présentes.

    Variables d'environnement :
      SEED_ADMIN_EMAIL      (défaut : admin@hrplatform.local)
      SEED_ADMIN_PASSWORD   (défaut : Admin1234!  — affiché en console)
    """
    import os
    from app.models.organization import Company
    from app.models.role import Permission, Role, RolePermission
    from app.models.user import User

    created: list[str] = []

    # ── 1. Company ────────────────────────────────────────────────────────────
    if db.session.execute(db.select(Company).limit(1)).scalar_one_or_none() is None:
        company = Company(name="Mon Entreprise", country="FR")
        db.session.add(company)
        db.session.flush()
        created.append(f"  [+] Company       : {company.name}")
    else:
        click.echo("  [=] Company       : déjà présente — ignorée")

    # ── 2. Permissions ────────────────────────────────────────────────────────
    ALL_PERMISSIONS: list[tuple[str, str, str, str]] = [
        # (code,                  module,        action,    description)
        ("employees.read",        "employees",   "read",    "Lire les fiches employés"),
        ("employees.write",       "employees",   "write",   "Créer / modifier des employés"),
        ("employees.delete",      "employees",   "delete",  "Désactiver / supprimer un employé"),
        ("leaves.read",           "leaves",      "read",    "Voir les demandes d'absence"),
        ("leaves.write",          "leaves",      "write",   "Soumettre une demande d'absence"),
        ("leaves.approve",        "leaves",      "approve", "Approuver / rejeter une demande d'absence"),
        ("performance.read",      "performance", "read",    "Voir les évaluations et objectifs"),
        ("performance.write",     "performance", "write",   "Créer / modifier des évaluations"),
        ("performance.finalize",  "performance", "finalize","Finaliser une évaluation"),
        ("payroll.read",          "payroll",     "read",    "Consulter les données de paie"),
        ("payroll.write",         "payroll",     "write",   "Saisir / modifier les éléments de paie"),
        ("contracts.read",        "contracts",   "read",    "Voir les contrats"),
        ("contracts.write",       "contracts",   "write",   "Créer / modifier des contrats"),
        ("admin.users",           "admin",       "users",   "Gérer les comptes utilisateurs"),
        ("admin.roles",           "admin",       "roles",   "Gérer les rôles et permissions"),
        ("admin.org",             "admin",       "org",     "Gérer l'organisation (depts, postes, sites)"),
        ("admin.audit",           "admin",       "audit",   "Consulter le journal d'audit"),
    ]

    perm_map: dict[str, Permission] = {}
    new_perm_count = 0
    for code, module, action, description in ALL_PERMISSIONS:
        perm = db.session.execute(
            db.select(Permission).where(Permission.code == code)
        ).scalar_one_or_none()
        if perm is None:
            perm = Permission(code=code, module=module, action=action, description=description)
            db.session.add(perm)
            db.session.flush()
            new_perm_count += 1
        perm_map[code] = perm

    if new_perm_count:
        created.append(f"  [+] Permissions   : {new_perm_count} créée(s)")
    else:
        click.echo("  [=] Permissions   : déjà présentes — ignorées")

    # ── 3. Rôles + affectation des permissions ────────────────────────────────
    ROLES: list[tuple[str, str, str, list[str]]] = [
        # (name, label, description, [permission codes])
        (
            Role.EMPLOYEE,
            "Employé",
            "Accès à son propre espace (congés, évaluations).",
            ["leaves.read", "leaves.write", "performance.read"],
        ),
        (
            Role.MANAGER,
            "Manager",
            "Gestion de son équipe directe.",
            [
                "employees.read",
                "leaves.read", "leaves.write", "leaves.approve",
                "performance.read", "performance.write",
                "contracts.read",
            ],
        ),
        (
            Role.RH,
            "Ressources Humaines",
            "Gestion RH complète hors administration technique.",
            [
                "employees.read", "employees.write", "employees.delete",
                "leaves.read", "leaves.write", "leaves.approve",
                "performance.read", "performance.write", "performance.finalize",
                "payroll.read",
                "contracts.read", "contracts.write",
                "admin.org",
            ],
        ),
        (
            Role.ADMIN,
            "Administrateur",
            "Accès complet à toutes les fonctionnalités.",
            list(perm_map.keys()),   # toutes les permissions
        ),
    ]

    new_role_count = 0
    for name, label, description, perm_codes in ROLES:
        role = db.session.execute(
            db.select(Role).where(Role.name == name)
        ).scalar_one_or_none()
        if role is None:
            role = Role(name=name, label=label, description=description, is_system=True)
            db.session.add(role)
            db.session.flush()
            new_role_count += 1

        existing_perm_ids = {
            rp.permission_id for rp in role.role_permissions
        }
        for code in perm_codes:
            perm = perm_map.get(code)
            if perm and perm.id not in existing_perm_ids:
                db.session.add(RolePermission(role_id=role.id, permission_id=perm.id))
                existing_perm_ids.add(perm.id)

    if new_role_count:
        created.append(f"  [+] Rôles         : {new_role_count} créé(s)")
    else:
        click.echo("  [=] Rôles         : déjà présents — ignorés")

    # ── 4. Compte admin ────────────────────────────────────────────────────────
    default_email    = "admin@hrplatform.local"
    default_password = "Admin1234!"
    admin_email    = os.environ.get("SEED_ADMIN_EMAIL",    default_email)
    admin_password = os.environ.get("SEED_ADMIN_PASSWORD", default_password)

    admin_role = db.session.execute(
        db.select(Role).where(Role.name == Role.ADMIN)
    ).scalar_one_or_none()

    existing_admin = db.session.execute(
        db.select(User).where(User.email == admin_email)
    ).scalar_one_or_none()

    if existing_admin is None and admin_role is not None:
        admin_user = User(
            email=admin_email,
            role_id=admin_role.id,
            _is_active=True,
            is_email_verified=True,
            force_password_change=False,
            preferred_language="fr",
        )
        admin_user.set_password(admin_password)
        db.session.add(admin_user)
        created.append(f"  [+] Compte admin  : {admin_email}")
        if admin_password == default_password:
            click.secho(
                f"  [!] Mot de passe par défaut utilisé : {default_password}"
                "  → changez-le après la première connexion !",
                fg="yellow",
            )
    else:
        click.echo(f"  [=] Compte admin  : {admin_email} déjà présent — ignoré")

    # ── Commit global ─────────────────────────────────────────────────────────
    db.session.commit()

    if created:
        click.secho("\n✓ seed-init terminé :", fg="green", bold=True)
        for line in created:
            click.echo(line)
    else:
        click.secho("\n✓ seed-init : rien à créer, base déjà initialisée.", fg="green")


if __name__ == "__main__":
    app.run()
