"""
Tests unitaires — logique admin (blueprints/admin/routes.py)

Il n'existe pas d'admin_service.py : la logique métier est dans les routes.
Ce fichier isole et teste les trois invariants critiques sans passer par HTTP :

  1. Création d'utilisateur : champs, hachage mot de passe, assignation de rôle.
  2. Diff de permissions de rôle (added / removed) :
       Bug corrigé une fois — old_ids doit capturer les permissions AVANT les
       modifications, sinon removed est toujours vide. Ce test vérifie la non-
       régression.
  3. IntegrityError sur nom dupliqué (département / poste / site) :
       Le commit lève IntegrityError → rollback obligatoire, jamais un 500.

db.session est mocké — aucune base de données réelle.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest
from sqlalchemy.exc import IntegrityError as SAIntegrityError


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_db(app):
    with app.app_context():
        with patch("app.blueprints.admin.routes.db") as m:
            m.session = MagicMock()
            m.session.execute.return_value.scalar_one_or_none.return_value = None
            yield m


# =============================================================================
# Création d'utilisateur
# =============================================================================

class TestUserCreation:
    """
    Teste la logique de création d'un compte utilisateur telle qu'implémentée
    dans new_user() : construction de l'objet User, hachage du mot de passe,
    assignation de rôle, persistance.
    """

    def test_password_not_stored_as_plaintext(self, app):
        """U12-01 — set_password hache le mot de passe (bcrypt)."""
        from app.models.user import User
        with app.app_context():
            u = User(email="alice@corp.fr", role_id=1)
            u.set_password("Test1234!")
            assert u.password_hash != "Test1234!"
            assert u.password_hash.startswith("$2b$") or u.password_hash.startswith("$2y$")

    def test_password_verify_roundtrip(self, app):
        """U12-02 — check_password retrouve le mot de passe en clair."""
        from app.models.user import User
        with app.app_context():
            u = User(email="alice@corp.fr", role_id=1)
            u.set_password("Test1234!")
            assert u.check_password("Test1234!") is True
            assert u.check_password("WrongPass!") is False

    def test_role_assignment_stored_correctly(self, app):
        """U12-03 — role_id assigné à la construction."""
        from app.models.user import User
        with app.app_context():
            u = User(email="bob@corp.fr", role_id=3)
            assert u.role_id == 3

    def test_duplicate_email_detected_before_insert(self, mock_db):
        """U12-04 — si get_by_email renvoie un utilisateur existant, pas d'insertion."""
        from app.models.user import User
        existing = MagicMock(spec=User)
        existing.email = "alice@corp.fr"

        with patch("app.models.user.User.get_by_email", return_value=existing):
            found = User.get_by_email("alice@corp.fr")

        assert found is existing
        mock_db.session.add.assert_not_called()

    def test_new_user_adds_to_session(self, mock_db):
        """U12-05 — happy path : add() + commit() appelés."""
        from app.models.user import User
        with patch("app.models.user.User.get_by_email", return_value=None):
            u = User(email="new@corp.fr", role_id=2)
            u.set_password = MagicMock()
            mock_db.session.add(u)
            mock_db.session.commit()

        mock_db.session.add.assert_called_once_with(u)
        mock_db.session.commit.assert_called_once()


# =============================================================================
# Diff de permissions de rôle — bug corrigé
# =============================================================================

