"""
Modèles : EvaluationCampaign · Evaluation · EvaluationItem
Évaluations de performance — SQLAlchemy 2.0 (Mapped / mapped_column)

EvaluationCampagne définit une vague d'évaluation (annuelle, semestrielle,
fin de période d'essai...) pour l'ensemble ou une partie de l'entreprise.

Evaluation est la fiche d'évaluation individuelle d'un employé dans le
cadre d'une campagne — workflow en plusieurs étapes : rédaction manager,
relecture employé, finalisation.

EvaluationItem détaille les critères évalués (compétences, comportements)
en complément des Objective (qui sont évalués séparément mais consolidés
dans le score global de l'Evaluation).

Relations principales :
  - campaign  (N:1, Evaluation) → campagne de rattachement
  - employee  (N:1, Evaluation) → personne évaluée
  - evaluator (N:1, Evaluation) → personne qui évalue (généralement le manager)
  - items     (1:N, Evaluation) → critères détaillés
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
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.extensions import db

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.objective import Objective
    from app.models.organization import Company
    from app.models.user import User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================================
# EvaluationCampaign
# =============================================================================

class EvaluationCampaign(db.Model):
    """
    Campagne d'évaluation lancée par l'entreprise.

    `period_type` catégorise la nature du cycle ('annual', 'semester',
    'quarterly', 'probation', 'custom') — la période d'essai a son propre
    type car son déclenchement est individuel (date d'embauche + N mois),
    pas calendaire comme les campagnes classiques.

    `objective_deadline` distingue la date limite de définition des
    objectifs (en début de période) de `end_date` qui marque la fin de
    la campagne d'évaluation elle-même.
    """

    __tablename__ = "evaluation_campaigns"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_campaigns_end_after_start"),
        CheckConstraint(
            "period_type IN ('annual','semester','quarterly','probation','custom')",
            name="ck_campaigns_period_type_valid",
        ),
        Index("ix_campaigns_company_id", "company_id"),
        Index("ix_campaigns_active", "company_id", "is_active"),
    )

    PERIOD_ANNUAL    = "annual"
    PERIOD_SEMESTER  = "semester"
    PERIOD_QUARTERLY = "quarterly"
    PERIOD_PROBATION = "probation"
    PERIOD_CUSTOM    = "custom"

    PERIOD_TYPES: tuple[str, ...] = (
        PERIOD_ANNUAL, PERIOD_SEMESTER, PERIOD_QUARTERLY, PERIOD_PROBATION, PERIOD_CUSTOM,
    )

    # ── Identifiants ──────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    created_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    # ── Informations ──────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    period_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    period_type: Mapped[str] = mapped_column(String(20), nullable=False, default=PERIOD_ANNUAL)

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    objective_deadline: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    is_active: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    company: Mapped["Company"] = relationship(
        "Company", foreign_keys=[company_id], lazy="select"
    )
    created_by: Mapped["User"] = relationship(
        "User", foreign_keys=[created_by_id], lazy="select"
    )
    evaluations: Mapped[List["Evaluation"]] = relationship(
        "Evaluation", back_populates="campaign", cascade="all, delete-orphan", lazy="dynamic"
    )
    objectives: Mapped[List["Objective"]] = relationship(
        "Objective", back_populates="campaign", lazy="dynamic"
    )

    # ── Validation ────────────────────────────────────────────────────────────
    @validates("name")
    def _strip_name(self, key: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Le nom de la campagne ne peut pas être vide.")
        return value.strip()

    @validates("period_type")
    def _validate_period_type(self, key: str, value: str) -> str:
        if value not in self.PERIOD_TYPES:
            raise ValueError(f"Type de période invalide : '{value}'.")
        return value

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def is_open(self) -> bool:
        """True si la campagne est active et dans sa période calendaire."""
        today = date.today()
        return self.is_active and self.start_date <= today <= self.end_date

    @property
    def is_past_objective_deadline(self) -> bool:
        return self.objective_deadline is not None and date.today() > self.objective_deadline

    @property
    def evaluation_count(self) -> int:
        return self.evaluations.count()

    @property
    def completed_count(self) -> int:
        from app.models.evaluation import Evaluation as _Eval
        return self.evaluations.filter(_Eval.status == _Eval.STATUS_COMPLETED).count()

    @property
    def completion_rate_pct(self) -> float:
        total = self.evaluation_count
        if total == 0:
            return 0.0
        return round((self.completed_count / total) * 100, 1)

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_or_404(cls, campaign_id: int) -> "EvaluationCampaign":
        campaign = db.session.get(cls, campaign_id)
        if campaign is None:
            from flask import abort
            abort(404, description="Campagne d'évaluation introuvable.")
        return campaign

    @classmethod
    def active_in_company(cls, company_id: int):
        """Requête (non exécutée) des campagnes actives d'une entreprise."""
        return db.select(cls).where(
            cls.company_id == company_id, cls.is_active.is_(True)
        ).order_by(cls.start_date.desc())

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self, include_stats: bool = False) -> dict:
        data: dict = {
            "id": self.id,
            "company_id": self.company_id,
            "name": self.name,
            "description": self.description,
            "period_year": self.period_year,
            "period_type": self.period_type,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "objective_deadline": self.objective_deadline.isoformat() if self.objective_deadline else None,
            "is_active": self.is_active,
            "is_open": self.is_open,
            "created_at": self.created_at.isoformat(),
        }
        if include_stats:
            data["evaluation_count"] = self.evaluation_count
            data["completed_count"] = self.completed_count
            data["completion_rate_pct"] = self.completion_rate_pct
        return data

    def __repr__(self) -> str:
        return f"<EvaluationCampaign id={self.id} {self.name!r} ({self.period_year})>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, EvaluationCampaign) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


