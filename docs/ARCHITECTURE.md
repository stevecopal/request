# ARCHITECTURE.md — Portail des Requêtes Universitaires (UnivReq)

> Document unique de référence pour l'architecture système, la modélisation de données,
> la sécurité, le temps réel et le pipeline frontend.
> Le design system visuel a sa propre source de vérité : `design-system/MASTER.md`.
> Le découpage temporel du chantier : `docs/ROADMAP.md`.

---

## 1. Contexte & objectifs

Application mobile-first (PWA) de soumission et de suivi de requêtes académiques
( notes manquantes, doubles corrections, absences justifiées…) pour une université
multi-facultés.

| Role | Usage principal |
|---|---|
| Étudiant | Soumet une requête dynamique (matière + pièces jointes), suit son statut en temps réel |
| Enseignant | Boîte de réception des requêtes assignées, traite et tranche (Valider / Rejeter) |
| Super Admin | Import massif Excel/CSV, règles de pièces jointes, métriques d'exploitation |

**Critères de succès (contrats mesurables)**
- Zéro rechargement de page complet (SPA par fragments HTML + AJAX + WebSockets).
- Dashboards < 5 ms de requête DB (index composites), endpoint de configuration de formulaire < 10 ms.
- Import atomique : rollback total en cas d'erreur sur n'importe quelle ligne.
- Aucune vulnérabilité IDOR : aucune donnée lue ou écrite à partir d'un ID fourni par le client.
- Cibles tactiles ≥ 48 px, contraste texte/corps ≥ 4,5:1, respect de `prefers-reduced-motion`.

---

## 2. Stack technique (versions réelles vérifiées dans l'environnement)

| Couche | Choix | Version vérifiée | Justification |
|---|---|---|---|
| Language | Python | 3.14.3 | `.python-version` du dépôt |
| Framework | Django | 6.1.2 | déjà résolu par `uv.lock` (≥ 5.x exigé par le brief) |
| Real-time | Django Channels + channels-redis | 4.3.2 / 4.3.0 | compatibles `Django>=4.2`, vérifié sur PyPI |
| DB | **SQLite (dev) → PostgreSQL 16 (prod)** | serveur 16.15 actif | décision utilisateur : SQLite pour le développement (zéro config), bascule PostgreSQL en production via variable d'environnement (`§5.3`). Les index composites/contraintes sont définis dès la Phase 3 pour être portables |
| Cache / channel layer | Redis | 7.0.15 actif | layer Channels + cache optionnel |
| Styling | Tailwind CSS **v3.4.19** (CLI npm) | — | **v3 imposé par le brief** : `tailwind.config.js` + directives `@tailwind` + build `input.css → output.css` (Tailwind v4 changerait ce contrat) |
| JS | Vanilla JS (modules ES, `async/await fetch`) | — | pas de framework, conformément au brief |
| Dép. Python | `uv` | 0.10.8 | imposé par l'utilisateur |
| Reverse-proxy/static (prod) | WhiteNoise | à installer | service de `staticfiles` sans nginx obligatoire |
| Excel | openpyxl | à installer | lecture `.xlsx` de l'ETL |

**Dépendances Python (pyproject.toml)**

```
django == 6.1.2            # déjà présent
channels == 4.3.2          # ASGI + WebSocket
channels-redis == 4.3.0    # channel layer Redis
daphne == 4.*              # serveur ASGI de dev (runserver + WebSocket)
psycopg[binary] == 3.2.*   # driver PostgreSQL (prod — dev = SQLite)
openpyxl == 3.1.*          # lecture Excel de l'ETL
whitenoise == 6.*          # service des fichiers statiques
python-decouple == 3.8     # variables d'environnement (.env + os.environ)
```

**Dépendances npm (package.json, devDependencies uniquement)**

```
tailwindcss == 3.4.19
```

Scripts : `npm run build` (`tailwindcss -i static/css/input.css -o static/css/output.css --minify`)
et `npm run watch` (mode dev, sans `--minify`).

**Décisions explicites**
1. **Pas de DRF** : les endpoints AJAX renvoient du `JsonResponse` depuis des vues Django
   classiques (stack légère, contrôles CSRF natifs).
2. **Pas de `LocaleMiddleware`** pour l'instant (brief) : `LANGUAGE_CODE = "fr"`, mais tous les
   littéraux UI sont wrappés dans `{% trans %}` et `gettext_lazy` pour un bascule future sans refonte.
3. **Pas de changement de mot de passe dans l'app** : message fixe renvoyant vers le portail
   central de l'université. En MVP, mot de passe temporaire à la création = règle `Matricule` + année.
4. **Pas de React/Vue/HTMX** : l'SPA repose sur des fragments HTML servis en AJAX + WebSockets.

---

## 3. Principes directeurs

1. **Monolithe modulaire** : 3 applications Django découpées par domaine métier, jamais par couche technique.
2. **Vues minces** : la logique métier vit dans `services/` (ETL, création de ticket, machine à états).
   Les `views/` ne font que : authz → validation → appel service → réponse (JSON ou fragment).
3. **`models.py` unique par app**, mais `views/` = package (`base.py`, `ajax_actions.py`, + spécialisés),
   `tests/` = package. Aucun `views.py` monolithique.
4. **Défense en profondeur IDOR** : toute lecture/écriture part de `request.user`,
   jamais d'un ID de profil issu de la requête.
