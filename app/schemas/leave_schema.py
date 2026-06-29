"""
Schémas Marshmallow : LeaveType · LeaveBalance · LeaveRequest

Mêmes conventions que employee_schema.py / department_schema.py :
  - <X>Schema        — sérialisation complète (lecture / réponse API)
  - <X>CreateSchema   — validation à la création (champs requis stricts)
  - <X>UpdateSchema    — validation à la mise à jour (tous champs optionnels)

LeaveBalance n'a pas de CreateSchema classique : les soldes sont créés
automatiquement via LeaveBalance.get_or_create() au niveau service, jamais
saisis directement par l'utilisateur — seul un AdjustmentSchema existe pour
les régularisations manuelles RH.
"""
from __future__ import annotations

from marshmallow import Schema, ValidationError, fields, validate, validates, validates_schema


# =============================================================================
# Constantes partagées (alignées avec les modèles)
# =============================================================================

LEAVE_REQUEST_STATUSES = (
    "draft", "pending_manager", "pending_hr", "approved", "rejected", "cancelled",
)

COLOR_HEX_REGEX = r"^#[0-9A-Fa-f]{6}$"


# =============================================================================
# LeaveType — sérialisation complète
# =============================================================================

class LeaveTypeSchema(Schema):
    """Sérialisation complète d'un LeaveType, utilisée en lecture (GET)."""

    id = fields.Integer(dump_only=True)
    company_id = fields.Integer(required=True)

    name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    code = fields.String(required=True, validate=validate.Length(min=1, max=20))
    color_hex = fields.String(validate=validate.Regexp(COLOR_HEX_REGEX))
    description = fields.String(allow_none=True)

    requires_justification = fields.Boolean()
    requires_document = fields.Boolean()
    max_consecutive_days = fields.Integer(allow_none=True, validate=validate.Range(min=1))
    min_advance_notice_days = fields.Integer(validate=validate.Range(min=0))

    is_paid = fields.Boolean()
    impacts_leave_balance = fields.Boolean()
    is_active = fields.Boolean()

    # ── Champs dérivés (lecture seule) ────────────────────────────────────────
    display_label = fields.String(dump_only=True)
    requires_approval_workflow = fields.Boolean(dump_only=True)

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    @validates("name")
    def validate_name_not_blank(self, value: str, **kwargs) -> None:
        if not value.strip():
            raise ValidationError("Le nom du type d'absence ne peut pas être vide.")

    @validates("code")
    def validate_code_not_blank(self, value: str, **kwargs) -> None:
        if not value.strip():
            raise ValidationError("Le code du type d'absence ne peut pas être vide.")


class LeaveTypeCreateSchema(Schema):
    """Validation des données à la création d'un type d'absence."""

    company_id = fields.Integer(required=True)

    name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    code = fields.String(required=True, validate=validate.Length(min=1, max=20))
    color_hex = fields.String(load_default="#6c757d", validate=validate.Regexp(COLOR_HEX_REGEX))
    description = fields.String(allow_none=True)

    requires_justification = fields.Boolean(load_default=False)
    requires_document = fields.Boolean(load_default=False)
    max_consecutive_days = fields.Integer(allow_none=True, validate=validate.Range(min=1))
    min_advance_notice_days = fields.Integer(load_default=0, validate=validate.Range(min=0))

    is_paid = fields.Boolean(load_default=True)
    impacts_leave_balance = fields.Boolean(load_default=True)
    is_active = fields.Boolean(load_default=True)

    @validates("name")
    def validate_name_not_blank(self, value: str, **kwargs) -> None:
        if not value.strip():
            raise ValidationError("Le nom du type d'absence ne peut pas être vide.")

    @validates("code")
    def validate_code_not_blank(self, value: str, **kwargs) -> None:
        if not value.strip():
            raise ValidationError("Le code du type d'absence ne peut pas être vide.")


class LeaveTypeUpdateSchema(Schema):
    """Validation des données à la mise à jour d'un type d'absence (PATCH)."""

    name = fields.String(validate=validate.Length(min=1, max=100))
    code = fields.String(validate=validate.Length(min=1, max=20))
    color_hex = fields.String(validate=validate.Regexp(COLOR_HEX_REGEX))
    description = fields.String(allow_none=True)

    requires_justification = fields.Boolean()
    requires_document = fields.Boolean()
    max_consecutive_days = fields.Integer(allow_none=True, validate=validate.Range(min=1))
    min_advance_notice_days = fields.Integer(validate=validate.Range(min=0))

    is_paid = fields.Boolean()
    impacts_leave_balance = fields.Boolean()
    is_active = fields.Boolean()

    @validates("name")
    def validate_name_not_blank(self, value: str, **kwargs) -> None:
        if value is not None and not value.strip():
            raise ValidationError("Le nom du type d'absence ne peut pas être vide.")

    @validates("code")
    def validate_code_not_blank(self, value: str, **kwargs) -> None:
        if value is not None and not value.strip():
            raise ValidationError("Le code du type d'absence ne peut pas être vide.")


