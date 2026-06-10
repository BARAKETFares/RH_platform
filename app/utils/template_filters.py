"""
Filtres et fonctions globales Jinja2.

Disponibles dans tous les templates sans import explicite.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

from flask import Flask


def register_filters(app: Flask) -> None:
    """Enregistre tous les filtres sur l'application."""

    @app.template_filter("date_fr")
    def date_fr(value: date | datetime | None) -> str:
        """Formate une date en français : 15 janvier 2025"""
        if not value:
            return "—"
        mois = [
            "", "janvier", "février", "mars", "avril", "mai", "juin",
            "juillet", "août", "septembre", "octobre", "novembre", "décembre",
        ]
        d = value.date() if isinstance(value, datetime) else value
        return f"{d.day} {mois[d.month]} {d.year}"

    @app.template_filter("euros")
    def euros(value: float | None) -> str:
        """Formate un montant en euros : 1 234,56 €"""
        if value is None:
            return "—"
        return f"{value:,.2f} €".replace(",", " ").replace(".", ",")

    @app.template_filter("initials")
    def initials(value: str | None) -> str:
        """Génère les initiales d'un nom complet : 'Jean Dupont' → 'JD'"""
        if not value:
            return "?"
        parts = value.split()
        return "".join(p[0].upper() for p in parts if p)[:2]

    @app.template_filter("days_label")
    def days_label(value: float | None) -> str:
        """'1.0' → '1 jour' ; '2.5' → '2.5 jours'"""
        if value is None:
            return "—"
        n = int(value) if value == int(value) else value
        return f"{n} jour" if value <= 1 else f"{n} jours"

    @app.template_global("now")
    def now() -> datetime:
        """Retourne la date/heure actuelle dans les templates."""
        return datetime.utcnow()

    @app.template_global("current_year")
    def current_year() -> int:
        return datetime.utcnow().year
