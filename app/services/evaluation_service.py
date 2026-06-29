"""
Service : Evaluation (Campagnes, Évaluations, Objectifs)

Logique métier de gestion des campagnes d'évaluation, des fiches
d'évaluation individuelles et des objectifs.

Règles d'architecture :
  - Aucun objet `request` Flask ici.
  - Les erreurs métier sont des exceptions (app.utils.exceptions).
  - Les commits SQLAlchemy sont faits dans ce service.
  - Le workflow Evaluation (draft → in_progress → employee_review →
    completed → archived) est entièrement piloté par les méthodes
    d'instance du modèle ; ce service orchestre, ne réimplémente pas
    la machine à états.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select

from app.extensions import db
from app.models.employee import Employee
from app.models.evaluation import Evaluation, EvaluationCampaign, EvaluationItem
from app.models.objective import Objective
from app.utils.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ValidationError,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Campagnes d'évaluation
# =============================================================================

def create_campaign(data: dict, created_by_id: int) -> EvaluationCampaign:
    """
    Crée une nouvelle campagne d'évaluation.

    Args:
        data: dict validé (cf. EvaluationCampaignCreateSchema).
        created_by_id: ID de l'utilisateur (User) à l'origine de la création.

    Returns:
        L'instance EvaluationCampaign créée.

    Raises:
        ValidationError: champs obligatoires manquants ou dates incohérentes.
    """
    if data["end_date"] < data["start_date"]:
        raise ValidationError("La date de fin ne peut pas précéder la date de début.")

    campaign = EvaluationCampaign(
        company_id=data["company_id"],
        created_by_id=created_by_id,
        name=data["name"],
        description=data.get("description"),
        period_year=data["period_year"],
        period_type=data.get("period_type", EvaluationCampaign.PERIOD_ANNUAL),
        start_date=data["start_date"],
        end_date=data["end_date"],
        objective_deadline=data.get("objective_deadline"),
        is_active=data.get("is_active", True),
    )
    db.session.add(campaign)
    db.session.commit()

    logger.info("Campagne d'évaluation créée", extra={"campaign_id": campaign.id})
    return campaign


def get_campaign(campaign_id: int) -> EvaluationCampaign:
    campaign = db.session.get(EvaluationCampaign, campaign_id)
    if campaign is None:
        raise NotFoundError(f"Campagne d'évaluation introuvable (id={campaign_id}).")
    return campaign


def launch_campaign_for_employees(
    campaign_id: int,
    employee_evaluator_pairs: list[tuple[int, int]],
) -> list[Evaluation]:
    """
    Lance la campagne en créant une Evaluation pour chaque paire
    (employee_id, evaluator_id) fournie, et envoie immédiatement
    chaque fiche à son évaluateur (draft → in_progress).

    Args:
        campaign_id: ID de la campagne.
        employee_evaluator_pairs: liste de tuples (employee_id, evaluator_id).

    Returns:
        Liste des Evaluation créées.

    Raises:
        NotFoundError:   campagne introuvable.
        ConflictError:    une évaluation existe déjà pour une paire donnée.
        BusinessRuleError: employee_id == evaluator_id dans une paire.
    """
    campaign = get_campaign(campaign_id)
    created: list[Evaluation] = []

    for employee_id, evaluator_id in employee_evaluator_pairs:
        if employee_id == evaluator_id:
            raise BusinessRuleError(
                f"L'employé {employee_id} ne peut pas être son propre évaluateur."
            )

        existing = db.session.execute(
            select(Evaluation).where(
                Evaluation.campaign_id == campaign_id,
                Evaluation.employee_id == employee_id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError(
                f"Une évaluation existe déjà pour l'employé {employee_id} dans cette campagne."
            )

        evaluation = Evaluation(
            campaign_id=campaign.id,
            employee_id=employee_id,
            evaluator_id=evaluator_id,
            status=Evaluation.STATUS_DRAFT,
        )
        db.session.add(evaluation)
        evaluation.send_to_evaluator()
        created.append(evaluation)

    db.session.commit()

    logger.info(
        "Campagne lancée",
        extra={"campaign_id": campaign_id, "evaluation_count": len(created)},
    )
    return created


# =============================================================================
# Objectifs
# =============================================================================

def create_objective(data: dict, set_by_id: int) -> Objective:
    """
    Crée un nouvel objectif pour un employé.

    Args:
        data: dict validé (cf. ObjectiveCreateSchema).
        set_by_id: ID de l'Employee fixant l'objectif (généralement le manager).

    Returns:
        L'instance Objective créée, au statut 'active'.

    Raises:
        NotFoundError:      employee_id introuvable.
        BusinessRuleError:  set_by_id == employee_id.
    """
    if db.session.get(Employee, data["employee_id"]) is None:
        raise NotFoundError(f"Employé introuvable (id={data['employee_id']}).")

    if data["employee_id"] == set_by_id:
        raise BusinessRuleError("Un employé ne peut pas se fixer son propre objectif.")

    objective = Objective(
        employee_id=data["employee_id"],
        campaign_id=data.get("campaign_id"),
        set_by_id=set_by_id,
        title=data["title"],
        description=data.get("description"),
        success_criteria=data.get("success_criteria"),
        weight=data.get("weight", 100),
        due_date=data.get("due_date"),
        status=Objective.STATUS_DRAFT,
    )
    db.session.add(objective)
    objective.activate()
    db.session.commit()

    logger.info("Objectif créé", extra={"objective_id": objective.id})
    return objective


def get_objective(objective_id: int) -> Objective:
    objective = db.session.get(Objective, objective_id)
    if objective is None:
        raise NotFoundError(f"Objectif introuvable (id={objective_id}).")
    return objective


def update_objective_progress(objective_id: int, completion_pct: int) -> Objective:
    """Met à jour le pourcentage d'avancement d'un objectif."""
    objective = get_objective(objective_id)

    if objective.status not in Objective.ACTIVE_STATUSES:
        raise BusinessRuleError(
            f"Impossible de mettre à jour la progression d'un objectif au statut '{objective.status}'."
        )

    objective.completion_pct = completion_pct
    if completion_pct >= 100:
        objective.complete(completion_pct=100)

    db.session.commit()
    return objective


def submit_objective_rating(
    objective_id: int,
    rating: int,
    comment: Optional[str],
    *,
    rated_by: str,
) -> Objective:
    """
    Soumet une note sur un objectif, côté manager ou employé.

    Args:
        rated_by: 'manager' ou 'employee'.

    Raises:
        ValidationError: rated_by invalide.
    """
    if rated_by not in ("manager", "employee"):
        raise ValidationError(f"Valeur 'rated_by' invalide : '{rated_by}'.")

    objective = get_objective(objective_id)

    if rated_by == "manager":
        objective.submit_manager_rating(rating, comment)
    else:
        objective.submit_employee_rating(rating, comment)

    db.session.commit()
    return objective


def list_objectives_for_employee(
    employee_id: int, *, campaign_id: Optional[int] = None, active_only: bool = False
) -> list[Objective]:
    """Liste les objectifs d'un employé, filtrables par campagne ou statut actif."""
    if db.session.get(Employee, employee_id) is None:
        raise NotFoundError(f"Employé introuvable (id={employee_id}).")

    query = (
        Objective.active_for_employee(employee_id)
        if active_only
        else Objective.for_employee(employee_id, campaign_id=campaign_id)
    )
    return list(db.session.execute(query).scalars().all())