# =============================================================================
# Evaluation
# =============================================================================

class Evaluation(db.Model):
    """
    Fiche d'évaluation individuelle d'un employé pour une campagne donnée.

    Workflow (champ `status`) :
        draft ──► in_progress ──► employee_review ──► completed ──► archived

    Les colonnes `*_signature_hash` stockent un hash SHA-256 du contenu
    de l'évaluation au moment de la signature électronique — preuve
    d'intégrité simple, pas une signature cryptographique au sens légal
    strict, mais suffisante pour détecter une modification a posteriori.

    Un employé ne peut avoir qu'une seule Evaluation par campagne
    (contrainte d'unicité) — logique, une campagne = un cycle = une fiche.
    """

    __tablename__ = "evaluations"
    __table_args__ = (
        CheckConstraint(
            "overall_score IS NULL OR overall_score BETWEEN 0 AND 5",
            name="ck_evaluations_score_valid",
        ),
        CheckConstraint(
            "status IN ('draft','in_progress','employee_review','completed','archived')",
            name="ck_evaluations_status_valid",
        ),
        CheckConstraint(
            "employee_id <> evaluator_id",
            name="ck_evaluations_employee_differs_evaluator",
        ),
        UniqueConstraint("campaign_id", "employee_id", name="uq_evaluations_campaign_employee"),
        Index("ix_evaluations_campaign_id", "campaign_id"),
        Index("ix_evaluations_employee_id", "employee_id"),
        Index("ix_evaluations_evaluator_id", "evaluator_id"),
        Index("ix_evaluations_status", "status"),
    )

    # ── Statuts (constantes) ──────────────────────────────────────────────────
    STATUS_DRAFT            = "draft"
    STATUS_IN_PROGRESS       = "in_progress"
    STATUS_EMPLOYEE_REVIEW   = "employee_review"
    STATUS_COMPLETED         = "completed"
    STATUS_ARCHIVED          = "archived"

    STATUSES: tuple[str, ...] = (
        STATUS_DRAFT, STATUS_IN_PROGRESS, STATUS_EMPLOYEE_REVIEW,
        STATUS_COMPLETED, STATUS_ARCHIVED,
    )

    # ── Identifiants ──────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── Rattachements ─────────────────────────────────────────────────────────
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    evaluator_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_DRAFT)

    # ── Scores et synthèse ────────────────────────────────────────────────────
    overall_score: Mapped[Optional[float]] = mapped_column(Numeric(4, 2), nullable=True)
    manager_overall_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    employee_overall_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    strengths: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    areas_for_improvement: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    development_plan: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Plan de Développement Individuel (PDI)"
    )

    # ── Dates clés du workflow ─────────────────────────────────────────────────
    sent_to_evaluator_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    evaluator_submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_to_employee_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    employee_acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Signatures (hash d'intégrité) ─────────────────────────────────────────
    employee_signature_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    manager_signature_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    campaign: Mapped["EvaluationCampaign"] = relationship(
        "EvaluationCampaign", back_populates="evaluations", lazy="joined"
    )
    employee: Mapped["Employee"] = relationship(
        "Employee", foreign_keys=[employee_id], lazy="joined"
    )
    evaluator: Mapped["Employee"] = relationship(
        "Employee", foreign_keys=[evaluator_id], lazy="joined"
    )
    items: Mapped[List["EvaluationItem"]] = relationship(
        "EvaluationItem", back_populates="evaluation",
        cascade="all, delete-orphan", lazy="dynamic",
        order_by="EvaluationItem.sort_order",
    )

    # ── Validation ────────────────────────────────────────────────────────────
    @validates("status")
    def _validate_status(self, key: str, value: str) -> str:
        if value not in self.STATUSES:
            raise ValueError(f"Statut invalide : '{value}'.")
        return value

    @validates("overall_score")
    def _validate_score(self, key: str, value: Optional[float]) -> Optional[float]:
        if value is not None and not (0 <= value <= 5):
            raise ValueError("Le score global doit être compris entre 0 et 5.")
        return value

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def is_signed_by_employee(self) -> bool:
        return self.employee_signature_hash is not None

    @property
    def is_signed_by_manager(self) -> bool:
        return self.manager_signature_hash is not None

    @property
    def is_fully_signed(self) -> bool:
        return self.is_signed_by_employee and self.is_signed_by_manager

    @property
    def computed_score_from_items(self) -> Optional[float]:
        """
        Score pondéré calculé à partir des EvaluationItem ayant une note
        manager. Retourne None si aucun item noté.
        """
        items = [i for i in self.items if i.manager_score is not None]
        if not items:
            return None
        total_weight = sum(float(i.weight) for i in items)
        if total_weight == 0:
            return None
        weighted_sum = sum(float(i.manager_score) * float(i.weight) for i in items)
        return round(weighted_sum / total_weight, 2)

    # ── Méthodes d'instance — transitions de workflow ─────────────────────────
    def send_to_evaluator(self) -> None:
        if self.status != self.STATUS_DRAFT:
            raise ValueError(f"Impossible d'envoyer à l'évaluateur depuis le statut '{self.status}'.")
        self.status = self.STATUS_IN_PROGRESS
        self.sent_to_evaluator_at = _utcnow()

    def submit_by_evaluator(self) -> None:
        if self.status != self.STATUS_IN_PROGRESS:
            raise ValueError(f"Impossible de soumettre depuis le statut '{self.status}'.")
        self.status = self.STATUS_EMPLOYEE_REVIEW
        self.evaluator_submitted_at = _utcnow()
        self.sent_to_employee_at = _utcnow()

    def acknowledge_by_employee(self, signature_hash: Optional[str] = None) -> None:
        if self.status != self.STATUS_EMPLOYEE_REVIEW:
            raise ValueError(f"Impossible d'accuser réception depuis le statut '{self.status}'.")
        self.employee_acknowledged_at = _utcnow()
        if signature_hash:
            self.employee_signature_hash = signature_hash

    def finalize(self, signature_hash: Optional[str] = None) -> None:
        if self.status != self.STATUS_EMPLOYEE_REVIEW:
            raise ValueError(f"Impossible de finaliser depuis le statut '{self.status}'.")
        self.status = self.STATUS_COMPLETED
        self.completed_at = _utcnow()
        if signature_hash:
            self.manager_signature_hash = signature_hash
        if self.overall_score is None:
            self.overall_score = self.computed_score_from_items

    def archive(self) -> None:
        if self.status != self.STATUS_COMPLETED:
            raise ValueError("Seule une évaluation terminée peut être archivée.")
        self.status = self.STATUS_ARCHIVED

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_or_404(cls, evaluation_id: int) -> "Evaluation":
        evaluation = db.session.get(cls, evaluation_id)
        if evaluation is None:
            from flask import abort
            abort(404, description="Évaluation introuvable.")
        return evaluation

    @classmethod
    def for_employee(cls, employee_id: int):
        """Requête (non exécutée) de l'historique des évaluations d'un employé."""
        return db.select(cls).where(
            cls.employee_id == employee_id
        ).order_by(cls.created_at.desc())

    @classmethod
    def pending_for_evaluator(cls, evaluator_id: int):
        """Requête (non exécutée) des évaluations à rédiger par un évaluateur."""
        return db.select(cls).where(
            cls.evaluator_id == evaluator_id,
            cls.status == cls.STATUS_IN_PROGRESS,
        ).order_by(cls.sent_to_evaluator_at.asc())

    @classmethod
    def pending_employee_review(cls, employee_id: int):
        """Requête (non exécutée) des évaluations en attente de relecture par l'employé
        (non encore signées — employee_acknowledged_at IS NULL)."""
        return db.select(cls).where(
            cls.employee_id == employee_id,
            cls.status == cls.STATUS_EMPLOYEE_REVIEW,
            cls.employee_acknowledged_at.is_(None),
        ).order_by(cls.sent_to_employee_at.asc())

    @classmethod
    def submitted_awaiting_employee(cls, evaluator_id: int):
        """Requête (non exécutée) des évaluations soumises par cet évaluateur,
        statut employee_review — l'employé doit encore relire/signer."""
        return db.select(cls).where(
            cls.evaluator_id == evaluator_id,
            cls.status == cls.STATUS_EMPLOYEE_REVIEW,
        ).order_by(cls.evaluator_submitted_at.asc())

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self, include_items: bool = False) -> dict:
        data: dict = {
            "id": self.id,
            "campaign_id": self.campaign_id,
            "campaign_name": self.campaign.name if self.campaign else None,
            "employee_id": self.employee_id,
            "employee_name": self.employee.full_name if self.employee else None,
            "evaluator_id": self.evaluator_id,
            "evaluator_name": self.evaluator.full_name if self.evaluator else None,
            "status": self.status,
            "overall_score": float(self.overall_score) if self.overall_score is not None else None,
            "strengths": self.strengths,
            "areas_for_improvement": self.areas_for_improvement,
            "development_plan": self.development_plan,
            "is_fully_signed": self.is_fully_signed,
            "sent_to_evaluator_at": self.sent_to_evaluator_at.isoformat() if self.sent_to_evaluator_at else None,
            "evaluator_submitted_at": self.evaluator_submitted_at.isoformat() if self.evaluator_submitted_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat(),
        }
        if include_items:
            data["items"] = [item.to_dict() for item in self.items]
        return data

    def __repr__(self) -> str:
        return f"<Evaluation id={self.id} employee={self.employee_id} [{self.status}]>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Evaluation) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


