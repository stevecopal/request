/* eslint-env serviceworker */
/**
 * service-worker.js — UnivReq PWA (ARCHITECTURE §11.4, Prompt 19).
 *
 *  - install  : précache du shell applicatif, activation immédiate ;
 *  - activate : purge des anciennes versions de cache ;
 *  - fetch    : Cache-First pour les assets statiques, Network-First
 *               (repli cache) pour les endpoints de données du dashboard ;
 *               jamais de cache pour les POST ni les WebSockets.
 */
const VERSION = "univreq-v1";
const SHELL_CACHE = `${VERSION}-shell`;
const RUNTIME_CACHE = `${VERSION}-runtime`;

const SHELL_ASSETS = [
  "/static/css/output.css",
  "/static/js/app_spa.js",
  "/static/js/auth_handler.js",
  "/static/js/ticket_form_dynamic.js",
  "/static/js/ticket_lifecycle.js",
  "/static/js/websocket_listener.js",
  "/static/icons/icon-192.png",
];

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

function isStaticAsset(url) {
  return (
    url.pathname.startsWith("/static/") &&
    /\.(css|js|png|jpg|jpeg|svg|webp|woff2?|ico)$/.test(url.pathname)
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

  if (isStaticAsset(url)) {
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
