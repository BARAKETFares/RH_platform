"""
Formulaires WTForms du module Recrutement.

JobPostingForm           — création / édition d'une offre d'emploi (admin/rh).
CandidateApplicationForm — ajout d'un candidat + soumission de sa candidature
                           en un seul formulaire (admin/rh).
ApplicationDecisionForm  — transition de statut d'une candidature (décision finale).
InterviewScheduleForm    — planification d'un entretien.
InterviewResultForm      — saisie du résultat après entretien.
"""
from __future__ import annotations

from datetime import date, datetime

from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    DateTimeLocalField,
    DecimalField,
    HiddenField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import (
    DataRequired,
    Email,
    Length,
    NumberRange,
    Optional as OptionalValidator,
    ValidationError,
)


# =============================================================================
# JobPostingForm — création / édition d'une offre
# =============================================================================

class JobPostingForm(FlaskForm):
    """
    Formulaire de création ou d'édition d'une offre d'emploi.

    `department_id` et `position_id` sont des SelectField peuplés
    dynamiquement via `populate_departments()` / `populate_positions()`.

    `salary_min` / `salary_max` sont optionnels et exprimés en € brut annuel.
    `headcount` est le nombre de postes à pourvoir (défaut : 1).
    """

    title = StringField(
        "Intitulé du poste",
        validators=[
            DataRequired(message="L'intitulé du poste est obligatoire."),
            Length(max=200, message="Maximum 200 caractères."),
        ],
        render_kw={"autofocus": True, "placeholder": "Ex : Développeur Python Senior"},
    )

    description = TextAreaField(
        "Description / Missions",
        validators=[OptionalValidator(), Length(max=10000)],
        render_kw={"rows": 5, "placeholder": "Missions, responsabilités, environnement..."},
    )

    requirements = TextAreaField(
        "Profil recherché / Compétences",
        validators=[OptionalValidator(), Length(max=5000)],
        render_kw={"rows": 4, "placeholder": "Diplômes, expériences, compétences techniques..."},
    )

    department_id = SelectField(
        "Département",
        coerce=int,
        validators=[OptionalValidator()],
    )

    position_id = SelectField(
        "Poste (référentiel RH)",
        coerce=int,
        validators=[OptionalValidator()],
    )

    location = StringField(
        "Lieu de travail",
        validators=[OptionalValidator(), Length(max=200)],
        render_kw={"placeholder": "Ex : Paris 9e — Hybride 3j/semaine"},
    )

    CONTRACT_TYPES = [
        ("", "— Non précisé —"),
        ("CDI", "CDI"),
        ("CDD", "CDD"),
        ("Stage", "Stage"),
        ("Alternance", "Alternance"),
        ("Freelance", "Freelance"),
        ("Intérim", "Intérim"),
    ]

    contract_type = SelectField(
        "Type de contrat",
        choices=CONTRACT_TYPES,
        validators=[OptionalValidator()],
        default="",
    )

    salary_min = DecimalField(
        "Salaire min (€ brut/an)",
        validators=[
            OptionalValidator(),
            NumberRange(min=0, message="Le salaire ne peut pas être négatif."),
        ],
        places=0,
    )

    salary_max = DecimalField(
        "Salaire max (€ brut/an)",
        validators=[
            OptionalValidator(),
            NumberRange(min=0, message="Le salaire ne peut pas être négatif."),
        ],
        places=0,
    )

    headcount = IntegerField(
        "Nombre de postes à pourvoir",
        validators=[
            OptionalValidator(),
            NumberRange(min=1, message="Le nombre de postes doit être au moins 1."),
        ],
        default=1,
    )

    closing_date = DateField(
        "Date limite de candidature",
        validators=[OptionalValidator()],
        format="%Y-%m-%d",
    )

    submit = SubmitField("Enregistrer l'offre")

    # ── Peuplement dynamique ──────────────────────────────────────────────────

    def populate_departments(self, company_id: int) -> None:
        """Charge les départements actifs de l'entreprise."""
        from app.extensions import db
        from app.models.department import Department

        depts = db.session.execute(
            db.select(Department)
            .where(Department.company_id == company_id, Department.is_active.is_(True))
            .order_by(Department.name)
        ).scalars().all()

        self.department_id.choices = [(0, "— Aucun —")] + [
            (d.id, d.name) for d in depts
        ]

    def populate_positions(self, company_id: int) -> None:
        """Charge les postes actifs de l'entreprise (via leur département)."""
        from app.extensions import db
        from app.models.department import Department
        from app.models.position import Position

        positions = db.session.execute(
            db.select(Position)
            .join(Department, Position.department_id == Department.id)
            .where(Department.company_id == company_id, Position.is_active.is_(True))
            .order_by(Position.title)
        ).scalars().all()

        self.position_id.choices = [(0, "— Aucun —")] + [
            (p.id, p.title) for p in positions
        ]

    # ── Validation ────────────────────────────────────────────────────────────

    def validate_salary_max(self, field: DecimalField) -> None:
        if (
            field.data is not None
            and self.salary_min.data is not None
            and field.data < self.salary_min.data
        ):
            raise ValidationError(
                "Le salaire maximum doit être supérieur ou égal au salaire minimum."
            )

    def validate_closing_date(self, field: DateField) -> None:
        if field.data and field.data < date.today():
            raise ValidationError("La date limite ne peut pas être dans le passé.")


