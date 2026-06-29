"""
Schémas Marshmallow : Recrutement
  JobPosting · Candidate · Application · Interview

Conventions (identiques aux autres schémas du projet) :
  - <X>Schema        → sérialisation complète (lecture / réponse API)
  - <X>CreateSchema  → validation stricte à la création
  - <X>UpdateSchema  → PATCH (tous champs optionnels)
  - ApplicationStatusUpdateSchema → transition de statut uniquement
"""
from __future__ import annotations

from datetime import datetime, timezone
from marshmallow import Schema, ValidationError, fields, post_load, validate, validates, validates_schema

# =============================================================================
# Constantes (alignées avec les modèles)
# =============================================================================

JOB_STATUSES         = ("draft", "open", "closed", "cancelled")
CANDIDATE_SOURCES    = ("linkedin", "jobboard", "referral", "spontaneous", "website", "other")
APPLICATION_STATUSES = ("recue", "preselectionnee", "entretien", "offre", "refusee", "embauchee")
INTERVIEW_TYPES      = ("phone", "video", "onsite", "technical", "hr")
INTERVIEW_DECISIONS  = ("pending", "proceed", "hold", "reject")


# =============================================================================
# JobPosting
# =============================================================================

class JobPostingSchema(Schema):
    """Sérialisation complète d'une offre d'emploi (lecture / GET)."""

    id             = fields.Integer(dump_only=True)
    company_id     = fields.Integer(dump_only=True)
    department_id  = fields.Integer(allow_none=True)
    position_id    = fields.Integer(allow_none=True)
    created_by_id  = fields.Integer(allow_none=True, dump_only=True)

    title          = fields.String(required=True, validate=validate.Length(min=1, max=200))
    description    = fields.String(allow_none=True)
    requirements   = fields.String(allow_none=True)
    location       = fields.String(allow_none=True, validate=validate.Length(max=200))
    contract_type  = fields.String(allow_none=True, validate=validate.Length(max=50))
    salary_min     = fields.Float(allow_none=True, validate=validate.Range(min=0))
    salary_max     = fields.Float(allow_none=True, validate=validate.Range(min=0))
    headcount      = fields.Integer(allow_none=True, validate=validate.Range(min=1))
    status         = fields.String(validate=validate.OneOf(JOB_STATUSES))
    published_at   = fields.Date(allow_none=True)
    closing_date   = fields.Date(allow_none=True)

    # Champs dérivés — lecture seule
    department_name       = fields.Method("_department_name", dump_only=True)
    application_count     = fields.Method("_application_count", dump_only=True)
    salary_range          = fields.Method("_salary_range", dump_only=True)

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    def _department_name(self, obj) -> str | None:
        try:
            return obj.department.name if obj.department else None
        except Exception:
            return None

    def _application_count(self, obj) -> int:
        try:
            return obj.application_count
        except Exception:
            return 0

    def _salary_range(self, obj) -> str | None:
        try:
            return obj.salary_range
        except Exception:
            return None

    @validates("title")
    def _validate_title(self, value: str, **kwargs) -> None:
        if not value.strip():
            raise ValidationError("Le titre de l'offre ne peut pas être vide.")

    @validates_schema
    def _validate_salary_range(self, data: dict, **kwargs) -> None:
        mn = data.get("salary_min")
        mx = data.get("salary_max")
        if mn is not None and mx is not None and mx < mn:
            raise ValidationError(
                "Le salaire maximum doit être supérieur ou égal au salaire minimum.",
                field_name="salary_max",
            )

    @validates_schema
    def _validate_closing_date(self, data: dict, **kwargs) -> None:
        pub = data.get("published_at")
        clo = data.get("closing_date")
        if pub and clo and clo < pub:
            raise ValidationError(
                "La date de clôture ne peut pas précéder la date de publication.",
                field_name="closing_date",
            )


