"""
Blueprint Auth — Pages HTML (SSR).

Préfixe URL : /auth  (enregistré dans create_app)
Templates   : app/templates/auth/
"""
from flask import Blueprint

bp: Blueprint = Blueprint(
    "auth",
    __name__,
    template_folder="templates",
)

from . import routes  # noqa: E402, F401