# Rapport Pytest — HR Platform

**Branche :** `dev`  
**Résultat final (P7) : 202 passed, 0 failed, couverture 46 %**

---

# P1 — Infrastructure Pytest

**Date du run :** 2026-06-30  
**Résultat : 19 passed, 0 failed**

## Fichiers créés / modifiés

| Fichier | Action |
|---|---|
| `tests/conftest.py` | Modifié — fixtures globales, corrections domaines email, teardown DROP CASCADE, cache login |
| `tests/fixtures/users.py` | Modifié — domaines email corrigés (`@fixture.hr-test.com`) |
| `tests/fixtures/employees.py` | Modifié — EmployeeFactory sans `Meta.exclude` |
| `tests/test_infrastructure.py` | Créé — 19 tests de validation de l'infrastructure |

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

## Bugs applicatifs trouvés

### B1 — `app/models/audit.py` — index `created_at` dupliqué
- **Symptôme** : `db.create_all()` échoue avec `ProgrammingError` au lancement des fixtures.
- **Cause** : La colonne `created_at` déclarait à la fois `index=True` et un `Index("ix_audit_logs_created_at", "created_at")` explicite dans `__table_args__` — PostgreSQL tente de créer deux index identiques.
- **Fix** : Suppression de la ligne `Index("ix_audit_logs_created_at", "created_at"),` dans `__table_args__`.

### B2 — `app/models/notification.py` — même problème index `created_at`
- **Symptôme** : même `ProgrammingError` au `create_all()`.
- **Cause** : `Index("ix_notifications_created_at", "created_at")` en doublon avec `index=True` sur la colonne.
- **Fix** : Même approche que B1.

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

## Résultat du run

```
platform win32 -- Python 3.12.12, pytest-8.1.0
19 passed in 612.98s (0:10:12)
```

**Commit :** `4ac5ede` — `test: infrastructure pytest (P1) validée — 19/19 passed`

---

# P2 — Unit Tests : leave_service

**Fichier :** `tests/unit/services/test_leave_service.py`  
**Résultat : 15 passed, 0 failed**

## Liste des 15 tests

```
tests/unit/services/test_leave_service.py::TestCreateLeaveRequest::test_employee_not_found
tests/unit/services/test_leave_service.py::TestCreateLeaveRequest::test_leave_type_not_found
tests/unit/services/test_leave_service.py::TestCreateLeaveRequest::test_overlap_raises_conflict
tests/unit/services/test_leave_service.py::TestCreateLeaveRequest::test_insufficient_balance_raises_business_rule
tests/unit/services/test_leave_service.py::TestCreateLeaveRequest::test_success_creates_and_reserves
tests/unit/services/test_leave_service.py::TestCalculateBalance::test_invalid_year_raises
tests/unit/services/test_leave_service.py::TestCalculateBalance::test_employee_not_found_raises
tests/unit/services/test_leave_service.py::TestCalculateBalance::test_returns_balance
tests/unit/services/test_leave_service.py::TestApproveLeave::test_manager_approval
tests/unit/services/test_leave_service.py::TestApproveLeave::test_invalid_role_raises
tests/unit/services/test_leave_service.py::TestApproveLeave::test_not_found_raises
tests/unit/services/test_leave_service.py::TestRejectLeave::test_manager_reject_releases_balance
tests/unit/services/test_leave_service.py::TestRejectLeave::test_empty_comment_raises
tests/unit/services/test_leave_service.py::TestRejectLeave::test_invalid_role_raises
tests/unit/services/test_leave_service.py::TestRejectLeave::test_not_found_raises
```

## Bugs applicatifs trouvés

Aucun bug applicatif identifié dans cette phase.

---

# P3 — Unit Tests : employee_service

**Fichier :** `tests/unit/services/test_employee_service.py`  
**Résultat : 28 passed, 0 failed**

## Liste des 28 tests

