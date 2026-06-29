"""
Blueprint Employees — Gestion des employés (Pages HTML / SSR).

Préfixe URL : /employees  (enregistré dans create_app)
Templates   : app/templates/employees/

Couvre les pages :
  - Liste des employés (avec recherche et filtres)
  - Détail d'un employé (infos perso, pro, contrats)
  - Création / édition d'un employé
  - Organigramme (vue arborescente par département)
"""
from flask import Blueprint

bp: Blueprint = Blueprint(
    "employees",
    __name__,
    template_folder="templates",
)

from . import routes  # noqa: E402, F401