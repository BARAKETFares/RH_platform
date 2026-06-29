"""
Schémas Marshmallow : Employee

Trois variantes par ressource, convention utilisée dans tout le module :
  - <X>Schema        — sérialisation complète (lecture / réponse API)
  - <X>CreateSchema   — validation à la création (champs requis stricts)
  - <X>UpdateSchema    — validation à la mise à jour (tous champs optionnels)

include_sensitive (IBAN, BIC, numéro de sécu, salaire) est géré au niveau
service/route — ce schéma sérialise toujours ces champs ; c'est l'appelant
qui décide de les exclure via `exclude=(...)` selon le rôle de l'utilisateur.
"""
from __future__ import annotations

from marshmallow import (
    Schema,
    ValidationError,
    fields,
    validate,
    validates,
    validates_schema,
)


# =============================================================================
# Constantes partagées (alignées avec app.models.employee.Employee)
# =============================================================================

EMPLOYEE_STATUSES = ("active", "on_leave", "probation", "terminated", "suspended")
GENDERS = ("male", "female", "other", "prefer_not_to_say")


# =============================================================================
# EmployeeSchema — sérialisation complète
# =============================================================================

class EmployeeSchema(Schema):
    """Sérialisation complète d'un Employee, utilisée en lecture (GET)."""

    id = fields.Integer(dump_only=True)
    uuid = fields.String(dump_only=True)
    employee_number = fields.String(allow_none=True)

    # ── Rattachements ─────────────────────────────────────────────────────────
    user_id = fields.Integer(allow_none=True)
    company_id = fields.Integer(required=True)
    department_id = fields.Integer(allow_none=True)
    position_id = fields.Integer(allow_none=True)
    site_id = fields.Integer(allow_none=True)
    manager_id = fields.Integer(allow_none=True)

    # ── Champs dérivés (lecture seule) ────────────────────────────────────────
    full_name = fields.String(dump_only=True)
    initials = fields.String(dump_only=True)
    manager_name = fields.Method("_get_manager_name", dump_only=True)
    department_name = fields.Method("_get_department_name", dump_only=True)
    position_title = fields.Method("_get_position_title", dump_only=True)
    seniority_years = fields.Float(dump_only=True)
    is_active = fields.Boolean(dump_only=True)
    is_on_probation = fields.Boolean(dump_only=True)

    # ── Informations personnelles ─────────────────────────────────────────────
    first_name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    last_name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    maiden_name = fields.String(allow_none=True, validate=validate.Length(max=100))
    gender = fields.String(allow_none=True, validate=validate.OneOf(GENDERS))
    birth_date = fields.Date(allow_none=True)
    birth_place = fields.String(allow_none=True, validate=validate.Length(max=150))
    nationality = fields.String(allow_none=True, validate=validate.Length(equal=2))
    national_id_number = fields.String(allow_none=True, load_only=False)

    # ── Contact ───────────────────────────────────────────────────────────────
    personal_email = fields.Email(allow_none=True)
    personal_phone = fields.String(allow_none=True, validate=validate.Length(max=30))
    professional_phone = fields.String(allow_none=True, validate=validate.Length(max=30))

    # ── Adresse ───────────────────────────────────────────────────────────────
    address_line1 = fields.String(allow_none=True, validate=validate.Length(max=200))
    address_line2 = fields.String(allow_none=True, validate=validate.Length(max=200))
    city = fields.String(allow_none=True, validate=validate.Length(max=100))
    postal_code = fields.String(allow_none=True, validate=validate.Length(max=20))
    country = fields.String(allow_none=True, validate=validate.Length(equal=2))

    # ── Contact d'urgence ─────────────────────────────────────────────────────
    emergency_contact_name = fields.String(allow_none=True, validate=validate.Length(max=200))
    emergency_contact_phone = fields.String(allow_none=True, validate=validate.Length(max=30))
    emergency_contact_relationship = fields.String(allow_none=True, validate=validate.Length(max=50))

    # ── Coordonnées bancaires (sensibles) ─────────────────────────────────────
    iban = fields.String(allow_none=True)
    bic = fields.String(allow_none=True)

    # ── Informations professionnelles ─────────────────────────────────────────
    hire_date = fields.Date(required=True)
    termination_date = fields.Date(allow_none=True)
    termination_reason = fields.String(allow_none=True)
    probation_end_date = fields.Date(allow_none=True)
    annual_gross_salary = fields.Decimal(allow_none=True, places=2, as_string=True)

    status = fields.String(validate=validate.OneOf(EMPLOYEE_STATUSES))

    photo_path = fields.String(allow_none=True, dump_only=True)
    notes = fields.String(allow_none=True)

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    # ── Méthodes de résolution des champs dérivés ─────────────────────────────
    def _get_manager_name(self, obj) -> str | None:
        manager = getattr(obj, "manager", None)
        return manager.full_name if manager else None

    def _get_department_name(self, obj) -> str | None:
        department = getattr(obj, "department", None)
        return department.name if department else None

    def _get_position_title(self, obj) -> str | None:
        position = getattr(obj, "position", None)
        return position.title if position else None

    # ── Validations transverses ────────────────────────────────────────────────
    @validates_schema
    def validate_dates(self, data: dict, **kwargs) -> None:
        hire_date = data.get("hire_date")
        termination_date = data.get("termination_date")
        probation_end_date = data.get("probation_end_date")

        if hire_date and termination_date and termination_date < hire_date:
            raise ValidationError(
                "La date de départ ne peut pas précéder la date d'embauche.",
                field_name="termination_date",
            )
        if hire_date and probation_end_date and probation_end_date < hire_date:
            raise ValidationError(
                "La fin de période d'essai ne peut pas précéder la date d'embauche.",
                field_name="probation_end_date",
            )

    @validates("manager_id")
    def validate_manager_not_self(self, value, **kwargs) -> None:
        # La vérification id != manager_id nécessite l'instance en cours de
        # modification ; elle est appliquée au niveau service, pas ici,
        # car le schéma ne connaît pas l'id de l'employé en mise à jour.
        pass


