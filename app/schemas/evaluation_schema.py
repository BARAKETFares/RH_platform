"""
Schémas Marshmallow : EvaluationCampaign · Evaluation · EvaluationItem · Objective

Mêmes conventions que leave_schema.py / employee_schema.py :
  - <X>Schema        — sérialisation complète (lecture / réponse API)
  - <X>CreateSchema   — validation à la création (champs requis stricts)
  - <X>UpdateSchema    — validation à la mise à jour (tous champs optionnels)
"""
from __future__ import annotations

from marshmallow import Schema, ValidationError, fields, validate, validates, validates_schema


# =============================================================================
# Constantes partagées (alignées avec les modèles)
# =============================================================================

CAMPAIGN_PERIOD_TYPES = ("annual", "semester", "quarterly", "probation", "custom")
EVALUATION_STATUSES = ("draft", "in_progress", "employee_review", "completed", "archived")
OBJECTIVE_STATUSES = ("draft", "active", "completed", "cancelled", "overdue")
EVALUATION_ITEM_CATEGORIES = ("competence", "behavior", "objective")


# =============================================================================
# EvaluationCampaign
# =============================================================================

class EvaluationCampaignSchema(Schema):
    """Sérialisation complète d'une EvaluationCampaign, utilisée en lecture (GET)."""

    id = fields.Integer(dump_only=True)
    company_id = fields.Integer(required=True)
    created_by_id = fields.Integer(dump_only=True)

    name = fields.String(required=True, validate=validate.Length(min=1, max=150))
    description = fields.String(allow_none=True)
    period_year = fields.Integer(required=True, validate=validate.Range(min=2000, max=2100))
    period_type = fields.String(validate=validate.OneOf(CAMPAIGN_PERIOD_TYPES))

    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)
    objective_deadline = fields.Date(allow_none=True)

    is_active = fields.Boolean()

    # ── Champs dérivés (lecture seule) ────────────────────────────────────────
    is_open = fields.Boolean(dump_only=True)
    evaluation_count = fields.Method("_get_evaluation_count", dump_only=True)
    completed_count = fields.Method("_get_completed_count", dump_only=True)
    completion_rate_pct = fields.Method("_get_completion_rate", dump_only=True)

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    def _get_evaluation_count(self, obj) -> int:
        try:
            return obj.evaluation_count
        except Exception:
            return 0

    def _get_completed_count(self, obj) -> int:
        try:
            return obj.completed_count
        except Exception:
            return 0

    def _get_completion_rate(self, obj) -> float:
        try:
            return obj.completion_rate_pct
        except Exception:
            return 0.0

    @validates("name")
    def validate_name_not_blank(self, value: str, **kwargs) -> None:
        if not value.strip():
            raise ValidationError("Le nom de la campagne ne peut pas être vide.")

    @validates_schema
    def validate_dates(self, data: dict, **kwargs) -> None:
        start = data.get("start_date")
        end = data.get("end_date")
        if start and end and end < start:
            raise ValidationError(
                "La date de fin ne peut pas précéder la date de début.",
                field_name="end_date",
            )


class EvaluationCampaignCreateSchema(Schema):
    """Validation des données à la création d'une campagne d'évaluation."""

    company_id = fields.Integer(required=True)
    name = fields.String(required=True, validate=validate.Length(min=1, max=150))
    description = fields.String(allow_none=True)
    period_year = fields.Integer(required=True, validate=validate.Range(min=2000, max=2100))
    period_type = fields.String(load_default="annual", validate=validate.OneOf(CAMPAIGN_PERIOD_TYPES))

    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)
    objective_deadline = fields.Date(allow_none=True)
    is_active = fields.Boolean(load_default=True)

    @validates("name")
    def validate_name_not_blank(self, value: str, **kwargs) -> None:
        if not value.strip():
            raise ValidationError("Le nom de la campagne ne peut pas être vide.")

    @validates_schema
    def validate_dates(self, data: dict, **kwargs) -> None:
        start = data.get("start_date")
        end = data.get("end_date")
        if start and end and end < start:
            raise ValidationError(
                "La date de fin ne peut pas précéder la date de début.",
                field_name="end_date",
            )