# =============================================================================
# CandidateApplicationForm — candidat + candidature (formulaire combiné)
# =============================================================================

class CandidateApplicationForm(FlaskForm):
    """
    Formulaire combiné : crée (ou identifie) un candidat et soumet
    sa candidature à une offre d'emploi en une seule action.

    Si un candidat avec le même email existe déjà dans le vivier,
    la route utilisera ce candidat existant plutôt que d'en créer un nouveau.

    `source` indique par quel canal la candidature a été reçue.
    `cv_text` est le CV saisi en texte libre (alternative au fichier uploadé).
    """

    # ── Identité du candidat ──────────────────────────────────────────────────
    first_name = StringField(
        "Prénom",
        validators=[
            DataRequired(message="Le prénom est obligatoire."),
            Length(max=100),
        ],
        render_kw={"autofocus": True},
    )

    last_name = StringField(
        "Nom",
        validators=[
            DataRequired(message="Le nom est obligatoire."),
            Length(max=100),
        ],
    )

    email = StringField(
        "Adresse e-mail",
        validators=[
            DataRequired(message="L'e-mail est obligatoire."),
            Email(message="Adresse e-mail invalide."),
            Length(max=255),
        ],
        render_kw={"placeholder": "candidat@exemple.com"},
    )

    phone = StringField(
        "Téléphone",
        validators=[OptionalValidator(), Length(max=30)],
        render_kw={"placeholder": "+33 6 xx xx xx xx"},
    )

    SOURCES = [
        ("linkedin",    "LinkedIn"),
        ("jobboard",    "Job board (Indeed, APEC…)"),
        ("referral",    "Cooptation"),
        ("spontaneous", "Candidature spontanée"),
        ("website",     "Site carrières"),
        ("other",       "Autre"),
    ]

    source = SelectField(
        "Source de la candidature",
        choices=SOURCES,
        default="other",
        validators=[DataRequired()],
    )

    cv_text = TextAreaField(
        "CV (texte libre)",
        validators=[OptionalValidator(), Length(max=20000)],
        render_kw={
            "rows": 6,
            "placeholder": "Collez ici le CV ou une synthèse du parcours du candidat…",
        },
    )

    # ── Notes sur la candidature ──────────────────────────────────────────────
    notes = TextAreaField(
        "Notes internes RH",
        validators=[OptionalValidator(), Length(max=5000)],
        render_kw={"rows": 3, "placeholder": "Observations, contexte de la candidature…"},
    )

    submit = SubmitField("Enregistrer la candidature")


# =============================================================================
# ApplicationDecisionForm — décision finale sur une candidature
# =============================================================================

class ApplicationDecisionForm(FlaskForm):
    """
    Formulaire de transition de statut d'une candidature.

    Transitions disponibles (proposées selon le statut actuel) :
        recue           → preselectionnee
        preselectionnee → entretien
        entretien       → offre
        offre           → embauchee
        tout sauf embauchee → refusee

    `rejection_reason` est affiché uniquement quand le statut cible est 'refusee'.
    """

    status = SelectField(
        "Décision",
        choices=[
            ("preselectionnee", "Présélectionner"),
            ("entretien",       "Convoquer en entretien"),
            ("offre",           "Émettre une offre d'embauche"),
            ("embauchee",       "Confirmer l'embauche"),
            ("refusee",         "Refuser la candidature"),
        ],
        validators=[DataRequired(message="Veuillez sélectionner une décision.")],
    )

    rejection_reason = TextAreaField(
        "Motif de refus",
        validators=[OptionalValidator(), Length(max=2000)],
        render_kw={
            "rows": 3,
            "placeholder": "Motif communiqué au candidat (optionnel)…",
        },
    )

    notes = TextAreaField(
        "Notes internes",
        validators=[OptionalValidator(), Length(max=5000)],
        render_kw={"rows": 2},
    )

    submit = SubmitField("Appliquer la décision")

    def set_choices_from_status(self, current_status: str) -> None:
        """Filtre les choix selon le statut actuel pour ne proposer que les transitions légales."""
        transitions = {
            "recue":           [("preselectionnee", "Présélectionner"),
                                ("refusee", "Refuser")],
            "preselectionnee": [("entretien", "Convoquer en entretien"),
                                ("refusee", "Refuser")],
            "entretien":       [("offre", "Émettre une offre d'embauche"),
                                ("refusee", "Refuser")],
            "offre":           [("embauchee", "Confirmer l'embauche"),
                                ("refusee", "Refuser")],
        }
        self.status.choices = transitions.get(current_status, [])

    def validate_rejection_reason(self, field: TextAreaField) -> None:
        if self.status.data != "refusee" and field.data and field.data.strip():
            raise ValidationError(
                "Le motif de refus ne s'applique qu'au statut 'Refusé'."
            )