# =============================================================================
# EvaluationItem
# =============================================================================

class EvaluationItem(db.Model):
    """
    Critère détaillé d'une fiche d'évaluation.

    `category` distingue les types de critères ('competence', 'behavior',
    'objective') — la catégorie 'objective' permet de lier un item à un
    Objective existant pour consolidation, sans dupliquer toute la logique
    de notation déjà présente sur Objective.

    Le double système manager_score/employee_score reproduit au niveau
    item le même principe d'auto-évaluation comparée que sur Objective.
    """

    __tablename__ = "evaluation_items"
    __table_args__ = (
        CheckConstraint("weight > 0", name="ck_evaluation_items_weight_positive"),
        CheckConstraint(
            "manager_score IS NULL OR manager_score BETWEEN 0 AND 5",
            name="ck_evaluation_items_manager_score_valid",
        ),
        CheckConstraint(
            "employee_score IS NULL OR employee_score BETWEEN 0 AND 5",
            name="ck_evaluation_items_employee_score_valid",
        ),
        Index("ix_evaluation_items_evaluation_id", "evaluation_id"),
    )

    CATEGORY_COMPETENCE = "competence"
    CATEGORY_BEHAVIOR   = "behavior"
    CATEGORY_OBJECTIVE  = "objective"

    CATEGORIES: tuple[str, ...] = (CATEGORY_COMPETENCE, CATEGORY_BEHAVIOR, CATEGORY_OBJECTIVE)

    # ── Identifiants ──────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    evaluation_id: Mapped[int] = mapped_column(
        ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False
    )

    # ── Contenu ───────────────────────────────────────────────────────────────
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    weight: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=1)

    # ── Notation ──────────────────────────────────────────────────────────────
    manager_score: Mapped[Optional[float]] = mapped_column(Numeric(4, 2), nullable=True)
    employee_score: Mapped[Optional[float]] = mapped_column(Numeric(4, 2), nullable=True)
    manager_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    evaluation: Mapped["Evaluation"] = relationship(
        "Evaluation", back_populates="items", lazy="select"
    )

    # ── Validation ────────────────────────────────────────────────────────────
    @validates("label")
    def _strip_label(self, key: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Le libellé du critère ne peut pas être vide.")
        return value.strip()

    @validates("category")
    def _validate_category(self, key: str, value: str) -> str:
        if value not in self.CATEGORIES:
            raise ValueError(f"Catégorie invalide : '{value}'. Valeurs acceptées : {self.CATEGORIES}")
        return value

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def score_gap(self) -> Optional[float]:
        if self.manager_score is None or self.employee_score is None:
            return None
        return round(float(self.employee_score) - float(self.manager_score), 2)

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "evaluation_id": self.evaluation_id,
            "category": self.category,
            "label": self.label,
            "description": self.description,
            "weight": float(self.weight),
            "manager_score": float(self.manager_score) if self.manager_score is not None else None,
            "employee_score": float(self.employee_score) if self.employee_score is not None else None,
            "score_gap": self.score_gap,
            "manager_comment": self.manager_comment,
            "sort_order": self.sort_order,
        }

    def __repr__(self) -> str:
        return f"<EvaluationItem id={self.id} {self.label!r} [{self.category}]>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, EvaluationItem) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)