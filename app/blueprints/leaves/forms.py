"""
Formulaires WTForms du module Leaves (Congés & Absences).

Chaque formulaire hérite de FlaskForm pour la protection CSRF automatique.

LeaveRequestForm  — soumission d'une nouvelle demande par l'employé.
LeaveDecisionForm — approbation ou refus par un manager/RH.

Les choix de leave_type_id sont peuplés dynamiquement dans la route
(QuerySelectField nécessiterait Flask-WTF + SQLAlchemy ; on reste ici
sur un SelectField classique pour rester découplé du contexte de requête
au niveau du formulaire — les choices sont injectés via populate_leave_types()).
"""
from __future__ import annotations

from datetime import date

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    HiddenField,
    RadioField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import (
    DataRequired,
    Length,
    Optional as OptionalValidator,
    ValidationError,
)


# =============================================================================
# LeaveRequestForm — soumission d'une demande d'absence
# =============================================================================

class LeaveRequestForm(FlaskForm):
    """
    Formulaire de soumission d'une nouvelle demande d'absence.

    Le champ `leave_type_id` est un SelectField dont les choices doivent
    être peuplés avant rendu via la méthode de classe `populate_leave_types()`
    (cf. usage dans routes.py) :

        form = LeaveRequestForm()
        form.populate_leave_types(current_employee.company_id)

    Les champs `start_half_day`/`end_half_day` permettent de demander
    une demi-journée en début ou fin de période, conformément au modèle
    LeaveRequest.
    """

    leave_type_id = SelectField(
        "Type d'absence",
        coerce=int,
        validators=[DataRequired(message="Veuillez sélectionner un type d'absence.")],
        render_kw={"autofocus": True},
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

    start_half_day = BooleanField(
        "Demi-journée en début de période",
        default=False,
    )

    end_half_day = BooleanField(
        "Demi-journée en fin de période",
        default=False,
    )

    employee_comment = TextAreaField(
        "Commentaire / Motif",
        validators=[
            OptionalValidator(),
            Length(max=2000, message="Le commentaire ne peut pas dépasser 2000 caractères."),
        ],
        render_kw={
            "rows": 3,
            "placeholder": "Précisez le motif de votre demande si nécessaire...",
        },
    )

    document_path = HiddenField(
        "Justificatif",
        validators=[OptionalValidator()],
    )

    is_emergency = BooleanField(
        "Demande urgente (déroge au délai de prévenance)",
        default=False,
    )

    submit = SubmitField("Soumettre la demande")

    # ── Méthode utilitaire de peuplement dynamique ────────────────────────────
    def populate_leave_types(self, company_id: int) -> None:
        """
        Charge les types d'absence actifs de l'entreprise dans le SelectField.
        À appeler systématiquement avant le rendu du formulaire (GET et POST),
        car WTForms revalide les choices à chaque soumission.
        """
        from app.models.leave_type import LeaveType
        from app.extensions import db

        leave_types = db.session.execute(
            LeaveType.active_in_company(company_id)
        ).scalars().all()

        self.leave_type_id.choices = [
            (lt.id, lt.display_label) for lt in leave_types
        ]

    # ── Validations transverses ────────────────────────────────────────────────
    def validate_end_date(self, field: DateField) -> None:
        """Vérifie que la date de fin n'est pas antérieure à la date de début."""
        if self.start_date.data and field.data and field.data < self.start_date.data:
            raise ValidationError("La date de fin ne peut pas précéder la date de début.")

    def validate_start_date(self, field: DateField) -> None:
        """
        Vérifie que la date de début n'est pas dans le passé,
        sauf si la demande est marquée comme urgente.
        """
        if field.data and field.data < date.today() and not self.is_emergency.data:
            raise ValidationError(
                "La date de début ne peut pas être antérieure à aujourd'hui "
                "(cochez 'Demande urgente' si nécessaire)."
            )


# =============================================================================
# LeaveDecisionForm — approbation ou refus (manager / RH)
# =============================================================================

class LeaveDecisionForm(FlaskForm):
    """
    Formulaire de décision sur une demande d'absence (manager ou RH).

    Le champ `decision` pilote la validation conditionnelle du commentaire :
    un motif devient obligatoire en cas de refus (cohérent avec la règle
    métier déjà appliquée côté service : reject_leave() exige un commentaire).
    """

    decision = RadioField(
        "Décision",
        choices=[
            ("approve", "Approuver"),
            ("reject", "Refuser"),
        ],
        validators=[DataRequired(message="Veuillez choisir une décision.")],
        default="approve",
    )

    comment = TextAreaField(
        "Commentaire",
        validators=[
            OptionalValidator(),
            Length(max=2000, message="Le commentaire ne peut pas dépasser 2000 caractères."),
        ],
        render_kw={
            "rows": 3,
            "placeholder": "Obligatoire en cas de refus, optionnel en cas d'approbation...",
        },
    )

    # Pertinent uniquement pour une approbation au niveau manager :
    # détermine si la demande doit ensuite transiter par la RH.
    requires_hr_validation = BooleanField(
        "Nécessite une validation RH supplémentaire",
        default=True,
    )

    submit = SubmitField("Confirmer la décision")

    # ── Validation conditionnelle ──────────────────────────────────────────────
    def validate_comment(self, field: TextAreaField) -> None:
        """Le commentaire devient obligatoire si la décision est un refus."""
        if self.decision.data == "reject" and not (field.data or "").strip():
            raise ValidationError("Un motif est obligatoire en cas de refus.")


# =============================================================================
# LeaveCancelForm — annulation d'une demande (employé ou RH/Admin)
# =============================================================================

class LeaveCancelForm(FlaskForm):
    """
    Formulaire d'annulation d'une demande d'absence.
    Le motif est optionnel — conforme à LeaveRequestCancelSchema côté API.
    """

    reason = TextAreaField(
        "Motif de l'annulation",
        validators=[
            OptionalValidator(),
            Length(max=500, message="Le motif ne peut pas dépasser 500 caractères."),
        ],
        render_kw={"rows": 2, "placeholder": "Optionnel..."},
    )

    submit = SubmitField("Confirmer l'annulation")