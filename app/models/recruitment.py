"""
Modèles : Recrutement — JobPosting · Candidate · Application · Interview
SQLAlchemy 2.0 (Mapped / mapped_column)

JobPosting   Offre d'emploi publiée par l'entreprise (rattachée à un département
             et un poste cible).

Candidate    Candidat externe : identité, coordonnées, CV et source de provenance.
             Un même candidat peut postuler à plusieurs offres.

Application  Candidature : lien entre un Candidate et un JobPosting, avec son propre
             cycle de vie (reçue → présélectionnée → entretien → offre → embauchée
             ou refusée).

Interview    Entretien planifié pour une candidature : date, interviewer (Employee),
             type, notes et décision.

Relations principales :
  - company      (N:1, JobPosting)   → entreprise qui publie l'offre
  - department   (N:1, JobPosting)   → département qui recrute
  - position     (N:1, JobPosting)   → poste cible (référentiel)
  - applications (1:N, JobPosting)   → candidatures reçues
  - applications (1:N, Candidate)    → candidatures soumises par ce candidat
  - job_posting  (N:1, Application)  → offre concernée
  - candidate    (N:1, Application)  → candidat concerné
  - interviews   (1:N, Application)  → entretiens liés à cette candidature
  - application  (N:1, Interview)    → candidature concernée
  - interviewer  (N:1, Interview)    → employé qui conduit l'entretien
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
    from app.models.department import Department
    from app.models.employee import Employee
    from app.models.organization import Company, Position


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================================
# JobPosting — Offre d'emploi
# =============================================================================

class JobPosting(db.Model):
    """
    Offre d'emploi publiée par l'entreprise.

    Cycle de vie du statut :
        draft  → open  → closed
               ↘ cancelled (depuis tout statut)

    `headcount` indique le nombre de postes à pourvoir sur cette offre.
    `published_at` est renseigné automatiquement lors du passage à 'open'.
    `closing_date` est la date limite de dépôt des candidatures (nullable).
    """

    __tablename__ = "job_postings"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','open','closed','cancelled')",
            name="ck_job_postings_status_valid",
        ),
        CheckConstraint(
            "headcount IS NULL OR headcount > 0",
            name="ck_job_postings_headcount_positive",
        ),
        CheckConstraint(
            "closing_date IS NULL OR published_at IS NULL OR closing_date >= published_at",
            name="ck_job_postings_closing_after_publish",
        ),
        Index("ix_job_postings_company_id", "company_id"),
        Index("ix_job_postings_department_id", "department_id"),
        Index("ix_job_postings_status", "company_id", "status"),
    )

    # ── Statuts ───────────────────────────────────────────────────────────────
    STATUS_DRAFT     = "draft"
    STATUS_OPEN      = "open"
    STATUS_CLOSED    = "closed"
    STATUS_CANCELLED = "cancelled"
    STATUSES = (STATUS_DRAFT, STATUS_OPEN, STATUS_CLOSED, STATUS_CANCELLED)

    # ── Identifiant ───────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── Rattachements ─────────────────────────────────────────────────────────
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False,
    )
    department_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), nullable=True,
        comment="Département qui recrute",
    )
    position_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("positions.id", ondelete="SET NULL"), nullable=True,
        comment="Poste cible dans le référentiel RH",
    )
    created_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        comment="Utilisateur ayant créé l'offre (RH ou Admin)",
    )

    # ── Informations de l'offre ───────────────────────────────────────────────
    title: Mapped[str] = mapped_column(
        String(200), nullable=False,
        comment="Intitulé du poste tel qu'affiché aux candidats",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Description complète du poste, missions, profil recherché",
    )
    requirements: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Compétences et qualifications requises",
    )
    location: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True,
        comment="Lieu de travail (ville, télétravail…)",
    )
    contract_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True,
        comment="Type de contrat proposé (CDI, CDD, stage, alternance…)",
    )
    salary_min: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True,
        comment="Fourchette salariale basse (brut annuel €)",
    )
    salary_max: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True,
        comment="Fourchette salariale haute (brut annuel €)",
    )
    headcount: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, default=1,
        comment="Nombre de postes à pourvoir",
    )

    # ── Cycle de vie ──────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=STATUS_DRAFT,
    )
    published_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    closing_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True,
        comment="Date limite de dépôt des candidatures",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow,
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    company: Mapped["Company"] = relationship(
        "Company", foreign_keys=[company_id], lazy="select",
    )
    department: Mapped[Optional["Department"]] = relationship(
        "Department", foreign_keys=[department_id], lazy="joined",
    )
    position: Mapped[Optional["Position"]] = relationship(
        "Position", foreign_keys=[position_id], lazy="joined",
    )
    applications: Mapped[List["Application"]] = relationship(
        "Application", back_populates="job_posting",
        cascade="all, delete-orphan", lazy="dynamic",
    )

    # ── Validation ────────────────────────────────────────────────────────────
    @validates("status")
    def _validate_status(self, key: str, value: str) -> str:
        if value not in self.STATUSES:
            raise ValueError(
                f"Statut d'offre invalide : {value!r}. "
                f"Valeurs acceptées : {self.STATUSES}"
            )
        return value

    @validates("title")
    def _validate_title(self, key: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Le titre de l'offre ne peut pas être vide.")
        return value.strip()

    # ── Transitions de statut ─────────────────────────────────────────────────
    def publish(self) -> None:
        """Publie l'offre (draft → open)."""
        if self.status != self.STATUS_DRAFT:
            raise ValueError(
                f"Seules les offres en brouillon peuvent être publiées (statut actuel : {self.status!r})."
            )
        self.status = self.STATUS_OPEN
        self.published_at = self.published_at or date.today()

    def close(self) -> None:
        """Clôture l'offre (open → closed)."""
        if self.status != self.STATUS_OPEN:
            raise ValueError(
                f"Seules les offres ouvertes peuvent être clôturées (statut actuel : {self.status!r})."
            )
        self.status = self.STATUS_CLOSED

    def cancel(self) -> None:
        """Annule l'offre (tout statut sauf cancelled)."""
        if self.status == self.STATUS_CANCELLED:
            raise ValueError("L'offre est déjà annulée.")
        self.status = self.STATUS_CANCELLED

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def application_count(self) -> int:
        return self.applications.count()

    @property
    def active_application_count(self) -> int:
        return self.applications.filter(
            Application.status != Application.STATUS_REJECTED
        ).count()

    @property
    def is_open(self) -> bool:
        return self.status == self.STATUS_OPEN

    @property
    def salary_range(self) -> Optional[str]:
        if self.salary_min and self.salary_max:
            return f"{int(self.salary_min):,} – {int(self.salary_max):,} €"
        if self.salary_min:
            return f"À partir de {int(self.salary_min):,} €"
        return None

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_or_404(cls, job_posting_id: int) -> "JobPosting":
        obj = db.session.get(cls, job_posting_id)
        if obj is None:
            from flask import abort
            abort(404, description="Offre d'emploi introuvable.")
        return obj

    @classmethod
    def open_in_company(cls, company_id: int):
        """Requête (non exécutée) des offres ouvertes d'une entreprise."""
        return (
            db.select(cls)
            .where(cls.company_id == company_id, cls.status == cls.STATUS_OPEN)
            .order_by(cls.published_at.desc())
        )

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "company_id":   self.company_id,
            "department_id": self.department_id,
            "department":   self.department.name if self.department else None,
            "position_id":  self.position_id,
            "title":        self.title,
            "description":  self.description,
            "requirements": self.requirements,
            "location":     self.location,
            "contract_type": self.contract_type,
            "salary_min":   float(self.salary_min) if self.salary_min else None,
            "salary_max":   float(self.salary_max) if self.salary_max else None,
            "headcount":    self.headcount,
            "status":       self.status,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "closing_date": self.closing_date.isoformat() if self.closing_date else None,
            "created_at":   self.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<JobPosting id={self.id} {self.title!r} status={self.status}>"


