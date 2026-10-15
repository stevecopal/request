/**
 * app_spa.js — noyau SPA UnivReq.
 *
 * Responsabilités (ARCHITECTURE §11.1) :
 *   1. Helper CSRF : lit le cookie csrftoken → header X-CSRFToken sur tout POST.
 *   2. Modal maîtresse : ouverture/fermeture avec transitions
 *      translate-y-full → translate-y-0, squelette de chargement, piège de focus.
 *   3. Swap de fragments : fetch() + injection HTML, zéro rechargement de page,
 *      historique du navigateur (pushState/popstate).
 *   4. Toaster global : notifications transientes (auto-dismiss 4 s).
 *
 * Exposé globalement via window.UnivReq (consommé par auth_handler.js,
 * ticket_form_dynamic.js, ticket_lifecycle.js, websocket_listener.js).
 */
(function () {
  "use strict";

  var TOASTER_DURATION = 4000;
  var MODAL_TRANSITION = 300;

  var modal = null;
  var modalPanel = null;
  var modalTitle = null;
  var modalBody = null;
  var lastFocusedElement = null;
  var toasterTimer = null;

  /* ------------------------------------------------------------------ */
  /* Helpers                                                             */
  /* ------------------------------------------------------------------ */

  function getCookie(name) {
    var value = "; " + document.cookie;
    var parts = value.split("; " + name + "=");
    if (parts.length !== 2) return null;
    return parts.pop().split(";").shift();
  }

  function csrfToken() {
    return getCookie("csrftoken");
  }

  /**
   * Requête fetch standardisée : headers CSRF + X-Requested-With,
   * parsing JSON automatique, erreurs HTTP levées avec leur charge utile.
   */
  function apiFetch(url, options) {
    options = options || {};
    var method = (options.method || "GET").toUpperCase();
    var headers = Object.assign({}, options.headers || {});

    headers["X-Requested-With"] = "XMLHttpRequest";
    if (method !== "GET" && method !== "HEAD" && csrfToken()) {
      headers["X-CSRFToken"] = csrfToken();
    }
    if (options.body && !(options.body instanceof FormData) && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    options.headers = headers;
    options.credentials = options.credentials || "same-origin";

    return fetch(url, options).then(function (response) {
      var contentType = response.headers.get("content-type") || "";
      var isJson = contentType.indexOf("application/json") !== -1;
      var parse = isJson ? response.json() : response.text();

      return parse.then(function (data) {
        if (!response.ok) {
          var error = new Error(
            (isJson && (data.message || data.detail)) || "Erreur " + response.status
          );
          error.status = response.status;
          error.data = data;
          throw error;
        }
        return { data: data, status: response.status, response: response };
      });
    });
  }

  /* ------------------------------------------------------------------ */
  /* Modal maîtresse                                                     */
  /* ------------------------------------------------------------------ */

  function resolveModal() {
    modal = document.getElementById("master-modal");
    modalPanel = document.getElementById("master-modal-panel");
    modalTitle = document.getElementById("modal-title");
    modalBody = document.getElementById("modal-body");
  }

  function openMasterModal(title) {
    if (!modal) resolveModal();
    if (!modal) return;
    lastFocusedElement = document.activeElement;

    modalTitle.textContent = title || "…";
    modal.classList.remove("hidden");
    document.body.style.overflow = "hidden";

    requestAnimationFrame(function () {
      modal.classList.add("opacity-100");
      modalPanel.classList.remove("translate-y-full");
    });

    // Cibler le vrai bouton de fermeture (le backdrop porte aussi data-modal-close
    // mais n'est pas focalisable)
    var closeButton = modal.querySelector("button[data-modal-close]");
    if (closeButton) closeButton.focus({ preventScroll: true });
  }

  function closeModal() {
    if (!modal || modal.classList.contains("hidden")) return;
    modal.classList.remove("opacity-100");
    modalPanel.classList.add("translate-y-full");
    document.body.style.overflow = "";

    window.setTimeout(function () {
      modal.classList.add("hidden");
      modalBody.innerHTML = "";
      if (lastFocusedElement && document.contains(lastFocusedElement)) {
        lastFocusedElement.focus({ preventScroll: true });
      }
    }, MODAL_TRANSITION);
  }

  /** Squelette affiché immédiatement, avant toute réponse réseau. */
  function showModalSkeleton(title) {
    if (!modal) resolveModal();
    modalTitle.textContent = title || "…";
    modalBody.innerHTML =
      '<div class="space-y-4" aria-hidden="true">' +
      '<div class="skeleton h-10 w-full"></div>' +
      '<div class="skeleton h-10 w-full"></div>' +
      '<div class="skeleton h-24 w-full"></div>' +
      '<div class="skeleton h-12 w-full mt-6"></div>' +
      "</div>";
  }

  /**
   * Charge un fragment HTML dans la modale (fallback d'erreur = toaster).
   * @param {string} url - route Django servant le fragment
   * @param {{title?: string}} opts
   */
  /* Endpoints JSON reserves au POST : jamais charges en GET dans la modale.
     Garde-fou anti-405 : un data-modal-src mal configure bascule vers
     le fragment HTML /login/ au lieu de requeter /accounts/login/ en GET. */
  var JSON_ONLY_PATHS = [
    "/accounts/login/",
    "/accounts/logout/",
    "/accounts/ajax/onboarding/",
    "/accounts/ajax/push/subscribe/",
    "/accounts/ajax/push/unsubscribe/",
    "/accounts/ajax/notifications/read/"
  ];

  function isJsonOnlyPath(url) {
    if (!url) return false;
    var path = String(url).split("?")[0].split("#")[0];
    // N'operer que sur les chemins same-origin (ignore http(s):// externes).
    if (/^https?:\/\//i.test(path)) {
      try {
        var parsed = new URL(path, window.location.origin);
        if (parsed.origin !== window.location.origin) return false;
        path = parsed.pathname;
      } catch (e) {
        return false;
      }
    }
    if (path.charAt(0) !== "/") return false;
    for (var i = 0; i < JSON_ONLY_PATHS.length; i++) {
      if (path === JSON_ONLY_PATHS[i]) return true;
    }
    return false;
  }

  function loadIntoModal(url, opts) {
    opts = opts || {};
    if (isJsonOnlyPath(url)) {
      // Redirige vers le fragment HTML plutot que de declencher un 405.
      url = "/login/";
      if (!opts.title || opts.title === "…") opts.title = "Connexion";
    }
    openMasterModal(opts.title || "…");
    showModalSkeleton(opts.title);

    return apiFetch(url)
      .then(function (result) {
        modalBody.innerHTML = result.data;
        if (opts.onLoaded) opts.onLoaded(modalBody);
        // Ignorer les inputs cachés (csrfmiddlewaretoken) pour le focus initial
        var focusable = modalBody.querySelector(
          "input:not([type=hidden]), select:not([disabled]), textarea:not([disabled]), button:not([disabled])"
        );
        if (focusable) focusable.focus({ preventScroll: true });
      })
      .catch(function (err) {
        closeModal();
        showNotification(err.message || "Impossible de charger le contenu.", "error");
      });
  }

  /* ------------------------------------------------------------------ */
  /* Swap de fragments (#spa-viewport)                                   */
  /* ------------------------------------------------------------------ */

  function setLoading(target, html) {
    target.innerHTML =
      '<div class="space-y-4" aria-hidden="true">' +
      '<div class="skeleton h-4 w-1/3"></div>' +
      '<div class="skeleton h-28 w-full"></div>' +
      '<div class="skeleton h-28 w-full"></div>' +
      '<div class="skeleton h-28 w-full"></div>' +
      "</div>";
    if (html) target.setAttribute("aria-busy", "true");
  }

  /**
   * Remplace le contenu d'un conteneur par un fragment serveur.
   * @param {string} url
   * @param {{target?: string, pushState?: boolean, keepScroll?: boolean, onLoaded?: Function}} opts
   *   keepScroll : vrai pour un rafraîchissement silencieux (temps réel,
   *   rechargement de détail après décision) — évite le retour en haut de page.
   */
  function loadFragment(url, opts) {
    opts = opts || {};
    var target = document.querySelector(opts.target || "#spa-viewport");
    if (!target) return Promise.resolve();

    setLoading(target, true);

    return apiFetch(url)
      .then(function (result) {
        target.innerHTML = result.data;
        target.setAttribute("aria-busy", "false");
        if (opts.keepScroll !== true) {
          target.focus({ preventScroll: true });
          window.scrollTo(0, 0);
        }

        if (opts.pushState !== false && url !== window.location.pathname) {
          history.pushState({ fragment: url }, "", url);
        }
        if (opts.onLoaded) opts.onLoaded(target);
        if (typeof window.UnivReq.onContentLoaded === "function") {
          window.UnivReq.onContentLoaded(target);
        }
      })
      .catch(function (err) {
        target.setAttribute("aria-busy", "false");
        target.innerHTML =
          '<div class="rounded-2xl bg-white border border-slate-100 shadow-sm p-6 text-center">' +
          '<p class="text-sm font-medium text-navy-dark">' +
          (err.message || "Une erreur est survenue.") +
          "</p></div>";
        showNotification(err.message || "Une erreur est survenue.", "error");
      });
  }

  /* ------------------------------------------------------------------ */
  /* Toaster global                                                      */
  /* ------------------------------------------------------------------ */

  var SUCCESS_ICON =
    '<svg class="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/></svg>';
  var ERROR_ICON =
    '<svg class="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
    '<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/></svg>';

  function showNotification(message, kind) {
    var toaster = document.getElementById("global-toaster");
    var card = document.getElementById("toaster-card");
    var icon = document.getElementById("toaster-icon");
    var text = document.getElementById("toaster-message");
    if (!toaster) return;

    var isSuccess = kind !== "error";
    card.classList.toggle("toast-success", isSuccess);
    card.classList.toggle("toast-error", !isSuccess);
    icon.classList.toggle("text-emerald-600", isSuccess);
    icon.classList.toggle("text-red-600", !isSuccess);
    icon.innerHTML = isSuccess ? SUCCESS_ICON : ERROR_ICON;
    text.textContent = message;

    toaster.classList.remove("-translate-y-24", "opacity-0");

    if (navigator.vibrate && !isSuccess) navigator.vibrate(50);

    if (toasterTimer) window.clearTimeout(toasterTimer);
    toasterTimer = window.setTimeout(function () {
      toaster.classList.add("-translate-y-24", "opacity-0");
    }, TOASTER_DURATION);
  }

  /* ------------------------------------------------------------------ */
  /* Événements délégués                                                 */
  /* ------------------------------------------------------------------ */

  function onClick(event) {
    var closeTrigger = event.target.closest("[data-modal-close]");
    if (closeTrigger) {
      event.preventDefault();
      closeModal();
      return;
    }

    var modalTrigger = event.target.closest("[data-modal-src]");
    if (modalTrigger) {
      event.preventDefault();
      loadIntoModal(modalTrigger.getAttribute("data-modal-src"), {
        title: modalTrigger.getAttribute("data-modal-title") || "…",
        onLoaded: function (body) {
          if (typeof window.UnivReq.onModalContentLoaded === "function") {
            window.UnivReq.onModalContentLoaded(body);
          }
        },
      });
      return;
    }

    var fragmentTrigger = event.target.closest("[data-fragment-src]");
    if (fragmentTrigger) {
      event.preventDefault();
      var nav = fragmentTrigger.closest("nav");
      if (nav) {
        nav.querySelectorAll("[data-fragment-src]").forEach(function (item) {
          item.removeAttribute("aria-current");
        });
        fragmentTrigger.setAttribute("aria-current", "page");
      }
      loadFragment(fragmentTrigger.getAttribute("data-fragment-src"));
    }
  }

  function onKeydown(event) {
    if (event.key === "Escape") {
      closeModal();
      return;
    }
    if (event.key !== "Tab" || !modal || modal.classList.contains("hidden")) return;

    // Piège de focus : uniquement les éléments de la modale
    var focusables = modalPanel.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
    if (!focusables.length) return;
    var first = focusables[0];
    var last = focusables[focusables.length - 1];

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function onPopstate() {
    // Coque SPA uniquement (présence de #spa-config). Sur les pages
    // publiques, une simple navigation par ancre (#section) déclenche un
    // popstate dans Chrome : charger le document complet dans #spa-viewport
    // y dupliquerait navbar et footer. Là-bas, le navigateur gère l'ancre
    // nativement — aucun swap de fragment.
    if (!document.getElementById("spa-config")) return;
    // pathname + search : conserve les filtres/pagination du flux étudiant.
    loadFragment(window.location.pathname + window.location.search, {
      pushState: false,
    });
  }

  /* ------------------------------------------------------------------ */
  /* Initialisation                                                      */
  /* ------------------------------------------------------------------ */

  function loadInitialView() {
    var config = document.getElementById("spa-config");
    if (!config) return;

    var fragment = config.getAttribute("data-initial-fragment");
    if (fragment) loadFragment(fragment, { pushState: false });

    var modal = config.getAttribute("data-initial-modal");
    if (modal) {
      loadIntoModal(modal, {
        title: config.getAttribute("data-initial-modal-title") || "…",
      });
    }
  }

  function init() {
    resolveModal();
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKeydown);
    window.addEventListener("popstate", onPopstate);
    loadInitialView();
  }

  window.UnivReq = {
    apiFetch: apiFetch,
    csrfToken: csrfToken,
    openMasterModal: openMasterModal,
    closeModal: closeModal,
    showModalSkeleton: showModalSkeleton,
    loadIntoModal: loadIntoModal,
    loadFragment: loadFragment,
    showNotification: showNotification,
    onModalContentLoaded: null, // hook branché par les modules (auth, formulaires…)
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
