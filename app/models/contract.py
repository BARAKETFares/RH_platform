"""
Modèles : ContractType · Contract
Historique des contrats de travail — SQLAlchemy 2.0 (Mapped / mapped_column)

ContractType définit un modèle de contrat configurable par entreprise
(CDI Cadre, CDI Non-Cadre, CDD, Alternance, Stage...) avec les droits à
congés et préavis associés par défaut.

Contract représente un contrat de travail INDIVIDUEL signé par un employé,
avec son propre salaire, ses propres dates, indépendamment des valeurs
par défaut du ContractType. Un employé peut avoir plusieurs Contract dans
le temps (renouvellement de CDD, passage CDD→CDI, avenant créant un
nouveau contrat) — la colonne `is_current` identifie le contrat actif.

Cette séparation Employee.annual_gross_salary (valeur de référence simple,
déjà existante) / Contract.gross_salary (valeur contractuelle historisée)
est volontaire : Employee garde une vue rapide, Contract garde la traçabilité
légale complète.

Relations principales :
  - company        (N:1, ContractType) → entreprise de rattachement
  - employee       (N:1, Contract) → employé concerné
  - contract_type  (N:1, Contract) → modèle de contrat utilisé
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
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
# ContractType
# =============================================================================

class ContractType(db.Model):
    """
    Modèle de contrat configurable par entreprise.

    Définit les valeurs par défaut appliquées aux nouveaux contrats de ce
    type (jours de CP, RTT, préavis) — ces valeurs sont des références
    utilisées au moment de la création d'un Contract, mais le Contract
    individuel peut s'en écarter (cas particulier négocié).

    duration_type catégorise le type légal du contrat, utilisé pour les
    règles métier (ex : un CDD a une end_date obligatoire, un CDI non).
    """

    __tablename__ = "contract_types"
    __table_args__ = (
        CheckConstraint(
            "duration_type IN ('cdi','cdd','interim','apprenticeship','internship','freelance')",
            name="ck_contract_types_duration_valid",
        ),
        CheckConstraint("paid_leave_days >= 0", name="ck_contract_types_leave_positive"),
        CheckConstraint("rtt_days >= 0", name="ck_contract_types_rtt_positive"),
        CheckConstraint("notice_period_days >= 0", name="ck_contract_types_notice_positive"),
        UniqueConstraint("company_id", "name", name="uq_contract_types_name_per_company"),
        Index("ix_contract_types_company_id", "company_id"),
    )

    # ── Types de durée (constantes) ───────────────────────────────────────────
    DURATION_CDI            = "cdi"
    DURATION_CDD            = "cdd"
    DURATION_INTERIM        = "interim"
    DURATION_APPRENTICESHIP = "apprenticeship"
    DURATION_INTERNSHIP     = "internship"
    DURATION_FREELANCE      = "freelance"

    DURATION_TYPES: tuple[str, ...] = (
        DURATION_CDI, DURATION_CDD, DURATION_INTERIM,
        DURATION_APPRENTICESHIP, DURATION_INTERNSHIP, DURATION_FREELANCE,
    )

    # Types nécessitant obligatoirement une date de fin
    FIXED_TERM_TYPES: tuple[str, ...] = (
        DURATION_CDD, DURATION_INTERIM, DURATION_APPRENTICESHIP, DURATION_INTERNSHIP,
    )

    DURATION_LABELS: dict[str, str] = {
        DURATION_CDI:            "CDI",
        DURATION_CDD:            "CDD",
        DURATION_INTERIM:        "Intérim",
        DURATION_APPRENTICESHIP: "Alternance",
        DURATION_INTERNSHIP:     "Stage",
        DURATION_FREELANCE:      "Freelance",
    }

    # ── Identifiants ──────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )

    # ── Informations ──────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    duration_type: Mapped[str] = mapped_column(String(20), nullable=False)

    # ── Valeurs par défaut ─────────────────────────────────────────────────────
    paid_leave_days: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=25)
    rtt_days: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    notice_period_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    company: Mapped["Company"] = relationship(
        "Company", foreign_keys=[company_id], lazy="select"
    )
    contracts: Mapped[List["Contract"]] = relationship(
        "Contract", back_populates="contract_type", lazy="dynamic"
    )

    # ── Validation SQLAlchemy ─────────────────────────────────────────────────
    @validates("name")
    def _strip_name(self, key: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Le nom du type de contrat ne peut pas être vide.")
        return value.strip()

    @validates("duration_type")
    def _validate_duration_type(self, key: str, value: str) -> str:
        if value not in self.DURATION_TYPES:
            raise ValueError(
                f"Type de durée invalide : '{value}'. Valeurs acceptées : {self.DURATION_TYPES}"
            )
        return value

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def duration_label(self) -> str:
        return self.DURATION_LABELS.get(self.duration_type, self.duration_type)

    @property
    def requires_end_date(self) -> bool:
        """True si ce type de contrat nécessite obligatoirement une date de fin."""
        return self.duration_type in self.FIXED_TERM_TYPES

    @property
    def active_contract_count(self) -> int:
        return self.contracts.filter_by(is_current=True).count()

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_or_404(cls, contract_type_id: int) -> "ContractType":
        ct = db.session.get(cls, contract_type_id)
        if ct is None:
            from flask import abort
            abort(404, description="Type de contrat introuvable.")
        return ct

    @classmethod
    def active_in_company(cls, company_id: int):
        """Requête (non exécutée) des types de contrat actifs d'une entreprise."""
        return db.select(cls).where(
            cls.company_id == company_id, cls.is_active.is_(True)
        ).order_by(cls.name)

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "company_id": self.company_id,
            "name": self.name,
            "duration_type": self.duration_type,
            "duration_label": self.duration_label,
            "requires_end_date": self.requires_end_date,
            "paid_leave_days": float(self.paid_leave_days),
            "rtt_days": float(self.rtt_days),
            "notice_period_days": self.notice_period_days,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<ContractType id={self.id} {self.name!r} [{self.duration_type}]>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ContractType) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


