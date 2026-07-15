"""
Package des modèles SQLAlchemy.

Tous les modèles sont importés ici pour que Flask-Migrate (Alembic)
puisse les découvrir lors de la génération des migrations.

IMPORTANT : Ne jamais importer les modèles directement depuis ce fichier
dans le code applicatif — importer depuis le module spécifique :
    from app.models.employee import Employee   ✓
    from app.models import Employee             ✓ (réexporté ici, aussi valide)
    from app import db; db.Model                ✗ (ne découvre pas les modèles)

Ordre d'import : tables sans dépendance d'abord, puis dépendantes,
afin d'éviter toute ambiguïté de résolution des relations SQLAlchemy
(les forward references via chaînes "ClassName" fonctionnent dans
n'importe quel ordre, mais cet ordre reste documenté pour la lisibilité
et pour Alembic, qui construit son graphe de dépendances FK dans cet ordre).

  1. roles, permissions          (aucune dépendance externe)
  2. users                        (dépend de roles)
  3. companies                     (aucune dépendance externe)
  4. sites, departments             (dépendent de companies)
  5. positions                       (dépend de departments)
  6. employees                        (dépend de companies, departments,
                                       positions, sites, users)
  7. leave_types                       (dépend de companies)
  8. leave_balances                     (dépend de employees, leave_types)
  9. leave_requests                      (dépend de employees, leave_types, users)
  10. public_holidays, work_schedules     (dépendent de companies, sites)
  11. audit_logs                            (dépend de users, user_sessions)
  12. notifications                          (dépend de users)
"""

# 1. Sécurité & Auth
from .role import Role, Permission, RolePermission  # noqa: F401
from .user import User, UserSession, PasswordResetToken  # noqa: F401

# 2. Structure organisationnelle
from .organization import Company, Site  # noqa: F401
from .department import Department  # noqa: F401
from .position import Position  # noqa: F401

# 3. Employés
from .employee import Employee  # noqa: F401
from .contract import ContractType, Contract  # noqa: F401
# 4. Congés & Absences
from .leave_type import LeaveType  # noqa: F401
from .leave_balance import LeaveBalance  # noqa: F401
from .leave_request import LeaveRequest  # noqa: F401
from .objective import Objective  # noqa: F401
from .evaluation import EvaluationCampaign, Evaluation, EvaluationItem  # noqa: F401
# 5. Calendrier
from .calendar import PublicHoliday, WorkSchedule  # noqa: F401

# 6. Paie
from .payroll import PaySlip, PayElement  # noqa: F401

# 7. Formations
from .training import Training, Enrollment  # noqa: F401

# 8. Recrutement
from .recruitment import JobPosting, Candidate, Application, Interview  # noqa: F401

# 9. Transversal
from .audit import AuditLog  # noqa: F401
from .notification import Notification  # noqa: F401

__all__ = [
    "Role", "Permission", "RolePermission",
    "User", "UserSession", "PasswordResetToken",
    "Company", "Site",
    "Department",
    "Position",
    "Employee",
    "LeaveType",
    "LeaveBalance",
    "LeaveRequest",
    "PublicHoliday", "WorkSchedule",
    "PaySlip", "PayElement",
    "AuditLog",
    "Notification",
    "Training", "Enrollment",
    "JobPosting", "Candidate", "Application", "Interview",
]