class EvaluationCampaignUpdateSchema(Schema):
    """Validation des données à la mise à jour d'une campagne (PATCH)."""

    name = fields.String(validate=validate.Length(min=1, max=150))
    description = fields.String(allow_none=True)
    period_type = fields.String(validate=validate.OneOf(CAMPAIGN_PERIOD_TYPES))
    start_date = fields.Date()
    end_date = fields.Date()
    objective_deadline = fields.Date(allow_none=True)
    is_active = fields.Boolean()

    @validates_schema
    def validate_dates(self, data: dict, **kwargs) -> None:
        start = data.get("start_date")
        end = data.get("end_date")
        if start and end and end < start:
            raise ValidationError(
                "La date de fin ne peut pas précéder la date de début.",
                field_name="end_date",
            )


# =============================================================================
# Objective
# =============================================================================

class ObjectiveSchema(Schema):
    """Sérialisation complète d'un Objective, utilisée en lecture (GET)."""

    id = fields.Integer(dump_only=True)
    employee_id = fields.Integer(required=True)
    campaign_id = fields.Integer(allow_none=True)
    set_by_id = fields.Integer(dump_only=True)

    title = fields.String(required=True, validate=validate.Length(min=1, max=200))
    description = fields.String(allow_none=True)
    success_criteria = fields.String(allow_none=True)
    weight = fields.Decimal(places=2, as_string=False, validate=validate.Range(min=0.01, max=100))
    due_date = fields.Date(allow_none=True)

    status = fields.String(validate=validate.OneOf(OBJECTIVE_STATUSES))
    completion_pct = fields.Integer(validate=validate.Range(min=0, max=100))

    manager_rating = fields.Integer(allow_none=True, validate=validate.Range(min=1, max=5))
    employee_rating = fields.Integer(allow_none=True, validate=validate.Range(min=1, max=5))
    manager_comment = fields.String(allow_none=True)
    employee_comment = fields.String(allow_none=True)

    # ── Champs dérivés (lecture seule) ────────────────────────────────────────
    employee_name = fields.String(dump_only=True)
    set_by_name = fields.String(dump_only=True)
    is_overdue = fields.Boolean(dump_only=True)
    days_until_due = fields.Integer(allow_none=True, dump_only=True)
    rating_gap = fields.Integer(allow_none=True, dump_only=True)
    has_rating_discrepancy = fields.Boolean(dump_only=True)

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    @validates("title")
    def validate_title_not_blank(self, value: str, **kwargs) -> None:
        if not value.strip():
            raise ValidationError("Le titre de l'objectif ne peut pas être vide.")


class ObjectiveCreateSchema(Schema):
    """Validation des données à la création d'un objectif."""

    employee_id = fields.Integer(required=True)
    campaign_id = fields.Integer(allow_none=True)

    title = fields.String(required=True, validate=validate.Length(min=1, max=200))
    description = fields.String(allow_none=True)
    success_criteria = fields.String(allow_none=True)
    weight = fields.Decimal(
        load_default=100, places=2, as_string=False, validate=validate.Range(min=0.01, max=100)
    )
    due_date = fields.Date(allow_none=True)
    status = fields.String(load_default="draft", validate=validate.OneOf(OBJECTIVE_STATUSES))

    @validates("title")
    def validate_title_not_blank(self, value: str, **kwargs) -> None:
        if not value.strip():
            raise ValidationError("Le titre de l'objectif ne peut pas être vide.")


