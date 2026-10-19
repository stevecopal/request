/**
 * pwa_install.js — bouton « Télécharger l’application » (landing publique).
 *
 * Le projet est une PWA (static/manifest.json) : « télécharger l’application »
 * = l'installer via le prompt natif `beforeinstallprompt`.
 *
 * Rôle :
 *   - capture `beforeinstallprompt` (preventDefault) ;
 *   - AU CICL : si le prompt est déjà émissible → le déclenche
 *     immédiatement (installation automatique, sans menu de navigateur) ;
 *     s'il n'est pas encore émissible (critères PWA en cours : service
 *     worker, engagement) → affiche « Préparation… » et le déclenche
 *     automatiquement dès que l'événement arrive ;
 *   - sans prompt après un délai (iOS/Safari, Firefox, origine non
 *     sécurisée…) → toaster d'aide (textes portés par les attributs
 *     data-install-* de [data-public-navbar], traduits côté template) ;
 *   - masque les boutons quand l'app est déjà installée (mode standalone
 *     ou événement `appinstalled`) ;
 *   - no-op hors landing : aucun bouton [data-install-app] ailleurs.
 *
 * Module autonome ; réutilise le toaster du noyau SPA
 * (window.UnivReq.showNotification) s'il est présent.
 */
(function () {
  "use strict";

  var WAIT_TIMEOUT_MS = 6000; // délai d'attente du prompt après un clic

  var deferredPrompt = null;
  var pendingInstall = false;

  function isStandalone() {
    // Chrome/Edge (Android et desktop) : app installée ouverte en fenêtre dédiée.
    if (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) {
      return true;
    }
    // iOS Safari : navigator.standalone n'existe que dans Safari.
    return window.navigator.standalone === true;
  }

  function isIOS() {
    return /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
  }

  function notify(message, kind) {
    if (!message) return;
    if (window.UnivReq && typeof window.UnivReq.showNotification === "function") {
      window.UnivReq.showNotification(message, kind);
    }
  }

  function hideButtons(buttons) {
    Array.prototype.forEach.call(buttons, function (btn) {
      btn.classList.add("hidden");
    });
  }

  function init() {
    var buttons = document.querySelectorAll("[data-install-app]");
    if (!buttons.length) return; // no-op hors landing

    var root = document.querySelector("[data-public-navbar]");

    function text(name) {
      return root ? root.getAttribute(name) || "" : "";
    }

    function fallbackMessage() {
      return isIOS() ? text("data-install-fallback-ios") : text("data-install-fallback");
    }

    // Déclenche le prompt natif UNE fois (BeforeInstallPromptEvent
    // mono-consommable). L'acceptation masque les boutons via
    // `appinstalled` ; le refus ré-affiche l'aide manuelle.
    function firePrompt() {
      var promptEvent = deferredPrompt;
      deferredPrompt = null;
      pendingInstall = false;
      if (!promptEvent) return;
      try {
        promptEvent.prompt();
      } catch (err) {
        notify(fallbackMessage(), "error");
        return;
      }
      if (promptEvent.userChoice && typeof promptEvent.userChoice.then === "function") {
        promptEvent.userChoice.then(function (choice) {
          if (choice && choice.outcome === "dismissed") {
            notify(fallbackMessage(), "error");
          }
        });
      }
    }

    window.addEventListener("beforeinstallprompt", function (event) {
      event.preventDefault();
      deferredPrompt = event;
      // Un clic était en attente du prompt : on l'auto-lance maintenant.
      if (pendingInstall) firePrompt();
    });

    window.addEventListener("appinstalled", function () {
      deferredPrompt = null;
      pendingInstall = false;
      hideButtons(buttons);
      notify(text("data-install-done"), "success");
    });

    Array.prototype.forEach.call(buttons, function (btn) {
      if (btn.dataset.installWired === "1") return;
      btn.dataset.installWired = "1";

      btn.addEventListener("click", function () {
        // App déjà installée : plus rien à faire, on retire les boutons.
        if (isStandalone()) {
          hideButtons(buttons);
          return;
        }

        // L'installation automatique exige un contexte sécurisé (HTTPS ou
        // localhost) : sinon `beforeinstallprompt` ne sera jamais émis.
        if (!window.isSecureContext) {
          notify(text("data-install-https"), "error");
          return;
        }

        // Prompt déjà émissible : déclenchements immédiats.
        if (deferredPrompt) {
          firePrompt();
          return;
        }

        // iOS Safari n'émet jamais `beforeinstallprompt` : aide manuelle.
        if (isIOS()) {
          notify(fallbackMessage(), "error");
          return;
        }

        // Prompt pas encore émissible : on attend son arrivée (Chrome
        // l'émet après installation du service worker + engagement).
        if (pendingInstall) return;
        pendingInstall = true;
        notify(text("data-install-waiting"), "success");
        window.setTimeout(function () {
          if (!pendingInstall) return;
          pendingInstall = false;
          if (!deferredPrompt) notify(fallbackMessage(), "error");
        }, WAIT_TIMEOUT_MS);
      });
    });

    // Rendu initial dans l'app déjà installée : boutons masqués d'emblée.
    if (isStandalone()) hideButtons(buttons);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
