"""
Blueprint Leaves — Congés & Absences (Pages HTML / SSR).

Préfixe URL : /leaves  (enregistré dans create_app)
Templates   : app/templates/leaves/

Couvre les pages :
  - Mes demandes d'absence (employé)
  - Soumission d'une nouvelle demande
  - Détail d'une demande
  - File d'approbation (manager / RH)
  - Mes soldes de congés
"""
from flask import Blueprint

bp: Blueprint = Blueprint(
    "leaves",
    __name__,
    template_folder="templates",
)

from . import routes  # noqa: E402, F401