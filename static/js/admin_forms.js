/**
 * admin_forms.js — formulaires de la console super-admin.
 *
 *   - #admin-import-form : import en deux phases — aperçu multipart ETL
 *     (rapport {line, message} ligne à ligne, aucune écriture) puis
 *     confirmation d'écriture via un jeton signé ;
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

  /** Met à jour une pastille de compteur du rapport (data-stat="valid"…). */
  function setStat(form, name, value) {
    var el = form.querySelector('[data-stat="' + name + '"]');
    if (el) el.textContent = String(value);
  }

  /**
   * Import en deux phases :
   *   1. « Valider le fichier » → POST preview (rapport ligne à ligne, aucune écriture)
   *   2. « Confirmer l'import » → POST commit (jeton signé, écriture atomique)
   * Les lignes en erreur/doublon sont bloquantes, sauf contrôle explicite
   * « n'enregistrer que les lignes valides ».
   */
  function handleImport(form) {
    var submit = form.querySelector('[type="submit"]');
    var confirmBtn = form.querySelector("#import-confirm");
    var restartBtn = form.querySelector("#import-restart");
    var errorBox = form.querySelector("#import-errors");
    var report = form.querySelector("#import-report");
    var reportTitle = form.querySelector("#import-report-title");
    var reportSummary = form.querySelector("#import-report-summary");
    var sampleBlock = form.querySelector("#import-sample-block");
    var sampleList = form.querySelector("#import-sample-list");
    var skipBlock = form.querySelector("#import-skip-block");
    var skipCheck = form.querySelector("#import-skip-invalid");
    var skipLabel = form.querySelector("#import-skip-label");
    var phaseHint = form.querySelector("#import-phase-hint");
    var entitySelect = form.querySelector("#import-entity");
    var state = { token: null, issues: 0 };

    function syncSkip() {
      if (!confirmBtn || !skipCheck) return;
      confirmBtn.disabled = state.issues > 0 && !skipCheck.checked;
    }

    function resetToUpload() {
      state = { token: null, issues: 0 };
      setStat(form, "valid", 0);
      setStat(form, "errors", 0);
      setStat(form, "duplicates", 0);
      var card = form.querySelector("#import-report-card");
      if (card) {
        card.classList.remove("border-emerald-200", "bg-emerald-50");
        card.classList.add("border-slate-200", "bg-slate-50");
      }
      if (report) report.classList.add("hidden");
      if (errorBox) errorBox.classList.add("hidden");
      if (skipBlock) skipBlock.classList.add("hidden");
      if (confirmBtn) confirmBtn.classList.add("hidden");
      if (restartBtn) restartBtn.classList.add("hidden");
      if (skipCheck) skipCheck.checked = false;
      if (phaseHint) phaseHint.classList.remove("hidden");
      if (submit) submit.classList.remove("hidden");
      syncSkip();
    }

    // Modèle téléchargeable toujours aligné sur le type de comptes choisi.
    function syncTemplateLinks() {
      var base = form.getAttribute("data-template-url");
      if (!base || !entitySelect) return;
      var csv = form.querySelector("#import-template-link");
      var xlsx = form.querySelector("#import-template-xlsx-link");
      var query = "?entity=" + encodeURIComponent(entitySelect.value);
      if (csv) csv.setAttribute("href", base + query);
      if (xlsx) xlsx.setAttribute("href", base + query + "&format=xlsx");
    }
    if (entitySelect) entitySelect.addEventListener("change", syncTemplateLinks);
    syncTemplateLinks();
    if (skipCheck) skipCheck.addEventListener("change", syncSkip);

    if (restartBtn) {
      restartBtn.addEventListener("click", function () {
        var input = form.querySelector("#import-file");
        if (input) input.value = "";
        resetToUpload();
        if (input) input.focus();
      });
    }

    if (confirmBtn) {
      confirmBtn.addEventListener("click", function () {
        if (!state.token) return;
        var body = new FormData();
        var field = entitySelect || form.querySelector('[name="entity"]');
        if (field) body.append("entity", field.value);
        var strict = form.querySelector('[name="strict_placement"]');
        if (strict && strict.checked) body.append("strict_placement", "true");
        var university = form.querySelector('[name="university"]');
        if (university && university.value) body.append("university", university.value);
        body.append("token", state.token);
        if (skipCheck && skipCheck.checked) body.append("skip_invalid", "true");

        setBusy(confirmBtn, true);
        api
          .apiFetch(form.getAttribute("data-commit-url"), { method: "POST", body: body })
          .then(function (result) {
            api.closeModal();
            var skipped = result.data.skipped || 0;
            api.showNotification(
              (result.data.message || "Import réussi.") +
                (skipped ? " (" + skipped + " ligne(s) ignorée(s))" : ""),
              "success"
            );
          })
          .catch(function (err) {
            var data = err.data || {};
            renderErrors(errorBox, null, data.message || "Import refusé.", data.errors || []);
            api.showNotification(data.message || err.message || "Import refusé.", "error");
          })
          .then(function () {
            setBusy(confirmBtn, false);
          });
      });
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (errorBox) errorBox.classList.add("hidden");
      if (report) report.classList.add("hidden");
      setBusy(submit, true);

      api
        .apiFetch(form.getAttribute("data-import-url"), {
          method: "POST",
          body: new FormData(form),
        })
        .then(function (result) {
          var data = result.data || {};
          var errorCount = (data.errors || []).length;
          var duplicateCount = (data.duplicates || []).length;
          var issues = errorCount + duplicateCount;
          var valid = data.valid || 0;
          state = { token: data.token || null, issues: issues };

          // Compteurs du rapport (pastilles colorées).
          setStat(form, "valid", valid);
          setStat(form, "errors", errorCount);
          setStat(form, "duplicates", duplicateCount);

          var statErrors = form.querySelector("[data-stat-errors]");
          var statDuplicates = form.querySelector("[data-stat-duplicates]");
          if (statErrors) statErrors.classList.toggle("hidden", errorCount === 0);
          if (statDuplicates) statDuplicates.classList.toggle("hidden", duplicateCount === 0);

          if (reportTitle) {
            reportTitle.textContent =
              valid > 0 && issues === 0
                ? "Fichier valide — prêt à importer"
                : "Aperçu du fichier — " + valid + " ligne(s) à importer";
          }
          if (reportSummary) {
            reportSummary.textContent =
              issues > 0
                ? "Rien n'a encore été enregistré. Corrigez le fichier puis rechargez-le, ou cochez l'import des seules lignes valides."
                : "Rien n'a encore été enregistré. Cliquez sur « Importer » pour créer les " +
                  valid + " compte(s).";
          }
          var card = form.querySelector("#import-report-card");
          if (card) {
            card.classList.toggle("border-emerald-200", issues === 0);
            card.classList.toggle("bg-emerald-50", issues === 0);
            card.classList.toggle("border-slate-200", issues > 0);
            card.classList.toggle("bg-slate-50", issues > 0);
          }

          if (sampleList) {
            sampleList.innerHTML = (data.sample || [])
              .slice(0, 10)
              .map(function (row) {
                return "<li>" + escapeHtml(row.MATRICULE || "") + " — " +
                  escapeHtml(row.NOM || "") + " " + escapeHtml(row.PRENOM || "") +
                  " · " + escapeHtml(row.EMAIL || "") + "</li>";
              })
              .join("");
          }
          if (sampleBlock) sampleBlock.classList.toggle("hidden", !valid);
          if (report) report.classList.remove("hidden");

          renderErrors(
            errorBox,
            null,
            issues > 0 ? "Lignes à corriger avant confirmation" : "",
            (data.errors || []).concat(data.duplicates || [])
          );

          // Fichier propre : bouton « Importer » seul, aucun bouton de correction.
          if (skipBlock) {
            skipBlock.classList.toggle("hidden", issues === 0);
            skipBlock.classList.add("flex");
            if (skipLabel) {
              skipLabel.textContent =
                "Ignorer les " + issues + " ligne(s) en erreur ou en doublon et n'enregistrer " +
                "que les " + valid + " ligne(s) valide(s).";
            }
          }
          if (submit) submit.classList.add("hidden");
          if (restartBtn) restartBtn.classList.toggle("hidden", issues === 0);
          if (confirmBtn) {
            confirmBtn.classList.remove("hidden");
            confirmBtn.disabled = !valid || issues > 0;
          }
          syncSkip();
          api.showNotification(
            valid + " ligne(s) valide(s) sur " + data.total +
              (issues ? " — " + issues + " à corriger." : " — prêt à importer."),
            issues ? "error" : "success"
          );
        })
        .catch(function (err) {
          var data = err.data || {};
          renderErrors(errorBox, null, data.message || "Import refusé.", data.errors || []);
          api.showNotification(data.message || err.message || "Import refusé.", "error");
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
