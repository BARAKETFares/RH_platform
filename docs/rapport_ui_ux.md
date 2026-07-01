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

---

## Session 2 — Login eye toggle + Avatar + Liste employés

### 1. Afficher/masquer le mot de passe (login + changement de mot de passe)

- `login.html` avait déjà un bouton œil fonctionnel (`bi-eye` / `bi-eye-slash`) avec un script inline
  dédié à son unique champ `password` — rien à faire côté login.
- `change_password.html` (créé en session 1) n'avait pas ce bouton, et comporte **3 champs mot de
  passe** (`current_password`, `new_password`, `new_password_confirm`). Plutôt que dupliquer un
  script par champ, un helper générique a été ajouté dans `app/static/js/main.js` : tout bouton
  `[data-password-toggle="<id-du-champ>"]` bascule le champ ciblé entre `type="password"`/`"text"`
  et échange l'icône `bi-eye` / `bi-eye-slash`. Les 3 champs de `change_password.html` utilisent ce
  helper. `login.html` n'a pas été touché (déjà fonctionnel, hors périmètre de migration).
- Vérifié par rendu (client de test) : les attributs `data-password-toggle` sont bien présents sur
  les 3 champs de `change_password.html` et le bouton/icône de `login.html` existent toujours.

### 2. Photo de profil (upload + affichage)

Architecture alignée sur le pattern CV existant (`app/blueprints/recruitment/routes.py`,
`storage/uploads/cvs/`) : fichier sur disque, chemin relatif en base.

- **Migration** : colonne `avatar_path` (String(500), nullable) ajoutée à `users`
  (`app/models/user.py`), migration Alembic `f7331b8d5cf3_add_avatar_path_to_users.py` générée par
  `flask db migrate` et appliquée par `flask db upgrade` — un seul `ADD COLUMN`, sans effet de bord
  (vérifié : `flask db current` pointait déjà sur le head avant migration, pas de drift de schéma
  préexistant). Commentaire explicite en base : ce n'est pas une donnée sensible (chemin de fichier),
  donc pas de chiffrement Fernet contrairement aux champs `iban`/`national_id_number` de `Employee`.
- **Upload** : `AvatarUploadForm` (`app/blueprints/auth/forms.py`) — `FileAllowed(["png","jpg","jpeg"])`
  + `FileSize(max_size=2 Mo)`, validation serveur (pas seulement client). Fichier nommé
  `<uuid_hex>_<user_id>.<ext>` et stocké dans `storage/uploads/avatars/` (même convention que les CV).
  L'ancien fichier est supprimé du disque lors d'un remplacement (évite l'accumulation d'orphelins).
- **Serving** : `GET /auth/avatar/<user_id>` (`app/blueprints/auth/routes.py`) — `send_from_directory`
  avec le bon `Content-Type` (`image/png` ou `image/jpeg`). Route protégée par `@login_required`
  (contrairement au téléchargement de CV qui exige en plus un rôle précis — une photo de profil est
  une donnée moins sensible qu'un CV, mais rester authentifié est le minimum raisonnable ; à
  resserrer si un rôle plus strict est souhaité). Si `avatar_path` est `None` → `abort(404)` géré
  proprement par le handler d'erreurs déjà en place (`_register_error_handlers`), pas de 500.
- **Profil** : formulaire d'upload ajouté dans `auth/profile.html` (aperçu `<img>` si `avatar_path`,
  sinon avatar initiales existant — filtre `initials`).
- **`storage/uploads/avatars/`** est déjà couvert par l'entrée `.gitignore` existante `storage/`
  (tout le dossier est ignoré) — aucune modification `.gitignore` nécessaire.
- Vérifié : upload valide (PNG) → 200 + `avatar_path` renseigné en base ; upload `.pdf` → message
  d'erreur lisible (pas 500) ; upload > 2 Mo → message d'erreur lisible (pas 500) ; route avatar sans
  fichier → 404 propre ; route avatar non authentifiée → redirection login (pas d'accès anonyme).

### 3. Avatar dans la liste et la fiche employé

- `employees/list.html` : la colonne "Employé" affiche désormais `<img>` (36×36px, rond,
  `object-fit:cover`) si `emp.user.avatar_path` existe, sinon l'avatar initiales déjà en place
  (`emp.initials`, inchangé).
- `employees/detail.html` : même logique en 80×80px dans la carte latérale.
- Relation vérifiée via Graphify (`graphify path "Employee" "User"`) puis lecture du modèle :
  `Employee.user` (relationship `lazy="joined"`, donc pas de N+1 supplémentaire) donne accès à
  `employee.user.avatar_path`. `employee.user` est `None` pour un employé sans compte applicatif —
  géré par le `{% if emp.user and emp.user.avatar_path %}`.
- Vérifié : liste et fiche détail rendent correctement avant upload (initiales) et après upload
  (`<img src="/auth/avatar/<user_id>">`) pour un employé lié à un compte.

### Vérification globale

- `pytest tests/ -v` : **202 passed**, aucune régression (aucun nouveau test permanent ajouté —
  la mission ne le demandait pas explicitement ; vérifications faites via clients de test temporaires
  puis supprimées après validation, à l'image de la session 1).
- CSP (`security_headers.py`) : `img-src 'self' data: blob:;` couvre déjà la route same-origin
  `/auth/avatar/<user_id>` — aucune modification nécessaire, comme anticipé par la mission.

### Bugs trouvés au passage

- Aucun bug préexistant supplémentaire découvert lors de cette session (le principal, les templates
  `profile.html`/`change_password.html` manquants, avait été corrigé en session 1).
- Point d'attention signalé (non bloquant) : la route `/auth/avatar/<user_id>` n'a pas de contrôle de
  rôle au-delà de l'authentification — un utilisateur "employee" peut donc récupérer la photo de
  profil d'un autre utilisateur en devinant son `user_id`. Acceptable pour une simple photo (pas une
  donnée confidentielle), mais à durcir (ex. `require_role` ou vérification d'appartenance à la même
  équipe/département) si la politique de confidentialité du projet l'exige.

### Fichiers modifiés — Session 2

| Commit | Fichiers |
|---|---|
| `feat: afficher/masquer mot de passe (eye toggle)` | `app/static/js/main.js`, `app/templates/auth/change_password.html` |
| `feat: upload et affichage photo de profil utilisateur` | `app/models/user.py`, `migrations/versions/f7331b8d5cf3_add_avatar_path_to_users.py`, `app/blueprints/auth/forms.py`, `app/blueprints/auth/routes.py`, `app/templates/auth/profile.html` |
| `feat: avatar utilisateur dans liste et fiche employé` | `app/templates/employees/list.html`, `app/templates/employees/detail.html` |