class JobPostingCreateSchema(Schema):
    """Validation des données à la création d'une offre d'emploi."""

    company_id    = fields.Integer(allow_none=True, load_default=None)
    department_id = fields.Integer(allow_none=True, load_default=None)
    position_id   = fields.Integer(allow_none=True, load_default=None)
    created_by_id = fields.Integer(allow_none=True, load_default=None)

    title         = fields.String(required=True, validate=validate.Length(min=1, max=200))
    description   = fields.String(allow_none=True, load_default=None)
    requirements  = fields.String(allow_none=True, load_default=None)
    location      = fields.String(allow_none=True, load_default=None,
                                   validate=validate.Length(max=200))
    contract_type = fields.String(allow_none=True, load_default=None,
                                   validate=validate.Length(max=50))
    salary_min    = fields.Float(allow_none=True, load_default=None,
                                  validate=validate.Range(min=0))
    salary_max    = fields.Float(allow_none=True, load_default=None,
                                  validate=validate.Range(min=0))
    headcount     = fields.Integer(allow_none=True, load_default=1,
                                    validate=validate.Range(min=1))
    status        = fields.String(load_default="draft", validate=validate.OneOf(JOB_STATUSES))
    published_at  = fields.Date(allow_none=True, load_default=None)
    closing_date  = fields.Date(allow_none=True, load_default=None)

    @validates("title")
    def _validate_title(self, value: str, **kwargs) -> None:
        if not value.strip():
            raise ValidationError("Le titre de l'offre ne peut pas être vide.")

    @validates_schema
    def _validate_salary_range(self, data: dict, **kwargs) -> None:
        mn = data.get("salary_min")
        mx = data.get("salary_max")
        if mn is not None and mx is not None and mx < mn:
            raise ValidationError(
                "salary_max doit être >= salary_min.", field_name="salary_max",
            )


class JobPostingUpdateSchema(Schema):
    """Mise à jour partielle d'une offre (PATCH — tous champs optionnels)."""

    department_id = fields.Integer(allow_none=True)
    position_id   = fields.Integer(allow_none=True)
    title         = fields.String(validate=validate.Length(min=1, max=200))
    description   = fields.String(allow_none=True)
    requirements  = fields.String(allow_none=True)
    location      = fields.String(allow_none=True, validate=validate.Length(max=200))
    contract_type = fields.String(allow_none=True, validate=validate.Length(max=50))
    salary_min    = fields.Float(allow_none=True, validate=validate.Range(min=0))
    salary_max    = fields.Float(allow_none=True, validate=validate.Range(min=0))
    headcount     = fields.Integer(allow_none=True, validate=validate.Range(min=1))
    status        = fields.String(validate=validate.OneOf(JOB_STATUSES))
    closing_date  = fields.Date(allow_none=True)

    @validates("title")
    def _validate_title(self, value: str, **kwargs) -> None:
        if value is not None and not value.strip():
            raise ValidationError("Le titre de l'offre ne peut pas être vide.")

    @validates_schema
    def _validate_salary_range(self, data: dict, **kwargs) -> None:
        mn = data.get("salary_min")
        mx = data.get("salary_max")
        if mn is not None and mx is not None and mx < mn:
            raise ValidationError(
                "salary_max doit être >= salary_min.", field_name="salary_max",
            )


# =============================================================================
# Candidate
# =============================================================================

class CandidateSchema(Schema):
    """Sérialisation complète d'un candidat (lecture / GET)."""

    id         = fields.Integer(dump_only=True)
    first_name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    last_name  = fields.String(required=True, validate=validate.Length(min=1, max=100))
    email      = fields.Email(required=True, validate=validate.Length(max=255))
    phone      = fields.String(allow_none=True, validate=validate.Length(max=30))
    cv_path    = fields.String(allow_none=True)
    cv_text    = fields.String(allow_none=True)
    source     = fields.String(validate=validate.OneOf(CANDIDATE_SOURCES))
    notes      = fields.String(allow_none=True)
    has_cv     = fields.Boolean(dump_only=True)
    full_name  = fields.Method("_full_name", dump_only=True)

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    def _full_name(self, obj) -> str:
        return obj.full_name


class CandidateCreateSchema(Schema):
    """Validation des données à la création d'un candidat."""

    first_name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    last_name  = fields.String(required=True, validate=validate.Length(min=1, max=100))
    email      = fields.Email(required=True, validate=validate.Length(max=255))
    phone      = fields.String(allow_none=True, load_default=None,
                                validate=validate.Length(max=30))
    cv_path    = fields.String(allow_none=True, load_default=None)
    cv_text    = fields.String(allow_none=True, load_default=None)
    source     = fields.String(load_default="other",
                                validate=validate.OneOf(CANDIDATE_SOURCES))
    notes      = fields.String(allow_none=True, load_default=None)

    @post_load
    def _normalize_email(self, data: dict, **kwargs) -> dict:
        if "email" in data and data["email"]:
            data["email"] = data["email"].strip().lower()
        return data


