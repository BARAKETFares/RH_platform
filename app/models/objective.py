"""
Modèle : Objective
Objectif individuel — SQLAlchemy 2.0 (Mapped / mapped_column)

Représente un objectif assigné à un employé (logique SMART), pouvant être
rattaché à une campagne d'évaluation ou défini librement par un manager
en dehors de tout cycle formel. Sert de base aux entretiens d'évaluation
(cf. evaluation.py).

`set_by_id` référence l'Employee qui a fixé l'objectif (généralement le
manager), distinct de l'employé concerné — permet de tracer qui a défini
quoi, indépendamment du lien hiérarchique courant (qui peut changer dans
le temps alors que l'objectif reste historique).

Relations principales :
  - employee   (N:1) → employé concerné par l'objectif
  - set_by     (N:1) → employé ayant fixé l'objectif (généralement le manager)
  - campaign   (N:1, optionnelle) → campagne d'évaluation de rattachement
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.extensions import db

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.evaluation import EvaluationCampaign


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Objective(db.Model):
    """
    Objectif individuel assigné à un employé.

    Le double système de notation (manager_rating / employee_rating) permet
    de comparer l'auto-évaluation de l'employé avec celle de son manager —
    un écart significatif entre les deux est souvent le point de départ
    d'une discussion lors de l'entretien.

    `completion_pct` est saisi manuellement (pas calculé automatiquement),
    car le degré d'avancement d'un objectif qualitatif n'est pas toujours
    déductible d'une formule — c'est une estimation humaine assumée.
    """

    __tablename__ = "objectives"
    __table_args__ = (
        CheckConstraint("weight > 0 AND weight <= 100", name="ck_objectives_weight_valid"),
        CheckConstraint(
            "completion_pct BETWEEN 0 AND 100",
            name="ck_objectives_completion_valid",
        ),
        CheckConstraint(
            "manager_rating IS NULL OR manager_rating BETWEEN 1 AND 5",
            name="ck_objectives_manager_rating_valid",
        ),
        CheckConstraint(
            "employee_rating IS NULL OR employee_rating BETWEEN 1 AND 5",
            name="ck_objectives_employee_rating_valid",
        ),
        CheckConstraint(
            "status IN ('draft','active','completed','cancelled','overdue')",
            name="ck_objectives_status_valid",
        ),
        CheckConstraint("employee_id <> set_by_id", name="ck_objectives_employee_differs_setter"),
        Index("ix_objectives_employee_id", "employee_id"),
        Index("ix_objectives_campaign_id", "campaign_id"),
        Index("ix_objectives_status", "status"),
        Index("ix_objectives_due_date", "due_date"),
    )

    # ── Statuts (constantes) ──────────────────────────────────────────────────
    STATUS_DRAFT     = "draft"
    STATUS_ACTIVE    = "active"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_OVERDUE   = "overdue"

    STATUSES: tuple[str, ...] = (
        STATUS_DRAFT, STATUS_ACTIVE, STATUS_COMPLETED, STATUS_CANCELLED, STATUS_OVERDUE,
    )

    ACTIVE_STATUSES: tuple[str, ...] = (STATUS_ACTIVE, STATUS_OVERDUE)

    # ── Identifiants ──────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── Rattachements ─────────────────────────────────────────────────────────
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("evaluation_campaigns.id", ondelete="SET NULL"), nullable=True
    )
    set_by_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False
    )

    # ── Contenu de l'objectif ─────────────────────────────────────────────────
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    success_criteria: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Critères mesurables de réussite (logique SMART)"
    )
    weight: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=100,
        comment="Pondération de l'objectif dans l'évaluation globale (%)",
    )
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # ── Suivi ─────────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_DRAFT)
    completion_pct: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    # ── Évaluation de l'objectif ───────────────────────────────────────────────
    manager_rating: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    employee_rating: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    manager_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    employee_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

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
    set_by: Mapped["Employee"] = relationship(
        "Employee", foreign_keys=[set_by_id], lazy="joined"
    )
    campaign: Mapped[Optional["EvaluationCampaign"]] = relationship(
        "EvaluationCampaign", back_populates="objectives", lazy="select"
    )

    # ── Validation SQLAlchemy ─────────────────────────────────────────────────
    @validates("title")
    def _strip_title(self, key: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Le titre de l'objectif ne peut pas être vide.")
        return value.strip()

    @validates("status")
    def _validate_status(self, key: str, value: str) -> str:
        if value not in self.STATUSES:
            raise ValueError(f"Statut invalide : '{value}'. Valeurs acceptées : {self.STATUSES}")
        return value

    @validates("completion_pct")
    def _validate_completion(self, key: str, value: int) -> int:
        if not (0 <= value <= 100):
            raise ValueError("La progression doit être comprise entre 0 et 100.")
        return value

    @validates("manager_rating", "employee_rating")
    def _validate_rating(self, key: str, value: Optional[int]) -> Optional[int]:
        if value is not None and not (1 <= value <= 5):
            raise ValueError(f"La note '{key}' doit être comprise entre 1 et 5.")
        return value

    @validates("weight")
    def _validate_weight(self, key: str, value: float) -> float:
        if not (0 < value <= 100):
            raise ValueError("La pondération doit être comprise entre 0 et 100.")
        return value

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def is_overdue(self) -> bool:
        """True si la date d'échéance est dépassée et l'objectif non terminé."""
        if self.due_date is None or self.status in (self.STATUS_COMPLETED, self.STATUS_CANCELLED):
            return False
        return self.due_date < date.today()

    @property
    def days_until_due(self) -> Optional[int]:
        if self.due_date is None:
            return None
        return (self.due_date - date.today()).days

    @property
    def rating_gap(self) -> Optional[int]:
        """
        Écart entre l'auto-évaluation et la note manager.
        Positif = l'employé se note plus sévèrement que le manager (rare).
        Négatif = l'employé se surestime par rapport au manager.
        None si l'une des deux notes manque.
        """
        if self.manager_rating is None or self.employee_rating is None:
            return None
        return self.employee_rating - self.manager_rating

    @property
    def has_rating_discrepancy(self) -> bool:
        """True si l'écart de notation est significatif (>= 2 points)."""
        gap = self.rating_gap
        return gap is not None and abs(gap) >= 2

    @property
    def is_self_assessed(self) -> bool:
        return self.employee_rating is not None

    @property
    def is_manager_assessed(self) -> bool:
        return self.manager_rating is not None

    # ── Méthodes d'instance ───────────────────────────────────────────────────
    def activate(self) -> None:
        if self.status != self.STATUS_DRAFT:
            raise ValueError(f"Impossible d'activer un objectif au statut '{self.status}'.")
        self.status = self.STATUS_ACTIVE

    def complete(self, completion_pct: int = 100) -> None:
        if self.status not in self.ACTIVE_STATUSES:
            raise ValueError(f"Impossible de terminer un objectif au statut '{self.status}'.")
        self.status = self.STATUS_COMPLETED
        self.completion_pct = completion_pct

    def cancel(self) -> None:
        if self.status == self.STATUS_COMPLETED:
            raise ValueError("Impossible d'annuler un objectif déjà terminé.")
        self.status = self.STATUS_CANCELLED

    def refresh_overdue_status(self) -> None:
        """
        Met à jour le statut vers 'overdue' si la date d'échéance est dépassée.
        Appelé typiquement par une tâche planifiée (cf. hr_tasks.py), pas
        au moment de la lecture, pour éviter des écritures en cascade
        à chaque consultation.
        """
        if self.status == self.STATUS_ACTIVE and self.due_date and self.due_date < date.today():
            self.status = self.STATUS_OVERDUE

    def submit_manager_rating(self, rating: int, comment: Optional[str] = None) -> None:
        self.manager_rating = rating
        if comment is not None:
            self.manager_comment = comment

    def submit_employee_rating(self, rating: int, comment: Optional[str] = None) -> None:
        self.employee_rating = rating
        if comment is not None:
            self.employee_comment = comment

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_or_404(cls, objective_id: int) -> "Objective":
        objective = db.session.get(cls, objective_id)
        if objective is None:
            from flask import abort
            abort(404, description="Objectif introuvable.")
        return objective

    @classmethod
    def for_employee(cls, employee_id: int, *, campaign_id: Optional[int] = None):
        """Requête (non exécutée) des objectifs d'un employé, filtrable par campagne."""
        query = db.select(cls).where(cls.employee_id == employee_id)
        if campaign_id is not None:
            query = query.where(cls.campaign_id == campaign_id)
        return query.order_by(cls.due_date.asc().nullslast())

    @classmethod
    def active_for_employee(cls, employee_id: int):
        """Requête (non exécutée) des objectifs actifs (en cours ou en retard)."""
        return db.select(cls).where(
            cls.employee_id == employee_id,
            cls.status.in_(cls.ACTIVE_STATUSES),
        ).order_by(cls.due_date.asc().nullslast())

    @classmethod
    def active_set_by(cls, manager_id: int):
        """Requête (non exécutée) des objectifs actifs fixés PAR ce manager pour son équipe."""
        return db.select(cls).where(
            cls.set_by_id == manager_id,
            cls.status.in_(cls.ACTIVE_STATUSES),
        ).order_by(cls.employee_id.asc(), cls.due_date.asc().nullslast())

    @classmethod
    def overdue_objectives(cls, company_id: Optional[int] = None):
        """
        Requête (non exécutée) de tous les objectifs en retard non clôturés —
        utilisée pour les alertes RH/manager.
        """
        from app.models.employee import Employee
        query = db.select(cls).join(Employee, cls.employee_id == Employee.id).where(
            cls.status == cls.STATUS_ACTIVE,
            cls.due_date.isnot(None),
            cls.due_date < date.today(),
        )
        if company_id is not None:
            query = query.where(Employee.company_id == company_id)
        return query

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "employee_id": self.employee_id,
            "employee_name": self.employee.full_name if self.employee else None,
            "campaign_id": self.campaign_id,
            "set_by_id": self.set_by_id,
            "set_by_name": self.set_by.full_name if self.set_by else None,
            "title": self.title,
            "description": self.description,
            "success_criteria": self.success_criteria,
            "weight": float(self.weight),
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "days_until_due": self.days_until_due,
            "is_overdue": self.is_overdue,
            "status": self.status,
            "completion_pct": self.completion_pct,
            "manager_rating": self.manager_rating,
            "employee_rating": self.employee_rating,
            "rating_gap": self.rating_gap,
            "has_rating_discrepancy": self.has_rating_discrepancy,
            "manager_comment": self.manager_comment,
            "employee_comment": self.employee_comment,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    # ── Dunder ────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return f"<Objective id={self.id} {self.title!r} [{self.status}] {self.completion_pct}%>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Objective) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)