# =============================================================================
# Candidate — Candidat externe
# =============================================================================

class Candidate(db.Model):
    """
    Candidat externe : identité, coordonnées, CV et source de provenance.

    `source` indique comment le candidat a connu l'offre :
        linkedin / jobboard / referral / spontaneous / website / other

    Un même candidat peut postuler à plusieurs offres via la table Application.
    Le CV peut être stocké comme chemin de fichier (`cv_path`) ou comme texte brut
    (`cv_text`) selon la méthode de collecte. Les deux champs sont mutuellement
    optionnels mais complémentaires.
    """

    __tablename__ = "candidates"
    __table_args__ = (
        CheckConstraint(
            "source IN ('linkedin','jobboard','referral','spontaneous','website','other')",
            name="ck_candidates_source_valid",
        ),
        Index("ix_candidates_email", "email"),
        Index("ix_candidates_last_name", "last_name"),
    )

    # ── Sources ───────────────────────────────────────────────────────────────
    SOURCE_LINKEDIN    = "linkedin"
    SOURCE_JOBBOARD    = "jobboard"
    SOURCE_REFERRAL    = "referral"
    SOURCE_SPONTANEOUS = "spontaneous"
    SOURCE_WEBSITE     = "website"
    SOURCE_OTHER       = "other"
    SOURCES = (
        SOURCE_LINKEDIN, SOURCE_JOBBOARD, SOURCE_REFERRAL,
        SOURCE_SPONTANEOUS, SOURCE_WEBSITE, SOURCE_OTHER,
    )

    # ── Identifiant ───────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── Identité ──────────────────────────────────────────────────────────────
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name:  Mapped[str] = mapped_column(String(100), nullable=False)
    email:      Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Email du candidat — identifiant naturel pour la déduplication",
    )
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # ── CV ────────────────────────────────────────────────────────────────────
    cv_path: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True,
        comment="Chemin relatif vers le fichier CV (PDF, DOCX…)",
    )
    cv_text: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Texte brut du CV (copié-collé ou extrait)",
    )

    # ── Provenance & Notes ────────────────────────────────────────────────────
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SOURCE_OTHER,
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Notes internes RH (non visibles par le candidat)",
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow,
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    applications: Mapped[List["Application"]] = relationship(
        "Application", back_populates="candidate",
        cascade="all, delete-orphan", lazy="dynamic",
    )

    # ── Validation ────────────────────────────────────────────────────────────
    @validates("source")
    def _validate_source(self, key: str, value: str) -> str:
        if value not in self.SOURCES:
            raise ValueError(
                f"Source invalide : {value!r}. Valeurs acceptées : {self.SOURCES}"
            )
        return value

    @validates("email")
    def _normalize_email(self, key: str, value: str) -> str:
        return value.strip().lower() if value else value

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def has_cv(self) -> bool:
        return bool(self.cv_path or self.cv_text)

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_or_404(cls, candidate_id: int) -> "Candidate":
        obj = db.session.get(cls, candidate_id)
        if obj is None:
            from flask import abort
            abort(404, description="Candidat introuvable.")
        return obj

    @classmethod
    def find_by_email(cls, email: str) -> Optional["Candidate"]:
        return db.session.execute(
            db.select(cls).where(cls.email == email.strip().lower())
        ).scalar_one_or_none()

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id":         self.id,
            "full_name":  self.full_name,
            "first_name": self.first_name,
            "last_name":  self.last_name,
            "email":      self.email,
            "phone":      self.phone,
            "source":     self.source,
            "has_cv":     self.has_cv,
            "cv_path":    self.cv_path,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<Candidate id={self.id} {self.full_name!r} {self.email!r}>"