class CandidateUpdateSchema(Schema):
    """Mise à jour partielle d'un candidat (PATCH)."""

    first_name = fields.String(validate=validate.Length(min=1, max=100))
    last_name  = fields.String(validate=validate.Length(min=1, max=100))
    email      = fields.Email(validate=validate.Length(max=255))
    phone      = fields.String(allow_none=True, validate=validate.Length(max=30))
    cv_path    = fields.String(allow_none=True)
    cv_text    = fields.String(allow_none=True)
    source     = fields.String(validate=validate.OneOf(CANDIDATE_SOURCES))
    notes      = fields.String(allow_none=True)


# =============================================================================
# Application (candidature)
# =============================================================================

class ApplicationSchema(Schema):
    """Sérialisation complète d'une candidature (lecture / GET)."""

    id             = fields.Integer(dump_only=True)
    candidate_id   = fields.Integer(required=True)
    job_posting_id = fields.Integer(required=True)
    status         = fields.String(validate=validate.OneOf(APPLICATION_STATUSES))
    applied_at     = fields.DateTime(allow_none=True)
    notes          = fields.String(allow_none=True)
    rejection_reason = fields.String(allow_none=True)

    # Champs dérivés — lecture seule
    status_label     = fields.Method("_status_label", dump_only=True)
    candidate_name   = fields.Method("_candidate_name", dump_only=True)
    candidate_email  = fields.Method("_candidate_email", dump_only=True)
    job_title        = fields.Method("_job_title", dump_only=True)
    interview_count  = fields.Method("_interview_count", dump_only=True)
    is_active        = fields.Boolean(dump_only=True)

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    def _status_label(self, obj) -> str:
        return obj.status_label

    def _candidate_name(self, obj) -> str | None:
        try:
            return obj.candidate.full_name if obj.candidate else None
        except Exception:
            return None

    def _candidate_email(self, obj) -> str | None:
        try:
            return obj.candidate.email if obj.candidate else None
        except Exception:
            return None

    def _job_title(self, obj) -> str | None:
        try:
            return obj.job_posting.title if obj.job_posting else None
        except Exception:
            return None

    def _interview_count(self, obj) -> int:
        try:
            return obj.interview_count
        except Exception:
            return 0


class ApplicationCreateSchema(Schema):
    """
    Validation des données de soumission d'une candidature.
    Le statut initial est toujours 'recue' — fixé par le service.
    """

    candidate_id   = fields.Integer(required=True)
    job_posting_id = fields.Integer(required=True)
    applied_at     = fields.DateTime(allow_none=True, load_default=None)
    notes          = fields.String(allow_none=True, load_default=None,
                                    validate=validate.Length(max=5000))


class ApplicationStatusUpdateSchema(Schema):
    """
    Transition de statut d'une candidature.

    Transitions légales :
        recue           → preselectionnee
        preselectionnee → entretien
        entretien       → offre
        offre           → embauchee
        tout sauf embauchee → refusee (+ rejection_reason optionnel)

    La validation des pré-conditions est déléguée au service (via les
    méthodes du modèle). Ce schéma valide uniquement les types et valeurs.
    """

    status           = fields.String(required=True,
                                      validate=validate.OneOf(APPLICATION_STATUSES))
    rejection_reason = fields.String(allow_none=True, load_default=None,
                                      validate=validate.Length(max=2000))
    notes            = fields.String(allow_none=True, load_default=None,
                                      validate=validate.Length(max=5000))

    @validates_schema
    def _validate_rejection_reason(self, data: dict, **kwargs) -> None:
        if data.get("rejection_reason") and data.get("status") != "refusee":
            raise ValidationError(
                "rejection_reason ne peut être fourni que pour le statut 'refusee'.",
                field_name="rejection_reason",
            )


# =============================================================================
# Interview
# =============================================================================

