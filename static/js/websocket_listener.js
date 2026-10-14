/**
 * websocket_listener.js — mises à jour temps réel (ARCHITECTURE §10.4, Prompt 18).
 *
 * Se connecte à /ws/tickets/ au chargement, avec reconnexion à backoff
 * exponentiel. À la réception d'un événement de statut :
 *   - met à jour la carte [data-ticket-id] (rail + badge), sans rechargement ;
 *   - déclenche navigator.vibrate(50) si supporté ;
 *   - affiche un message via le toaster global.
 */
(function () {
  "use strict";

  var api = window.UnivReq;
  var socket = null;
  var reconnectDelay = 1000;
  var MAX_DELAY = 30000;
  var manuallyClosed = false;

  var BADGE_BY_STATUS = {
    SENT: "badge-status bg-slate-100 text-slate-700",
    RECEIVED: "badge-status bg-blue-100 text-blue-700",
    PROCESSING: "badge-status bg-amber-100 text-amber-700",
    RESOLVED: "badge-status bg-emerald-100 text-emerald-700",
    REJECTED: "badge-status bg-red-100 text-red-700",
  };

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

  function connect() {
    var scheme = window.location.protocol === "https:" ? "wss://" : "ws://";
    socket = new WebSocket(scheme + window.location.host + "/ws/tickets/");

    socket.onopen = function () {
      reconnectDelay = 1000;
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
      window.setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, MAX_DELAY);
    };

    socket.onerror = function () {
      if (socket) socket.close();
    };
  }

  document.addEventListener("DOMContentLoaded", function () {
    if ("WebSocket" in window) connect();
  });

  window.addEventListener("beforeunload", function () {
    manuallyClosed = true;
    if (socket) socket.close();
  });
})();
