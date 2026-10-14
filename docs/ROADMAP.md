# ROADMAP.md — Plan de bataille (chaque tâche faite une seule fois, zéro redite)

> Règle de chantier : **une phase = un livrable vérifiable**. On ne passe à la suivante
> qu'après exécution réelle des commandes de vérification de la phase (jamais affirmées).
> Traçabilité complète brief → phase : `ARCHITECTURE.md §14`.

---

## Phase 0 — Architecture & Design System ✅ (livrables de cette étape)

| Livrable | Fichier |
|---|---|
| Système d'architecture (stack, arborescence, settings, schéma, endpoints, sécurité, WS, PWA, tests) | `docs/ARCHITECTURE.md` |
| Design system (tokens, statuts, composants, a11y, anti-patterns) | `design-system/MASTER.md` |
| Plan par phases + traçabilité | `docs/ROADMAP.md` |

**Critère de sortie** : validation utilisateur → démarrage Phase 1.

---

## Phase 1 — Socle technique & ossature du monolithe
*« On ne code le métier qu'après l'ossature. »*

1. Dépendances `uv` (channels, channels-redis, psycopg[binary], openpyxl, whitenoise,
   python-dotenv) + `.env.example` + nettoyage du squelette `main.py`.
2. `package.json` (tailwindcss 3.4.19) + scripts `build`/`watch`.
3. Django project `core/` : `settings.py` **fichier unique** (dev=SQLite via `DB_ENGINE=sqlite`,
   prod=PostgreSQL via `DB_ENGINE=postgresql`), `urls.py`,
   `asgi.py`, `wsgi.py`, `routing.py`, `manage.py`.
4. 3 apps squelettes (`accounts`, `core_scolarite`, `tickets`) avec la structure
   `models.py` / `views/{__init__,base,ajax_actions}.py` / `tests/__init__.py` / `urls.py`.
5. Base **SQLite** `db.sqlite3` initialisée, migration initiale de `contrib`
   (bascule PostgreSQL documentée pour la prod, `ARCHITECTURE.md §5.3`).
6. Structure `templates/`, `static/{css,js,fonts,icons}/` créées (vides).

**Vérifications** : `uv run python manage.py check`,
`makemigrations --check --dry-run`, le serveur démarre sur `runserver`.

## Phase 2 — Design system & coque SPA (Prompt 1/2/3 + CSS/JS architecture)
1. `tailwind.config.js` (palette navy/ink/background, Inter, safelist des badges de statut).
2. `static/css/input.css` : `@tailwind base/components/utilities` + composants
   `@layer` (btn, field, toast, ticket-card, bottom-nav, skeleton) conformes à `MASTER.md`.
3. Inter auto-hébergé (`static/fonts/*.woff2` + `@font-face`).
4. `templates/base.html` : i18n `{% trans %}`, `#master-modal`, `#global-toaster`, ordre des scripts.
5. `templates/dashboard/index.html` : header, `#spa-viewport`, bottom-nav à 3 zones,
   squelette de chargement.
6. `static/js/app_spa.js` : `openMasterModal/closeMasterModal` (translate-y), skeleton,
   `loadFragment` (fetch + swap, zéro reload), `showNotification` (toaster 4 s).
7. Landing minimaliste (`templates/landing/index.html`) : hero centré + [Se connecter]
   qui ouvre la modale de login (markup only, wiring en Phase 4).
8. Build : `npm run build` → `static/css/output.css`.

**Vérifications** : build OK, rendu à 375 px (capture via navigateur si disponible),
contraste des tokens, focus visible.

## Phase 3 — Modèles & migrations (Prompts 4/5/6)
1. `accounts/models.py` : Faculty, Department, Student (onboarding null-ok), Teacher + index.
2. `core_scolarite/models.py` : Course, ProblemType, AttachmentConfig + index.
3. `tickets/models.py` : Ticket (enum, `received_at`/`resolved_at`, CheckConstraint,
   index `(student,status)` `(teacher,status)`), TicketAttachment.
4. `admin.py` des 3 apps + `seed_demo.py` (facultés, départements, UE, types de problèmes,
   règles de pièces jointes, comptes de démo des 3 rôles).

**Vérifications** : `makemigrations` + `migrate` + `test` (contraintes uniques, index présents
dans `sqlmigrate`), seed rejouable.

## Phase 4 — Authentification, rôles & onboarding MVP (Prompt « Landing », scénario Cas A)
1. Routes login/logout JSON (`accounts/views/ajax_actions.py`) + `auth_handler.js`
   (loading, erreurs, rate-limit session 5 essais).
2. Routage par rôle depuis `/dashboard/` : étudiant → flux, enseignant → inbox,
   superuser → console admin (redirections AJAX, pas de page pleine).
3. Onboarding MVP : si `not student.is_onboarded` → modale `onboarding_profile.html`,
   cascade Faculté → Département (`/accounts/ajax/departments/`), sauvegarde
   liée à `request.user.student_profile` uniquement.
4. Bandeau « mot de passe géré par le portail central » sur le profil (aucun formulaire).
5. Garde-fous : decorators `login_required` + rôles, tests IDOR de base.

**Vérifications** : tests login/onboarding/403, parcours réel : landing → login → onboarding → dashboard.

## Phase 5 — ETL massif (Prompts 7/8)
1. `core_scolarite/services/data_importer.py` : 6 headers stricts, validation ligne à ligne
   (faculté inexistante, département mal rattaché, champ vide, doublon matricule),
   collecte `{line, message}`, `transaction.atomic()` global, mode `strict_placement` (Cas A/B).
2. `core_scolarite/views/admin_actions.py` : superuser only, upload multipart AJAX →
   `200 {status, imported_count}` / `400 {status, errors:[...]}`.
