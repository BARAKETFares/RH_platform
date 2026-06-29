"""
Modèle : Employee
Dossier employé — SQLAlchemy 2.0 (Mapped / mapped_column)

Table centrale du schéma RH. Relie l'identité civile, les informations
professionnelles et le statut RH d'un collaborateur.

Relations principales :
  - user         (1:1, optionnelle) → compte d'accès à la plateforme
  - department   (N:1) → service de rattachement
  - position     (N:1) → poste / fonction occupée
  - site         (N:1) → site géographique de travail
  - manager      (N:1, self-referential) → hiérarchique direct
  - subordinates (1:N, self-referential) → collaborateurs encadrés
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional
from uuid import uuid4

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
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.extensions import db
from app.utils.crypto import decrypt_field, encrypt_field

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.organization import Company, Department, Position, Site


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Employee(db.Model):
    """
    Dossier employé complet.

    Statuts possibles (champ `status`) :
        active      — en poste
        on_leave    — en congé long (maternité, maladie longue durée)
        probation   — période d'essai en cours
        terminated  — départ définitif
        suspended   — suspendu temporairement

    Un Employee peut exister sans User associé (ex : import RH avant
    création du compte d'accès). L'inverse est vérifié au niveau
    applicatif : un User RH/Admin n'a pas forcément de fiche Employee.
    """

    __tablename__ = "employees"
    __table_args__ = (
        CheckConstraint("id <> manager_id", name="ck_employees_no_self_manager"),
        CheckConstraint(
            "termination_date IS NULL OR termination_date >= hire_date",
            name="ck_employees_termination_after_hire",
        ),
        CheckConstraint(
            "probation_end_date IS NULL OR probation_end_date >= hire_date",
            name="ck_employees_probation_after_hire",
        ),
        CheckConstraint(
            "annual_gross_salary IS NULL OR annual_gross_salary > 0",
            name="ck_employees_salary_positive",
        ),
        CheckConstraint(
            "status IN ('active','on_leave','probation','terminated','suspended')",
            name="ck_employees_status_valid",
        ),
        CheckConstraint(
            "gender IS NULL OR gender IN ('male','female','other','prefer_not_to_say')",
            name="ck_employees_gender_valid",
        ),
        UniqueConstraint("employee_number", name="uq_employees_employee_number"),
        UniqueConstraint("uuid", name="uq_employees_uuid"),
        UniqueConstraint("user_id", name="uq_employees_user_id"),
        Index("ix_employees_company_status", "company_id", "status"),
        Index("ix_employees_department_id", "department_id"),
        Index("ix_employees_manager_id", "manager_id"),
        Index("ix_employees_name", "last_name", "first_name"),
    )

    # ── Statuts (constantes) ──────────────────────────────────────────────────
    STATUS_ACTIVE     = "active"
    STATUS_ON_LEAVE    = "on_leave"
    STATUS_PROBATION   = "probation"
    STATUS_TERMINATED  = "terminated"
    STATUS_SUSPENDED   = "suspended"

    STATUSES: tuple[str, ...] = (
        STATUS_ACTIVE, STATUS_ON_LEAVE, STATUS_PROBATION,
        STATUS_TERMINATED, STATUS_SUSPENDED,
    )

    GENDERS: tuple[str, ...] = ("male", "female", "other", "prefer_not_to_say")

    # ── Identifiants ──────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        default=lambda: str(uuid4()),
        index=True,
        comment="Identifiant public non séquentiel (API, URLs)",
    )
    employee_number: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, comment="Matricule RH"
    )

    # ── Rattachements ─────────────────────────────────────────────────────────
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    department_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    position_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("positions.id", ondelete="SET NULL"), nullable=True
    )
    site_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), nullable=True
    )
    manager_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )

    # ── Informations personnelles ─────────────────────────────────────────────
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    maiden_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    birth_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    birth_place: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    nationality: Mapped[Optional[str]] = mapped_column(String(2), nullable=True, default="FR")
    _national_id_number: Mapped[Optional[str]] = mapped_column(
        "national_id_number",
        String(255), nullable=True,
        comment="Numéro de sécurité sociale — CHIFFRÉ Fernet avant stockage",
    )

    # ── Contact personnel ─────────────────────────────────────────────────────
    personal_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    personal_phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    professional_phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # ── Adresse ───────────────────────────────────────────────────────────────
    address_line1: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    address_line2: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True, default="FR")

    # ── Contact d'urgence ─────────────────────────────────────────────────────
    emergency_contact_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    emergency_contact_phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    emergency_contact_relationship: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )

    # ── Coordonnées bancaires (chiffrées) ─────────────────────────────────────
    _iban: Mapped[Optional[str]] = mapped_column(
        "iban", String(255), nullable=True, comment="IBAN — CHIFFRÉ Fernet avant stockage"
    )
    _bic: Mapped[Optional[str]] = mapped_column(
        "bic", String(255), nullable=True
    )

    # ── Informations professionnelles ─────────────────────────────────────────
    hire_date: Mapped[date] = mapped_column(Date, nullable=False)
    termination_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    termination_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    probation_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    annual_gross_salary: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    # ── Statut RH ─────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=STATUS_ACTIVE
    )

    # ── Médias & notes ─────────────────────────────────────────────────────────
    photo_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Notes internes RH — non visibles par l'employé"
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    user: Mapped[Optional["User"]] = relationship(
        "User",
        backref=db.backref("employee", uselist=False),
        foreign_keys=[user_id],
        lazy="joined",
    )
    company: Mapped["Company"] = relationship(
        "Company",
        foreign_keys=[company_id],
        lazy="select",
    )
    department: Mapped[Optional["Department"]] = relationship(
        "Department",
        foreign_keys=[department_id],
        back_populates="employees",
        lazy="joined",
    )
    position: Mapped[Optional["Position"]] = relationship(
        "Position",
        foreign_keys=[position_id],
        lazy="joined",
    )
    site: Mapped[Optional["Site"]] = relationship(
        "Site",
        foreign_keys=[site_id],
        lazy="select",
    )

    # Auto-référence : hiérarchie manager / subordonnés
    manager: Mapped[Optional["Employee"]] = relationship(
        "Employee",
        remote_side="Employee.id",
        foreign_keys=[manager_id],
        back_populates="subordinates",
        lazy="joined",
    )
    subordinates: Mapped[List["Employee"]] = relationship(
        "Employee",
        foreign_keys=[manager_id],
        back_populates="manager",
        lazy="dynamic",
    )

    # Définies dans leurs modules respectifs (back_populates="employee") :
    #   contracts          → app/models/employee_contract.py (ou contract.py)
    #   documents           → app/models/document.py
    #   employee_skills     → app/models/skill.py
    #   leave_balances      → app/models/leave.py
    #   leave_requests      → app/models/leave.py
    #   evaluations         → app/models/evaluation.py (evaluator_id + employee_id)
    #   objectives          → app/models/objective.py

    # ── Validation SQLAlchemy ─────────────────────────────────────────────────
    @validates("first_name", "last_name")
    def _strip_names(self, key: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError(f"Le champ '{key}' ne peut pas être vide.")
        return value.strip()

    @validates("personal_email")
    def _normalize_personal_email(self, key: str, value: Optional[str]) -> Optional[str]:
        return value.lower().strip() if value else value

    @validates("status")
    def _validate_status(self, key: str, value: str) -> str:
        if value not in self.STATUSES:
            raise ValueError(f"Statut invalide : '{value}'. Valeurs acceptées : {self.STATUSES}")
        return value

    @validates("gender")
    def _validate_gender(self, key: str, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in self.GENDERS:
            raise ValueError(f"Genre invalide : '{value}'. Valeurs acceptées : {self.GENDERS}")
        return value

    # ── Propriétés chiffrées ──────────────────────────────────────────────────
    @hybrid_property
    def national_id_number(self) -> Optional[str]:
        return decrypt_field(self._national_id_number)

    @national_id_number.setter
    def national_id_number(self, value: Optional[str]) -> None:
        self._national_id_number = encrypt_field(value)

    @hybrid_property
    def iban(self) -> Optional[str]:
        return decrypt_field(self._iban)

    @iban.setter
    def iban(self, value: Optional[str]) -> None:
        self._iban = encrypt_field(value)

    @hybrid_property
    def bic(self) -> Optional[str]:
        return decrypt_field(self._bic)

    @bic.setter
    def bic(self, value: Optional[str]) -> None:
        self._bic = encrypt_field(value)

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def full_name(self) -> str:
        """Nom complet affichable : 'Prénom Nom'."""
        return f"{self.first_name} {self.last_name}"

    @property
    def initials(self) -> str:
        """Initiales pour avatar : 'JD' pour Jean Dupont."""
        first = self.first_name[0].upper() if self.first_name else ""
        last = self.last_name[0].upper() if self.last_name else ""
        return f"{first}{last}"

    @property
    def is_active(self) -> bool:
        """True si l'employé est actuellement en poste (actif ou en congé)."""
        return self.status in (self.STATUS_ACTIVE, self.STATUS_ON_LEAVE)

    @property
    def is_terminated(self) -> bool:
        return self.status == self.STATUS_TERMINATED

    @property
    def is_on_probation(self) -> bool:
        """True si en période d'essai non encore échue."""
        if self.status != self.STATUS_PROBATION:
            return False
        if self.probation_end_date is None:
            return True
        return self.probation_end_date >= date.today()

    @property
    def seniority_days(self) -> int:
        """Nombre de jours d'ancienneté depuis hire_date (ou jusqu'à termination_date)."""
        end = self.termination_date or date.today()
        return (end - self.hire_date).days

    @property
    def seniority_years(self) -> float:
        """Ancienneté en années (valeur décimale)."""
        return round(self.seniority_days / 365.25, 1)

    @property
    def has_user_account(self) -> bool:
        return self.user_id is not None

    # ── Méthodes d'instance ───────────────────────────────────────────────────
    def is_managed_by(self, employee_id: int) -> bool:
        """Vérifie si cet employé est dans la chaîne hiérarchique d'un manager donné."""
        current = self.manager
        while current is not None:
            if current.id == employee_id:
                return True
            current = current.manager
        return False

    def terminate(self, termination_date: date, reason: Optional[str] = None) -> None:
        """Marque l'employé comme parti définitivement."""
        if termination_date < self.hire_date:
            raise ValueError("La date de départ ne peut pas précéder la date d'embauche.")
        self.status = self.STATUS_TERMINATED
        self.termination_date = termination_date
        self.termination_reason = reason

    def reactivate(self) -> None:
        """Réactive un employé (annulation d'un départ, retour de congé long)."""
        self.status = self.STATUS_ACTIVE
        self.termination_date = None
        self.termination_reason = None

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_by_uuid(cls, employee_uuid: str) -> Optional["Employee"]:
        return db.session.execute(
            db.select(cls).where(cls.uuid == employee_uuid)
        ).scalar_one_or_none()

    @classmethod
    def get_by_employee_number(cls, number: str) -> Optional["Employee"]:
        return db.session.execute(
            db.select(cls).where(cls.employee_number == number)
        ).scalar_one_or_none()

    @classmethod
    def get_or_404(cls, employee_id: int) -> "Employee":
        employee = db.session.get(cls, employee_id)
        if employee is None:
            from flask import abort
            abort(404, description="Employé introuvable.")
        return employee

    @classmethod
    def active_in_company(cls, company_id: int):
        """Retourne une requête des employés actifs d'une entreprise (non exécutée)."""
        return db.select(cls).where(
            cls.company_id == company_id,
            cls.status.in_((cls.STATUS_ACTIVE, cls.STATUS_ON_LEAVE, cls.STATUS_PROBATION)),
        )

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self, include_sensitive: bool = False) -> dict:
        """
        Sérialise l'employé en dict.
        include_sensitive=True expose IBAN/numéro de sécu (réservé Admin/RH).
        """
        data: dict = {
            "id":               self.id,
            "uuid":              self.uuid,
            "employee_number":  self.employee_number,
            "first_name":       self.first_name,
            "last_name":        self.last_name,
            "full_name":        self.full_name,
            "gender":           self.gender,
            "personal_email":   self.personal_email,
            "personal_phone":   self.personal_phone,
            "professional_phone": self.professional_phone,
            "status":           self.status,
            "hire_date":        self.hire_date.isoformat() if self.hire_date else None,
            "termination_date": self.termination_date.isoformat() if self.termination_date else None,
            "probation_end_date": self.probation_end_date.isoformat() if self.probation_end_date else None,
            "seniority_years":  self.seniority_years,
            "department_id":    self.department_id,
            "position_id":      self.position_id,
            "site_id":          self.site_id,
            "manager_id":       self.manager_id,
            "manager_name":     self.manager.full_name if self.manager else None,
            "photo_path":       self.photo_path,
            "created_at":       self.created_at.isoformat(),
            "updated_at":       self.updated_at.isoformat(),
        }
        if include_sensitive:
            data["national_id_number"] = self.national_id_number
            data["iban"] = self.iban
            data["bic"] = self.bic
            data["annual_gross_salary"] = (
                float(self.annual_gross_salary) if self.annual_gross_salary else None
            )
            data["address_line1"] = self.address_line1
            data["address_line2"] = self.address_line2
            data["city"] = self.city
            data["postal_code"] = self.postal_code
            data["country"] = self.country
            data["emergency_contact_name"] = self.emergency_contact_name
            data["emergency_contact_phone"] = self.emergency_contact_phone
            data["notes"] = self.notes
        return data

    # ── Dunder ────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return f"<Employee id={self.id} {self.full_name!r} [{self.status}]>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Employee) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)