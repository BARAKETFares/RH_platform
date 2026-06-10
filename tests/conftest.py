"""
Configuration pytest — Fixtures globales.

Les fixtures définies ici sont disponibles dans tous les tests
sans import explicite.
"""
from __future__ import annotations

import pytest

from app import create_app
from app.extensions import db as _db


@pytest.fixture(scope="session")
def app():
    """Instance Flask configurée pour les tests (scope session = une seule fois)."""
    application = create_app("testing")
    application.config["TESTING"] = True
    return application


@pytest.fixture(scope="session")
def db(app):
    """
    Base de données de test.
    Crée toutes les tables au début de la session, les supprime à la fin.
    """
    with app.app_context():
        _db.create_all()
        yield _db
        _db.drop_all()


@pytest.fixture(scope="function")
def db_session(db):
    """
    Session DB isolée par test.
    Chaque test s'exécute dans une transaction annulée à la fin (rollback).
    """
    connection = db.engine.connect()
    transaction = connection.begin()
    db.session.bind = connection

    yield db.session

    db.session.remove()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="function")
def client(app):
    """Client de test Flask."""
    return app.test_client()


@pytest.fixture(scope="function")
def runner(app):
    """Runner CLI Flask pour tester les commandes Click."""
    return app.test_cli_runner()
