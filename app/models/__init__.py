"""
Package des modèles SQLAlchemy.

Tous les modèles sont importés ici afin que Flask-Migrate (Alembic)
puisse les découvrir lors de la génération des migrations.

IMPORTANT : Ne jamais importer les modèles directement depuis ce fichier
dans le code applicatif — importer depuis le module spécifique :
    from app.models.employee import Employee   ✓
    from app.models import Employee            ✓ (si réexporté ici)
    from app import db; db.Model              ✗ (ne découvre pas les modèles)

Ordre d'import : tables sans FK en premier, puis dépendantes.
Les modèles eux-mêmes seront créés lors de la prochaine phase.
"""

# Sécurité & Auth
# from .role         import Role, Permission, RolePermission
# from .user         import User, UserSession, PasswordResetToken

# Structure organisationnelle
# from .organization import Company, Site, Department, Position

# Employés
# from .employee     import Employee, ContractType, Contract
# from .document     import EmployeeDocument
# from .skill        import Skill, EmployeeSkill

# Congés & Absences
# from .leave        import LeaveType, LeaveBalance, LeaveRequest
# from .calendar     import PublicHoliday, WorkSchedule

# Évaluations
# from .evaluation   import EvaluationCampaign, Evaluation, EvaluationItem
# from .objective    import Objective

# Transversal
# from .notification import Notification
# from .audit        import AuditLog
