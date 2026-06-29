"""
Modèles : Training · Enrollment
Formations et inscriptions — SQLAlchemy 2.0 (Mapped / mapped_column)

Training décrit un programme de formation disponible dans l'entreprise
(titre, organisme, durée, mode de diffusion, coût unitaire).

Enrollment représente l'inscription individuelle d'un employé à une
formation, avec son propre cycle de vie (planifiée → en cours → terminée
ou annulée) et son évaluation finale.

Relations principales :
  - company    (N:1, Training)    → entreprise propriétaire du catalogue
  - employee   (N:1, Enrollment)  → employé inscrit
  - training   (N:1, Enrollment)  → formation concernée
  - enrollments (1:N, Training)   → toutes les inscriptions à cette formation

Note : app/models/skill.py est un placeholder vide à ce jour.
Lorsqu'un modèle Skill sera implémenté, une relation M:N
Training ↔ Skill pourra être ajoutée via une table d'association.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
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
    from app.models.organization import Company


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================================
# Training
# =============================================================================

class Training(db.Model):
    """
    Programme de formation du catalogue RH.

    `training_type` précise le mode de diffusion :
        presentiel   — formation en salle avec un formateur présent
        distanciel   — classe virtuelle / webinaire synchrone
        e_learning   — parcours en ligne asynchrone (MOOC, LMS...)

    `duration_hours` stocke la durée en heures (décimales acceptées,
    ex : 3.5 pour 3h30). Nullable si la durée n'est pas encore fixée.

    `cost` représente le coût unitaire par participant (HT, en euros).
    Nullable si la formation est interne et non facturée.

    `is_active` permet de désactiver un programme sans le supprimer
    (masquage du catalogue sans perte d'historique des inscriptions).
    """

    __tablename__ = "trainings"
    __table_args__ = (
        CheckConstraint(
            "training_type IN ('presentiel','distanciel','e_learning')",
            name="ck_trainings_type_valid",
        ),
        CheckConstraint("duration_hours IS NULL OR duration_hours > 0",
                        name="ck_trainings_duration_positive"),
        CheckConstraint("cost IS NULL OR cost >= 0",
                        name="ck_trainings_cost_non_negative"),
        Index("ix_trainings_company_id", "company_id"),
        Index("ix_trainings_active", "company_id", "is_active"),
    )

    # ── Identifiants ──────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── Rattachement entreprise ───────────────────────────────────────────────
    company_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
        comment="NULL = formation partagée entre entreprises / catalogue global",
    )

    # ── Description de la formation ───────────────────────────────────────────
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    organisme: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True,
        comment="Nom de l'organisme ou du prestataire de formation",
    )
    duration_hours: Mapped[Optional[float]] = mapped_column(
        Numeric(6, 2), nullable=True,
        comment="Durée totale en heures (décimales acceptées)",
    )
    training_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="presentiel",
    )
    cost: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True,
        comment="Coût unitaire par participant en euros HT",
    )

    # ── Cycle de vie ──────────────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow,
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    company: Mapped[Optional["Company"]] = relationship(
        "Company", foreign_keys=[company_id], lazy="select",
    )
    enrollments: Mapped[List["Enrollment"]] = relationship(
        "Enrollment", back_populates="training", lazy="dynamic",
        cascade="all, delete-orphan",
    )

    # ── Validation ────────────────────────────────────────────────────────────
    VALID_TYPES = ("presentiel", "distanciel", "e_learning")

    @validates("training_type")
    def _validate_type(self, key: str, value: str) -> str:
        if value not in self.VALID_TYPES:
            raise ValueError(
                f"training_type invalide : {value!r}. "
                f"Valeurs acceptées : {self.VALID_TYPES}"
            )
        return value

    # ── Propriétés calculées ──────────────────────────────────────────────────
    @property
    def enrollment_count(self) -> int:
        """Nombre total d'inscriptions (tous statuts confondus)."""
        return self.enrollments.count()

    @property
    def active_enrollment_count(self) -> int:
        """Nombre d'inscriptions non annulées."""
        return self.enrollments.filter(
            Enrollment.status != Enrollment.STATUS_CANCELLED
        ).count()

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_or_404(cls, training_id: int) -> "Training":
        t = db.session.get(cls, training_id)
        if t is None:
            from flask import abort
            abort(404, description="Formation introuvable.")
        return t

    @classmethod
    def active_in_company(cls, company_id: int):
        """Requête (non exécutée) des formations actives d'une entreprise."""
        return (
            db.select(cls)
            .where(
                cls.is_active.is_(True),
                db.or_(cls.company_id == company_id, cls.company_id.is_(None)),
            )
            .order_by(cls.title)
        )

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "company_id": self.company_id,
            "title": self.title,
            "description": self.description,
            "organisme": self.organisme,
            "duration_hours": float(self.duration_hours) if self.duration_hours is not None else None,
            "training_type": self.training_type,
            "cost": float(self.cost) if self.cost is not None else None,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<Training id={self.id} title={self.title!r} type={self.training_type}>"


# =============================================================================
# Enrollment
# =============================================================================

class Enrollment(db.Model):
    """
    Inscription d'un employé à une formation.

    Cycle de vie du statut :
        planifiee  → en_cours  → terminee
                   ↘ annulee  (depuis tout statut antérieur à terminee)

    Un employé peut être inscrit plusieurs fois à la même formation
    (reprise après annulation, formation récurrente) — aucune contrainte
    d'unicité sur (employee_id, training_id).

    `score` stocke la note ou le pourcentage de réussite obtenu à l'issue
    de la formation (0-100). Nullable tant que la formation n'est pas terminée.

    `final_comment` permet au formateur ou au RH de consigner une appréciation
    qualitative complémentaire à la note.
    """

    __tablename__ = "enrollments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('planifiee','en_cours','terminee','annulee')",
            name="ck_enrollments_status_valid",
        ),
        CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="ck_enrollments_end_after_start",
        ),
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 100)",
            name="ck_enrollments_score_range",
        ),
        Index("ix_enrollments_employee_id", "employee_id"),
        Index("ix_enrollments_training_id", "training_id"),
        Index("ix_enrollments_status", "status"),
        Index("ix_enrollments_employee_status", "employee_id", "status"),
    )

    # ── Statuts ───────────────────────────────────────────────────────────────
    STATUS_PLANNED    = "planifiee"
    STATUS_IN_PROGRESS = "en_cours"
    STATUS_COMPLETED  = "terminee"
    STATUS_CANCELLED  = "annulee"

    STATUSES = (STATUS_PLANNED, STATUS_IN_PROGRESS, STATUS_COMPLETED, STATUS_CANCELLED)

    # ── Identifiants ──────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── Rattachements ─────────────────────────────────────────────────────────
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False,
    )
    training_id: Mapped[int] = mapped_column(
        ForeignKey("trainings.id", ondelete="CASCADE"), nullable=False,
    )

    # ── Cycle de vie ──────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=STATUS_PLANNED,
    )
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date:   Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # ── Évaluation finale ─────────────────────────────────────────────────────
    score: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 2), nullable=True,
        comment="Note finale sur 100",
    )
    final_comment: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Appréciation qualitative issue de la formation",
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow,
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    employee: Mapped["Employee"] = relationship(
        "Employee", foreign_keys=[employee_id], lazy="joined",
    )
    training: Mapped["Training"] = relationship(
        "Training", back_populates="enrollments", lazy="joined",
    )

    # ── Validation ────────────────────────────────────────────────────────────
    @validates("status")
    def _validate_status(self, key: str, value: str) -> str:
        if value not in self.STATUSES:
            raise ValueError(
                f"Statut d'inscription invalide : {value!r}. "
                f"Valeurs acceptées : {self.STATUSES}"
            )
        return value

    @validates("score")
    def _validate_score(self, key: str, value: Optional[float]) -> Optional[float]:
        if value is not None and not (0 <= float(value) <= 100):
            raise ValueError(f"Le score doit être compris entre 0 et 100 (reçu : {value}).")
        return value

    # ── Transitions de statut ─────────────────────────────────────────────────
    def start(self, start_date: Optional[date] = None) -> None:
        """Passe l'inscription en cours (planifiee → en_cours)."""
        if self.status != self.STATUS_PLANNED:
            raise ValueError(
                f"Impossible de démarrer une inscription au statut {self.status!r}."
            )
        self.status = self.STATUS_IN_PROGRESS
        if start_date:
            self.start_date = start_date

    def complete(
        self,
        end_date: Optional[date] = None,
        score: Optional[float] = None,
        comment: Optional[str] = None,
    ) -> None:
        """Marque la formation comme terminée (en_cours → terminee)."""
        if self.status != self.STATUS_IN_PROGRESS:
            raise ValueError(
                f"Impossible de terminer une inscription au statut {self.status!r}."
            )
        self.status = self.STATUS_COMPLETED
        if end_date:
            self.end_date = end_date
        if score is not None:
            self.score = score
        if comment:
            self.final_comment = comment

    def cancel(self) -> None:
        """Annule l'inscription (planifiee ou en_cours → annulee)."""
        if self.status == self.STATUS_COMPLETED:
            raise ValueError("Une inscription terminée ne peut pas être annulée.")
        self.status = self.STATUS_CANCELLED

    # ── Propriétés calculées ──────────────────────────────────────────────────
    @property
    def is_passed(self) -> Optional[bool]:
        """True si score >= 50, False si < 50, None si pas encore noté."""
        if self.score is None:
            return None
        return float(self.score) >= 50.0

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_or_404(cls, enrollment_id: int) -> "Enrollment":
        e = db.session.get(cls, enrollment_id)
        if e is None:
            from flask import abort
            abort(404, description="Inscription introuvable.")
        return e

    @classmethod
    def for_employee(cls, employee_id: int):
        """Requête (non exécutée) de toutes les inscriptions d'un employé."""
        return (
            db.select(cls)
            .where(cls.employee_id == employee_id)
            .order_by(cls.created_at.desc())
        )

    @classmethod
    def active_for_employee(cls, employee_id: int):
        """Inscriptions non annulées d'un employé."""
        return (
            db.select(cls)
            .where(
                cls.employee_id == employee_id,
                cls.status != cls.STATUS_CANCELLED,
            )
            .order_by(cls.start_date.desc().nullslast())
        )

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "employee_id": self.employee_id,
            "training_id": self.training_id,
            "training_title": self.training.title if self.training else None,
            "status": self.status,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "score": float(self.score) if self.score is not None else None,
            "final_comment": self.final_comment,
            "is_passed": self.is_passed,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return (
            f"<Enrollment id={self.id} "
            f"employee={self.employee_id} "
            f"training={self.training_id} "
            f"status={self.status!r}>"
        )
