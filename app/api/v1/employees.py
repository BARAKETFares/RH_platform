"""
Endpoints API REST v1 — Ressource : employees

Conventions :
  GET    /api/v1/employees/          → liste paginée
  POST   /api/v1/employees/          → création
  GET    /api/v1/employees/<id>      → détail
  PUT    /api/v1/employees/<id>      → mise à jour complète
  PATCH  /api/v1/employees/<id>      → mise à jour partielle
  DELETE /api/v1/employees/<id>      → suppression

Authentification : JWT Bearer token (header Authorization)
Réponses : JSON conforme à la structure { data, meta, errors }
"""
from flask import jsonify
from flask_jwt_extended import jwt_required

from . import bp


# Les routes seront implémentées lors de la phase de développement.
