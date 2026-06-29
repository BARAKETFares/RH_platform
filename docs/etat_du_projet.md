# État du projet — HR Platform
**Date** : 29 juin 2026  
**Stack** : Flask · SQLAlchemy 2.0 · WTForms · Bootstrap 5 · Celery · JWT

---

## 1. Architecture générale

```
hr_platform/
├── app/
│   ├── blueprints/          # Modules SSR (HTML rendu côté serveur)
│   │   ├── auth/            # ✅ Authentification (login, logout, 2FA TOTP)
│   │   ├── employees/       # ✅ Gestion des employés
│   │   ├── leaves/          # ✅ Congés & absences
│   │   ├── performance/     # ✅ Évaluations & objectifs
│   │   ├── admin/           # ✅ Administration (users, rôles, org, audit)
│   │   ├── reporting/       # ✅ Tableau de bord KPIs
│   │   ├── payroll/         # 🔴 Squelette vide (routes non implémentées)
│   │   ├── recruitment/     # 🔴 Squelette vide
│   │   └── training/        # 🔴 Squelette vide
│   ├── api/v1/              # REST API JWT
│   │   ├── auth.py          # ✅ Login/refresh JWT
│   │   ├── employees.py     # ✅ CRUD employés (JSON)
│   │   ├── evaluations.py   # ✅ Évaluations (JSON)
│   │   └── leaves.py        # ✅ Congés (JSON)
│   ├── models/              # Modèles SQLAlchemy
│   └── services/            # Logique métier
└── docs/                    # Ce dossier
```

---

## 2. Ce qui a été fait dans cette session

### 2.1 Bug critique — TypeError à la création d'un employé

**Problème** : `TypeError: 'national_id_number' is an invalid keyword argument for Employee`

**Cause** : Dans `employee_service.py`, les champs `national_id_number`, `iban`, `bic` étaient passés directement au constructeur `Employee(...)`. Or ces trois champs sont des `hybrid_property` (avec chiffrement Fernet via `encrypt_field`), pas des colonnes mappées. SQLAlchemy n'accepte dans `__init__` que les noms des colonnes réelles (`_national_id_number`, `_iban`, `_bic`).

**Fix** (`app/services/employee_service.py`) : Retrait de ces trois champs du constructeur, puis affectation via les setters de propriété après instanciation :
```python
employee = Employee(...)  # sans national_id_number, iban, bic
if data.get("national_id_number"):
    employee.national_id_number = data["national_id_number"]  # → encrypt_field()
if data.get("iban"):
    employee.iban = data["iban"]
if data.get("bic"):
    employee.bic = data["bic"]
```

---

### 2.2 Champs sensibles absents du formulaire employé

**Problème** : `national_id_number`, `annual_gross_salary`, `iban`, `bic` étaient volontairement exclus du formulaire (commentaire dans le code), mais absents de l'interface.

**Fix** : Ajout dans :
- `app/blueprints/employees/forms.py` — 4 nouveaux champs dans `EmployeeForm`
- `app/templates/employees/form.html` — section "Données sensibles (Admin / RH)"
- `app/blueprints/employees/routes.py` — payloads `new_employee` et `edit_employee`, pré-remplissage en GET

---

### 2.3 Listes déroulantes vides (département, poste, site, manager)

**Problème** : Le formulaire employé affichait uniquement `— Aucun —` dans tous les `SelectField` organisationnels.

**Cause** : Il n'existait aucune page admin pour créer des départements, postes ou sites. La base de données était vide pour ces tables.

**Fix** : Création de l'administration complète pour l'organisation :

| Route | Description |
|-------|-------------|
| `GET/POST /admin/departments/` | Liste et création de départements |
| `GET/POST /admin/departments/<id>/edit` | Modification |
| `GET/POST /admin/positions/` | Liste et création de postes |
| `GET/POST /admin/positions/<id>/edit` | Modification |
| `GET/POST /admin/sites/` | Liste et création de sites géographiques |
| `GET/POST /admin/sites/<id>/edit` | Modification |

