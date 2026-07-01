"""
Formulaires WTForms du module Auth.

Chaque formulaire hérite de FlaskForm :
  - Protection CSRF automatique via le token caché {{ form.hidden_tag() }}
  - Validation déclarative (validators) + méthodes validate_<field>()

Utilisation dans un template :
    <form method="POST" novalidate>
      {{ form.hidden_tag() }}
      {{ form.email(class="form-control") }}
      {{ form.submit(class="btn btn-primary") }}
    </form>
"""
from __future__ import annotations

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired, FileSize
from wtforms import BooleanField, EmailField, PasswordField, SubmitField
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    Length,
    Regexp,
    ValidationError,
)


# =============================================================================
# LoginForm
# =============================================================================

class LoginForm(FlaskForm):
    """
    Formulaire de connexion email + mot de passe.

    Champs :
      email       — adresse email (format validé)
      password    — mot de passe (non validé côté form, délégué au service)
      remember_me — case à cocher pour la session persistante
    """

    email = EmailField(
        label="Adresse email",
        validators=[
            DataRequired(message="L'adresse email est obligatoire."),
            Email(message="Format d'adresse email invalide."),
            Length(max=255, message="L'adresse email ne peut pas dépasser 255 caractères."),
        ],
        render_kw={
            "placeholder":  "vous@entreprise.fr",
            "autofocus":    True,
            "autocomplete": "email",
            "inputmode":    "email",
        },
    )

    password = PasswordField(
        label="Mot de passe",
        validators=[
            DataRequired(message="Le mot de passe est obligatoire."),
            Length(
                min=1,
                max=256,
                message="Le mot de passe ne peut pas dépasser 256 caractères.",
            ),
        ],
        render_kw={
            "placeholder":  "••••••••••",
            "autocomplete": "current-password",
        },
    )

    remember_me = BooleanField(
        label="Rester connecté",
        default=False,
    )

    submit = SubmitField(label="Se connecter")

    def validate_email(self, field: EmailField) -> None:
        """Normalise l'email en minuscules avant validation."""
        if field.data:
            field.data = field.data.lower().strip()


# =============================================================================
# ForgotPasswordForm
# =============================================================================

class PasswordResetRequestForm(FlaskForm):
    """
    Formulaire de demande de réinitialisation de mot de passe.

    Demande uniquement l'adresse email.
    La réponse du service est toujours générique (timing-safe) :
    le formulaire ne révèle jamais si l'email est connu ou non.
    """

    email = EmailField(
        label="Adresse email",
        validators=[
            DataRequired(message="L'adresse email est obligatoire."),
            Email(message="Format d'adresse email invalide."),
            Length(max=255, message="L'adresse email ne peut pas dépasser 255 caractères."),
        ],
        render_kw={
            "placeholder":  "vous@entreprise.fr",
            "autofocus":    True,
            "autocomplete": "email",
            "inputmode":    "email",
        },
    )

    submit = SubmitField(label="Recevoir le lien de réinitialisation")

    def validate_email(self, field: EmailField) -> None:
        """Normalise l'email en minuscules avant validation."""
        if field.data:
            field.data = field.data.lower().strip()


# =============================================================================
# ResetPasswordForm
# =============================================================================

class PasswordResetConfirmForm(FlaskForm):
    """
    Formulaire de saisie du nouveau mot de passe.

    Utilisé sur la page /auth/reset-password/<token>.
    Applique les règles de robustesse directement dans le formulaire
    pour un retour utilisateur immédiat (avant l'appel au service).

    Règles de robustesse (alignées avec _validate_password_strength()) :
      - 10 caractères minimum
      - Au moins une majuscule
      - Au moins une minuscule
      - Au moins un chiffre
      - Au moins un caractère spécial

    La confirmation est vérifiée par EqualTo : les deux champs
    doivent être strictement identiques.
    """

    password = PasswordField(
        label="Nouveau mot de passe",
        validators=[
            DataRequired(message="Le mot de passe est obligatoire."),
            Length(
                min=10,
                max=256,
                message="Le mot de passe doit contenir au moins 10 caractères.",
            ),
            Regexp(
                r"(?=.*[A-Z])",
                message="Le mot de passe doit contenir au moins une lettre majuscule.",
            ),
            Regexp(
                r"(?=.*[a-z])",
                message="Le mot de passe doit contenir au moins une lettre minuscule.",
            ),
            Regexp(
                r"(?=.*\d)",
                message="Le mot de passe doit contenir au moins un chiffre.",
            ),
            Regexp(
                r"(?=.*[!@#$%^&*()\-_=+\[\]{};:'\",.<>/?\\|`~])",
                message="Le mot de passe doit contenir au moins un caractère spécial.",
            ),
        ],
        render_kw={
            "placeholder":  "Au moins 10 caractères",
            "autofocus":    True,
            "autocomplete": "new-password",
        },
    )

    password_confirm = PasswordField(
        label="Confirmer le mot de passe",
        validators=[
            DataRequired(message="La confirmation du mot de passe est obligatoire."),
            EqualTo(
                "password",
                message="Les mots de passe ne correspondent pas.",
            ),
        ],
        render_kw={
            "placeholder":  "Répéter le mot de passe",
            "autocomplete": "new-password",
        },
    )

    submit = SubmitField(label="Enregistrer le nouveau mot de passe")

    def validate_password_confirm(self, field: PasswordField) -> None:
        """
        Vérification supplémentaire : lève une erreur explicite si le champ
        password lui-même contient des erreurs (évite un message trompeur
        sur password_confirm quand c'est password qui est invalide).
        """
        if self.password.errors:
            raise ValidationError(
                "Corrigez d'abord les erreurs sur le champ 'Nouveau mot de passe'."
            )


