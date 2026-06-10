"""
Blueprint : absences

Enregistré dans create_app() avec url_prefix="/absences".
Ce fichier instancie le Blueprint et importe les routes afin
que les décorateurs @bp.route() soient enregistrés au chargement.
"""
from flask import Blueprint

bp: Blueprint = Blueprint(
    "absences",
    __name__,
    template_folder="templates",  # templates/absences/
    static_folder=None,
)

# Import des routes — doit rester en bas pour éviter les imports circulaires
from . import routes  # noqa: F401, E402
