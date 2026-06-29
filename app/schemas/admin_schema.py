"""
Schémas Marshmallow : User · Role (gestion par un administrateur)

Convention identique aux autres schémas du projet :
  - <X>Schema        — sérialisation complète (lecture / réponse API)
  - <X>CreateSchema   — validation stricte à la création
  - <X>UpdateSchema    — validation pour mise à jour partielle (PATCH)

Règles de sécurité :
  - `password_hash` n'est jamais exposé.
  - `password` est load_only (saisie uniquement, jamais sérialisé).
  - Les rôles système (is_system=True) ne peuvent pas être renommés via
    le schéma : la contrainte est appliquée au niveau service.
"""
from __future__ import annotations

import re

from marshmallow import (
    Schema,
    ValidationError,
    fields,
    validate,
    validates,
    validates_schema,
)

# =============================================================================
# Constantes (alignées avec les modèles)
# =============================================================================

LANGUAGES = ("fr", "en")
ROLE_NAMES = ("employee", "manager", "rh", "admin")


# =============================================================================
# UserSchema — sérialisation complète (lecture)
# =============================================================================

class UserSchema(Schema):
    """Représentation complète d'un User, utilisée en lecture (GET)."""

    id = fields.Integer(dump_only=True)
    uuid = fields.String(dump_only=True)
    email = fields.Email(dump_only=True)

    role_id = fields.Integer(dump_only=True)
    role_name = fields.Method("_get_role_name", dump_only=True)
    role_label = fields.Method("_get_role_label", dump_only=True)

    is_active = fields.Boolean(dump_only=True)
    is_locked = fields.Boolean(dump_only=True)
    is_email_verified = fields.Boolean(dump_only=True)
    totp_enabled = fields.Boolean(dump_only=True)
    force_password_change = fields.Boolean(dump_only=True)

    preferred_language = fields.String(dump_only=True)
    timezone = fields.String(dump_only=True)

    last_login_at = fields.DateTime(dump_only=True)
    last_login_ip = fields.String(dump_only=True)
    failed_login_attempts = fields.Integer(dump_only=True)

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    def _get_role_name(self, obj) -> str | None:
        role = getattr(obj, "role", None)
        return role.name if role else None

    def _get_role_label(self, obj) -> str | None:
        role = getattr(obj, "role", None)
        return role.label if role else None


# =============================================================================
# UserCreateSchema — validation stricte à la création
# =============================================================================

class UserCreateSchema(Schema):
    """
    Validation des données à la création d'un User par un admin.

    `password` est obligatoire à la création ; il ne doit jamais être
    renvoyé dans une réponse (load_only=True).
    """

    email = fields.Email(
        required=True,
        validate=validate.Length(max=255),
    )
    password = fields.String(
        required=True,
        load_only=True,
        validate=validate.Length(min=8, max=128),
    )
    role_id = fields.Integer(required=True)

    is_active = fields.Boolean(load_default=True)
    is_email_verified = fields.Boolean(load_default=False)
    force_password_change = fields.Boolean(load_default=True)

    preferred_language = fields.String(
        load_default="fr",
        validate=validate.OneOf(LANGUAGES),
    )
    timezone = fields.String(
        load_default="Europe/Paris",
        validate=validate.Length(max=64),
    )

    @validates("password")
    def validate_password_strength(self, value: str, **kwargs) -> None:
        if not re.search(r"[A-Z]", value):
            raise ValidationError("Le mot de passe doit contenir au moins une majuscule.")
        if not re.search(r"[0-9]", value):
            raise ValidationError("Le mot de passe doit contenir au moins un chiffre.")


# =============================================================================
# UserUpdateSchema — validation pour mise à jour partielle
# =============================================================================

class UserUpdateSchema(Schema):
    """
    Validation des données à la modification d'un User par un admin.
    Tous les champs sont optionnels (PATCH sémantique).
    """

    email = fields.Email(validate=validate.Length(max=255))
    password = fields.String(
        load_only=True,
        validate=validate.Length(min=8, max=128),
    )
    role_id = fields.Integer()

    is_active = fields.Boolean()
    is_email_verified = fields.Boolean()
    force_password_change = fields.Boolean()

    preferred_language = fields.String(validate=validate.OneOf(LANGUAGES))
    timezone = fields.String(validate=validate.Length(max=64))

    @validates("password")
    def validate_password_strength(self, value: str, **kwargs) -> None:
        if not re.search(r"[A-Z]", value):
            raise ValidationError("Le mot de passe doit contenir au moins une majuscule.")
        if not re.search(r"[0-9]", value):
            raise ValidationError("Le mot de passe doit contenir au moins un chiffre.")


# =============================================================================
# RoleSchema — sérialisation complète (lecture)
# =============================================================================

class RoleSchema(Schema):
    """Représentation complète d'un Role, utilisée en lecture (GET)."""

    id = fields.Integer(dump_only=True)
    name = fields.String(dump_only=True)
    label = fields.String(dump_only=True)
    description = fields.String(dump_only=True, allow_none=True)
    is_system = fields.Boolean(dump_only=True)
    hierarchy_level = fields.Integer(dump_only=True)

    permissions = fields.Method("_get_permissions", dump_only=True)

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    def _get_permissions(self, obj) -> list[dict]:
        return [p.to_dict() for p in getattr(obj, "permissions", [])]


# =============================================================================
# RoleCreateSchema — validation stricte à la création
# =============================================================================

class RoleCreateSchema(Schema):
    """Validation des données à la création d'un Role par un admin."""

    name = fields.String(
        required=True,
        validate=[
            validate.Length(min=2, max=50),
            validate.Regexp(r"^[a-z][a-z0-9_]*$", error="Le nom doit être en snake_case minuscule."),
        ],
    )
    label = fields.String(required=True, validate=validate.Length(min=1, max=100))
    description = fields.String(allow_none=True, validate=validate.Length(max=500))
    is_system = fields.Boolean(load_default=False)
    permission_ids = fields.List(fields.Integer(), load_default=list)

    @validates("name")
    def validate_name_not_reserved(self, value: str, **kwargs) -> None:
        if value in ROLE_NAMES:
            raise ValidationError(
                f"'{value}' est un nom de rôle système réservé. Choisissez un autre nom."
            )


# =============================================================================
# RoleUpdateSchema — validation pour mise à jour partielle
# =============================================================================

class RoleUpdateSchema(Schema):
    """
    Validation des données à la modification d'un Role par un admin.
    Tous les champs sont optionnels (PATCH sémantique).

    Le renommage d'un rôle système (is_system=True) est bloqué
    au niveau service, pas ici.
    """

    label = fields.String(validate=validate.Length(min=1, max=100))
    description = fields.String(allow_none=True, validate=validate.Length(max=500))
    permission_ids = fields.List(fields.Integer())

    @validates_schema
    def forbid_name_change(self, data: dict, **kwargs) -> None:
        if "name" in data:
            raise ValidationError(
                "Le nom d'un rôle ne peut pas être modifié après sa création.",
                field_name="name",
            )


# =============================================================================
# Instances prêtes à l'emploi
# =============================================================================

user_schema = UserSchema()
users_schema = UserSchema(many=True)
user_create_schema = UserCreateSchema()
user_update_schema = UserUpdateSchema()

role_schema = RoleSchema()
roles_schema = RoleSchema(many=True)
role_create_schema = RoleCreateSchema()
role_update_schema = RoleUpdateSchema()