5. **Mobile-first** : conception sur 375–480 px, montée en largeur ensuite. Colonne centrée `max-w-md`.
6. **Atomicité** : toute opération multi-lignes (ETL, ticket + pièces jointes) sous `transaction.atomic()`.

---

## 4. Arborescence cible du dépôt

```
request/
├── pyproject.toml                  # dépendances uv (Python)
├── uv.lock
├── package.json                    # tailwindcss (npm)
├── package-lock.json
├── manage.py
├── .env                            # secrets (gitignoré)
├── .env.example                    # modèle sans secrets
├── README.md
│
├── core/                           # ── Projet Django : config & routage ──
│   ├── __init__.py
│   ├── settings.py                 # FICHIER UNIQUE : INSTALLED_APPS, middleware, DB, STATIC, MEDIA…
│   │                               #   dev = SQLite ; prod = PostgreSQL via env (§5.3)
│   ├── urls.py                     # routage racine → include() par app (namespaces)
│   ├── asgi.py                     # ProtocolTypeRouter HTTP + WebSocket
│   ├── wsgi.py
│   └── routing.py                  # URLRouter des WebSocket (/ws/tickets/)
│
├── accounts/                       # ── Identités, rôles, profils ──
│   ├── __init__.py
│   ├── apps.py
│   ├── admin.py
│   ├── models.py                   # Faculty, Department, Student, Teacher
│   ├── forms.py                    # formulaire de connexion matricule+MDP, onboarding
│   ├── views/
│   │   ├── __init__.py
│   │   ├── base.py                 # landing, shell dashboard, profil, logout
│   │   └── ajax_actions.py         # login/logout JSON, cascade faculté→département, onboarding
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── test_models.py          # contraintes uniques, index
│   │   └── test_views.py           # auth, cascade, IDOR
│   └── urls.py                     # app_name = "accounts"
│
├── core_scolarite/                 # ── Métadonnées académiques, ETL, règles, analytique ──
│   ├── __init__.py
│   ├── apps.py
│   ├── admin.py
│   ├── models.py                   # Course, ProblemType, AttachmentConfig
│   ├── forms.py                    # import upload, création manuelle, règles admin
│   ├── services/
│   │   ├── __init__.py
│   │   └── data_importer.py        # ETL CSV/XLSX strict + transactionnel
│   ├── views/
│   │   ├── __init__.py
│   │   ├── base.py                 # pages admin (import, règles, analytics)
│   │   ├── admin_actions.py        # POST upload ETL → JSON (superuser only)
│   │   ├── ajax_selectors.py       # GET form-config → JSON cascade (cœur du formulaire dynamique)
│   │   └── analytics.py            # métriques agrégées (Count, conditional aggregation)
│   ├── management/
│   │   └── commands/
│   │       └── seed_demo.py        # jeu de démo (facultés, départements, UE, règles)
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── test_models.py
│   │   ├── test_importer.py        # headers, rollback 9999/10000, cohérence hiérarchique
│   │   └── test_views.py           # droits superuser, JSON d'erreurs
│   └── urls.py                     # app_name = "core_scolarite"
│
├── tickets/                        # ── Workflow, états, temps réel ──
│   ├── __init__.py
│   ├── apps.py
│   ├── admin.py
│   ├── models.py                   # Ticket, TicketAttachment
│   ├── services/
│   │   ├── __init__.py
│   │   ├── ticket_creator.py       # create_student_ticket(...) transactionnel
│   │   └── status_machine.py       # transitions autorisées + apply_status()
│   ├── views/
│   │   ├── __init__.py
│   │   ├── base.py                 # fragments de pages
│   │   ├── ajax_actions.py         # POST création ticket (étudiant)
│   │   ├── student_dashboard.py    # flux étudiant (select_related, badges, collapse)
│   │   ├── teacher_dashboard.py    # boîte enseignant (inbox + détail + téléchargement)
│   │   └── status_processor.py     # POST résolution (Valider/Rejeter) + contrôle 403
│   ├── consumers.py                # TicketConsumer(AsyncWebsocketConsumer)
│   ├── signals.py                  # post_save(Ticket) → broadcast Channels
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── test_models.py          # index, enum statuts, contraintes FK
│   │   ├── test_ticket_creator.py  # pièces manquantes, atomicité, résolution enseignant
│   │   ├── test_status_processor.py# transitions invalides, rejection_reason requis
│   │   └── test_permissions.py     # tentatives IDOR → 403
│   └── urls.py                     # app_name = "tickets"
│
├── templates/
│   ├── base.html                   # squelette SPA : i18n, #master-modal, #global-toaster, scripts
│   ├── landing/index.html          # hero minimal + bouton [Se connecter]
│   ├── dashboard/
│   │   └── index.html              # coque SPA : header, #spa-viewport, bottom-nav, squelette de chargement
│   ├── components/                 # fragments réutilisables (cards, badges, nav, skeletons)
│   │   ├── bottom_nav.html
│   │   ├── status_badge.html
│   │   ├── ticket_card_student.html
│   │   ├── ticket_card_teacher.html
│   │   └── skeleton_list.html
│   ├── partials/                   # fragments servis en AJAX (injectés dans #spa-viewport)
│   │   ├── student_feed.html
│   │   ├── student_profile.html
│   │   ├── teacher_inbox.html
│   │   ├── teacher_ticket_detail.html
│   │   └── admin_metrics.html
│   ├── modals/                     # fragments injectés dans #master-modal
│   │   ├── login.html
│   │   ├── student_request_form.html
│   │   ├── teacher_decision.html
│   │   ├── admin_import.html
│   │   └── onboarding_profile.html
│   └── errors/{403,404,500}.html
│
├── static/
│   ├── css/
│   │   ├── input.css               # @tailwind base/components/utilities + @layer components
│   │   └── output.css              # build compilé minifié (généré, lié par les templates)
│   ├── fonts/                      # Inter auto-hébergé (woff2, licence OFL)
│   ├── js/
│   │   ├── app_spa.js              # noyau : CSRF, modal (translate-y), toaster, swap de fragments
│   │   ├── auth_handler.js         # login/logout via fetch
│   │   ├── ticket_form_dynamic.js  # fetchFormConfiguration() + injection des uploads dynamiques
│   │   ├── ticket_lifecycle.js     # RECEIVED/PROCESSING/RESOLVED/REJECTED côté enseignant
│   │   └── websocket_listener.js   # new WebSocket(), patch des cards, navigator.vibrate
│   ├── icons/                      # icônes PWA 192/512/maskable
│   ├── manifest.json               # PWA manifest
│   └── service-worker.js           # cache shell + Network-First sur les données
│
├── media/tickets/attachments/YYYY/MM/DD/   # uploads (gitignoré)
├── docs/
│   ├── ARCHITECTURE.md             # ← ce document
│   └── ROADMAP.md                  # plan de bataille par phases + matrice de traçabilité
└── design-system/
    └── MASTER.md                   # tokens, composants, règles d'accessibilité
```

