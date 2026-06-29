"""
Formulaires WTForms du module Performance (Évaluations & Objectifs).

ObjectiveForm           — création d'un nouvel objectif pour un employé.
ObjectiveRatingForm       — soumission d'une note (manager ou employé).
EvaluationCampaignForm     — création d'une campagne d'évaluation.
EvaluationContentForm        — rédaction du contenu par l'évaluateur (manager).
EvaluationAcknowledgeForm      — accusé de réception par l'employé.
"""
from __future__ import annotations

from datetime import date

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
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
    ValidationError,
)


# =============================================================================
# ObjectiveForm — création d'un objectif
# =============================================================================

class ObjectiveForm(FlaskForm):
    """
    Formulaire de création d'un objectif pour un employé (logique SMART).

    employee_id est un SelectField peuplé dynamiquement via
    populate_employees() — utilisé par un manager pour fixer un objectif
    à un membre de son équipe.
    """

    employee_id = SelectField(
        "Employé concerné",
        coerce=int,
        validators=[DataRequired(message="Veuillez sélectionner un employé.")],
    )
    campaign_id = SelectField(
        "Campagne (optionnel)",
        coerce=int,
        validators=[OptionalValidator()],
    )

    title = StringField(
        "Titre de l'objectif",
        validators=[DataRequired(message="Le titre est obligatoire."), Length(max=200)],
        render_kw={"autofocus": True},
    )
    description = TextAreaField(
        "Description",
        validators=[OptionalValidator(), Length(max=2000)],
        render_kw={"rows": 3},
    )
    success_criteria = TextAreaField(
        "Critères de réussite mesurables",
        validators=[OptionalValidator(), Length(max=2000)],
        render_kw={"rows": 2, "placeholder": "Ex : Augmenter le taux de conversion de 10%..."},
    )
    weight = DecimalField(
        "Pondération (%)",
        validators=[
            DataRequired(message="La pondération est obligatoire."),
            NumberRange(min=0.01, max=100, message="Doit être comprise entre 0 et 100."),
        ],
        places=2,
        default=100,
    )
    due_date = DateField(
        "Date d'échéance",
        validators=[OptionalValidator()],
        format="%Y-%m-%d",
    )

    submit = SubmitField("Créer l'objectif")

    def populate_employees(self, manager_employee_id: int) -> None:
        """Charge les membres de l'équipe directe du manager connecté."""
        from app.extensions import db
        from app.models.employee import Employee

        team = db.session.execute(
            db.select(Employee).where(
                Employee.manager_id == manager_employee_id,
                Employee.status.in_((Employee.STATUS_ACTIVE, Employee.STATUS_PROBATION)),
            ).order_by(Employee.last_name)
        ).scalars().all()
        self.employee_id.choices = [(e.id, e.full_name) for e in team]

    def populate_campaigns(self, company_id: int) -> None:
        from app.extensions import db
        from app.models.evaluation import EvaluationCampaign

        campaigns = db.session.execute(
            EvaluationCampaign.active_in_company(company_id)
        ).scalars().all()
        self.campaign_id.choices = [(0, "— Aucune —")] + [(c.id, c.name) for c in campaigns]

    def validate_due_date(self, field: DateField) -> None:
        if field.data and field.data < date.today():
            raise ValidationError("La date d'échéance ne peut pas être dans le passé.")


# =============================================================================
# ObjectiveRatingForm — notation d'un objectif
# =============================================================================

class ObjectiveRatingForm(FlaskForm):
    """Formulaire de notation d'un objectif (manager ou employé)."""

    rating = IntegerField(
        "Note (1 à 5)",
        validators=[
            DataRequired(message="La note est obligatoire."),
            NumberRange(min=1, max=5, message="La note doit être comprise entre 1 et 5."),
        ],
    )
    comment = TextAreaField(
        "Commentaire",
        validators=[OptionalValidator(), Length(max=2000)],
        render_kw={"rows": 3},
    )
    submit = SubmitField("Enregistrer la note")


class ObjectiveProgressForm(FlaskForm):
    """Formulaire de mise à jour rapide de l'avancement d'un objectif."""

    completion_pct = IntegerField(
        "Avancement (%)",
        validators=[
            DataRequired(message="L'avancement est obligatoire."),
            NumberRange(min=0, max=100, message="Doit être compris entre 0 et 100."),
        ],
    )
    submit = SubmitField("Mettre à jour")


# =============================================================================
# AddEvaluationForm — ajout d'un participant à une campagne
# =============================================================================

