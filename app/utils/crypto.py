"""
Utilitaires de chiffrement et hachage.
- Chiffrement Fernet pour les champs sensibles (IBAN, numéro SS, etc.)
- Hachage SHA-256 pour les tokens
- Gestion de la liste noire JWT (Redis)
"""
import hashlib
import secrets
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


# ---------------------------------------------------------------------------
# Chiffrement symétrique Fernet (FIELD_ENCRYPTION_KEY)
# ---------------------------------------------------------------------------

def _get_fernet() -> Fernet:
    key = current_app.config.get("FIELD_ENCRYPTION_KEY", "")
    if not key:
        raise EnvironmentError("FIELD_ENCRYPTION_KEY est absent de la configuration.")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_field(value: str | None) -> str | None:
    """Chiffre une chaîne avec Fernet. Retourne une chaîne base64url."""
    if value is None:
        return None
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_field(value: str | None) -> str | None:
    """Déchiffre une chaîne chiffrée par encrypt_field()."""
    if value is None:
        return None
    try:
        return _get_fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Impossible de déchiffrer le champ : token invalide ou clé incorrecte.") from exc


# ---------------------------------------------------------------------------
# Hachage de tokens (réinitialisation de mot de passe, etc.)
# ---------------------------------------------------------------------------

def generate_token() -> str:
    """Génère un token URL-safe aléatoire de 48 caractères."""
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """Hache un token en SHA-256 pour stockage en base."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_token(raw_token: str, stored_hash: str) -> bool:
    """Vérifie qu'un token correspond à son hash stocké."""
    return secrets.compare_digest(hash_token(raw_token), stored_hash)


# ---------------------------------------------------------------------------
# Liste noire JWT (Redis)
# ---------------------------------------------------------------------------

def revoke_token(jti: str, expires_delta_seconds: int) -> None:
    """Ajoute un JTI à la liste noire Redis avec TTL."""
    from .extensions import cache
    cache.set(f"jwt_blocklist:{jti}", "revoked", timeout=expires_delta_seconds)


def is_token_revoked(jti: str) -> bool:
    """Retourne True si le token est dans la liste noire."""
    from .extensions import cache
    return cache.get(f"jwt_blocklist:{jti}") is not None
