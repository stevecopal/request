/* eslint-env serviceworker */
/**
 * service-worker.js — UnivReq PWA (ARCHITECTURE §11.4, Prompt 19).
 *
 * Stratégie volontairement minimale : on ne met en cache que ce qui sert
 * réellement au PWA hors-ligne (icônes + manifeste). Les assets de code
 * (CSS et JS) ne sont JAMAIS mis en cache — le navigateur les récupère
 * toujours frais auprès du serveur, ce qui évite de servir une ancienne
 * feuille de style ou un ancien script après un déploiement.
 *
 *  - install  : précache des seules ressources PWA (icônes, manifeste) ;
 *  - activate : purge des anciennes versions de cache ;
 *  - fetch    : Cache-First pour les images/polices, Network-First (repli
 *               cache) pour les endpoints de données, jamais de cache pour
 *               le CSS/JS, les POST ni les WebSockets.
 */
const VERSION = "univreq-v5";
const SHELL_CACHE = `${VERSION}-shell`;
const RUNTIME_CACHE = `${VERSION}-runtime`;

/* Ressources strictement nécessaires au PWA hors-ligne. */
const SHELL_ASSETS = [
  "/static/manifest.json",
  "/static/icons/icon-192.png",
  "/static/icons/favicon.svg",
];

/* Endpoints de données du dashboard : Network-First (frais si en ligne). */
const NETWORK_FIRST_PATHS = [
  "/tickets/",
  "/tickets/accueil/",
  "/tickets/teacher/",
  "/accounts/notifications/",
  "/scolarite/admin/analytics/",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((key) => !key.startsWith(VERSION)).map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

/* Le code applicatif (CSS/JS) n'est jamais mis en cache : à chaque
   déploiement, le navigateur récupère la version fraîche. */
function isCodeAsset(url) {
  return (
    url.pathname.startsWith("/static/") &&
    /\.(css|js|mjs)$/.test(url.pathname)
  );
}

/* Images et polices : Cache-First (immuables, utiles hors-ligne). */
function isCacheableMedia(url) {
  return (
    url.pathname.startsWith("/static/") &&
    /\.(png|jpg|jpeg|svg|webp|gif|ico|woff2?|ttf)$/.test(url.pathname)
  );
}

function isNetworkFirst(url) {
  return NETWORK_FIRST_PATHS.some((path) => url.pathname === path);
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return; // jamais de cache pour les mutations
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // CSS/JS : laisser le navigateur gérer (aucune mise en cache).
  if (isCodeAsset(url)) return;

  if (isCacheableMedia(url)) {
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request).then((response) => {
            const copy = response.clone();
            caches.open(SHELL_CACHE).then((cache) => cache.put(request, copy));
            return response;
          })
      )
    );
    return;
  }

  if (isNetworkFirst(url)) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(RUNTIME_CACHE).then((cache) => cache.put(request, copy));
          return response;
        })
        .catch(() => caches.match(request))
    );
  }
});

/* ── Web Push : notifications hors-page (distinctes des WebSockets) ────── */

self.addEventListener("push", (event) => {
  let payload = { title: "UnivReq", body: "", tag: "univreq", url: "/dashboard/" };
  try {
    if (event.data) payload = Object.assign(payload, event.data.json());
  } catch (e) {
    if (event.data) payload.body = event.data.text();
  }
  event.waitUntil(
    self.registration.showNotification(payload.title || "UnivReq", {
      body: payload.body || "",
      tag: payload.tag || "univreq",
      icon: "/static/icons/icon-192.png",
      badge: "/static/icons/icon-192.png",
      data: { url: payload.url || "/dashboard/" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || "/dashboard/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ("focus" in client) return client.focus();
      }
      return self.clients.openWindow(targetUrl);
    })
  );
});