class ObjectiveUpdateSchema(Schema):
    """Validation des données à la mise à jour d'un objectif (PATCH)."""

    title = fields.String(validate=validate.Length(min=1, max=200))
    description = fields.String(allow_none=True)
    success_criteria = fields.String(allow_none=True)
    weight = fields.Decimal(places=2, as_string=False, validate=validate.Range(min=0.01, max=100))
    due_date = fields.Date(allow_none=True)
    status = fields.String(validate=validate.OneOf(OBJECTIVE_STATUSES))
    completion_pct = fields.Integer(validate=validate.Range(min=0, max=100))

    @validates("title")
    def validate_title_not_blank(self, value: str, **kwargs) -> None:
        if value is not None and not value.strip():
            raise ValidationError("Le titre de l'objectif ne peut pas être vide.")


class ObjectiveRatingSchema(Schema):
    """Validation de la soumission d'une note (manager ou employé) sur un objectif."""

    rating = fields.Integer(required=True, validate=validate.Range(min=1, max=5))
    comment = fields.String(allow_none=True, validate=validate.Length(max=2000))


# =============================================================================
# EvaluationItem
# =============================================================================

class EvaluationItemSchema(Schema):
    """Sérialisation complète d'un EvaluationItem, utilisée en lecture (GET)."""

    id = fields.Integer(dump_only=True)
    evaluation_id = fields.Integer(required=True)

    category = fields.String(required=True, validate=validate.OneOf(EVALUATION_ITEM_CATEGORIES))
    label = fields.String(required=True, validate=validate.Length(min=1, max=200))
    description = fields.String(allow_none=True)
    weight = fields.Decimal(places=2, as_string=False, validate=validate.Range(min=0.01))

    manager_score = fields.Decimal(allow_none=True, places=2, as_string=False, validate=validate.Range(min=0, max=5))
    employee_score = fields.Decimal(allow_none=True, places=2, as_string=False, validate=validate.Range(min=0, max=5))
    manager_comment = fields.String(allow_none=True)

    sort_order = fields.Integer()

    score_gap = fields.Float(allow_none=True, dump_only=True)

    @validates("label")
    def validate_label_not_blank(self, value: str, **kwargs) -> None:
        if not value.strip():
            raise ValidationError("Le libellé du critère ne peut pas être vide.")


class EvaluationItemCreateSchema(Schema):
    """Validation des données à la création d'un critère d'évaluation."""

    category = fields.String(required=True, validate=validate.OneOf(EVALUATION_ITEM_CATEGORIES))
    label = fields.String(required=True, validate=validate.Length(min=1, max=200))
    description = fields.String(allow_none=True)
    weight = fields.Decimal(load_default=1, places=2, as_string=False, validate=validate.Range(min=0.01))
    sort_order = fields.Integer(load_default=0)

    @validates("label")
    def validate_label_not_blank(self, value: str, **kwargs) -> None:
        if not value.strip():
            raise ValidationError("Le libellé du critère ne peut pas être vide.")


class EvaluationItemScoreSchema(Schema):
    """Validation de la notation d'un critère (manager ou employé)."""

    manager_score = fields.Decimal(allow_none=True, places=2, as_string=False, validate=validate.Range(min=0, max=5))
    employee_score = fields.Decimal(allow_none=True, places=2, as_string=False, validate=validate.Range(min=0, max=5))
    manager_comment = fields.String(allow_none=True, validate=validate.Length(max=2000))


# =============================================================================
# Evaluation
# =============================================================================