```
tests/unit/services/test_employee_service.py::TestSensitiveFieldEncryption::test_national_id_not_stored_as_plaintext
tests/unit/services/test_employee_service.py::TestSensitiveFieldEncryption::test_national_id_roundtrip
tests/unit/services/test_employee_service.py::TestSensitiveFieldEncryption::test_iban_not_stored_as_plaintext
tests/unit/services/test_employee_service.py::TestSensitiveFieldEncryption::test_iban_roundtrip
tests/unit/services/test_employee_service.py::TestSensitiveFieldEncryption::test_bic_roundtrip
tests/unit/services/test_employee_service.py::TestSensitiveFieldEncryption::test_none_value_stays_none
tests/unit/services/test_employee_service.py::TestSensitiveFieldEncryption::test_fernet_token_is_not_readable_without_key
tests/unit/services/test_employee_service.py::TestCreateEmployee::test_sensitive_fields_encrypted_at_service_level
tests/unit/services/test_employee_service.py::TestCreateEmployee::test_missing_required_fields_raises
tests/unit/services/test_employee_service.py::TestCreateEmployee::test_blank_first_name_raises
tests/unit/services/test_employee_service.py::TestCreateEmployee::test_duplicate_employee_number_raises
tests/unit/services/test_employee_service.py::TestCreateEmployee::test_manager_not_found_raises
tests/unit/services/test_employee_service.py::TestCreateEmployee::test_success_adds_and_commits
tests/unit/services/test_employee_service.py::TestUpdateEmployee::test_sensitive_field_update_encrypted
tests/unit/services/test_employee_service.py::TestUpdateEmployee::test_self_manager_raises
tests/unit/services/test_employee_service.py::TestUpdateEmployee::test_termination_before_hire_raises
tests/unit/services/test_employee_service.py::TestUpdateEmployee::test_probation_before_hire_raises
tests/unit/services/test_employee_service.py::TestUpdateEmployee::test_success_commits
tests/unit/services/test_employee_service.py::TestSoftDelete::test_soft_delete_calls_terminate
tests/unit/services/test_employee_service.py::TestSoftDelete::test_already_terminated_raises
tests/unit/services/test_employee_service.py::TestSoftDelete::test_not_found_raises
tests/unit/services/test_employee_service.py::TestSoftDelete::test_hard_delete_with_subordinates_raises
tests/unit/services/test_employee_service.py::TestSoftDelete::test_hard_delete_clean_removes
tests/unit/services/test_employee_service.py::TestListEmployees::test_invalid_status_raises
tests/unit/services/test_employee_service.py::TestListEmployees::test_valid_status_builds_query
tests/unit/services/test_employee_service.py::TestListEmployees::test_department_filter_narrows_query
tests/unit/services/test_employee_service.py::TestListEmployees::test_search_filter_narrows_query
tests/unit/services/test_employee_service.py::TestListEmployees::test_manager_filter_narrows_query
```

## Bugs applicatifs trouvés

Aucun bug applicatif identifié dans cette phase.

---

# P4 — Unit Tests : evaluation_service

**Fichier :** `tests/unit/services/test_evaluation_service.py`  
**Résultat : 19 passed, 0 failed**

## Liste des 19 tests

