/**
 * dashboard_nav.js — interactions de la coque applicative authentifiée.
 *
 *   - Tiroir de navigation mobile (ouvrir / fermer + voile + Échap).
 *   - Fermeture automatique du tiroir après une action de navigation
 *     (chargement d'un fragment ou ouverture d'une modale).
 *
 * Aucune logique métier : le routage des fragments reste dans app_spa.js.
 */
(function () {
  "use strict";

  function init() {
    var sidebar = document.getElementById("app-sidebar");
    var overlay = document.getElementById("app-drawer-overlay");
    if (!sidebar) return;

    var openers = document.querySelectorAll("[data-drawer-open]");
    var closers = document.querySelectorAll("[data-drawer-close]");

    function openDrawer() {
      sidebar.classList.remove("-translate-x-full");
      if (overlay) overlay.classList.remove("hidden");
      document.body.style.overflow = "hidden";
      openers.forEach(function (btn) {
        btn.setAttribute("aria-expanded", "true");
      });
    }

    function closeDrawer() {
      sidebar.classList.add("-translate-x-full");
      if (overlay) overlay.classList.add("hidden");
      document.body.style.overflow = "";
      openers.forEach(function (btn) {
        btn.setAttribute("aria-expanded", "false");
      });
    }

    openers.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var isOpen = !sidebar.classList.contains("-translate-x-full");
        if (isOpen) closeDrawer();
        else openDrawer();
      });
    });

    closers.forEach(function (btn) {
      btn.addEventListener("click", closeDrawer);
    });

    // Fermer le tiroir après une action de navigation (fragment ou modale).
    sidebar.addEventListener("click", function (event) {
      if (event.target.closest("[data-fragment-src], [data-modal-src]")) {
        closeDrawer();
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeDrawer();
    });

    // Replier à la bascule desktop pour ne jamais bloquer le scroll du body.
    var desktop = window.matchMedia("(min-width: 1024px)");
    function syncDesktop(event) {
      if (event.matches) {
        if (overlay) overlay.classList.add("hidden");
        document.body.style.overflow = "";
      }
    }
    if (typeof desktop.addEventListener === "function") {
      desktop.addEventListener("change", syncDesktop);
    } else if (typeof desktop.addListener === "function") {
      desktop.addListener(syncDesktop);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
