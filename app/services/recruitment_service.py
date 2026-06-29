"""
Service : Recrutement
  JobPosting · Candidate · Application · Interview

Logique métier du pipeline de recrutement :
    - Création et gestion des offres d'emploi (JobPosting)
    - Gestion du vivier de candidats (Candidate)
    - Soumission et suivi des candidatures (Application)
    - Planification et enregistrement des entretiens (Interview)

Règles d'architecture :
    - Aucun objet `request` Flask ici.
    - Les erreurs métier sont des exceptions (app.utils.exceptions).
    - Les commits SQLAlchemy sont faits dans ce service.
    - Les transitions de statut Application sont déléguées aux méthodes
      d'instance du modèle ; ce service orchestre et valide les pré-conditions.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.extensions import db
from app.models.employee import Employee
from app.models.department import Department
from app.models.recruitment import Application, Candidate, Interview, JobPosting
from app.utils.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ValidationError,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Helpers privés
# =============================================================================

def _get_job_posting_or_404(job_posting_id: int) -> JobPosting:
    jp = db.session.get(JobPosting, job_posting_id)
    if jp is None:
        raise NotFoundError(f"Offre d'emploi introuvable (id={job_posting_id}).")
    return jp


def _get_candidate_or_404(candidate_id: int) -> Candidate:
    c = db.session.get(Candidate, candidate_id)
    if c is None:
        raise NotFoundError(f"Candidat introuvable (id={candidate_id}).")
    return c


def _get_application_or_404(application_id: int) -> Application:
    a = db.session.get(Application, application_id)
    if a is None:
        raise NotFoundError(f"Candidature introuvable (id={application_id}).")
    return a


def _get_interview_or_404(interview_id: int) -> Interview:
    i = db.session.get(Interview, interview_id)
    if i is None:
        raise NotFoundError(f"Entretien introuvable (id={interview_id}).")
    return i


# =============================================================================
# JobPosting — Offres d'emploi
# =============================================================================

def create_job_posting(data: dict) -> JobPosting:
    """
    Crée une nouvelle offre d'emploi.

    Si `status` vaut 'open' et que `published_at` n'est pas fourni,
    la date de publication est fixée à aujourd'hui.

    Args:
        data: dict validé (cf. JobPostingCreateSchema).
              Champ obligatoire : title.
              Champs optionnels : company_id, department_id, position_id,
                                  description, requirements, location,
                                  contract_type, salary_min, salary_max,
                                  headcount, status, published_at, closing_date.

    Returns:
        L'instance JobPosting créée et commitée.

    Raises:
        ValidationError:  titre vide, statut invalide, salaire incohérent.
        NotFoundError:    department_id ou position_id inexistant.
    """
    title = data.get("title", "").strip()
    if not title:
        raise ValidationError("Le titre de l'offre ne peut pas être vide.")

    status = data.get("status", JobPosting.STATUS_DRAFT)
    if status not in JobPosting.STATUSES:
        raise ValidationError(
            f"Statut d'offre invalide : {status!r}. "
            f"Valeurs acceptées : {JobPosting.STATUSES}."
        )

    salary_min = data.get("salary_min")
    salary_max = data.get("salary_max")
    if salary_min is not None and salary_max is not None and salary_max < salary_min:
        raise ValidationError(
            "salary_max doit être supérieur ou égal à salary_min.",
            details={"salary_min": salary_min, "salary_max": salary_max},
        )

    # Vérifie les FK optionnelles
    dept_id = data.get("department_id")
    if dept_id is not None and db.session.get(Department, dept_id) is None:
        raise NotFoundError(f"Département introuvable (id={dept_id}).")

    published_at = data.get("published_at")
    if status == JobPosting.STATUS_OPEN and published_at is None:
        from datetime import date
        published_at = date.today()

    job_posting = JobPosting(
        company_id=data.get("company_id"),
        department_id=dept_id,
        position_id=data.get("position_id"),
        created_by_id=data.get("created_by_id"),
        title=title,
        description=data.get("description"),
        requirements=data.get("requirements"),
        location=data.get("location"),
        contract_type=data.get("contract_type"),
        salary_min=salary_min,
        salary_max=salary_max,
        headcount=data.get("headcount", 1),
        status=status,
        published_at=published_at,
        closing_date=data.get("closing_date"),
    )
    db.session.add(job_posting)
    db.session.commit()

    logger.info(
        "Offre d'emploi creee",
        extra={"job_posting_id": job_posting.id, "title": job_posting.title},
    )
    return job_posting


def get_job_posting(job_posting_id: int) -> JobPosting:
    """Retourne une offre par son id ou lève NotFoundError."""
    return _get_job_posting_or_404(job_posting_id)


def update_job_posting(job_posting_id: int, data: dict) -> JobPosting:
    """
    Met à jour les champs d'une offre d'emploi (PATCH).

    Le changement de statut est orchestré via les méthodes du modèle
    (publish / close / cancel) plutôt que par assignation directe, afin
    de garantir les invariants (ex : published_at automatique).

    Args:
        job_posting_id: ID de l'offre.
        data: dict validé (cf. JobPostingUpdateSchema).

    Returns:
        L'instance JobPosting mise à jour.

    Raises:
        NotFoundError:    offre introuvable.
        BusinessRuleError: transition de statut invalide.
        ValidationError:  valeur de champ invalide.
    """
    jp = _get_job_posting_or_404(job_posting_id)

    new_status = data.pop("status", None)
    if new_status is not None and new_status != jp.status:
        try:
            if new_status == JobPosting.STATUS_OPEN:
                jp.publish()
            elif new_status == JobPosting.STATUS_CLOSED:
                jp.close()
            elif new_status == JobPosting.STATUS_CANCELLED:
                jp.cancel()
            elif new_status == JobPosting.STATUS_DRAFT:
                raise BusinessRuleError(
                    "Une offre ne peut pas revenir au statut brouillon après publication."
                )
        except ValueError as exc:
            raise BusinessRuleError(str(exc)) from exc

    updatable = (
        "department_id", "position_id", "title", "description",
        "requirements", "location", "contract_type",
        "salary_min", "salary_max", "headcount", "closing_date",
    )
    for field in updatable:
        if field in data:
            setattr(jp, field, data[field])

    db.session.commit()
    logger.info("Offre d'emploi mise a jour", extra={"job_posting_id": job_posting_id})
    return jp


def list_job_postings(
    company_id: Optional[int] = None,
    *,
    status: Optional[str] = None,
    department_id: Optional[int] = None,
) -> list[JobPosting]:
    """
    Retourne les offres d'emploi, filtrables par entreprise, statut et département.

    Args:
        company_id:    Si fourni, filtre sur l'entreprise (None = toutes).
        status:        Filtre optionnel sur le statut ('open', 'draft'…).
        department_id: Filtre optionnel sur le département.

    Returns:
        Liste de JobPosting triée par date de publication décroissante puis titre.

    Raises:
        ValidationError: valeur de statut inconnue.
    """
    if status is not None and status not in JobPosting.STATUSES:
        raise ValidationError(
            f"Statut d'offre invalide : {status!r}. "
            f"Valeurs acceptées : {JobPosting.STATUSES}."
        )

    query = db.select(JobPosting)

    if company_id is not None:
        query = query.where(JobPosting.company_id == company_id)

    if status is not None:
        query = query.where(JobPosting.status == status)

    if department_id is not None:
        query = query.where(JobPosting.department_id == department_id)

    query = query.order_by(
        JobPosting.published_at.desc().nullslast(),
        JobPosting.title,
    )
    return list(db.session.execute(query).scalars().all())


# =============================================================================
# Candidate — Vivier candidats
# =============================================================================

def create_candidate(data: dict) -> Candidate:
    """
    Crée un nouveau candidat dans le vivier.

    Si un candidat avec le même email existe déjà, lève ConflictError.
    L'email est normalisé en minuscules avant toute comparaison.

    Args:
        data: dict validé (cf. CandidateCreateSchema).
              Champs obligatoires : first_name, last_name, email.
              Champs optionnels  : phone, cv_path, cv_text, source, notes.

    Returns:
        L'instance Candidate créée et commitée.

    Raises:
        ValidationError: champs obligatoires manquants.
        ConflictError:   email déjà présent dans le vivier.
    """
    for required in ("first_name", "last_name", "email"):
        if not data.get(required, "").strip():
            raise ValidationError(f"Le champ '{required}' est obligatoire.")

    email = data["email"].strip().lower()

    existing = Candidate.find_by_email(email)
    if existing is not None:
        raise ConflictError(
            f"Un candidat avec l'adresse e-mail {email!r} existe déjà (id={existing.id})."
        )

    candidate = Candidate(
        first_name=data["first_name"].strip(),
        last_name=data["last_name"].strip(),
        email=email,
        phone=data.get("phone"),
        cv_path=data.get("cv_path"),
        cv_text=data.get("cv_text"),
        source=data.get("source", Candidate.SOURCE_OTHER),
        notes=data.get("notes"),
    )
    db.session.add(candidate)
    db.session.commit()

    logger.info(
        "Candidat cree",
        extra={"candidate_id": candidate.id, "email": candidate.email},
    )
    return candidate


def get_candidate(candidate_id: int) -> Candidate:
    """Retourne un candidat par son id ou lève NotFoundError."""
    return _get_candidate_or_404(candidate_id)


def update_candidate(candidate_id: int, data: dict) -> Candidate:
    """
    Met à jour les informations d'un candidat (PATCH).

    Args:
        candidate_id: ID du candidat.
        data: dict validé (cf. CandidateUpdateSchema).

    Returns:
        L'instance Candidate mise à jour.

    Raises:
        NotFoundError: candidat introuvable.
        ConflictError: nouvel email déjà utilisé par un autre candidat.
    """
    candidate = _get_candidate_or_404(candidate_id)

    new_email = data.get("email")
    if new_email:
        new_email = new_email.strip().lower()
        existing = Candidate.find_by_email(new_email)
        if existing is not None and existing.id != candidate_id:
            raise ConflictError(
                f"L'e-mail {new_email!r} est déjà utilisé par le candidat id={existing.id}."
            )
        data["email"] = new_email

    updatable = ("first_name", "last_name", "email", "phone",
                  "cv_path", "cv_text", "source", "notes")
    for field in updatable:
        if field in data:
            setattr(candidate, field, data[field])

    db.session.commit()
    logger.info("Candidat mis a jour", extra={"candidate_id": candidate_id})
    return candidate


def list_candidates() -> list[Candidate]:
    """Retourne tous les candidats triés par nom de famille puis prénom."""
    return list(
        db.session.execute(
            db.select(Candidate).order_by(Candidate.last_name, Candidate.first_name)
        ).scalars().all()
    )


# =============================================================================
# Application — Candidatures
# =============================================================================

def submit_application(data: dict) -> Application:
    """
    Soumet une candidature (statut initial : 'recue').

    Un candidat ne peut pas postuler deux fois à la même offre : une
    UniqueConstraint (candidate_id, job_posting_id) le garantit en base,
    mais le service lève ConflictError avant d'atteindre la contrainte.

    L'offre doit être ouverte (statut 'open') pour accepter des candidatures.

    Args:
        data: dict validé (cf. ApplicationCreateSchema).
              Champs obligatoires : candidate_id, job_posting_id.
              Champs optionnels  : applied_at, notes.

    Returns:
        L'instance Application créée et commitée.

    Raises:
        NotFoundError:    candidate_id ou job_posting_id introuvable.
        BusinessRuleError: l'offre n'est pas ouverte.
        ConflictError:     candidature déjà existante pour ce couple.
    """
    candidate_id   = data["candidate_id"]
    job_posting_id = data["job_posting_id"]

    _get_candidate_or_404(candidate_id)
    jp = _get_job_posting_or_404(job_posting_id)

    if jp.status != JobPosting.STATUS_OPEN:
        raise BusinessRuleError(
            f"L'offre « {jp.title} » n'est pas ouverte aux candidatures "
            f"(statut actuel : {jp.status!r})."
        )

    existing = db.session.execute(
        select(Application).where(
            Application.candidate_id == candidate_id,
            Application.job_posting_id == job_posting_id,
        )
    ).scalar_one_or_none()

    if existing is not None:
        raise ConflictError(
            f"Le candidat {candidate_id} a déjà postulé à cette offre "
            f"(candidature id={existing.id}, statut={existing.status!r})."
        )

    applied_at = data.get("applied_at") or datetime.now(timezone.utc)

    application = Application(
        candidate_id=candidate_id,
        job_posting_id=job_posting_id,
        status=Application.STATUS_RECEIVED,
        applied_at=applied_at,
        notes=data.get("notes"),
    )
    db.session.add(application)
    db.session.commit()

    logger.info(
        "Candidature soumise",
        extra={
            "application_id": application.id,
            "candidate_id": candidate_id,
            "job_posting_id": job_posting_id,
        },
    )
    return application


def get_application(application_id: int) -> Application:
    """Retourne une candidature par son id ou lève NotFoundError."""
    return _get_application_or_404(application_id)


def update_application_status(application_id: int, data: dict) -> Application:
    """
    Applique une transition de statut à une candidature.

    Transitions légales (déléguées aux méthodes du modèle) :
        recue           → preselectionnee  (via prescreen)
        preselectionnee → entretien        (via advance_to_interview)
        entretien       → offre            (via make_offer)
        offre           → embauchee        (via hire)
        tout sauf embauchee → refusee      (via reject, + rejection_reason optionnel)

    Args:
        application_id: ID de la candidature.
        data: dict validé (cf. ApplicationStatusUpdateSchema).
              Champ obligatoire : status (cible).
              Champs optionnels : rejection_reason, notes.

    Returns:
        L'instance Application mise à jour.

    Raises:
        NotFoundError:     candidature introuvable.
        BusinessRuleError: transition illégale depuis le statut actuel.
        ValidationError:   statut cible inconnu.
    """
    application = _get_application_or_404(application_id)
    target_status = data["status"]

    if target_status not in Application.STATUSES:
        raise ValidationError(
            f"Statut de candidature invalide : {target_status!r}. "
            f"Valeurs acceptées : {Application.STATUSES}."
        )

    try:
        if target_status == Application.STATUS_PRESCREENED:
            application.prescreen()
        elif target_status == Application.STATUS_INTERVIEW:
            application.advance_to_interview()
        elif target_status == Application.STATUS_OFFER:
            application.make_offer()
        elif target_status == Application.STATUS_HIRED:
            application.hire()
        elif target_status == Application.STATUS_REJECTED:
            application.reject(reason=data.get("rejection_reason"))
        else:
            raise BusinessRuleError(
                f"La transition vers le statut '{target_status}' n'est pas supportée "
                f"depuis '{application.status}'."
            )
    except ValueError as exc:
        raise BusinessRuleError(str(exc)) from exc

    if data.get("notes") is not None:
        application.notes = data["notes"]

    db.session.commit()

    logger.info(
        "Statut candidature mis a jour",
        extra={"application_id": application_id, "status": target_status},
    )
    return application


def list_applications_for_posting(
    job_posting_id: int,
    *,
    status: Optional[str] = None,
) -> list[Application]:
    """
    Retourne les candidatures pour une offre d'emploi donnée.

    Args:
        job_posting_id: ID de l'offre.
        status:         Filtre optionnel sur le statut de la candidature.

    Returns:
        Liste d'Application triée par date de candidature décroissante.

    Raises:
        NotFoundError:   offre introuvable.
        ValidationError: valeur de statut inconnue.
    """
    _get_job_posting_or_404(job_posting_id)

    if status is not None and status not in Application.STATUSES:
        raise ValidationError(
            f"Statut de candidature invalide : {status!r}. "
            f"Valeurs acceptées : {Application.STATUSES}."
        )

    query = db.select(Application).where(
        Application.job_posting_id == job_posting_id
    )
    if status is not None:
        query = query.where(Application.status == status)

    query = query.order_by(Application.applied_at.desc())
    return list(db.session.execute(query).scalars().all())


def list_applications_for_candidate(
    candidate_id: int,
    *,
    status: Optional[str] = None,
) -> list[Application]:
    """
    Retourne toutes les candidatures d'un candidat (tous postes confondus).

    Args:
        candidate_id: ID du candidat.
        status:       Filtre optionnel sur le statut.

    Returns:
        Liste d'Application triée par date de candidature décroissante.

    Raises:
        NotFoundError: candidat introuvable.
    """
    _get_candidate_or_404(candidate_id)

    query = db.select(Application).where(Application.candidate_id == candidate_id)
    if status is not None:
        if status not in Application.STATUSES:
            raise ValidationError(
                f"Statut invalide : {status!r}. Valeurs acceptées : {Application.STATUSES}."
            )
        query = query.where(Application.status == status)

    query = query.order_by(Application.applied_at.desc())
    return list(db.session.execute(query).scalars().all())


# =============================================================================
# Interview — Entretiens
# =============================================================================

def schedule_interview(data: dict) -> Interview:
    """
    Planifie un entretien pour une candidature.

    L'entretien ne peut être planifié que si la candidature est au statut
    'entretien' (la transition de statut de la candidature est gérée
    séparément via update_application_status).

    Args:
        data: dict validé (cf. InterviewCreateSchema).
              Champs obligatoires : application_id, scheduled_at.
              Champs optionnels  : interviewer_id, duration_minutes,
                                   location, interview_type.

    Returns:
        L'instance Interview créée et commitée.

    Raises:
        NotFoundError:     application_id introuvable.
        BusinessRuleError: la candidature n'est pas au stade 'entretien'.
        NotFoundError:     interviewer_id introuvable.
    """
    application_id = data["application_id"]
    application = _get_application_or_404(application_id)

    if application.status != Application.STATUS_INTERVIEW:
        raise BusinessRuleError(
            f"Les entretiens ne peuvent être planifiés que pour une candidature "
            f"au statut 'entretien' (statut actuel : {application.status!r}). "
            f"Utilisez update_application_status pour avancer le pipeline d'abord."
        )

    interviewer_id = data.get("interviewer_id")
    if interviewer_id is not None:
        if db.session.get(Employee, interviewer_id) is None:
            raise NotFoundError(f"Interviewer introuvable (employee id={interviewer_id}).")

    scheduled_at = data["scheduled_at"]

    interview = Interview(
        application_id=application_id,
        interviewer_id=interviewer_id,
        scheduled_at=scheduled_at,
        duration_minutes=data.get("duration_minutes", 60),
        location=data.get("location"),
        interview_type=data.get("interview_type", Interview.TYPE_HR),
        decision=Interview.DECISION_PENDING,
    )
    db.session.add(interview)
    db.session.commit()

    logger.info(
        "Entretien planifie",
        extra={
            "interview_id": interview.id,
            "application_id": application_id,
            "scheduled_at": str(scheduled_at),
        },
    )
    return interview


def get_interview(interview_id: int) -> Interview:
    """Retourne un entretien par son id ou lève NotFoundError."""
    return _get_interview_or_404(interview_id)


def update_interview(interview_id: int, data: dict) -> Interview:
    """
    Met à jour un entretien (replanification ou enregistrement du résultat).

    Args:
        interview_id: ID de l'entretien.
        data: dict validé (cf. InterviewUpdateSchema).

    Returns:
        L'instance Interview mise à jour.

    Raises:
        NotFoundError:     entretien ou interviewer introuvable.
        BusinessRuleError: note fournie sans décision.
    """
    interview = _get_interview_or_404(interview_id)

    new_interviewer_id = data.get("interviewer_id")
    if new_interviewer_id is not None:
        if db.session.get(Employee, new_interviewer_id) is None:
            raise NotFoundError(
                f"Interviewer introuvable (employee id={new_interviewer_id})."
            )

    updatable = (
        "interviewer_id", "scheduled_at", "duration_minutes", "location",
        "interview_type", "notes", "decision", "rating",
    )
    for field in updatable:
        if field in data:
            setattr(interview, field, data[field])

    db.session.commit()
    logger.info("Entretien mis a jour", extra={"interview_id": interview_id})
    return interview


def list_interviews_for_application(application_id: int) -> list[Interview]:
    """
    Retourne les entretiens liés à une candidature, triés par date planifiée.

    Raises:
        NotFoundError: candidature introuvable.
    """
    _get_application_or_404(application_id)

    return list(
        db.session.execute(
            db.select(Interview)
            .where(Interview.application_id == application_id)
            .order_by(Interview.scheduled_at)
        ).scalars().all()
    )


# =============================================================================
# Pont recrutement → RH
# =============================================================================

def prepare_employee_data_from_application(application_id: int) -> dict:
    """
    Retourne un dict pré-rempli à partir d'une candidature embauchée,
    prêt à être injecté dans le formulaire de création employé existant.

    Seules les données disponibles dans le dossier candidat sont copiées :
    nom, prénom, email personnel et téléphone. Les champs RH (département,
    poste, date d'entrée…) doivent être complétés manuellement par le RH.

    Args:
        application_id: ID de la candidature (doit être au statut 'embauchee').

    Returns:
        dict avec les clés :
            first_name, last_name, personal_email, phone,
            department_id, position_id,  # depuis l'offre si renseignés
            source_application_id        # pour traçabilité

    Raises:
        NotFoundError:     candidature introuvable.
        BusinessRuleError: candidature pas encore au statut 'embauchee'.
    """
    application = _get_application_or_404(application_id)

    if application.status != Application.STATUS_HIRED:
        raise BusinessRuleError(
            f"La candidature {application_id} n'est pas encore embauchée "
            f"(statut actuel : {application.status!r}). "
            f"Passez-la au statut 'embauchee' avant de créer la fiche employé."
        )

    candidate   = application.candidate
    job_posting = application.job_posting

    return {
        # Identité — copiée directement depuis le candidat
        "first_name":     candidate.first_name,
        "last_name":      candidate.last_name,
        "personal_email": candidate.email,
        "phone":          candidate.phone,
        # Structure organisationnelle — pré-remplie depuis l'offre si disponible
        "department_id":  job_posting.department_id if job_posting else None,
        "position_id":    job_posting.position_id   if job_posting else None,
        # Traçabilité recrutement → dossier employé
        "source_application_id": application_id,
    }


def link_hired_employee(application_id: int, employee_id: int) -> Application:
    """
    Associe la fiche employé nouvellement créée à la candidature embauchée.

    À appeler juste après la création de l'employé, pour refermer la boucle
    recrutement → RH et renseigner `Application.hired_employee_id`.

    Args:
        application_id: ID de la candidature (statut 'embauchee').
        employee_id:    ID de la fiche employé créée.

    Returns:
        L'instance Application mise à jour.

    Raises:
        NotFoundError:     candidature ou employé introuvable.
        BusinessRuleError: candidature pas au statut 'embauchee',
                           ou lien déjà établi.
    """
    application = _get_application_or_404(application_id)

    if application.status != Application.STATUS_HIRED:
        raise BusinessRuleError(
            f"Le lien ne peut être établi que pour une candidature embauchée "
            f"(statut actuel : {application.status!r})."
        )

    if application.hired_employee_id is not None:
        raise BusinessRuleError(
            f"La candidature {application_id} est déjà liée à l'employé "
            f"id={application.hired_employee_id}."
        )

    if db.session.get(Employee, employee_id) is None:
        raise NotFoundError(f"Employé introuvable (id={employee_id}).")

    application.hired_employee_id = employee_id
    db.session.commit()

    logger.info(
        "Candidature liee a l'employe",
        extra={"application_id": application_id, "employee_id": employee_id},
    )
    return application
