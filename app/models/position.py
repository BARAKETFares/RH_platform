"""
Modèle : Position
Poste / Fonction — SQLAlchemy 2.0 (Mapped / mapped_column)

Représente un poste occupable au sein d'un département (ex : "Développeur
Backend Senior", "Responsable RH", "Comptable"). Un poste définit un
niveau hiérarchique et une fourchette de rémunération indicative,
utilisés pour le recrutement et la gestion de carrière.

Relations principales :
  - department (N:1) → département de rattachement
  - employees  (1:N) → employés occupant ce poste
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
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.extensions import db

if TYPE_CHECKING:
    from app.models.department import Department
    from app.models.employee import Employee


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Position(db.Model):
    """
    Poste / fonction rattaché à un département.

    Le niveau hiérarchique (`level`) suit une échelle standardisée
    permettant de comparer les postes entre eux (filtres RH, grilles
    salariales, plans de carrière). Plus la valeur est élevée, plus
    le poste est senior.

    La fourchette salariale (`min_salary` / `max_salary`) est indicative —
    utilisée pour le recrutement et les simulations budgétaires, pas
    comme contrainte stricte sur le salaire réel de l'employé.
    """

    __tablename__ = "positions"
    __table_args__ = (
        CheckConstraint(
            "min_salary IS NULL OR max_salary IS NULL OR min_salary <= max_salary",
            name="ck_positions_salary_range_valid",
        ),
        CheckConstraint(
            "level IS NULL OR level IN "
            "('junior','intermediate','senior','lead','manager','director','executive')",
            name="ck_positions_level_valid",
        ),
        UniqueConstraint("department_id", "title", name="uq_positions_title_per_department"),
        Index("ix_positions_department_id", "department_id"),
        Index("ix_positions_level", "level"),
    )

    # ── Niveaux hiérarchiques (constantes) ────────────────────────────────────
    LEVEL_JUNIOR       = "junior"
    LEVEL_INTERMEDIATE = "intermediate"
    LEVEL_SENIOR       = "senior"
    LEVEL_LEAD         = "lead"
    LEVEL_MANAGER      = "manager"
    LEVEL_DIRECTOR     = "director"
    LEVEL_EXECUTIVE    = "executive"

    LEVELS: tuple[str, ...] = (
        LEVEL_JUNIOR, LEVEL_INTERMEDIATE, LEVEL_SENIOR,
        LEVEL_LEAD, LEVEL_MANAGER, LEVEL_DIRECTOR, LEVEL_EXECUTIVE,
    )

    # Ordre numérique pour comparaison (plus la valeur est haute, plus senior)
    LEVEL_RANK: dict[str, int] = {
        LEVEL_JUNIOR:       1,
        LEVEL_INTERMEDIATE: 2,
        LEVEL_SENIOR:       3,
        LEVEL_LEAD:         4,
        LEVEL_MANAGER:      5,
        LEVEL_DIRECTOR:     6,
        LEVEL_EXECUTIVE:    7,
    }

    LEVEL_LABELS: dict[str, str] = {
        LEVEL_JUNIOR:       "Junior",
        LEVEL_INTERMEDIATE: "Intermédiaire",
        LEVEL_SENIOR:       "Senior",
        LEVEL_LEAD:         "Lead",
        LEVEL_MANAGER:      "Manager",
        LEVEL_DIRECTOR:     "Directeur",
        LEVEL_EXECUTIVE:    "Exécutif",
    }

    # ── Identifiants ──────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── Rattachement ──────────────────────────────────────────────────────────
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), nullable=False
    )

    # ── Informations ──────────────────────────────────────────────────────────
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    level: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True,
        comment="Niveau hiérarchique : junior, intermediate, senior, lead, manager, director, executive",
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Fourchette salariale indicative ────────────────────────────────────────
    min_salary: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    max_salary: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    department: Mapped["Department"] = relationship(
        "Department",
        foreign_keys=[department_id],
        lazy="joined",
    )

    # Employés occupant ce poste (back_populates côté Employee.position)
    employees: Mapped[List["Employee"]] = relationship(
        "Employee",
        foreign_keys="Employee.position_id",
        back_populates="position",
        lazy="dynamic",
    )

    # ── Validation SQLAlchemy ─────────────────────────────────────────────────
    @validates("title")
    def _strip_title(self, key: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("L'intitulé du poste ne peut pas être vide.")
        return value.strip()

    @validates("level")
    def _validate_level(self, key: str, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in self.LEVELS:
            raise ValueError(
                f"Niveau hiérarchique invalide : '{value}'. Valeurs acceptées : {self.LEVELS}"
            )
        return value

    @validates("max_salary")
    def _validate_salary_range(self, key: str, value: Optional[float]) -> Optional[float]:
        if value is not None and self.min_salary is not None and value < self.min_salary:
            raise ValueError("Le salaire maximum ne peut pas être inférieur au salaire minimum.")
        return value

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def level_label(self) -> str:
        """Libellé lisible du niveau hiérarchique (ex: 'Senior')."""
        return self.LEVEL_LABELS.get(self.level, "—") if self.level else "—"

    @property
    def level_rank(self) -> int:
        """Rang numérique du niveau (0 si non défini)."""
        return self.LEVEL_RANK.get(self.level, 0) if self.level else 0

    @property
    def salary_range_label(self) -> str:
        """Fourchette salariale formatée, ex : '35 000 € – 45 000 €'."""
        if self.min_salary is None and self.max_salary is None:
            return "Non définie"
        if self.min_salary is None:
            return f"Jusqu'à {self.max_salary:,.0f} €".replace(",", " ")
        if self.max_salary is None:
            return f"À partir de {self.min_salary:,.0f} €".replace(",", " ")
        return (
            f"{self.min_salary:,.0f} € – {self.max_salary:,.0f} €"
        ).replace(",", " ")

    @property
    def employee_count(self) -> int:
        """Nombre d'employés occupant actuellement ce poste."""
        return self.employees.count()

    @property
    def is_management_level(self) -> bool:
        """True si le poste est de niveau manager ou supérieur."""
        return self.level_rank >= self.LEVEL_RANK[self.LEVEL_MANAGER]

    # ── Méthodes d'instance ───────────────────────────────────────────────────
    def is_senior_to(self, other: "Position") -> bool:
        """Compare le niveau hiérarchique avec un autre poste."""
        return self.level_rank > other.level_rank

    def salary_in_range(self, salary: float) -> bool:
        """Vérifie si un salaire donné est dans la fourchette définie."""
        if self.min_salary is not None and salary < self.min_salary:
            return False
        if self.max_salary is not None and salary > self.max_salary:
            return False
        return True

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_or_404(cls, position_id: int) -> "Position":
        position = db.session.get(cls, position_id)
        if position is None:
            from flask import abort
            abort(404, description="Poste introuvable.")
        return position

    @classmethod
    def get_by_title(cls, department_id: int, title: str) -> Optional["Position"]:
        return db.session.execute(
            db.select(cls).where(
                cls.department_id == department_id,
                cls.title == title.strip(),
            )
        ).scalar_one_or_none()

    @classmethod
    def active_in_department(cls, department_id: int):
        """Requête (non exécutée) des postes actifs d'un département."""
        return db.select(cls).where(
            cls.department_id == department_id,
            cls.is_active.is_(True),
        ).order_by(cls.title)

    @classmethod
    def by_level(cls, department_id: int, level: str):
        """Requête (non exécutée) des postes d'un niveau donné dans un département."""
        return db.select(cls).where(
            cls.department_id == department_id,
            cls.level == level,
            cls.is_active.is_(True),
        ).order_by(cls.title)

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self, include_stats: bool = False) -> dict:
        data: dict = {
            "id":                 self.id,
            "department_id":      self.department_id,
            "department_name":    self.department.name if self.department else None,
            "title":              self.title,
            "level":              self.level,
            "level_label":        self.level_label,
            "level_rank":         self.level_rank,
            "description":        self.description,
            "min_salary":         float(self.min_salary) if self.min_salary else None,
            "max_salary":         float(self.max_salary) if self.max_salary else None,
            "salary_range_label": self.salary_range_label,
            "is_active":          self.is_active,
            "created_at":         self.created_at.isoformat(),
            "updated_at":         self.updated_at.isoformat(),
        }
        if include_stats:
            data["employee_count"] = self.employee_count
        return data

    # ── Dunder ────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return f"<Position id={self.id} {self.title!r} [{self.level or 'no-level'}]>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Position) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)