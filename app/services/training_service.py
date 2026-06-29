"""
Service : Training · Enrollment (Formations et inscriptions)

Logique métier de gestion du catalogue de formations et des inscriptions
individuelles.

Règles d'architecture :
  - Aucun objet `request` Flask ici.
  - Les erreurs métier sont des exceptions (app.utils.exceptions).
  - Les commits SQLAlchemy sont faits dans ce service.
  - Les transitions de statut Enrollment sont déléguées aux méthodes
    d'instance du modèle (start / complete / cancel) ; ce service
    orchestre et valide les pré-conditions, il ne réimplémente pas
    la machine à états.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select

from app.extensions import db
from app.models.employee import Employee
from app.models.training import Enrollment, Training
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

def _get_training_or_404(training_id: int) -> Training:
    t = db.session.get(Training, training_id)
    if t is None:
        raise NotFoundError(f"Formation introuvable (id={training_id}).")
    return t


def _get_enrollment_or_404(enrollment_id: int) -> Enrollment:
    e = db.session.get(Enrollment, enrollment_id)
    if e is None:
        raise NotFoundError(f"Inscription introuvable (id={enrollment_id}).")
    return e


# =============================================================================
# Training — CRUD catalogue
# =============================================================================

def create_training(data: dict) -> Training:
    """
    Crée une nouvelle formation dans le catalogue.

    Args:
        data: dict validé (cf. TrainingCreateSchema).
              Champs obligatoires : title, training_type.
              Champs optionnels  : company_id, description, organisme,
                                   duration_hours, cost, is_active.

    Returns:
        L'instance Training créée et commitée.

    Raises:
        ValidationError: training_type invalide ou title vide.
    """
    if not data.get("title", "").strip():
        raise ValidationError("Le titre de la formation ne peut pas être vide.")

    training_type = data.get("training_type", Training.VALID_TYPES[0])
    if training_type not in Training.VALID_TYPES:
        raise ValidationError(
            f"Type de formation invalide : {training_type!r}. "
            f"Valeurs acceptées : {Training.VALID_TYPES}."
        )

    training = Training(
        company_id=data.get("company_id"),
        title=data["title"].strip(),
        description=data.get("description"),
        organisme=data.get("organisme"),
        duration_hours=data.get("duration_hours"),
        training_type=training_type,
        cost=data.get("cost"),
        is_active=data.get("is_active", True),
    )
    db.session.add(training)
    db.session.commit()

    logger.info("Formation créée", extra={"training_id": training.id, "title": training.title})
    return training


def get_training(training_id: int) -> Training:
    """Retourne une formation par son id ou lève NotFoundError."""
    return _get_training_or_404(training_id)


def update_training(training_id: int, data: dict) -> Training:
    """
    Met à jour les champs d'une formation (PATCH — seuls les champs présents
    dans `data` sont modifiés).

    Args:
        training_id: ID de la formation.
        data: dict validé (cf. TrainingUpdateSchema).

    Returns:
        L'instance Training mise à jour.

    Raises:
        NotFoundError:   formation introuvable.
        ValidationError: valeur invalide (type, titre vide, etc.).
    """
    training = _get_training_or_404(training_id)

    updatable = (
        "title", "description", "organisme",
        "duration_hours", "training_type", "cost", "is_active",
    )
    for field in updatable:
        if field in data:
            setattr(training, field, data[field])

    db.session.commit()
    logger.info("Formation mise à jour", extra={"training_id": training_id})
    return training


def list_trainings(
    company_id: Optional[int] = None,
    *,
    active_only: bool = True,
    training_type: Optional[str] = None,
) -> list[Training]:
    """
    Retourne les formations du catalogue, filtrables par entreprise,
    statut actif et type.

    Args:
        company_id:    Si fourni, inclut les formations de cette entreprise
                       ET les formations sans company_id (catalogue global).
                       Si None, retourne toutes les formations (usage admin).
        active_only:   Si True (défaut), exclut les formations désactivées.
        training_type: Filtre optionnel sur le mode de diffusion.

    Returns:
        Liste de Training triée par titre.
    """
    query = db.select(Training)

    if company_id is not None:
        query = query.where(
            db.or_(Training.company_id == company_id, Training.company_id.is_(None))
        )

    if active_only:
        query = query.where(Training.is_active.is_(True))

    if training_type is not None:
        if training_type not in Training.VALID_TYPES:
            raise ValidationError(
                f"Type de formation invalide : {training_type!r}. "
                f"Valeurs acceptées : {Training.VALID_TYPES}."
            )
        query = query.where(Training.training_type == training_type)

    query = query.order_by(Training.title)
    return list(db.session.execute(query).scalars().all())


# =============================================================================
# Enrollment — inscriptions
# =============================================================================

def enroll_employee(data: dict) -> Enrollment:
    """
    Inscrit un employé à une formation (statut initial : 'planifiee').

    Args:
        data: dict validé (cf. EnrollmentCreateSchema).
              Champs obligatoires : employee_id, training_id.
              Champs optionnels  : start_date, end_date.

    Returns:
        L'instance Enrollment créée.

    Raises:
        NotFoundError:     employee_id ou training_id introuvable.
        BusinessRuleError: la formation est désactivée.
        ConflictError:     une inscription active (non annulée) existe déjà
                           pour ce doublon employee × training × période.
    """
    employee_id = data["employee_id"]
    training_id = data["training_id"]

    if db.session.get(Employee, employee_id) is None:
        raise NotFoundError(f"Employé introuvable (id={employee_id}).")

    training = _get_training_or_404(training_id)

    if not training.is_active:
        raise BusinessRuleError(
            f"La formation « {training.title} » est désactivée et n'accepte plus d'inscriptions."
        )

    # Vérifie l'absence d'une inscription active en cours (planifiee ou en_cours)
    # pour la même paire afin d'éviter les doublons opérationnels.
    active_statuses = (Enrollment.STATUS_PLANNED, Enrollment.STATUS_IN_PROGRESS)
    existing = db.session.execute(
        select(Enrollment).where(
            Enrollment.employee_id == employee_id,
            Enrollment.training_id == training_id,
            Enrollment.status.in_(active_statuses),
        )
    ).scalar_one_or_none()

    if existing is not None:
        raise ConflictError(
            f"L'employé {employee_id} possède déjà une inscription active "
            f"(id={existing.id}, statut={existing.status!r}) à cette formation."
        )

    enrollment = Enrollment(
        employee_id=employee_id,
        training_id=training_id,
        status=Enrollment.STATUS_PLANNED,
        start_date=data.get("start_date"),
        end_date=data.get("end_date"),
    )
    db.session.add(enrollment)
    db.session.commit()

    logger.info(
        "Inscription créée",
        extra={"enrollment_id": enrollment.id, "employee_id": employee_id, "training_id": training_id},
    )
    return enrollment


def get_enrollment(enrollment_id: int) -> Enrollment:
    """Retourne une inscription par son id ou lève NotFoundError."""
    return _get_enrollment_or_404(enrollment_id)


def update_enrollment_status(enrollment_id: int, data: dict) -> Enrollment:
    """
    Applique une transition de statut à une inscription et persiste les
    données complémentaires associées à cette transition.

    Transitions légales et données attendues :
        planifiee  → en_cours   : start_date (optionnel)
        en_cours   → terminee   : end_date, score (0-100), final_comment (optionnels)
        planifiee
        ou en_cours → annulee   : aucune donnée complémentaire

    Args:
        enrollment_id: ID de l'inscription.
        data: dict validé (cf. EnrollmentStatusUpdateSchema).
              Champ obligatoire : status (cible).

    Returns:
        L'instance Enrollment mise à jour.

    Raises:
        NotFoundError:     inscription introuvable.
        BusinessRuleError: transition de statut illégale (délégué au modèle).
        ValidationError:   score hors plage ou status inconnu.
    """
    enrollment = _get_enrollment_or_404(enrollment_id)
    target_status = data["status"]

    if target_status not in Enrollment.STATUSES:
        raise ValidationError(
            f"Statut d'inscription invalide : {target_status!r}. "
            f"Valeurs acceptées : {Enrollment.STATUSES}."
        )

    try:
        if target_status == Enrollment.STATUS_IN_PROGRESS:
            enrollment.start(start_date=data.get("start_date"))

        elif target_status == Enrollment.STATUS_COMPLETED:
            # FIX D-1 : conversion explicite en float avant passage au modèle
            score_raw = data.get("score")
            score = float(score_raw) if score_raw is not None else None
            if score is not None and not (0 <= score <= 100):
                raise ValidationError("Le score doit être compris entre 0 et 100.")
            enrollment.complete(
                end_date=data.get("end_date"),
                score=score,
                comment=data.get("final_comment"),
            )

        elif target_status == Enrollment.STATUS_CANCELLED:
            enrollment.cancel()

        else:
            # Retour vers 'planifiee' non supporté (historique immuable)
            raise BusinessRuleError(
                f"La transition vers le statut 'planifiee' n'est pas autorisée "
                f"depuis '{enrollment.status}'."
            )

    except ValueError as exc:
        raise BusinessRuleError(str(exc)) from exc

    db.session.commit()

    logger.info(
        "Statut inscription mis à jour",
        extra={"enrollment_id": enrollment_id, "status": target_status},
    )
    return enrollment


def list_enrollments_for_employee(
    employee_id: int,
    *,
    status: Optional[str] = None,
    active_only: bool = False,
) -> list[Enrollment]:
    """
    Retourne les inscriptions d'un employé.

    Args:
        employee_id: ID de l'employé.
        status:      Filtre optionnel sur un statut précis.
        active_only: Si True, exclut les inscriptions annulées (prend le
                     dessus sur `status` si les deux sont fournis).

    Returns:
        Liste d'Enrollment triée par date de création décroissante.

    Raises:
        NotFoundError:  employé introuvable.
        ValidationError: valeur de `status` inconnue.
    """
    if db.session.get(Employee, employee_id) is None:
        raise NotFoundError(f"Employé introuvable (id={employee_id}).")

    if status is not None and status not in Enrollment.STATUSES:
        raise ValidationError(
            f"Statut d'inscription invalide : {status!r}. "
            f"Valeurs acceptées : {Enrollment.STATUSES}."
        )

    if active_only:
        query = Enrollment.active_for_employee(employee_id)
    elif status is not None:
        query = (
            db.select(Enrollment)
            .where(Enrollment.employee_id == employee_id, Enrollment.status == status)
            .order_by(Enrollment.created_at.desc())
        )
    else:
        query = Enrollment.for_employee(employee_id)

    return list(db.session.execute(query).scalars().all())


def list_enrollments_for_training(
    training_id: int,
    *,
    status: Optional[str] = None,
) -> list[Enrollment]:
    """
    Retourne les inscriptions à une formation donnée.

    Args:
        training_id: ID de la formation.
        status:      Filtre optionnel sur un statut précis.

    Returns:
        Liste d'Enrollment triée par date de création décroissante.

    Raises:
        NotFoundError:  formation introuvable.
        ValidationError: valeur de `status` inconnue.
    """
    _get_training_or_404(training_id)

    if status is not None and status not in Enrollment.STATUSES:
        raise ValidationError(
            f"Statut d'inscription invalide : {status!r}. "
            f"Valeurs acceptées : {Enrollment.STATUSES}."
        )

    query = (
        db.select(Enrollment)
        .where(Enrollment.training_id == training_id)
    )
    if status is not None:
        query = query.where(Enrollment.status == status)

    query = query.order_by(Enrollment.created_at.desc())
    return list(db.session.execute(query).scalars().all())
