"""
Blueprint : admin

Enregistré dans create_app() avec url_prefix="/admin".
Ce fichier instancie le Blueprint et importe les routes afin
que les décorateurs @bp.route() soient enregistrés au chargement.
"""
from flask import Blueprint

bp: Blueprint = Blueprint(
    "admin",
    __name__,
    template_folder="templates",  # templates/admin/
    static_folder=None,
)

# Import des routes — doit rester en bas pour éviter les imports circulaires
from . import routes  # noqa: F401, E402
