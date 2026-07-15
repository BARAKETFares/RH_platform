"""add leaves.adjust permission for RH/admin balance adjustment

Revision ID: ebd87a407912
Revises: f7331b8d5cf3
Create Date: 2026-07-14

Adds the "leaves.adjust" permission (manual RH/admin regularisation of a
leave balance, via leave_service.adjust_balance()) and assigns it to the
rh and admin roles only — not manager, not employee.

No schema changes — pure data inserts/updates.
"""
from alembic import op
import sqlalchemy as sa

revision = 'ebd87a407912'
down_revision = 'f7331b8d5cf3'
branch_labels = None
depends_on = None


NEW_PERMISSIONS = [
    # (code, module, action, description)
    ("leaves.adjust", "leaves", "adjust", "Ajuster manuellement le solde de congés d'un employé"),
]

ROLE_PERMISSIONS = {
    "rh": ["leaves.adjust"],
    "admin": ["leaves.adjust"],
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
