"""
Formulaires WTForms du module Employees.

EmployeeForm  — création et édition d'un employé (infos perso + pro).
ContractForm  — création d'un nouveau contrat de travail pour un employé.

Les SelectField (department_id, position_id, site_id, manager_id,
contract_type_id) sont peuplés dynamiquement dans les routes via les
méthodes populate_*() — même pattern que LeaveRequestForm.
"""
from __future__ import annotations

from datetime import date

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    DecimalField,
    EmailField,
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
# EmployeeForm — création / édition
# =============================================================================

class EmployeeForm(FlaskForm):
    """
    Formulaire de création ou modification d'un employé.

    Les champs sensibles (IBAN, numéro de sécu, salaire) sont volontairement
    absents de ce formulaire — ils sont gérés séparément (vue dédiée RH/Admin
    avec confirmation supplémentaire), pour limiter la surface d'exposition
    accidentelle de données sensibles dans un formulaire généraliste.
    """

    # ── Identité ──────────────────────────────────────────────────────────────
    first_name = StringField(
        "Prénom",
        validators=[DataRequired(message="Le prénom est obligatoire."), Length(max=100)],
        render_kw={"autofocus": True},
    )
    last_name = StringField(
        "Nom",
        validators=[DataRequired(message="Le nom est obligatoire."), Length(max=100)],
    )
    gender = SelectField(
        "Genre",
        choices=[
            ("", "Non précisé"),
            ("male", "Homme"),
            ("female", "Femme"),
            ("other", "Autre"),
            ("prefer_not_to_say", "Préfère ne pas préciser"),
        ],
        validators=[OptionalValidator()],
    )
    birth_date = DateField(
        "Date de naissance",
        validators=[OptionalValidator()],
        format="%Y-%m-%d",
    )

    # ── Contact ───────────────────────────────────────────────────────────────
    personal_email = EmailField(
        "Email personnel",
        validators=[OptionalValidator(), Length(max=255)],
    )
    personal_phone = StringField(
        "Téléphone personnel",
        validators=[OptionalValidator(), Length(max=30)],
    )
    professional_phone = StringField(
        "Téléphone professionnel",
        validators=[OptionalValidator(), Length(max=30)],
    )

    # ── Adresse ───────────────────────────────────────────────────────────────
    address_line1 = StringField("Adresse", validators=[OptionalValidator(), Length(max=200)])
    city = StringField("Ville", validators=[OptionalValidator(), Length(max=100)])
    postal_code = StringField("Code postal", validators=[OptionalValidator(), Length(max=20)])

    # ── Rattachement organisationnel ───────────────────────────────────────────
    department_id = SelectField("Département", coerce=int, validators=[OptionalValidator()])
    position_id = SelectField("Poste", coerce=int, validators=[OptionalValidator()])
    site_id = SelectField("Site", coerce=int, validators=[OptionalValidator()])
    manager_id = SelectField("Manager", coerce=int, validators=[OptionalValidator()])

    # ── Informations professionnelles ─────────────────────────────────────────
    employee_number = StringField(
        "Matricule",
        validators=[OptionalValidator(), Length(max=50)],
    )
    hire_date = DateField(
        "Date d'embauche",
        validators=[DataRequired(message="La date d'embauche est obligatoire.")],
        format="%Y-%m-%d",
    )
    probation_end_date = DateField(
        "Fin de période d'essai",
        validators=[OptionalValidator()],
        format="%Y-%m-%d",
    )
    status = SelectField(
        "Statut",
        choices=[
            ("active", "Actif"),
            ("probation", "Période d'essai"),
            ("on_leave", "En congé"),
            ("suspended", "Suspendu"),
            ("terminated", "Parti"),
        ],
        validators=[DataRequired()],
        default="active",
    )

    notes = TextAreaField(
        "Notes internes RH",
        validators=[OptionalValidator(), Length(max=2000)],
        render_kw={"rows": 3},
    )

    # ── Données sensibles (Admin / RH) ────────────────────────────────────────
    national_id_number = StringField(
        "Numéro de sécurité sociale",
        validators=[OptionalValidator(), Length(max=20)],
        render_kw={"placeholder": "1 85 06 75 105 001 12"},
    )
    annual_gross_salary = DecimalField(
        "Salaire brut annuel (€)",
        validators=[OptionalValidator(), NumberRange(min=0)],
        places=2,
    )
    iban = StringField(
        "IBAN",
        validators=[OptionalValidator(), Length(max=34)],
        render_kw={"placeholder": "FR76 3000 6000 0112 3456 7890 189"},
    )
    bic = StringField(
        "BIC / SWIFT",
        validators=[OptionalValidator(), Length(max=11)],
        render_kw={"placeholder": "BNPAFRPP"},
    )

    submit = SubmitField("Enregistrer")

    # ── Méthodes utilitaires de peuplement dynamique ──────────────────────────
    def populate_choices(self, company_id: int, exclude_employee_id: int | None = None) -> None:
        """
        Charge les options des SelectField pour une entreprise donnée.
        exclude_employee_id évite qu'un employé puisse être son propre manager
        dans la liste déroulante (édition).
        """
        from app.extensions import db
        from app.models.department import Department
        from app.models.position import Position
        from app.models.organization import Site
        from app.models.employee import Employee

        departments = db.session.execute(
            Department.active_in_company(company_id)
        ).scalars().all()
        self.department_id.choices = [(0, "— Aucun —")] + [
            (d.id, d.full_path) for d in departments
        ]

        sites = db.session.execute(Site.active_in_company(company_id)).scalars().all()
        self.site_id.choices = [(0, "— Aucun —")] + [(s.id, s.name) for s in sites]

        # Postes : tous ceux des départements de l'entreprise
        positions = []
        for d in departments:
            positions.extend(
                db.session.execute(Position.active_in_department(d.id)).scalars().all()
            )
        self.position_id.choices = [(0, "— Aucun —")] + [
            (p.id, f"{p.title} ({p.department.name})") for p in positions
        ]

        managers_query = db.select(Employee).where(
            Employee.company_id == company_id,
            Employee.status.in_((Employee.STATUS_ACTIVE, Employee.STATUS_PROBATION)),
        )
        if exclude_employee_id is not None:
            managers_query = managers_query.where(Employee.id != exclude_employee_id)
        managers = db.session.execute(managers_query).scalars().all()
        self.manager_id.choices = [(0, "— Aucun —")] + [
            (m.id, m.full_name) for m in managers
        ]

    # ── Validations transverses ────────────────────────────────────────────────
    def validate_probation_end_date(self, field: DateField) -> None:
        if field.data and self.hire_date.data and field.data < self.hire_date.data:
            raise ValidationError(
                "La fin de période d'essai ne peut pas précéder la date d'embauche."
            )


