# UnivReq — Déploiement production (Docker + Caddy)

Stack : **Docker multi-étage** (Tailwind → uv → runtime) + **Gunicorn/uvicorn
(ASGI, WebSockets inclus)** + **PostgreSQL 16** + **Redis 7**, derrière
**Caddy** en reverse-proxy sur le VPS. Chaque service est isolé (préfixe
`univreq`, réseau interne dédié, base PostgreSQL conteneurisée) pour cohabiter
avec d'autres applications sur le même VPS.

## 1. Prérequis sur le VPS

- Docker ≥ 24 + plugin Compose v2
- Caddy déjà installé et fonctionnant (certificats TLS automatiques)
- Le domaine `univreq.example.com` (A/AAAA) pointé vers le VPS

## 2. Premier déploiement

```sh
git clone <repo> /opt/univreq && cd /opt/univreq

# Configuration (secrets + domaine) — jamais committée
cp .env.production.example .env
vim .env   # SECRET_KEY, DB_PASSWORD, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS

docker compose build          # build multi-étage (assets Tailwind inclus)
docker compose up -d          # db + redis + web (migrations & collectstatic auto)

docker compose logs -f web    # suivre le démarrage jusqu'à « Listening at »
```

L'`entry.sh` du conteneur `univreq_web` exécute à chaque démarrage :
permissions des volumes → attente de PostgreSQL → `collectstatic` (WhiteNoise)
→ `migrate` → lancement de gunicorn en non-root (`appuser`, uid 1000).

Création du super-admin (matricule `ADMIN001`) et jeu de données de démo :

```sh
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py seed_demo   # optionnel (démo UDS)
```

## 3. Caddy (reverse-proxy de l'hôte)

Ajouter au Caddyfile de l'hôte (`/etc/caddy/Caddyfile`) puis `caddy reload` :

```caddyfile
univreq.example.com {
    encode zstd gzip

    # Médias uploadés — servis depuis le bind mount ./data/media du projet
    handle_path /media/* {
        root * /opt/univreq/data/media
        file_server
        header Cache-Control "public, max-age=86400"
    }

    # Application (HTTP + WebSockets : Caddy gère l'upgrade nativement)
    handle {
        reverse_proxy http://127.0.0.1:8010
    }
}
```

Points clés :

- le port `8010` n'est publié que sur `127.0.0.1` → invisible depuis
  l'extérieur, aucun conflit avec les autres apps du VPS ;
- Caddy terminant le TLS, Django reçoit du HTTP derrière le proxy :
  `SECURE_PROXY_SSL_HEADER` est déjà actif (`DEBUG=False`) et
  `SECURE_SSL_REDIRECT=False` (redirection HTTP→HTTPS gérée par Caddy) ;
- si votre Caddy tourne lui aussi en conteneur, joignez-le au réseau externe
  et utilisez le nom de conteneur au lieu de `127.0.0.1`.

## 4. Statiques & médias

| Ressource | Stockage | Servi par |
|---|---|---|
| `/static/` (CSS/JS, **output.css compilé par Tailwind dans le build**) | volume `univreq_static` → `/app/staticfiles` | **WhiteNoise** dans le conteneur (en-têtes de cache + fichiers précompressés) |
| `/media/` (avatars, pièces jointes) | bind mount `./data/media` → `/app/media` | **Caddy** directement depuis le disque hôte |

`collectstatic` est rejoué à chaque démarrage du conteneur `web` : une simple
reconstruction de l'image suffit à publier un nouveau CSS/JS.

## 5. Commandes courantes

```sh
docker compose logs -f web            # logs applicatifs
docker compose up -d --build web      # nouvelle version (rebuild + restart)
docker compose exec web python manage.py shell   # shell Django
docker compose down                   # arrêt (les volumes persistent)
```

## 6. Sauvegarde / restauration

```sh
# Base PostgreSQL
docker compose exec db pg_dump -U univreq univreq | gzip > backup-$(date +%F).sql.gz
gunzip < backup-2026-01-01.sql.gz | docker compose exec -T db psql -U univreq univreq

# Médias
tar czf media-$(date +%F).tar.gz -C data media
```

## 7. Isolation multi-apps (résumé)

- `name: univreq` dans le compose → volumes (`univreq_pgdata`, …) et
  conteneurs préfixés, jamais partagés avec une autre stack ;
- réseau bridge `univreq-internal` : `db` et `redis` ne sont joignables que
  par `web` ;
- port publié en loopback uniquement (`127.0.0.1:8010`), choisissez-le dans
  `.env` (`UNIVREQ_HTTP_PORT`) pour éviter tout conflit ;
- PostgreSQL embarqué dans la stack : aucune dépendance au PostgreSQL hôte
  ni à celui des autres applications.

## 8. PWA (installabilité)

Le manifest est servi par Django sur `/manifest.json`
(`application/manifest+json`) et le service worker à `/` : avec le HTTPS de
Caddy, le bouton « Télécharger l'application » (installation automatique via
`beforeinstallprompt`) fonctionne en production dès le premier
chargement de la landing.