# =============================================================================
# Formulaires secondaires (2FA, changement de mot de passe)
# =============================================================================

class TwoFactorForm(FlaskForm):
    """
    Formulaire de vérification du code TOTP (étape 2FA).

    Accepte uniquement 6 chiffres consécutifs.
    """

    code = PasswordField(
        label="Code d'authentification",
        validators=[
            DataRequired(message="Le code est obligatoire."),
            Length(min=6, max=6, message="Le code doit contenir exactement 6 chiffres."),
            Regexp(
                r"^\d{6}$",
                message="Le code doit contenir uniquement des chiffres.",
            ),
        ],
        render_kw={
            "placeholder":    "000000",
            "autofocus":      True,
            "inputmode":      "numeric",
            "autocomplete":   "one-time-code",
            "maxlength":      "6",
            "pattern":        r"\d{6}",
        },
    )

    submit = SubmitField(label="Vérifier")


class TwoFactorSetupConfirmForm(FlaskForm):
    """
    Formulaire de confirmation lors de l'activation du 2FA.
    Identique à TwoFactorForm, libellé différent.
    """

    code = PasswordField(
        label="Code de vérification",
        validators=[
            DataRequired(message="Le code est obligatoire."),
            Length(min=6, max=6, message="6 chiffres requis."),
            Regexp(r"^\d{6}$", message="Chiffres uniquement."),
        ],
        render_kw={
            "placeholder":  "000000",
            "autofocus":    True,
            "inputmode":    "numeric",
            "autocomplete": "one-time-code",
            "maxlength":    "6",
        },
    )

    submit = SubmitField(label="Activer le 2FA")


class ChangePasswordForm(FlaskForm):
    """
    Formulaire de changement de mot de passe pour un utilisateur connecté.

    Requiert le mot de passe actuel pour confirmer l'identité,
    puis applique les mêmes règles de robustesse que ResetPasswordForm.
    """

    current_password = PasswordField(
        label="Mot de passe actuel",
        validators=[
            DataRequired(message="Le mot de passe actuel est obligatoire."),
        ],
        render_kw={
            "placeholder":  "Votre mot de passe actuel",
            "autocomplete": "current-password",
        },
    )

    new_password = PasswordField(
        label="Nouveau mot de passe",
        validators=[
            DataRequired(message="Le nouveau mot de passe est obligatoire."),
            Length(min=10, max=256, message="Au moins 10 caractères requis."),
            Regexp(r"(?=.*[A-Z])", message="Au moins une majuscule requise."),
            Regexp(r"(?=.*[a-z])", message="Au moins une minuscule requise."),
            Regexp(r"(?=.*\d)",    message="Au moins un chiffre requis."),
            Regexp(
                r"(?=.*[!@#$%^&*()\-_=+\[\]{};:'\",.<>/?\\|`~])",
                message="Au moins un caractère spécial requis.",
            ),
        ],
        render_kw={
            "placeholder":  "Au moins 10 caractères",
            "autocomplete": "new-password",
        },
    )

    new_password_confirm = PasswordField(
        label="Confirmer le nouveau mot de passe",
        validators=[
            DataRequired(message="La confirmation est obligatoire."),
            EqualTo("new_password", message="Les mots de passe ne correspondent pas."),
        ],
        render_kw={
            "placeholder":  "Répéter le nouveau mot de passe",
            "autocomplete": "new-password",
        },
    )

    submit = SubmitField(label="Changer le mot de passe")

    def validate_new_password(self, field: PasswordField) -> None:
        """Refuse un nouveau mot de passe identique à l'actuel."""
        if (
            field.data
            and self.current_password.data
            and field.data == self.current_password.data
        ):
            raise ValidationError(
                "Le nouveau mot de passe doit être différent de l'actuel."
            )


class DisableTwoFactorForm(FlaskForm):
    """
    Formulaire de désactivation du 2FA.
    Demande le mot de passe pour confirmer l'intention.
    """

    password = PasswordField(
        label="Confirmer avec votre mot de passe",
        validators=[
            DataRequired(message="Le mot de passe est obligatoire."),
        ],
        render_kw={
            "placeholder":  "Votre mot de passe actuel",
            "autocomplete": "current-password",
            "autofocus":    True,
        },
    )

    submit = SubmitField(label="Désactiver le 2FA")


class AvatarUploadForm(FlaskForm):
    """Formulaire d'upload de la photo de profil (PNG/JPG, 2 Mo max)."""

    avatar = FileField(
        label="Photo de profil",
        validators=[
            FileRequired(message="Sélectionnez une image."),
            FileAllowed(["png", "jpg", "jpeg"], "Seuls les fichiers PNG et JPG sont acceptés."),
            FileSize(max_size=2 * 1024 * 1024, message="L'image ne doit pas dépasser 2 Mo."),
        ],
    )

    submit = SubmitField(label="Mettre à jour la photo")