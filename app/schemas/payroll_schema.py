"""
Schémas Marshmallow : PaySlip · PayElement

Trois variantes par ressource (convention du projet) :
  - <X>Schema       — sérialisation complète (lecture / réponse API)
  - <X>CreateSchema  — validation à la création (champs requis stricts)
  - <X>UpdateSchema   — mise à jour partielle (tous champs optionnels)

Les montants Decimal sont sérialisés en chaîne (`as_string=True`) pour éviter
l'erreur "Decimal not JSON serializable" avec json.dumps natif.
"""
from __future__ import annotations

from marshmallow import Schema, fields, validate, validates, validates_schema, ValidationError


# =============================================================================
# Constantes (alignées avec app.models.payroll)
# =============================================================================

PAYSLIP_STATUSES    = ("draft", "validated", "paid")
PAY_ELEMENT_TYPES   = ("bonus", "deduction", "contribution")


# =============================================================================
# PayElementSchema — sérialisation complète
# =============================================================================

class PayElementSchema(Schema):
    """Sérialisation complète d'une ligne de bulletin (lecture)."""

    id           = fields.Integer(dump_only=True)
    payslip_id   = fields.Integer(dump_only=True)

    element_type = fields.String(dump_only=True)
    type_label   = fields.String(dump_only=True)
    label        = fields.String(dump_only=True)
    is_employer  = fields.Boolean(dump_only=True)

    amount       = fields.Decimal(as_string=True, dump_only=True)
    rate         = fields.Decimal(as_string=True, allow_none=True, dump_only=True)
    base_amount  = fields.Decimal(as_string=True, allow_none=True, dump_only=True)
    signed_amount = fields.Decimal(as_string=True, dump_only=True)


# =============================================================================
# PayElementCreateSchema — ajout manuel d'un élément sur un bulletin draft
# =============================================================================

class PayElementCreateSchema(Schema):
    """Validation d'un PayElement ajouté manuellement (prime, retenue exceptionnelle)."""

    payslip_id   = fields.Integer(required=True)
    element_type = fields.String(
        required=True,
        validate=validate.OneOf(PAY_ELEMENT_TYPES),
    )
    label        = fields.String(required=True, validate=validate.Length(min=1, max=200))
    is_employer  = fields.Boolean(load_default=False)
    amount       = fields.Decimal(
        required=True,
        places=2,
        validate=validate.Range(min=0.01),
    )
    rate        = fields.Decimal(places=4, allow_none=True, load_default=None)
    base_amount = fields.Decimal(places=2, allow_none=True, load_default=None)

    @validates("rate")
    def _validate_rate(self, value):
        if value is not None and not (0 < float(value) <= 100):
            raise ValidationError("Le taux doit être compris entre 0 et 100 %.")


# =============================================================================
# PaySlipSchema — sérialisation complète
# =============================================================================

class PaySlipSchema(Schema):
    """Sérialisation complète d'un bulletin de paie (lecture)."""

    id          = fields.Integer(dump_only=True)
    employee_id = fields.Integer(dump_only=True)
    contract_id = fields.Integer(allow_none=True, dump_only=True)

    # ── Période ───────────────────────────────────────────────────────────────
    period_year  = fields.Integer(dump_only=True)
    period_month = fields.Integer(dump_only=True)
    period_label = fields.String(dump_only=True)

    # ── Montants ──────────────────────────────────────────────────────────────
    gross_salary                   = fields.Decimal(as_string=True, dump_only=True)
    total_employee_contributions   = fields.Decimal(as_string=True, dump_only=True)
    total_employer_contributions   = fields.Decimal(as_string=True, dump_only=True)
    net_salary                     = fields.Decimal(as_string=True, dump_only=True)
    employer_cost                  = fields.Decimal(as_string=True, dump_only=True)

    # ── Statut ────────────────────────────────────────────────────────────────
    status        = fields.String(dump_only=True)
    status_label  = fields.String(dump_only=True)
    validated_at  = fields.DateTime(allow_none=True, dump_only=True)
    paid_at       = fields.DateTime(allow_none=True, dump_only=True)
    payment_reference = fields.String(allow_none=True, dump_only=True)

    notes      = fields.String(allow_none=True, dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    # ── Éléments imbriqués (optionnel, chargé via include_elements=True) ─────
    elements = fields.List(fields.Nested(PayElementSchema), dump_only=True)


# =============================================================================
# PaySlipCreateSchema — déclenchement de la génération d'un bulletin
# =============================================================================

class PaySlipCreateSchema(Schema):
    """
    Paramètres d'entrée pour generate_payslip().

    Les montants (gross, net, cotisations) sont calculés par le service,
    pas fournis par le client.
    """

    employee_id  = fields.Integer(required=True)
    period_year  = fields.Integer(
        required=True,
        validate=validate.Range(min=2000, max=2100),
    )
    period_month = fields.Integer(
        required=True,
        validate=validate.Range(min=1, max=12),
    )
    gross_salary_override = fields.Decimal(
        places=2,
        allow_none=True,
        load_default=None,
        validate=validate.Range(min=0.01),
        metadata={"description": "Remplace le brut du contrat actif si fourni."},
    )
    notes = fields.String(allow_none=True, load_default=None)

    @validates_schema
    def _validate_period(self, data, **kwargs):
        year  = data.get("period_year")
        month = data.get("period_month")
        if year and month and not (1 <= month <= 12):
            raise ValidationError(
                {"period_month": ["Le mois doit être compris entre 1 et 12."]}
            )


# =============================================================================
# PaySlipUpdateSchema — modification d'un bulletin draft
# =============================================================================

class PaySlipUpdateSchema(Schema):
    """
    Mise à jour partielle d'un bulletin.
    Seuls les champs non calculés sont modifiables (notes, référence paiement).
    Les montants ne sont pas rééditables après génération — il faut regénérer.
    """

    payment_reference = fields.String(
        allow_none=True,
        validate=validate.Length(max=100),
    )
    notes = fields.String(allow_none=True)


# =============================================================================
# Instances partagées
# =============================================================================

pay_element_schema         = PayElementSchema()
pay_elements_schema        = PayElementSchema(many=True)
pay_element_create_schema  = PayElementCreateSchema()

payslip_schema             = PaySlipSchema()
payslips_schema            = PaySlipSchema(many=True)
payslip_with_elements_schema = PaySlipSchema()   # éléments chargés via selectin

payslip_create_schema      = PaySlipCreateSchema()
payslip_update_schema      = PaySlipUpdateSchema()
