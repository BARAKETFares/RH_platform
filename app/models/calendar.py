"""
Modèles : PublicHoliday · WorkSchedule
Calendrier de travail — SQLAlchemy 2.0 (Mapped / mapped_column)

PublicHoliday recense les jours fériés légaux et conventionnels par
entreprise (et optionnellement par site, pour le multi-pays/multi-région).
Consommé directement par leave_service._get_company_holidays() pour
exclure ces jours du calcul des congés ouvrés.

WorkSchedule définit un horaire de référence hebdomadaire (heures par jour
de la semaine), utilisé pour le calcul du temps de travail théorique et
les exports de paie. Une entreprise peut avoir plusieurs calendriers
(ex : "35h Standard", "39h Cadre"), un seul étant marqué `is_default`.

Relations principales :
  - company (N:1) → entreprise de rattachement, sur les deux modèles
  - site    (N:1, optionnelle, PublicHoliday uniquement) → jour férié
            spécifique à un site géographique (NULL = s'applique à tous
            les sites de l'entreprise)
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.extensions import db

if TYPE_CHECKING:
    from app.models.organization import Company, Site


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================================
# PublicHoliday
# =============================================================================

class PublicHoliday(db.Model):
    """
    Jour férié légal ou conventionnel.

    `site_id` NULL signifie que le jour férié s'applique à tous les sites
    de l'entreprise (cas standard pour les jours fériés nationaux). Un
    site_id renseigné permet de gérer des jours fériés locaux distincts
    (ex : jours fériés régionaux/religieux variant selon l'implantation).

    La contrainte d'unicité (company_id, site_id, holiday_date) empêche
    les doublons tout en autorisant la coexistence d'un jour férié
    "national" (site_id=NULL) et d'un jour férié local à la même date
    pour un site donné si nécessaire.
    """

    __tablename__ = "public_holidays"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "site_id", "holiday_date",
            name="uq_public_holidays_company_site_date",
        ),
        Index("ix_public_holidays_company_date", "company_id", "holiday_date"),
        Index("ix_public_holidays_site_id", "site_id"),
    )

    # ── Identifiants ──────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── Rattachements ─────────────────────────────────────────────────────────
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    site_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=True,
        comment="NULL = s'applique à tous les sites de l'entreprise",
    )

    # ── Informations ──────────────────────────────────────────────────────────
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_national: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    company: Mapped["Company"] = relationship(
        "Company", foreign_keys=[company_id], lazy="select"
    )
    site: Mapped[Optional["Site"]] = relationship(
        "Site", foreign_keys=[site_id], lazy="select"
    )

    # ── Validation SQLAlchemy ─────────────────────────────────────────────────
    @validates("name")
    def _strip_name(self, key: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Le nom du jour férié ne peut pas être vide.")
        return value.strip()

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def applies_to_all_sites(self) -> bool:
        return self.site_id is None

    @property
    def weekday_name(self) -> str:
        """Jour de la semaine en français, ex : 'lundi'."""
        days = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
        return days[self.holiday_date.weekday()]

    @property
    def falls_on_weekend(self) -> bool:
        """True si le jour férié tombe un week-end (samedi ou dimanche)."""
        return self.holiday_date.weekday() >= 5

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_or_404(cls, holiday_id: int) -> "PublicHoliday":
        holiday = db.session.get(cls, holiday_id)
        if holiday is None:
            from flask import abort
            abort(404, description="Jour férié introuvable.")
        return holiday

    @classmethod
    def for_company_in_range(
        cls,
        company_id: int,
        start_date: date,
        end_date: date,
        site_id: Optional[int] = None,
    ):
        """
        Requête (non exécutée) des jours fériés applicables à une entreprise
        (et optionnellement un site précis) sur une période donnée.

        Si site_id est fourni, retourne les jours fériés nationaux
        (site_id IS NULL) ET les jours fériés spécifiques à ce site.
        """
        query = db.select(cls).where(
            cls.company_id == company_id,
            cls.holiday_date >= start_date,
            cls.holiday_date <= end_date,
        )
        if site_id is not None:
            query = query.where(db.or_(cls.site_id.is_(None), cls.site_id == site_id))
        else:
            query = query.where(cls.site_id.is_(None))
        return query.order_by(cls.holiday_date)

    @classmethod
    def for_year(cls, company_id: int, year: int, site_id: Optional[int] = None):
        """Requête (non exécutée) de tous les jours fériés d'une entreprise pour une année."""
        return cls.for_company_in_range(
            company_id, date(year, 1, 1), date(year, 12, 31), site_id
        )

    @classmethod
    def is_holiday(cls, company_id: int, check_date: date, site_id: Optional[int] = None) -> bool:
        """Vérifie si une date donnée est un jour férié pour l'entreprise (et le site)."""
        query = db.select(cls.id).where(
            cls.company_id == company_id,
            cls.holiday_date == check_date,
        )
        if site_id is not None:
            query = query.where(db.or_(cls.site_id.is_(None), cls.site_id == site_id))
        else:
            query = query.where(cls.site_id.is_(None))
        return db.session.execute(query).first() is not None

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "company_id": self.company_id,
            "site_id": self.site_id,
            "holiday_date": self.holiday_date.isoformat(),
            "name": self.name,
            "is_national": self.is_national,
            "weekday_name": self.weekday_name,
            "falls_on_weekend": self.falls_on_weekend,
            "created_at": self.created_at.isoformat(),
        }

    # ── Dunder ────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return f"<PublicHoliday {self.holiday_date.isoformat()} {self.name!r}>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PublicHoliday) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


