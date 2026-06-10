"""
Couche Service — Logique métier.

Les services encapsulent toute la logique métier RH, séparée des routes.
Une route ne fait que valider l'entrée, appeler un service, et formater la réponse.

Règles :
  - Pas d'objet Request Flask dans un service (testabilité)
  - Les services lèvent des exceptions métier (BusinessError, NotFoundError…)
  - Les services appellent d'autres services, jamais les routes
  - Transactions SQLAlchemy gérées au niveau service (db.session.commit/rollback)
"""
