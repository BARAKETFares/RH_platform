"""seed full permission set for all modules

Revision ID: a1c2d3e4f5a6
Revises: fd115f7e3b87
Create Date: 2026-06-29

Adds the missing permissions for leaves, employees, dashboard and admin
modules, and assigns each permission to the correct roles to match the
4-role spec (employee / manager / rh / admin).

No schema changes — pure data inserts/updates.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1c2d3e4f5a6'
down_revision = 'fd115f7e3b87'
branch_labels = None
depends_on = None


NEW_PERMISSIONS = [
    # (code, module, action, description)
    ("leaves.read",             "leaves",     "read",     "Voir ses propres demandes de congés"),
    ("leaves.write",            "leaves",     "write",    "Créer et annuler ses demandes de congés"),
    ("leaves.approve",          "leaves",     "approve",  "Approuver ou refuser des demandes de congés"),
    ("leaves.view_all",         "leaves",     "view_all", "Voir toutes les demandes de congés (tous les employés)"),
    ("employees.read",          "employees",  "read",     "Voir la liste et le détail des fiches employés"),
    ("employees.write",         "employees",  "write",    "Créer, modifier et archiver des fiches employés"),
    ("dashboard.personal",      "dashboard",  "personal", "Accéder au tableau de bord personnel"),
    ("dashboard.team",          "dashboard",  "team",     "Accéder aux KPIs d'équipe"),
    ("dashboard.company",       "dashboard",  "company",  "Accéder aux KPIs globaux de l'entreprise"),
    ("admin.users",             "admin",      "users",    "Gérer les comptes utilisateurs"),
    ("admin.roles",             "admin",      "roles",    "Gérer les rôles et leurs permissions"),
    ("admin.audit",             "admin",      "audit",    "Consulter le journal d'audit"),
]

# role name → permission codes assigned to that role
ROLE_PERMISSIONS = {
    "employee": [
        "leaves.read",
        "leaves.write",
        "dashboard.personal",
        "evaluation.read",
    ],
    "manager": [
        "leaves.read",
        "leaves.write",
        "leaves.approve",
        "leaves.view_all",
        "employees.read",
        "dashboard.personal",
        "dashboard.team",
        "evaluation.read",
        "evaluation.write",
        "evaluation.campaign",
    ],
    "rh": [
        "leaves.read",
        "leaves.write",
        "leaves.approve",
        "leaves.view_all",
        "employees.read",
        "employees.write",
        "dashboard.personal",
        "dashboard.company",
        "evaluation.read",
        "evaluation.write",
        "evaluation.campaign",
    ],
    "admin": [
        "leaves.read",
        "leaves.write",
        "leaves.approve",
        "leaves.view_all",
        "employees.read",
        "employees.write",
        "dashboard.personal",
        "dashboard.company",
        "evaluation.read",
        "evaluation.write",
        "evaluation.campaign",
        "admin.users",
        "admin.roles",
        "admin.audit",
    ],
}


def upgrade():
    conn = op.get_bind()

    # 1. Insert missing permissions (ignore duplicates via ON CONFLICT)
    for code, module, action, description in NEW_PERMISSIONS:
        conn.execute(sa.text("""
            INSERT INTO permissions (code, module, action, description, created_at)
            VALUES (:code, :module, :action, :description, NOW())
            ON CONFLICT (code) DO NOTHING
        """), {"code": code, "module": module, "action": action, "description": description})

    # 2. Build a code→id map for all permissions
    rows = conn.execute(sa.text("SELECT id, code FROM permissions")).fetchall()
    perm_id_by_code = {r[1]: r[0] for r in rows}

    # 3. Build a name→id map for all roles
    rows = conn.execute(sa.text("SELECT id, name FROM roles")).fetchall()
    role_id_by_name = {r[1]: r[0] for r in rows}

    # 4. For each role, ensure the target permissions exist in role_permissions
    for role_name, codes in ROLE_PERMISSIONS.items():
        role_id = role_id_by_name.get(role_name)
        if role_id is None:
            continue
        for code in codes:
            perm_id = perm_id_by_code.get(code)
            if perm_id is None:
                continue
            conn.execute(sa.text("""
                INSERT INTO role_permissions (role_id, permission_id, granted_at)
                VALUES (:role_id, :perm_id, NOW())
                ON CONFLICT (role_id, permission_id) DO NOTHING
            """), {"role_id": role_id, "perm_id": perm_id})


def downgrade():
    conn = op.get_bind()

    # Remove only the permissions added in this migration
    codes_to_remove = [p[0] for p in NEW_PERMISSIONS]
    for code in codes_to_remove:
        conn.execute(sa.text(
            "DELETE FROM role_permissions WHERE permission_id = "
            "(SELECT id FROM permissions WHERE code = :code)"
        ), {"code": code})
        conn.execute(sa.text(
            "DELETE FROM permissions WHERE code = :code"
        ), {"code": code})
