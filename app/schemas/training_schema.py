"""
Schémas Marshmallow : Training · Enrollment

Mêmes conventions que evaluation_schema.py / leave_schema.py :
  - <X>Schema        — sérialisation complète (lecture / réponse API)
  - <X>CreateSchema   — validation à la création (champs requis stricts)
  - <X>UpdateSchema    — validation à la mise à jour (tous champs optionnels)

EnrollmentStatusUpdateSchema est un cas particulier : il transporte
le statut cible ET les données complémentaires propres à chaque
transition (score et dates pour 'terminee', start_date pour 'en_cours').
"""
from __future__ import annotations

from marshmallow import Schema, ValidationError, fields, validate, validates, validates_schema

# =============================================================================
# Constantes (alignées avec Training / Enrollment)
# =============================================================================

TRAINING_TYPES     = ("presentiel", "distanciel", "e_learning")
ENROLLMENT_STATUSES = ("planifiee", "en_cours", "terminee", "annulee")


# =============================================================================
# Training
# =============================================================================

class TrainingSchema(Schema):
    """Sérialisation complète d'une formation, utilisée en lecture (GET)."""

    id          = fields.Integer(dump_only=True)
    company_id  = fields.Integer(allow_none=True)

    title           = fields.String(required=True, validate=validate.Length(min=1, max=200))
    description     = fields.String(allow_none=True)
    organisme       = fields.String(allow_none=True, validate=validate.Length(max=200))
    duration_hours  = fields.Float(allow_none=True, validate=validate.Range(min=0, min_inclusive=False))
    training_type   = fields.String(validate=validate.OneOf(TRAINING_TYPES))
    cost            = fields.Float(allow_none=True, validate=validate.Range(min=0))
    is_active       = fields.Boolean()

    # Champs dérivés — calculés par les propriétés du modèle
    enrollment_count        = fields.Method("_enrollment_count", dump_only=True)
    active_enrollment_count = fields.Method("_active_enrollment_count", dump_only=True)

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    def _enrollment_count(self, obj) -> int:
        try:
            return obj.enrollment_count
        except Exception:
            return 0

    def _active_enrollment_count(self, obj) -> int:
        try:
            return obj.active_enrollment_count
        except Exception:
            return 0

    @validates("title")
    def validate_title_not_blank(self, value: str, **kwargs) -> None:
        if not value.strip():
            raise ValidationError("Le titre de la formation ne peut pas être vide.")


class TrainingCreateSchema(Schema):
    """Validation des données à la création d'une formation."""

    company_id     = fields.Integer(allow_none=True, load_default=None)
    title          = fields.String(required=True, validate=validate.Length(min=1, max=200))
    description    = fields.String(allow_none=True, load_default=None)
    organisme      = fields.String(allow_none=True, load_default=None,
                                   validate=validate.Length(max=200))
    duration_hours = fields.Float(allow_none=True, load_default=None,
                                   validate=validate.Range(min=0, min_inclusive=False))
    training_type  = fields.String(load_default="presentiel",
                                    validate=validate.OneOf(TRAINING_TYPES))
    cost           = fields.Float(allow_none=True, load_default=None,
                                   validate=validate.Range(min=0))
    is_active      = fields.Boolean(load_default=True)

    @validates("title")
    def validate_title_not_blank(self, value: str, **kwargs) -> None:
        if not value.strip():
            raise ValidationError("Le titre de la formation ne peut pas être vide.")


class TrainingUpdateSchema(Schema):
    """Validation des données à la mise à jour d'une formation (PATCH — tous champs optionnels)."""

    title          = fields.String(validate=validate.Length(min=1, max=200))
    description    = fields.String(allow_none=True)
    organisme      = fields.String(allow_none=True, validate=validate.Length(max=200))
    duration_hours = fields.Float(allow_none=True, validate=validate.Range(min=0, min_inclusive=False))
    training_type  = fields.String(validate=validate.OneOf(TRAINING_TYPES))
    cost           = fields.Float(allow_none=True, validate=validate.Range(min=0))
    is_active      = fields.Boolean()

    @validates("title")
    def validate_title_not_blank(self, value: str, **kwargs) -> None:
        if value is not None and not value.strip():
            raise ValidationError("Le titre de la formation ne peut pas être vide.")


