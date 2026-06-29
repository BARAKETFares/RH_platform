"""
Modèle : LeaveBalance
Solde de congés annuel par employé et par type — SQLAlchemy 2.0

Représente le solde de congés d'un employé pour un type d'absence donné
sur une année civile. Le solde est décomposé en plusieurs compteurs pour
assurer la traçabilité complète (acquisition, report, ajustement manuel,
consommation) plutôt qu'une simple valeur agrégée.

Formules de calcul (exposées en propriétés Python — non stockées) :
    remaining  = initial_balance + carried_over + acquired + adjustment - taken
    available  = remaining - pending

Relations principales :
  - employee   (N:1) → employé concerné
  - leave_type (N:1) → type d'absence concerné
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.extensions import db

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.leave_type import LeaveType


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LeaveBalance(db.Model):
    """
    Solde de congés d'un employé pour un type d'absence, sur une année donnée.

    Un seul enregistrement existe par triplet (employee_id, leave_type_id, year)
    — contrainte d'unicité imposée en base. Le solde se calcule en couches :

        initial_balance  — droits attribués au 1er janvier (selon contrat)
        carried_over      — jours reportés de l'année précédente (report légal/conventionnel)
        acquired           — jours acquis progressivement dans l'année (calcul mensuel Celery)
        adjustment          — corrections manuelles RH (régularisation, erreur de saisie)
        taken                — jours effectivement pris (demandes approuvées)
        pending               — jours en attente d'approbation (réservés, pas encore décomptés)

    Cette décomposition permet d'auditer précisément l'origine de chaque
    variation du solde, plutôt que de ne stocker qu'un solde final opaque.
    """

    __tablename__ = "leave_balances"
    __table_args__ = (
        CheckConstraint("year BETWEEN 2000 AND 2100", name="ck_leave_balances_year_valid"),
        CheckConstraint("initial_balance >= 0", name="ck_leave_balances_initial_positive"),
        CheckConstraint("carried_over >= 0", name="ck_leave_balances_carried_positive"),
        CheckConstraint("acquired >= 0", name="ck_leave_balances_acquired_positive"),
        CheckConstraint("taken >= 0", name="ck_leave_balances_taken_positive"),
        CheckConstraint("pending >= 0", name="ck_leave_balances_pending_positive"),
        UniqueConstraint(
            "employee_id", "leave_type_id", "year",
            name="uq_leave_balances_employee_type_year",
        ),
        Index("ix_leave_balances_employee_id", "employee_id"),
        Index("ix_leave_balances_leave_type_id", "leave_type_id"),
        Index("ix_leave_balances_employee_year", "employee_id", "year"),
    )

    # ── Identifiants ──────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── Rattachements ─────────────────────────────────────────────────────────
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    leave_type_id: Mapped[int] = mapped_column(
        ForeignKey("leave_types.id", ondelete="CASCADE"), nullable=False
    )

    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # ── Compteurs (en jours, valeurs décimales pour demi-journées) ───────────
    initial_balance: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    carried_over: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    acquired: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    taken: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    pending: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    adjustment: Mapped[float] = mapped_column(
        Numeric(6, 2), nullable=False, default=0,
        comment="Correction manuelle RH — peut être négative",
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
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

    # ── Validation SQLAlchemy ─────────────────────────────────────────────────
    @validates("year")
    def _validate_year(self, key: str, value: int) -> int:
        if not (2000 <= value <= 2100):
            raise ValueError(f"Année invalide : {value}. Doit être comprise entre 2000 et 2100.")
        return value

    @validates("initial_balance", "carried_over", "acquired", "taken", "pending")
    def _validate_non_negative(self, key: str, value: float) -> float:
        if value is not None and value < 0:
            raise ValueError(f"Le champ '{key}' ne peut pas être négatif.")
        return value

    # ── Propriétés calculées ──────────────────────────────────────────────────
    @property
    def remaining(self) -> float:
        """
        Solde restant total : droits acquis moins jours pris.
        N'inclut pas les jours en attente (cf. `available`).
        """
        return float(
            self.initial_balance + self.carried_over + self.acquired
            + self.adjustment - self.taken
        )

    @property
    def available(self) -> float:
        """
        Solde réellement disponible pour une nouvelle demande :
        solde restant diminué des jours déjà réservés (en attente d'approbation).
        C'est cette valeur qui doit être utilisée pour valider une nouvelle
        demande d'absence.
        """
        return self.remaining - float(self.pending)

    @property
    def total_acquired(self) -> float:
        """Total des droits acquis dans l'année, hors prise et ajustement."""
        return float(self.initial_balance + self.carried_over + self.acquired)

    @property
    def usage_rate_pct(self) -> float:
        """Taux d'utilisation du solde en pourcentage (0-100+)."""
        total = self.total_acquired
        if total <= 0:
            return 0.0
        return round((float(self.taken) / total) * 100, 1)

    @property
    def has_sufficient_balance(self) -> bool:
        """True si le solde disponible est positif (au moins 0)."""
        return self.available >= 0

    # ── Méthodes d'instance ───────────────────────────────────────────────────
    def can_take(self, days: float) -> bool:
        """Vérifie si un nombre de jours donné peut être pris sans dépasser le solde disponible."""
        return self.available >= days

    def reserve(self, days: float) -> None:
        """
        Réserve des jours (passage en attente d'approbation).
        Ne vérifie pas la disponibilité — cette validation métier est de
        la responsabilité du service appelant (absence_service).
        """
        self.pending = float(self.pending) + days

    def release_reservation(self, days: float) -> None:
        """Libère une réservation (annulation ou refus de la demande)."""
        self.pending = max(0.0, float(self.pending) - days)

    def consume(self, days: float, from_pending: bool = True) -> None:
        """
        Consomme des jours du solde (demande approuvée).
        Si from_pending=True, retire aussi le montant correspondant de `pending`
        (cas standard : la demande était réservée avant approbation).
        """
        self.taken = float(self.taken) + days
        if from_pending:
            self.pending = max(0.0, float(self.pending) - days)

    def restore(self, days: float) -> None:
        """Restitue des jours consommés (annulation d'une absence déjà approuvée)."""
        self.taken = max(0.0, float(self.taken) - days)

    def apply_adjustment(self, days: float, reason: Optional[str] = None) -> None:
        """
        Applique un ajustement manuel RH (régularisation positive ou négative).
        Le motif n'est pas stocké ici — il doit être tracé via le journal
        d'audit (AuditLog) par le service appelant.
        """
        self.adjustment = float(self.adjustment) + days

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_or_404(cls, balance_id: int) -> "LeaveBalance":
        balance = db.session.get(cls, balance_id)
        if balance is None:
            from flask import abort
            abort(404, description="Solde de congés introuvable.")
        return balance

    @classmethod
    def get_for_employee(
        cls, employee_id: int, leave_type_id: int, year: int
    ) -> Optional["LeaveBalance"]:
        """Récupère le solde d'un employé pour un type et une année donnés."""
        return db.session.execute(
            db.select(cls).where(
                cls.employee_id == employee_id,
                cls.leave_type_id == leave_type_id,
                cls.year == year,
            )
        ).scalar_one_or_none()

    @classmethod
    def get_or_create(
        cls, employee_id: int, leave_type_id: int, year: int
    ) -> "LeaveBalance":
        """
        Récupère le solde existant ou en crée un nouveau (initialisé à zéro)
        si aucun n'existe encore pour ce triplet employé/type/année.
        Ne fait pas de commit — à la charge de l'appelant.
        """
        balance = cls.get_for_employee(employee_id, leave_type_id, year)
        if balance is None:
            balance = cls(
                employee_id=employee_id,
                leave_type_id=leave_type_id,
                year=year,
                initial_balance=0,
                carried_over=0,
                acquired=0,
                taken=0,
                pending=0,
                adjustment=0,
            )
            db.session.add(balance)
        return balance

    @classmethod
    def for_employee_year(cls, employee_id: int, year: int):
        """Requête (non exécutée) de tous les soldes d'un employé pour une année."""
        return db.select(cls).where(
            cls.employee_id == employee_id,
            cls.year == year,
        )

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "employee_id": self.employee_id,
            "leave_type_id": self.leave_type_id,
            "leave_type_code": self.leave_type.code if self.leave_type else None,
            "leave_type_name": self.leave_type.name if self.leave_type else None,
            "leave_type_color": self.leave_type.color_hex if self.leave_type else None,
            "year": self.year,
            "initial_balance": float(self.initial_balance),
            "carried_over": float(self.carried_over),
            "acquired": float(self.acquired),
            "taken": float(self.taken),
            "pending": float(self.pending),
            "adjustment": float(self.adjustment),
            "remaining": self.remaining,
            "available": self.available,
            "usage_rate_pct": self.usage_rate_pct,
            "updated_at": self.updated_at.isoformat(),
        }

    # ── Dunder ────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return (
            f"<LeaveBalance employee={self.employee_id} "
            f"type={self.leave_type_id} year={self.year} available={self.available}>"
        )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, LeaveBalance) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)