# =============================================================================
# WorkSchedule
# =============================================================================

class WorkSchedule(db.Model):
    """
    Calendrier de travail hebdomadaire de référence.

    Définit le nombre d'heures travaillées par jour de la semaine.
    Une entreprise peut définir plusieurs calendriers (ex : "35h Standard",
    "39h Cadre", "Temps Partiel 80%") ; un seul est marqué `is_default`
    et sert de référence par défaut pour les nouveaux employés.

    Les valeurs à 0 (ex : samedi/dimanche par défaut) signifient que ce
    jour n'est pas travaillé dans ce calendrier — utilisé notamment pour
    déterminer les jours ouvrés dans le calcul des congés.
    """

    __tablename__ = "work_schedules"
    __table_args__ = (
        CheckConstraint("monday_hours >= 0", name="ck_work_schedules_monday_positive"),
        CheckConstraint("tuesday_hours >= 0", name="ck_work_schedules_tuesday_positive"),
        CheckConstraint("wednesday_hours >= 0", name="ck_work_schedules_wednesday_positive"),
        CheckConstraint("thursday_hours >= 0", name="ck_work_schedules_thursday_positive"),
        CheckConstraint("friday_hours >= 0", name="ck_work_schedules_friday_positive"),
        CheckConstraint("saturday_hours >= 0", name="ck_work_schedules_saturday_positive"),
        CheckConstraint("sunday_hours >= 0", name="ck_work_schedules_sunday_positive"),
        UniqueConstraint("company_id", "name", name="uq_work_schedules_name_per_company"),
        Index("ix_work_schedules_company_id", "company_id"),
    )

    # ── Identifiants ──────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # ── Heures par jour de la semaine ──────────────────────────────────────────
    monday_hours: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False, default=7)
    tuesday_hours: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False, default=7)
    wednesday_hours: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False, default=7)
    thursday_hours: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False, default=7)
    friday_hours: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False, default=7)
    saturday_hours: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False, default=0)
    sunday_hours: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False, default=0)

    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    company: Mapped["Company"] = relationship(
        "Company", foreign_keys=[company_id], lazy="select"
    )

    # ── Validation SQLAlchemy ─────────────────────────────────────────────────
    @validates("name")
    def _strip_name(self, key: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Le nom du calendrier de travail ne peut pas être vide.")
        return value.strip()

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def daily_hours(self) -> dict[str, float]:
        """Dictionnaire {jour: heures}, indexé par nom de jour en anglais (cohérence code)."""
        return {
            "monday": float(self.monday_hours),
            "tuesday": float(self.tuesday_hours),
            "wednesday": float(self.wednesday_hours),
            "thursday": float(self.thursday_hours),
            "friday": float(self.friday_hours),
            "saturday": float(self.saturday_hours),
            "sunday": float(self.sunday_hours),
        }

    @property
    def weekly_hours_total(self) -> float:
        """Total d'heures travaillées sur la semaine complète."""
        return sum(self.daily_hours.values())

    @property
    def working_days_per_week(self) -> int:
        """Nombre de jours travaillés dans la semaine (heures > 0)."""
        return sum(1 for h in self.daily_hours.values() if h > 0)

    @property
    def non_working_weekdays(self) -> list[int]:
        """
        Liste des indices de jours non travaillés (convention Python :
        0=lundi ... 6=dimanche), utilisée pour les calculs de jours ouvrés.
        """
        order = [
            self.monday_hours, self.tuesday_hours, self.wednesday_hours,
            self.thursday_hours, self.friday_hours, self.saturday_hours, self.sunday_hours,
        ]
        return [i for i, hours in enumerate(order) if hours == 0]

    # ── Méthodes d'instance ───────────────────────────────────────────────────
    def is_working_day(self, weekday: int) -> bool:
        """
        Vérifie si un jour de la semaine donné (0=lundi ... 6=dimanche,
        convention Python date.weekday()) est travaillé dans ce calendrier.
        """
        order = [
            self.monday_hours, self.tuesday_hours, self.wednesday_hours,
            self.thursday_hours, self.friday_hours, self.saturday_hours, self.sunday_hours,
        ]
        return float(order[weekday]) > 0

    def hours_for_weekday(self, weekday: int) -> float:
        """Retourne le nombre d'heures travaillées pour un jour donné (0=lundi ... 6=dimanche)."""
        order = [
            self.monday_hours, self.tuesday_hours, self.wednesday_hours,
            self.thursday_hours, self.friday_hours, self.saturday_hours, self.sunday_hours,
        ]
        return float(order[weekday])

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_or_404(cls, schedule_id: int) -> "WorkSchedule":
        schedule = db.session.get(cls, schedule_id)
        if schedule is None:
            from flask import abort
            abort(404, description="Calendrier de travail introuvable.")
        return schedule

    @classmethod
    def get_default(cls, company_id: int) -> Optional["WorkSchedule"]:
        """Retourne le calendrier de travail par défaut d'une entreprise."""
        return db.session.execute(
            db.select(cls).where(
                cls.company_id == company_id,
                cls.is_default.is_(True),
            )
        ).scalar_one_or_none()

    @classmethod
    def for_company(cls, company_id: int):
        """Requête (non exécutée) de tous les calendriers d'une entreprise."""
        return db.select(cls).where(cls.company_id == company_id).order_by(cls.name)

    # ── Sérialisation ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "company_id": self.company_id,
            "name": self.name,
            "monday_hours": float(self.monday_hours),
            "tuesday_hours": float(self.tuesday_hours),
            "wednesday_hours": float(self.wednesday_hours),
            "thursday_hours": float(self.thursday_hours),
            "friday_hours": float(self.friday_hours),
            "saturday_hours": float(self.saturday_hours),
            "sunday_hours": float(self.sunday_hours),
            "weekly_hours_total": self.weekly_hours_total,
            "working_days_per_week": self.working_days_per_week,
            "is_default": self.is_default,
            "created_at": self.created_at.isoformat(),
        }

    # ── Dunder ────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return f"<WorkSchedule id={self.id} {self.name!r} ({self.weekly_hours_total}h/sem)>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, WorkSchedule) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)