# =============================================================================
# EmployeeCreateSchema — validation stricte à la création
# =============================================================================

class EmployeeCreateSchema(Schema):
    """
    Validation des données à la création d'un employé.
    Seuls les champs strictement nécessaires sont requis ; le reste est
    optionnel et complété progressivement via la mise à jour du dossier.
    """

    company_id = fields.Integer(required=True)
    department_id = fields.Integer(allow_none=True)
    position_id = fields.Integer(allow_none=True)
    site_id = fields.Integer(allow_none=True)
    manager_id = fields.Integer(allow_none=True)

    employee_number = fields.String(allow_none=True, validate=validate.Length(max=50))

    first_name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    last_name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    gender = fields.String(allow_none=True, validate=validate.OneOf(GENDERS))
    birth_date = fields.Date(allow_none=True)
    nationality = fields.String(allow_none=True, validate=validate.Length(equal=2))
    national_id_number = fields.String(allow_none=True)

    personal_email = fields.Email(allow_none=True)
    personal_phone = fields.String(allow_none=True, validate=validate.Length(max=30))
    professional_phone = fields.String(allow_none=True, validate=validate.Length(max=30))

    address_line1 = fields.String(allow_none=True, validate=validate.Length(max=200))
    address_line2 = fields.String(allow_none=True, validate=validate.Length(max=200))
    city = fields.String(allow_none=True, validate=validate.Length(max=100))
    postal_code = fields.String(allow_none=True, validate=validate.Length(max=20))
    country = fields.String(allow_none=True, validate=validate.Length(equal=2))

    emergency_contact_name = fields.String(allow_none=True, validate=validate.Length(max=200))
    emergency_contact_phone = fields.String(allow_none=True, validate=validate.Length(max=30))
    emergency_contact_relationship = fields.String(allow_none=True, validate=validate.Length(max=50))

    iban = fields.String(allow_none=True)
    bic = fields.String(allow_none=True)

    hire_date = fields.Date(required=True)
    probation_end_date = fields.Date(allow_none=True)
    annual_gross_salary = fields.Decimal(allow_none=True, places=2, as_string=True, validate=validate.Range(min=0.01))

    status = fields.String(
        load_default="active",
        validate=validate.OneOf(EMPLOYEE_STATUSES),
    )

    notes = fields.String(allow_none=True)

    @validates_schema
    def validate_probation_after_hire(self, data: dict, **kwargs) -> None:
        hire_date = data.get("hire_date")
        probation_end_date = data.get("probation_end_date")
        if hire_date and probation_end_date and probation_end_date < hire_date:
            raise ValidationError(
                "La fin de période d'essai ne peut pas précéder la date d'embauche.",
                field_name="probation_end_date",
            )

    @validates("first_name")
    def validate_first_name_not_blank(self, value: str, **kwargs) -> None:
        if not value.strip():
            raise ValidationError("Le prénom ne peut pas être vide ou contenir uniquement des espaces.")

    @validates("last_name")
    def validate_last_name_not_blank(self, value: str, **kwargs) -> None:
        if not value.strip():
            raise ValidationError("Le nom ne peut pas être vide ou contenir uniquement des espaces.")