# =============================================================================
# InterviewScheduleForm — planification d'un entretien
# =============================================================================

class InterviewScheduleForm(FlaskForm):
    """
    Formulaire de planification d'un entretien pour une candidature.

    `interviewer_id` est un SelectField peuplé via `populate_interviewers()`.
    `scheduled_at` utilise `DateTimeLocalField` (HTML5 datetime-local input).
    """

    scheduled_at = DateTimeLocalField(
        "Date et heure de l'entretien",
        format="%Y-%m-%dT%H:%M",
        validators=[DataRequired(message="La date et l'heure sont obligatoires.")],
    )

    INTERVIEW_TYPES = [
        ("hr",        "Entretien RH"),
        ("technical", "Entretien technique"),
        ("phone",     "Pré-qualification téléphonique"),
        ("video",     "Visioconférence"),
        ("onsite",    "Présentiel"),
    ]

    interview_type = SelectField(
        "Type d'entretien",
        choices=INTERVIEW_TYPES,
        default="hr",
        validators=[DataRequired()],
    )

    interviewer_id = SelectField(
        "Interviewer",
        coerce=int,
        validators=[OptionalValidator()],
    )

    duration_minutes = IntegerField(
        "Durée (minutes)",
        default=60,
        validators=[
            OptionalValidator(),
            NumberRange(min=5, max=480, message="La durée doit être entre 5 et 480 minutes."),
        ],
    )

    location = StringField(
        "Lieu / Lien de visioconférence",
        validators=[OptionalValidator(), Length(max=300)],
        render_kw={"placeholder": "Salle Einstein — 2e étage ou https://meet.example.com/..."},
    )

    submit = SubmitField("Planifier l'entretien")

    # ── Peuplement dynamique ──────────────────────────────────────────────────

    def populate_interviewers(self, company_id: int) -> None:
        """Charge les employés actifs de l'entreprise comme interviewers potentiels."""
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

        self.interviewer_id.choices = [(0, "— Non assigné —")] + [
            (e.id, e.full_name) for e in employees
        ]

    # ── Validation ────────────────────────────────────────────────────────────

    def validate_scheduled_at(self, field: DateTimeLocalField) -> None:
        if field.data and field.data < datetime.now():
            raise ValidationError("La date de l'entretien ne peut pas être dans le passé.")


# =============================================================================
# InterviewResultForm — résultat d'un entretien
# =============================================================================

class InterviewResultForm(FlaskForm):
    """
    Formulaire de saisie du résultat d'un entretien réalisé.

    `decision` est la recommandation de l'interviewer à l'issue de l'entretien.
    `rating` est une note globale sur 5 (optionnelle).
    `notes` contient les observations détaillées.
    """

    DECISIONS = [
        ("proceed", "Recommande de poursuivre le processus"),
        ("hold",    "À confirmer / deuxième avis nécessaire"),
        ("reject",  "Recommande de refuser le candidat"),
    ]

    decision = SelectField(
        "Décision",
        choices=DECISIONS,
        validators=[DataRequired(message="Veuillez sélectionner une décision.")],
    )

    RATINGS = [
        (0, "— Sans avis —"),
        (5, "5 — Excellent"),
        (4, "4 — Bon"),
        (3, "3 — Moyen"),
        (2, "2 — Insuffisant"),
        (1, "1 — Rédhibitoire"),
    ]

    rating = SelectField(
        "Note globale",
        choices=RATINGS,
        coerce=int,
        default=0,
        validators=[OptionalValidator()],
    )

    notes = TextAreaField(
        "Observations / Compte-rendu",
        validators=[OptionalValidator(), Length(max=10000)],
        render_kw={
            "rows": 6,
            "placeholder": "Points forts, points faibles, adéquation au poste…",
        },
    )

    submit = SubmitField("Enregistrer le résultat")
