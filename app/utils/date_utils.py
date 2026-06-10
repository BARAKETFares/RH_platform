"""Utilitaires de dates et fuseaux horaires."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
from flask import current_app


PARIS_TZ = ZoneInfo("Europe/Paris")


def now_paris() -> datetime:
    """Datetime courant en heure Paris."""
    return datetime.now(PARIS_TZ)


def to_paris(dt: datetime) -> datetime:
    """Convertit un datetime UTC en heure Paris."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(PARIS_TZ)


def format_date_fr(d: date | None) -> str:
    """Filtre Jinja2 : formate une date en français (dd/mm/yyyy)."""
    if d is None:
        return ""
    return d.strftime("%d/%m/%Y")


def format_datetime_fr(dt: datetime | None) -> str:
    """Filtre Jinja2 : formate un datetime en français."""
    if dt is None:
        return ""
    return to_paris(dt).strftime("%d/%m/%Y à %H:%M")


def working_days_between(start: date, end: date, holidays: list[date] | None = None) -> float:
    """
    Calcule le nombre de jours ouvrés entre deux dates (incluses).
    Exclut les week-ends et les jours fériés fournis.
    """
    if start > end:
        return 0.0
    holidays_set = set(holidays or [])
    days = 0.0
    current = start
    while current <= end:
        if current.weekday() < 5 and current not in holidays_set:  # Lun-Ven
            days += 1
        from datetime import timedelta
        current += timedelta(days=1)
    return days