def list_objectives_set_by(manager_id: int) -> list[Objective]:
    """Objectifs actifs que ce manager a fixés pour son équipe (set_by_id = manager_id)."""
    query = Objective.active_set_by(manager_id)
    return list(db.session.execute(query).scalars().all())


# =============================================================================
# Évaluations — workflow
# =============================================================================

def create_evaluation(data: dict) -> Evaluation:
    """
    Crée une fiche d'évaluation individuelle au statut 'draft'.

    Raises:
        NotFoundError:    campaign_id, employee_id ou evaluator_id introuvable.
        ConflictError:     une évaluation existe déjà pour cette paire campagne/employé.
        BusinessRuleError: employee_id == evaluator_id.
    """
    campaign = get_campaign(data["campaign_id"])

    if db.session.get(Employee, data["employee_id"]) is None:
        raise NotFoundError(f"Employé introuvable (id={data['employee_id']}).")
    if db.session.get(Employee, data["evaluator_id"]) is None:
        raise NotFoundError(f"Évaluateur introuvable (id={data['evaluator_id']}).")
    if data["employee_id"] == data["evaluator_id"]:
        raise BusinessRuleError("L'employé évalué ne peut pas être son propre évaluateur.")

    existing = db.session.execute(
        select(Evaluation).where(
            Evaluation.campaign_id == campaign.id,
            Evaluation.employee_id == data["employee_id"],
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("Une évaluation existe déjà pour cet employé dans cette campagne.")

    evaluation = Evaluation(
        campaign_id=campaign.id,
        employee_id=data["employee_id"],
        evaluator_id=data["evaluator_id"],
        status=Evaluation.STATUS_DRAFT,
    )
    db.session.add(evaluation)
    db.session.commit()

    logger.info("Évaluation créée", extra={"evaluation_id": evaluation.id})
    return evaluation


def get_evaluation(evaluation_id: int) -> Evaluation:
    evaluation = db.session.get(Evaluation, evaluation_id)
    if evaluation is None:
        raise NotFoundError(f"Évaluation introuvable (id={evaluation_id}).")
    return evaluation


def add_evaluation_item(evaluation_id: int, data: dict) -> EvaluationItem:
    """Ajoute un critère détaillé à une évaluation (en cours de rédaction)."""
    evaluation = get_evaluation(evaluation_id)

    if evaluation.status not in (Evaluation.STATUS_DRAFT, Evaluation.STATUS_IN_PROGRESS):
        raise BusinessRuleError(
            f"Impossible d'ajouter un critère à une évaluation au statut '{evaluation.status}'."
        )

    item = EvaluationItem(
        evaluation_id=evaluation_id,
        category=data["category"],
        label=data["label"],
        description=data.get("description"),
        weight=data.get("weight", 1),
        sort_order=data.get("sort_order", 0),
    )
    db.session.add(item)
    db.session.commit()
    return item


def score_evaluation_item(item_id: int, data: dict) -> EvaluationItem:
    """Renseigne la notation (manager et/ou employé) d'un critère."""
    item = db.session.get(EvaluationItem, item_id)
    if item is None:
        raise NotFoundError(f"Critère d'évaluation introuvable (id={item_id}).")

    if "manager_score" in data:
        item.manager_score = data["manager_score"]
    if "employee_score" in data:
        item.employee_score = data["employee_score"]
    if "manager_comment" in data:
        item.manager_comment = data["manager_comment"]

    db.session.commit()
    return item


def send_to_evaluator(evaluation_id: int) -> Evaluation:
    """Transition : draft → in_progress."""
    evaluation = get_evaluation(evaluation_id)
    try:
        evaluation.send_to_evaluator()
    except ValueError as exc:
        raise BusinessRuleError(str(exc)) from exc
    db.session.commit()
    return evaluation


def submit_by_evaluator(evaluation_id: int, content: dict) -> Evaluation:
    """
    Transition : in_progress → employee_review.
    Enregistre le contenu rédigé par l'évaluateur avant la transition.
    """
    evaluation = get_evaluation(evaluation_id)

    for field in (
        "overall_score", "manager_overall_comment", "strengths",
        "areas_for_improvement", "development_plan",
    ):
        if field in content:
            setattr(evaluation, field, content[field])

    try:
        evaluation.submit_by_evaluator()
    except ValueError as exc:
        raise BusinessRuleError(str(exc)) from exc

    db.session.commit()
    return evaluation


def acknowledge_by_employee(
    evaluation_id: int, employee_comment: Optional[str] = None, sign: bool = False
) -> Evaluation:
    """
    Transition : reste en employee_review, enregistre l'accusé de réception
    et le commentaire de l'employé. La signature finale se fait via finalize().
    """
    evaluation = get_evaluation(evaluation_id)

    if employee_comment is not None:
        evaluation.employee_overall_comment = employee_comment

    signature_hash = _generate_signature_hash(evaluation, "employee") if sign else None

    try:
        evaluation.acknowledge_by_employee(signature_hash)
    except ValueError as exc:
        raise BusinessRuleError(str(exc)) from exc

    db.session.commit()
    return evaluation


def finalize_evaluation(evaluation_id: int, sign: bool = True) -> Evaluation:
    """
    Transition : employee_review → completed.
    Calcule automatiquement overall_score depuis les items si non renseigné.
    """
    evaluation = get_evaluation(evaluation_id)
    signature_hash = _generate_signature_hash(evaluation, "manager") if sign else None

    try:
        evaluation.finalize(signature_hash)
    except ValueError as exc:
        raise BusinessRuleError(str(exc)) from exc

    db.session.commit()

    logger.info("Évaluation finalisée", extra={"evaluation_id": evaluation_id})
    return evaluation


def archive_evaluation(evaluation_id: int) -> Evaluation:
    """Transition : completed → archived."""
    evaluation = get_evaluation(evaluation_id)
    try:
        evaluation.archive()
    except ValueError as exc:
        raise BusinessRuleError(str(exc)) from exc
    db.session.commit()
    return evaluation


def list_evaluations_for_employee(employee_id: int) -> list[Evaluation]:
    if db.session.get(Employee, employee_id) is None:
        raise NotFoundError(f"Employé introuvable (id={employee_id}).")
    return list(db.session.execute(Evaluation.for_employee(employee_id)).scalars().all())


def list_pending_for_evaluator(evaluator_employee_id: int) -> list[Evaluation]:
    """Évaluations à rédiger par un évaluateur (manager)."""
    return list(
        db.session.execute(Evaluation.pending_for_evaluator(evaluator_employee_id)).scalars().all()
    )


def list_pending_employee_review(employee_id: int) -> list[Evaluation]:
    """Évaluations en attente de relecture par l'employé concerné."""
    return list(
        db.session.execute(Evaluation.pending_employee_review(employee_id)).scalars().all()
    )


def list_submitted_awaiting_employee(evaluator_id: int) -> list[Evaluation]:
    """Évaluations soumises par cet évaluateur, en attente de signature de l'employé."""
    return list(
        db.session.execute(Evaluation.submitted_awaiting_employee(evaluator_id)).scalars().all()
    )


_EVAL_STATUSES = (
    Evaluation.STATUS_DRAFT,
    Evaluation.STATUS_IN_PROGRESS,
    Evaluation.STATUS_EMPLOYEE_REVIEW,
    Evaluation.STATUS_COMPLETED,
    Evaluation.STATUS_ARCHIVED,
)


def list_all_campaigns_overview(company_id: int) -> list[dict]:
    """
    Vue d'ensemble RH/admin : toutes les campagnes actives de l'entreprise avec,
    pour chacune, le nombre d'évaluations par statut (sans filtre par évaluateur).
    Retourne une liste de dicts :
        [{'campaign': EvaluationCampaign, 'counts': {'draft': 0, ..., 'total': N}}, ...]
    """
    campaigns = db.session.execute(
        EvaluationCampaign.active_in_company(company_id)
    ).scalars().all()

    if not campaigns:
        return []

    campaign_ids = [c.id for c in campaigns]

    rows = db.session.execute(
        db.select(
            Evaluation.campaign_id,
            Evaluation.status,
            func.count(Evaluation.id).label("cnt"),
        )
        .where(Evaluation.campaign_id.in_(campaign_ids))
        .group_by(Evaluation.campaign_id, Evaluation.status)
    ).all()

    counts_map: dict[int, dict] = {}
    for row in rows:
        if row.campaign_id not in counts_map:
            counts_map[row.campaign_id] = {s: 0 for s in _EVAL_STATUSES}
        counts_map[row.campaign_id][row.status] = row.cnt

    result = []
    for campaign in campaigns:
        counts = counts_map.get(campaign.id, {s: 0 for s in _EVAL_STATUSES})
        counts["total"] = sum(counts.get(s, 0) for s in _EVAL_STATUSES)
        result.append({"campaign": campaign, "counts": counts})

    return result


# =============================================================================
# Helpers privés
# =============================================================================

def _generate_signature_hash(evaluation: Evaluation, signer: str) -> str:
    """
    Génère un hash SHA-256 simple du contenu de l'évaluation au moment
    de la signature — preuve d'intégrité basique, pas une signature
    cryptographique légale.
    """
    content = (
        f"{evaluation.id}|{evaluation.overall_score}|{evaluation.strengths}|"
        f"{evaluation.areas_for_improvement}|{evaluation.development_plan}|"
        f"{signer}|{datetime.now(timezone.utc).isoformat()}"
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()