**Règle d'isolation** : une app ne doit jamais importer un `views/` d'une autre app.
Les croisements se font uniquement par les modèles (`accounts.models.Student`, etc.)
et par les services quand la logique métier est transversale.

---

## 5. Spécification `core/settings.py` (fichier unique)

> Décision utilisateur : **un seul `settings.py`**, pas de package `settings/`.
> Tous les basculements (dev/prod) se font par variables d'environnement (`.env`).

### 5.1 `INSTALLED_APPS` (ordre exact)

```python
INSTALLED_APPS = [
    # Serveur ASGI de développement (Daphne en tête → `runserver` supporte
    # les WebSockets dès la Phase 8)
    "daphne",
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Tierces
    "channels",
    # Métier (ordre : accounts d'abord, il est référencé par les autres)
    "accounts",
    "core_scolarite",
    "tickets",
]
```

### 5.2 Middleware (ordre exact, routage des requêtes)

```python
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",        # static en prod
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
```

### 5.3 Cœur de configuration (valeurs à respecter)

> Implémentation : `config()` de **python-decouple** (priorité : variables système > `.env`),
> helper `Csv()` pour les listes, `cast=bool` pour les booléens.

```python
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = env("SECRET_KEY", default="dev-insecure-change-me")   # obligatoire en prod
DEBUG = env.bool("DEBUG", default=True)                            # False exigé en prod
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# ── Base de données ──────────────────────────────────────────────
# DEV (défaut) : SQLite → zéro configuration, fichier db.sqlite3 à la racine.
# PROD  : poser DB_ENGINE=postgresql (+ DB_*) dans le .env → bascule automatique.
if env("DB_ENGINE", default="sqlite") == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DB_NAME", default="univreq"),
            "USER": env("DB_USER", default="postgres"),
            "PASSWORD": env("DB_PASSWORD", default=""),
            "HOST": env("DB_HOST", default="127.0.0.1"),
            "PORT": env("DB_PORT", default="5432"),
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3",
                             "NAME": BASE_DIR / "db.sqlite3"}}

# ── ASGI / Real-time ──
ASGI_APPLICATION = "core.asgi.application"
# DEV : InMemoryChannelLayer (aucun service requis) ; PROD : Redis via REDIS_URL
if env.bool("USE_REDIS_CHANNEL_LAYER", default=not DEBUG):
    CHANNEL_LAYERS = {"default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [env("REDIS_URL", default="redis://127.0.0.1:6379/0")]}}}
else:
    CHANNEL_LAYERS = {"default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer"}}

# ── Sessions / CSRF (SPA AJAX) ──
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14     # 14 jours (usage mobile)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False               # JS doit lire le cookie pour le header X-CSRFToken
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# ── Frontière des uploads multi-part ──
DATA_UPLOAD_MAX_MEMORY_SIZE = 15 * 1024 * 1024       # 15 Mo max par requête
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024       # 10 Mo max par fichier en RAM
DATA_UPLOAD_MAX_NUMBER_FIELDS = 30                   # garde-fou formulaire dynamique
DEFAULT_FILE_STORAGE rules → STORAGES["default"] = FileSystemStorage(loc MEDIA_ROOT)
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"

# ── Frontière des uploads ──
ALLOWED_UPLOAD_EXTENSIONS = ["pdf", "png", "jpg", "jpeg", "webp"]
MAX_UPLOAD_SIZE = 8 * 1024 * 1024                    # 8 Mo par fichier (validation applicative)

# ── Static ──
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"                # collectstatic (prod)
STORAGES = {"staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage", ...}}

# ── Templates ──
TEMPLATES[0]["DIRS"] = [BASE_DIR / "templates"]
APP_DIRS = True
CONTEXT_PROCESSORS ajoute "django.template.context_processors.request"

# ── i18n (sans LocaleMiddleware pour l'instant) ──
LANGUAGE_CODE = "fr"
USE_I18N = True
USE_TZ = True
```

