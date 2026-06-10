"""
Endpoints API REST v1 — Ressource : reporting

Conventions :
  GET    /api/v1/reporting/          → liste paginée
  POST   /api/v1/reporting/          → création
  GET    /api/v1/reporting/<id>      → détail
  PUT    /api/v1/reporting/<id>      → mise à jour complète
  PATCH  /api/v1/reporting/<id>      → mise à jour partielle
  DELETE /api/v1/reporting/<id>      → suppression

Authentification : JWT Bearer token (header Authorization)
Réponses : JSON conforme à la structure { data, meta, errors }
"""
from flask import jsonify
from flask_jwt_extended import jwt_required

from . import bp


# Les routes seront implémentées lors de la phase de développement.
