"""
Schémas Marshmallow : Position

Mêmes conventions que employee_schema.py : Schema / CreateSchema / UpdateSchema.
"""
from __future__ import annotations

from marshmallow import Schema, ValidationError, fields, validate, validates, validates_schema


# =============================================================================
# Constantes partagées (alignées avec app.models.position.Position)
# =============================================================================

POSITION_LEVELS = (
    "junior", "intermediate", "senior", "lead", "manager", "director", "executive",
)


# =============================================================================
# PositionSchema — sérialisation complète
# =============================================================================

class PositionSchema(Schema):
    """Sérialisation complète d'une Position, utilisée en lecture (GET)."""

    id = fields.Integer(dump_only=True)

    department_id = fields.Integer(required=True)

    title = fields.String(required=True, validate=validate.Length(min=1, max=150))
    level = fields.String(allow_none=True, validate=validate.OneOf(POSITION_LEVELS))
    description = fields.String(allow_none=True)

    min_salary = fields.Decimal(allow_none=True, places=2, as_string=False, validate=validate.Range(min=0))
    max_salary = fields.Decimal(allow_none=True, places=2, as_string=False, validate=validate.Range(min=0))

    is_active = fields.Boolean()

    # ── Champs dérivés (lecture seule) ────────────────────────────────────────
    department_name = fields.Method("_get_department_name", dump_only=True)
    level_label = fields.String(dump_only=True)
    level_rank = fields.Integer(dump_only=True)
    salary_range_label = fields.String(dump_only=True)
    is_management_level = fields.Boolean(dump_only=True)
    employee_count = fields.Method("_get_employee_count", dump_only=True)

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    def _get_department_name(self, obj) -> str | None:
        department = getattr(obj, "department", None)
        return department.name if department else None

    def _get_employee_count(self, obj) -> int:
        try:
            return obj.employee_count
        except Exception:
            return 0

    @validates("title")
    def validate_title_not_blank(self, value: str, **kwargs) -> None:
        if not value.strip():
            raise ValidationError("L'intitulé du poste ne peut pas être vide.")

    @validates_schema
    def validate_salary_range(self, data: dict, **kwargs) -> None:
        min_salary = data.get("min_salary")
        max_salary = data.get("max_salary")
        if min_salary is not None and max_salary is not None and max_salary < min_salary:
            raise ValidationError(
                "Le salaire maximum ne peut pas être inférieur au salaire minimum.",
                field_name="max_salary",
            )


# =============================================================================
# PositionCreateSchema
# =============================================================================

class PositionCreateSchema(Schema):
    """Validation des données à la création d'un poste."""

    department_id = fields.Integer(required=True)

    title = fields.String(required=True, validate=validate.Length(min=1, max=150))
    level = fields.String(allow_none=True, validate=validate.OneOf(POSITION_LEVELS))
    description = fields.String(allow_none=True)

    min_salary = fields.Decimal(allow_none=True, places=2, as_string=False, validate=validate.Range(min=0))
    max_salary = fields.Decimal(allow_none=True, places=2, as_string=False, validate=validate.Range(min=0))

    is_active = fields.Boolean(load_default=True)

    @validates("title")
    def validate_title_not_blank(self, value: str, **kwargs) -> None:
        if not value.strip():
            raise ValidationError("L'intitulé du poste ne peut pas être vide.")

    @validates_schema
    def validate_salary_range(self, data: dict, **kwargs) -> None:
        min_salary = data.get("min_salary")
        max_salary = data.get("max_salary")
        if min_salary is not None and max_salary is not None and max_salary < min_salary:
            raise ValidationError(
                "Le salaire maximum ne peut pas être inférieur au salaire minimum.",
                field_name="max_salary",
            )


# =============================================================================
# PositionUpdateSchema
# =============================================================================

class PositionUpdateSchema(Schema):
    """Validation des données à la mise à jour d'un poste (PATCH)."""

    department_id = fields.Integer()

    title = fields.String(validate=validate.Length(min=1, max=150))
    level = fields.String(allow_none=True, validate=validate.OneOf(POSITION_LEVELS))
    description = fields.String(allow_none=True)

    min_salary = fields.Decimal(allow_none=True, places=2, as_string=False, validate=validate.Range(min=0))
    max_salary = fields.Decimal(allow_none=True, places=2, as_string=False, validate=validate.Range(min=0))

    is_active = fields.Boolean()

    @validates("title")
    def validate_title_not_blank(self, value: str, **kwargs) -> None:
        if value is not None and not value.strip():
            raise ValidationError("L'intitulé du poste ne peut pas être vide.")

    @validates_schema
    def validate_salary_range(self, data: dict, **kwargs) -> None:
        min_salary = data.get("min_salary")
        max_salary = data.get("max_salary")
        if min_salary is not None and max_salary is not None and max_salary < min_salary:
            raise ValidationError(
                "Le salaire maximum ne peut pas être inférieur au salaire minimum.",
                field_name="max_salary",
            )


# =============================================================================
# Schémas d'instance prêts à l'emploi
# =============================================================================

position_schema = PositionSchema()
positions_schema = PositionSchema(many=True)
position_create_schema = PositionCreateSchema()
position_update_schema = PositionUpdateSchema()

# Variante allégée pour les listes déroulantes (selects)
position_light_schema = PositionSchema(
    only=("id", "title", "level", "level_label", "is_active"),
    many=True,
)