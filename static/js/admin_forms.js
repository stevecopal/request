/**
 * admin_forms.js — formulaires de la console super-admin.
 *
 *   - #admin-import-form : upload multipart ETL → rendu des erreurs {line, message} ;
 *   - #admin-manual-form : création manuelle d'un compte (cascade faculté/département) ;
 *   - [data-title-field] : champ « Titre » affiché pour un enseignant, retiré
 *     du DOM et de la validation pour un étudiant (bascule dynamique).
 * Toutes les réponses passent par le toaster global (UnivReq.showNotification).
 */
(function () {
  "use strict";

  var api = window.UnivReq;

  function setBusy(button, busy) {
    if (!button) return;
    button.disabled = busy;
    button.setAttribute("aria-busy", busy ? "true" : "false");
  }

  function renderErrors(container, list, titleText, entries) {
    if (!container) return;
    if (!entries || !entries.length) {
      container.classList.add("hidden");
      return;
    }
    var titleEl = container.querySelector("[id$='-errors-title']");
    var listEl = container.querySelector("ul");
    if (titleEl) titleEl.textContent = titleText;
    if (listEl) {
      listEl.innerHTML = entries
        .map(function (err) {
          var prefix = err.line ? "Ligne " + err.line + " : " : "";
          return "<li>" + prefix + escapeHtml(err.message) + "</li>";
        })
        .join("");
    }
    container.classList.remove("hidden");
  }

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.textContent = value == null ? "" : value;
    return div.innerHTML;
  }

  function handleImport(form) {
    var submit = form.querySelector('[type="submit"]');
    var errorBox = form.querySelector("#import-errors");

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (errorBox) errorBox.classList.add("hidden");
      setBusy(submit, true);

      api
        .apiFetch(form.getAttribute("data-import-url"), {
          method: "POST",
          body: new FormData(form),
        })
        .then(function (result) {
          api.closeModal();
          api.showNotification(
            (result.data.message || "Import réussi.") +
              " (" + result.data.imported_count + ")",
            "success"
          );
        })
        .catch(function (err) {
          var data = err.data || {};
          renderErrors(errorBox, null, data.message || "Import refusé.", data.errors || []);
          api.showNotification(data.message || err.message || "Import refusé.", "error");
          setBusy(submit, false);
        })
        .then(function () {
          setBusy(submit, false);
        });
    });
  }

  function handleManual(form) {
    var submit = form.querySelector('[type="submit"]');
    var faculty = form.querySelector("[data-department-target]");

    if (faculty) {
      faculty.addEventListener("change", function () {
        var target = document.querySelector(faculty.getAttribute("data-department-target"));
        var url = faculty.getAttribute("data-departments-url");
        if (!target) return;
        target.disabled = true;
        target.innerHTML = '<option value="">Chargement…</option>';
        api
          .apiFetch(url + "?faculty=" + encodeURIComponent(faculty.value))
          .then(function (result) {
            var options = ['<option value="">Sélectionnez un département</option>'];
            (result.data.departments || []).forEach(function (dept) {
              options.push('<option value="' + dept.id + '">' + escapeHtml(dept.name) + "</option>");
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
      setBusy(submit, true);
      api
        .apiFetch(form.getAttribute("data-create-url"), {
          method: "POST",
          body: new FormData(form),
        })
        .then(function (result) {
          api.closeModal();
          api.showNotification(result.data.message || "Compte créé.", "success");
        })
        .catch(function (err) {
          var data = err.data || {};
          api.showNotification(data.message || err.message || "Création impossible.", "error");
          setBusy(submit, false);
        })
        .then(function () {
          setBusy(submit, false);
        });
    });
  }

  /* ---------------------------------------------------------------- */
  /* Champ « Titre » conditionnel au rôle (Étudiant / Enseignant)      */
  /* ---------------------------------------------------------------- */

  // Rôles enseignants connus : « teachers » (création manuelle) et
  // « teacher » (AdminUserForm de la console).
  var TEACHER_ROLE_VALUES = { teacher: 1, teachers: 1 };

  /**
   * Affiche/masque le bloc `[data-title-field]` selon le rôle sélectionné :
   *   - Étudiant → bloc retiré du flux (classe + attribut `hidden`) et
   *     contrôle `disabled` (exclu de FormData et de la validation HTML) ;
   *   - Enseignant → bloc ré-affiché, replacé juste après le champ Rôle,
   *     donc avant toutes les autres informations.
   * Idempotent (bascule unique par formulaire), branché au chargement du
   * document comme à chaque injection de modale.
   */
  function wireRoleTitle(form) {
    if (!form || form.dataset.roleTitleWired) return;
    var titleField = form.querySelector("[data-title-field]");
    if (!titleField) return;

    var roleSelect =
      form.querySelector("[data-role-select]") ||
      form.querySelector('[data-field="role"] select') ||
      form.querySelector('[name="role"]') ||
      form.querySelector('[name="entity"]');
    if (!roleSelect) return;

    form.dataset.roleTitleWired = "1";
    var control = titleField.querySelector("select, input");

    function placeTitleAfterRole() {
      var roleWrapper =
        roleSelect.closest("[data-field]") || roleSelect.parentElement;
      if (roleWrapper && titleField.previousElementSibling !== roleWrapper) {
        roleWrapper.insertAdjacentElement("afterend", titleField);
      }
    }

    function sync() {
      var isTeacher =
        TEACHER_ROLE_VALUES[(roleSelect.value || "").toLowerCase()] === 1;
      if (isTeacher) placeTitleAfterRole();
      titleField.classList.toggle("hidden", !isTeacher);
      titleField.toggleAttribute("hidden", !isTeacher);
      titleField.setAttribute("aria-hidden", isTeacher ? "false" : "true");
      if (control) {
        control.disabled = !isTeacher;
        if (!isTeacher) control.value = "";
      }
    }

    roleSelect.addEventListener("change", sync);
    sync();
  }

  function wire(root) {
    var importForm = root.querySelector("#admin-import-form");
    if (importForm && !importForm.dataset.wired) {
      importForm.dataset.wired = "1";
      handleImport(importForm);
    }
    var manualForm = root.querySelector("#admin-manual-form");
    if (manualForm && !manualForm.dataset.wired) {
      manualForm.dataset.wired = "1";
      handleManual(manualForm);
    }
    // Champ Titre conditionnel (formulaire manuel + formulaires de console).
    if (root.querySelectorAll) {
      root.querySelectorAll("[data-title-field]").forEach(function (field) {
        wireRoleTitle(field.closest("form"));
      });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    wire(document);
  });

  // Fragments injectés dans #spa-viewport : recâbler les formulaires de
  // console injectés par navigation sans rechargement de page.
  var previousContentHook = api.onContentLoaded;
  api.onContentLoaded = function (body) {
    if (typeof previousContentHook === "function") previousContentHook(body);
    wire(body);
  };

  var previousHook = api.onModalContentLoaded;
  api.onModalContentLoaded = function (body) {
    if (typeof previousHook === "function") previousHook(body);
    wire(body);
  };
})();
