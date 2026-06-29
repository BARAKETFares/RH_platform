"""
Modèles : PaySlip · PayElement
Bulletins de paie — SQLAlchemy 2.0 (Mapped / mapped_column)

PaySlip représente un bulletin de paie mensuel individuel.
Un bulletin appartient à un Employee et référence le Contract actif
au moment de son émission (snapshot, pour conserver la traçabilité
même si le contrat évolue ultérieurement).

PayElement représente une ligne de bulletin : prime, retenue ou
cotisation. Les éléments portent un `amount` toujours positif ;
le sens (gain ou déduction) est déterminé par `element_type` et
`is_employer` (cotisation salariale vs patronale).

Statuts du bulletin :
    draft      — généré automatiquement, en cours de vérification
    validated  — validé par le gestionnaire de paie
    paid       — virement effectué

Relations principales :
  - employee      (N:1) → employé concerné
  - contract      (N:1, optionnelle) → contrat en vigueur à l'émission
  - elements      (1:N) → lignes de détail du bulletin
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
    from app.models.contract import Contract


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================================
# PaySlip — Bulletin de paie
# =============================================================================

class PaySlip(db.Model):
    """
    Bulletin de paie mensuel d'un employé.

    La période est identifiée par (period_year, period_month).
    La contrainte d'unicité (employee_id, period_year, period_month)
    garantit un seul bulletin par employé par mois.

    gross_salary et net_salary sont les totaux du bulletin.
    Le détail est porté par les PayElement associés.
    """

    __tablename__ = "payslips"
    __table_args__ = (
        UniqueConstraint(
            "employee_id", "period_year", "period_month",
            name="uq_payslips_employee_period",
        ),
        CheckConstraint(
            "period_month BETWEEN 1 AND 12",
            name="ck_payslips_month_valid",
        ),
        CheckConstraint(
            "period_year >= 2000",
            name="ck_payslips_year_valid",
        ),
        CheckConstraint(
            "gross_salary > 0",
            name="ck_payslips_gross_positive",
        ),
        CheckConstraint(
            "net_salary > 0",
            name="ck_payslips_net_positive",
        ),
        CheckConstraint(
            "net_salary <= gross_salary",
            name="ck_payslips_net_le_gross",
        ),
        CheckConstraint(
            "total_employee_contributions >= 0",
            name="ck_payslips_employee_contributions_positive",
        ),
        CheckConstraint(
            "total_employer_contributions >= 0",
            name="ck_payslips_employer_contributions_positive",
        ),
        CheckConstraint(
            "status IN ('draft','validated','paid')",
            name="ck_payslips_status_valid",
        ),
        Index("ix_payslips_employee_id", "employee_id"),
        Index("ix_payslips_period", "period_year", "period_month"),
        Index("ix_payslips_status", "status"),
    )

    # ── Statuts ───────────────────────────────────────────────────────────────
    STATUS_DRAFT     = "draft"
    STATUS_VALIDATED = "validated"
    STATUS_PAID      = "paid"

    STATUSES: tuple[str, ...] = (STATUS_DRAFT, STATUS_VALIDATED, STATUS_PAID)

    STATUS_LABELS: dict[str, str] = {
        STATUS_DRAFT:     "Généré",
        STATUS_VALIDATED: "Validé",
        STATUS_PAID:      "Payé",
    }

    # ── Identifiant ───────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── Rattachements ─────────────────────────────────────────────────────────
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
    )
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"),
        nullable=True,
        comment="Contrat en vigueur au moment de l'émission (snapshot)",
    )

    # ── Période ───────────────────────────────────────────────────────────────
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)

    # ── Montants ──────────────────────────────────────────────────────────────
    gross_salary: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
        comment="Salaire brut mensuel (base + éléments variables)",
    )
    total_employee_contributions: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00"),
        comment="Total des cotisations salariales",
    )
    total_employer_contributions: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00"),
        comment="Total des cotisations patronales",
    )
    net_salary: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
        comment="Net à payer = brut − cotisations salariales",
    )

    # ── Statut & workflow ─────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=STATUS_DRAFT
    )
    validated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payment_reference: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True,
        comment="Référence virement ou chèque",
    )

    # ── Métadonnées ───────────────────────────────────────────────────────────
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    employee: Mapped["Employee"] = relationship(
        "Employee",
        foreign_keys=[employee_id],
        lazy="joined",
    )
    contract: Mapped[Optional["Contract"]] = relationship(
        "Contract",
        foreign_keys=[contract_id],
        lazy="joined",
    )
    elements: Mapped[List["PayElement"]] = relationship(
        "PayElement",
        back_populates="payslip",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="PayElement.element_type, PayElement.label",
    )

    # ── Validation SQLAlchemy ─────────────────────────────────────────────────
    @validates("status")
    def _validate_status(self, key: str, value: str) -> str:
        if value not in self.STATUSES:
            raise ValueError(
                f"Statut de bulletin invalide : '{value}'. "
                f"Valeurs acceptées : {self.STATUSES}"
            )
        return value

    @validates("period_month")
    def _validate_month(self, key: str, value: int) -> int:
        if not (1 <= value <= 12):
            raise ValueError("Le mois doit être compris entre 1 et 12.")
        return value

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def period_label(self) -> str:
        """Libellé lisible de la période : 'Janvier 2025'."""
        months = [
            "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
            "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
        ]
        return f"{months[self.period_month - 1]} {self.period_year}"

    @property
    def period_start(self) -> date:
        return date(self.period_year, self.period_month, 1)

    @property
    def status_label(self) -> str:
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def is_editable(self) -> bool:
        return self.status == self.STATUS_DRAFT

    @property
    def employer_cost(self) -> Decimal:
        """Coût total employeur = brut + cotisations patronales."""
        return self.gross_salary + self.total_employer_contributions

    @property
    def bonuses(self) -> list["PayElement"]:
        return [e for e in self.elements if e.element_type == PayElement.TYPE_BONUS]

    @property
    def deductions(self) -> list["PayElement"]:
        return [e for e in self.elements if e.element_type == PayElement.TYPE_DEDUCTION]

    @property
    def contributions(self) -> list["PayElement"]:
        return [e for e in self.elements if e.element_type == PayElement.TYPE_CONTRIBUTION]

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_or_404(cls, payslip_id: int) -> "PaySlip":
        ps = db.session.get(cls, payslip_id)
        if ps is None:
            from flask import abort
            abort(404, description="Bulletin de paie introuvable.")
        return ps

    @classmethod
    def for_employee(cls, employee_id: int):
        """Requête non exécutée : bulletins d'un employé, du plus récent au plus ancien."""
        return (
            db.select(cls)
            .where(cls.employee_id == employee_id)
            .order_by(cls.period_year.desc(), cls.period_month.desc())
        )

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self, include_elements: bool = False) -> dict:
        data: dict = {
            "id":                           self.id,
            "employee_id":                  self.employee_id,
            "contract_id":                  self.contract_id,
            "period_year":                  self.period_year,
            "period_month":                 self.period_month,
            "period_label":                 self.period_label,
            "gross_salary":                 float(self.gross_salary),
            "total_employee_contributions": float(self.total_employee_contributions),
            "total_employer_contributions": float(self.total_employer_contributions),
            "net_salary":                   float(self.net_salary),
            "employer_cost":                float(self.employer_cost),
            "status":                       self.status,
            "status_label":                 self.status_label,
            "validated_at":  self.validated_at.isoformat() if self.validated_at else None,
            "paid_at":       self.paid_at.isoformat() if self.paid_at else None,
            "payment_reference": self.payment_reference,
            "notes":         self.notes,
            "created_at":    self.created_at.isoformat(),
            "updated_at":    self.updated_at.isoformat(),
        }
        if include_elements:
            data["elements"] = [e.to_dict() for e in self.elements]
        return data

    # ── Dunder ────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return (
            f"<PaySlip id={self.id} emp={self.employee_id} "
            f"period={self.period_year}-{self.period_month:02d} "
            f"status={self.status}>"
        )


