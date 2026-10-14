/**
 * ticket_form_dynamic.js — formulaire dynamique de nouvelle requête.
 *
 * `fetchFormConfiguration(problemTypeId)` interroge l'endpoint form-config et
 * reconstruit la zone #dynamic-fields : sélection d'UE (si `requires_course`),
 * sélection d'enseignant (sinon), puis une zone d'upload par règle de pièce
 * jointe (marquée * si obligatoire). Aucun rechargement de page.
 */
(function () {
  "use strict";

  var api = window.UnivReq;

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.textContent = value == null ? "" : value;
    return div.innerHTML;
  }

  function skeleton() {
    return (
      '<div class="space-y-3" aria-hidden="true">' +
      '<div class="skeleton h-12 w-full"></div>' +
      '<div class="skeleton h-12 w-full"></div>' +
      "</div>"
    );
  }

  function selectField(name, label, options, required) {
    var html =
      '<div><label class="label" for="field-' + name + '">' +
      escapeHtml(label) +
      (required ? ' <span class="text-red-600" aria-hidden="true">*</span>' : "") +
      "</label>" +
      '<select class="field" id="field-' + name + '" name="' + name + '"' +
      (required ? " required" : "") +
      ">" +
      '<option value="">' + escapeHtml("— Sélectionnez —") + "</option>";
    options.forEach(function (option) {
      html +=
        '<option value="' + option.id + '">' + escapeHtml(option.label) + "</option>";
    });
    html += "</select></div>";
    return html;
  }

  function fileField(config) {
    var required = !!config.is_required;
    return (
      '<div><label class="label" for="file-' + config.id + '">' +
      escapeHtml(config.label) +
      (required ? ' <span class="text-red-600" aria-hidden="true">*</span>' : "") +
      "</label>" +
      '<input class="field file:mr-3 file:rounded-lg file:border-0 file:bg-navy file:text-white file:px-3 file:py-2" ' +
      'id="file-' + config.id + '" name="attachment_' + config.id + '" type="file"' +
      (required ? " required" : "") +
      "></div>"
    );
  }

  function buildFields(data) {
    var html = "";
    if (data.requires_course) {
      html += selectField(
        "course_id",
        "Unité d'enseignement",
        (data.courses || []).map(function (c) {
          return { id: c.id, label: c.code + " — " + c.name };
        }),
        true
      );
    } else {
      html += selectField(
        "teacher_id",
        "Enseignant concerné",
        (data.teachers || []).map(function (t) {
          return { id: t.id, label: t.label };
        }),
        true
      );
    }

    var attachments = data.attachments || [];
    if (attachments.length) {
      html +=
        '<hr class="border-slate-100"><p class="text-sm font-semibold text-navy-dark">' +
        escapeHtml("Pièces justificatives") +
        "</p>";
      attachments.forEach(function (config) {
        html += fileField(config);
      });
    }
    return html;
  }

  function fetchFormConfiguration(problemTypeId) {
    var form = document.getElementById("ticket-form");
    var container = document.getElementById("dynamic-fields");
    var hint = document.getElementById("problem-type-hint");
    if (!form || !container) return Promise.resolve();

    container.innerHTML = skeleton();

    return api
      .apiFetch(
        form.getAttribute("data-form-config-url") +
          "?problem_type_id=" +
          encodeURIComponent(problemTypeId)
      )
      .then(function (result) {
        var data = result.data;
        container.innerHTML = buildFields(data);
        if (hint) hint.textContent = (data.problem_type && data.problem_type.description) || "";
      })
      .catch(function (err) {
        var errorBox = document.getElementById("ticket-error");
        var payload = err.data || {};
        container.innerHTML = "";
        if (payload.code === "onboarding_required") {
          api.closeModal();
          api.loadIntoModal("/accounts/onboarding/", { title: "Compléter mon profil" });
          return;
        }
        if (errorBox) {
          errorBox.textContent = payload.message || err.message || "Configuration indisponible.";
          errorBox.classList.remove("hidden");
        }
        api.showNotification(payload.message || err.message || "Configuration indisponible.", "error");
      });
  }

  document.addEventListener("change", function (event) {
    var trigger = event.target.closest("[data-form-config-trigger]");
    if (!trigger) return;
    var value = trigger.value;
    var container = document.getElementById("dynamic-fields");
    if (!value) {
      if (container) container.innerHTML = "";
      return;
    }
    fetchFormConfiguration(value);
  });

  // Exposé pour tests / usages futurs.
  api.fetchFormConfiguration = fetchFormConfiguration;
})();