# =============================================================================
# LeaveBalance — sérialisation et ajustement manuel
# =============================================================================

class LeaveBalanceSchema(Schema):
    """Sérialisation complète d'un LeaveBalance, utilisée en lecture (GET)."""

    id = fields.Integer(dump_only=True)

    employee_id = fields.Integer(required=True)
    leave_type_id = fields.Integer(required=True)
    year = fields.Integer(required=True, validate=validate.Range(min=2000, max=2100))

    initial_balance = fields.Decimal(places=2, as_string=False, validate=validate.Range(min=0))
    carried_over = fields.Decimal(places=2, as_string=False, validate=validate.Range(min=0))
    acquired = fields.Decimal(places=2, as_string=False, validate=validate.Range(min=0))
    taken = fields.Decimal(places=2, as_string=False, validate=validate.Range(min=0))
    pending = fields.Decimal(places=2, as_string=False, validate=validate.Range(min=0))
    adjustment = fields.Decimal(places=2, as_string=False)

    # ── Champs dérivés (lecture seule) ────────────────────────────────────────
    leave_type_code = fields.String(dump_only=True)
    leave_type_name = fields.String(dump_only=True)
    leave_type_color = fields.String(dump_only=True)
    remaining = fields.Float(dump_only=True)
    available = fields.Float(dump_only=True)
    usage_rate_pct = fields.Float(dump_only=True)

    updated_at = fields.DateTime(dump_only=True)


class LeaveBalanceAdjustmentSchema(Schema):
    """
    Validation d'une régularisation manuelle de solde par un RH/Admin.
    N'autorise QUE la modification du champ `adjustment` (delta appliqué),
    accompagnée obligatoirement d'un motif pour l'audit.
    """

    days = fields.Decimal(
        required=True, places=2, as_string=False,
        metadata={"description": "Delta à appliquer — peut être négatif (régularisation à la baisse)"},
    )
    reason = fields.String(required=True, validate=validate.Length(min=3, max=500))

    @validates("days")
    def validate_days_not_zero(self, value, **kwargs) -> None:
        if value == 0:
            raise ValidationError("Le delta d'ajustement ne peut pas être égal à zéro.")

    @validates("reason")
    def validate_reason_not_blank(self, value: str, **kwargs) -> None:
        if not value.strip():
            raise ValidationError("Le motif de régularisation est obligatoire.")


# =============================================================================
# LeaveRequest — sérialisation complète
# =============================================================================

class LeaveRequestSchema(Schema):
    """Sérialisation complète d'une LeaveRequest, utilisée en lecture (GET)."""

    id = fields.Integer(dump_only=True)

    employee_id = fields.Integer(required=True)
    leave_type_id = fields.Integer(required=True)

    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)
    start_half_day = fields.Boolean()
    end_half_day = fields.Boolean()
    working_days = fields.Decimal(allow_none=True, places=2, as_string=False, dump_only=True)

    status = fields.String(validate=validate.OneOf(LEAVE_REQUEST_STATUSES))
    employee_comment = fields.String(allow_none=True)
    document_path = fields.String(allow_none=True, dump_only=True)
    is_emergency = fields.Boolean()

    manager_id = fields.Integer(allow_none=True, dump_only=True)
    manager_decision_at = fields.DateTime(allow_none=True, dump_only=True)
    manager_comment = fields.String(allow_none=True)

    hr_user_id = fields.Integer(allow_none=True, dump_only=True)
    hr_decision_at = fields.DateTime(allow_none=True, dump_only=True)
    hr_comment = fields.String(allow_none=True)

    cancelled_at = fields.DateTime(allow_none=True, dump_only=True)
    cancellation_reason = fields.String(allow_none=True)

    # ── Champs dérivés (lecture seule) ────────────────────────────────────────
    employee_name = fields.String(dump_only=True)
    leave_type_name = fields.String(dump_only=True)
    leave_type_code = fields.String(dump_only=True)
    leave_type_color = fields.String(dump_only=True)
    manager_name = fields.String(dump_only=True)
    calendar_days = fields.Integer(dump_only=True)
    waiting_for = fields.String(allow_none=True, dump_only=True)

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    @validates_schema
    def validate_end_after_start(self, data: dict, **kwargs) -> None:
        start = data.get("start_date")
        end = data.get("end_date")
        if start and end and end < start:
            raise ValidationError(
                "La date de fin ne peut pas précéder la date de début.",
                field_name="end_date",
            )


# =============================================================================
# LeaveRequestCreateSchema — soumission d'une nouvelle demande
# =============================================================================