Fichiers créés/modifiés : `admin/forms.py`, `admin/routes.py`, templates dans `admin/departments/`, `admin/positions/`, `admin/sites/`, sidebar dans `base.html`.

---

### 2.4 Données sensibles absentes de la vue détail employé

**Problème** : Après remplissage du formulaire employé, la page de détail n'affichait pas IBAN, numéro de sécu ni salaire.

**Cause** : `detail.html` n'avait aucune section pour ces champs.

**Fix** (`app/templates/employees/detail.html`) : Ajout d'un bloc "Données sensibles (Admin / RH)" visible uniquement par les rôles `admin` et `rh`, affichant numéro de sécurité sociale, salaire brut annuel, IBAN, BIC.

---

### 2.5 Liste de contrats vide — impossible d'ajouter un contrat

**Problème** : La modal "Nouveau contrat" dans la fiche employé avait une liste déroulante vide pour le "Type de contrat", rendant le formulaire invalide.

**Cause** : Le formulaire `ContractForm.populate_contract_types()` requête `ContractType.active_in_company()`, mais aucune page admin n'existait pour créer des types de contrats.

**Fix** : Création de l'administration des types de contrats :

| Route | Description |
|-------|-------------|
| `GET /admin/contract-types/` | Liste |
| `GET/POST /admin/contract-types/new` | Créer (ex: CDI Cadre, CDD, Stage…) |
| `GET/POST /admin/contract-types/<id>/edit` | Modifier |

Fichiers : `ContractTypeForm` dans `admin/forms.py`, routes dans `admin/routes.py`, templates dans `admin/contract_types/`.

**Ordre de configuration requis** : Créer d'abord un type de contrat dans l'admin, puis utiliser la modal "Nouveau contrat" sur la fiche employé.

---

### 2.6 Erreur 403 pour l'admin sur toutes les pages employés

**Problème** : L'admin obtient une erreur HTTP 403 sur `/employees/`, `/employees/new`, etc.

**Cause** : La fonction `_current_company_id()` dans `employees/routes.py` faisait `abort(403)` si l'utilisateur n'avait pas de fiche employé associée :
```python
# AVANT (cassé pour admin sans fiche employé)
if not current_user.employee:
    abort(403, description="Aucun profil employé associé à ce compte.")
return current_user.employee.company_id
```

**Fix** : Fallback sur `Company.get_default()` :
```python
# APRÈS
if current_user.employee:
    return current_user.employee.company_id
company = Company.get_default()
if company is None:
    abort(400, description="Aucune entreprise configurée.")
return company.id
```

---

## 3. Problèmes et failles logiques identifiés

### 3.1 🔴 Critique — Aucune interface pour créer une Company

**Problème** : Il n'existe aucune page pour créer une entreprise (`Company`). Tout le système repose sur `Company.get_default()` (première ligne de la table `companies`), mais si la table est vide, toutes les pages retournent une erreur 400.

**Impact** : Un fresh install est inutilisable sans script de seed ou migration avec données initiales.

**Solution recommandée** : Créer un script CLI Flask (`flask seed`) ou une page de setup initial accessible sans login si `companies` est vide.

---

### 3.2 🔴 Critique — Types de congés (`LeaveType`) sans interface d'administration

**Problème** : Même problème que les types de contrats. Le module congés (`leaves`) requête `LeaveType` pour remplir les formulaires de demande d'absence. Il n'y a aucune page admin pour créer des types de congés (CP, RTT, maladie…).

**Impact** : Le module congés est inutilisable sans données initiales dans `leave_types`.

**Solution recommandée** : Créer un CRUD admin pour `LeaveType`, similaire à ce qui a été fait pour `ContractType`.

---

### 3.3 🟠 Important — Sidebar admin invisible pour le rôle RH