# =============================================================================
# Contract
# =============================================================================

class Contract(db.Model):
    """
    Contrat de travail individuel d'un employé.

    Historise chaque contrat signé : un employé peut avoir plusieurs
    Contract dans le temps (renouvellement CDD, passage CDD→CDI, avenant).
    `is_current` identifie le contrat actuellement en vigueur — un seul
    contrat devrait être `is_current=True` par employé à un instant donné
    (règle appliquée au niveau service, pas en contrainte SQL stricte,
    pour permettre des périodes de transition lors d'un renouvellement).

    `trial_end_date` est distinct de `Employee.probation_end_date` :
    le premier est spécifique à CE contrat précis, le second reste un
    raccourci de lecture rapide sur la fiche employé pour le contrat en cours.
    """

    __tablename__ = "contracts"
    __table_args__ = (
        CheckConstraint(
            "end_date IS NULL OR end_date > start_date",
            name="ck_contracts_end_after_start",
        ),
        CheckConstraint(
            "trial_end_date IS NULL OR trial_end_date >= start_date",
            name="ck_contracts_trial_after_start",
        ),
        CheckConstraint("gross_salary > 0", name="ck_contracts_salary_positive"),
        CheckConstraint(
            "weekly_hours > 0 AND weekly_hours <= 48",
            name="ck_contracts_hours_valid",
        ),
        Index("ix_contracts_employee_id", "employee_id"),
        Index("ix_contracts_employee_current", "employee_id", "is_current"),
        Index("ix_contracts_end_date", "end_date"),
    )

    # ── Identifiants ──────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── Rattachements ─────────────────────────────────────────────────────────
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    contract_type_id: Mapped[int] = mapped_column(
        ForeignKey("contract_types.id", ondelete="RESTRICT"), nullable=False
    )

    # ── Période ───────────────────────────────────────────────────────────────
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, comment="NULL = CDI ou contrat sans terme défini"
    )
    trial_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # ── Conditions contractuelles ──────────────────────────────────────────────
    gross_salary: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    weekly_hours: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=35)

    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    document_path: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True, comment="Contrat signé numérisé"
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

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
    contract_type: Mapped["ContractType"] = relationship(
        "ContractType", back_populates="contracts", lazy="joined"
    )

    # ── Validation SQLAlchemy ─────────────────────────────────────────────────
    @validates("gross_salary")
    def _validate_salary(self, key: str, value: float) -> float:
        if value is not None and value <= 0:
            raise ValueError("Le salaire brut doit être strictement positif.")
        return value

    @validates("weekly_hours")
    def _validate_hours(self, key: str, value: float) -> float:
        if value is not None and not (0 < value <= 48):
            raise ValueError("Le nombre d'heures hebdomadaires doit être compris entre 0 et 48.")
        return value

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def is_fixed_term(self) -> bool:
        return self.end_date is not None

    @property
    def is_expired(self) -> bool:
        return self.end_date is not None and self.end_date < date.today()

    @property
    def is_in_trial_period(self) -> bool:
        if self.trial_end_date is None:
            return False
        return date.today() <= self.trial_end_date

    @property
    def duration_days(self) -> Optional[int]:
        """Durée en jours du contrat. None si CDI (pas de end_date)."""
        if self.end_date is None:
            return None
        return (self.end_date - self.start_date).days

    @property
    def annual_gross_salary(self) -> float:
        """Salaire brut annuel estimé (mensuel × 12)."""
        return float(self.gross_salary) * 12

    @property
    def days_until_expiry(self) -> Optional[int]:
        """Jours restants avant expiration. None si CDI. Négatif si déjà expiré."""
        if self.end_date is None:
            return None
        return (self.end_date - date.today()).days

    @property
    def expires_soon(self) -> bool:
        """True si le contrat expire dans moins de 30 jours (alerte RH CDD)."""
        days = self.days_until_expiry
        return days is not None and 0 <= days <= 30

    # ── Méthodes d'instance ───────────────────────────────────────────────────
    def terminate(self, end_date: date) -> None:
        """Met fin au contrat à la date donnée et le sort du statut courant."""
        if end_date < self.start_date:
            raise ValueError("La date de fin ne peut pas précéder la date de début.")
        self.end_date = end_date
        self.is_current = False

    def renew(self, new_end_date: Optional[date] = None, new_salary: Optional[float] = None) -> "Contract":
        """
        Crée un nouveau contrat de renouvellement, désactive le contrat actuel.
        Ne fait pas de commit — à la charge de l'appelant.
        """
        self.is_current = False

        renewed = Contract(
            employee_id=self.employee_id,
            contract_type_id=self.contract_type_id,
            start_date=self.end_date or date.today(),
            end_date=new_end_date,
            gross_salary=new_salary if new_salary is not None else self.gross_salary,
            weekly_hours=self.weekly_hours,
            is_current=True,
        )
        db.session.add(renewed)
        return renewed

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_or_404(cls, contract_id: int) -> "Contract":
        contract = db.session.get(cls, contract_id)
        if contract is None:
            from flask import abort
            abort(404, description="Contrat introuvable.")
        return contract

    @classmethod
    def get_current(cls, employee_id: int) -> Optional["Contract"]:
        """Retourne le contrat actuellement en vigueur pour un employé."""
        return db.session.execute(
            db.select(cls).where(
                cls.employee_id == employee_id,
                cls.is_current.is_(True),
            ).order_by(cls.start_date.desc())
        ).scalars().first()

    @classmethod
    def history_for_employee(cls, employee_id: int):
        """Requête (non exécutée) de l'historique complet des contrats d'un employé."""
        return db.select(cls).where(
            cls.employee_id == employee_id
        ).order_by(cls.start_date.desc())

    @classmethod
    def expiring_soon(cls, company_id: int, within_days: int = 30):
        """
        Requête (non exécutée) des contrats à durée déterminée arrivant à
        échéance — utilisée pour les alertes RH (renouvellement CDD à anticiper).
        """
        from app.models.employee import Employee
        cutoff = date.today()
        return db.select(cls).join(Employee, cls.employee_id == Employee.id).where(
            Employee.company_id == company_id,
            cls.is_current.is_(True),
            cls.end_date.isnot(None),
            cls.end_date >= cutoff,
        ).order_by(cls.end_date.asc())

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self, include_sensitive: bool = False) -> dict:
        data: dict = {
            "id": self.id,
            "employee_id": self.employee_id,
            "contract_type_id": self.contract_type_id,
            "contract_type_name": self.contract_type.name if self.contract_type else None,
            "duration_type": self.contract_type.duration_type if self.contract_type else None,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "trial_end_date": self.trial_end_date.isoformat() if self.trial_end_date else None,
            "weekly_hours": float(self.weekly_hours),
            "is_current": self.is_current,
            "is_fixed_term": self.is_fixed_term,
            "is_expired": self.is_expired,
            "is_in_trial_period": self.is_in_trial_period,
            "expires_soon": self.expires_soon,
            "days_until_expiry": self.days_until_expiry,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
        if include_sensitive:
            data["gross_salary"] = float(self.gross_salary)
            data["annual_gross_salary"] = self.annual_gross_salary
            data["notes"] = self.notes
        return data

    # ── Dunder ────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        status = "current" if self.is_current else "ended"
        return f"<Contract id={self.id} employee={self.employee_id} [{status}]>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Contract) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)