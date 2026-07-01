"""
En-têtes de sécurité HTTP ajoutés à chaque réponse.

Référence : https://owasp.org/www-project-secure-headers/
"""
from flask import Response


def add_security_headers(response: Response) -> Response:
    headers = {
        # Empêche l'injection de contenu MIME
        "X-Content-Type-Options": "nosniff",
        # Protection XSS navigateurs anciens
        "X-XSS-Protection": "1; mode=block",
        # Empêche le clickjacking
        "X-Frame-Options": "SAMEORIGIN",
        # Force HTTPS (HSTS) — activer en production uniquement
        # "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        # Politique de référent
        "Referrer-Policy": "strict-origin-when-cross-origin",
        # Permissions browser API
        "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
        # Content Security Policy
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'self' 'nonce-{nonce}' cdn.jsdelivr.net cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net fonts.googleapis.com; "
            "font-src 'self' cdn.jsdelivr.net fonts.gstatic.com; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        ),
    }
    for key, value in headers.items():
        response.headers[key] = value
    return response
