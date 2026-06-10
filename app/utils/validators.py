"""
Validateurs métier réutilisables.

Peuvent être utilisés dans les formulaires WTForms, les services,
et les schémas Marshmallow.
"""
from __future__ import annotations

import re
from datetime import date


SIRET_REGEX = re.compile(r"^\d{14}$")
IBAN_FR_REGEX = re.compile(r"^FR\d{2}[A-Z0-9]{23}$")
PHONE_REGEX = re.compile(r"^(\+33|0)[1-9](\d{8})$")


def validate_siret(value: str) -> bool:
    """Valide le format d'un numéro SIRET (14 chiffres)."""
    return bool(SIRET_REGEX.match(value.replace(" ", "")))


def validate_iban(value: str) -> bool:
    """Valide le format d'un IBAN français."""
    return bool(IBAN_FR_REGEX.match(value.replace(" ", "").upper()))


def validate_phone_fr(value: str) -> bool:
    """Valide le format d'un numéro de téléphone français."""
    return bool(PHONE_REGEX.match(value.replace(" ", "").replace("-", "")))


def validate_date_range(start: date, end: date) -> bool:
    """Vérifie que la date de fin est >= date de début."""
    return end >= start


def validate_password_strength(password: str, min_length: int = 10) -> list[str]:
    """
    Retourne une liste d'erreurs (vide = mot de passe valide).
    Règles : longueur, majuscule, minuscule, chiffre, caractère spécial.
    """
    errors = []
    if len(password) < min_length:
        errors.append(f"Au moins {min_length} caractères requis.")
    if not re.search(r"[A-Z]", password):
        errors.append("Au moins une lettre majuscule requise.")
    if not re.search(r"[a-z]", password):
        errors.append("Au moins une lettre minuscule requise.")
    if not re.search(r"\d", password):
        errors.append("Au moins un chiffre requis.")
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", password):
        errors.append("Au moins un caractère spécial requis.")
    return errors