class EvaluationSchema(Schema):
    """Sérialisation complète d'une Evaluation, utilisée en lecture (GET)."""

    id = fields.Integer(dump_only=True)
    campaign_id = fields.Integer(required=True)
    employee_id = fields.Integer(required=True)
    evaluator_id = fields.Integer(required=True)

    status = fields.String(validate=validate.OneOf(EVALUATION_STATUSES))
    overall_score = fields.Decimal(allow_none=True, places=2, as_string=False, validate=validate.Range(min=0, max=5))

    manager_overall_comment = fields.String(allow_none=True)
    employee_overall_comment = fields.String(allow_none=True)
    strengths = fields.String(allow_none=True)
    areas_for_improvement = fields.String(allow_none=True)
    development_plan = fields.String(allow_none=True)

    sent_to_evaluator_at = fields.DateTime(allow_none=True, dump_only=True)
    evaluator_submitted_at = fields.DateTime(allow_none=True, dump_only=True)
    sent_to_employee_at = fields.DateTime(allow_none=True, dump_only=True)
    employee_acknowledged_at = fields.DateTime(allow_none=True, dump_only=True)
    completed_at = fields.DateTime(allow_none=True, dump_only=True)

    # ── Champs dérivés (lecture seule) ────────────────────────────────────────
    campaign_name = fields.String(dump_only=True)
    employee_name = fields.String(dump_only=True)
    evaluator_name = fields.String(dump_only=True)
    is_fully_signed = fields.Boolean(dump_only=True)
    items = fields.List(fields.Nested(EvaluationItemSchema), dump_only=True)

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    @validates_schema
    def validate_employee_differs_evaluator(self, data: dict, **kwargs) -> None:
        employee_id = data.get("employee_id")
        evaluator_id = data.get("evaluator_id")
        if employee_id and evaluator_id and employee_id == evaluator_id:
            raise ValidationError(
                "L'employé évalué ne peut pas être son propre évaluateur.",
                field_name="evaluator_id",
            )


class EvaluationCreateSchema(Schema):
    """
    Validation des données à la création d'une évaluation.
    Crée la fiche au statut 'draft' — le contenu détaillé (items, scores)
    est ajouté ensuite via des appels séparés.
    """

    campaign_id = fields.Integer(required=True)
    employee_id = fields.Integer(required=True)
    evaluator_id = fields.Integer(required=True)

    @validates_schema
    def validate_employee_differs_evaluator(self, data: dict, **kwargs) -> None:
        if data.get("employee_id") == data.get("evaluator_id"):
            raise ValidationError(
                "L'employé évalué ne peut pas être son propre évaluateur.",
                field_name="evaluator_id",
            )


class EvaluationContentUpdateSchema(Schema):
    """Validation de la mise à jour du contenu d'une évaluation (rédaction manager/employé)."""

    overall_score = fields.Decimal(allow_none=True, places=2, as_string=False, validate=validate.Range(min=0, max=5))
    manager_overall_comment = fields.String(allow_none=True, validate=validate.Length(max=5000))
    employee_overall_comment = fields.String(allow_none=True, validate=validate.Length(max=5000))
    strengths = fields.String(allow_none=True, validate=validate.Length(max=2000))
    areas_for_improvement = fields.String(allow_none=True, validate=validate.Length(max=2000))
    development_plan = fields.String(allow_none=True, validate=validate.Length(max=2000))


class EvaluationSignatureSchema(Schema):
    """Validation de la signature électronique (hash fourni par le client ou généré serveur)."""

    signature_hash = fields.String(allow_none=True, validate=validate.Length(max=255))


# =============================================================================
# Schémas d'instance prêts à l'emploi
# =============================================================================

evaluation_campaign_schema = EvaluationCampaignSchema()
evaluation_campaigns_schema = EvaluationCampaignSchema(many=True)
evaluation_campaign_create_schema = EvaluationCampaignCreateSchema()
evaluation_campaign_update_schema = EvaluationCampaignUpdateSchema()

objective_schema = ObjectiveSchema()
objectives_schema = ObjectiveSchema(many=True)
objective_create_schema = ObjectiveCreateSchema()
objective_update_schema = ObjectiveUpdateSchema()
objective_rating_schema = ObjectiveRatingSchema()

evaluation_item_schema = EvaluationItemSchema()
evaluation_items_schema = EvaluationItemSchema(many=True)
evaluation_item_create_schema = EvaluationItemCreateSchema()
evaluation_item_score_schema = EvaluationItemScoreSchema()

evaluation_schema = EvaluationSchema()
evaluations_schema = EvaluationSchema(many=True)
evaluation_create_schema = EvaluationCreateSchema()
evaluation_content_update_schema = EvaluationContentUpdateSchema()
evaluation_signature_schema = EvaluationSignatureSchema()