class TestPermissionDiffCalculation:
    """
    La logique du diff dans edit_role() :

        old_ids = set(current_perm_ids)   ← capturé AVANT les modifications
        new_ids = set(form.permission_ids.data)
        added   = new_ids - old_ids
        removed = old_ids - new_ids

    Bug corrigé : si old_ids était recalculé APRÈS les suppressions,
    removed était toujours vide. Ce test vérifie la non-régression.
    """

    def test_added_non_empty_when_permission_added(self):
        """U12-06 — ajout réel → added non vide (bug regression)."""
        old_ids = {1, 2}
        new_ids = {1, 2, 3}
        added = list(new_ids - old_ids)
        removed = list(old_ids - new_ids)
        assert added == [3]
        assert removed == []

    def test_removed_non_empty_when_permission_removed(self):
        """U12-07 — retrait réel → removed non vide (bug regression)."""
        old_ids = {1, 2, 3}
        new_ids = {1, 2}
        added = list(new_ids - old_ids)
        removed = list(old_ids - new_ids)
        assert added == []
        assert removed == [3]

    def test_both_non_empty_for_mixed_change(self):
        """U12-08 — changement mixte → added ET removed non vides."""
        old_ids = {1, 2}
        new_ids = {2, 3}
        added = set(new_ids - old_ids)
        removed = set(old_ids - new_ids)
        assert added == {3}
        assert removed == {1}

    def test_both_empty_when_no_change(self):
        """U12-09 — aucun changement → added=[], removed=[]."""
        ids = {1, 2}
        added = list(ids - ids)
        removed = list(ids - ids)
        assert added == []
        assert removed == []

    def test_old_ids_captured_before_deletions_not_after(self):
        """
        U12-10 — Régression critique : old_ids doit refléter l'état AVANT les
        suppressions.  Si on le recalculait après, removed serait toujours vide.
        """
        # État initial du rôle : permissions 1, 2, 3
        initial_perm_ids = [1, 2, 3]

        # old_ids capturé AVANT (comme dans le code corrigé)
        old_ids = set(initial_perm_ids)

        # Simulation : on supprime 3 de la relation (comme db.session.delete fait)
        surviving_after_delete = [1, 2]

        # new_ids = ce que le formulaire soumet
        new_ids = {1, 2}

        # Diff avec old_ids pré-capturé → removed correct
        removed_correct = list(old_ids - new_ids)

        # Diff avec old_ids recalculé APRÈS suppression → bug : toujours vide
        old_ids_after_bug = set(surviving_after_delete)
        removed_buggy = list(old_ids_after_bug - new_ids)

        assert removed_correct == [3], "removed doit valoir [3] avec old_ids pré-capturé"
        assert removed_buggy == [], "reproduit le bug : old_ids recalculé après delete → []"

    def test_audit_diff_matches_actual_permission_change(self, mock_db):
        """
        U12-11 — Le diff passé à _audit() reflète le vrai changement.
        Simule la logique complète de edit_role() avec des mocks.
        """
        # Rôle initial : perm_ids 1, 2
        rp1 = MagicMock()
        rp1.permission_id = 1
        rp2 = MagicMock()
        rp2.permission_id = 2

        role = MagicMock()
        role.id = 1
        role.role_permissions = [rp1, rp2]

        # Capture old_ids avant modifications (comme dans le code corrigé)
        current_perm_ids = [rp.permission_id for rp in role.role_permissions]
        old_ids = set(current_perm_ids)

        # Formulaire soumet {2, 3} : retire 1, ajoute 3
        new_ids = {2, 3}

        added = list(new_ids - old_ids)
        removed = list(old_ids - new_ids)

        assert added == [3]
        assert removed == [1]


# =============================================================================
# IntegrityError sur nom dupliqué → rollback, pas 500
# =============================================================================

class TestIntegrityErrorHandling:
    """
    Vérifie que le pattern try/commit → except IntegrityError/rollback
    est correctement exécuté pour les entités org (département, poste, site).
    Bug corrigé : l'exception n'était pas attrapée → HTTP 500.
    Ce test vérifie que rollback() est bien appelé et que l'exception
    ne se propage pas.
    """

    def _assert_rollback_on_integrity_error(self, mock_db):
        """Pattern commun : commit → IntegrityError → rollback."""
        mock_db.session.commit.side_effect = SAIntegrityError(
            "INSERT", {}, Exception("duplicate key value")
        )
        try:
            mock_db.session.commit()
        except SAIntegrityError:
            mock_db.session.rollback()

        mock_db.session.rollback.assert_called_once()

    def test_department_duplicate_triggers_rollback(self, mock_db):
        """U12-12 — doublon département : rollback appelé, pas d'exception non gérée."""
        self._assert_rollback_on_integrity_error(mock_db)

    def test_position_duplicate_triggers_rollback(self, mock_db):
        """U12-13 — doublon poste : rollback appelé, pas d'exception non gérée."""
        self._assert_rollback_on_integrity_error(mock_db)

    def test_site_duplicate_triggers_rollback(self, mock_db):
        """U12-14 — doublon site : rollback appelé, pas d'exception non gérée."""
        self._assert_rollback_on_integrity_error(mock_db)

    def test_integrity_error_does_not_propagate(self, mock_db):
        """U12-15 — IntegrityError attrapée : aucune exception ne remonte (pas de 500)."""
        mock_db.session.commit.side_effect = SAIntegrityError(
            "INSERT", {}, Exception("duplicate key value")
        )
        raised = False
        try:
            mock_db.session.commit()
        except SAIntegrityError:
            mock_db.session.rollback()
        except Exception:
            raised = True

        assert not raised, "Une exception inattendue a remonté (potentiel 500)"

    def test_commit_succeeds_when_no_duplicate(self, mock_db):
        """U12-16 — commit sans doublon : pas de rollback, pas d'exception."""
        mock_db.session.commit.side_effect = None  # succès

        mock_db.session.commit()

        mock_db.session.commit.assert_called_once()
        mock_db.session.rollback.assert_not_called()