class InterviewSchema(Schema):
    """Sérialisation complète d'un entretien (lecture / GET)."""

    id               = fields.Integer(dump_only=True)
    application_id   = fields.Integer(required=True)
    interviewer_id   = fields.Integer(allow_none=True)
    scheduled_at     = fields.DateTime(required=True)
    duration_minutes = fields.Integer(allow_none=True, validate=validate.Range(min=1))
    location         = fields.String(allow_none=True)
    interview_type   = fields.String(validate=validate.OneOf(INTERVIEW_TYPES))
    notes            = fields.String(allow_none=True)
    decision         = fields.String(validate=validate.OneOf(INTERVIEW_DECISIONS))
    rating           = fields.Integer(allow_none=True, validate=validate.Range(min=1, max=5))

    # Champs dérivés — lecture seule
    type_label        = fields.Method("_type_label", dump_only=True)
    interviewer_name  = fields.Method("_interviewer_name", dump_only=True)
    is_completed      = fields.Boolean(dump_only=True)

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    def _type_label(self, obj) -> str:
        return obj.type_label

    def _interviewer_name(self, obj) -> str | None:
        try:
            return obj.interviewer_name
        except Exception:
            return None

    def _is_completed(self, obj) -> bool:
        return obj.is_completed


class InterviewCreateSchema(Schema):
    """Validation des données pour planifier un entretien."""

    application_id   = fields.Integer(required=True)
    interviewer_id   = fields.Integer(allow_none=True, load_default=None)
    scheduled_at     = fields.DateTime(required=True)
    duration_minutes = fields.Integer(allow_none=True, load_default=60,
                                       validate=validate.Range(min=1, max=480))
    location         = fields.String(allow_none=True, load_default=None,
                                      validate=validate.Length(max=300))
    interview_type   = fields.String(load_default="hr",
                                      validate=validate.OneOf(INTERVIEW_TYPES))

    @validates("scheduled_at")
    def _validate_scheduled_at(self, value: datetime, **kwargs) -> None:
        now = datetime.now(timezone.utc)
        # Marshmallow peut retourner un datetime naive si aucun offset n'est fourni
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        if value < now:
            raise ValidationError(
                "La date de l'entretien ne peut pas être dans le passé."
            )


class InterviewUpdateSchema(Schema):
    """Mise à jour d'un entretien (résultat ou replanification — PATCH)."""

    interviewer_id   = fields.Integer(allow_none=True)
    scheduled_at     = fields.DateTime(allow_none=True)
    duration_minutes = fields.Integer(allow_none=True, validate=validate.Range(min=1, max=480))
    location         = fields.String(allow_none=True, validate=validate.Length(max=300))
    interview_type   = fields.String(validate=validate.OneOf(INTERVIEW_TYPES))
    notes            = fields.String(allow_none=True, validate=validate.Length(max=10000))
    decision         = fields.String(validate=validate.OneOf(INTERVIEW_DECISIONS))
    rating           = fields.Integer(allow_none=True, validate=validate.Range(min=1, max=5))

    @validates_schema
    def _validate_rating_with_decision(self, data: dict, **kwargs) -> None:
        if data.get("rating") is not None and data.get("decision") == "pending":
            raise ValidationError(
                "Une note ne peut être attribuée qu'après une décision (proceed/hold/reject).",
                field_name="rating",
            )


# =============================================================================
# Instances prêtes à l'emploi
# =============================================================================

job_posting_schema         = JobPostingSchema()
job_postings_schema        = JobPostingSchema(many=True)
job_posting_create_schema  = JobPostingCreateSchema()
job_posting_update_schema  = JobPostingUpdateSchema()

candidate_schema        = CandidateSchema()
candidates_schema       = CandidateSchema(many=True)
candidate_create_schema = CandidateCreateSchema()
candidate_update_schema = CandidateUpdateSchema()

application_schema               = ApplicationSchema()
applications_schema              = ApplicationSchema(many=True)
application_create_schema        = ApplicationCreateSchema()
application_status_update_schema = ApplicationStatusUpdateSchema()

interview_schema        = InterviewSchema()
interviews_schema       = InterviewSchema(many=True)
interview_create_schema = InterviewCreateSchema()
interview_update_schema = InterviewUpdateSchema()
