"""
Blueprint API v1.

Enregistré dans create_app() avec url_prefix="/api/v1".
Regroupe tous les sous-blueprints par ressource.
"""
from flask import Blueprint

bp: Blueprint = Blueprint("api_v1", __name__)

# Import des sous-modules de ressources
# APRÈS
from . import (
    auth,
    employees,
    leaves,
    evaluations,
)