```
tests/unit/services/test_evaluation_service.py::TestCreateCampaign::test_end_before_start_raises
tests/unit/services/test_evaluation_service.py::TestCreateCampaign::test_success_adds_and_commits
tests/unit/services/test_evaluation_service.py::TestCreateEvaluation::test_self_evaluator_raises
tests/unit/services/test_evaluation_service.py::TestCreateEvaluation::test_employee_not_found_raises
tests/unit/services/test_evaluation_service.py::TestCreateEvaluation::test_duplicate_raises
tests/unit/services/test_evaluation_service.py::TestCreateEvaluation::test_success_creates_at_draft
tests/unit/services/test_evaluation_service.py::TestSendToInProgress::test_draft_becomes_in_progress
tests/unit/services/test_evaluation_service.py::TestSendToInProgress::test_bad_transition_raises_business_rule
tests/unit/services/test_evaluation_service.py::TestSubmitToEmployeeReview::test_submit_sets_content_and_transitions
tests/unit/services/test_evaluation_service.py::TestSubmitToEmployeeReview::test_bad_transition_raises_business_rule
tests/unit/services/test_evaluation_service.py::TestAcknowledgeByEmployee::test_acknowledge_sets_comment
tests/unit/services/test_evaluation_service.py::TestAcknowledgeByEmployee::test_wrong_status_raises
tests/unit/services/test_evaluation_service.py::TestAcknowledgeByEmployee::test_double_acknowledge_guard_against_re_signature
tests/unit/services/test_evaluation_service.py::TestFinalizeEvaluation::test_employee_review_becomes_completed
tests/unit/services/test_evaluation_service.py::TestFinalizeEvaluation::test_bad_transition_raises_business_rule
tests/unit/services/test_evaluation_service.py::TestFinalizeEvaluation::test_manager_cannot_finalize_evaluation_of_wrong_evaluator
tests/unit/services/test_evaluation_service.py::TestArchiveEvaluation::test_completed_becomes_archived
tests/unit/services/test_evaluation_service.py::TestArchiveEvaluation::test_wrong_status_raises_business_rule
tests/unit/services/test_evaluation_service.py::TestPermissions::test_employee_cannot_acknowledge_twice
```

## Bugs applicatifs trouvés

Aucun bug applicatif identifié dans cette phase.

---

# P5 — Unit Tests : admin_service

**Fichier :** `tests/unit/services/test_admin_service.py`  
**Résultat : 16 passed, 0 failed**

## Liste des 16 tests

```
tests/unit/services/test_admin_service.py::TestUserCreation::test_password_not_stored_as_plaintext
tests/unit/services/test_admin_service.py::TestUserCreation::test_password_verify_roundtrip
tests/unit/services/test_admin_service.py::TestUserCreation::test_role_assignment_stored_correctly
tests/unit/services/test_admin_service.py::TestUserCreation::test_duplicate_email_detected_before_insert
tests/unit/services/test_admin_service.py::TestUserCreation::test_new_user_adds_to_session
tests/unit/services/test_admin_service.py::TestPermissionDiffCalculation::test_added_non_empty_when_permission_added
tests/unit/services/test_admin_service.py::TestPermissionDiffCalculation::test_removed_non_empty_when_permission_removed
tests/unit/services/test_admin_service.py::TestPermissionDiffCalculation::test_both_non_empty_for_mixed_change
tests/unit/services/test_admin_service.py::TestPermissionDiffCalculation::test_both_empty_when_no_change
tests/unit/services/test_admin_service.py::TestPermissionDiffCalculation::test_old_ids_captured_before_deletions_not_after
tests/unit/services/test_admin_service.py::TestPermissionDiffCalculation::test_audit_diff_matches_actual_permission_change
tests/unit/services/test_admin_service.py::TestIntegrityErrorHandling::test_department_duplicate_triggers_rollback
tests/unit/services/test_admin_service.py::TestIntegrityErrorHandling::test_position_duplicate_triggers_rollback
tests/unit/services/test_admin_service.py::TestIntegrityErrorHandling::test_site_duplicate_triggers_rollback
tests/unit/services/test_admin_service.py::TestIntegrityErrorHandling::test_integrity_error_does_not_propagate
tests/unit/services/test_admin_service.py::TestIntegrityErrorHandling::test_commit_succeeds_when_no_duplicate
```

## Bugs applicatifs trouvés

Aucun bug applicatif identifié dans cette phase.

---

# P6 — Tests d'intégration : auth + leaves

**Fichiers :**
- `tests/integration/test_auth.py` — 18 tests
- `tests/integration/test_leaves.py` — 12 tests

**Résultat : 30 passed, 0 failed**

## Corrections infrastructure (conftest.py)

Deux bugs d'infrastructure ont été découverts lors de l'écriture des tests d'intégration multi-clients.

