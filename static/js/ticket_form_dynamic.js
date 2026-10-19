/**
 * ticket_form_dynamic.js — formulaire dynamique de nouvelle requête.
 *
 * `fetchFormConfiguration(problemTypeId)` interroge l'endpoint form-config et
 * reconstruit la zone #dynamic-fields : sélection d'UE (si `requires_course`),
 * sélection d'enseignant (sinon), champs dynamiques du type (FormField +
 * ConditionalRule : afficher/masquer/obligatoire), puis une zone d'upload par
 * règle de pièce jointe (marquée * si obligatoire). Aucun rechargement de page.
 *
 * Les valeurs des champs dynamiques sont sérialisées en JSON dans le champ
 * caché #ticket-form-data (name="form_data") avant soumission.
 */
(function () {
  "use strict";

  var api = window.UnivReq;
  var DYN_PREFIX = "dyn_";

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

  /* -------------------- Champs dynamiques (FormField) -------------------- */

  function dynamicFieldHtml(field) {
    var name = DYN_PREFIX + field.key;
    var required = !!field.is_required;
    var marker = required ? ' <span class="text-red-600" aria-hidden="true">*</span>' : "";
    var help = field.help_text
      ? '<p class="helper">' + escapeHtml(field.help_text) + "</p>"
      : "";
    var head =
      '<label class="label" for="field-' + name + '">' +
      escapeHtml(field.label) + marker + "</label>";
    var input;

    switch (field.field_type) {
      case "textarea":
        input =
          '<textarea class="field min-h-20" id="field-' + name + '" name="' + name +
          '" rows="3"' + (required ? " required" : "") +
          ' data-dyn-key="' + escapeHtml(field.key) + '"></textarea>';
        break;
      case "select":
        var options = '<option value="">— Sélectionnez —</option>';
        (field.choices || []).forEach(function (choice) {
          options +=
            '<option value="' + escapeHtml(choice) + '">' +
            escapeHtml(choice) + "</option>";
        });
        input =
          '<select class="field" id="field-' + name + '" name="' + name + '"' +
          (required ? " required" : "") +
          ' data-dyn-key="' + escapeHtml(field.key) + '">' + options + "</select>";
        break;
      case "checkbox":
        return (
          '<div data-dyn-wrapper="' + escapeHtml(field.key) + '" class="flex items-center gap-2">' +
          '<input type="checkbox" id="field-' + name + '" name="' + name +
          '" value="1" class="h-5 w-5 rounded border-slate-300 text-navy focus:ring-navy"' +
          ' data-dyn-key="' + escapeHtml(field.key) + '">' +
          '<label class="label !mb-0" for="field-' + name + '">' +
          escapeHtml(field.label) + marker + "</label>" + help + "</div>"
        );
      case "number":
        input =
          '<input class="field" type="number" id="field-' + name + '" name="' + name + '"' +
          (required ? " required" : "") +
          ' data-dyn-key="' + escapeHtml(field.key) + '">';
        break;
      case "date":
        input =
          '<input class="field" type="date" id="field-' + name + '" name="' + name + '"' +
          (required ? " required" : "") +
          ' data-dyn-key="' + escapeHtml(field.key) + '">';
        break;
      default:
        input =
          '<input class="field" type="text" id="field-' + name + '" name="' + name + '"' +
          (required ? " required" : "") +
          ' data-dyn-key="' + escapeHtml(field.key) + '">';
    }
    return (
      '<div data-dyn-wrapper="' + escapeHtml(field.key) + '">' + head + input + help + "</div>"
    );
  }

  /* ------------- Règles conditionnelles (afficher/masquer/obliger) ------------- */

  function ruleMatches(rule, rawValue) {
    var value = String(rawValue == null ? "" : rawValue).trim();
    var target = String(rule.value == null ? "" : rule.value).trim();
    switch (rule.operator) {
      case "is_set":
        return value !== "";
      case "not_equals":
        return value.toLowerCase() !== target.toLowerCase();
      case "contains":
        return value.toLowerCase().indexOf(target.toLowerCase()) !== -1;
      default:
        return value.toLowerCase() === target.toLowerCase();
    }
  }

  function readDynamicValues(root) {
    var values = {};
    Array.prototype.forEach.call(root.querySelectorAll("[data-dyn-key]"), function (el) {
      if (el.type === "checkbox") {
        values[el.getAttribute("data-dyn-key")] = el.checked;
      } else {
        values[el.getAttribute("data-dyn-key")] = el.value;
      }
    });
    return values;
  }

  function applyDynamicRules(root, data) {
    var values = readDynamicValues(root);
    var rules = data.rules || [];
    var visible = {};
    var required = {};
    (data.fields || []).forEach(function (field) {
      visible[field.key] = true;
      required[field.key] = !!field.is_required;
    });
    rules.forEach(function (rule) {
      var source = values[rule.depends_on];
      if (source === undefined) return;
      if (!ruleMatches(rule, source)) return;
      if (rule.action === "hide") visible[rule.field] = false;
      else if (rule.action === "show") visible[rule.field] = true;
      else if (rule.action === "require") required[rule.field] = true;
    });
    Object.keys(visible).forEach(function (key) {
      var wrapper = root.querySelector('[data-dyn-wrapper="' + key + '"]');
      if (!wrapper) return;
      wrapper.classList.toggle("hidden", !visible[key]);
      var control = wrapper.querySelector("[data-dyn-key]");
      if (control) {
        if (required[key]) control.setAttribute("required", "required");
        else control.removeAttribute("required");
        // Un champ masqué ne doit pas conserver une valeur qui serait soumise.
        if (!visible[key] && control.type === "checkbox") control.checked = false;
        else if (!visible[key] && control.tagName !== "SELECT") control.value = "";
      }
    });
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

    var fields = data.fields || [];
    if (fields.length) {
      html +=
        '<hr class="border-slate-100"><p class="text-sm font-semibold text-navy-dark">' +
        escapeHtml("Informations requises") +
        "</p>";
      fields.forEach(function (field) {
        html += dynamicFieldHtml(field);
      });
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

  /** Sérialise les champs dynamiques visibles dans le champ caché form_data. */
  function syncFormData(form) {
    var hidden = form.querySelector("#ticket-form-data");
    var container = form.querySelector("#dynamic-fields");
    if (!hidden || !container) return;
    var values = {};
    Array.prototype.forEach.call(
      container.querySelectorAll("[data-dyn-key]"),
      function (el) {
        var wrapper = el.closest("[data-dyn-wrapper]");
        if (wrapper && wrapper.classList.contains("hidden")) return;
        var key = el.getAttribute("data-dyn-key");
        if (el.type === "checkbox") values[key] = el.checked;
        else values[key] = el.value.trim();
      }
    );
    hidden.value = JSON.stringify(values);
  }

  function fetchFormConfiguration(problemTypeId, draftValues) {
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
        // Reprise d'un brouillon : valeurs restaurées puis règles réévaluées.
        if (draftValues) {
          Object.keys(draftValues).forEach(function (key) {
            var el = container.querySelector('[data-dyn-key="' + key + '"]');
            if (!el) return;
            if (el.type === "checkbox") el.checked = !!draftValues[key];
            else el.value = draftValues[key];
          });
        }
        applyDynamicRules(container, data);
        container._configData = data;
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
    if (trigger) {
      var value = trigger.value;
      var container = document.getElementById("dynamic-fields");
      if (!value) {
        if (container) container.innerHTML = "";
        return;
      }
      fetchFormConfiguration(value);
      return;
    }
    // Réévaluation des règles conditionnelles à chaque changement d'un champ dynamique.
    var dyn = event.target.closest("[data-dyn-key]");
    if (dyn) {
      var box = dyn.closest("#dynamic-fields");
      if (box && box._configData) applyDynamicRules(box, box._configData);
    }
  });

  document.addEventListener("input", function (event) {
    var dyn = event.target.closest("[data-dyn-key]");
    if (!dyn) return;
    var box = dyn.closest("#dynamic-fields");
    if (box && box._configData) applyDynamicRules(box, box._configData);
  });

  // Exposé pour le sérialiseur de soumission et les tests.
  api.fetchFormConfiguration = fetchFormConfiguration;
  api.syncTicketFormData = syncFormData;
  api.applyDynamicRules = applyDynamicRules;
})();
