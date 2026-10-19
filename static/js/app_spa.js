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
  var viewportRaf = null;
  var viewportSyncActive = false;

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

  /**
   * Aligne la modale sur le viewport visuel : sur mobile, le clavier virtuel
   * réduit `visualViewport` sans redimensionner la fenêtre — sans cet
   * ajustement, le bas de la modale (et les champs) passe sous le clavier.
   */
  function syncModalViewport() {
    if (!modal || modal.classList.contains("hidden")) return;
    var vv = window.visualViewport;
    if (!vv) return;

    var top = Math.max(vv.offsetTop, 0);
    var height = Math.max(vv.height, 0);
    var isMobile = window.innerWidth < 640;

    modal.style.top = top + "px";
    modal.style.height = height + "px";
    modal.style.bottom = "auto";

    // Clavier mobile : le viewport visuel est nettement plus court que la
    // fenêtre. On compacte l'en-tête et le bouton d'action (collant, cf.
    // input.css) reste visible au-dessus du clavier.
    var keyboardOpen = isMobile && height < window.innerHeight - 120;
    modal.classList.toggle("is-keyboard-open", keyboardOpen);

    if (modalPanel && isMobile) {
      modalPanel.style.maxHeight = Math.max(height - 12, 0) + "px";
    } else if (modalPanel) {
      modalPanel.style.maxHeight = "";
    }
  }

  function onViewportChange() {
    if (viewportRaf) window.cancelAnimationFrame(viewportRaf);
    viewportRaf = window.requestAnimationFrame(function () {
      viewportRaf = null;
      syncModalViewport();
      // Après l'ouverture du clavier, ramener le champ actif dans la zone visible.
      var active = document.activeElement;
      if (isFormField(active)) {
        window.setTimeout(function () {
          ensureFieldVisible(active);
        }, 60);
      }
    });
  }

  function startViewportSync() {
    syncModalViewport();
    if (viewportSyncActive) return;
    var vv = window.visualViewport;
    if (!vv) return;
    viewportSyncActive = true;
    vv.addEventListener("resize", onViewportChange);
    vv.addEventListener("scroll", onViewportChange);
  }

  function stopViewportSync() {
    viewportSyncActive = false;
    var vv = window.visualViewport;
    if (vv) {
      vv.removeEventListener("resize", onViewportChange);
      vv.removeEventListener("scroll", onViewportChange);
    }
    if (viewportRaf) {
      window.cancelAnimationFrame(viewportRaf);
      viewportRaf = null;
    }
    if (modal) {
      modal.style.top = "";
      modal.style.height = "";
      modal.style.bottom = "";
      modal.classList.remove("is-keyboard-open");
    }
    if (modalPanel) modalPanel.style.maxHeight = "";
  }

  /** Fait défiler #modal-body juste assez pour rendre le champ visible. */
  function keepFieldVisible(field) {
    if (!modalBody || !field || !modalBody.contains(field)) return;
    var margin = 16;
    var bodyRect = modalBody.getBoundingClientRect();
    var fieldRect = field.getBoundingClientRect();

    // Réserve la hauteur du bouton d'action collant (mobile) : le champ
    // actif ne doit jamais se retrouver masqué derrière lui.
    var action = modalBody.querySelector("form > .btn:last-child");
    var bottomInset = 0;
    if (action && action !== field && !action.classList.contains("hidden")) {
      var actionRect = action.getBoundingClientRect();
      if (actionRect.height) {
        bottomInset = Math.min(actionRect.height + 12, bodyRect.height * 0.6);
      }
    }

    var visibleBottom = bodyRect.bottom - margin - bottomInset;
    if (fieldRect.bottom > visibleBottom) {
      modalBody.scrollTop += fieldRect.bottom - visibleBottom;
    } else if (fieldRect.top < bodyRect.top + margin) {
      modalBody.scrollTop -= bodyRect.top - fieldRect.top + margin;
    }
  }

  /* ------------------------------------------------------------------ */
  /* Clavier virtuel : le champ actif reste toujours visible            */
  /* ------------------------------------------------------------------ */

  function isFormField(el) {
    return !!el && typeof el.matches === "function" && el.matches("input, select, textarea");
  }

  /** Bas du viewport **visuel** (celui que recouvre le clavier mobile). */
  function visualBottom() {
    var vv = window.visualViewport;
    return vv ? vv.offsetTop + vv.height : window.innerHeight;
  }

  function visualTop() {
    var vv = window.visualViewport;
    return vv ? vv.offsetTop : 0;
  }

  /**
   * Garantit qu'un champ actif est visible au-dessus du clavier virtuel :
   *   - dans la modale → défilement interne de #modal-body (marge réservée
   *     pour le bouton d'action collant) ;
   *   - hors modale (page de connexion, formulaires de fragments) →
   *     scrollIntoView sur la fenêtre, borné au viewport visuel.
   * Le navigateur a d'abord le droit d'agir ; on ne corrige que si le champ
   * reste masqué (aucun défilement parasite).
   */
  function ensureFieldVisible(field) {
    if (!isFormField(field)) return;
    var margin = 24;
    var rect = field.getBoundingClientRect();
    if (rect.bottom <= visualBottom() - margin && rect.top >= visualTop() + 8) {
      return;
    }

    if (modalBody && modalBody.contains(field)) {
      keepFieldVisible(field);
      return;
    }

    try {
      field.scrollIntoView({ block: "nearest", behavior: "smooth" });
    } catch (e) {
      field.scrollIntoView(true);
    }
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

    startViewportSync();

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
    stopViewportSync();

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
    // Cible robuste : sur mobile, le clic peut viser l'icône SVG ; on
    // remonte toujours au bouton parent (icônes en pointer-events: none).
    var target = event.target;
    var filterToggle =
      target && typeof target.closest === "function"
        ? target.closest("[data-filter-toggle]")
        : null;
    if (filterToggle) {
      event.preventDefault();
      var panelId = filterToggle.getAttribute("aria-controls");
      var panel = panelId ? document.getElementById(panelId) : null;
      if (!panel) return;
      var expanded = filterToggle.getAttribute("aria-expanded") !== "true";
      filterToggle.setAttribute("aria-expanded", expanded ? "true" : "false");
      filterToggle.classList.toggle("is-active", expanded);
      panel.classList.toggle("hidden", !expanded);
      var chevron = filterToggle.querySelector("[data-filter-chevron]");
      if (chevron) chevron.classList.toggle("rotate-180", expanded);
      return;
    }

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

    // Clavier mobile : quel que soit l'endroit du champ actif (modale ou
    // page autonome), le ramener au-dessus du clavier après ouverture.
    document.addEventListener("focusin", function (event) {
      var field = event.target;
      if (!isFormField(field)) return;
      window.setTimeout(function () {
        ensureFieldVisible(field);
      }, 320);
    });

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