### I1 — `AssertionError: Popped wrong request context` (Flask 3.x)
- **Cause** : `with app.test_client() as c:` active `preserve_context=True` dans Flask 3.x. Quand deux clients authentifiés (`employee_client` + `rh_client`) sont actifs simultanément dans le même test, chaque login redirige vers `/reporting/dashboard`, empilant deux `RequestContext` différents sur le même stack global `contextvars`. Quand `employee_client.post(...)` appelle `_context_stack.close()`, il trouve le contexte de `rh_client` au sommet → `AssertionError`.
- **Fix** : Toutes les fixtures de clients changées de `with app.test_client() as c:` vers `c = app.test_client()` (sans `preserve_context`).

### I2 — `idle in transaction` bloque `DROP SCHEMA CASCADE`
- **Cause** : Des runs pytest interrompus laissent des connexions SQLAlchemy dans l'état `idle in transaction` dans le pool. Ces connexions détiennent des verrous et bloquent `DROP SCHEMA CASCADE` au teardown.
- **Fix** : Ajout de `_reset_public_schema()` dans `conftest.py` : `_db.session.remove()` + `_db.engine.dispose()` libèrent le pool avant tout `DROP SCHEMA`, avec `pg_terminate_backend` (filtré sur `state = 'idle in transaction'`) comme filet de sécurité.

## Liste des 18 tests (test_auth.py)

```
tests/integration/test_auth.py::TestLogin::test_get_login_page_returns_200
tests/integration/test_auth.py::TestLogin::test_valid_credentials_redirect
tests/integration/test_auth.py::TestLogin::test_admin_valid_credentials_redirect
tests/integration/test_auth.py::TestLogin::test_wrong_password_returns_401
tests/integration/test_auth.py::TestLogin::test_unknown_email_returns_401
tests/integration/test_auth.py::TestLogin::test_blank_email_returns_422
tests/integration/test_auth.py::TestLogin::test_blank_password_returns_422
tests/integration/test_auth.py::TestUnauthenticatedAccess::test_protected_leaves_list_redirects_to_login
tests/integration/test_auth.py::TestUnauthenticatedAccess::test_protected_admin_redirects_to_login
tests/integration/test_auth.py::TestUnauthenticatedAccess::test_protected_approvals_redirects_to_login
tests/integration/test_auth.py::TestRoleBasedAccess::test_employee_cannot_access_approvals_403
tests/integration/test_auth.py::TestRoleBasedAccess::test_employee_cannot_access_admin_users_403
tests/integration/test_auth.py::TestRoleBasedAccess::test_manager_can_access_approvals_200
tests/integration/test_auth.py::TestRoleBasedAccess::test_rh_can_access_approvals_200
tests/integration/test_auth.py::TestRoleBasedAccess::test_admin_can_access_admin_users_200
tests/integration/test_auth.py::TestLogout::test_logout_redirects_to_login
tests/integration/test_auth.py::TestLogout::test_after_logout_protected_route_redirects
tests/integration/test_auth.py::TestLogout::test_unauthenticated_logout_redirects
```

## Liste des 12 tests (test_leaves.py)

```
tests/integration/test_leaves.py::TestAccessControl::test_get_my_requests_requires_auth
tests/integration/test_leaves.py::TestAccessControl::test_get_new_requires_auth
tests/integration/test_leaves.py::TestAccessControl::test_employee_forbidden_on_approvals
tests/integration/test_leaves.py::TestAccessControl::test_manager_allowed_on_approvals
tests/integration/test_leaves.py::TestAccessControl::test_employee_without_profile_forbidden_on_new_request_post
tests/integration/test_leaves.py::TestLeaveCreation::test_get_new_request_form_returns_200
tests/integration/test_leaves.py::TestLeaveCreation::test_post_new_request_valid_data_redirects
tests/integration/test_leaves.py::TestLeaveCreation::test_post_new_request_missing_dates_stays_on_form
tests/integration/test_leaves.py::TestLeaveList::test_get_my_requests_returns_200_with_employee_profile
tests/integration/test_leaves.py::TestLeaveApproval::test_full_create_and_approve_flow
tests/integration/test_leaves.py::TestLeaveApproval::test_rh_can_reject_leave
tests/integration/test_leaves.py::TestLeaveApproval::test_decide_on_nonexistent_leave_returns_404
```

## Bugs applicatifs trouvés

