"""
Modèle : AuditLog
Journal d'audit immuable — SQLAlchemy 2.0 (Mapped / mapped_column)

Enregistre toute action sensible effectuée sur la plateforme (création,
modification, suppression, connexion, approbation, export...) pour des
besoins de traçabilité, de sécurité et de conformité RGPD.

Conçu comme une table en ÉCRITURE SEULE applicativement : aucune méthode
update()/delete() n'est exposée sur ce modèle. Les seules opérations
prévues sont la création (log_action) et la lecture (consultation/export).

Le champ `user_email` est dénormalisé volontairement : si le compte
utilisateur est supprimé plus tard, la trace d'audit reste lisible et
attribuable, ce qui est une exigence de conformité (qui a fait quoi,
même après suppression du compte).

Les colonnes `old_values`/`new_values` stockent des snapshots JSON
(colonnes modifiées uniquement, pas l'objet complet) pour permettre une
reconstitution précise de l'historique sans alourdir la table.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

if TYPE_CHECKING:
    from app.models.user import User, UserSession


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditLog(db.Model):
    """
    Entrée du journal d'audit — un enregistrement par action tracée.

    Conventions d'usage :
        action       : verbe normalisé (cf. ACTIONS ci-dessous), pas de
                       texte libre, pour permettre le filtrage fiable.
        entity_type   : nom de la table/ressource concernée (ex: 'employees',
                        'leave_requests', 'users') — généralement TG_TABLE_NAME
                        si l'audit est déclenché par un trigger SQL, ou le nom
                        du modèle si déclenché applicativement.
        entity_id      : PK de la ligne concernée (NULL pour les actions sans
                        ressource précise, ex : login/logout).
        old_values /
        new_values      : dict JSON des colonnes modifiées uniquement
                          (pas l'objet complet) — None si non pertinent
                          (ex : login, export).

    Cette table n'a volontairement AUCUNE colonne updated_at : un audit
    log ne doit jamais être modifié après sa création.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_id", "user_id"),
        Index("ix_audit_logs_action", "action"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_session_id", "session_id"),
    )

    # ── Actions normalisées (constantes) ──────────────────────────────────────
    ACTION_CREATE             = "create"
    ACTION_READ               = "read"
    ACTION_UPDATE             = "update"
    ACTION_DELETE             = "delete"
    ACTION_LOGIN              = "login"
    ACTION_LOGOUT             = "logout"
    ACTION_LOGIN_FAILED       = "login_failed"
    ACTION_EXPORT             = "export"
    ACTION_UPLOAD             = "upload"
    ACTION_DOWNLOAD           = "download"
    ACTION_APPROVE            = "approve"
    ACTION_REJECT             = "reject"
    ACTION_CANCEL             = "cancel"
    ACTION_PASSWORD_CHANGE    = "password_change"
    ACTION_PERMISSION_CHANGE  = "permission_change"

    ACTIONS: tuple[str, ...] = (
        ACTION_CREATE, ACTION_READ, ACTION_UPDATE, ACTION_DELETE,
        ACTION_LOGIN, ACTION_LOGOUT, ACTION_LOGIN_FAILED,
        ACTION_EXPORT, ACTION_UPLOAD, ACTION_DOWNLOAD,
        ACTION_APPROVE, ACTION_REJECT, ACTION_CANCEL,
        ACTION_PASSWORD_CHANGE, ACTION_PERMISSION_CHANGE,
    )

    # Actions considérées comme sensibles pour la sécurité (alertes possibles)
    SECURITY_SENSITIVE_ACTIONS: tuple[str, ...] = (
        ACTION_LOGIN_FAILED, ACTION_PASSWORD_CHANGE, ACTION_PERMISSION_CHANGE,
    )

    # ── Identifiants ──────────────────────────────────────────────────────────
    # BIGSERIAL : volumétrie potentiellement très élevée sur cette table
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ── Acteur ────────────────────────────────────────────────────────────────
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    user_email: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
        comment="Dénormalisé — conserve la traçabilité même après suppression du compte",
    )

    # ── Action tracée ─────────────────────────────────────────────────────────
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    entity_uuid: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    # ── Snapshots (JSONB natif PostgreSQL) ────────────────────────────────────
    old_values: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    new_values: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    extra_data: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True, comment="Contexte additionnel libre (clé-valeur)"
    )

    # ── Contexte de la requête ────────────────────────────────────────────────
    ip_address: Mapped[Optional[str]] = mapped_column(INET, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("user_sessions.id", ondelete="SET NULL"), nullable=True
    )

    # ── Timestamp ─────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    user: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[user_id], lazy="select"
    )
    session: Mapped[Optional["UserSession"]] = relationship(
        "UserSession", foreign_keys=[session_id], lazy="select"
    )

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def is_security_sensitive(self) -> bool:
        return self.action in self.SECURITY_SENSITIVE_ACTIONS

    @property
    def has_changes(self) -> bool:
        """True si au moins un snapshot (old ou new) est renseigné."""
        return self.old_values is not None or self.new_values is not None

    @property
    def changed_fields(self) -> list[str]:
        """
        Liste des noms de champs ayant changé, déduite par comparaison
        des clés communes entre old_values et new_values dont la valeur diffère.
        Retourne toutes les clés de new_values si old_values est absent (création).
        """
        if self.new_values is None:
            return []
        if self.old_values is None:
            return list(self.new_values.keys())
        return [
            key for key in self.new_values
            if self.old_values.get(key) != self.new_values.get(key)
        ]

    # ── Méthodes de classe — création ─────────────────────────────────────────
    @classmethod
    def record(
        cls,
        action: str,
        *,
        user_id: Optional[int] = None,
        user_email: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        entity_uuid: Optional[str] = None,
        old_values: Optional[dict] = None,
        new_values: Optional[dict] = None,
        extra_data: Optional[dict] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        session_id: Optional[str] = None,
        commit: bool = False,
    ) -> "AuditLog":
        """
        Crée et persiste une entrée d'audit.

        Args:
            action:       Doit appartenir à AuditLog.ACTIONS (non vérifié
                          strictement ici pour rester tolérant aux évolutions,
                          mais à respecter par convention).
            commit:        Si True, exécute db.session.commit() immédiatement.
                          Par défaut False — laisse l'appelant maîtriser la
                          transaction (ex : audit + autre opération dans le
                          même commit applicatif).

        Returns:
            L'instance AuditLog créée (ajoutée à la session, committée ou non
            selon `commit`).

        Note : cette méthode ne lève jamais d'exception métier — en cas
        d'échec d'écriture, l'erreur SQLAlchemy native se propage telle
        quelle. L'appelant (ex : décorateur @audit_action) est responsable
        d'encapsuler l'appel dans un try/except non bloquant si l'audit
        ne doit jamais faire échouer l'opération principale.
        """
        entry = cls(
            user_id=user_id,
            user_email=user_email,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_uuid=entity_uuid,
            old_values=old_values,
            new_values=new_values,
            extra_data=extra_data,
            ip_address=ip_address,
            user_agent=user_agent,
            session_id=session_id,
        )
        db.session.add(entry)
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return entry

    # ── Méthodes de classe — lecture / filtrage ───────────────────────────────
    @classmethod
    def get_or_404(cls, log_id: int) -> "AuditLog":
        log = db.session.get(cls, log_id)
        if log is None:
            from flask import abort
            abort(404, description="Entrée d'audit introuvable.")
        return log

    @classmethod
    def for_entity(cls, entity_type: str, entity_id: int):
        """Requête (non exécutée) de l'historique d'audit d'une ressource précise."""
        return db.select(cls).where(
            cls.entity_type == entity_type,
            cls.entity_id == entity_id,
        ).order_by(cls.created_at.desc())

    @classmethod
    def for_user(cls, user_id: int):
        """Requête (non exécutée) de toutes les actions effectuées par un utilisateur."""
        return db.select(cls).where(cls.user_id == user_id).order_by(cls.created_at.desc())

    @classmethod
    def security_events(cls, since: Optional[datetime] = None):
        """
        Requête (non exécutée) des événements sensibles pour la sécurité
        (échecs de connexion, changements de mot de passe, changements
        de permissions), optionnellement depuis une date donnée.
        """
        query = db.select(cls).where(
            cls.action.in_(cls.SECURITY_SENSITIVE_ACTIONS)
        )
        if since is not None:
            query = query.where(cls.created_at >= since)
        return query.order_by(cls.created_at.desc())

    @classmethod
    def login_history(cls, user_id: Optional[int] = None, limit: int = 50):
        """Requête (non exécutée) de l'historique des connexions/déconnexions."""
        query = db.select(cls).where(
            cls.action.in_((cls.ACTION_LOGIN, cls.ACTION_LOGOUT, cls.ACTION_LOGIN_FAILED))
        )
        if user_id is not None:
            query = query.where(cls.user_id == user_id)
        return query.order_by(cls.created_at.desc()).limit(limit)

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "user_email": self.user_email,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "entity_uuid": self.entity_uuid,
            "old_values": self.old_values,
            "new_values": self.new_values,
            "changed_fields": self.changed_fields,
            "extra_data": self.extra_data,
            "ip_address": str(self.ip_address) if self.ip_address else None,
            "is_security_sensitive": self.is_security_sensitive,
            "created_at": self.created_at.isoformat(),
        }

    # ── Dunder ────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} action={self.action!r} "
            f"entity={self.entity_type}:{self.entity_id} user={self.user_id}>"
        )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, AuditLog) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)