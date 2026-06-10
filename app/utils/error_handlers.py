# app/utils/error_handlers.py
from flask import jsonify, render_template, request


def _wants_json() -> bool:
    return request.path.startswith("/api/") or \
           request.accept_mimetypes.best_match(["application/json", "text/html"]) == "application/json"


def _error_response(code: int, message: str, details=None):
    if _wants_json():
        payload = {"error": {"code": code, "message": message}}
        if details:
            payload["error"]["details"] = details
        return jsonify(payload), code

    # Tenter le template — fallback texte si absent
    try:
        return render_template(f"errors/{code}.html", message=message), code
    except Exception:
        return f"<h1>{code}</h1><p>{message}</p>", code


def handle_400(e): return _error_response(400, "Requête invalide.")
def handle_403(e): return _error_response(403, "Accès refusé.")
def handle_404(e): return _error_response(404, "Page introuvable.")
def handle_405(e): return _error_response(405, "Méthode non autorisée.")
def handle_422(e): return _error_response(422, "Données invalides.")
def handle_429(e): return _error_response(429, "Trop de requêtes.")
def handle_500(e): return _error_response(500, "Erreur serveur interne.")