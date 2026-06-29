"""
Formulaires WTForms du module Payroll.

GeneratePaySlipForm   — déclenchement de la génération d'un bulletin.
PaySlipFilterForm     — filtres GET sur la liste des bulletins (CSRF désactivé).
AddPayElementForm     — ajout manuel d'une ligne sur un bulletin draft.
PaySlipActionForm     — formulaire vide (juste CSRF) pour validate/pay.
"""
from __future__ import annotations

from datetime import date

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DecimalField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import (
    DataRequired,
    Length,
    NumberRange,
    Optional as OptionalValidator,
)


# ── Choix partagés ────────────────────────────────────────────────────────────

_MONTH_CHOICES: list[tuple[int, str]] = [
    (1, "Janvier"),   (2, "Février"),  (3, "Mars"),
    (4, "Avril"),     (5, "Mai"),      (6, "Juin"),
    (7, "Juillet"),   (8, "Août"),     (9, "Septembre"),
    (10, "Octobre"),  (11, "Novembre"),(12, "Décembre"),
]

_ELEMENT_TYPE_CHOICES: list[tuple[str, str]] = [
    ("bonus",        "Prime / Indemnité"),
    ("deduction",    "Retenue"),
    ("contribution", "Cotisation"),
]


# =============================================================================
# GeneratePaySlipForm
# =============================================================================

class GeneratePaySlipForm(FlaskForm):
    """Déclenchement de la génération d'un bulletin de paie."""

    employee_id = SelectField(
        "Employé",
        coerce=int,
        validators=[DataRequired(message="Sélectionnez un employé.")],
    )
    period_year = IntegerField(
        "Année",
        validators=[
            DataRequired(),
            NumberRange(min=2000, max=2100, message="Année invalide."),
        ],
        default=lambda: date.today().year,
    )
    period_month = SelectField(
        "Mois",
        coerce=int,
        choices=_MONTH_CHOICES,
        validators=[DataRequired()],
        default=lambda: date.today().month,
    )
    gross_override = DecimalField(
        "Salaire brut mensuel (€) — laissez vide pour utiliser le contrat actif",
        validators=[OptionalValidator(), NumberRange(min=0.01)],
        places=2,
    )
    notes = TextAreaField(
        "Notes internes",
        validators=[OptionalValidator(), Length(max=500)],
        render_kw={"rows": 2},
    )
    submit = SubmitField("Générer le bulletin")

    def populate_employees(self, company_id: int) -> None:
        """Charge les employés actifs de l'entreprise."""
        from app.extensions import db
        from app.models.employee import Employee
        employees = db.session.execute(
            db.select(Employee)
            .where(
                Employee.company_id == company_id,
                Employee.status.in_((
                    Employee.STATUS_ACTIVE,
                    Employee.STATUS_ON_LEAVE,
                    Employee.STATUS_PROBATION,
                )),
            )
            .order_by(Employee.last_name, Employee.first_name)
        ).scalars().all()
        self.employee_id.choices = [
            (e.id, f"{e.full_name} ({e.employee_number or '—'})")
            for e in employees
        ]


# =============================================================================
# PaySlipFilterForm  (GET — CSRF désactivé)
# =============================================================================

class PaySlipFilterForm(FlaskForm):
    """Filtres pour la liste des bulletins de paie."""

    class Meta:
        csrf = False

    employee_id = SelectField(
        "Employé",
        coerce=int,
        validators=[OptionalValidator()],
    )
    period_year = IntegerField(
        "Année",
        validators=[OptionalValidator(), NumberRange(min=2000, max=2100)],
    )
    period_month = SelectField(
        "Mois",
        coerce=int,
        choices=[(-1, "Tous les mois")] + _MONTH_CHOICES,
        validators=[OptionalValidator()],
    )
    status = SelectField(
        "Statut",
        choices=[
            ("",          "Tous les statuts"),
            ("draft",     "Généré"),
            ("validated", "Validé"),
            ("paid",      "Payé"),
        ],
        validators=[OptionalValidator()],
    )
    submit = SubmitField("Filtrer")

    def populate_employees(self, company_id: int) -> None:
        from app.extensions import db
        from app.models.employee import Employee
        employees = db.session.execute(
            db.select(Employee)
            .where(Employee.company_id == company_id)
            .order_by(Employee.last_name, Employee.first_name)
        ).scalars().all()
        self.employee_id.choices = [(0, "Tous les employés")] + [
            (e.id, e.full_name) for e in employees
        ]


# =============================================================================
# AddPayElementForm
# =============================================================================

class AddPayElementForm(FlaskForm):
    """Ajout manuel d'une ligne de paie sur un bulletin draft."""

    element_type = SelectField(
        "Type",
        choices=_ELEMENT_TYPE_CHOICES,
        validators=[DataRequired()],
    )
    label = StringField(
        "Libellé",
        validators=[DataRequired(), Length(min=1, max=200)],
        render_kw={"placeholder": "Prime d'ancienneté"},
    )
    amount = DecimalField(
        "Montant (€)",
        validators=[DataRequired(), NumberRange(min=0.01)],
        places=2,
    )
    is_employer = BooleanField("Cotisation patronale (décoché = salariale)")
    rate = DecimalField(
        "Taux (%)",
        validators=[OptionalValidator(), NumberRange(min=0.0001, max=100)],
        places=4,
    )
    base_amount = DecimalField(
        "Assiette (€)",
        validators=[OptionalValidator(), NumberRange(min=0.01)],
        places=2,
    )
    submit = SubmitField("Ajouter la ligne")


# =============================================================================
# PaySlipActionForm  — formulaire CSRF vide pour validate / pay
# =============================================================================

class PaySlipActionForm(FlaskForm):
    """Formulaire sans champs utilisé pour les actions validate et pay (protection CSRF)."""

    submit = SubmitField("Confirmer")