# =============================================================================
# Enrollment
# =============================================================================

class EnrollmentSchema(Schema):
    """Sérialisation complète d'une inscription, utilisée en lecture (GET)."""

    id          = fields.Integer(dump_only=True)
    employee_id = fields.Integer(required=True)
    training_id = fields.Integer(required=True)

    status     = fields.String(validate=validate.OneOf(ENROLLMENT_STATUSES))
    start_date = fields.Date(allow_none=True)
    end_date   = fields.Date(allow_none=True)
    score      = fields.Float(allow_none=True, validate=validate.Range(min=0, max=100))
    final_comment = fields.String(allow_none=True)

    # Champs dérivés — lecture seule
    is_passed      = fields.Boolean(allow_none=True, dump_only=True)
    training_title = fields.Method("_training_title", dump_only=True)
    employee_name  = fields.Method("_employee_name", dump_only=True)

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    def _training_title(self, obj) -> str | None:
        try:
            return obj.training.title if obj.training else None
        except Exception:
            return None

    def _employee_name(self, obj) -> str | None:
        try:
            return obj.employee.full_name if obj.employee else None
        except Exception:
            return None

    @validates_schema
    def validate_dates(self, data: dict, **kwargs) -> None:
        start = data.get("start_date")
        end   = data.get("end_date")
        if start and end and end < start:
            raise ValidationError(
                "La date de fin ne peut pas précéder la date de début.",
                field_name="end_date",
            )


class EnrollmentCreateSchema(Schema):
    """
    Validation des données à la création d'une inscription.
    Le statut initial est toujours 'planifiee' — fixé par le service,
    pas par le client.
    """

    employee_id = fields.Integer(required=True)
    training_id = fields.Integer(required=True)
    start_date  = fields.Date(allow_none=True, load_default=None)
    end_date    = fields.Date(allow_none=True, load_default=None)

    @validates_schema
    def validate_dates(self, data: dict, **kwargs) -> None:
        start = data.get("start_date")
        end   = data.get("end_date")
        if start and end and end < start:
            raise ValidationError(
                "La date de fin ne peut pas précéder la date de début.",
                field_name="end_date",
            )


class EnrollmentStatusUpdateSchema(Schema):
    """
    Validation d'une transition de statut d'inscription.

    Transitions légales :
        planifiee  → en_cours   (start_date optionnelle)
        en_cours   → terminee   (end_date, score, final_comment optionnels)
        planifiee
        en_cours   → annulee    (aucun champ supplémentaire requis)

    Le service valide la cohérence de la transition ; ce schéma valide
    uniquement les types et plages de valeurs.
    """

    status        = fields.String(required=True, validate=validate.OneOf(ENROLLMENT_STATUSES))
    start_date    = fields.Date(allow_none=True, load_default=None)
    end_date      = fields.Date(allow_none=True, load_default=None)
    score         = fields.Float(allow_none=True, load_default=None,
                                  validate=validate.Range(min=0, max=100))
    final_comment = fields.String(allow_none=True, load_default=None,
                                   validate=validate.Length(max=5000))

    @validates_schema
    def validate_dates(self, data: dict, **kwargs) -> None:
        start = data.get("start_date")
        end   = data.get("end_date")
        if start and end and end < start:
            raise ValidationError(
                "La date de fin ne peut pas précéder la date de début.",
                field_name="end_date",
            )

    @validates_schema
    def validate_score_only_on_completion(self, data: dict, **kwargs) -> None:
        if data.get("score") is not None and data.get("status") != "terminee":
            raise ValidationError(
                "Le score ne peut être renseigné que pour le statut 'terminee'.",
                field_name="score",
            )


# =============================================================================
# Instances prêtes à l'emploi
# =============================================================================

training_schema         = TrainingSchema()
trainings_schema        = TrainingSchema(many=True)
training_create_schema  = TrainingCreateSchema()
training_update_schema  = TrainingUpdateSchema()

enrollment_schema               = EnrollmentSchema()
enrollments_schema              = EnrollmentSchema(many=True)
enrollment_create_schema        = EnrollmentCreateSchema()
enrollment_status_update_schema = EnrollmentStatusUpdateSchema()
