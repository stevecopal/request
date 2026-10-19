"""
Django settings — UnivReq (Portail des Requêtes Universitaires).

Fichier unique (décision projet) : configuration via python-decouple.
`config()` lit, par ordre de priorité :
  1. les variables d'environnement système,
  2. le fichier `.env` à la racine du projet (voir `.env.example`).

- DEV  (défaut) : SQLite + channel layer in-memory, DEBUG=True.
- PROD          : DB_ENGINE=postgresql + USE_REDIS_CHANNEL_LAYER=True, DEBUG=False.
"""

from pathlib import Path

from decouple import Csv, config, UndefinedValueError
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
# Sécurité de base
# --------------------------------------------------------------------------- #
DEBUG = config("DEBUG", default=True, cast=bool)

try:
    SECRET_KEY = config("SECRET_KEY")
except UndefinedValueError:
    if DEBUG:
        SECRET_KEY = "django-insecure-dev-only-key-generate-a-real-one-in-prod"
    else:
        raise ImproperlyConfigured(
            "SECRET_KEY manquant : définissez-le dans le .env de production."
        )

ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS", default="localhost,127.0.0.1,[::1]", cast=Csv()
)
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())

# --------------------------------------------------------------------------- #
# Application
# --------------------------------------------------------------------------- #
INSTALLED_APPS = [
    # Serveur ASGI de développement : en premier pour que `runserver`
    # embarque Daphne (WebSocket inclus, Phase 8). Inoffensif en production.
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
    # Métier (ordre strict : accounts est référencé par les autres apps)
    "accounts",
    "core_scolarite",
    "tickets",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
            "OPTIONS": {
                "context_processors": [
                    "django.template.context_processors.request",
                    "django.contrib.auth.context_processors.auth",
                    "django.contrib.messages.context_processors.messages",
                    "core.context_processors.vapid_public_key",
                ],
            },
    },
]

WSGI_APPLICATION = "core.wsgi.application"
ASGI_APPLICATION = "core.asgi.application"

# --------------------------------------------------------------------------- #
# Base de données — DEV SQLite / PROD PostgreSQL (ARCHITECTURE §5.3)
# --------------------------------------------------------------------------- #
if config("DB_ENGINE", default="sqlite") == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": config("DB_NAME", default="univreq"),
            "USER": config("DB_USER", default="postgres"),
            "PASSWORD": config("DB_PASSWORD", default=""),
            "HOST": config("DB_HOST", default="127.0.0.1"),
            "PORT": config("DB_PORT", default="5432"),
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# --------------------------------------------------------------------------- #
# Temps réel (Django Channels) — InMemory en dev, Redis en prod
# --------------------------------------------------------------------------- #
if config("USE_REDIS_CHANNEL_LAYER", default=not DEBUG, cast=bool):
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [config("REDIS_URL", default="redis://127.0.0.1:6379/0")]},
        }
    }
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# --------------------------------------------------------------------------- #
# Authentification & mots de passe
# Login unique « Matricule + Mot de passe » : User.username = MATRICULE (§6.1).
# Aucun écran de changement de mot de passe dans l'application (§9.2).
# --------------------------------------------------------------------------- #
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Les redirections non-AJAX retournent vers la landing (page complète),
# jamais vers le fragment de modale.
LOGIN_URL = "accounts:landing"

# --------------------------------------------------------------------------- #
# Sessions & CSRF (SPA AJAX : JS lit le cookie csrftoken → header X-CSRFToken)
# --------------------------------------------------------------------------- #
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14  # 14 jours (usage mobile)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # le JS doit lire le cookie CSRF

# --------------------------------------------------------------------------- #
# Frontières des uploads multi-part (§5.3)
# --------------------------------------------------------------------------- #
DATA_UPLOAD_MAX_MEMORY_SIZE = 15 * 1024 * 1024       # 15 Mo max par requête
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024       # 10 Mo max par fichier en mémoire
DATA_UPLOAD_MAX_NUMBER_FIELDS = 30                   # garde-fou du formulaire dynamique

# Règles applicatives (validées dans le service de création de ticket, §9.4)
ALLOWED_UPLOAD_EXTENSIONS = ["pdf", "png", "jpg", "jpeg", "webp"]
MAX_UPLOAD_SIZE = 8 * 1024 * 1024                    # 8 Mo par fichier

# Mot de passe temporaire attribué à l'import ETL (jamais de secret en dur, §9.2)
IMPORT_DEFAULT_PASSWORD_PATTERN = config(
    "IMPORT_DEFAULT_PASSWORD_PATTERN", default="{matricule}Univ!{year}"
)

# Feature flag espace enseignant : demande d'informations complémentaires
# (transition MORE_INFO). Désactivable par environnement sans toucher au code.
ENABLE_TEACHER_MORE_INFO = config(
    "ENABLE_TEACHER_MORE_INFO", default=True, cast=bool
)

# --------------------------------------------------------------------------- #
# Web Push (notifications hors-page, distinctes des WebSockets) — §10
# Clés VAPID : si absentes, le push est désactivé proprement (best-effort).
# Génération : python -m py_vapid generate --applicationServerKey
# --------------------------------------------------------------------------- #
VAPID_PRIVATE_KEY = config("VAPID_PRIVATE_KEY", default="")
VAPID_PUBLIC_KEY = config("VAPID_PUBLIC_KEY", default="")
VAPID_CLAIM_EMAIL = config("VAPID_CLAIM_EMAIL", default="admin@univ.example")

# --------------------------------------------------------------------------- #
# Fichiers statiques & médias
# --------------------------------------------------------------------------- #
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# --------------------------------------------------------------------------- #
# Internationalisation — LocaleMiddleware volontairement absent (brief) ;
# tous les littéraux UI passent par {% trans %} / gettext_lazy (§2 décision 2).
# --------------------------------------------------------------------------- #
LANGUAGE_CODE = "fr"
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------- #
# Durcissement (actif quand DEBUG=False ; `manage.py check --deploy` en Phase 11)
# --------------------------------------------------------------------------- #
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = config("SECURE_COOKIES", default=True, cast=bool)
    CSRF_COOKIE_SECURE = config("SECURE_COOKIES", default=True, cast=bool)
    X_FRAME_OPTIONS = "DENY"
    SECURE_CONTENT_TYPE_NOSNIFF = True
    # True uniquement si TLS terminé derrière le reverse-proxy
    SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=False, cast=bool)

# --------------------------------------------------------------------------- #
# Journalisation console (aucun secret ni PII dans les logs — §9)
# --------------------------------------------------------------------------- #
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "%(levelname)s %(asctime)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
        # Erreurs/crítiques persistées en base (console C6 « Sécurité & audit »).
        "database": {
            "class": "core_scolarite.logging_handler.DatabaseLogHandler",
            "level": "ERROR",
            "formatter": "standard",
        },
    },
    "root": {
        "handlers": ["console", "database"],
        "level": config("LOG_LEVEL", default="INFO"),
    },
}
