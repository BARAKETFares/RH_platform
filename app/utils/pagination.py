"""
Utilitaire de pagination pour les requêtes SQLAlchemy.

Usage dans une route :
    from app.utils.pagination import paginate
    result = paginate(Employee.query.filter_by(status="active"))
    return render_template("employees/list.html", pagination=result)

Usage dans l'API :
    return jsonify(result.to_dict())
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, List, TypeVar

from flask import request
from sqlalchemy.orm import Query

T = TypeVar("T")


@dataclass
class PaginationResult(Generic[T]):
    items:        List[T]
    page:         int
    per_page:     int
    total:        int
    pages:        int
    has_prev:     bool
    has_next:     bool
    prev_num:     int | None
    next_num:     int | None

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
    query: Query,
    page: int | None = None,
    per_page: int | None = None,
    max_per_page: int = 100,
) -> PaginationResult:
    """
    Pagine une requête SQLAlchemy.

    Lit page et per_page depuis les query params (?page=1&per_page=25)
    si non fournis explicitement.
    """
    from flask import current_app

    page = page or max(1, request.args.get("page", 1, type=int))
    per_page = per_page or request.args.get(
        "per_page",
        current_app.config.get("DEFAULT_PAGE_SIZE", 25),
        type=int,
    )
    per_page = min(per_page, max_per_page)

    total = query.count()
    pages = max(1, -(-total // per_page))  # Ceiling division
    items = query.offset((page - 1) * per_page).limit(per_page).all()

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
