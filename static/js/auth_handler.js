/**
 * auth_handler.js — connexion, déconnexion et onboarding (UnivReq).
 *
 * Sécurité (OWASP) :
 *   - le formulaire déclare `method="post"` ; ce contrôleur intercepte le
 *     `submit` via `event.preventDefault()` : rien ne part jamais en query
 *     string, l'URL reste propre (aucun mot de passe / matricule visible) ;
 *   - envoi `fetch()` POST avec en-tête `X-CSRFToken` lu dans le cookie ;
 *   - corps compilé via `FormData` (aucune sérialisation manuelle).
 *
 * UX : état de chargement (champs désactivés + pulsation du bouton), erreurs
 * rendues dans la modale (400/401) sans rompre la session, succès → toaster.
 */
(function () {
  "use strict";

  var api = window.UnivReq;

  /* ------------------------------------------------------------------ */
  /* Utilitaire : lecture sécurisée du cookie CSRF                      */
  /* ------------------------------------------------------------------ */

  function getCookie(name) {
    var match = document.cookie.match(
      new RegExp("(?:^|;\\s*)" + name.replace(/([.*+?^${}()|[\]\\])/g, "\\$1") + "=([^;]*)")
    );
    return match ? decodeURIComponent(match[1]) : null;
  }

  var SPINNER =
    '<span class="inline-block w-5 h-5 mr-2 border-2 border-white/40 border-t-white rounded-full animate-spin" aria-hidden="true"></span>';

  function setFormBusy(form, busy) {
    var fields = form.querySelectorAll("input, select, textarea, button");
    fields.forEach(function (field) {
      field.disabled = busy;
    });
    form.setAttribute("aria-busy", busy ? "true" : "false");

    var submit = form.querySelector('[type="submit"]');
    if (!submit) return;
    if (busy) {
      if (!submit.dataset.originalHtml) submit.dataset.originalHtml = submit.innerHTML;
      submit.innerHTML = SPINNER + submit.dataset.originalHtml;
      submit.classList.add("opacity-80", "pointer-events-none");
    } else if (submit.dataset.originalHtml) {
      submit.innerHTML = submit.dataset.originalHtml;
      submit.classList.remove("opacity-80", "pointer-events-none");
    }
  }

  /* ------------------------------------------------------------------ */
  /* Connexion                                                           */
  /* ------------------------------------------------------------------ */

  function handleLogin(form) {
    var errorBox = form.querySelector("#login-error");

    function fail(message) {
      // 400/401 : la modale reste ouverte, la session n'est pas touchée.
      if (errorBox) {
        errorBox.textContent = message;
        errorBox.classList.remove("hidden");
      }
      api.showNotification(message, "error");
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault(); // interdit toute soumission GET native
      if (errorBox) errorBox.classList.add("hidden");
      setFormBusy(form, true);

      api
        .apiFetch(form.getAttribute("data-login-url"), {
          method: "POST",
          headers: { "X-CSRFToken": getCookie("csrftoken") || "" },
          body: new FormData(form),
        })
        .then(function (result) {
          var data = result.data || {};
          api.closeModal();
          api.showNotification(data.message || "Connexion réussie", "success");

          var next = data.next || "/dashboard/";
          if (document.getElementById("spa-config")) {
            // Déjà dans la coque SPA : injection du fragment, zéro rechargement.
            api.loadFragment(next, { pushState: false });
          } else {
            // Depuis la landing : navigation vers la coque (header + bottom-nav).
            window.location.href = next;
          }
        })
        .catch(function (err) {
          var payload = err.data || {};
          fail(payload.message || err.message || "Connexion impossible.");
          setFormBusy(form, false); // la modale reste active pour réessayer
        });
    });
  }

  /* ------------------------------------------------------------------ */
  /* Déconnexion                                                         */
  /* ------------------------------------------------------------------ */

  function handleLogout(button) {
    setBusy(button, true);
    api
      .apiFetch(button.getAttribute("data-logout-url"), {
        method: "POST",
        headers: { "X-CSRFToken": getCookie("csrftoken") || "" },
      })
      .then(function (result) {
        window.location.href = (result.data && result.data.next) || "/";
      })
      .catch(function (err) {
        setBusy(button, false);
        api.showNotification(err.message || "Déconnexion impossible.", "error");
      });
  }

  function setBusy(button, busy) {
    if (!button) return;
    button.disabled = busy;
    button.setAttribute("aria-busy", busy ? "true" : "false");
  }

  /* ------------------------------------------------------------------ */
  /* Onboarding — cascade Faculté → Département                          */
  /* ------------------------------------------------------------------ */

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.textContent = value == null ? "" : value;
    return div.innerHTML;
  }

  function loadDepartments(facultySelect) {
    var targetSelector = facultySelect.getAttribute("data-department-target");
    var url = facultySelect.getAttribute("data-departments-url");
    var target = document.querySelector(targetSelector);
    if (!target) return;

    var facultyId = facultySelect.value;
    target.disabled = true;
    target.innerHTML = '<option value="">Chargement…</option>';

    if (!facultyId) {
      target.innerHTML = '<option value="">Sélectionnez d\'abord une faculté</option>';
      return;
    }

    api
      .apiFetch(url + "?faculty=" + encodeURIComponent(facultyId))
      .then(function (result) {
        var options = ['<option value="">Sélectionnez un département</option>'];
        (result.data.departments || []).forEach(function (dept) {
          options.push('<option value="' + dept.id + '">' + escapeHtml(dept.name) + "</option>");
        });
        target.innerHTML = options.join("");
        target.disabled = false;
      })
      .catch(function (err) {
        target.innerHTML = '<option value="">Erreur de chargement</option>';
        api.showNotification(err.message || "Chargement impossible.", "error");
      });
  }

  function handleOnboarding(form) {
    var errorBox = form.querySelector("#onboarding-error");
    var facultySelect = form.querySelector("[data-department-target]");

    if (facultySelect) {
      facultySelect.addEventListener("change", function () {
        loadDepartments(facultySelect);
      });
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (errorBox) errorBox.classList.add("hidden");
      setFormBusy(form, true);

      api
        .apiFetch(form.getAttribute("data-onboarding-url"), {
          method: "POST",
          headers: { "X-CSRFToken": getCookie("csrftoken") || "" },
          body: new FormData(form),
        })
        .then(function (result) {
          var data = result.data || {};
          api.closeModal();
          api.showNotification(data.message || "Profil enregistré.", "success");
          window.location.href = data.next || "/dashboard/";
        })
        .catch(function (err) {
          var payload = err.data || {};
          var message = payload.message || err.message || "Enregistrement impossible.";
          if (errorBox) {
            errorBox.textContent = message;
            errorBox.classList.remove("hidden");
          }
          api.showNotification(message, "error");
          setFormBusy(form, false);
        });
    });
  }

  /* ------------------------------------------------------------------ */
  /* Câblage (formulaires injectés en modale compris)                   */
  /* ------------------------------------------------------------------ */

  function wire(root) {
    var loginForm = root.querySelector("#login-form");
    if (loginForm && !loginForm.dataset.wired) {
      loginForm.dataset.wired = "1";
      handleLogin(loginForm);
    }
    var onboardingForm = root.querySelector("#onboarding-form");
    if (onboardingForm && !onboardingForm.dataset.wired) {
      onboardingForm.dataset.wired = "1";
      handleOnboarding(onboardingForm);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    wire(document);
  });

  document.addEventListener("click", function (event) {
    var logoutButton = event.target.closest("[data-logout]");
    if (logoutButton) {
      event.preventDefault();
      handleLogout(logoutButton);
    }
  });

  // Exposé pour les autres modules / tests.
  api.getCookie = getCookie;
  api.onModalContentLoaded = function (body) {
    wire(body);
  };
})();