# =============================================================================
# Application — Candidature
# =============================================================================

class Application(db.Model):
    """
    Candidature : lien entre un Candidate et un JobPosting.

    Cycle de vie du statut :
        recue → preselectionnee → entretien → offre → embauchee
              ↘ refusee  (depuis tout statut sauf embauchee)

    Un candidat ne peut déposer qu'une seule candidature par offre
    (contrainte UniqueConstraint sur candidate_id + job_posting_id).

    `applied_at` est la date effective de soumission de la candidature
    (peut être antérieure à `created_at` pour les candidatures importées).

    `hired_employee_id` est nullable et ne doit être renseigné qu'après
    création effective de la fiche employé dans le module RH. Il sert de
    lien de traçabilité recrutement → dossier employé.
    """

    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('recue','preselectionnee','entretien','offre','refusee','embauchee')",
            name="ck_applications_status_valid",
        ),
        UniqueConstraint(
            "candidate_id", "job_posting_id",
            name="uq_applications_candidate_per_posting",
        ),
        Index("ix_applications_job_posting_id", "job_posting_id"),
        Index("ix_applications_candidate_id", "candidate_id"),
        Index("ix_applications_status", "job_posting_id", "status"),
        Index("ix_applications_hired_employee_id", "hired_employee_id"),
    )

    # ── Statuts ───────────────────────────────────────────────────────────────
    STATUS_RECEIVED     = "recue"
    STATUS_PRESCREENED  = "preselectionnee"
    STATUS_INTERVIEW    = "entretien"
    STATUS_OFFER        = "offre"
    STATUS_REJECTED     = "refusee"
    STATUS_HIRED        = "embauchee"
    STATUSES = (
        STATUS_RECEIVED, STATUS_PRESCREENED, STATUS_INTERVIEW,
        STATUS_OFFER, STATUS_REJECTED, STATUS_HIRED,
    )

    # Libellés français pour l'affichage
    STATUS_LABELS: dict[str, str] = {
        STATUS_RECEIVED:    "Reçue",
        STATUS_PRESCREENED: "Présélectionnée",
        STATUS_INTERVIEW:   "Entretien",
        STATUS_OFFER:       "Offre",
        STATUS_REJECTED:    "Refusée",
        STATUS_HIRED:       "Embauchée",
    }

    # ── Identifiant ───────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── Rattachements ─────────────────────────────────────────────────────────
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False,
    )
    job_posting_id: Mapped[int] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False,
    )
    # Renseigné uniquement après création effective de la fiche employé
    hired_employee_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), nullable=True,
        comment="Fiche employé créée à l'issue du recrutement — NULL jusqu'à sa création",
    )

    # ── Cycle de vie ──────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=STATUS_RECEIVED,
    )
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        comment="Date effective de soumission de la candidature",
    )

    # ── Notes internes ────────────────────────────────────────────────────────
    notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Notes RH internes sur cette candidature",
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Motif de refus (communication possible au candidat)",
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow,
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    candidate: Mapped["Candidate"] = relationship(
        "Candidate", back_populates="applications", lazy="joined",
    )
    job_posting: Mapped["JobPosting"] = relationship(
        "JobPosting", back_populates="applications", lazy="joined",
    )
    interviews: Mapped[List["Interview"]] = relationship(
        "Interview", back_populates="application",
        cascade="all, delete-orphan", lazy="dynamic",
    )
    hired_employee: Mapped[Optional["Employee"]] = relationship(
        "Employee", foreign_keys=[hired_employee_id], lazy="select",
    )

    # ── Validation ────────────────────────────────────────────────────────────
    @validates("status")
    def _validate_status(self, key: str, value: str) -> str:
        if value not in self.STATUSES:
            raise ValueError(
                f"Statut de candidature invalide : {value!r}. "
                f"Valeurs acceptées : {self.STATUSES}"
            )
        return value

    # ── Transitions de statut ─────────────────────────────────────────────────
    def prescreen(self) -> None:
        """Présélectionne la candidature (recue → preselectionnee)."""
        if self.status != self.STATUS_RECEIVED:
            raise ValueError(
                f"Seules les candidatures reçues peuvent être présélectionnées "
                f"(statut actuel : {self.status!r})."
            )
        self.status = self.STATUS_PRESCREENED

    def advance_to_interview(self) -> None:
        """Convoque à un entretien (preselectionnee → entretien)."""
        if self.status != self.STATUS_PRESCREENED:
            raise ValueError(
                f"La candidature doit être présélectionnée avant de passer en entretien "
                f"(statut actuel : {self.status!r})."
            )
        self.status = self.STATUS_INTERVIEW

    def make_offer(self) -> None:
        """Émet une offre d'embauche (entretien → offre)."""
        if self.status != self.STATUS_INTERVIEW:
            raise ValueError(
                f"L'offre ne peut être émise qu'après entretien "
                f"(statut actuel : {self.status!r})."
            )
        self.status = self.STATUS_OFFER

    def hire(self) -> None:
        """Finalise l'embauche (offre → embauchee)."""
        if self.status != self.STATUS_OFFER:
            raise ValueError(
                f"L'embauche ne peut être confirmée qu'après émission d'une offre "
                f"(statut actuel : {self.status!r})."
            )
        self.status = self.STATUS_HIRED

    def reject(self, reason: Optional[str] = None) -> None:
        """Refuse la candidature (depuis tout statut sauf embauchee)."""
        if self.status == self.STATUS_HIRED:
            raise ValueError("Une candidature embauchée ne peut pas être refusée.")
        self.status = self.STATUS_REJECTED
        if reason:
            self.rejection_reason = reason

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def status_label(self) -> str:
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def interview_count(self) -> int:
        return self.interviews.count()

    @property
    def is_active(self) -> bool:
        return self.status not in (self.STATUS_REJECTED, self.STATUS_HIRED)

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_or_404(cls, application_id: int) -> "Application":
        obj = db.session.get(cls, application_id)
        if obj is None:
            from flask import abort
            abort(404, description="Candidature introuvable.")
        return obj

    @classmethod
    def for_posting(cls, job_posting_id: int):
        """Requête (non exécutée) des candidatures pour une offre donnée."""
        return (
            db.select(cls)
            .where(cls.job_posting_id == job_posting_id)
            .order_by(cls.applied_at.desc())
        )

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "candidate_id":     self.candidate_id,
            "candidate_name":   self.candidate.full_name if self.candidate else None,
            "job_posting_id":   self.job_posting_id,
            "job_title":        self.job_posting.title if self.job_posting else None,
            "status":           self.status,
            "status_label":     self.status_label,
            "applied_at":       self.applied_at.isoformat(),
            "notes":            self.notes,
            "rejection_reason": self.rejection_reason,
            "interview_count":  self.interview_count,
            "hired_employee_id": self.hired_employee_id,
            "created_at":       self.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return (
            f"<Application id={self.id} "
            f"candidate={self.candidate_id} "
            f"posting={self.job_posting_id} "
            f"status={self.status!r}>"
        )


