"""
Formulaires WTForms du module Training (Formations).

TrainingForm           — création / édition d'une formation (admin/rh).
EnrollForm             — inscription d'un ou plusieurs employés à une formation.
EnrollmentStatusForm   — transition de statut d'une inscription avec données
                         complémentaires propres à chaque étape.
"""
from __future__ import annotations

from datetime import date

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    DecimalField,
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
# TrainingForm — création / édition d'une formation
# =============================================================================

class TrainingForm(FlaskForm):
    """
    Formulaire de création ou d'édition d'une formation dans le catalogue.

    `training_type` contrôle le mode de diffusion :
        presentiel  — formation en salle avec formateur
        distanciel  — classe virtuelle / webinaire synchrone
        e_learning  — parcours asynchrone (MOOC, LMS...)

    `duration_hours` est exprimé en heures (décimales acceptées : 3.5 = 3h30).
    `cost` est le coût unitaire par participant en euros HT.
    """

    title = StringField(
        "Titre de la formation",
        validators=[
            DataRequired(message="Le titre est obligatoire."),
            Length(max=200, message="Le titre ne peut pas dépasser 200 caractères."),
        ],
        render_kw={"autofocus": True, "placeholder": "Ex : Management de projet agile"},
    )

    description = TextAreaField(
        "Description / Programme",
        validators=[OptionalValidator(), Length(max=5000)],
        render_kw={"rows": 4, "placeholder": "Objectifs pédagogiques, contenu, public cible..."},
    )

    organisme = StringField(
        "Organisme / Prestataire",
        validators=[
            OptionalValidator(),
            Length(max=200, message="Le nom de l'organisme ne peut pas dépasser 200 caractères."),
        ],
        render_kw={"placeholder": "Ex : OpenClassrooms, Cegos, interne..."},
    )

    duration_hours = DecimalField(
        "Durée (heures)",
        validators=[
            OptionalValidator(),
            NumberRange(min=0.25, message="La durée doit être positive (minimum 0,25 h)."),
        ],
        places=2,
    )

    training_type = SelectField(
        "Mode de diffusion",
        choices=[
            ("presentiel", "Présentiel"),
            ("distanciel", "Distanciel (classe virtuelle)"),
            ("e_learning", "E-learning (asynchrone)"),
        ],
        validators=[DataRequired()],
        default="presentiel",
    )

    cost = DecimalField(
        "Coût par participant (€ HT)",
        validators=[
            OptionalValidator(),
            NumberRange(min=0, message="Le coût ne peut pas être négatif."),
        ],
        places=2,
    )

    is_active = BooleanField(
        "Formation active (visible au catalogue)",
        default=True,
    )

    submit = SubmitField("Enregistrer la formation")


# =============================================================================
# EnrollForm — inscription d'un employé à une formation
# =============================================================================