class AddEvaluationForm(FlaskForm):
    """Formulaire d'ajout d'un participant (employé + évaluateur) à une campagne."""

    employee_id = SelectField(
        "Employé évalué",
        coerce=int,
        validators=[DataRequired(message="Veuillez sélectionner un employé.")],
    )
    evaluator_id = SelectField(
        "Évaluateur",
        coerce=int,
        validators=[DataRequired(message="Veuillez sélectionner un évaluateur.")],
    )

    submit = SubmitField("Ajouter à la campagne")

    def populate_employees(self, company_id: int, exclude_employee_ids: set[int] | None = None) -> None:
        """Charge tous les employés actifs de l'entreprise."""
        from app.extensions import db
        from app.models.employee import Employee

        employees = db.session.execute(
            db.select(Employee).where(
                Employee.company_id == company_id,
                Employee.status.in_((Employee.STATUS_ACTIVE, Employee.STATUS_PROBATION)),
            ).order_by(Employee.last_name, Employee.first_name)
        ).scalars().all()

        excluded = exclude_employee_ids or set()
        all_choices = [(e.id, e.full_name) for e in employees]
        # Évaluateurs : tous les employés actifs
        self.evaluator_id.choices = all_choices
        # Employés à évaluer : exclure ceux qui ont déjà une évaluation dans la campagne
        self.employee_id.choices = [(e.id, e.full_name) for e in employees if e.id not in excluded]

    def validate_evaluator_id(self, field: SelectField) -> None:
        if field.data and self.employee_id.data and field.data == self.employee_id.data:
            raise ValidationError("L'employé ne peut pas être son propre évaluateur.")


# =============================================================================
# EvaluationCampaignForm — création d'une campagne
# =============================================================================

class EvaluationCampaignForm(FlaskForm):
    """Formulaire de création d'une campagne d'évaluation."""

    name = StringField(
        "Nom de la campagne",
        validators=[DataRequired(message="Le nom est obligatoire."), Length(max=150)],
        render_kw={"placeholder": "Ex : Évaluation annuelle 2026", "autofocus": True},
    )
    description = TextAreaField(
        "Description",
        validators=[OptionalValidator(), Length(max=2000)],
        render_kw={"rows": 2},
    )
    period_year = IntegerField(
        "Année",
        validators=[
            DataRequired(message="L'année est obligatoire."),
            NumberRange(min=2000, max=2100),
        ],
        default=lambda: date.today().year,
    )
    period_type = SelectField(
        "Type de période",
        choices=[
            ("annual", "Annuelle"),
            ("semester", "Semestrielle"),
            ("quarterly", "Trimestrielle"),
            ("probation", "Fin de période d'essai"),
            ("custom", "Personnalisée"),
        ],
        validators=[DataRequired()],
        default="annual",
    )
    start_date = DateField(
        "Date de début",
        validators=[DataRequired(message="La date de début est obligatoire.")],
        format="%Y-%m-%d",
    )
    end_date = DateField(
        "Date de fin",
        validators=[DataRequired(message="La date de fin est obligatoire.")],
        format="%Y-%m-%d",
    )
    objective_deadline = DateField(
        "Date limite de définition des objectifs",
        validators=[OptionalValidator()],
        format="%Y-%m-%d",
    )

    submit = SubmitField("Créer la campagne")

    def validate_end_date(self, field: DateField) -> None:
        if field.data and self.start_date.data and field.data < self.start_date.data:
            raise ValidationError("La date de fin ne peut pas précéder la date de début.")

    def validate_objective_deadline(self, field: DateField) -> None:
        if field.data and self.start_date.data and field.data < self.start_date.data:
            raise ValidationError(
                "La date limite des objectifs ne peut pas précéder la date de début de la campagne."
            )


# =============================================================================
# EvaluationContentForm — rédaction par l'évaluateur
# =============================================================================

class EvaluationContentForm(FlaskForm):
    """
    Formulaire de rédaction du contenu d'une évaluation par le manager,
    avant soumission à la relecture de l'employé.
    """

    overall_score = DecimalField(
        "Score global (0 à 5)",
        validators=[
            OptionalValidator(),
            NumberRange(min=0, max=5, message="Doit être compris entre 0 et 5."),
        ],
        places=2,
    )
    strengths = TextAreaField(
        "Points forts",
        validators=[OptionalValidator(), Length(max=2000)],
        render_kw={"rows": 3},
    )
    areas_for_improvement = TextAreaField(
        "Axes de progression",
        validators=[OptionalValidator(), Length(max=2000)],
        render_kw={"rows": 3},
    )
    development_plan = TextAreaField(
        "Plan de développement individuel (PDI)",
        validators=[OptionalValidator(), Length(max=2000)],
        render_kw={"rows": 3},
    )
    manager_overall_comment = TextAreaField(
        "Commentaire général du manager",
        validators=[OptionalValidator(), Length(max=5000)],
        render_kw={"rows": 4},
    )

    submit = SubmitField("Soumettre à l'employé")


# =============================================================================
# EvaluationAcknowledgeForm — accusé de réception employé
# =============================================================================

class EvaluationAcknowledgeForm(FlaskForm):
    """Formulaire d'accusé de réception et de signature par l'employé évalué."""

    employee_overall_comment = TextAreaField(
        "Votre commentaire",
        validators=[OptionalValidator(), Length(max=5000)],
        render_kw={"rows": 4, "placeholder": "Vos remarques sur cette évaluation..."},
    )
    confirm_signature = BooleanField(
        "Je confirme avoir pris connaissance de cette évaluation",
        validators=[],
    )
    submit = SubmitField("Valider et signer")

    def validate_confirm_signature(self, field: BooleanField) -> None:
        if not field.data:
            raise ValidationError("Vous devez confirmer la prise de connaissance pour valider.")