# =============================================================================
# Interview — Entretien
# =============================================================================

class Interview(db.Model):
    """
    Entretien planifié pour une candidature.

    `interviewer_id` référence un Employee — le collaborateur qui conduit
    l'entretien. Nullable pour permettre la planification avant affectation.

    `decision` reflète la conclusion de l'interviewer à l'issue de l'entretien :
        pending  — entretien non encore réalisé ou décision en attente
        proceed  — recommande de poursuivre le processus
        hold     — à confirmer / deuxième avis nécessaire
        reject   — recommande de refuser la candidature

    `rating` est une note globale du candidat sur 5 (optionnelle).
    """

    __tablename__ = "interviews"
    __table_args__ = (
        CheckConstraint(
            "interview_type IN ('phone','video','onsite','technical','hr')",
            name="ck_interviews_type_valid",
        ),
        CheckConstraint(
            "decision IN ('pending','proceed','hold','reject')",
            name="ck_interviews_decision_valid",
        ),
        CheckConstraint(
            "rating IS NULL OR (rating >= 1 AND rating <= 5)",
            name="ck_interviews_rating_range",
        ),
        CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes > 0",
            name="ck_interviews_duration_positive",
        ),
        Index("ix_interviews_application_id", "application_id"),
        Index("ix_interviews_interviewer_id", "interviewer_id"),
        Index("ix_interviews_scheduled_at", "scheduled_at"),
    )

    # ── Types d'entretien ─────────────────────────────────────────────────────
    TYPE_PHONE     = "phone"
    TYPE_VIDEO     = "video"
    TYPE_ONSITE    = "onsite"
    TYPE_TECHNICAL = "technical"
    TYPE_HR        = "hr"
    TYPES = (TYPE_PHONE, TYPE_VIDEO, TYPE_ONSITE, TYPE_TECHNICAL, TYPE_HR)

    TYPE_LABELS: dict[str, str] = {
        TYPE_PHONE:     "Téléphonique",
        TYPE_VIDEO:     "Visioconférence",
        TYPE_ONSITE:    "Présentiel",
        TYPE_TECHNICAL: "Technique",
        TYPE_HR:        "RH",
    }

    # ── Décisions ─────────────────────────────────────────────────────────────
    DECISION_PENDING = "pending"
    DECISION_PROCEED = "proceed"
    DECISION_HOLD    = "hold"
    DECISION_REJECT  = "reject"
    DECISIONS = (DECISION_PENDING, DECISION_PROCEED, DECISION_HOLD, DECISION_REJECT)

    # ── Identifiant ───────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── Rattachements ─────────────────────────────────────────────────────────
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False,
    )
    interviewer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), nullable=True,
        comment="Employé qui conduit l'entretien",
    )

    # ── Planification ─────────────────────────────────────────────────────────
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment="Date et heure planifiées de l'entretien",
    )
    duration_minutes: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, default=60,
        comment="Durée prévue en minutes",
    )
    location: Mapped[Optional[str]] = mapped_column(
        String(300), nullable=True,
        comment="Lieu (salle, lien de visioconférence…)",
    )
    interview_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TYPE_HR,
    )

    # ── Résultat ──────────────────────────────────────────────────────────────
    notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Notes et observations de l'interviewer pendant l'entretien",
    )
    decision: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DECISION_PENDING,
    )
    rating: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="Note globale du candidat sur 5 (1 = insuffisant, 5 = excellent)",
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow,
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    application: Mapped["Application"] = relationship(
        "Application", back_populates="interviews", lazy="joined",
    )
    interviewer: Mapped[Optional["Employee"]] = relationship(
        "Employee", foreign_keys=[interviewer_id], lazy="joined",
    )

    # ── Validation ────────────────────────────────────────────────────────────
    @validates("interview_type")
    def _validate_type(self, key: str, value: str) -> str:
        if value not in self.TYPES:
            raise ValueError(
                f"Type d'entretien invalide : {value!r}. "
                f"Valeurs acceptées : {self.TYPES}"
            )
        return value

    @validates("decision")
    def _validate_decision(self, key: str, value: str) -> str:
        if value not in self.DECISIONS:
            raise ValueError(
                f"Décision invalide : {value!r}. "
                f"Valeurs acceptées : {self.DECISIONS}"
            )
        return value

    @validates("rating")
    def _validate_rating(self, key: str, value: Optional[int]) -> Optional[int]:
        if value is not None and not (1 <= int(value) <= 5):
            raise ValueError(
                f"La note doit être comprise entre 1 et 5 (reçu : {value})."
            )
        return value

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def is_completed(self) -> bool:
        return self.decision != self.DECISION_PENDING

    @property
    def type_label(self) -> str:
        return self.TYPE_LABELS.get(self.interview_type, self.interview_type)

    @property
    def interviewer_name(self) -> Optional[str]:
        return self.interviewer.full_name if self.interviewer else None

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_or_404(cls, interview_id: int) -> "Interview":
        obj = db.session.get(cls, interview_id)
        if obj is None:
            from flask import abort
            abort(404, description="Entretien introuvable.")
        return obj

    @classmethod
    def for_interviewer(cls, employee_id: int):
        """Requête (non exécutée) des entretiens assignés à un interviewer."""
        return (
            db.select(cls)
            .where(cls.interviewer_id == employee_id)
            .order_by(cls.scheduled_at)
        )

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "application_id":   self.application_id,
            "interviewer_id":   self.interviewer_id,
            "interviewer_name": self.interviewer_name,
            "scheduled_at":     self.scheduled_at.isoformat(),
            "duration_minutes": self.duration_minutes,
            "location":         self.location,
            "interview_type":   self.interview_type,
            "type_label":       self.type_label,
            "decision":         self.decision,
            "rating":           self.rating,
            "notes":            self.notes,
            "is_completed":     self.is_completed,
            "created_at":       self.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return (
            f"<Interview id={self.id} "
            f"application={self.application_id} "
            f"scheduled_at={self.scheduled_at} "
            f"decision={self.decision!r}>"
        )
