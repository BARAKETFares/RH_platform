"""
Modèle : LeaveRequest
Demande d'absence — SQLAlchemy 2.0 (Mapped / mapped_column)

Représente une demande d'absence soumise par un employé, suivant un circuit
d'approbation à deux niveaux (Manager → RH) configurable selon le type
d'absence. Le cycle de vie complet est tracé : soumission, décisions,
annulation, avec horodatage et commentaire à chaque étape.

Machine à états (champ `status`) :

    draft ──► pending_manager ──► pending_hr ──► approved
                    │                  │
                    ▼                  ▼
                rejected           rejected
                    │                  │
                    └──────┬───────────┘
                           ▼
                       cancelled (depuis n'importe quel état non terminal)

Relations principales :
  - employee     (N:1) → demandeur
  - leave_type   (N:1) → type d'absence demandé
  - manager      (N:1, optionnelle) → approbateur niveau 1 (Employee)
  - hr_validator (N:1, optionnelle) → approbateur niveau 2 (User, rôle RH/Admin)
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.extensions import db

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.leave_type import LeaveType
    from app.models.user import User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LeaveRequest(db.Model):
    """
    Demande d'absence d'un employé.

    Le champ `working_days` est calculé applicativement (jours ouvrés hors
    week-ends et jours fériés, en tenant compte des demi-journées de début/fin)
    et stocké pour éviter de recalculer à chaque lecture — il est recalculé
    et mis à jour à chaque modification des dates par le service métier.

    La distinction `manager_*` / `hr_*` permet de tracer indépendamment
    chaque étape du circuit d'approbation, même si le workflow exact
    (un ou deux niveaux requis) dépend de la configuration du LeaveType
    et de la politique de l'entreprise, gérée au niveau service.
    """

    __tablename__ = "leave_requests"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_leave_requests_end_after_start"),
        CheckConstraint(
            "working_days IS NULL OR working_days > 0",
            name="ck_leave_requests_working_days_positive",
        ),
        CheckConstraint(
            "status IN ('draft','pending_manager','pending_hr','approved','rejected','cancelled')",
            name="ck_leave_requests_status_valid",
        ),
        CheckConstraint(
            "manager_decision_at IS NULL OR manager_id IS NOT NULL",
            name="ck_leave_requests_manager_decision_requires_manager",
        ),
        Index("ix_leave_requests_employee_id", "employee_id"),
        Index("ix_leave_requests_leave_type_id", "leave_type_id"),
        Index("ix_leave_requests_status", "status"),
        Index("ix_leave_requests_manager_id", "manager_id"),
        Index("ix_leave_requests_date_range", "employee_id", "start_date", "end_date"),
        Index("ix_leave_requests_pending", "manager_id", "status"),
    )

    # ── Statuts (constantes) ──────────────────────────────────────────────────
    STATUS_DRAFT           = "draft"
    STATUS_PENDING_MANAGER = "pending_manager"
    STATUS_PENDING_HR      = "pending_hr"
    STATUS_APPROVED        = "approved"
    STATUS_REJECTED        = "rejected"
    STATUS_CANCELLED       = "cancelled"

    STATUSES: tuple[str, ...] = (
        STATUS_DRAFT, STATUS_PENDING_MANAGER, STATUS_PENDING_HR,
        STATUS_APPROVED, STATUS_REJECTED, STATUS_CANCELLED,
    )

    # États depuis lesquels une annulation est possible
    CANCELLABLE_STATUSES: tuple[str, ...] = (
        STATUS_DRAFT, STATUS_PENDING_MANAGER, STATUS_PENDING_HR, STATUS_APPROVED,
    )

    # États considérés comme "en attente d'action" (dashboard d'approbation)
    PENDING_STATUSES: tuple[str, ...] = (STATUS_PENDING_MANAGER, STATUS_PENDING_HR)

    # États terminaux (plus aucune transition possible)
    TERMINAL_STATUSES: tuple[str, ...] = (STATUS_APPROVED, STATUS_REJECTED, STATUS_CANCELLED)

    # ── Identifiants ──────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── Rattachements ─────────────────────────────────────────────────────────
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    leave_type_id: Mapped[int] = mapped_column(
        ForeignKey("leave_types.id", ondelete="RESTRICT"), nullable=False
    )

    # ── Période demandée ──────────────────────────────────────────────────────
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_half_day: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="Demi-journée le jour de début"
    )
    end_half_day: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="Demi-journée le jour de fin"
    )
    working_days: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 2), nullable=True,
        comment="Jours ouvrés calculés (hors week-ends/fériés) — recalculé par le service",
    )

    # ── Contenu de la demande ─────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_DRAFT)
    employee_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    document_path: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True, comment="Justificatif joint (arrêt maladie, etc.)"
    )
    is_emergency: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Approbation niveau 1 — Manager ────────────────────────────────────────
    manager_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    manager_decision_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    manager_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Approbation niveau 2 — RH ──────────────────────────────────────────────
    hr_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    hr_decision_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    hr_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Annulation ────────────────────────────────────────────────────────────
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancellation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    employee: Mapped["Employee"] = relationship(
        "Employee", foreign_keys=[employee_id], lazy="joined"
    )
    leave_type: Mapped["LeaveType"] = relationship(
        "LeaveType", foreign_keys=[leave_type_id], lazy="joined"
    )
    manager: Mapped[Optional["Employee"]] = relationship(
        "Employee", foreign_keys=[manager_id], lazy="joined"
    )
    hr_validator: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[hr_user_id], lazy="select"
    )

    # ── Validation SQLAlchemy ─────────────────────────────────────────────────
    @validates("status")
    def _validate_status(self, key: str, value: str) -> str:
        if value not in self.STATUSES:
            raise ValueError(f"Statut invalide : '{value}'. Valeurs acceptées : {self.STATUSES}")
        return value

    @validates("end_date")
    def _validate_end_after_start(self, key: str, value: date) -> date:
        if self.start_date is not None and value < self.start_date:
            raise ValueError("La date de fin ne peut pas précéder la date de début.")
        return value

    @validates("working_days")
    def _validate_working_days(self, key: str, value: Optional[float]) -> Optional[float]:
        if value is not None and value <= 0:
            raise ValueError("Le nombre de jours ouvrés doit être strictement positif.")
        return value

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def is_pending(self) -> bool:
        return self.status in self.PENDING_STATUSES

    @property
    def is_approved(self) -> bool:
        return self.status == self.STATUS_APPROVED

    @property
    def is_rejected(self) -> bool:
        return self.status == self.STATUS_REJECTED

    @property
    def is_cancelled(self) -> bool:
        return self.status == self.STATUS_CANCELLED

    @property
    def is_terminal(self) -> bool:
        return self.status in self.TERMINAL_STATUSES

    @property
    def is_cancellable(self) -> bool:
        return self.status in self.CANCELLABLE_STATUSES

    @property
    def calendar_days(self) -> int:
        """Nombre de jours calendaires bruts (incluant week-ends) entre les deux dates."""
        return (self.end_date - self.start_date).days + 1

    @property
    def requires_document(self) -> bool:
        """Délègue au type d'absence : ce type exige-t-il un justificatif ?"""
        return self.leave_type.requires_document if self.leave_type else False

    @property
    def has_document(self) -> bool:
        return self.document_path is not None

    @property
    def waiting_for(self) -> Optional[str]:
        """Indique qui doit agir actuellement : 'manager', 'hr', ou None."""
        if self.status == self.STATUS_PENDING_MANAGER:
            return "manager"
        if self.status == self.STATUS_PENDING_HR:
            return "hr"
        return None

    # ── Méthodes d'instance — transitions de la machine à états ──────────────
    def submit(self) -> None:
        """Soumet la demande (draft → pending_manager)."""
        if self.status != self.STATUS_DRAFT:
            raise ValueError(f"Impossible de soumettre une demande au statut '{self.status}'.")
        self.status = self.STATUS_PENDING_MANAGER

    def approve_by_manager(self, manager_id: int, comment: Optional[str] = None,
                            requires_hr_validation: bool = True) -> None:
        """
        Approuve la demande au niveau manager.
        Passe en 'pending_hr' si une validation RH est requise,
        sinon directement en 'approved'.
        """
        if self.status != self.STATUS_PENDING_MANAGER:
            raise ValueError(
                f"Impossible d'approuver (niveau manager) une demande au statut '{self.status}'."
            )
        self.manager_id = manager_id
        self.manager_decision_at = _utcnow()
        self.manager_comment = comment
        self.status = self.STATUS_PENDING_HR if requires_hr_validation else self.STATUS_APPROVED

    def reject_by_manager(self, manager_id: int, comment: Optional[str] = None) -> None:
        """Rejette la demande au niveau manager."""
        if self.status != self.STATUS_PENDING_MANAGER:
            raise ValueError(
                f"Impossible de refuser (niveau manager) une demande au statut '{self.status}'."
            )
        self.manager_id = manager_id
        self.manager_decision_at = _utcnow()
        self.manager_comment = comment
        self.status = self.STATUS_REJECTED

    def approve_by_hr(self, hr_user_id: int, comment: Optional[str] = None) -> None:
        """Approuve définitivement la demande au niveau RH."""
        if self.status != self.STATUS_PENDING_HR:
            raise ValueError(
                f"Impossible d'approuver (niveau RH) une demande au statut '{self.status}'."
            )
        self.hr_user_id = hr_user_id
        self.hr_decision_at = _utcnow()
        self.hr_comment = comment
        self.status = self.STATUS_APPROVED

    def reject_by_hr(self, hr_user_id: int, comment: Optional[str] = None) -> None:
        """Rejette la demande au niveau RH."""
        if self.status != self.STATUS_PENDING_HR:
            raise ValueError(
                f"Impossible de refuser (niveau RH) une demande au statut '{self.status}'."
            )
        self.hr_user_id = hr_user_id
        self.hr_decision_at = _utcnow()
        self.hr_comment = comment
        self.status = self.STATUS_REJECTED

    def cancel(self, reason: Optional[str] = None) -> None:
        """Annule la demande, quel que soit l'état non terminal."""
        if not self.is_cancellable:
            raise ValueError(f"Impossible d'annuler une demande au statut '{self.status}'.")
        self.cancelled_at = _utcnow()
        self.cancellation_reason = reason
        self.status = self.STATUS_CANCELLED

    def overlaps_with(self, other_start: date, other_end: date) -> bool:
        """Vérifie si cette demande chevauche une autre période donnée."""
        return self.start_date <= other_end and self.end_date >= other_start

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_or_404(cls, request_id: int) -> "LeaveRequest":
        request = db.session.get(cls, request_id)
        if request is None:
            from flask import abort
            abort(404, description="Demande d'absence introuvable.")
        return request

    @classmethod
    def for_employee(cls, employee_id: int):
        """Requête (non exécutée) de toutes les demandes d'un employé."""
        return db.select(cls).where(
            cls.employee_id == employee_id
        ).order_by(cls.start_date.desc())

    @classmethod
    def pending_for_manager(cls, manager_id: int):
        """Requête (non exécutée) des demandes en attente d'action pour un manager."""
        return db.select(cls).where(
            cls.manager_id == manager_id,
            cls.status == cls.STATUS_PENDING_MANAGER,
        ).order_by(cls.created_at.asc())

    @classmethod
    def pending_for_hr(cls):
        """Requête (non exécutée) des demandes en attente de validation RH."""
        return db.select(cls).where(
            cls.status == cls.STATUS_PENDING_HR
        ).order_by(cls.created_at.asc())

    @classmethod
    def overlapping_for_employee(cls, employee_id: int, start: date, end: date,
                                   exclude_id: Optional[int] = None):
        """
        Requête (non exécutée) des demandes actives (non rejetées/annulées)
        d'un employé qui chevauchent la période donnée — utilisée pour
        détecter les doublons avant soumission.
        """
        query = db.select(cls).where(
            cls.employee_id == employee_id,
            cls.status.notin_((cls.STATUS_REJECTED, cls.STATUS_CANCELLED)),
            cls.start_date <= end,
            cls.end_date >= start,
        )
        if exclude_id is not None:
            query = query.where(cls.id != exclude_id)
        return query

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "employee_id": self.employee_id,
            "employee_name": self.employee.full_name if self.employee else None,
            "leave_type_id": self.leave_type_id,
            "leave_type_name": self.leave_type.name if self.leave_type else None,
            "leave_type_code": self.leave_type.code if self.leave_type else None,
            "leave_type_color": self.leave_type.color_hex if self.leave_type else None,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "start_half_day": self.start_half_day,
            "end_half_day": self.end_half_day,
            "working_days": float(self.working_days) if self.working_days else None,
            "calendar_days": self.calendar_days,
            "status": self.status,
            "waiting_for": self.waiting_for,
            "employee_comment": self.employee_comment,
            "document_path": self.document_path,
            "is_emergency": self.is_emergency,
            "manager_id": self.manager_id,
            "manager_name": self.manager.full_name if self.manager else None,
            "manager_decision_at": self.manager_decision_at.isoformat() if self.manager_decision_at else None,
            "manager_comment": self.manager_comment,
            "hr_user_id": self.hr_user_id,
            "hr_decision_at": self.hr_decision_at.isoformat() if self.hr_decision_at else None,
            "hr_comment": self.hr_comment,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "cancellation_reason": self.cancellation_reason,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    # ── Dunder ────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return (
            f"<LeaveRequest id={self.id} employee={self.employee_id} "
            f"{self.start_date}→{self.end_date} [{self.status}]>"
        )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, LeaveRequest) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)