class LeaveRequestCreateSchema(Schema):
    """
    Validation des données à la création d'une demande d'absence.
    employee_id est volontairement requis ici (et non déduit du JWT) afin
    que ce schéma reste réutilisable côté admin/RH (création pour un tiers) ;
    la route applicative peut imposer employee_id = current_user si nécessaire.
    """

    employee_id = fields.Integer(required=True)
    leave_type_id = fields.Integer(required=True)

    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)
    start_half_day = fields.Boolean(load_default=False)
    end_half_day = fields.Boolean(load_default=False)

    employee_comment = fields.String(allow_none=True, validate=validate.Length(max=2000))
    document_path = fields.String(allow_none=True, validate=validate.Length(max=500))
    is_emergency = fields.Boolean(load_default=False)

    @validates_schema
    def validate_end_after_start(self, data: dict, **kwargs) -> None:
        start = data.get("start_date")
        end = data.get("end_date")
        if start and end and end < start:
            raise ValidationError(
                "La date de fin ne peut pas précéder la date de début.",
                field_name="end_date",
            )

    @validates_schema
    def validate_not_in_past(self, data: dict, **kwargs) -> None:
        from datetime import date as _date
        start = data.get("start_date")
        if start and start < _date.today():
            raise ValidationError(
                "La date de début ne peut pas être antérieure à aujourd'hui.",
                field_name="start_date",
            )


# =============================================================================
# LeaveRequestUpdateSchema — modification d'une demande non encore traitée
# =============================================================================

class LeaveRequestUpdateSchema(Schema):
    """
    Validation des données à la mise à jour d'une demande d'absence.
    Réservé aux demandes encore au statut 'draft' ou 'pending_manager' —
    la vérification de l'état autorisant la modification est faite au
    niveau service, pas dans ce schéma.
    """

    leave_type_id = fields.Integer()

    start_date = fields.Date()
    end_date = fields.Date()
    start_half_day = fields.Boolean()
    end_half_day = fields.Boolean()

    employee_comment = fields.String(allow_none=True, validate=validate.Length(max=2000))
    document_path = fields.String(allow_none=True, validate=validate.Length(max=500))
    is_emergency = fields.Boolean()

    @validates_schema
    def validate_end_after_start(self, data: dict, **kwargs) -> None:
        start = data.get("start_date")
        end = data.get("end_date")
        if start and end and end < start:
            raise ValidationError(
                "La date de fin ne peut pas précéder la date de début.",
                field_name="end_date",
            )


# =============================================================================
# LeaveRequestDecisionSchema — approbation / refus (manager ou RH)
# =============================================================================

class LeaveRequestDecisionSchema(Schema):
    """
    Validation d'une décision d'approbation ou de refus.
    Utilisé pour les deux niveaux (manager et RH) — le service applicatif
    détermine quel champ (manager_* ou hr_*) renseigner selon le rôle
    de l'utilisateur courant et le statut actuel de la demande.
    """

    decision = fields.String(
        required=True,
        validate=validate.OneOf(("approve", "reject")),
    )
    comment = fields.String(allow_none=True, validate=validate.Length(max=2000))

    @validates_schema
    def validate_comment_required_on_reject(self, data: dict, **kwargs) -> None:
        if data.get("decision") == "reject" and not (data.get("comment") or "").strip():
            raise ValidationError(
                "Un motif est obligatoire en cas de refus.",
                field_name="comment",
            )


class LeaveRequestCancelSchema(Schema):
    """Validation de l'annulation d'une demande par l'employé ou un RH/Admin."""

    reason = fields.String(allow_none=True, validate=validate.Length(max=500))


# =============================================================================
# Schémas d'instance prêts à l'emploi
# =============================================================================

leave_type_schema = LeaveTypeSchema()
leave_types_schema = LeaveTypeSchema(many=True)
leave_type_create_schema = LeaveTypeCreateSchema()
leave_type_update_schema = LeaveTypeUpdateSchema()

leave_balance_schema = LeaveBalanceSchema()
leave_balances_schema = LeaveBalanceSchema(many=True)
leave_balance_adjustment_schema = LeaveBalanceAdjustmentSchema()

leave_request_schema = LeaveRequestSchema()
leave_requests_schema = LeaveRequestSchema(many=True)
leave_request_create_schema = LeaveRequestCreateSchema()
leave_request_update_schema = LeaveRequestUpdateSchema()
leave_request_decision_schema = LeaveRequestDecisionSchema()
leave_request_cancel_schema = LeaveRequestCancelSchema()

# Variante allégée pour les listes déroulantes (selects) de types d'absence
leave_type_light_schema = LeaveTypeSchema(
    only=("id", "name", "code", "color_hex", "is_active"),
    many=True,
)