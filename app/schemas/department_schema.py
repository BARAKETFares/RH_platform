"""
Schémas Marshmallow : Department

Mêmes conventions que employee_schema.py : Schema / CreateSchema / UpdateSchema.
"""
from __future__ import annotations

from marshmallow import Schema, ValidationError, fields, validate, validates, validates_schema


# =============================================================================
# DepartmentSchema — sérialisation complète
# =============================================================================

class DepartmentSchema(Schema):
    """Sérialisation complète d'un Department, utilisée en lecture (GET)."""

    id = fields.Integer(dump_only=True)

    company_id = fields.Integer(required=True)
    parent_id = fields.Integer(allow_none=True)
    manager_id = fields.Integer(allow_none=True)

    name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    code = fields.String(allow_none=True, validate=validate.Length(max=20))
    description = fields.String(allow_none=True)
    cost_center = fields.String(allow_none=True, validate=validate.Length(max=50))
    is_active = fields.Boolean()

    # ── Champs dérivés (lecture seule) ────────────────────────────────────────
    full_path = fields.String(dump_only=True)
    depth = fields.Integer(dump_only=True)
    is_root = fields.Boolean(dump_only=True)
    has_children = fields.Boolean(dump_only=True)
    has_manager = fields.Boolean(dump_only=True)
    manager_name = fields.Method("_get_manager_name", dump_only=True)
    employee_count = fields.Method("_get_employee_count", dump_only=True)
    total_employee_count = fields.Method("_get_total_employee_count", dump_only=True)

    # Sous-départements — récursif, profondeur limitée pour éviter une charge excessive
    children = fields.List(
        fields.Nested(lambda: DepartmentSchema(exclude=("children",))),
        dump_only=True,
    )

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    def _get_manager_name(self, obj) -> str | None:
        manager = getattr(obj, "manager", None)
        return manager.full_name if manager else None

    def _get_employee_count(self, obj) -> int:
        try:
            return obj.employee_count
        except Exception:
            return 0

    def _get_total_employee_count(self, obj) -> int:
        try:
            return obj.total_employee_count
        except Exception:
            return 0

    @validates("name")
    def validate_name_not_blank(self, value: str, **kwargs) -> None:
        if not value.strip():
            raise ValidationError("Le nom du département ne peut pas être vide.")


# =============================================================================
# DepartmentCreateSchema
# =============================================================================

class DepartmentCreateSchema(Schema):
    """Validation des données à la création d'un département."""

    company_id = fields.Integer(required=True)
    parent_id = fields.Integer(allow_none=True)
    manager_id = fields.Integer(allow_none=True)

    name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    code = fields.String(allow_none=True, validate=validate.Length(max=20))
    description = fields.String(allow_none=True)
    cost_center = fields.String(allow_none=True, validate=validate.Length(max=50))
    is_active = fields.Boolean(load_default=True)

    @validates("name")
    def validate_name_not_blank(self, value: str, **kwargs) -> None:
        if not value.strip():
            raise ValidationError("Le nom du département ne peut pas être vide.")

    @validates_schema
    def validate_parent_differs(self, data: dict, **kwargs) -> None:
        # La vérification id != parent_id nécessite l'id du département en
        # cours de création, qui n'existe pas encore : non applicable ici.
        # Vérification appliquée côté service pour les mises à jour.
        pass


# =============================================================================
# DepartmentUpdateSchema
# =============================================================================

class DepartmentUpdateSchema(Schema):
    """Validation des données à la mise à jour d'un département (PATCH)."""

    parent_id = fields.Integer(allow_none=True)
    manager_id = fields.Integer(allow_none=True)

    name = fields.String(validate=validate.Length(min=1, max=100))
    code = fields.String(allow_none=True, validate=validate.Length(max=20))
    description = fields.String(allow_none=True)
    cost_center = fields.String(allow_none=True, validate=validate.Length(max=50))
    is_active = fields.Boolean()

    @validates("name")
    def validate_name_not_blank(self, value: str, **kwargs) -> None:
        if value is not None and not value.strip():
            raise ValidationError("Le nom du département ne peut pas être vide.")


# =============================================================================
# Schémas d'instance prêts à l'emploi
# =============================================================================

department_schema = DepartmentSchema()
departments_schema = DepartmentSchema(many=True)
department_create_schema = DepartmentCreateSchema()
department_update_schema = DepartmentUpdateSchema()

# Variante allégée pour les listes déroulantes (selects) — pas de récursion
department_light_schema = DepartmentSchema(
    only=("id", "name", "code", "full_path", "is_active"),
    many=True,
)