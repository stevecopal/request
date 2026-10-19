/**
 * admin_console.js — interactions de la console super-admin (C1–C6).
 *
 *   [data-console-form]     : soumission JSON des formulaires (génériques ou
 *                             inline), erreurs par champ, fermeture modale,
 *                             affichage du mot de passe à usage unique ;
 *   [data-console-filter]   : filtres → rechargement du fragment ciblé ;
 *   [data-console-action]   : action ponctuelle (toggle, delete, révocation…)
 *                             avec confirmation, puis rechargement ;
 *   [data-modal-target]     : sélecteur pilotant l'URL d'un bouton de modale
 *                             (C2 — ajout d'un membre de service) ;
 *   [data-fragment-select]  : sélecteur rechargeant un fragment (onglets C4) ;
 *   [data-admin-ticket]     : sélection d'une requête → chargement du détail
 *                             dans #admin-request-detail (C3).
 *
 * Chaîne les hooks UnivReq.onContentLoaded / onModalContentLoaded (jamais
 * l'écrase) — même convention que ticket_lifecycle.js.
 */
(function () {
  "use strict";

  var api = window.UnivReq;
  var selectedTicket = null;

  /* ---------------------------------------------------------------- */
  /* Helpers                                                           */
  /* ---------------------------------------------------------------- */

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
  }

  function setBusy(button, busy) {
    if (!button) return;
    button.disabled = busy;
    button.setAttribute("aria-busy", busy ? "true" : "false");
  }

  function currentFragmentUrl() {
    return window.location.pathname + window.location.search;
  }

  /** Recharge le fragment courant (filtres/pages conservés, sans scroll saut). */
  function reloadFragment(opts) {
    opts = opts || {};
    api.loadFragment(currentFragmentUrl(), {
      pushState: false,
      keepScroll: true,
      onLoaded: opts.onLoaded,
    });
  }

  function findDetailTarget() {
    return document.getElementById("admin-request-detail");
  }

  function detailBaseUrl() {
    var list = document.getElementById("admin-request-list");
    if (list && list.getAttribute("data-detail-base")) {
      return list.getAttribute("data-detail-base");
    }
    var row = document.querySelector("[data-admin-ticket]");
    return row ? row.getAttribute("data-detail-url") : null;
  }

  function markSelectedRow() {
    document.querySelectorAll("[data-admin-ticket]").forEach(function (row) {
      var on = row.getAttribute("data-ticket-id") === selectedTicket;
      row.classList.toggle("ring-2", on);
      row.classList.toggle("ring-navy", on);
      if (on) {
        row.setAttribute("aria-current", "true");
      } else {
        row.removeAttribute("aria-current");
      }
    });
  }

  /** (Re)charge la fiche de la requête sélectionnée (si panneau présent). */
  function loadSelectedDetail() {
    if (!selectedTicket) return;
    var target = findDetailTarget();
    var base = detailBaseUrl();
    if (!target || !base) return;
    api.loadFragment(
      base + "?ticket=" + encodeURIComponent(selectedTicket),
      {
        target: "#admin-request-detail",
        pushState: false,
        keepScroll: true,
        onLoaded: function (element) {
          element.classList.remove("hidden");
          markSelectedRow();
        },
      }
    );
  }

  /** Après une écriture C3 : fragment courant + fiche sélectionnée. */
  function refreshRequests() {
    reloadFragment({ onLoaded: loadSelectedDetail });
  }

  /* ---------------------------------------------------------------- */
  /* Erreurs de formulaire                                             */
  /* ---------------------------------------------------------------- */

  function renderErrors(form, data) {
    var message = (data && data.message) || "Formulaire invalide.";
    var box = form.querySelector("[data-form-errors]");
    if (!box) {
      api.showNotification(message, "error");
      return;
    }
    var title = box.querySelector("[data-form-errors-title]");
    var list = box.querySelector("[data-form-errors-list]");
    if (title) title.textContent = message;
    if (list) {
      var errors = (data && data.errors) || [];
      if (errors.length) {
        list.innerHTML = errors
          .map(function (err) {
            var field = err.field && err.field !== "__all__" ? err.field + " : " : "";
            return "<li>" + escapeHtml(field + err.message) + "</li>";
          })
          .join("");
      } else {
        list.innerHTML = "<li>" + escapeHtml(message) + "</li>";
      }
    }
    box.classList.remove("hidden");
    if (typeof box.scrollIntoView === "function") {
      box.scrollIntoView({ block: "nearest" });
    }
  }

  /* ---------------------------------------------------------------- */
  /* Modale à usage unique (mot de passe affiché une fois)             */
  /* ---------------------------------------------------------------- */

  function showCredential(form, password) {
    var scope = form.closest("#master-modal") || form.ownerDocument;
    var box = scope.querySelector("[data-credential-box]");
    var code = box && box.querySelector("[data-credential-value]");
    if (!box || !code) return;
    code.textContent = password;
    box.classList.remove("hidden");
    box.scrollIntoView({ block: "nearest" });
  }

  /* ---------------------------------------------------------------- */
  /* Formulaires [data-console-form]                                   */
  /* ---------------------------------------------------------------- */

  function onFormSuccess(form, data) {
    api.showNotification(data.message || "Enregistré.", "success");

    if (form.hasAttribute("data-keep-open")) {
      if (data.password) showCredential(form, data.password);
      return;
    }

    var inModal = form.closest("#master-modal");
    if (inModal) api.closeModal();

    if (form.getAttribute("data-refresh") === "requests") {
      refreshRequests();
    } else {
      reloadFragment({ onLoaded: loadSelectedDetail });
    }
  }

  function wireForm(form) {
    if (form.dataset.wired) return;
    form.dataset.wired = "1";

    // Cascade faculté → département (modales C1 et formulaires associés).
    var faculty = form.querySelector("[data-department-target]");
    if (faculty && !faculty.dataset.wired) {
      faculty.dataset.wired = "1";
      faculty.addEventListener("change", function () {
        var target = document.querySelector(
          faculty.getAttribute("data-department-target")
        );
        var url = faculty.getAttribute("data-departments-url");
        if (!target || !url) return;
        target.disabled = true;
        target.innerHTML = '<option value="">Chargement…</option>';
        api
          .apiFetch(url + "?faculty=" + encodeURIComponent(faculty.value))
          .then(function (result) {
            var options = ['<option value="">Sélectionnez un département</option>'];
            (result.data.departments || []).forEach(function (dept) {
              options.push(
                '<option value="' + dept.id + '">' + escapeHtml(dept.name) + "</option>"
              );
            });
            target.innerHTML = options.join("");
            target.disabled = false;
          })
          .catch(function (err) {
            target.innerHTML = '<option value="">Erreur</option>';
            api.showNotification(err.message || "Chargement impossible.", "error");
          });
      });
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var box = form.querySelector("[data-form-errors]");
      if (box) box.classList.add("hidden");

      // Bouton cliqué : transmis manuellement (FormData ignore les boutons).
      var submitter =
        event.submitter ||
        form.querySelector('button[type="submit"]:not([disabled])');
      setBusy(submitter, true);

      var body = new FormData(form);
      if (submitter && submitter.name) {
        body.append(submitter.name, submitter.value);
      }

      api
        .apiFetch(form.getAttribute("data-save-url") || form.action, {
          method: "POST",
          body: body,
        })
        .then(function (result) {
          onFormSuccess(form, result.data);
        })
        .catch(function (err) {
          var data = err.data || {};
          renderErrors(form, {
            message: data.message || err.message || "Enregistrement impossible.",
            errors: data.errors,
          });
        })
        .then(function () {
          setBusy(submitter, false);
        });
    });
  }

  /* ---------------------------------------------------------------- */
  /* Filtres [data-console-filter]                                     */
  /* ---------------------------------------------------------------- */

  function wireFilter(form) {
    if (form.dataset.wired) return;
    form.dataset.wired = "1";

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var params = new URLSearchParams();
      new FormData(form).forEach(function (value, key) {
        if (value !== "") params.append(key, value);
      });
      var query = params.toString();
      var base = form.getAttribute("data-list-url");
      api.loadFragment(base + (query ? "?" + query : ""));
    });
  }

  /* ---------------------------------------------------------------- */
  /* Actions ponctuelles [data-console-action]                         */
  /* ---------------------------------------------------------------- */

  function onActionClick(event) {
    var action = event.target.closest("[data-console-action]");
    if (!action) return;
    event.preventDefault();
    if (action.disabled) return;

    var confirmMessage = action.getAttribute("data-confirm");
    if (confirmMessage && !window.confirm(confirmMessage)) return;

    var body = new FormData();
    if (action.hasAttribute("data-pk")) {
      body.append("pk", action.getAttribute("data-pk"));
    }
    if (action.hasAttribute("data-session-key")) {
      body.append("session_key", action.getAttribute("data-session-key"));
    }

    setBusy(action, true);
    api
      .apiFetch(action.getAttribute("data-action-url"), {
        method: "POST",
        body: body,
      })
      .then(function (result) {
        api.showNotification(result.data.message || "Action effectuée.", "success");
        if (action.getAttribute("data-refresh") === "requests") {
          refreshRequests();
        } else {
          reloadFragment({ onLoaded: loadSelectedDetail });
        }
      })
      .catch(function (err) {
        var data = err.data || {};
        api.showNotification(
          data.message || err.message || "Action impossible.",
          "error"
        );
        setBusy(action, false);
      });
  }

  /* ---------------------------------------------------------------- */
  /* Sélection d'une requête (C3)                                      */
  /* ---------------------------------------------------------------- */

  function onTicketClick(event) {
    var row = event.target.closest("[data-admin-ticket]");
    if (!row) return;
    event.preventDefault();

    selectedTicket = row.getAttribute("data-ticket-id");
    var target = findDetailTarget();
    var base = detailBaseUrl();
    if (!target || !base) return;

    api.loadFragment(base + "?ticket=" + encodeURIComponent(selectedTicket), {
      target: "#admin-request-detail",
      pushState: false,
      keepScroll: true,
      onLoaded: function (element) {
        element.classList.remove("hidden");
        markSelectedRow();
      },
    });
  }

  /* ---------------------------------------------------------------- */
  /* Sélecteurs : pilotage de modale (C2) et de fragment (C4)          */
  /* ---------------------------------------------------------------- */

  function onChange(event) {
    var modalTarget = event.target.closest("[data-modal-target]");
    if (modalTarget) {
      var button = document.querySelector(
        modalTarget.getAttribute("data-modal-target")
      );
      if (!button) return;
      var value = modalTarget.value;
      var base = modalTarget.getAttribute("data-modal-base") || "";
      button.disabled = !value;
      button.setAttribute(
        "data-modal-src",
        value ? base + "?service=" + encodeURIComponent(value) : ""
      );
      return;
    }

    var fragmentSelect = event.target.closest("[data-fragment-select]");
    if (fragmentSelect) {
      var url = fragmentSelect.getAttribute("data-fragment-base");
      if (!url) return;
      var keep = fragmentSelect.getAttribute("data-fragment-keep") || "";
      var name = fragmentSelect.name || fragmentSelect.id || "value";
      var query = keep ? keep + "&" : "";
      query += name + "=" + encodeURIComponent(fragmentSelect.value);
      api.loadFragment(url + "?" + query, { keepScroll: true });
    }
  }

  /* ---------------------------------------------------------------- */
  /* Câblage & hooks                                                    */
  /* ---------------------------------------------------------------- */

  function wire(root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll("[data-console-form]").forEach(wireForm);
    root.querySelectorAll("[data-console-filter]").forEach(wireFilter);
    markSelectedRow();
  }

  document.addEventListener("DOMContentLoaded", function () {
    wire(document);
  });
  document.addEventListener("click", onActionClick);
  document.addEventListener("click", onTicketClick);
  document.addEventListener("change", onChange);

  // Fragments injectés dans #spa-viewport — on chaîne les hooks existants.
  api.onContentLoaded = (function (previous) {
    return function (body) {
      if (typeof previous === "function") previous(body);
      wire(body);
      // Après rechargement (pagination, filtre…) : la fiche reste affichée.
      loadSelectedDetail();
    };
  })(api.onContentLoaded);

  var previousModalHook = api.onModalContentLoaded;
  api.onModalContentLoaded = function (body) {
    if (typeof previousModalHook === "function") previousModalHook(body);
    wire(body);
  };
})();
