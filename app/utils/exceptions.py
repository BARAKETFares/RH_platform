"""
Exceptions métier personnalisées.

Hiérarchie :
    HRPlatformError (base)
        ├── NotFoundError         → 404
        ├── ValidationError       → 422
        ├── PermissionError       → 403
        ├── AuthenticationError   → 401
        ├── ConflictError         → 409
        ├── BusinessRuleError     → 400
        └── ExternalServiceError  → 502
"""
from __future__ import annotations


class HRPlatformError(Exception):
    """Classe de base pour toutes les erreurs applicatives."""
    http_status: int = 500
    default_message: str = "Une erreur inattendue s'est produite."

    def __init__(self, message: str | None = None, details: dict | None = None):
        self.message = message or self.default_message
        self.details = details or {}
        super().__init__(self.message)


class NotFoundError(HRPlatformError):
    http_status = 404
    default_message = "Ressource introuvable."


class ValidationError(HRPlatformError):
    http_status = 422
    default_message = "Les données fournies sont invalides."


class PermissionDeniedError(HRPlatformError):
    http_status = 403
    default_message = "Accès refusé."


class AuthenticationError(HRPlatformError):
    http_status = 401
    default_message = "Authentification requise ou invalide."


class ConflictError(HRPlatformError):
    http_status = 409
    default_message = "Conflit avec l'état actuel de la ressource."


class BusinessRuleError(HRPlatformError):
    http_status = 400
    default_message = "Cette opération viole une règle métier."


class InsufficientLeaveBalanceError(BusinessRuleError):
    default_message = "Solde de congés insuffisant."


class OverlappingLeaveError(ConflictError):
    default_message = "Une absence chevauche une demande existante."


class ExternalServiceError(HRPlatformError):
    http_status = 502
    default_message = "Erreur de communication avec un service externe."