### 5.4 `core/asgi.py`

```python
ProtocolTypeRouter({
    "http": get_asgi_application(),                  # Django HTTP classique
    "websocket": AuthMiddlewareStack(URLRouter(core.routing.websocket_urlpatterns)),
})
```

### 5.5 `core/routing.py`

```python
websocket_urlpatterns = [path("ws/tickets/", consumers.TicketConsumer.as_asgi())]
```

### 5.6 `core/urls.py` (routage racine)

```python
urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("scolarite/", include("core_scolarite.urls")),
    path("tickets/", include("tickets.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)  # dev uniquement
```

---

## 6. Modèle de données (schéma définitif)

> **Décision PK — UUID (mise à jour)** : tous les modèles métier héritent de
> `core.models.UUIDModel` (`id = UUIDField(primary_key=True, default=uuid.uuid4, editable=False)`).
> Les identifiants ne sont donc plus des entiers auto-incrémentés : les routes Django use
> `<uuid:pk>` et les payloads AJAX transportent des UUID. Avantage : identifiants non
> devinables côté client (défense IDOR renforcée). Les FK entre apps restent des `ForeignKey`
> vers ces UUID. La règle §6.1/6.2/6.3 sur les champs et index reste inchangée ; seul le type
> de PK change.

### 6.1 `accounts/models.py`

```
Faculty
  name            CharField(150, unique=True)
  → Meta: verbose_name_plural = "Faculties"

Department
  faculty         FK Faculty, on_delete=CASCADE, related_name="departments"
  name            CharField(150)
  → Meta: unique_together = ("faculty", "name")
  → Meta.indexes: Index(fields=["faculty", "name"])

Student
  user                OneToOneField(User, CASCADE, related_name="student_profile")
  registration_number CharField(50, unique=True)          # MATRICULE
  faculty             FK Faculty, PROTECT, related_name="students"   → null=True (mode MVP)
  department          FK Department, PROTECT, related_name="students" → null=True (mode MVP)
  → Meta.indexes: Index(fields=["registration_number"])
  → décorateur property: is_onboarded → faculty_id is not None and department_id is not None

Teacher
  user    OneToOneField(User, CASCADE, related_name="teacher_profile")
  title   CharField(5, choices=DR/PR/MR/MME, default="MR")
  faculty FK Faculty, PROTECT, related_name="teachers"
  department FK Department, PROTECT, related_name="teachers"
  → Meta.indexes: Index(fields=["department"])
```