3. Modale `admin_import.html` + rendu des erreurs par ligne (mapping élégant pour l'admin).
4. Création manuelle (formulaire lié Faculté → Département) — option A du brief.

**Vérifications** : `test_importer.py` (fichier 10k lignes simulé avec erreur en fin de
fichier → rollback total = 0 enregistrement), refus non-superuser (403).

## Phase 6 — Formulaire dynamique & création de ticket (Prompts 9/10/11/12)
1. `core_scolarite/views/ajax_selectors.py` : `form-config` (`.values()`, filtre département
   étudiant, cible < 10 ms).
2. `tickets/services/ticket_creator.py` : résolution enseignant (`primary_instructor`),
   contrôle des pièces requises, whitelist/taille, `transaction.atomic()` + nettoyage
   des fichiers orphelins.
3. `tickets/views/ajax_actions.py` : POST multipart, **binding `request.user.student_profile`
   (aucun ID client)**, `201`/`400`.
4. `static/js/ticket_form_dynamic.js` : `fetchFormConfiguration(problemTypeId)`,
   injection dynamique des `<input type="file">` étiquetés avec `*` si requis,
   champ enseignant pré-rempli/filtré.
5. Modale `student_request_form.html` + intégration à la bottom-nav [Nouvelle].

**Vérifications** : tests (pièce manquante → exception, cours hors département → 400,
création → ticket SENT + pièces), parcours complet soumission en navigateur.

## Phase 7 — Dashboards étudiant/enseignant & cycle de vie (Prompts 13/14/15)
1. `tickets/views/student_dashboard.py` : flux `select_related`, cartes avec rail de statut,
   collapse du `rejection_reason`.
2. `tickets/views/teacher_dashboard.py` : inbox chronologique (priorité non traités),
   vue détail sans reload (student, description, téléchargement des fichiers),
   boutons [Valider]/[Rejeter] → modale de décision.
3. `tickets/services/status_machine.py` : transitions autorisées + horodatages.
4. `tickets/views/status_processor.py` : contrôle **appartenance → 403**,
   `rejection_reason` requis sur REJECTED → `400`, sinon `200` JSON.
5. `static/js/ticket_lifecycle.js` : [Démarrer l'analyse], validation des pièces,
   états loading, toasters.

**Vérifications** : tests transitions + IDOR (enseignant A sur ticket de B → 403),
parcours double écran étudiant/enseignant.

## Phase 8 — WebSockets & notifications temps réel (Prompts 16/17/18)
1. `core/asgi.py` + `core/routing.py` (`AuthMiddlewareStack`).
2. `tickets/consumers.py` : `TicketConsumer`, groupe `user_{id}`, refus anonyme (4401).
3. `tickets/signals.py` : `post_save(Ticket)` → payload (+ `card_html`) vers
   étudiant **et** enseignant via `async_to_sync(group_send)`.
4. `static/js/websocket_listener.js` : connexion, reconnexion backoff, patch de carte
   par `data-ticket-id`, `navigator.vibrate(50)`, toaster de statut.

**Vérifications** : test consumer (channel layer en mémoire), scénario réel 2 onglets
(soumission → carte enseignant qui s'insère sans reload).

## Phase 9 — PWA (Prompt 19)
1. `static/manifest.json` (short_name, orientation portrait, themes, icônes 192/512/maskable).
2. `static/service-worker.js` : précache shell, Cache-First statique,
   Network-First dashboard, purge des anciennes versions.
3. Icônes + enregistrement SW dans `base.html`.

**Vérifications** : manifest valide, SW actif (onglet Application), offline : shell affiché.

## Phase 10 — Console super-admin & analytique (Prompt 20)
1. `core_scolarite/views/analytics.py` : agrégation en une passe
   (`Count` + `Case/When`) : total requêtes, non résolues, temps moyen de réponse par faculté.
2. `partials/admin_metrics.html` : cartes de KPI + goulots d'étranglement (mobile-first),
   liens vers import et règles de pièces jointes.
3. Éditeur de règles `AttachmentConfig` / `ProblemType` (fragment modal + POST AJAX).

**Vérifications** : test des agrégations sur jeu de démo, contrôle des droits (non-superuser 403).

## Phase 11 — Durcissement, tests & livraison (CHECKLIST.md)
1. Suite de tests complète, `manage.py check --deploy` (settings prod),
   `makemigrations --check --dry-run`, build Tailwind reproductible.
2. Revue sécurité : IDOR, CSRF, uploads, secrets, logs, rate-limit login.
3. Revue UI : `web-design-guidelines` + checklist `MASTER.md §7-8` (navigateur si outil dispo).
4. Docs : README (installation uv/npm, commandes), bascule LDAP (Cas B) documentée.
5. Rapport final au format du skill `django-fullstack-pro` + `CHECKLIST.md`.

---

## Garde-fous de chantier

- **Pas de codage métier avant la validation de la Phase 0** (ce document).
- Chaque phase se termine par l'exécution réelle de ses commandes de vérification ;
  un test non exécuté est rapporté comme « non exécuté », jamais comme réussi.
- Une tâche n'est listée qu'une fois : pour le reste, se référer à `ARCHITECTURE.md §14`
  (traçabilité) plutôt que de redécrire les spécifications ici.
- `skills` requis par la suite : `django-fullstack-pro` (toujours),
  `frontend-design` + `ui-ux-pro-max` (P2, P7, P10), `web-design-guidelines` + `webapp-testing`
  (revisions P2/P11). Les skills `polish`, `critique`, `agent-browser` mentionnées dans
  `AGENTS.md` **ne sont pas installées** dans cet environnement → remplacées par
  `web-design-guidelines` (revue) et `webapp-testing` (vérification navigateur).
