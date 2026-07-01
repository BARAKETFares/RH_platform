# Rapport — Refonte UI/UX de la plateforme RH

## 1. Diagnostic préalable (Graphify + inspection manuelle)

- `base.html` est étendu par les **47 templates** du projet (tous les modules : Employés, Congés,
  Évaluations, Admin, Paie, Recrutement, Formation). La sidebar affiche/masque ses liens selon
  `current_user.role.name` (Jinja `{% if role in [...] %}`) — logique préservée à l'identique.
- Graphify n'indexe que l'AST Python (pas les templates Jinja) ; le diagnostic sur `base.html` /
  `main.css` a donc été fait par lecture directe et `grep` des 47 `extends "base.html"`.

## 2. Choix du template — Bootstrap 5 "Dashboard" (officiel)

**AdminLTE 3 et SB Admin 2 sont en réalité basés sur Bootstrap 4** (vérifié via recherche web),
ce qui contredit le critère "Bootstrap 5 natif" de la mission. AdminLTE 4 est bien du Bootstrap 5
natif, mais impose son propre système de classes de layout (`main-sidebar`, `nav-treeview`,
`content-wrapper`…), ce qui aurait nécessité de réécrire la structure de la sidebar par rôle dans
les 47 templates — un risque disproportionné pour l'objectif recherché.

Choix retenu (validé avec l'utilisateur) : **le pattern officiel "Dashboard" de getbootstrap.com**,
appliqué en enrichissant `base.html` / `main.css` existants plutôt qu'en les remplaçant :
- Même version Bootstrap 5.3.2 déjà chargée → **zéro nouvelle dépendance CDN**.
- La logique Jinja de sidebar par rôle n'est pas touchée, uniquement restylée.
- Répond à tous les critères : Bootstrap 5 natif, sidebar, cartes KPI, tableaux, formulaires propres.

Changements apportés :
- Sidebar rendue responsive (collapse Bootstrap natif sur mobile/tablette, `d-lg-block` sur grand
  écran) — auparavant fixe à 240px, elle recouvrait le contenu sur petit écran.
- Navbar : bouton toggler mobile pour la sidebar, avatar avec initiales (filtre `initials`) au lieu
  d'un simple texte.
- Cartes KPI : accent de couleur à gauche + ombre légère (`.kpi-card`).
- Tableaux : en-têtes stylisés (majuscules, espacement).

Fichiers modifiés : `app/templates/base.html`, `app/templates/components/_navbar.html`,
`app/static/css/main.css`.

Vérification : rendu testé (via client de test Flask, 4 rôles) sur `/reporting/dashboard`,
`/employees/` et `/performance/evaluations/<id>` → 200 OK sur les 3 pages, suite pytest complète
(202/202) toujours au vert.

## 3. Cause exacte des boutons/icônes carrés vides — et correctif

**Ce n'était pas un problème de CDN manquant ni de classe CSS incorrecte.** `bootstrap-icons.min.css`
était bien chargé (autorisé par la directive `style-src`). Le bug venait de la **Content-Security-Policy**
définie dans `app/utils/security_headers.py` :

```
font-src 'self' fonts.gstatic.com;   ← cdn.jsdelivr.net absent
```

Le fichier de police (`.woff2`) référencé par `bootstrap-icons.min.css` est hébergé sur
`cdn.jsdelivr.net`. La CSP bloquait son chargement → chaque `<i class="bi bi-*">` s'affichait comme
un carré vide (glyphe de fallback "tofu" du navigateur), alors que la feuille de style CSS
elle-même se chargeait sans erreur.

**Correctif** (une seule ligne, source du problème corrigée plutôt que les symptômes) :
```
font-src 'self' cdn.jsdelivr.net fonts.gstatic.com;
```

Fichier modifié : `app/utils/security_headers.py`.

## 4. Section profil utilisateur

La route `GET /auth/profile` existait déjà (`app/blueprints/auth/routes.py`) mais son template
(`auth/profile.html`) était absent — la page renvoyait une erreur 500. Idem pour
`/auth/password/change` (`auth/change_password.html` absent).

Créé/complété :
- `app/templates/auth/profile.html` — informations de compte (email, rôle, date de création,
  dernière connexion), avatar à initiales, informations professionnelles (département, poste,
  manager, date d'embauche) si une fiche employé est liée, statistiques congés personnelles
  (demandes en attente + soldes disponibles par type) pour les rôles employee/manager, statut 2FA,
  et accès à la sécurité (changement de mot de passe, activation/désactivation 2FA).
- `app/templates/auth/change_password.html` — formulaire séparé (mot de passe actuel + nouveau +
  confirmation), réutilise le formulaire et la validation serveur déjà existants
  (`ChangePasswordForm`, service `change_password`).
- `app/blueprints/auth/routes.py` — `profile_get()` calcule désormais les congés en attente et les
  soldes de congés (`calculate_all_balances`) pour les rôles employee/manager.
- Lien "Mon profil" dans la navbar (`_navbar.html`) : pointait vers `href="#"` (non fonctionnel),
  redirige maintenant vers `auth.profile_get`.

## 5. Vérification post-modification

- `pytest tests/ -v` : **202 passed**, aucune régression introduite par les changements de
  templates/routes.
- Rendu testé via client de test Flask pour les **4 rôles** (admin, rh, manager, employee) sur
  `/auth/profile` et `/auth/password/change` → 200 OK pour chacun, y compris le cas d'un compte
  employee lié à une fiche employé (bloc "Informations professionnelles" + soldes de congés
  correctement affichés).
- Icônes/boutons Bootstrap Icons désormais chargés sans blocage CSP sur toutes les pages testées.

## 6. Bugs trouvés au passage (hors périmètre direct, signalés)

- **`auth/profile.html` et `auth/change_password.html` manquants** : les routes existaient déjà et
  plantaient en 500 avant cette intervention — corrigé (cf. section 4).
- **Lien navbar "Mon profil" mort** (`href="#"`) — corrigé (cf. section 4).
- **CSP avec nonce jamais substitué** : `security_headers.py` contient `'nonce-{nonce}'` en dur
  dans `script-src`, jamais formaté avec un vrai nonce généré par requête. Ligne morte sans impact
  sur le rendu des icônes (hors périmètre de cette mission), mais à corriger dans une revue de
  sécurité dédiée — soit en générant un vrai nonce par requête, soit en retirant ce fragment inutile.

## 7. Fichiers modifiés

| Commit | Fichiers |
|---|---|
| `feat: intégration template Bootstrap 5 Dashboard` | `app/templates/base.html`, `app/templates/components/_navbar.html`, `app/static/css/main.css` |
| `fix: correction icônes/boutons carrés vides` | `app/utils/security_headers.py` |
| `feat: page profil utilisateur améliorée` | `app/blueprints/auth/routes.py`, `app/templates/auth/profile.html` (nouveau), `app/templates/auth/change_password.html` (nouveau) |