> **Décision** : `faculty`/`department` de `Student` sont `null=True` pour supporter le
> **Cas A (MVP onboarding déclaratif)**. En mode **Cas B (LDAP/API)**, l'import/synchronisation
> les renseigne et l'écran d'onboarding disparaît automatiquement (le code teste `is_onboarded`).
> `Teacher` reste non-null (provisionné par l'admin).
>
> **Décision login** : `User.username = MATRICULE` pour les deux rôles. Le formulaire de
> connexion demande « Matricule + Mot de passe » et utilise `authenticate(username=matricule, ...)`.

### 6.2 `core_scolarite/models.py`

```
Course
  code                CharField(20, unique=True)
  name                CharField(150)
  department          FK Department, CASCADE, related_name="courses"
  primary_instructor  FK Teacher, SET_NULL, null=True, related_name="courses"
  → Meta.indexes: Index(fields=["department"])

ProblemType
  name            CharField(100, unique=True)
  description     TextField(blank=True)                  # instructions affichées à l'étudiant
  requires_course BooleanField(default=True)
  → seed : "Note manquante", "Double correction", "Absence justifiée", …

AttachmentConfig
  problem_type  FK ProblemType, CASCADE, related_name="required_attachments"
  label         CharField(150)       # ex. "Résultat du portail", "Justificatif médical"
  is_required   BooleanField(default=True)
```

### 6.3 `tickets/models.py`

```
Ticket
  id                Auto PK
  student           FK Student, CASCADE, related_name="tickets"
  teacher           FK Teacher, PROTECT, related_name="tickets"
  course            FK Course, PROTECT, null=True, blank=True, related_name="tickets"
  problem_type      FK ProblemType, PROTECT, related_name="tickets"
  description       TextField()                          # commentaires de l'étudiant
  status            CharField(15, choices, default="SENT")
  rejection_reason  TextField(null=True, blank=True)     # obligatoire si status == REJECTED
  created_at        DateTimeField(auto_now_add=True)
  updated_at        DateTimeField(auto_now=True)
  received_at       DateTimeField(null=True)             # + reçu : horodatage pour l'analytique
  resolved_at       DateTimeField(null=True)             # + terminé : calcul du temps de réponse
  → Meta:
      ordering = ["-created_at"]
      indexes = [
        Index(fields=["student", "status"]),
        Index(fields=["teacher", "status"]),
        Index(fields=["status", "created_at"]),          # liste admin / analytics
      ]
      constraints = [
        CheckConstraint(Q(status != "REJECTED") | Q(rejection_reason__isnull=False) & ~Q(rejection_reason=""),
                        name="ticket_rejection_reason_required"),
      ]

STATUS_CHOICES (clé stockée en anglais, label traduit en français) :
  SENT      → "Envoyé"
  RECEIVED  → "Reçu"
  PROCESSING→ "En cours"
  RESOLVED  → "Résolu"
  REJECTED  → "Rejeté"

TicketAttachment
  ticket  FK Ticket, CASCADE, related_name="attachments"
  config  FK AttachmentConfig, PROTECT
  file    FileField(upload_to="tickets/attachments/%Y/%m/%d/")
```

> Les champs `received_at` / `resolved_at` sont le **seul enrichissement** au-delà du brief :
> sans eux, le « temps de réponse moyen par faculté » de la Phase 7 serait impossible à calculer
> de façon fiable (`updated_at` change à chaque mutation).

### 6.4 Définition de la machine à états (`tickets/services/status_machine.py`)

```
ALLOWED_TRANSITIONS = {
    "SENT":       ["RECEIVED"],
    "RECEIVED":   ["PROCESSING"],
    "PROCESSING": ["RESOLVED", "REJECTED"],
    "RESOLVED":   [],
    "REJECTED":   [],
}
```

- `SENT → RECEIVED` : automatique à l'ouverture du détail côté enseignant.
- `RECEIVED → PROCESSING` : bouton « Démarrer l'analyse ».
- `PROCESSING → RESOLVED` : bouton [Valider].
- `PROCESSING → REJECTED` : bouton [Rejeter] + `rejection_reason` non vide (validé 2× :
  vue + contrainte `CheckConstraint` DB).
- Toute transition hors table → erreur `400` JSON.
- Chaque application passe par `apply_status(ticket, new_status, reason=None)` :
  pose `received_at`/`resolved_at`, sauvegarde, déclenche le signal de broadcast.

---

## 7. Cartographie des endpoints

Toutes les réponses AJAX sont du JSON ; les vues de fragments renvoient du HTML partielle.
Toute route `ajax_*` exige `@login_requireer_view` + contrôle de rôle + CSRF (POST).

### 7.1 accounts (namespace `accounts:`)

| # | Méthode | Route | Accès | Payload → Réponse |
|---|---|---|---|---|
| 1 | GET | `/` | anonyme | → `landing/index.html` |
| 2 | POST | `/accounts/login/` | anonyme | `{matricule, password}` → `200 {status:success, next}` \| `400 {status:error, message}` |
| 3 | POST | `/accounts/logout/` | connecté | → `200 {status:success}` |
| 4 | GET | `/dashboard/` | connecté | → coque SPA `dashboard/index.html` (contenu selon rôle) |
| 5 | GET | `/accounts/ajax/departments/` | connecté | `?faculty_id=` → `200 [{id, name}]` |
| 6 | POST | `/accounts/ajax/onboarding/` | étudiant | `{faculty_id, department_id}` → `200 {status:success}` (bind sur `request.user.student_profile`) |
| 7 | GET | `/accounts/profile/` | connecté | → fragment profil (inclut le bandeau « mot de passe géré par le portail central ») |

### 7.2 core_scolarite (namespace `core_scolarite:`)

| # | Méthode | Route | Accès | Payload → Réponse |
|---|---|---|---|---|
| 8 | GET | `/scolarite/ajax/form-config/` | étudiant | `?problem_type_id=` → `200 {requires_course, courses:[{id,code,name}], teachers:[{id,label}], attachments:[{id,label,is_required}]}` — **`.values()` uniquement, cible < 10 ms** |
| 9 | GET | `/scolarite/admin/import/` | superuser | → fragment `modals/admin_import.html` |
| 10 | POST | `/scolarite/admin/import/upload/` | superuser | multipart `{file, entity: students\|teachers, strict_placement}` → `200 {status:success, imported_count}` \| `400 {status:error, errors:[{line, message}]}` |
| 11 | GET | `/scolarite/admin/analytics/` | superuser | → fragment `partials/admin_metrics.html` |
| 12 | GET | `/scolarite/ajax/problem-types/` | étudiant/enseignant | → `200 [{id, name, requires_course}]` |

### 7.3 tickets (namespace `tickets:`)

| # | Méthode | Route | Accès | Payload → Réponse |
|---|---|---|---|---|
| 13 | GET | `/tickets/` | étudiant | → fragment `partials/student_feed.html` (cartes + badges + collapse rejet) |
| 14 | POST | `/tickets/ajax/create/` | étudiant | multipart FormData (description, problem_type_id, course_id?, teacher_id?, files[nom_piece]) → **`201 {status:success, message}`** \| **`400 {status:error, message}`** |
| 15 | GET | `/tickets/teacher/` | enseignant | → fragment `partials/teacher_inbox.html` (tri chronologique, priorité aux non traités) |
| 16 | GET | `/tickets/<int:pk>/detail/` | propriétaire* | → fragment `partials/teacher_ticket_detail.html` — *étudiant propriétaire OU enseignant assigné, sinon **403** |
| 17 | POST | `/tickets/ajax/status/` | enseignant | `{ticket_id, status, rejection_reason?}` → `200 {status:success, ticket:{id,status,status_label}}` \| `403` (mauvais enseignant) \| `400` (transition invalide / motif manquant) |
| 18 | GET | `/media/...` → **vue dédiée de téléchargement** | propriétaire* | contrôle d'appartenance avant envoi du fichier (voir §9.4) |

### 7.4 WebSocket

| Route | Consumer | Groupes |
|---|---|---|
| `ws://<host>/ws/tickets/` | `tickets.consumers.TicketConsumer` | `user_{user_id}` (étudiant et enseignant) |

Format de l'événement diffusé par `tickets/signals.py` :

```json
{
  "type": "ticket.status.changed",
  "ticket_id": 42,
  "status": "PROCESSING",
  "status_label": "En cours",
  "rejection_reason": null,
  "actor": "teacher",
  "card_html": "<article …>…</article>"
}
```

`card_html` est rendu côté serveur depuis `components/ticket_card_student.html` pour que le
client remplace la carte sans requête supplémentaire ; si le fragment est trop lourd, le client
retombe sur le patch des attributs `data-ticket-id` / `data-status`.

---

## 8. Logique métier (couche services)

### 8.1 `core_scolarite/services/data_importer.py`

```python
REQUIRED_HEADERS = ["MATRICULE", "NOM", "PRENOM", "EMAIL", "FACULTE", "DEPARTEMENT"]

def import_users(file, entity: Literal["students", "teachers"], strict_placement: bool = True) -> int
```

Algorithme :
1. Détection du format (`.csv` → `csv.DictReader` avec `utf-8-sig`; `.xlsx` → `openpyxl` read-only).
2. **Vérification des en-têtes** : les 6 tokens doivent exister sur la ligne 1 (insensible à la
   casse/espaces). Manquant → `ImportValidationError("La colonne EMAIL est manquante…")` avant toute écriture.
3. Pré-fetch de toutes les `Faculty` et `(faculty, department)` en mémoire (2 requêtes, pas de N+1).
4. Pour chaque ligne (numéro de ligne = index réel dans le fichier, ligne 1 = en-têtes) :
   - champs requis non vides → sinon erreur `{line, message}`;
   - `MATRICULE` déjà existant en base → erreur de doublon;
   - `FACULTE` inexistante → erreur ;
   - `DEPARTEMENT` non rattaché à cette faculté → erreur ;
   - `strict_placement=False` (mode MVP) : faculté/département vides **autorisés** → profil non onboardé ;
   - collecte des erreurs ligne par ligne (on collecte toutes les erreurs du fichier pour les
     renvoyer d'un bloc à l'admin, mais une erreur = échec global).
5. **`transaction.atomic()`** englobant la boucle complète : la moindre erreur lève
   `ImportValidationError(errors)` → **rollback total**, zéro enregistrement partiel.
6. Création `User(username=MATRICULE, first_name=PRENOM, last_name=NOM, email=EMAIL)` + profil
   (`set_password(mot_de_passe_temporaire)`), `imported_count` retourné si tout est valide.

### 8.2 `tickets/services/ticket_creator.py`

```python
def create_student_ticket(student_profile, course_id, problem_type_id,
                          description, uploaded_files_dict) -> Ticket
```

1. Charger `ProblemType` ; si `requires_course` → `course_id` obligatoire et
   `course.department_id == student_profile.department_id` (sinon erreur).
2. Résoudre l'enseignant :
   - `requires_course=True` → `course.primary_instructor` (sinon erreur « Aucun enseignant assigné ») ;
   - `requires_course=False` → `teacher_id` fourni par le formulaire (liste déjà filtrée par
     le endpoint `form-config` sur le département de l'étudiant).
3. Vérifier `AttachmentConfig` : pour chaque config `is_required=True`, la clé correspondante
   doit exister dans `uploaded_files_dict` → sinon `TicketCreationError` listant les pièces manquantes.
4. Valider type/taille de chaque fichier (whitelist d'extensions, 8 Mo max).
5. Dans `transaction.atomic()` : créer le `Ticket` (statut `SENT`), créer les `TicketAttachment`
   et persister les fichiers. Échec fichier n°2 → rollback DB (les fichiers déjà écrits sur disque
   sont supprimés en `except` pour éviter les orphelins).
6. Le `post_save` de `Ticket` (signal) déclenche le broadcast vers `teacher_{id}` + `student_{id}`.

### 8.3 Sélection dynamique (`ajax_selectors.py`)

```
GET /scolarite/ajax/form-config/?problem_type_id=3   (étudiant)
→ student = request.user.student_profile            # jamais d'ID client
→ pt = ProblemType.objects.only("requires_course").get(pk=...)   # 404 → 400 JSON
→ courses = Course.objects.filter(department=student.department_id)
             .values("id", "code", "name")                          # pas d'objet complet
→ teachers = Teacher.objects.filter(department=student.department_id)
              .values("id", "title", "user__first_name", "user__last_name")
→ attachments = pt.required_attachments.values("id", "label", "is_required")
→ 200 JsonResponse({...})
```

---

## 9. Sécurité

### 9.1 Défense IDOR (règle absolue)
- Aucune vue ne lit `request.POST["student_id"]` / `registration_number`.
- Liaison systématique : `student = request.user.student_profile`,
  `teacher = request.user.teacher_profile` (`ObjectDoesNotExist` → redirect profil).
- Sur toute ressource `pk` : vérification d'appartenance **avant** toute donnée retournée ;
  échec → **`JsonResponse(..., status=403)`** (jamais de 200 partiel).
- Tests dédiés dans `tickets/tests/test_permissions.py` (étudiant A lit la carte de B → 403).

### 9.2 Authentification & mots de passe
- `POST /accounts/login/` : rate-limit simple (session-based, 5 tentatives / 5 min),
  message d'erreur identique que le matricule existe ou non.
- Aucun écran de changement de mot de passe ; bandeau fixe :
  « La gestion des identifiants est centralisée. Pour modifier vos accès, rendez-vous sur le
  portail informatique de l'université. »
- MVP : mot de passe temporaire à l'import (règle documentée, jamais de secret en dur dans le
  dépôt — générée depuis `.env` : `IMPORT_DEFAULT_PASSWORD_PATTERN`).
- Production : bascule LDAP/AD en remplaçant le backend d'authentification (`AUTHENTICATION_BACKENDS`).

### 9.3 CSRF & headers
- Tous les POST AJAX passent par le helper de `app_spa.js` qui lit le cookie `csrftoken`
  et pose `X-CSRFToken` (+ `X-Requested-With: XMLHttpRequest`).
- `SESSION_COOKIE_HTTPONLY=True`, `X_FRAME_OPTIONS=DENY`, `SECURE_BROWSER_XSS_FILTER`
  (dev), HSTS/cookies `secure` activés uniquement quand `DEBUG=False` + `SECURE_SSL_REDIRECT`
  posé par le `.env` de production (après vérif du TLS).

### 9.4 Fichiers (untrusted)
- Validation applicative : extension whitelist + `content_type` + taille ≤ 8 Mo.
- Stockage sous `media/tickets/attachments/%Y/%m/%d/` avec nom généré (UUID) :
  aucun nom de fichier client n'atteint le système de fichiers.
- **Service privé** : les pièces jointes ne sont pas servies en statique publique ;
  une vue de téléchargement vérifie « étudiant propriétaire ou enseignant assigné » puis
  renvoie le fichier (`FileResponse`, `X-Content-Type-Options: nosniff`).
  En production, remplacer par `X-Accel-Redirect` (nginx) sans changer la vue.

### 9.5 Validation & robustesse
- `JsonResponse` d'erreur systématique : `{status: "error", message: "..."}`
  (messages traduits, jamais de stack trace, jamais de détail SQL).
- `404` sur ressource inconnue en JSON pour les routes AJAX (pas de page HTML dans une modale).
- Templates : autoescape actif ; `|safe` interdit sauf snippet déjà échappé côté serveur.

### 9.6 Production
- `DEBUG=False`, `SECRET_KEY` et identifiants 100 % environnement,
  `python manage.py check --deploy` exécuté avant livraison (voir `CHECKLIST.md`).

---

## 10. Temps réel (Django Channels)

1. `core/asgi.py` : `AuthMiddlewareStack` injecte `scope["user"]` (session DB) sur le WebSocket.
2. `TicketConsumer` :
   - `connect()` : utilisateur anonyme → `close(4401)` ; sinon
     `self.group_name = f"user_{user.id}"` → `channel_layer.group_add(...)`, `accept()`.
   - `ticket_status_changed(event)` : `self.send(text_data=json.dumps(event["message"]))`.
3. `tickets/signals.py` :
   - `@receiver(post_save, sender=Ticket)` ;
   - détecte les champs critiques (`status`, création) via `update_fields` / `old_status` ;
   - identifie `ticket.student.user_id` et `ticket.teacher.user_id` ;
   - `async_to_sync(channel_layer.group_send)(f"user_{uid}", {"type": "ticket.status.changed", "message": payload})`.
4. Côté client (`websocket_listener.js`) :
   - `new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/tickets/")`
     au `DOMContentLoaded` ;
   - reconnexion avec backoff exponentiel (1 s → 30 s) ;
   - `onmessage` → patch de la carte `[data-ticket-id="…"]` (texte + classes de badge),
     `navigator.vibrate(50)` si supporté, `showNotification()` (toaster) ;
   - `prefers-reduced-motion` respecté : pas d'animation de transition sur le badge.

---

## 11. Frontend

### 11.1 Contrat SPA (`static/js/app_spa.js`)
- `openMasterModal(title)` / `closeMasterModal()` : overlay `hidden` + `opacity`,
  panneau `translate-y-full → translate-y-0` (300 ms), fermeture `Escape` + clic backdrop,
  `role="dialog" aria-modal="true"` + focus trap.
- `showModalSkeleton()` : bloc `animate-pulse bg-slate-200` injecté **avant** tout `fetch`.
- `loadFragment(url, target)` : `e.preventDefault()` → skeleton → `fetch` → injection HTML dans
  `#spa-viewport` ou `#modal-body` → `history.pushState` → aucun `location.href`.
- `showNotification(message, kind)` : toaster `#global-toaster`, variantes success/error,
  auto-dismiss 3–5 s, `aria-live="polite"`.

### 11.2 Modules JS (un fichier = un problème)

| Fichier | Responsabilité | Déclencheurs |
|---|---|---|
| `app_spa.js` | CSRF, modal, toaster, swap de fragments, router léger | chargement global |
| `auth_handler.js` | submit login/logout en `async/await fetch`, états loading | `submit` du formulaire de login |
| `ticket_form_dynamic.js` | `fetchFormConfiguration(problemTypeId)` : cascade matière/enseignant + injection `<input type="file">` étiquetés (`*` si requis) | `change` du `select#problem_type` |
| `ticket_lifecycle.js` | envoi `FormData` multipart, validation JS de présence des pièces, boutons enseignant + modale de décision | `submit`, clics [Valider]/[Rejeter]/[Démarrer] |
| `websocket_listener.js` | connexion WS, patch des cartes, vibration, toaster | `DOMContentLoaded`, `onmessage` |

Toutes les fonctions : `async/await`, états loading (boutons `disabled` + skeleton),
réponses routeées vers `showNotification()`.

### 11.3 Templates
- `base.html` : `{% load i18n %}`, blocs `{% trans %}` partout, `#master-modal`,
  `#global-toaster`, `<link output.css>`, scripts dans l'ordre
  (`app_spa.js` → modules → `service-worker.js`).
- Sémantique : `<header>`, `<main>`, `<nav aria-label>`, `<article>` pour les cartes,
  `<button>` pour les actions (jamais `<div onclick>`), viewport `width=device-width, initial-scale=1`,
  `pb-24` sur le `<main>` pour dégager la bottom-nav fixe.

### 11.4 PWA
- `static/manifest.json` : `name`, `short_name: "UnivReq"`, `orientation: "portrait"`,
  `theme_color: "#1E3A8A"`, `background_color: "#F8FAFC"`, `display: "standalone"`,
  icônes 192/512 + `maskable`.
- `static/service-worker.js` :
  - `install` : précache du shell (`output.css`, `app_spa.js`, icônes) + `skipWaiting` ;
  - `activate` : purge des anciennes versions de cache ;
  - stratégie **Cache-First** pour les assets statiques (CSS/JS/fonts/icônes) ;
  - stratégie **Network-First, Cache-Fallback** pour les endpoints dashboard
    (`/tickets/`, `/tickets/teacher/`, `/scolarite/admin/analytics/`) ;
  - jamais de cache des POST AJAX ni des WebSockets.

---

## 12. Performance & observabilité

- Index composites listés en §6 (objectifs : dashboards < 5 ms, `form-config` < 10 ms,
  mesurés avec `EXPLAIN ANALYZE` en Phase 11, pas déclarés sans mesure).
- `select_related("course", "problem_type", "student__user")` sur les flux (anti N+1).
- `.values()` / `.only()` sur les endpoints JSON.
- Pagination des flux à 20 éléments (`Paginator`), rendu côté serveur.
- `CONN_MAX_AGE=60`, pas de requête dans les boucles de template (les badges utilisent une
  template tag/mixin pré-calculée).

---

## 13. Stratégie de tests

| App | Tests |
|---|---|
| `accounts` | unicité Faculty/Department, cascade Faculty→Department, `is_onboarded`, login matricule, onboarding ne touche qu'à `request.user` (IDOR) |
| `core_scolarite` | headers manquants → exception, département mal rattaché → erreur ligne N, rollback complet (fichier valide + 1 ligne cassée → 0 enregistrement), refus non-superuser, endpoint `form-config` filtré par département de l'étudiant |
| `tickets` | enum + index, `create_student_ticket` (pièce manquante → exception, enseignant résolu via `primary_instructor`), transitions invalides, `rejection_reason` requis, **403 IDOR** création/vues/statut |

Commandes de vérification (exécutées et rapportées à chaque fin de phase, jamais affirmées) :

```
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test
npm run build && git diff --exit-code static/css/output.css   # build reproductible
uv run python manage.py check --deploy   # avec DEBUG=False et les variables de prod (Phase 11)
```

---

## 14. Matrice de traçabilité (brief → phase)

| Brief (prompt) | Phase |
|---|---|
| Prompt 1/2 — Design system, tailwind.config.js, composants atomiques | P2 |
| Prompt 2/1 — Arborescence, settings, INSTALLED_APPS, middleware, urls | P1 |
| Prompt 3/3 — base.html, dashboard/index.html, modal, toaster, skeleton | P2 |
| Prompt 4/5 — Modèles accounts + index composites | P3 |
| Prompt 5/5 — Modèles core_scolarite (Course, ProblemType, AttachmentConfig) | P3 |
| Prompt 6/5 — Modèles tickets + enum statuts + index (student,status)/(teacher,status) | P3 |
| Prompt 7/4 — Service ETL strict + `transaction.atomic` | P5 |
| Prompt 8 — Vue admin import + rapports d'exception JSON | P5 |
| Prompt 9 — Endpoint `form-config` cascade | P6 |
| Prompt 10 — `fetchFormConfiguration()` + uploads dynamiques | P6 |
| Prompt 11 — `create_student_ticket()` transactionnel | P6 |
| Prompt 12 — Endpoint création ticket (POST, IDOR-proof, 201/400) | P6 |
| Prompt 13 — Flux étudiant (cards, badges, collapse rejet) | P7 |
| Prompt 14 — Boîte enseignant (inbox, détail, Valider/Rejeter) | P7 |
| Prompt 15 — Processeur de statut (403, validation motif) | P7 |
| Prompt 16 — `TicketConsumer` WebSocket | P8 |
| Prompt 17 — Signal `post_save` + broadcast | P8 |
| Prompt 18 — Client WS + vibration + toaster | P8 |
| Prompt 19 — `manifest.json` + `service-worker.js` | P9 |
| Prompt 20 — Métriques super-admin + dashboard analytique | P10 |
| Landing minimaliste + login modal (prompt « Landing ») | P2/P4 |
| Pipeline CSS input.css/output.css (prompt « CSS Management ») | P1/P2 |
| JS modulaire par problème (prompt « Modular JS Architecture ») | P2 (squelette) → P4-P8 (contenu) |
| Cas MVP onboarding vs Cas production LDAP (§ scénarios) | P4 (MVP), P11 (doc bascule LDAP) |
| Gestion mots de passe bloquée + import manuel/masse admin | P5 |
