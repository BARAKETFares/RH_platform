"""
Formulaires WTForms du module Admin.

UserCreateForm  — création d'un compte utilisateur par un admin.
UserEditForm    — modification d'un compte (rôle, statut, reset mdp).
RoleEditForm    — modification du libellé et des permissions d'un rôle.
AuditLogFilterForm — filtres GET pour le journal d'audit (pas de CSRF).
"""
from __future__ import annotations

import re

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    DecimalField,
    EmailField,
    IntegerField,
    PasswordField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    Length,
    NumberRange,
    Optional as OptionalValidator,
    ValidationError,
)


def _password_strength(form, field) -> None:
    value = field.data
    if not value:
        return
    if not re.search(r"[A-Z]", value):
        raise ValidationError("Le mot de passe doit contenir au moins une majuscule.")
    if not re.search(r"[0-9]", value):
        raise ValidationError("Le mot de passe doit contenir au moins un chiffre.")


# =============================================================================
# UserCreateForm
# =============================================================================

class UserCreateForm(FlaskForm):
    """Création d'un compte utilisateur par un administrateur."""

    email = EmailField(
        "Adresse e-mail",
        validators=[
            DataRequired(message="L'e-mail est obligatoire."),
            Email(message="Format d'e-mail invalide."),
            Length(max=255),
        ],
        render_kw={"autofocus": True, "placeholder": "prenom.nom@entreprise.fr"},
    )
    password = PasswordField(
        "Mot de passe",
        validators=[
            DataRequired(message="Le mot de passe est obligatoire."),
            Length(min=8, max=128, message="Entre 8 et 128 caractères."),
            _password_strength,
        ],
    )
    password_confirm = PasswordField(
        "Confirmer le mot de passe",
        validators=[
            DataRequired(),
            EqualTo("password", message="Les mots de passe ne correspondent pas."),
        ],
    )
    role_id = SelectField(
        "Rôle",
        coerce=int,
        validators=[DataRequired(message="Un rôle est obligatoire.")],
    )
    is_active = BooleanField("Compte actif", default=True)
    force_password_change = BooleanField(
        "Forcer le changement de mot de passe à la 1ʳᵉ connexion", default=True
    )
    preferred_language = SelectField(
        "Langue",
        choices=[("fr", "Français"), ("en", "English")],
        default="fr",
    )

    employee_id = SelectField(
        "Lier à une fiche employé (optionnel)",
        coerce=int,
        validators=[OptionalValidator()],
    )

    submit = SubmitField("Créer le compte")

    def populate_roles(self) -> None:
        from app.models.role import Role
        roles = Role.all_ordered()
        self.role_id.choices = [(r.id, r.label) for r in roles]

    def populate_employees(self) -> None:
        """Propose uniquement les employés sans compte utilisateur."""
        from app.extensions import db
        from app.models.employee import Employee
        employees = db.session.execute(
            db.select(Employee)
            .where(Employee.user_id.is_(None))
            .order_by(Employee.last_name, Employee.first_name)
        ).scalars().all()
        self.employee_id.choices = [(0, "— Aucun —")] + [
            (e.id, f"{e.full_name} ({e.employee_number or '—'})") for e in employees
        ]


# =============================================================================
# UserEditForm
# =============================================================================

class UserEditForm(FlaskForm):
    """
    Modification d'un compte utilisateur par un administrateur.
    Le champ `new_password` est optionnel : s'il est vide, le mot de passe
    actuel est conservé.
    """

    email = EmailField(
        "Adresse e-mail",
        validators=[
            DataRequired(message="L'e-mail est obligatoire."),
            Email(message="Format d'e-mail invalide."),
            Length(max=255),
        ],
    )
    role_id = SelectField(
        "Rôle",
        coerce=int,
        validators=[DataRequired(message="Un rôle est obligatoire.")],
    )
    employee_id = SelectField(
        "Fiche employé liée",
        coerce=int,
        validators=[OptionalValidator()],
    )
    is_active = BooleanField("Compte actif")
    is_email_verified = BooleanField("E-mail vérifié")
    force_password_change = BooleanField("Forcer le changement de mot de passe")

    new_password = PasswordField(
        "Nouveau mot de passe (laisser vide pour ne pas changer)",
        validators=[
            OptionalValidator(),
            Length(min=8, max=128, message="Entre 8 et 128 caractères."),
            _password_strength,
        ],
    )

    submit = SubmitField("Enregistrer")

    def populate_roles(self) -> None:
        from app.models.role import Role
        roles = Role.all_ordered()
        self.role_id.choices = [(r.id, r.label) for r in roles]

    def populate_employees(self, current_employee_id: int | None = None) -> None:
        """Propose les employés sans compte + l'employé actuellement lié."""
        from app.extensions import db
        from app.models.employee import Employee
        from sqlalchemy import or_
        query = db.select(Employee).where(
            or_(Employee.user_id.is_(None), Employee.id == current_employee_id)
        ).order_by(Employee.last_name, Employee.first_name)
        employees = db.session.execute(query).scalars().all()
        self.employee_id.choices = [(0, "— Aucun —")] + [
            (e.id, f"{e.full_name} ({e.employee_number or '—'})") for e in employees
        ]


