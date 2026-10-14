/**
 * webpush.js — abonnement Web Push de l'appareil courant (UnivReq).
 *
 * - Lit la clé VAPID publique (meta tag) ; si absente → no-op silencieux.
 * - Si la permission est déjà accordée → abonnement automatique.
 * - Sinon → demande la permission au premier geste utilisateur (pas de
 *   prompt intempestif).
 * - L'abonnement est envoyé en POST JSON à /accounts/ajax/push/subscribe/
 *   avec le header X-CSRFToken. En cas de permission révoquée, l'ancien
 *   endpoint (localStorage) est désabonné proprement.
 */
(function () {
  "use strict";

  var api = window.UnivReq;
  var SUBSCRIBE_URL = "/accounts/ajax/push/subscribe/";
  var UNSUBSCRIBE_URL = "/accounts/ajax/push/unsubscribe/";
  var STORAGE_KEY = "univreq.push.endpoint";

  function urlBase64ToUint8Array(base64String) {
    var padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    var base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    var rawData = window.atob(base64);
    var outputArray = new Uint8Array(rawData.length);
    for (var i = 0; i < rawData.length; i++) outputArray[i] = rawData.charCodeAt(i);
    return outputArray;
  }

  function getVapidPublicKey() {
    var meta = document.querySelector('meta[name="vapid-public-key"]');
    return meta ? meta.getAttribute("content") : null;
  }

  function csrfToken() {
    return (api && api.getCookie && api.getCookie("csrftoken")) || "";
  }

  function postJson(url, body) {
    return fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
        "X-Requested-With": "XMLHttpRequest",
      },
      body: JSON.stringify(body),
      credentials: "same-origin",
    });
  }

  function unsubscribeStale() {
    var endpoint = null;
    try {
      endpoint = window.localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      /* stockage indisponible */
    }
    if (!endpoint) return;
    navigator.serviceWorker.ready
      .then(function (reg) {
        return reg.pushManager.getSubscription();
      })
      .then(function (subscription) {
        if (subscription) return null; // toujours actif
        return postJson(UNSUBSCRIBE_URL, { subscription: { endpoint: endpoint } });
      })
      .then(function () {
        try {
          window.localStorage.removeItem(STORAGE_KEY);
        } catch (e) {
          /* ignore */
        }
      })
      .catch(function () {});
  }

  function subscribe() {
    var publicKey = getVapidPublicKey();
    if (!publicKey || !("serviceWorker" in navigator) || !("PushManager" in window)) {
      return;
    }
    if (Notification.permission !== "granted") return;

    navigator.serviceWorker.ready
      .then(function (reg) {
        return reg.pushManager.getSubscription().then(function (existing) {
          if (existing) return existing;
          return reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(publicKey),
          });
        });
      })
      .then(function (subscription) {
        var endpoint = subscription.endpoint;
        try {
          window.localStorage.setItem(STORAGE_KEY, endpoint);
        } catch (e) {
          /* ignore */
        }
        return postJson(SUBSCRIBE_URL, { subscription: subscription.toJSON() });
      })
      .catch(function () {
        /* best-effort : jamais bloquant pour l'UX */
      });
  }

  function requestPermissionThenSubscribe() {
    if (Notification.permission !== "default") return;
    Notification.requestPermission().then(function (permission) {
      if (permission === "granted") subscribe();
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (!("Notification" in window) || !("serviceWorker" in navigator)) return;
    unsubscribeStale();
    if (Notification.permission === "granted") {
      subscribe();
    } else if (Notification.permission === "default") {
      // Demande la permission au premier geste utilisateur (clic/tap).
      var handler = function () {
        requestPermissionThenSubscribe();
        document.removeEventListener("pointerdown", handler);
        document.removeEventListener("keydown", handler);
      };
      document.addEventListener("pointerdown", handler);
      document.addEventListener("keydown", handler);
    }
  });
})();