# =============================================================================
# ContractForm — nouveau contrat de travail
# =============================================================================

class ContractForm(FlaskForm):
    """Formulaire de création d'un nouveau contrat de travail pour un employé."""

    contract_type_id = SelectField(
        "Type de contrat",
        coerce=int,
        validators=[DataRequired(message="Veuillez sélectionner un type de contrat.")],
    )
    start_date = DateField(
        "Date de début",
        validators=[DataRequired(message="La date de début est obligatoire.")],
        format="%Y-%m-%d",
    )
    end_date = DateField(
        "Date de fin (laisser vide pour un CDI)",
        validators=[OptionalValidator()],
        format="%Y-%m-%d",
    )
    trial_end_date = DateField(
        "Fin de période d'essai",
        validators=[OptionalValidator()],
        format="%Y-%m-%d",
    )
    gross_salary = DecimalField(
        "Salaire brut mensuel (€)",
        validators=[
            DataRequired(message="Le salaire brut est obligatoire."),
            NumberRange(min=0.01, message="Le salaire doit être positif."),
        ],
        places=2,
    )
    weekly_hours = DecimalField(
        "Heures hebdomadaires",
        validators=[
            DataRequired(message="Les heures hebdomadaires sont obligatoires."),
            NumberRange(min=0.01, max=48, message="Doit être compris entre 0 et 48."),
        ],
        places=2,
        default=35,
    )
    is_current = BooleanField("Définir comme contrat actuel", default=True)
    notes = TextAreaField(
        "Notes",
        validators=[OptionalValidator(), Length(max=2000)],
        render_kw={"rows": 2},
    )

    submit = SubmitField("Créer le contrat")

    def populate_contract_types(self, company_id: int) -> None:
        from app.extensions import db
        from app.models.contract import ContractType

        types = db.session.execute(
            ContractType.active_in_company(company_id)
        ).scalars().all()
        self.contract_type_id.choices = [(t.id, t.name) for t in types]

    def validate_end_date(self, field: DateField) -> None:
        if field.data and self.start_date.data and field.data <= self.start_date.data:
            raise ValidationError("La date de fin doit être postérieure à la date de début.")

    def validate_trial_end_date(self, field: DateField) -> None:
        if field.data and self.start_date.data and field.data < self.start_date.data:
            raise ValidationError(
                "La fin de période d'essai ne peut pas précéder la date de début."
            )