# =============================================================================
# PayElement — Ligne de bulletin de paie
# =============================================================================

class PayElement(db.Model):
    """
    Ligne de détail d'un bulletin de paie.

    Types d'éléments :
        bonus        — prime, indemnité, avantage (augmente le brut)
        deduction    — retenue exceptionnelle (diminue le net)
        contribution — cotisation salariale ou patronale

    `amount` est toujours positif ; l'effet sur le salaire est déterminé
    par `element_type` et `is_employer` :
        bonus         → augmente gross_salary
        deduction     → déduit du net_salary
        contribution  + is_employer=False → cotisation salariale
        contribution  + is_employer=True  → cotisation patronale

    `rate` et `base_amount` permettent de tracer les cotisations
    calculées en pourcentage (ex : 22 % sur la base de 3 500 €).
    """

    __tablename__ = "pay_elements"
    __table_args__ = (
        CheckConstraint(
            "element_type IN ('bonus','deduction','contribution')",
            name="ck_pay_elements_type_valid",
        ),
        CheckConstraint(
            "amount > 0",
            name="ck_pay_elements_amount_positive",
        ),
        CheckConstraint(
            "rate IS NULL OR (rate > 0 AND rate <= 100)",
            name="ck_pay_elements_rate_valid",
        ),
        CheckConstraint(
            "base_amount IS NULL OR base_amount > 0",
            name="ck_pay_elements_base_positive",
        ),
        Index("ix_pay_elements_payslip_id", "payslip_id"),
    )

    # ── Types d'éléments ─────────────────────────────────────────────────────
    TYPE_BONUS        = "bonus"
    TYPE_DEDUCTION    = "deduction"
    TYPE_CONTRIBUTION = "contribution"

    TYPES: tuple[str, ...] = (TYPE_BONUS, TYPE_DEDUCTION, TYPE_CONTRIBUTION)

    TYPE_LABELS: dict[str, str] = {
        TYPE_BONUS:        "Prime / Indemnité",
        TYPE_DEDUCTION:    "Retenue",
        TYPE_CONTRIBUTION: "Cotisation",
    }

    # ── Identifiant ───────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── Rattachement ──────────────────────────────────────────────────────────
    payslip_id: Mapped[int] = mapped_column(
        ForeignKey("payslips.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ── Identification de l'élément ───────────────────────────────────────────
    element_type: Mapped[str] = mapped_column(String(20), nullable=False)
    label: Mapped[str] = mapped_column(
        String(200), nullable=False,
        comment="Libellé affiché sur le bulletin (ex: 'Prime d'ancienneté', 'URSSAF maladie')",
    )
    is_employer: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="True = cotisation patronale ; False = salariale ou élément standard",
    )

    # ── Montants ──────────────────────────────────────────────────────────────
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
        comment="Montant toujours positif ; le sens est déterminé par element_type",
    )
    rate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(6, 4), nullable=True,
        comment="Taux appliqué en % (ex: 22.0000 pour 22 %)",
    )
    base_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True,
        comment="Assiette sur laquelle le taux est calculé",
    )

    # ── Relation ──────────────────────────────────────────────────────────────
    payslip: Mapped["PaySlip"] = relationship(
        "PaySlip",
        back_populates="elements",
        lazy="select",
    )

    # ── Validation SQLAlchemy ─────────────────────────────────────────────────
    @validates("element_type")
    def _validate_type(self, key: str, value: str) -> str:
        if value not in self.TYPES:
            raise ValueError(
                f"Type d'élément invalide : '{value}'. "
                f"Valeurs acceptées : {self.TYPES}"
            )
        return value

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def type_label(self) -> str:
        return self.TYPE_LABELS.get(self.element_type, self.element_type)

    @property
    def signed_amount(self) -> Decimal:
        """Montant signé selon l'effet sur le net (+prime, -retenue/cotisation sal.)."""
        if self.element_type == self.TYPE_BONUS:
            return self.amount
        if self.is_employer:
            return Decimal("0")
        return -self.amount

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "payslip_id":    self.payslip_id,
            "element_type":  self.element_type,
            "type_label":    self.type_label,
            "label":         self.label,
            "is_employer":   self.is_employer,
            "amount":        float(self.amount),
            "rate":          float(self.rate) if self.rate is not None else None,
            "base_amount":   float(self.base_amount) if self.base_amount is not None else None,
            "signed_amount": float(self.signed_amount),
        }

    # ── Dunder ────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        employer_flag = " [patronal]" if self.is_employer else ""
        return (
            f"<PayElement id={self.id} "
            f"{self.element_type}{employer_flag} "
            f"'{self.label}' {self.amount}>"
        )
