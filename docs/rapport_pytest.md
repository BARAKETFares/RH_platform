# Rapport P1 — Infrastructure Pytest

**Date du run :** 2026-06-30  
**Branche :** `dev`  
**Résultat final : 19 passed, 0 failed, 0 error**

---

## Fichiers créés / modifiés

| Fichier | Action |
|---|---|
| `tests/conftest.py` | Modifié — fixtures globales, corrections domaines email, teardown DROP CASCADE, cache login |
| `tests/fixtures/users.py` | Modifié — domaines email corrigés (`@fixture.hr-test.com`) |
| `tests/fixtures/employees.py` | Modifié — EmployeeFactory sans `Meta.exclude` |
| `tests/test_infrastructure.py` | Créé — 19 tests de validation de l'infrastructure |

---

## Corrections appliquées

### 1. Domaines email de test invalides (HTTP 422 sur POST /auth/login)
- **Cause** : WTForms rejette les TLD non standards (`.test` invalide).
- **Fix** : `@fixtures.test` → `@fixtures.hr-test.com` dans `conftest.py` et `fixtures/users.py`.

### 2. `EmployeeFactory._create()` — KeyError: 'org'
- **Cause** : `Meta.exclude = ["org"]` retirait `org` des kwargs *avant* que `_create()` soit appelé par Factory Boy.
- **Fix** : Suppression de `exclude = ["org"]` dans `EmployeeFactory.Meta` ; `kwargs.pop("org")` → `kwargs.pop("org", {})`.

### 3. `drop_all()` — CircularDependencyError en teardown
- **Cause** : `Employee.manager_id` (auto-référence) et `Department.manager_id → Employee` créent des dépendances FK circulaires que SQLAlchemy ne peut pas résoudre pour `drop_all()`.
- **Fix** : Remplacement par `DROP SCHEMA public CASCADE; CREATE SCHEMA public` dans le teardown du fixture `db`.

### 4. `test_unauthenticated_redirects_to_login` — HTTP 200 au lieu de 302 (ordre-dépendant)
- **Cause (root cause Flask 3.x)** : En Flask 3.x, `g` est stocké dans l'`AppContext`, non dans le `RequestContext`. Le fixture `db` (scope=session) maintient un `with app.app_context():` ouvert pour tout le run. Toutes les requêtes HTTP réutilisent ce même `AppContext` et partagent donc le même `g`. Flask-Login met en cache `current_user` dans `g._login_user`. Après une requête authentifiée (`admin_client`, etc.), `g._login_user = <admin_user>` persiste dans le `g` partagé. La requête suivante du client non authentifié trouve `"_login_user" in g` → True → retourne l'utilisateur admin sans lire le cookie → `@login_required` ne redirige pas → HTTP 200.
- **Fix** : Fixture session-scoped `_reset_login_user_cache` (autouse) qui enregistre un hook `before_request` appelant `g.pop("_login_user", None)` avant chaque requête, forçant Flask-Login à recharger depuis la session (cookie) à chaque requête.

### 5. Fixture `client` — suppress preserve_context
- **Fix** : `return app.test_client()` sans `with` pour éviter l'accumulation de contextes de requête préservés qui appellaient `db.session.remove()` sur le scope partagé.

---

## Liste des 19 tests

```
tests/test_infrastructure.py::TestAppConfig::test_app_exists
tests/test_infrastructure.py::TestAppConfig::test_testing_mode
tests/test_infrastructure.py::TestAppConfig::test_csrf_disabled
tests/test_infrastructure.py::TestAppConfig::test_uses_test_database
tests/test_infrastructure.py::TestDatabase::test_tables_created
tests/test_infrastructure.py::TestDatabase::test_roles_seeded
tests/test_infrastructure.py::TestDbSession::test_flush_without_commit
tests/test_infrastructure.py::TestDbSession::test_rollback_does_not_leak
tests/test_infrastructure.py::TestSeedFixtures::test_seed_org_returns_ids
tests/test_infrastructure.py::TestSeedFixtures::test_seed_users_returns_all_roles
tests/test_infrastructure.py::TestAuthenticatedClients::test_admin_client_reaches_dashboard
tests/test_infrastructure.py::TestAuthenticatedClients::test_rh_client_reaches_dashboard
tests/test_infrastructure.py::TestAuthenticatedClients::test_manager_client_reaches_dashboard
tests/test_infrastructure.py::TestAuthenticatedClients::test_employee_client_reaches_dashboard
tests/test_infrastructure.py::TestAuthenticatedClients::test_unauthenticated_redirects_to_login
tests/test_infrastructure.py::TestFactories::test_make_user
tests/test_infrastructure.py::TestFactories::test_make_employee
tests/test_infrastructure.py::TestFactories::test_user_factory
tests/test_infrastructure.py::TestFactories::test_employee_factory
```

---

## Résultat du run final

```
platform win32 -- Python 3.12.12, pytest-8.1.0
19 passed in 612.98s (0:10:12)
```