**Problème** : Les liens vers Départements, Postes, Sites, Types de contrats dans la sidebar sont dans le bloc `{% if role == 'admin' %}`. Or les routes correspondantes acceptent aussi le rôle `rh` (`@require_role("admin", "rh")`).

**Conséquence** : Un utilisateur RH peut accéder aux URLs directement mais ne voit pas ces menus.

**Fix** (`app/templates/base.html`) : Changer la condition du bloc administration :
```jinja2
{# AVANT #}
{% if role == 'admin' %}

{# APRÈS #}
{% if role in ['admin', 'rh'] %}
```
Attention : les sous-sections "Utilisateurs", "Rôles", "Journal d'audit" doivent rester restreintes à `admin` uniquement. Il faut scinder le bloc en deux.

---

### 3.4 🟠 Important — Contraintes UNIQUE non gérées dans les routes admin

**Problème** : Les routes admin pour Département, Poste, Site, Type de contrat ne capturent pas les `IntegrityError` SQLAlchemy. Si on essaie de créer deux fois le même nom, l'application lève une erreur 500 au lieu d'afficher un message d'erreur lisible.

**Exemples de contraintes concernées** :
- `uq_departments_name_per_company` (même nom de département dans la même entreprise)
- `uq_positions_title_per_department` (même titre de poste dans le même département)
- `uq_sites_name_per_company` (même nom de site)
- `uq_contract_types_name_per_company` (même nom de type de contrat)

**Fix recommandé** : Wrapper les `db.session.commit()` dans un `try/except IntegrityError` dans chaque route concernée et afficher un `flash(..., "error")` explicite.

---

### 3.5 🟠 Important — Dashboard admin vide sans fiche employé

**Problème** : Dans `reporting/routes.py`, `_current_company_id()` retourne `None` si l'admin n'a pas de fiche employé. Dans ce cas le dashboard affiche des KPIs vides (effectif = None, congés = 0) même s'il y a des données en base.

**Fix recommandé** : Appliquer le même fallback `Company.get_default()` que dans les autres routes :
```python
def _current_company_id() -> int | None:
    if current_user.employee:
        return current_user.employee.company_id
    from app.models.organization import Company
    company = Company.get_default()
    return company.id if company else None
```

---

### 3.6 🟡 Mineur — `annual_gross_salary` : type `float` vs `Decimal`

**Problème** : Le modèle `Employee` déclare `annual_gross_salary: Mapped[Optional[float]]` mais la colonne SQLAlchemy est `Numeric(12, 2)`, qui retourne des objets Python `Decimal`. Le type hint `float` est donc incorrect.

**Conséquence** : Pas de bug à l'exécution (Python convertit implicitement), mais peut provoquer des surprises lors de comparaisons ou de sérialisations JSON (`json.dumps` ne sait pas sérialiser `Decimal`).

**Fix recommandé** : Changer l'annotation en `Decimal` et importer `from decimal import Decimal`, ou ajouter une propriété qui force le cast en `float`.

---

### 3.7 🟡 Mineur — `notice_period_days` dans `ContractTypeForm` est un `StringField`

**Problème** : Le champ `notice_period_days` est défini comme `StringField` avec `render_kw={"type": "number"}`. La validation ne garantit pas que la valeur est un entier valide.

**Fix recommandé** : Remplacer par `IntegerField` de WTForms avec `NumberRange(min=0)`.

---

### 3.8 🟡 Mineur — Module Performance : accès impossible pour admin sans fiche employé

**Problème** : Le module performance (`/performance/`) utilise `current_user.employee.id` sans vérification dans plusieurs endroits. Un admin sans fiche employé obtient une erreur `AttributeError: 'NoneType' object has no attribute 'id'`.

**Fix recommandé** : Appliquer le même pattern de garde que dans les autres blueprints, ou réserver l'accès performance aux comptes avec fiche employé.

---

### 3.9 🟡 Mineur — Multi-société non fonctionnel

