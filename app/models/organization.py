"""
Modèles : Company · Site
Structure organisationnelle racine — SQLAlchemy 2.0 (Mapped / mapped_column)

Company est la racine de toute la hiérarchie organisationnelle :
    Company → Site
    Company → Department → Position
    Company → Employee

Une seule Company suffit pour une PME ; le modèle supporte le multi-société
(plusieurs entités juridiques dans la même base) sans changement de schéma.
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
    SmallInteger,
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


# =============================================================================
# Company
# =============================================================================

class Company(db.Model):
    """
    Entité juridique employeuse.

    Racine de toute donnée organisationnelle (sites, départements, employés).
    Le champ `fiscal_year_start` permet de gérer des exercices comptables
    ne démarrant pas en janvier (ex : 1er avril pour certains groupes).
    """

    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint(
            "fiscal_year_start BETWEEN 1 AND 12",
            name="ck_companies_fiscal_year_start_valid",
        ),
        UniqueConstraint("siret", name="uq_companies_siret"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    siret: Mapped[Optional[str]] = mapped_column(String(14), nullable=True)
    naf_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="FR")

    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    logo_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    fiscal_year_start: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1,
        comment="Mois de début d'exercice fiscal (1=janvier ... 12=décembre)",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    sites: Mapped[List["Site"]] = relationship(
        "Site", back_populates="company", cascade="all, delete-orphan", lazy="dynamic"
    )
    departments: Mapped[List["Department"]] = relationship(
        "Department", back_populates="company", cascade="all, delete-orphan", lazy="dynamic"
    )
    employees: Mapped[List["Employee"]] = relationship(
        "Employee", foreign_keys="Employee.company_id", back_populates="company", lazy="dynamic"
    )

    # ── Validation ────────────────────────────────────────────────────────────
    @validates("name")
    def _strip_name(self, key: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Le nom de l'entreprise ne peut pas être vide.")
        return value.strip()

    @validates("siret")
    def _validate_siret(self, key: str, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        cleaned = value.replace(" ", "")
        if not cleaned.isdigit() or len(cleaned) != 14:
            raise ValueError("Le SIRET doit contenir exactement 14 chiffres.")
        return cleaned

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def active_employee_count(self) -> int:
        from app.models.employee import Employee
        return self.employees.filter(
            Employee.status.in_((Employee.STATUS_ACTIVE, Employee.STATUS_ON_LEAVE, Employee.STATUS_PROBATION))
        ).count()

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_or_404(cls, company_id: int) -> "Company":
        company = db.session.get(cls, company_id)
        if company is None:
            from flask import abort
            abort(404, description="Entreprise introuvable.")
        return company

    @classmethod
    def get_default(cls) -> Optional["Company"]:
        """Retourne la première entreprise — utile en mono-société."""
        return db.session.execute(db.select(cls).order_by(cls.id).limit(1)).scalar_one_or_none()

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "legal_name": self.legal_name,
            "siret": self.siret,
            "naf_code": self.naf_code,
            "address": self.address,
            "city": self.city,
            "postal_code": self.postal_code,
            "country": self.country,
            "phone": self.phone,
            "email": self.email,
            "website": self.website,
            "logo_path": self.logo_path,
            "fiscal_year_start": self.fiscal_year_start,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<Company id={self.id} {self.name!r}>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Company) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


# =============================================================================
# Site
# =============================================================================

class Site(db.Model):
    """
    Site géographique (établissement) d'une entreprise.

    Un employé est rattaché à un site (lieu de travail physique),
    indépendamment de son département (organisation fonctionnelle).
    Permet de gérer le multi-sites avec jours fériés locaux distincts
    (cf. PublicHoliday.site_id dans le module Congés à venir).
    """

    __tablename__ = "sites"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_sites_name_per_company"),
        Index("ix_sites_company_id", "company_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="FR")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    company: Mapped["Company"] = relationship(
        "Company", foreign_keys=[company_id], back_populates="sites", lazy="joined"
    )
    employees: Mapped[List["Employee"]] = relationship(
        "Employee", foreign_keys="Employee.site_id", back_populates="site", lazy="dynamic"
    )

    # ── Validation ────────────────────────────────────────────────────────────
    @validates("name")
    def _strip_name(self, key: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Le nom du site ne peut pas être vide.")
        return value.strip()

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def employee_count(self) -> int:
        return self.employees.count()

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_or_404(cls, site_id: int) -> "Site":
        site = db.session.get(cls, site_id)
        if site is None:
            from flask import abort
            abort(404, description="Site introuvable.")
        return site

    @classmethod
    def active_in_company(cls, company_id: int):
        """Requête (non exécutée) des sites actifs d'une entreprise."""
        return db.select(cls).where(
            cls.company_id == company_id, cls.is_active.is_(True)
        ).order_by(cls.name)

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self, include_stats: bool = False) -> dict:
        data = {
            "id": self.id,
            "company_id": self.company_id,
            "name": self.name,
            "address": self.address,
            "city": self.city,
            "postal_code": self.postal_code,
            "country": self.country,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
        if include_stats:
            data["employee_count"] = self.employee_count
        return data

    def __repr__(self) -> str:
        return f"<Site id={self.id} {self.name!r}>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Site) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)