Aucun bug applicatif dans le code de production (les deux corrections ci-dessus sont des bugs d'infrastructure de test).

---

# P7 — Couverture de code

**Commande :** `pytest --cov=app tests/`  
**Résultat : 202 passed, 0 failed**  
**Couverture globale : 46 %**

## Configuration ajoutée (`pyproject.toml`)

```toml
[tool.coverage.run]
source = ["app"]
branch = true
omit = [
    "*/migrations/*",
    "*/scripts/*",
    "*/tests/*",
]
```

## Couverture par module

```
Name                                     Stmts   Miss Branch BrPart  Cover
--------------------------------------------------------------------------
app\__init__.py                            133     20      8      2    83%
app\api\v1\auth.py                         100     72     18      0    24%
app\api\v1\employees.py                    125     89     18      0    25%
app\api\v1\evaluations.py                  318    233     56      0    23%
app\api\v1\leaves.py                       215    161     70      0    19%
app\blueprints\admin\forms.py              136     44     12      0    62%
app\blueprints\admin\routes.py             483    371     96      2    20%
app\blueprints\auth\forms.py                42      6      8      1    74%
app\blueprints\auth\routes.py              218    122     54      7    39%
app\blueprints\employees\forms.py           73     28     10      0    54%
app\blueprints\employees\routes.py         150    109     20      0    24%
app\blueprints\leaves\forms.py              37      3      6      3    86%
app\blueprints\leaves\routes.py            169     74     44      7    53%
app\blueprints\payroll\forms.py             42      8      0      0    81%
app\blueprints\payroll\routes.py           137     97     20      0    25%
app\blueprints\performance\forms.py         78     25     10      0    60%
app\blueprints\performance\routes.py       260    204     52      0    18%
app\blueprints\recruitment\forms.py         81     23      8      0    65%
app\blueprints\recruitment\routes.py       271    202     44      0    22%
app\blueprints\reporting\routes.py          56      4     14      3    90%
app\blueprints\training\forms.py            51     18      8      0    56%
app\blueprints\training\routes.py          210    160     52      0    19%
app\extensions.py                           26      0      0      0   100%
app\models\audit.py                         99     32     12      0    60%
app\models\calendar.py                     128     51     12      0    55%
app\models\contract.py                     166     68     22      0    52%
app\models\department.py                   124     56     22      1    47%
app\models\employee.py                     191     58     20      3    64%
app\models\evaluation.py                   251     99     44      2    52%
app\models\leave_balance.py                 94     39     12      0    52%
app\models\leave_request.py               166     57     26      7    60%
app\models\leave_type.py                    99     25     16      4    68%
app\models\notification.py                 142     58     18      0    52%
app\models\objective.py                    146     67     34      0    44%
app\models\organization.py                109     35     14      1    61%
app\models\payroll.py                      125     39     14      0    62%
app\models\position.py                     104     39     20      1    53%
app\models\recruitment.py                  283     98     44      0    57%
app\models\role.py                         104     27      8      0    69%
app\models\training.py                     122     49     26      0    49%
app\models\user.py                         240     78     32      7    62%
app\schemas\employee_schema.py             173     30     16      0    76%
app\schemas\evaluation_schema.py           234     44     24      0    74%
app\schemas\leave_schema.py                196     34     26      0    73%
app\services\auth_service.py               179    106     52      5    35%
app\services\employee_service.py           144     26     76      7    78%
app\services\evaluation_service.py         203     56     62      5    69%
app\services\leave_service.py             156     11     74     11    90%
app\services\payroll_service.py            133    109     56      0    13%
app\services\recruitment_service.py        235    201    102      0    10%
app\services\training_service.py           114     94     48      0    12%
app\utils\crypto.py                         32     10      6      1    71%
app\utils\decorators.py                    103     50     28      8    48%
app\utils\error_handlers.py                 20      6     18      6    63%
app\utils\exceptions.py                     33      0      0      0   100%
app\utils\pagination.py                     37      3      2      1    90%
app\utils\security_headers.py                6      0      2      0   100%
app\utils\template_filters.py               36     11      8      2    61%
--------------------------------------------------------------------------
TOTAL                                     8390   4019   1684     99    46%
```

## Modules les mieux couverts (>= 70 %)

| Module | Couverture |
|---|---|
| `app\utils\exceptions.py` | 100 % |
| `app\extensions.py` | 100 % |
| `app\utils\security_headers.py` | 100 % |
| `app\blueprints\reporting\routes.py` | 90 % |
| `app\utils\pagination.py` | 90 % |
| `app\services\leave_service.py` | 90 % |
| `app\blueprints\leaves\forms.py` | 86 % |
| `app\__init__.py` | 83 % |
| `app\blueprints\payroll\forms.py` | 81 % |
| `app\services\employee_service.py` | 78 % |
| `app\schemas\employee_schema.py` | 76 % |
| `app\blueprints\auth\forms.py` | 74 % |
| `app\schemas\evaluation_schema.py` | 74 % |
| `app\schemas\leave_schema.py` | 73 % |
| `app\utils\crypto.py` | 71 % |
| `app\models\role.py` | 69 % |
| `app\services\evaluation_service.py` | 69 % |
| `app\models\leave_type.py` | 68 % |

## Modules non couverts (0 %)

| Module | Raison |
|---|---|
| `app\models\document.py` | Stub vide |
| `app\models\leave.py` | Stub vide |
| `app\models\skill.py` | Stub vide |
| `app\services\absence_service.py` | Stub vide |
| `app\services\notification_service.py` | Stub vide |
| `app\services\report_service.py` | Stub vide |
| `app\tasks\leave_tasks.py` | Tâches Celery non testées |
| `app\utils\date_utils.py` | Utilitaires non utilisés dans les tests |
| `app\utils\file_utils.py` | Utilitaires non utilisés dans les tests |
| `app\utils\validators.py` | Validateurs non utilisés dans les tests |

---

# Résumé global

## Décompte des tests par phase

| Phase | Fichier(s) | Tests |
|---|---|---|
| P1 — Infrastructure | `tests/test_infrastructure.py` | 19 |
| P2 — leave_service | `tests/unit/services/test_leave_service.py` | 15 |
| P3 — employee_service | `tests/unit/services/test_employee_service.py` | 28 |
| P4 — evaluation_service | `tests/unit/services/test_evaluation_service.py` | 19 |
| P5 — admin_service | `tests/unit/services/test_admin_service.py` | 16 |
| P6 — Intégration auth | `tests/integration/test_auth.py` | 18 |
| P6 — Intégration leaves | `tests/integration/test_leaves.py` | 12 |
| Héritage — leave_service (v1) | `tests/unit/test_leave_service.py` | 28 |
| Héritage — employee_service (v1) | `tests/unit/test_employee_service.py` | 19 |
| Héritage — evaluation_service (v1) | `tests/unit/test_evaluation_service.py` | 28 |
| **Total** | | **202** |

> Les fichiers `tests/unit/test_*.py` (héritage) sont des tests antérieurs au projet de couverture systématique. Ils coexistent avec les suites P2–P5 et couvrent des cas complémentaires.

## Couverture de code

- **Globale : 46 %** (8 390 instructions, 4 019 manquées, 1 684 branches)
- Points forts : `leave_service` (90 %), `employee_service` (78 %), `evaluation_service` (69 %)
- Points faibles : API REST v1 (19–25 %), routes admin/performance/training (18–20 %), services non testés (`payroll`, `recruitment`, `training` : 10–13 %)

## Bugs applicatifs trouvés par les tests

| # | Fichier | Description | Phase détection |
|---|---|---|---|
| B1 | `app/models/audit.py` | Index `ix_audit_logs_created_at` dupliqué (`index=True` + `Index(...)` explicite) — `ProgrammingError` au `create_all()` | P1 |
| B2 | `app/models/notification.py` | Index `ix_notifications_created_at` dupliqué (même cause) — `ProgrammingError` au `create_all()` | P1 |

> Les corrections d'infrastructure (`conftest.py` : preserve_context, engine.dispose, g._login_user) sont des bugs de la configuration de test, pas du code applicatif.
