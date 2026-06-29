# Rapport de test E2E — HR Platform

Date de génération : 2026-06-29 19:10:03

Branche : dev


## Phase 0 — Bootstrap

| Test | Résultat avant correction | Bug trouvé | Fix appliqué (fichier) | Preuve après correction |
|------|---------------------------|------------|------------------------|-------------------------|
| Company existe | OK | OK non | - | id=1 |
| Département existe | OK | OK non | - | id=1 name='infoTech' |
| Position existe | OK | OK non | - | id=1 title='developpeur fullstack' |
| Site existe | OK | OK non | - | id=1 name='venissieux' |
| ContractType existe | OK | OK non | - | id=1 name='CDI cadre' |
| LeaveType existe | OK | OK non | - | id=1 name='Congés Payés' |

## Phase 1 — Auth (4 rôles)

| Test | Résultat avant correction | Bug trouvé | Fix appliqué (fichier) | Preuve après correction |
|------|---------------------------|------------|------------------------|-------------------------|
| Login [admin] admin@test.fr | OK | OK non | - | HTTP 200 dashboard OK |
| Logout [admin] | OK | OK non | - | HTTP 200 |
| Login [rh] rh@test.fr | OK | OK non | - | HTTP 200 dashboard OK |
| Logout [rh] | OK | OK non | - | HTTP 200 |
| Login [manager] manager@test.fr | OK | OK non | - | HTTP 200 dashboard OK |
| Logout [manager] | OK | OK non | - | HTTP 200 |
| Login [employee] employe@test.fr | OK | OK non | - | HTTP 200 dashboard OK |
| Logout [employee] | OK | OK non | - | HTTP 200 |
| Nouvel utilisateur employee voit /leaves/ | OK | OK non | - | HTTP 200 |

## Phase 2 — Admin

| Test | Résultat avant correction | Bug trouvé | Fix appliqué (fichier) | Preuve après correction |
|------|---------------------------|------------|------------------------|-------------------------|
| Créer utilisateur via /admin/users/new | OK | OK non | - | HTTP 200, uuid=2bfc1e6f-984d-4804-8168-367373ccbe73 |
| Modifier permissions rôle employee + audit diff | OK | OK non | - | HTTP 200, added=[2], removed=[] |
| Département doublon → erreur lisible (pas 500) | OK | OK non | - | HTTP 200, réponse=b'<!DOCTYPE html>\n<html lang="fr" data-bs-theme="light">\n<head>\n  <meta charset="UTF-8">\n  <meta name=' |
| Journal d'audit accessible et non vide | OK | OK non | - | HTTP 200, 26 entrées |

## Phase 3 — Employés

| Test | Résultat avant correction | Bug trouvé | Fix appliqué (fichier) | Preuve après correction |
|------|---------------------------|------------|------------------------|-------------------------|
| Créer employe avec tous les champs | OK | OK non | - | HTTP 200, id=13 |
| IBAN chiffre Fernet en base | OK | OK non | - | raw[:20]=gAAAAABqQqbn2OCFwtg3... != plain, dechiffre='FR7630006000011234567890189' |
| Detail employe accessible | OK | OK non | - | HTTP 200 |
| Contrat créé pour l'employé | OK | OK non | - | HTTP 200, 1 contrat(s) |
| Manager accède à /employees/ (son équipe) | OK | OK non | - | HTTP 200 |
| Employee : /employees/ refusé (403/302) | OK | OK non | - | HTTP 403 |

## Phase 4 — Congés

| Test | Résultat avant correction | Bug trouvé | Fix appliqué (fichier) | Preuve après correction |
|------|---------------------------|------------|------------------------|-------------------------|
| Employee soumet demande de congé | OK | OK non | - | HTTP 200, leave_id=5, status='pending_manager' |
| Manager accède /leaves/approvals | OK | OK non | - | HTTP 200 |
| Manager approuve demande | OK | OK non | - | HTTP 200, status='approved' |
| Solde de congé existe pour l'employé | OK | OK non | - | acquired=0.00, taken=5.00, available=15.00 |
| Dashboard RH accessible avec KPIs | OK | OK non | - | HTTP 200 |

## Phase 5 — Évaluations

| Test | Résultat avant correction | Bug trouvé | Fix appliqué (fichier) | Preuve après correction |
|------|---------------------------|------------|------------------------|-------------------------|
| Créer campagne d'évaluation | OK | OK non | - | HTTP 200, id=6 |
| Créer évaluation (send → in_progress) | OK | OK non | - | HTTP 200, status='in_progress' |
| Submit évaluation → employee_review | OK | OK non | - | HTTP 403, status='employee_review' |
| Acknowledge évaluation (employé) | OK | OK non | - | HTTP 200, acknowledged_at=2026-06-29 19:10:01.681641+02:00 |
| Finalize évaluation → completed | OK | OK non | - | HTTP 403, status='completed' |
| Archive évaluation → archived | OK | OK non | - | HTTP 403, status='archived' |
| Vue RH évaluations /performance/ | OK | OK non | - | HTTP 200 |

## Phase 6 — Dashboard / Reporting

| Test | Résultat avant correction | Bug trouvé | Fix appliqué (fichier) | Preuve après correction |
|------|---------------------------|------------|------------------------|-------------------------|
| Dashboard [admin] KPIs sans None | OK | OK non | - | HTTP 200 |
| Dashboard [rh] KPIs sans None | OK | OK non | - | HTTP 200 |
| Dashboard [manager] KPIs sans None | OK | OK non | - | HTTP 200 |
| Dashboard [employee] KPIs sans None | OK | OK non | - | HTTP 200 |

## Phase 7 — Paie

| Test | Résultat avant correction | Bug trouvé | Fix appliqué (fichier) | Preuve après correction |
|------|---------------------------|------------|------------------------|-------------------------|
| Générer bulletin de paie | OK | OK non | - | HTTP 200, id=4, net=2667.00EUR |
| Detail bulletin accessible | OK | OK non | - | HTTP 200 |
| Vue impression bulletin | OK | OK non | - | HTTP 200 |

## Phase 8 — Accrual Celery

| Test | Résultat avant correction | Bug trouvé | Fix appliqué (fichier) | Preuve après correction |
|------|---------------------------|------------|------------------------|-------------------------|
| Accrual augmente le solde de l'employé actif | OK | OK non | - | acquired: 0.0000 → 2.0800 (+2.0800) |
| Employé embauché après fin du mois → accrual=0 | OK | OK non | - | _compute_accrual_days=0.0 |

---
*Rapport généré automatiquement par scripts/test_e2e.py*