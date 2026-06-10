"""
Utilitaires de chiffrement et hachage.
- Chiffrement AES-256-GCM pour les données sensibles (IBAN, numéro SS, etc.)
- Hachage SHA-256 pour les tokens
- Gestion de la liste noire JWT (Redis)
"""
import hashlib
import secrets
import base64
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import current_app


# ---------------------------------------------------------------------------
# Chiffrement symétrique AES-256-GCM
# ---------------------------------------------------------------------------

def _get_encryption_key() -> bytes:
    """Dérive la clé AES-256 depuis ENCRYPTION_KEY en config."""
    raw = os.environ.get("ENCRYPTION_KEY", "")
    if len(raw) < 32:
        raise EnvironmentError("ENCRYPTION_KEY doit faire au moins 32 caractères")
    return raw[:32].encode()


def encrypt_field(plaintext: str) -> str:
    """
    Chiffre une chaîne avec AES-256-GCM.
    Retourne une chaîne base64 : nonce(12) + tag(16) + ciphertext.
    """
    if not plaintext:
        return plaintext
    key   = _get_encryption_key()
    nonce = secrets.token_bytes(12)
    aesgcm = AESGCM(key)
    ct_with_tag = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct_with_tag).decode()


def decrypt_field(encrypted: str) -> str:
    """Déchiffre une chaîne chiffrée par encrypt_field()."""
    if not encrypted:
        return encrypted
    key   = _get_encryption_key()
    raw   = base64.b64decode(encrypted.encode())
    nonce = raw[:12]
    ct_with_tag = raw[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct_with_tag, None).decode()


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
