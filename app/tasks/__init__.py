"""
Tâches Celery asynchrones.

Toutes les tâches importent l'instance `celery` depuis app.extensions.
Le ContextTask configuré dans create_app() garantit la disponibilité
du contexte Flask (db, mail, config) dans chaque tâche.

Lancement du worker :
    celery -A wsgi.celery worker --loglevel=info
Lancement du scheduler (beat) :
    celery -A wsgi.celery beat --loglevel=info
"""