class EnrollForm(FlaskForm):
    """
    Formulaire d'inscription d'un employé à une formation.

    `employee_id` est un SelectField peuplé dynamiquement via
    `populate_employees()` selon le rôle du demandeur :
        - admin/rh     → tous les employés actifs de l'entreprise
        - manager      → uniquement les membres directs de son équipe
        - employee     → uniquement lui-même (non affiché, pré-rempli)

    Les dates sont optionnelles à la création : elles peuvent être
    renseignées lors du passage au statut 'en_cours'.
    """

    employee_id = SelectField(
        "Employé inscrit",
        coerce=int,
        validators=[DataRequired(message="Veuillez sélectionner un employé.")],
    )

    start_date = DateField(
        "Date de début prévue",
        validators=[OptionalValidator()],
        format="%Y-%m-%d",
    )

    end_date = DateField(
        "Date de fin prévue",
        validators=[OptionalValidator()],
        format="%Y-%m-%d",
    )

    submit = SubmitField("Inscrire")

    # ── Peuplement dynamique ──────────────────────────────────────────────────

    def populate_employees_company(self, company_id: int) -> None:
        """Charge tous les employés actifs de l'entreprise (admin/rh)."""
        from app.extensions import db
        from app.models.employee import Employee

        employees = db.session.execute(
            db.select(Employee)
            .where(
                Employee.company_id == company_id,
                Employee.status.in_((Employee.STATUS_ACTIVE, Employee.STATUS_PROBATION)),
            )
            .order_by(Employee.last_name, Employee.first_name)
        ).scalars().all()
        self.employee_id.choices = [(e.id, e.full_name) for e in employees]

    def populate_employees_team(self, manager_employee_id: int) -> None:
        """Charge uniquement les membres directs de l'équipe (manager)."""
        from app.extensions import db
        from app.models.employee import Employee

        team = db.session.execute(
            db.select(Employee)
            .where(
                Employee.manager_id == manager_employee_id,
                Employee.status.in_((Employee.STATUS_ACTIVE, Employee.STATUS_PROBATION)),
            )
            .order_by(Employee.last_name)
        ).scalars().all()
        self.employee_id.choices = [(e.id, e.full_name) for e in team]

    def populate_self(self, employee_id: int, employee_name: str) -> None:
        """Pré-remplit le champ avec l'employé lui-même (auto-inscription)."""
        self.employee_id.choices = [(employee_id, employee_name)]
        self.employee_id.data = employee_id

    # ── Validation ────────────────────────────────────────────────────────────

    def validate_end_date(self, field: DateField) -> None:
        if self.start_date.data and field.data and field.data < self.start_date.data:
            raise ValidationError("La date de fin ne peut pas précéder la date de début.")

    def validate_start_date(self, field: DateField) -> None:
        if field.data and field.data < date.today():
            raise ValidationError("La date de début ne peut pas être dans le passé.")


# =============================================================================
# EnrollmentStatusForm — transition de statut d'une inscription
# =============================================================================

class EnrollmentStatusForm(FlaskForm):
    """
    Formulaire de changement de statut d'une inscription.

    Transitions gérées :
        planifiee  → en_cours  : start_date optionnel
        en_cours   → terminee  : end_date, score (0-100), final_comment optionnels
        planifiee
        ou en_cours → annulee  : aucun champ complémentaire requis

    L'affichage conditionnel des champs selon la transition est géré
    côté template (JavaScript ou rendu serveur selon statut courant).
    """

    status = SelectField(
        "Nouveau statut",
        choices=[
            ("planifiee",  "Planifiée"),
            ("en_cours",   "En cours"),
            ("terminee",   "Terminée"),
            ("annulee",    "Annulée"),
        ],
        validators=[DataRequired(message="Veuillez sélectionner un statut.")],
    )

    start_date = DateField(
        "Date de début effective",
        validators=[OptionalValidator()],
        format="%Y-%m-%d",
    )

    end_date = DateField(
        "Date de fin effective",
        validators=[OptionalValidator()],
        format="%Y-%m-%d",
    )

    score = DecimalField(
        "Note finale (0 à 100)",
        validators=[
            OptionalValidator(),
            NumberRange(min=0, max=100, message="La note doit être comprise entre 0 et 100."),
        ],
        places=2,
    )

    final_comment = TextAreaField(
        "Commentaire / Appréciation",
        validators=[OptionalValidator(), Length(max=5000)],
        render_kw={"rows": 3},
    )

    submit = SubmitField("Mettre à jour")

    # ── Validation ────────────────────────────────────────────────────────────

    def validate_end_date(self, field: DateField) -> None:
        if self.start_date.data and field.data and field.data < self.start_date.data:
            raise ValidationError("La date de fin ne peut pas précéder la date de début.")

    def validate_score(self, field: DecimalField) -> None:
        if field.data is not None and self.status.data != "terminee":
            raise ValidationError(
                "La note ne peut être saisie que pour une inscription terminée."
            )
