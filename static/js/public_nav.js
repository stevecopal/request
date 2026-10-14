/**
 * public_nav.js — navigation mobile de la landing publique (UnivReq).
 *
 * Rôle : piloter le panneau #public-nav-panel (dépliable sous l'en-tête).
 *   - ouverture/fermeture via [data-nav-toggle] (aria-expanded + icônes
 *     hamburger ↔ croix + aria-label mis à jour) ;
 *   - fermeture par : contrôle de fermeture (la bascule), touche Échap,
 *     sélection d'un lien de section du panneau, clic en dehors de
 *     l'en-tête ;
 *   - retour du focus sur la bascule uniquement quand la fermeture est
 *     explicite (Échap / bouton), jamais après un lien de section ;
 *   - réinitialisation à la bascule desktop (≥ 1024 px).
 *
 * Le panneau est en flux (jamais en surimpression) : sa fermeture ne peut
 * donc pas masquer de contenu. Module autonome, sans dépendance à app_spa.js.
 */
(function () {
  "use strict";

  function init() {
    var toggle = document.querySelector("[data-nav-toggle]");
    var panel = document.querySelector("[data-nav-panel]");
    if (!toggle || !panel || toggle.dataset.navWired === "1") return;
    toggle.dataset.navWired = "1";

    var iconOpen = toggle.querySelector("[data-nav-icon-open]");
    var iconClose = toggle.querySelector("[data-nav-icon-close]");
    var labelOpen = toggle.getAttribute("data-label-open") || "";
    var labelClose = toggle.getAttribute("data-label-close") || "";
    var desktopQuery = window.matchMedia("(min-width: 1024px)");

    function isOpen() {
      return toggle.getAttribute("aria-expanded") === "true";
    }

    function setOpen(open, refocusToggle) {
      panel.classList.toggle("hidden", !open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? labelClose : labelOpen);
      if (iconOpen) iconOpen.classList.toggle("hidden", open);
      if (iconClose) iconClose.classList.toggle("hidden", !open);
      if (!open && refocusToggle) toggle.focus({ preventScroll: true });
    }

    toggle.addEventListener("click", function () {
      setOpen(!isOpen(), false);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && isOpen()) setOpen(false, true);
    });

    // Sélection d'un lien de section : le panneau se referme avant le
    // défilement (le CTA de connexion, hors ancre, garde le focus visible).
    panel.addEventListener("click", function (event) {
      if (event.target.closest('a[href^="#"]')) setOpen(false, false);
    });

    // Clic en dehors de l'en-tête public.
    document.addEventListener("click", function (event) {
      if (isOpen() && !event.target.closest("[data-public-navbar]")) {
        setOpen(false, false);
      }
    });

    // Passage en desktop : plus de panneau, état remis à zéro.
    var onDesktopChange = function (event) {
      if (event.matches) setOpen(false, false);
    };
    if (typeof desktopQuery.addEventListener === "function") {
      desktopQuery.addEventListener("change", onDesktopChange);
    } else if (typeof desktopQuery.addListener === "function") {
      desktopQuery.addListener(onDesktopChange);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
