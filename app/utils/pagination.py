"""
Utilitaire de pagination, compatible SQLAlchemy 1.x (Query) et 2.0 (Select).

Usage avec syntaxe 2.0 (recommandée, utilisée dans les services récents) :
    query = db.select(LeaveRequest).where(LeaveRequest.employee_id == 1)
    result = paginate(query)

Usage avec syntaxe 1.x (legacy, encore présente dans d'anciens fichiers) :
    query = LeaveRequest.query.filter_by(employee_id=1)
    result = paginate(query)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, List, TypeVar, Union

from flask import request
from sqlalchemy import func, select
from sqlalchemy.orm import Query
from sqlalchemy.sql import Select

T = TypeVar("T")

QueryLike = Union[Query, Select]


@dataclass
class PaginationResult(Generic[T]):
    items:    List[T]
    page:     int
    per_page: int
    total:    int
    pages:    int
    has_prev: bool
    has_next: bool
    prev_num: int | None
    next_num: int | None

    def to_dict(self) -> dict:
        return {
            "meta": {
                "page":     self.page,
                "per_page": self.per_page,
                "total":    self.total,
                "pages":    self.pages,
                "has_prev": self.has_prev,
                "has_next": self.has_next,
            }
        }


def paginate(
    query: QueryLike,
    page: int | None = None,
    per_page: int | None = None,
    max_per_page: int = 100,
) -> PaginationResult:
    """
    Pagine une requête SQLAlchemy, qu'elle soit écrite en syntaxe 1.x
    (Query, ex: Model.query.filter(...)) ou 2.0 (Select, ex: db.select(Model).where(...)).

    Lit page et per_page depuis les query params (?page=1&per_page=25)
    si non fournis explicitement.
    """
    from flask import current_app
    from app.extensions import db

    page = page or max(1, request.args.get("page", 1, type=int))
    per_page = per_page or request.args.get(
        "per_page",
        current_app.config.get("DEFAULT_PAGE_SIZE", 25),
        type=int,
    )
    per_page = min(per_page, max_per_page)

    if isinstance(query, Select):
        # ── Syntaxe SQLAlchemy 2.0 ────────────────────────────────────────────
        count_query = select(func.count()).select_from(query.subquery())
        total = db.session.execute(count_query).scalar_one()

        paged_query = query.offset((page - 1) * per_page).limit(per_page)
        items = list(db.session.execute(paged_query).scalars().all())
    else:
        # ── Syntaxe SQLAlchemy 1.x (legacy Query) ─────────────────────────────
        total = query.count()
        items = query.offset((page - 1) * per_page).limit(per_page).all()

    pages = max(1, -(-total // per_page))  # Ceiling division

    return PaginationResult(
        items=items,
        page=page,
        per_page=per_page,
        total=total,
        pages=pages,
        has_prev=page > 1,
        has_next=page < pages,
        prev_num=page - 1 if page > 1 else None,
        next_num=page + 1 if page < pages else None,
    )