"""
Modèle : Notification
Notification in-app et email — SQLAlchemy 2.0 (Mapped / mapped_column)

Représente une notification adressée à un utilisateur de la plateforme,
déclenchée par un événement métier (demande de congé soumise, approuvée,
évaluation à compléter, document expiré, etc.). Une notification peut
être affichée dans l'interface (badge, centre de notifications) et/ou
envoyée par email selon le canal configuré.

Le couple (entity_type, entity_id) permet un lien polymorphe léger vers
la ressource concernée (ex : entity_type='leave_requests', entity_id=42)
sans dépendance FK stricte — la ressource source peut appartenir à
n'importe quel module métier sans coupler ce modèle à toutes les tables.

Ce modèle est consommé typiquement par :
  - notification_service.py    → création et marquage lu/archivé
  - notification_tasks.py (Celery) → envoi email asynchrone, archivage
    automatique des notifications expirées

Relations principales :
  - recipient (N:1) → utilisateur destinataire (User)
  - sender    (N:1, optionnelle) → utilisateur à l'origine de l'action
              (None si notification système/automatique)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.extensions import db

if TYPE_CHECKING:
    from app.models.user import User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Notification(db.Model):
    """
    Notification adressée à un utilisateur.

    Cycle de vie (champ `status`) :
        unread ──► read ──► archived
           │
           └──────────────► archived  (expiration automatique)

    Le canal (`channel`) détermine où la notification doit apparaître :
        in_app  — uniquement dans le centre de notifications de l'UI
        email    — uniquement par email (pas de badge in-app)
        both     — les deux (comportement par défaut le plus courant)

    `email_sent_at`/`email_error` tracent l'état de l'envoi email
    indépendamment du statut de lecture in-app, car les deux canaux
    sont asynchrones et peuvent échouer indépendamment.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('in_app','email','both')",
            name="ck_notifications_channel_valid",
        ),
        CheckConstraint(
            "status IN ('unread','read','archived')",
            name="ck_notifications_status_valid",
        ),
        CheckConstraint(
            "read_at IS NULL OR status IN ('read','archived')",
            name="ck_notifications_read_consistency",
        ),
        Index("ix_notifications_recipient_id", "recipient_id"),
        Index("ix_notifications_recipient_status", "recipient_id", "status"),
        Index("ix_notifications_entity", "entity_type", "entity_id"),
        Index("ix_notifications_created_at", "created_at"),
    )

    # ── Canaux (constantes) ───────────────────────────────────────────────────
    CHANNEL_IN_APP = "in_app"
    CHANNEL_EMAIL  = "email"
    CHANNEL_BOTH   = "both"

    CHANNELS: tuple[str, ...] = (CHANNEL_IN_APP, CHANNEL_EMAIL, CHANNEL_BOTH)

    # ── Statuts (constantes) ──────────────────────────────────────────────────
    STATUS_UNREAD   = "unread"
    STATUS_READ     = "read"
    STATUS_ARCHIVED = "archived"

    STATUSES: tuple[str, ...] = (STATUS_UNREAD, STATUS_READ, STATUS_ARCHIVED)

    # ── Identifiants ──────────────────────────────────────────────────────────
    # BIGSERIAL : volumétrie potentiellement élevée (une notif par événement/utilisateur)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ── Rattachements ─────────────────────────────────────────────────────────
    recipient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    sender_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        comment="NULL = notification système/automatique",
    )

    # ── Canal & statut ────────────────────────────────────────────────────────
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default=CHANNEL_BOTH)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_UNREAD)

    # ── Contenu ───────────────────────────────────────────────────────────────
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    action_url: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True, comment="Lien vers la ressource concernée (deep-link)"
    )

    # ── Lien polymorphe léger vers la ressource source ────────────────────────
    entity_type: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True, comment="ex : 'leave_requests', 'evaluations'"
    )
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── Suivi de lecture ──────────────────────────────────────────────────────
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Suivi de l'envoi email (indépendant du statut in-app) ─────────────────
    email_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    email_error: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Message d'erreur si l'envoi email a échoué"
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Passé cette date, archivage automatique par tâche Celery",
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    recipient: Mapped["User"] = relationship(
        "User", foreign_keys=[recipient_id], lazy="joined"
    )
    sender: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[sender_id], lazy="select"
    )

    # ── Validation SQLAlchemy ─────────────────────────────────────────────────
    @validates("title")
    def _strip_title(self, key: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Le titre de la notification ne peut pas être vide.")
        return value.strip()

    @validates("channel")
    def _validate_channel(self, key: str, value: str) -> str:
        if value not in self.CHANNELS:
            raise ValueError(f"Canal invalide : '{value}'. Valeurs acceptées : {self.CHANNELS}")
        return value

    @validates("status")
    def _validate_status(self, key: str, value: str) -> str:
        if value not in self.STATUSES:
            raise ValueError(f"Statut invalide : '{value}'. Valeurs acceptées : {self.STATUSES}")
        return value

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def is_unread(self) -> bool:
        return self.status == self.STATUS_UNREAD

    @property
    def is_read(self) -> bool:
        return self.status in (self.STATUS_READ, self.STATUS_ARCHIVED)

    @property
    def is_archived(self) -> bool:
        return self.status == self.STATUS_ARCHIVED

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= _utcnow()

    @property
    def requires_email(self) -> bool:
        return self.channel in (self.CHANNEL_EMAIL, self.CHANNEL_BOTH)

    @property
    def requires_in_app(self) -> bool:
        return self.channel in (self.CHANNEL_IN_APP, self.CHANNEL_BOTH)

    @property
    def email_pending(self) -> bool:
        """True si l'email doit être envoyé mais ne l'a pas encore été (ni en erreur)."""
        return self.requires_email and self.email_sent_at is None and self.email_error is None

    @property
    def email_failed(self) -> bool:
        return self.requires_email and self.email_error is not None

    @property
    def is_system_notification(self) -> bool:
        """True si la notification n'a pas d'émetteur humain identifié."""
        return self.sender_id is None

    # ── Méthodes d'instance ───────────────────────────────────────────────────
    def mark_read(self) -> None:
        """Marque la notification comme lue (idempotent)."""
        if self.status == self.STATUS_UNREAD:
            self.status = self.STATUS_READ
            self.read_at = _utcnow()

    def mark_unread(self) -> None:
        """Remet la notification en non-lue (action utilisateur explicite)."""
        self.status = self.STATUS_UNREAD
        self.read_at = None

    def archive(self) -> None:
        """Archive la notification (lue ou non)."""
        if self.read_at is None:
            self.read_at = _utcnow()
        self.status = self.STATUS_ARCHIVED

    def mark_email_sent(self) -> None:
        """Enregistre l'envoi réussi de l'email."""
        self.email_sent_at = _utcnow()
        self.email_error = None

    def mark_email_failed(self, error_message: str) -> None:
        """Enregistre l'échec de l'envoi email (ne bloque pas l'affichage in-app)."""
        self.email_error = error_message[:2000]  # Tronqué par sécurité

    # ── Méthodes de classe — création ─────────────────────────────────────────
    @classmethod
    def create_for_user(
        cls,
        recipient_id: int,
        title: str,
        body: str,
        *,
        sender_id: Optional[int] = None,
        channel: str = CHANNEL_BOTH,
        action_url: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        expires_in_days: Optional[int] = None,
        commit: bool = False,
    ) -> "Notification":
        """
        Crée une notification pour un utilisateur.

        Args:
            expires_in_days: Si fourni, calcule expires_at = maintenant + N jours.
            commit:            Si True, commite immédiatement. Par défaut False
                              pour laisser l'appelant maîtriser la transaction
                              (ex : créer la notif dans le même commit que
                              l'action métier qui la déclenche).

        Returns:
            L'instance Notification créée et ajoutée à la session.
        """
        expires_at = None
        if expires_in_days is not None:
            expires_at = _utcnow() + timedelta(days=expires_in_days)

        notification = cls(
            recipient_id=recipient_id,
            sender_id=sender_id,
            channel=channel,
            title=title,
            body=body,
            action_url=action_url,
            entity_type=entity_type,
            entity_id=entity_id,
            expires_at=expires_at,
        )
        db.session.add(notification)
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return notification

    # ── Méthodes de classe — lecture / filtrage ───────────────────────────────
    @classmethod
    def get_or_404(cls, notification_id: int) -> "Notification":
        notification = db.session.get(cls, notification_id)
        if notification is None:
            from flask import abort
            abort(404, description="Notification introuvable.")
        return notification

    @classmethod
    def for_recipient(cls, recipient_id: int, *, status: Optional[str] = None):
        """Requête (non exécutée) des notifications d'un utilisateur, filtrables par statut."""
        query = db.select(cls).where(cls.recipient_id == recipient_id)
        if status is not None:
            query = query.where(cls.status == status)
        return query.order_by(cls.created_at.desc())

    @classmethod
    def unread_for_recipient(cls, recipient_id: int):
        """Requête (non exécutée) des notifications non lues d'un utilisateur."""
        return cls.for_recipient(recipient_id, status=cls.STATUS_UNREAD)

    @classmethod
    def unread_count(cls, recipient_id: int) -> int:
        """Nombre de notifications non lues — utilisé pour le badge de l'UI."""
        return db.session.execute(
            db.select(db.func.count(cls.id)).where(
                cls.recipient_id == recipient_id,
                cls.status == cls.STATUS_UNREAD,
            )
        ).scalar_one()

    @classmethod
    def pending_emails(cls, limit: int = 100):
        """
        Requête (non exécutée) des notifications dont l'email reste à
        envoyer — consommée par la tâche Celery d'envoi asynchrone.
        """
        return db.select(cls).where(
            cls.channel.in_((cls.CHANNEL_EMAIL, cls.CHANNEL_BOTH)),
            cls.email_sent_at.is_(None),
            cls.email_error.is_(None),
        ).order_by(cls.created_at.asc()).limit(limit)

    @classmethod
    def expired_not_archived(cls, limit: int = 500):
        """
        Requête (non exécutée) des notifications expirées non encore
        archivées — consommée par la tâche Celery d'archivage automatique.
        """
        return db.select(cls).where(
            cls.expires_at.isnot(None),
            cls.expires_at <= _utcnow(),
            cls.status != cls.STATUS_ARCHIVED,
        ).limit(limit)

    @classmethod
    def mark_all_read_for_recipient(cls, recipient_id: int) -> int:
        """
        Marque toutes les notifications non lues d'un utilisateur comme lues.
        Retourne le nombre de lignes affectées. Ne commite pas — à la
        charge de l'appelant.
        """
        result = db.session.execute(
            db.update(cls)
            .where(cls.recipient_id == recipient_id, cls.status == cls.STATUS_UNREAD)
            .values(status=cls.STATUS_READ, read_at=_utcnow())
        )
        return result.rowcount

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "recipient_id": self.recipient_id,
            "sender_id": self.sender_id,
            "sender_email": self.sender.email if self.sender else None,
            "channel": self.channel,
            "status": self.status,
            "title": self.title,
            "body": self.body,
            "action_url": self.action_url,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "is_unread": self.is_unread,
            "is_expired": self.is_expired,
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "email_sent_at": self.email_sent_at.isoformat() if self.email_sent_at else None,
            "email_failed": self.email_failed,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    # ── Dunder ────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return (
            f"<Notification id={self.id} recipient={self.recipient_id} "
            f"[{self.status}] {self.title!r}>"
        )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Notification) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)