# =============================================================================
# RoleEditForm
# =============================================================================

class RoleEditForm(FlaskForm):
    """
    Modification d'un rôle par un administrateur.
    Le `name` (code interne) est immuable — seul le libellé, la description
    et les permissions associées peuvent être modifiés.
    """

    label = StringField(
        "Libellé affiché",
        validators=[
            DataRequired(message="Le libellé est obligatoire."),
            Length(min=1, max=100),
        ],
    )
    description = TextAreaField(
        "Description",
        validators=[OptionalValidator(), Length(max=500)],
        render_kw={"rows": 3},
    )
    permission_ids = SelectMultipleField(
        "Permissions",
        coerce=int,
        validators=[OptionalValidator()],
    )

    submit = SubmitField("Enregistrer")

    def populate_permissions(self, current_permission_ids: list[int] | None = None) -> None:
        """Charge les permissions disponibles et pré-sélectionne les actuelles."""
        from app.extensions import db
        from app.models.role import Permission

        perms = db.session.execute(
            db.select(Permission).order_by(Permission.module, Permission.action)
        ).scalars().all()

        self.permission_ids.choices = [
            (p.id, f"{p.code}  —  {p.description or p.action}")
            for p in perms
        ]
        if current_permission_ids is not None:
            self.permission_ids.data = current_permission_ids


# =============================================================================
# AuditLogFilterForm (GET, pas de CSRF)
# =============================================================================

class AuditLogFilterForm(FlaskForm):
    """
    Formulaire de filtrage du journal d'audit.
    CSRF désactivé : formulaire soumis en GET (paramètres dans l'URL).
    """

    class Meta:
        csrf = False

    action = SelectField("Action", validators=[OptionalValidator()])
    entity_type = StringField(
        "Ressource",
        validators=[OptionalValidator(), Length(max=80)],
        render_kw={"placeholder": "employees, users…"},
    )
    user_email = StringField(
        "E-mail utilisateur",
        validators=[OptionalValidator(), Length(max=255)],
        render_kw={"placeholder": "prenom.nom@…"},
    )
    date_from = DateField("Du", validators=[OptionalValidator()], format="%Y-%m-%d")
    date_to = DateField("Au", validators=[OptionalValidator()], format="%Y-%m-%d")

    submit = SubmitField("Filtrer")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from app.models.audit import AuditLog
        self.action.choices = [("", "Toutes les actions")] + [
            (a, a) for a in AuditLog.ACTIONS
        ]


# =============================================================================
# DepartmentForm
# =============================================================================

class DepartmentForm(FlaskForm):
    """Création / modification d'un département."""

    name = StringField(
        "Nom",
        validators=[DataRequired(message="Le nom est obligatoire."), Length(max=100)],
        render_kw={"autofocus": True},
    )
    code = StringField(
        "Code court (ex: RH, TECH)",
        validators=[OptionalValidator(), Length(max=20)],
        render_kw={"placeholder": "TECH"},
    )
    description = TextAreaField(
        "Description",
        validators=[OptionalValidator(), Length(max=500)],
        render_kw={"rows": 2},
    )
    parent_id = SelectField(
        "Département parent",
        coerce=int,
        validators=[OptionalValidator()],
    )
    is_active = BooleanField("Actif", default=True)
    submit = SubmitField("Enregistrer")

    def populate_parents(self, company_id: int, exclude_id: int | None = None) -> None:
        from app.extensions import db
        from app.models.department import Department
        depts = db.session.execute(
            Department.active_in_company(company_id)
        ).scalars().all()
        choices = [(0, "— Aucun (département racine) —")]
        for d in depts:
            if exclude_id is None or d.id != exclude_id:
                choices.append((d.id, d.full_path))
        self.parent_id.choices = choices


# =============================================================================
# PositionForm
# =============================================================================

