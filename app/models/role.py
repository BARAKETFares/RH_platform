"""
Modèles : Role · Permission · RolePermission
RBAC — SQLAlchemy 2.0 (Mapped / mapped_column)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer,
    String, Text, UniqueConstraint, event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

if TYPE_CHECKING:
    from app.models.user import User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================================
# Table d'association role_permissions (many-to-many)
# =============================================================================

class RolePermission(db.Model):
    """
    Table d'association rôle ↔ permission.
    Modèle explicite (pas db.Table) pour pouvoir stocker granted_at.
    """
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )

    role_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    permission_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )

    # Relations
    role: Mapped[Role] = relationship("Role", back_populates="role_permissions")
    permission: Mapped[Permission] = relationship("Permission", back_populates="role_permissions")

    def __repr__(self) -> str:
        return f"<RolePermission role={self.role_id} perm={self.permission_id}>"


# =============================================================================
# Permission
# =============================================================================

class Permission(db.Model):
    """
    Permission atomique identifiée par un code de la forme "module.action".
    Exemples : "leave.approve", "payroll.read", "employees.write"
    """
    __tablename__ = "permissions"
    __table_args__ = (
        UniqueConstraint("code", name="uq_permission_code"),
    )

    # ── Colonnes ─────────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    role_permissions: Mapped[List[RolePermission]] = relationship(
        "RolePermission",
        back_populates="permission",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def roles(self) -> list[Role]:
        return [rp.role for rp in self.role_permissions]

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_by_code(cls, code: str) -> Optional[Permission]:
        return db.session.execute(
            db.select(cls).where(cls.code == code)
        ).scalar_one_or_none()

    @classmethod
    def get_by_module(cls, module: str) -> list[Permission]:
        return list(
            db.session.execute(
                db.select(cls).where(cls.module == module).order_by(cls.action)
            ).scalars()
        )

    # ── Dunder ────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return f"<Permission {self.code}>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Permission) and self.code == other.code

    def __hash__(self) -> int:
        return hash(self.code)

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "code":        self.code,
            "module":      self.module,
            "action":      self.action,
            "description": self.description,
        }


# =============================================================================
# Role
# =============================================================================

class Role(db.Model):
    """
    Rôle applicatif. Chaque utilisateur possède exactement un rôle.

    Hiérarchie (valeur numérique croissante = droits plus étendus) :
        employee(1) < manager(2) < rh(3) < admin(4)

    Les rôles système (is_system=True) ne peuvent être supprimés
    ni renommés via l'interface.
    """
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("name", name="uq_role_name"),
    )

    # ── Noms des rôles système ────────────────────────────────────────────────
    ADMIN    = "admin"
    RH       = "rh"
    MANAGER  = "manager"
    EMPLOYEE = "employee"

    HIERARCHY: dict[str, int] = {
        EMPLOYEE: 1,
        MANAGER:  2,
        RH:       3,
        ADMIN:    4,
    }

    # ── Colonnes ─────────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="TRUE = rôle non modifiable ni supprimable via l'interface"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    role_permissions: Mapped[List[RolePermission]] = relationship(
        "RolePermission",
        back_populates="role",
        cascade="all, delete-orphan",
        lazy="selectin",          # Chargé avec le rôle (évite N+1)
    )
    users: Mapped[List[User]] = relationship(
        "User",
        back_populates="role",
        lazy="dynamic",
    )

    # ── Propriétés ────────────────────────────────────────────────────────────
    @property
    def permissions(self) -> list[Permission]:
        """Liste des objets Permission de ce rôle."""
        return [rp.permission for rp in self.role_permissions]

    @property
    def permission_codes(self) -> set[str]:
        """Ensemble des codes de permission (optimisé pour les vérifications)."""
        return {rp.permission.code for rp in self.role_permissions}

    @property
    def hierarchy_level(self) -> int:
        """Niveau hiérarchique numérique. 0 si rôle inconnu."""
        return self.HIERARCHY.get(self.name, 0)

    # ── Méthodes d'instance ───────────────────────────────────────────────────
    def has_permission(self, code: str) -> bool:
        """Retourne True si ce rôle possède la permission identifiée par code."""
        return code in self.permission_codes

    def is_at_least(self, role_name: str) -> bool:
        """
        Retourne True si ce rôle est hiérarchiquement >= role_name.

            Role("rh").is_at_least("manager")  → True
            Role("employee").is_at_least("rh") → False
        """
        return self.hierarchy_level >= self.HIERARCHY.get(role_name, 0)

    def add_permission(self, permission: Permission) -> None:
        """Ajoute une permission au rôle (idempotent)."""
        if not self.has_permission(permission.code):
            self.role_permissions.append(
                RolePermission(role_id=self.id, permission_id=permission.id)
            )

    def remove_permission(self, code: str) -> None:
        """Retire une permission du rôle par son code."""
        self.role_permissions = [
            rp for rp in self.role_permissions
            if rp.permission.code != code
        ]

    # ── Méthodes de classe ────────────────────────────────────────────────────
    @classmethod
    def get_by_name(cls, name: str) -> Optional[Role]:
        return db.session.execute(
            db.select(cls).where(cls.name == name)
        ).scalar_one_or_none()

    @classmethod
    def get_or_404(cls, role_id: int) -> Role:
        role = db.session.get(cls, role_id)
        if role is None:
            from flask import abort
            abort(404, description="Rôle introuvable.")
        return role

    @classmethod
    def all_ordered(cls) -> list[Role]:
        """Retourne tous les rôles triés par niveau hiérarchique décroissant."""
        roles = db.session.execute(db.select(cls)).scalars().all()
        return sorted(roles, key=lambda r: r.hierarchy_level, reverse=True)

    # ── Dunder ────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return f"<Role {self.name} (level={self.hierarchy_level})>"

    def to_dict(self, include_permissions: bool = False) -> dict:
        data: dict = {
            "id":          self.id,
            "name":        self.name,
            "label":       self.label,
            "description": self.description,
            "is_system":   self.is_system,
            "level":       self.hierarchy_level,
        }
        if include_permissions:
            data["permissions"] = [p.to_dict() for p in self.permissions]
        return data


# =============================================================================
# Événement SQLAlchemy — Protège les rôles système contre la suppression
# =============================================================================

@event.listens_for(Role, "before_delete")
def prevent_system_role_deletion(mapper, connection, target: Role) -> None:
    if target.is_system:
        raise ValueError(
            f"Le rôle système '{target.name}' ne peut pas être supprimé."
        )