**Problème** : Le modèle `Company` supporte plusieurs entreprises (architecture multi-tenant), mais `Company.get_default()` retourne toujours la première. Dans un contexte multi-société, un admin verrait toujours la première entreprise, quelle que soit celle qu'il gère.

**État actuel** : Mono-société uniquement, ce qui est suffisant pour une PME.

**À documenter** : Si le projet évolue vers le multi-société, il faudra un mécanisme de sélection de company (session, URL prefix `/company/<id>/`, ou subdomain).

---

## 4. État des modules

| Module | Interface web | API REST | Service métier | État |
|--------|--------------|----------|----------------|------|
| Auth | ✅ Complet | ✅ JWT | ✅ | Fonctionnel |
| Employés | ✅ CRUD complet | ✅ | ✅ | Fonctionnel |
| Organisation (dept/poste/site) | ✅ Admin CRUD | ❌ | — | Fonctionnel |
| Types de contrats | ✅ Admin CRUD | ❌ | — | Fonctionnel |
| Contrats employé | ✅ Création via modal | ❌ | — | Fonctionnel |
| Congés | ✅ Circuit approbation | ✅ | ✅ | Fonctionnel si LeaveTypes créés |
| Types de congés | ❌ Pas d'admin CRUD | ❌ | — | **Bloquant** |
| Performance | ✅ Campagnes + évaluations | ✅ | ✅ | Fonctionnel si fiche employé |
| Tableau de bord | ✅ KPIs | — | — | Partiellement (vide pour admin) |
| Paie | ❌ Squelette vide | ❌ | ❌ | Non développé |
| Recrutement | ❌ Squelette vide | ❌ | ❌ | Non développé |
| Formation | ❌ Squelette vide | ❌ | ❌ | Non développé |

---

## 5. Ordre de configuration pour un premier démarrage

Pour rendre la plateforme opérationnelle depuis zéro :

1. **Créer l'entreprise** en base (via `flask shell` ou migration seed) — pas d'interface UI
2. **Créer un compte admin** (via `flask shell` ou route d'initialisation)
3. **Admin → Départements** : créer au moins un département
4. **Admin → Postes** : créer des postes (nécessite un département)
5. **Admin → Sites** : créer un site géographique (optionnel)
6. **Admin → Types de contrats** : créer CDI, CDD, etc.
7. *(À créer)* **Admin → Types de congés** : créer CP, RTT, maladie, etc.
8. **Employés → Nouvel employé** : les listes déroulantes seront maintenant remplies
9. **Fiche employé → Nouveau contrat** : la liste des types sera remplie

---

## 6. Fichiers modifiés dans cette session

| Fichier | Type de changement |
|---------|-------------------|
| `app/services/employee_service.py` | Bug fix : hybrid_property dans constructeur |
| `app/blueprints/employees/forms.py` | Ajout champs sensibles (IBAN, sécu, salaire) |
| `app/blueprints/employees/routes.py` | Payloads + pré-remplissage + fix 403 admin |
| `app/templates/employees/form.html` | Section "Données sensibles" |
| `app/templates/employees/detail.html` | Section "Données sensibles" en lecture |
| `app/blueprints/admin/forms.py` | DepartmentForm, PositionForm, SiteForm, ContractTypeForm |
| `app/blueprints/admin/routes.py` | CRUD Département, Poste, Site, Type de contrat + helper |
| `app/templates/admin/departments/list.html` | Nouveau |
| `app/templates/admin/departments/form.html` | Nouveau |
| `app/templates/admin/positions/list.html` | Nouveau |
| `app/templates/admin/positions/form.html` | Nouveau |
| `app/templates/admin/sites/list.html` | Nouveau |
| `app/templates/admin/sites/form.html` | Nouveau |
| `app/templates/admin/contract_types/list.html` | Nouveau |
| `app/templates/admin/contract_types/form.html` | Nouveau |
| `app/templates/base.html` | Sidebar : liens org + types contrats |
