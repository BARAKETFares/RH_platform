"""
Modèle : Department
Service / Département — SQLAlchemy 2.0 (Mapped / mapped_column)

Représente une unité organisationnelle de l'entreprise (service, équipe,
direction). Structure arborescente via auto-référence (parent_id) pour
modéliser des départements imbriqués (ex: "Direction Technique" >
"Équipe Backend" > "Squad Paiement").

Relations principales :
  - company      (N:1) → entreprise de rattachement
  - parent       (N:1, self-referential) → département parent
  - children     (1:N, self-referential) → sous-départements
  - manager      (N:1) → Employee responsable du département
  - employees    (1:N) → collaborateurs rattachés à ce département
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
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.extensions import db

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.organization import Company, Position


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Department(db.Model):
    """
    Département / service de l'entreprise.

    Structure hiérarchique récursive via `parent_id` :
        Direction Générale (parent_id=None)
        └── Direction Technique (parent_id=1)
            └── Équipe Backend (parent_id=2)

    Le manager du département est un Employee — pas un User — car
    seul un employé peut encadrer une équipe au sens RH du terme.
    La relation est volontairement nullable : un département peut
    être temporairement sans responsable désigné.
    """

    __tablename__ = "departments"
    __table_args__ = (
        CheckConstraint("id <> parent_id", name="ck_departments_no_self_parent"),
        UniqueConstraint("company_id", "name", name="uq_departments_name_per_company"),
        Index("ix_departments_company_id", "company_id"),
        Index("ix_departments_parent_id", "parent_id"),
        Index("ix_departments_manager_id", "manager_id"),
    )

    # ── Identifiants ──────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── Rattachements ─────────────────────────────────────────────────────────
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    manager_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), nullable=True,
        comment="Employé responsable du département",
    )

    # ── Informations ──────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, comment="Code court (ex: 'TECH', 'RH', 'FIN')"
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cost_center: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, comment="Centre de coût analytique"
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
        "Company",
        foreign_keys=[company_id],
        lazy="select",
    )

    # Auto-référence : hiérarchie parent / sous-départements
    parent: Mapped[Optional["Department"]] = relationship(
        "Department",
        remote_side="Department.id",
        foreign_keys=[parent_id],
        back_populates="children",
        lazy="joined",
    )
    children: Mapped[List["Department"]] = relationship(
        "Department",
        foreign_keys=[parent_id],
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="select",
    )

    # Manager du département (Employee, pas User)
    manager: Mapped[Optional["Employee"]] = relationship(
        "Employee",
        foreign_keys=[manager_id],
        lazy="joined",
        post_update=True,  # Évite les conflits d'ordre d'insertion (FK croisée avec Employee)
    )

    # Employés rattachés à ce département (back_populates côté Employee.department)
    employees: Mapped[List["Employee"]] = relationship(
        "Employee",
        foreign_keys="Employee.department_id",
        back_populates="department",
        lazy="dynamic",
    )

    # Postes rattachés à ce département (défini dans organization.py)
    # positions: Mapped[List["Position"]] = relationship(
    #     "Position", back_populates="department", lazy="dynamic"
    # )

    # ── Validation SQLAlchemy ─────────────────────────────────────────────────
    @validates("name")
    def _strip_name(self, key: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Le nom du département ne peut pas être vide.")
        return value.strip()

    @validates("code")
    def _normalize_code(self, key: str, value: Optional[str]) -> Optional[str]:
        return value.strip().upper() if value else value

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def full_path(self) -> str:
        """
        Chemin hiérarchique complet, ex : 'Direction Technique > Équipe Backend'.
        Remonte récursivement jusqu'à la racine.
        """
        if self.parent is None:
            return self.name
        return f"{self.parent.full_path} > {self.name}"

    @property
    def depth(self) -> int:
        """Profondeur dans l'arborescence (0 = racine)."""
        depth = 0
        current = self.parent
        while current is not None:
            depth += 1
            current = current.parent
        return depth

    @property
    def is_root(self) -> bool:
        return self.parent_id is None

    @property
    def has_children(self) -> bool:
        return len(self.children) > 0

    @property
    def employee_count(self) -> int:
        """Nombre d'employés directement rattachés (hors sous-départements)."""
        return self.employees.count()

    @property
    def total_employee_count(self) -> int:
        """Nombre total d'employés, incluant tous les sous-départements."""
        total = self.employee_count
        for child in self.children:
            total += child.total_employee_count
        return total

    @property
    def has_manager(self) -> bool:
        return self.manager_id is not None

    # ── Méthodes d'instance ───────────────────────────────────────────────────
    def is_ancestor_of(self, department: "Department") -> bool:
        """Vérifie si ce département est un ancêtre du département donné."""
        current = department.parent
        while current is not None:
            if current.id == self.id:
                return True
            current = current.parent
        return False

    def is_descendant_of(self, department: "Department") -> bool:
        """Vérifie si ce département est un descendant du département donné."""
        return department.is_ancestor_of(self)

    def get_all_descendants(self) -> List["Department"]:
        """Retourne tous les sous-départements récursivement (à plat)."""
        result: List["Department"] = []
        for child in self.children:
            result.append(child)
            result.extend(child.get_all_descendants())
        return result

    def get_all_employee_ids(self) -> List[int]:
        """IDs de tous les employés du département et de ses sous-départements."""
        ids = [e.id for e in self.employees]
        for child in self.children:
            ids.extend(child.get_all_employee_ids())
        return ids

    def assign_manager(self, employee: "Employee") -> None:
        """
        Assigne un manager au département.
        Ne vérifie pas ici que l'employé appartient au département —
        cette règle métier est de la responsabilité du service applicatif.
        """
        self.manager_id = employee.id

    def remove_manager(self) -> None:
        self.manager_id = None

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_or_404(cls, department_id: int) -> "Department":
        department = db.session.get(cls, department_id)
        if department is None:
            from flask import abort
            abort(404, description="Département introuvable.")
        return department

    @classmethod
    def get_by_name(cls, company_id: int, name: str) -> Optional["Department"]:
        return db.session.execute(
            db.select(cls).where(
                cls.company_id == company_id,
                cls.name == name.strip(),
            )
        ).scalar_one_or_none()

    @classmethod
    def get_by_code(cls, company_id: int, code: str) -> Optional["Department"]:
        return db.session.execute(
            db.select(cls).where(
                cls.company_id == company_id,
                cls.code == code.strip().upper(),
            )
        ).scalar_one_or_none()

    @classmethod
    def root_departments(cls, company_id: int):
        """Requête (non exécutée) des départements racine d'une entreprise."""
        return db.select(cls).where(
            cls.company_id == company_id,
            cls.parent_id.is_(None),
            cls.is_active.is_(True),
        ).order_by(cls.name)

    @classmethod
    def active_in_company(cls, company_id: int):
        """Requête (non exécutée) de tous les départements actifs."""
        return db.select(cls).where(
            cls.company_id == company_id,
            cls.is_active.is_(True),
        ).order_by(cls.name)

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self, include_children: bool = False, include_stats: bool = False) -> dict:
        data: dict = {
            "id":           self.id,
            "company_id":   self.company_id,
            "parent_id":    self.parent_id,
            "name":         self.name,
            "code":         self.code,
            "description":  self.description,
            "cost_center":  self.cost_center,
            "is_active":    self.is_active,
            "full_path":    self.full_path,
            "depth":        self.depth,
            "manager_id":   self.manager_id,
            "manager_name": self.manager.full_name if self.manager else None,
            "created_at":   self.created_at.isoformat(),
            "updated_at":   self.updated_at.isoformat(),
        }
        if include_stats:
            data["employee_count"] = self.employee_count
            data["total_employee_count"] = self.total_employee_count
            data["has_children"] = self.has_children
        if include_children:
            data["children"] = [
                child.to_dict(include_children=True, include_stats=include_stats)
                for child in self.children
            ]
        return data

    # ── Dunder ────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return f"<Department id={self.id} {self.name!r}>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Department) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)