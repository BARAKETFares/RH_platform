"""
Modèle : LeaveType
Type d'absence configurable — SQLAlchemy 2.0 (Mapped / mapped_column)

Représente un type d'absence paramétrable par l'entreprise (Congés Payés,
RTT, Arrêt Maladie, Maternité/Paternité, Événement Familial, Congé Sans
Solde, Formation, Télétravail...). Chaque type définit ses propres règles :
justification requise, délai de prévenance, impact sur le solde de congés,
rémunération ou non.

Relations principales :
  - company        (N:1) → entreprise de rattachement
  - leave_balances  (1:N) → soldes annuels par employé (défini dans leave_balance.py)
  - leave_requests  (1:N) → demandes d'absence (défini dans leave_request.py)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.extensions import db

if TYPE_CHECKING:
    from app.models.organization import Company


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LeaveType(db.Model):
    """
    Type d'absence configurable par entreprise.

    Le champ `code` est un identifiant court et stable utilisé dans les
    calculs, les exports et l'affichage compact (ex : 'CP', 'RTT', 'MAL').
    `color_hex` permet de coder visuellement chaque type dans le calendrier
    d'équipe et les widgets Chart.js du dashboard RH.

    `impacts_leave_balance` distingue les absences décomptées d'un solde
    (CP, RTT) de celles qui n'en consomment pas (maladie, maternité) —
    cette distinction pilote directement la logique du module Congés.
    """

    __tablename__ = "leave_types"
    __table_args__ = (
        CheckConstraint(
            "max_consecutive_days IS NULL OR max_consecutive_days > 0",
            name="ck_leave_types_max_days_positive",
        ),
        CheckConstraint(
            "min_advance_notice_days >= 0",
            name="ck_leave_types_notice_positive",
        ),
        UniqueConstraint("company_id", "code", name="uq_leave_types_code_per_company"),
        UniqueConstraint("company_id", "name", name="uq_leave_types_name_per_company"),
        Index("ix_leave_types_company_id", "company_id"),
        Index("ix_leave_types_active", "company_id", "is_active"),
    )

    # ── Identifiants ──────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )

    # ── Informations ──────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="Code court stable (CP, RTT, MAL...)"
    )
    color_hex: Mapped[str] = mapped_column(
        String(7), nullable=False, default="#6c757d",
        comment="Couleur d'affichage calendrier (format #RRGGBB)",
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Règles de demande ──────────────────────────────────────────────────────
    requires_justification: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="Un commentaire/motif est obligatoire à la demande",
    )
    requires_document: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="Un justificatif (PJ) est obligatoire (ex : arrêt maladie)",
    )
    max_consecutive_days: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="Limite de jours consécutifs (NULL = illimité)"
    )
    min_advance_notice_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Délai de prévenance minimum avant la date de début",
    )

    # ── Impact métier ──────────────────────────────────────────────────────────
    is_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    impacts_leave_balance: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        comment="True = décompte un solde (CP, RTT) ; False = n'en consomme pas (maladie)",
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    company: Mapped["Company"] = relationship(
        "Company", foreign_keys=[company_id], lazy="select"
    )

    # Définies dans leurs modules respectifs (back_populates="leave_type") :
    #   leave_balances  → app/models/leave_balance.py
    #   leave_requests  → app/models/leave_request.py

    # ── Codes standards (constantes pour seed/référence — non contraints en base) ──
    CODE_PAID_LEAVE      = "CP"
    CODE_RTT             = "RTT"
    CODE_SICK_LEAVE      = "MAL"
    CODE_PARENTAL_LEAVE  = "MAT"
    CODE_FAMILY_EVENT    = "EVF"
    CODE_UNPAID_LEAVE    = "CSS"
    CODE_TRAINING        = "FOR"
    CODE_REMOTE_WORK     = "TTW"

    # ── Validation SQLAlchemy ─────────────────────────────────────────────────
    @validates("name")
    def _strip_name(self, key: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Le nom du type d'absence ne peut pas être vide.")
        return value.strip()

    @validates("code")
    def _normalize_code(self, key: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Le code du type d'absence ne peut pas être vide.")
        return value.strip().upper()

    @validates("color_hex")
    def _validate_color(self, key: str, value: str) -> str:
        import re
        if not value or not re.match(r"^#[0-9A-Fa-f]{6}$", value):
            raise ValueError(
                f"Couleur invalide : '{value}'. Format attendu : #RRGGBB (ex: #28a745)."
            )
        return value.lower()

    @validates("max_consecutive_days")
    def _validate_max_days(self, key: str, value: Optional[int]) -> Optional[int]:
        if value is not None and value <= 0:
            raise ValueError("Le nombre maximum de jours consécutifs doit être positif.")
        return value

    @validates("min_advance_notice_days")
    def _validate_notice_days(self, key: str, value: int) -> int:
        if value < 0:
            raise ValueError("Le délai de prévenance ne peut pas être négatif.")
        return value

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def requires_approval_workflow(self) -> bool:
        """
        Indique si ce type d'absence suit le circuit d'approbation standard
        (manager → RH). Les types non rémunérés ou impactant le solde
        suivent systématiquement le workflow ; les autres restent flexibles
        au niveau du service applicatif.
        """
        return self.impacts_leave_balance or not self.is_paid

    @property
    def display_label(self) -> str:
        """Libellé compact pour badges/calendrier, ex : 'CP — Congés Payés'."""
        return f"{self.code} — {self.name}"

    # ── Méthodes d'instance ───────────────────────────────────────────────────
    def validate_duration(self, working_days: float) -> Optional[str]:
        """
        Vérifie qu'une durée demandée respecte la limite de jours consécutifs.
        Retourne un message d'erreur (str) si invalide, None si valide.
        Ne lève pas d'exception ici — laisse l'appelant (service) décider
        du type d'exception métier à propager.
        """
        if self.max_consecutive_days is not None and working_days > self.max_consecutive_days:
            return (
                f"Ce type d'absence est limité à {self.max_consecutive_days} "
                f"jour(s) consécutif(s) maximum."
            )
        return None

    def validate_advance_notice(self, days_until_start: int) -> Optional[str]:
        """
        Vérifie le respect du délai de prévenance minimum.
        Retourne un message d'erreur (str) si invalide, None si valide.
        """
        if days_until_start < self.min_advance_notice_days:
            return (
                f"Cette absence doit être demandée au moins "
                f"{self.min_advance_notice_days} jour(s) à l'avance."
            )
        return None

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_or_404(cls, leave_type_id: int) -> "LeaveType":
        leave_type = db.session.get(cls, leave_type_id)
        if leave_type is None:
            from flask import abort
            abort(404, description="Type d'absence introuvable.")
        return leave_type

    @classmethod
    def get_by_code(cls, company_id: int, code: str) -> Optional["LeaveType"]:
        return db.session.execute(
            db.select(cls).where(
                cls.company_id == company_id,
                cls.code == code.strip().upper(),
            )
        ).scalar_one_or_none()

    @classmethod
    def active_in_company(cls, company_id: int):
        """Requête (non exécutée) des types d'absence actifs d'une entreprise."""
        return db.select(cls).where(
            cls.company_id == company_id,
            cls.is_active.is_(True),
        ).order_by(cls.name)

    @classmethod
    def balance_impacting_in_company(cls, company_id: int):
        """Requête (non exécutée) des types impactant un solde (pour calculs RH)."""
        return db.select(cls).where(
            cls.company_id == company_id,
            cls.is_active.is_(True),
            cls.impacts_leave_balance.is_(True),
        ).order_by(cls.name)

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "company_id": self.company_id,
            "name": self.name,
            "code": self.code,
            "color_hex": self.color_hex,
            "description": self.description,
            "requires_justification": self.requires_justification,
            "requires_document": self.requires_document,
            "max_consecutive_days": self.max_consecutive_days,
            "min_advance_notice_days": self.min_advance_notice_days,
            "is_paid": self.is_paid,
            "impacts_leave_balance": self.impacts_leave_balance,
            "is_active": self.is_active,
            "display_label": self.display_label,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    # ── Dunder ────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return f"<LeaveType id={self.id} {self.code!r} ({self.name!r})>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, LeaveType) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)