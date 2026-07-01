"""
Modèles : User · UserSession · PasswordResetToken
Auth — SQLAlchemy 2.0 (Mapped / mapped_column)
"""
from __future__ import annotations

import hashlib
import secrets
import uuid as _uuid_module
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, List, Optional

import bcrypt
import pyotp
from flask import current_app
from flask_login import UserMixin
from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey,
    Index, Integer, SmallInteger, String, Text, event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.extensions import db

if TYPE_CHECKING:
    from app.models.role import Role


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================================
# User
# =============================================================================

class User(UserMixin, db.Model):
    """
    Compte d'accès à la plateforme RH.

    Hérite de UserMixin (Flask-Login) pour is_authenticated, get_id()…
    Identifié publiquement par uuid (jamais par id dans les URLs/API).

    Sécurité :
      - Mot de passe : bcrypt, facteur de coût configurable (BCRYPT_LOG_ROUNDS)
      - Verrouillage : après MAX_LOGIN_ATTEMPTS tentatives échouées
      - 2FA : TOTP RFC 6238 (Google Authenticator, Authy…)
      - Sessions : Flask-Login (SSR) + JWT (API REST)
    """
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("failed_login_attempts >= 0", name="ck_users_attempts_positive"),
        CheckConstraint(
            "email ~* '^[A-Za-z0-9._%+\\-]+@[A-Za-z0-9.\\-]+\\.[A-Za-z]{2,}$'",
            name="ck_users_email_format",
        ),
        Index("ix_users_email_lower", "email"),        # index sur email (insensible casse géré applicativement)
        Index("ix_users_active", "is_active"),
    )

    # ── Identifiants ──────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        unique=True,
        default=lambda: str(_uuid_module.uuid4()),
        index=True,
        comment="Identifiant public non séquentiel (URLs, API)",
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # ── Rôle ──────────────────────────────────────────────────────────────────
    role_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("roles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # ── Statut du compte ──────────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    force_password_change: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── 2FA (TOTP) ────────────────────────────────────────────────────────────
    totp_secret: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
        comment="Secret base32 — chiffré côté application avant stockage"
    )
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Sécurité connexion ────────────────────────────────────────────────────
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_ip: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True,
        comment="Supporte IPv4 et IPv6"
    )
    failed_login_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0
    )
    locked_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="NULL = compte non verrouillé"
    )

    # ── Préférences ───────────────────────────────────────────────────────────
    preferred_language: Mapped[str] = mapped_column(
        String(2), nullable=False, default="fr"
    )
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Europe/Paris"
    )

    # ── Avatar ────────────────────────────────────────────────────────────────
    avatar_path: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True,
        comment="Chemin relatif depuis UPLOAD_FOLDER — pas de donnée sensible, non chiffré",
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    role: Mapped[Role] = relationship(
        "Role",
        back_populates="users",
        lazy="joined",            # Chargé systématiquement (évite N+1 sur les vérifications de rôle)
    )
    sessions: Mapped[List[UserSession]] = relationship(
        "UserSession",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    reset_tokens: Mapped[List[PasswordResetToken]] = relationship(
        "PasswordResetToken",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    # employee → défini dans app/models/employee.py avec back_populates="user"

    # ── Validation SQLAlchemy ─────────────────────────────────────────────────
    @validates("email")
    def normalize_email(self, key: str, value: str) -> str:
        """Force la mise en minuscules et supprime les espaces."""
        return value.lower().strip() if value else value

    @validates("preferred_language")
    def validate_language(self, key: str, value: str) -> str:
        allowed = {"fr", "en"}
        if value not in allowed:
            raise ValueError(f"Langue non supportée : {value}. Valeurs acceptées : {allowed}")
        return value

    # ── Flask-Login ───────────────────────────────────────────────────────────
    def get_id(self) -> str:
        """Identifiant de session Flask-Login (chaîne obligatoire)."""
        return str(self.id)

    @property
    def is_active(self) -> bool:  # type: ignore[override]
        """
        Surcharge Flask-Login.
        Retourne False si le compte est désactivé OU verrouillé temporairement.
        """
        if not self._is_active:
            return False
        if self.locked_until and self.locked_until > _utcnow():
            return False
        return True

    @is_active.setter
    def is_active(self, value: bool) -> None:
        self._is_active = value

    # Colonne réelle (is_active est une propriété Python, pas directement mappée)
    _is_active: Mapped[bool] = mapped_column(
        "is_active", Boolean, nullable=False, default=True
    )

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def is_locked(self) -> bool:
        """True si le compte est en période de verrouillage."""
        return bool(self.locked_until and self.locked_until > _utcnow())

    @property
    def lockout_remaining_seconds(self) -> int:
        """Secondes restantes de verrouillage. 0 si non verrouillé."""
        if not self.is_locked or self.locked_until is None:
            return 0
        return max(0, int((self.locked_until - _utcnow()).total_seconds()))

    @property
    def active_sessions(self) -> list[UserSession]:
        """Sessions actuellement actives (non révoquées, non expirées)."""
        return [s for s in self.sessions if s.is_active]

    # ── Mot de passe ──────────────────────────────────────────────────────────
    def set_password(self, plain_password: str) -> None:
        """
        Hache le mot de passe avec bcrypt.
        Le facteur de coût est lu depuis BCRYPT_LOG_ROUNDS (config, défaut=12).
        """
        rounds = current_app.config.get("BCRYPT_LOG_ROUNDS", 12)
        hashed = bcrypt.hashpw(
            plain_password.encode("utf-8"),
            bcrypt.gensalt(rounds=rounds),
        )
        self.password_hash = hashed.decode("utf-8")

    def check_password(self, plain_password: str) -> bool:
        """
        Vérifie un mot de passe en clair contre le hash bcrypt stocké.
        Retourne False (sans exception) si password_hash est absent.
        """
        if not self.password_hash:
            return False
        try:
            return bcrypt.checkpw(
                plain_password.encode("utf-8"),
                self.password_hash.encode("utf-8"),
            )
        except Exception:
            return False

    # ── Verrouillage de compte ────────────────────────────────────────────────
    def record_failed_login(self) -> None:
        """
        Incrémente le compteur d'échecs.
        Verrouille le compte si MAX_LOGIN_ATTEMPTS est atteint.
        """
        self.failed_login_attempts += 1
        max_attempts = current_app.config.get("MAX_LOGIN_ATTEMPTS", 5)
        lockout_minutes = current_app.config.get("ACCOUNT_LOCKOUT_MINUTES", 15)

        if self.failed_login_attempts >= max_attempts:
            self.locked_until = _utcnow() + timedelta(minutes=lockout_minutes)

    def record_successful_login(self, ip_address: Optional[str] = None) -> None:
        """Réinitialise tous les compteurs de sécurité après une connexion réussie."""
        self.failed_login_attempts = 0
        self.locked_until = None
        self.last_login_at = _utcnow()
        self.last_login_ip = ip_address

    def unlock(self) -> None:
        """Déverrouille manuellement le compte (action admin)."""
        self.locked_until = None
        self.failed_login_attempts = 0

    # ── 2FA (TOTP) ────────────────────────────────────────────────────────────
    def generate_totp_secret(self) -> str:
        """
        Génère un nouveau secret TOTP base32 et le stocke (sans activer le 2FA).
        Retourne le secret pour l'affichage du QR code.
        """
        self.totp_secret = pyotp.random_base32()
        return self.totp_secret

    def get_totp_uri(self) -> str:
        """
        Retourne l'URI otpauth:// pour la génération du QR code.
        Lève ValueError si aucun secret n'a été généré.
        """
        if not self.totp_secret:
            raise ValueError("Aucun secret TOTP disponible. Appelez generate_totp_secret() d'abord.")
        issuer = current_app.config.get("TOTP_ISSUER_NAME", "Plateforme RH")
        return pyotp.TOTP(self.totp_secret).provisioning_uri(
            name=self.email,
            issuer_name=issuer,
        )

    def verify_totp(self, code: str) -> bool:
        """
        Vérifie un code TOTP à 6 chiffres.
        valid_window=1 : tolère ±30s de décalage d'horloge.
        """
        if not self.totp_secret:
            return False
        return pyotp.TOTP(self.totp_secret).verify(code, valid_window=1)

    def enable_totp(self, confirmation_code: str) -> bool:
        """
        Active le 2FA après vérification du code de confirmation.
        Retourne True si activé, False si code invalide.
        """
        if self.verify_totp(confirmation_code):
            self.totp_enabled = True
            return True
        return False

    def disable_totp(self) -> None:
        """Désactive le 2FA et efface le secret stocké."""
        self.totp_enabled = False
        self.totp_secret = None

    # ── Permissions (délégation au rôle) ──────────────────────────────────────
    def has_permission(self, code: str) -> bool:
        """Vérifie si l'utilisateur possède une permission atomique via son rôle."""
        return self.role.has_permission(code) if self.role else False

    def has_role(self, *role_names: str) -> bool:
        """Vérifie si le rôle de l'utilisateur est parmi les noms fournis."""
        return self.role.name in role_names if self.role else False

    def is_at_least(self, role_name: str) -> bool:
        """Vérifie le niveau hiérarchique minimum requis."""
        return self.role.is_at_least(role_name) if self.role else False

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_by_email(cls, email: str) -> Optional[User]:
        return db.session.execute(
            db.select(cls).where(cls.email == email.lower().strip())
        ).scalar_one_or_none()

    @classmethod
    def get_by_uuid(cls, uuid: str) -> Optional[User]:
        return db.session.execute(
            db.select(cls).where(cls.uuid == uuid)
        ).scalar_one_or_none()

    @classmethod
    def get_or_404(cls, user_id: int) -> User:
        user = db.session.get(cls, user_id)
        if user is None:
            from flask import abort
            abort(404, description="Utilisateur introuvable.")
        return user

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self, include_permissions: bool = False) -> dict:
        data: dict = {
            "id":                    self.id,
            "uuid":                  self.uuid,
            "email":                 self.email,
            "role":                  self.role.name if self.role else None,
            "role_label":            self.role.label if self.role else None,
            "is_active":             self._is_active,
            "is_locked":             self.is_locked,
            "is_email_verified":     self.is_email_verified,
            "totp_enabled":          self.totp_enabled,
            "force_password_change": self.force_password_change,
            "preferred_language":    self.preferred_language,
            "last_login_at":         self.last_login_at.isoformat() if self.last_login_at else None,
            "created_at":            self.created_at.isoformat(),
            "updated_at":            self.updated_at.isoformat(),
        }
        if include_permissions:
            data["permissions"] = list(self.role.permission_codes) if self.role else []
        return data

    # ── Dunder ────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        role_name = self.role.name if self.role else "no-role"
        return f"<User id={self.id} email={self.email!r} role={role_name}>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, User) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


# =============================================================================
# UserSession
# =============================================================================

class UserSession(db.Model):
    """
    Enregistrement d'une session utilisateur active.

    Stocke les refresh tokens (via leur session_id dans les claims JWT)
    et permet la révocation côté serveur sans liste noire globale.
    """
    __tablename__ = "user_sessions"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="ck_session_expiry_valid"),
        Index("ix_session_user_expires", "user_id", "expires_at"),
    )

    # ── Colonnes ─────────────────────────────────────────────────────────────
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(_uuid_module.uuid4()),
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    user: Mapped[User] = relationship("User", back_populates="sessions")

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def is_active(self) -> bool:
        """Session valide : non révoquée ET non expirée."""
        return self.revoked_at is None and self.expires_at > _utcnow()

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= _utcnow()

    # ── Méthodes ──────────────────────────────────────────────────────────────
    def revoke(self) -> None:
        """Révoque la session (déconnexion côté serveur)."""
        self.revoked_at = _utcnow()

    def touch(self) -> None:
        """Met à jour le timestamp de dernière activité."""
        self.last_active_at = _utcnow()

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_active(cls, session_id: str, user_id: int) -> Optional[UserSession]:
        """Récupère une session active par son ID et son propriétaire."""
        session = db.session.get(cls, session_id)
        if session and session.user_id == user_id and session.is_active:
            return session
        return None

    @classmethod
    def revoke_all_for_user(cls, user_id: int) -> int:
        """
        Révoque toutes les sessions actives d'un utilisateur.
        Retourne le nombre de sessions révoquées.
        """
        now = _utcnow()
        result = db.session.execute(
            db.update(cls)
            .where(cls.user_id == user_id, cls.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        return result.rowcount

    @classmethod
    def cleanup_expired(cls, user_id: Optional[int] = None) -> int:
        """
        Supprime les sessions expirées de la base.
        Si user_id est fourni, ne traite que cet utilisateur.
        Retourne le nombre de lignes supprimées.
        """
        stmt = db.delete(cls).where(cls.expires_at <= _utcnow())
        if user_id is not None:
            stmt = stmt.where(cls.user_id == user_id)
        result = db.session.execute(stmt)
        return result.rowcount

    def __repr__(self) -> str:
        status = "active" if self.is_active else ("expired" if self.is_expired else "revoked")
        return f"<UserSession {self.id[:8]}… user={self.user_id} [{status}]>"


# =============================================================================
# PasswordResetToken
# =============================================================================

class PasswordResetToken(db.Model):
    """
    Token de réinitialisation de mot de passe à usage unique.

    Flux :
        1. request_password_reset() → génère token, stocke SHA-256, envoie email
        2. Utilisateur clique le lien → find_valid(raw_token) vérifie hash + expiry
        3. confirm_password_reset()  → mark_used() + set_password()

    Sécurité :
        - Seul le SHA-256(token_brut) est stocké — le token brut n'est jamais persisté
        - Validité : PASSWORD_RESET_EXPIRY_HOURS (défaut : 1h)
        - Usage unique : used_at IS NULL pour être valide
        - Création d'un nouveau token invalide tous les anciens
    """
    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="ck_prt_expiry_valid"),
        Index("ix_prt_user_used", "user_id", "used_at"),
    )

    # ── Colonnes ─────────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="SHA-256 du token brut envoyé par email — jamais le token en clair",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    user: Mapped[User] = relationship("User", back_populates="reset_tokens")

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def is_valid(self) -> bool:
        """Token utilisable : non utilisé ET non expiré."""
        return self.used_at is None and self.expires_at > _utcnow()

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= _utcnow()

    # ── Méthodes ──────────────────────────────────────────────────────────────
    def mark_used(self) -> None:
        """Consomme le token (idempotent)."""
        if self.used_at is None:
            self.used_at = _utcnow()

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def create_for_user(cls, user: User) -> tuple[PasswordResetToken, str]:
        """
        Génère un token de reset sécurisé pour un utilisateur.

        Invalide tous les tokens précédents non utilisés avant d'en créer un.

        Returns:
            (instance PasswordResetToken, raw_token à envoyer par email)

        Le raw_token est un secret URL-safe de 48 octets (384 bits d'entropie).
        """
        # Invalider les anciens tokens actifs
        db.session.execute(
            db.update(cls)
            .where(cls.user_id == user.id, cls.used_at.is_(None))
            .values(used_at=_utcnow())
        )

        raw_token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        expiry_hours = current_app.config.get("PASSWORD_RESET_EXPIRY_HOURS", 1)

        instance = cls(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=_utcnow() + timedelta(hours=expiry_hours),
        )
        db.session.add(instance)
        return instance, raw_token

    @classmethod
    def find_valid(cls, raw_token: str) -> Optional[PasswordResetToken]:
        """
        Recherche un token valide à partir du token brut reçu.
        Retourne None si le token est inexistant, expiré ou déjà utilisé.
        """
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        result = db.session.execute(
            db.select(cls).where(cls.token_hash == token_hash)
        ).scalar_one_or_none()
        return result if (result and result.is_valid) else None

    @classmethod
    def cleanup_expired(cls) -> int:
        """Supprime les tokens expirés. Retourne le nombre de lignes supprimées."""
        result = db.session.execute(
            db.delete(cls).where(cls.expires_at <= _utcnow())
        )
        return result.rowcount

    def __repr__(self) -> str:
        status = "valid" if self.is_valid else ("used" if self.used_at else "expired")
        return f"<PasswordResetToken user={self.user_id} [{status}]>"


# =============================================================================
# Événements SQLAlchemy
# =============================================================================

@event.listens_for(User, "before_update")
def prevent_last_admin_deactivation(mapper, connection, target: User) -> None:
    """
    Empêche la désactivation du dernier administrateur actif.
    Vérifié uniquement si is_active passe à False.
    """
    from sqlalchemy import inspect as sa_inspect
    state = sa_inspect(target)
    history = state.attrs._is_active.history

    # history.deleted contient l'ancienne valeur si elle a changé
    if history.deleted and history.deleted[0] is True and not target._is_active:
        admin_count = db.session.execute(
            db.select(db.func.count(User.id))
            .join(User.role)
            .where(
                User._is_active.is_(True),
                db.text("roles.name = 'admin'"),
            )
        ).scalar_one()
        if admin_count == 0:
            raise ValueError(
                "Impossible de désactiver le dernier administrateur actif."
            )