# =============================================================================
# EmployeeUpdateSchema — validation pour mise à jour partielle
# =============================================================================

class EmployeeUpdateSchema(Schema):
    """
    Validation des données à la mise à jour d'un employé.
    Tous les champs sont optionnels (PATCH sémantique) : seuls les champs
    présents dans le payload sont validés et appliqués.
    """

    department_id = fields.Integer(allow_none=True)
    position_id = fields.Integer(allow_none=True)
    site_id = fields.Integer(allow_none=True)
    manager_id = fields.Integer(allow_none=True)

    employee_number = fields.String(allow_none=True, validate=validate.Length(max=50))

    first_name = fields.String(validate=validate.Length(min=1, max=100))
    last_name = fields.String(validate=validate.Length(min=1, max=100))
    maiden_name = fields.String(allow_none=True, validate=validate.Length(max=100))
    gender = fields.String(allow_none=True, validate=validate.OneOf(GENDERS))
    birth_date = fields.Date(allow_none=True)
    birth_place = fields.String(allow_none=True, validate=validate.Length(max=150))
    nationality = fields.String(allow_none=True, validate=validate.Length(equal=2))
    national_id_number = fields.String(allow_none=True)

    personal_email = fields.Email(allow_none=True)
    personal_phone = fields.String(allow_none=True, validate=validate.Length(max=30))
    professional_phone = fields.String(allow_none=True, validate=validate.Length(max=30))

    address_line1 = fields.String(allow_none=True, validate=validate.Length(max=200))
    address_line2 = fields.String(allow_none=True, validate=validate.Length(max=200))
    city = fields.String(allow_none=True, validate=validate.Length(max=100))
    postal_code = fields.String(allow_none=True, validate=validate.Length(max=20))
    country = fields.String(allow_none=True, validate=validate.Length(equal=2))

    emergency_contact_name = fields.String(allow_none=True, validate=validate.Length(max=200))
    emergency_contact_phone = fields.String(allow_none=True, validate=validate.Length(max=30))
    emergency_contact_relationship = fields.String(allow_none=True, validate=validate.Length(max=50))

    iban = fields.String(allow_none=True)
    bic = fields.String(allow_none=True)

    hire_date = fields.Date()
    termination_date = fields.Date(allow_none=True)
    termination_reason = fields.String(allow_none=True)
    probation_end_date = fields.Date(allow_none=True)
    annual_gross_salary = fields.Decimal(allow_none=True, places=2, as_string=True, validate=validate.Range(min=0.01))

    status = fields.String(validate=validate.OneOf(EMPLOYEE_STATUSES))

    notes = fields.String(allow_none=True)

    @validates_schema
    def validate_dates_coherence(self, data: dict, **kwargs) -> None:
        hire_date = data.get("hire_date")
        termination_date = data.get("termination_date")
        if hire_date and termination_date and termination_date < hire_date:
            raise ValidationError(
                "La date de départ ne peut pas précéder la date d'embauche.",
                field_name="termination_date",
            )

    @validates("first_name")
    def validate_first_name_not_blank(self, value: str, **kwargs) -> None:
        if value is not None and not value.strip():
            raise ValidationError("Le prénom ne peut pas être vide.")

    @validates("last_name")
    def validate_last_name_not_blank(self, value: str, **kwargs) -> None:
        if value is not None and not value.strip():
            raise ValidationError("Le nom ne peut pas être vide.")


# =============================================================================
# Schémas d'instance prêts à l'emploi
# =============================================================================

employee_schema = EmployeeSchema()
employees_schema = EmployeeSchema(many=True)
employee_create_schema = EmployeeCreateSchema()
employee_update_schema = EmployeeUpdateSchema()

# Variante pour les rôles sans accès aux données sensibles (Employé standard)
employee_public_schema = EmployeeSchema(
    exclude=("national_id_number", "iban", "bic", "annual_gross_salary", "notes")
)
employees_public_schema = EmployeeSchema(
    many=True,
    exclude=("national_id_number", "iban", "bic", "annual_gross_salary", "notes"),
)