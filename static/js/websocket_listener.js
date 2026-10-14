/**
 * websocket_listener.js — mises à jour temps réel (ARCHITECTURE §10.4, Prompt 18).
 *
 * - connexion à /ws/tickets/ avec reconnexion à backoff exponentiel ;
 * - resynchronisation du fragment courant après chaque reconnexion réussie
 *   (rattrape les événements manqués pendant la coupure) ;
 * - repli polling (30 s) si le WS échoue à répétition ou n'est pas supporté ;
 * - à la réception d'un événement : patch de la carte [data-ticket-id],
 *   navigator.vibrate(50), toaster.
 */
(function () {
  "use strict";

  var api = window.UnivReq;
  var socket = null;
  var reconnectDelay = 1000;
  var MAX_DELAY = 30000;
  var POLL_INTERVAL = 30000;
  var MAX_FAILED_ATTEMPTS = 3;
  var manuallyClosed = false;
  var hadConnection = false; // true dès la première connexion réussie
  var failedAttempts = 0;
  var pollTimer = null;

  var BADGE_BY_STATUS = {
    SENT: "badge-status bg-slate-100 text-slate-700",
    RECEIVED: "badge-status bg-blue-100 text-blue-700",
    PROCESSING: "badge-status bg-amber-100 text-amber-700",
    MORE_INFO: "badge-status bg-violet-100 text-violet-700",
    RESOLVED: "badge-status bg-emerald-100 text-emerald-700",
    REJECTED: "badge-status bg-red-100 text-red-700",
  };

  function updateUnreadBadges(count) {
    if (typeof count !== "number") return;
    document.querySelectorAll("[data-unread-badge]").forEach(function (badge) {
      if (count > 0) {
        badge.textContent = String(count);
        badge.classList.remove("hidden");
      } else {
        badge.textContent = "";
        badge.classList.add("hidden");
      }
    });
  }

  function patchCard(payload) {
    var selector = '[data-ticket-id="' + payload.ticket_id + '"]';
    var cards = document.querySelectorAll(selector);
    cards.forEach(function (card) {
      card.setAttribute("data-status", payload.status);
      var badge = card.querySelector("[data-status-badge]");
      if (badge) {
        badge.className = BADGE_BY_STATUS[payload.status] || BADGE_BY_STATUS.SENT;
        badge.textContent = payload.status_label || payload.status;
      }
    });
    return cards.length > 0;
  }

  function handleMessage(payload) {
    var updated = patchCard(payload);

    // Badge de navigation : compteur de notifications non lues émis par le
    // signal serveur (uniquement le destinataire concerné le reçoit).
    updateUnreadBadges(payload.unread_notifications);

    if (navigator.vibrate) navigator.vibrate(50);

    var verb = payload.created ? "Nouvelle requête" : "Statut mis à jour";
    api.showNotification(
      "🟢 " + verb + " : " + (payload.status_label || payload.status),
      "success"
    );

    // Une nouvelle requête débarque dans la boîte enseignant : on rafraîchit.
    if (payload.created && document.querySelector("[data-teacher-inbox]")) {
      api.loadFragment("/tickets/teacher/", { target: "#spa-viewport", pushState: false });
    } else if (!updated) {
      // La carte n'est pas à l'écran : rien à patcher, la notif suffit.
    }
  }

  /* ------------------------------------------------------------------ */
  /* Repli polling : recharge le fragment courant toutes les 30 s.      */
  /* Activé seulement si le WS est défaillant / non supporté.           */
  /* ------------------------------------------------------------------ */

  function spaReady() {
    return Boolean(document.getElementById("spa-config") && document.getElementById("spa-viewport"));
  }

  function resyncCurrentView() {
    if (!spaReady()) return;
    api.loadFragment(window.location.pathname + window.location.search, {
      target: "#spa-viewport",
      pushState: false,
    });
  }

  function startPolling() {
    if (pollTimer || !spaReady()) return;
    pollTimer = window.setInterval(resyncCurrentView, POLL_INTERVAL);
  }

  function stopPolling() {
    if (pollTimer) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  /* ------------------------------------------------------------------ */
  /* Connexion WebSocket + resynchronisation                             */
  /* ------------------------------------------------------------------ */

  function connect() {
    if (!("WebSocket" in window)) {
      startPolling(); // navigateur sans WS : repli polling silencieux
      return;
    }
    var scheme = window.location.protocol === "https:" ? "wss://" : "ws://";
    socket = new WebSocket(scheme + window.location.host + "/ws/tickets/");

    socket.onopen = function () {
      reconnectDelay = 1000;
      failedAttempts = 0;
      stopPolling(); // le temps réel reprend la main
      if (hadConnection) {
        // Reconnexion après coupure : resynchronise l'état affiché.
        resyncCurrentView();
      }
      hadConnection = true;
    };

    socket.onmessage = function (event) {
      var payload;
      try {
        payload = JSON.parse(event.data);
      } catch (e) {
        return;
      }
      handleMessage(payload);
    };

    socket.onclose = function (event) {
      if (manuallyClosed || event.code === 4401) return;
      failedAttempts += 1;
      if (failedAttempts >= MAX_FAILED_ATTEMPTS) startPolling();
      window.setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, MAX_DELAY);
    };

    socket.onerror = function () {
      if (socket) socket.close();
    };
  }

  document.addEventListener("DOMContentLoaded", function () {
    if ("WebSocket" in window) connect();
    else startPolling();
  });

  // Onglet redevenant visible : reconnexion immédiate si le socket est fermé.
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState !== "visible") return;
    if (manuallyClosed) return;
    if (socket && socket.readyState === WebSocket.OPEN) {
      resyncCurrentView(); // rattrape les événements manqués en arrière-plan
      return;
    }
    reconnectDelay = 1000;
    connect();
  });

  window.addEventListener("beforeunload", function () {
    manuallyClosed = true;
    stopPolling();
    if (socket) socket.close();
  });
})();
