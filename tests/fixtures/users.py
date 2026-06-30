"""
Factory pour créer des User de test.

Deux interfaces disponibles :

1. Fonction utilitaire ``make_user()``  — simple, sans Factory Boy.
2. Classe ``UserFactory``               — Factory Boy (SQLAlchemyModelFactory).

Exemple d'utilisation dans un test :

    from tests.fixtures.users import make_user, UserFactory

    def test_avec_fonction(db_session):
        user = make_user("rh")
        db_session.flush()
        assert user.role.name == "rh"

    def test_avec_factory(db_session):
        admin = UserFactory(role_name="admin")
        assert admin.email.endswith("@fixture.hr-test.com")
"""
from __future__ import annotations

import uuid as _uuid_module

import factory
from faker import Faker

from app.extensions import db
from app.models.user import User

_faker = Faker("fr_FR")


# =============================================================================
# Fonction utilitaire
# =============================================================================

def make_user(
    role_name: str = "employee",
    *,
    email: str | None = None,
    password: str = "Test1234!",
    is_active: bool = True,
    force_password_change: bool = False,
) -> User:
    """
    Crée et ajoute un User à la session courante (flush, pas commit).

    Args:
        role_name: "admin", "rh", "manager" ou "employee".
        email: adresse e-mail unique ; générée automatiquement si None.
        password: mot de passe en clair (haché via set_password).
        is_active: état du compte.
        force_password_change: force le changement de MDP à la prochaine connexion.

    Returns:
        Instance ``User`` avec un ``id`` populé par le flush.

    Raises:
        sqlalchemy.exc.NoResultFound: si le rôle ``role_name`` n'existe pas en DB.
    """
    from app.models.role import Role

    if email is None:
        email = f"test_{_uuid_module.uuid4().hex[:8]}@fixture.hr-test.com"

    role = db.session.execute(
        db.select(Role).where(Role.name == role_name)
    ).scalar_one()

    user = User(
        email=email,
        role_id=role.id,
        _is_active=is_active,
        is_email_verified=True,
        force_password_change=force_password_change,
        preferred_language="fr",
    )
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    return user


# =============================================================================
# Factory Boy
# =============================================================================

class UserFactory(factory.Factory):
    """
    Factory Factory Boy pour créer des User de test.

    Utilise ``factory.Factory`` (non SQLAlchemy) pour rester compatible avec
    le pattern SQLAlchemy 2.0 + Flask-SQLAlchemy 3.x (scoped_session dynamique).
    La création est déléguée à ``make_user()`` via ``_create()``.

    Usage :
        user = UserFactory()                        # rôle "employee" par défaut
        admin = UserFactory(role_name="admin")
        rh    = UserFactory(role_name="rh", email="rh_special@test.com")
    """

    class Meta:
        model = User
        # On court-circuite la création SQLAlchemy standard pour passer
        # par make_user() qui gère set_password() et le flush.
        exclude = ["role_name", "password"]

    email     = factory.LazyFunction(lambda: f"test_{_faker.unique.uuid4()[:8]}@fixture.hr-test.com")
    role_name = "employee"
    password  = "Test1234!"

    @classmethod
    def _create(cls, model_class, *args, **kwargs):  # type: ignore[override]
        role_name = kwargs.pop("role_name", "employee")
        password  = kwargs.pop("password", "Test1234!")
        email     = kwargs.pop("email", None)
        return make_user(role_name, email=email, password=password)

    @classmethod
    def _build(cls, model_class, *args, **kwargs):  # type: ignore[override]
        # Build sans DB — retourne un User non persisté (sans id).
        role_name = kwargs.pop("role_name", "employee")
        password  = kwargs.pop("password", "Test1234!")
        email     = kwargs.pop("email", f"test_{_uuid_module.uuid4().hex[:8]}@fixture.hr-test.com")

        user = User(
            email=email,
            _is_active=True,
            is_email_verified=True,
            force_password_change=False,
            preferred_language="fr",
        )
        user.set_password(password)
        return user