class PositionForm(FlaskForm):
    """Création / modification d'un poste."""

    title = StringField(
        "Intitulé du poste",
        validators=[DataRequired(message="L'intitulé est obligatoire."), Length(max=150)],
        render_kw={"autofocus": True, "placeholder": "Développeur Backend Senior"},
    )
    department_id = SelectField(
        "Département",
        coerce=int,
        validators=[DataRequired(message="Le département est obligatoire.")],
    )
    level = SelectField(
        "Niveau hiérarchique",
        choices=[
            ("", "— Non défini —"),
            ("junior", "Junior"),
            ("intermediate", "Intermédiaire"),
            ("senior", "Senior"),
            ("lead", "Lead"),
            ("manager", "Manager"),
            ("director", "Directeur"),
            ("executive", "Exécutif"),
        ],
        validators=[OptionalValidator()],
    )
    description = TextAreaField(
        "Description",
        validators=[OptionalValidator(), Length(max=500)],
        render_kw={"rows": 2},
    )
    min_salary = DecimalField(
        "Salaire minimum (€)",
        validators=[OptionalValidator(), NumberRange(min=0)],
        places=2,
    )
    max_salary = DecimalField(
        "Salaire maximum (€)",
        validators=[OptionalValidator(), NumberRange(min=0)],
        places=2,
    )
    is_active = BooleanField("Actif", default=True)
    submit = SubmitField("Enregistrer")

    def populate_departments(self, company_id: int) -> None:
        from app.extensions import db
        from app.models.department import Department
        depts = db.session.execute(
            Department.active_in_company(company_id)
        ).scalars().all()
        self.department_id.choices = [(d.id, d.full_path) for d in depts]


# =============================================================================
# SiteForm
# =============================================================================

class SiteForm(FlaskForm):
    """Création / modification d'un site géographique."""

    name = StringField(
        "Nom du site",
        validators=[DataRequired(message="Le nom est obligatoire."), Length(max=100)],
        render_kw={"autofocus": True, "placeholder": "Siège social Paris"},
    )
    address = TextAreaField(
        "Adresse",
        validators=[OptionalValidator()],
        render_kw={"rows": 2},
    )
    city = StringField(
        "Ville",
        validators=[OptionalValidator(), Length(max=100)],
    )
    postal_code = StringField(
        "Code postal",
        validators=[OptionalValidator(), Length(max=20)],
    )
    country = StringField(
        "Pays (code ISO 2)",
        validators=[OptionalValidator(), Length(max=2)],
        default="FR",
        render_kw={"placeholder": "FR"},
    )
    is_active = BooleanField("Actif", default=True)
    submit = SubmitField("Enregistrer")


# =============================================================================
# ContractTypeForm
# =============================================================================

class ContractTypeForm(FlaskForm):
    """Création / modification d'un type de contrat."""

    name = StringField(
        "Nom",
        validators=[DataRequired(message="Le nom est obligatoire."), Length(max=100)],
        render_kw={"autofocus": True, "placeholder": "CDI Cadre"},
    )
    duration_type = SelectField(
        "Catégorie légale",
        choices=[
            ("cdi",           "CDI"),
            ("cdd",           "CDD"),
            ("interim",       "Intérim"),
            ("apprenticeship","Alternance"),
            ("internship",    "Stage"),
            ("freelance",     "Freelance"),
        ],
        validators=[DataRequired()],
    )
    paid_leave_days = DecimalField(
        "Jours de congés payés / an",
        validators=[DataRequired(), NumberRange(min=0)],
        places=2,
        default=25,
    )
    rtt_days = DecimalField(
        "Jours de RTT / an",
        validators=[DataRequired(), NumberRange(min=0)],
        places=2,
        default=0,
    )
    notice_period_days = IntegerField(
        "Préavis (jours)",
        validators=[OptionalValidator(), NumberRange(min=0)],
        default=0,
        render_kw={"type": "number", "min": "0"},
    )
    is_active = BooleanField("Actif", default=True)
    submit = SubmitField("Enregistrer")


# =============================================================================
# LeaveTypeForm
# =============================================================================

class LeaveTypeForm(FlaskForm):
    """Création / modification d'un type d'absence."""

    name = StringField(
        "Nom",
        validators=[DataRequired(message="Le nom est obligatoire."), Length(max=100)],
        render_kw={"autofocus": True, "placeholder": "Congés Payés"},
    )
    code = StringField(
        "Code court",
        validators=[DataRequired(message="Le code est obligatoire."), Length(max=20)],
        render_kw={"placeholder": "CP"},
    )
    color_hex = StringField(
        "Couleur (#RRGGBB)",
        validators=[DataRequired(), Length(min=7, max=7)],
        default="#6c757d",
        render_kw={"type": "color"},
    )
    description = TextAreaField(
        "Description",
        validators=[OptionalValidator(), Length(max=500)],
        render_kw={"rows": 2},
    )
    min_advance_notice_days = IntegerField(
        "Délai de prévenance (jours)",
        validators=[DataRequired(), NumberRange(min=0)],
        default=0,
    )
    max_consecutive_days = IntegerField(
        "Limite de jours consécutifs (0 = illimité)",
        validators=[OptionalValidator(), NumberRange(min=0)],
        default=0,
    )
    requires_justification = BooleanField("Nécessite un motif à la demande")
    requires_document = BooleanField("Nécessite un justificatif (PJ)")
    is_paid = BooleanField("Congé rémunéré", default=True)
    impacts_leave_balance = BooleanField("Décompte un solde (CP, RTT…)", default=True)
    is_active = BooleanField("Actif", default=True)
    submit = SubmitField("Enregistrer")
