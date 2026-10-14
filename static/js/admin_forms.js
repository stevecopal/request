/**
 * admin_forms.js — formulaires de la console super-admin.
 *
 *   - #admin-import-form : upload multipart ETL → rendu des erreurs {line, message} ;
 *   - #admin-manual-form : création manuelle d'un compte (cascade faculté/département).
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
  }

  document.addEventListener("DOMContentLoaded", function () {
    wire(document);
  });

  var previousHook = api.onModalContentLoaded;
  api.onModalContentLoaded = function (body) {
    if (typeof previousHook === "function") previousHook(body);
    wire(body);
  };
})();
