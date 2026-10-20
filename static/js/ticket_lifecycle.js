/**
 * ticket_lifecycle.js — cycle de vie des requêtes (soumission + décisions).
 *
 *   - #ticket-form (étudiant)   : étape 1 saisie → étape 2 prévisualisation
 *     → envoi multipart unique, toaster, rechargement du flux ;
 *   - #student-reply-form        : réponse à une demande MORE_INFO ;
 *   - #feed-filter (étudiant)    : recherche/filtre/pagination sans rechargement ;
 *   - [data-notifications-read]  : marquage « lu » + badge de navigation ;
 *   - [data-ticket-select]       : charge le détail dans #teacher-ticket-detail ;
 *   - [data-status-action]       : transition directe (Démarrer l'analyse…) ;
 *   - #teacher-decision-form     : Accepter (motif) / Rejeter (motif) /
 *     Infos supplémentaires (note obligatoire) ;
 *   - #teacher-transfer-form     : transmission à un autre enseignant / service.
 */
(function () {
  "use strict";

  var api = window.UnivReq;
  var lastDetailUrl = null;
  var previewConfirmed = false;

  function setBusy(button, busy) {
    if (!button) return;
    button.disabled = busy;
    button.setAttribute("aria-busy", busy ? "true" : "false");
  }

  function errorBoxOf(box, message) {
    if (!box) return;
    box.textContent = message;
    box.classList.remove("hidden");
  }

  /* ---------------------------- ÉTUDIANT ---------------------------- */

  var DRAFT_DEFAULT_KEY = "univreq_ticket_draft";

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.textContent = value == null ? "" : value;
    return div.innerHTML;
  }

  function collectDraft(form) {
    var subject = form.querySelector("#ticket-subject");
    var description = form.querySelector("#ticket-description");
    var typeSelect = form.querySelector("#problem-type");
    var yearSelect = form.querySelector("#academic-year");
    var course = form.querySelector('[name="course_id"]');
    var teacher = form.querySelector('[name="teacher_id"]');
    var container = form.querySelector("#dynamic-fields");
    var dyn = {};
    if (container) {
      Array.prototype.forEach.call(
        container.querySelectorAll("[data-dyn-key]"),
        function (el) {
          var key = el.getAttribute("data-dyn-key");
          dyn[key] = el.type === "checkbox" ? el.checked : el.value;
        }
      );
    }
    return {
      saved_at: new Date().toISOString(),
      problem_type_id: typeSelect ? typeSelect.value : "",
      academic_year: yearSelect ? yearSelect.value : "",
      subject: subject ? subject.value : "",
      description: description ? description.value : "",
      course_id: course ? course.value : "",
      teacher_id: teacher ? teacher.value : "",
      dyn: dyn,
    };
  }

  function restoreDraft(form) {
    var key = form.getAttribute("data-draft-key") || DRAFT_DEFAULT_KEY;
    var raw;
    try {
      raw = window.localStorage.getItem(key);
    } catch (err) {
      return;
    }
    if (!raw) return;
    var draft;
    try {
      draft = JSON.parse(raw);
    } catch (err) {
      return;
    }
    if (!draft || typeof draft !== "object") return;

    function setValue(selector, value) {
      var el = form.querySelector(selector);
      if (el && value) el.value = value;
    }
    setValue("#ticket-subject", draft.subject);
    setValue("#ticket-description", draft.description);
    setValue("#academic-year", draft.academic_year);

    var typeSelect = form.querySelector("#problem-type");
    if (typeSelect && draft.problem_type_id) {
      typeSelect.value = draft.problem_type_id;
      if (typeSelect.value && api.fetchFormConfiguration) {
        api.fetchFormConfiguration(draft.problem_type_id).then(function () {
          var container = form.querySelector("#dynamic-fields");
          if (!container) return;
          // UE / enseignant restaurés après construction de la zone dynamique.
          if (draft.course_id) {
            var course = container.querySelector('[name="course_id"]');
            if (course) course.value = draft.course_id;
          }
          if (draft.teacher_id) {
            var teacher = container.querySelector('[name="teacher_id"]');
            if (teacher) teacher.value = draft.teacher_id;
          }
          var dyn = draft.dyn || {};
          Object.keys(dyn).forEach(function (k) {
            var el = container.querySelector('[data-dyn-key="' + k + '"]');
            if (!el) return;
            if (el.type === "checkbox") el.checked = !!dyn[k];
            else el.value = dyn[k];
          });
          if (container._configData && api.applyDynamicRules) {
            api.applyDynamicRules(container, container._configData);
          }
        });
      }
    }
    var status = form.querySelector("#ticket-draft-status");
    if (status) {
      status.textContent = "Brouillon restauré (sauvegardé le " +
        (draft.saved_at ? new Date(draft.saved_at).toLocaleString() : "—") + ").";
      status.classList.remove("hidden");
    }
  }

  function wireDraftButton(form) {
    var button = form.querySelector("#ticket-draft-save");
    if (!button || button.dataset.wired) return;
    button.dataset.wired = "1";
    button.addEventListener("click", function () {
      var key = form.getAttribute("data-draft-key") || DRAFT_DEFAULT_KEY;
      try {
        window.localStorage.setItem(key, JSON.stringify(collectDraft(form)));
        var status = form.querySelector("#ticket-draft-status");
        if (status) {
          status.textContent = "Brouillon enregistré sur cet appareil.";
          status.classList.remove("hidden");
        }
        api.showNotification("Brouillon enregistré sur cet appareil.", "success");
      } catch (err) {
        api.showNotification("Enregistrement du brouillon impossible.", "error");
      }
    });
  }

  function clearDraft(form) {
    var key = form.getAttribute("data-draft-key") || DRAFT_DEFAULT_KEY;
    try {
      window.localStorage.removeItem(key);
    } catch (err) {
      /* stockage indisponible : sans conséquence */
    }
  }

  function fillPreview(form) {
    var list = form.querySelector("#ticket-preview-list");
    if (!list) return;

    var typeSelect = form.querySelector("#problem-type");
    var yearSelect = form.querySelector("#academic-year");
    var subject = form.querySelector("#ticket-subject");
    var description = form.querySelector("#ticket-description");
    var course = form.querySelector('[name="course_id"]');
    var teacher = form.querySelector('[name="teacher_id"]');

    var rows = [];
    if (subject) rows.push({ term: "Objet", value: subject.value.trim() });
    rows.push({ term: "Type de problème", value: typeSelect ? typeSelect.selectedOptions[0].text : "" });
    rows.push({ term: "Année académique", value: yearSelect ? yearSelect.value : "" });
    rows.push({
      term: course ? "Unité d'enseignement" : "Enseignant concerné",
      value: course || teacher ? (course || teacher).selectedOptions[0].text : "",
    });

    // Champs dynamiques renseignés (libellé → valeur).
    var container = form.querySelector("#dynamic-fields");
    if (container) {
      Array.prototype.forEach.call(
        container.querySelectorAll("[data-dyn-wrapper]"),
        function (wrapper) {
          if (wrapper.classList.contains("hidden")) return;
          var control = wrapper.querySelector("[data-dyn-key]");
          if (!control) return;
          var label = wrapper.querySelector("label");
          var value;
          if (control.type === "checkbox") {
            value = control.checked ? "Oui" : "";
          } else if (control.tagName === "SELECT") {
            value = control.selectedOptions.length ? control.selectedOptions[0].text : "";
            if (value.indexOf("— Sélectionnez") === 0) value = "";
          } else {
            value = control.value.trim();
          }
          if (value) rows.push({ term: label ? label.textContent.replace("*", "").trim() : control.name, value: value });
        }
      );
    }

    list.innerHTML = rows
      .map(function (row) {
        if (!row.value) return "";
        return (
          '<div class="flex justify-between gap-4">' +
          '<dt class="text-slate-500 shrink-0">' +
          escapeHtml(row.term) +
          "</dt>" +
          '<dd class="font-medium text-navy-dark text-right">' +
          escapeHtml(row.value) +
          "</dd>" +
          "</div>"
        );
      })
      .join("");

    // Pièces jointes sélectionnées : nom + aperçu ouvrable dans un nouvel onglet
    // (le document est consultable avant même l'envoi de la requête).
    (list.__previewUrls || []).forEach(function (url) {
      URL.revokeObjectURL(url);
    });
    list.__previewUrls = [];

    var files = [];
    Array.prototype.forEach.call(
      form.querySelectorAll('input[type="file"]'),
      function (input) {
        Array.prototype.forEach.call(input.files || [], function (file) {
          files.push(file);
        });
      }
    );

    files.forEach(function (file) {
      var row = document.createElement("div");
      row.className = "flex items-start justify-between gap-4";

      var term = document.createElement("dt");
      term.className = "text-slate-500 shrink-0";
      term.textContent = "Pièce jointe";

      var value = document.createElement("dd");
      value.className = "font-medium text-navy-dark text-right min-w-0";

      var name = document.createElement("span");
      name.className = "block truncate";
      name.textContent = file.name;
      value.appendChild(name);

      var link = document.createElement("a");
      var url = URL.createObjectURL(file);
      list.__previewUrls.push(url);
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener";
      link.className = "mt-0.5 inline-block text-xs font-semibold text-navy-light hover:underline";
      link.textContent = "Consulter le document";
      value.appendChild(link);

      row.appendChild(term);
      row.appendChild(value);
      list.appendChild(row);
    });

    list.insertAdjacentHTML(
      "beforeend",
      '<div class="pt-1 border-t border-navy-100">' +
        '<p class="label !mb-0">Commentaires</p>' +
        '<p class="text-sm text-navy-dark whitespace-pre-line"></p>' +
        "</div>"
    );
    list.lastElementChild.querySelector("p:last-child").textContent = description
      ? description.value.trim()
      : "";
  }

  function showPreview(form, show) {
    var fields = form.querySelector("#ticket-form-fields");
    var preview = form.querySelector("#ticket-preview");
    var submit = form.querySelector("#ticket-submit");
    if (!fields || !preview || !submit) return;
    fields.classList.toggle("hidden", show);
    submit.classList.toggle("hidden", show);
    preview.classList.toggle("hidden", !show);
    if (show) {
      fillPreview(form);
      preview.focus();
    }
  }

  function handleTicketForm(form) {
    var submit = form.querySelector("#ticket-submit");
    var errorBox = form.querySelector("#ticket-error");
    var back = form.querySelector("#ticket-preview-back");

    wireDraftButton(form);
    restoreDraft(form);

    if (back) {
      back.addEventListener("click", function () {
        previewConfirmed = false;
        showPreview(form, false);
      });
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (errorBox) errorBox.classList.add("hidden");

      // Étape 1 → 2 : aucun envoi tant que l'étudiant n'a pas confirmé.
      if (!previewConfirmed) {
        if (!form.checkValidity()) {
          form.reportValidity();
          return;
        }
        previewConfirmed = true;
        showPreview(form, true);
        return;
      }

      // Champs dynamiques sérialisés (JSON) avant la soumission multipart.
      if (api.syncTicketFormData) api.syncTicketFormData(form);
      var body = new FormData(form);

      setBusy(submit, true);
      api
        .apiFetch(form.getAttribute("data-create-url"), {
          method: "POST",
          body: body,
        })
        .then(function (result) {
          previewConfirmed = false;
          clearDraft(form);
          api.closeModal();
          var data = result.data || {};
          var message = data.message || "Requête envoyée.";
          if (data.short_id) {
            message += " — N° de suivi : " + data.short_id;
          }
          api.showNotification(message, "success");
          var feed = form.getAttribute("data-feed-url");
          if (feed) api.loadFragment(feed, { pushState: false });
        })
        .catch(function (err) {
          previewConfirmed = false;
          showPreview(form, false);
          var payload = err.data || {};
          var message = payload.message || err.message || "Envoi impossible.";
          errorBoxOf(errorBox, message);
          api.showNotification(message, "error");
        })
        .then(function () {
          setBusy(submit, false);
        });
    });
  }

  /* -------------------- RÉPONSE ÉTUDIANT (MORE_INFO) -------------------- */

  function handleReplyForm(form) {
    var errorBox = form.querySelector("#reply-error");
    var submit = form.querySelector('[type="submit"]');

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (errorBox) errorBox.classList.add("hidden");
      var body = form.querySelector('[name="body"]');
      if (!body.value.trim()) {
        errorBoxOf(errorBox, "Votre réponse est obligatoire.");
        body.focus();
        return;
      }
      setBusy(submit, true);
      api
        .apiFetch(form.getAttribute("data-reply-url"), {
          method: "POST",
          body: new FormData(form),
        })
        .then(function (result) {
          api.showNotification(result.data.message || "Réponse transmise.", "success");
          var detail = form.getAttribute("data-detail-url");
          if (detail) api.loadFragment(detail, { pushState: false });
        })
        .catch(function (err) {
          var payload = err.data || {};
          var message = payload.message || err.message || "Envoi impossible.";
          errorBoxOf(errorBox, message);
          api.showNotification(message, "error");
        })
        .then(function () {
          setBusy(submit, false);
        });
    });
  }

  /* -------------------- FLUX ÉTUDIANT : RECHERCHE / FILTRES -------------------- */

  function handleFeedFilter(form) {
    if (form.dataset.wired) return;
    form.dataset.wired = "1";
    var base = form.getAttribute("data-feed-url");

    function currentQuery() {
      var params = new URLSearchParams();
      Array.prototype.forEach.call(
        form.querySelectorAll("input[name], select[name]"),
        function (control) {
          var value = (control.value || "").trim();
          if (value) params.set(control.name, value);
        }
      );
      return params.toString();
    }

    function apply() {
      var query = currentQuery();
      api.loadFragment(base + (query ? "?" + query : ""), {
        target: "#spa-viewport",
        pushState: true,
      });
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      apply();
    });
    // Application immédiate sur les listes déroulantes (statut, tri).
    Array.prototype.forEach.call(form.querySelectorAll("select"), function (select) {
      select.addEventListener("change", apply);
    });
  }

  /* --------------- BOÎTE ENSEIGNANT : RECHERCHE / FILTRES --------------- */

  /**
   * Formulaire #inbox-filter : recherche + filtres (statut, motif, faculté,
   * département, cours, dates). Sérialise tous les champs non vides, recharge
   * la liste dans #teacher-ticket-list (sans perdre le panneau de détail) et
   * synchronise l'URL du navigateur (partageable, bouton retour fonctionnel).
   */
  function handleInboxFilter(form) {
    if (form.dataset.wired) return;
    form.dataset.wired = "1";
    var listUrl = form.getAttribute("data-list-url");
    var inboxUrl = form.getAttribute("data-inbox-url") || window.location.pathname;

    function currentQuery() {
      var params = new URLSearchParams();
      Array.prototype.forEach.call(
        form.querySelectorAll("input[name], select[name]"),
        function (control) {
          var value = (control.value || "").trim();
          if (value) params.set(control.name, value);
        }
      );
      return params.toString();
    }

    function apply() {
      var query = currentQuery();
      var container = document.getElementById("teacher-ticket-list");
      if (container) container.setAttribute("data-active-qs", query);
      if (listUrl) {
        api.loadFragment(listUrl + (query ? "?" + query : ""), {
          target: "#teacher-ticket-list",
          pushState: false,
          keepScroll: true,
        });
      }
      // URL navigateur = boîte + filtres (pas l'URL du fragment liste).
      var pageUrl = inboxUrl + (query ? "?" + query : "");
      if (pageUrl !== window.location.pathname + window.location.search) {
        history.pushState({ fragment: pageUrl }, "", pageUrl);
      }
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      apply();
    });
    // Application immédiate sur les listes déroulantes (pas de clic « Filtrer »).
    Array.prototype.forEach.call(form.querySelectorAll("select"), function (select) {
      select.addEventListener("change", apply);
    });
  }

  /* -------------------- NOTIFICATIONS : MARQUAGE « LU » -------------------- */

  function updateUnreadBadges(count) {
    document.querySelectorAll("[data-unread-badge]").forEach(function (badge) {
      if (count > 0) {
        badge.textContent = String(count);
        badge.classList.remove("hidden");
      } else {
        badge.textContent = "";
        badge.classList.add("hidden");
      }
    });
  }

  function markNotificationsRead(button) {
    var url = button.getAttribute("data-read-url");
    if (!url) return;
    var ids = button.getAttribute("data-read-ids");
    var body = new FormData();
    if (ids) body.append("ids", ids);

    api
      .apiFetch(url, { method: "POST", body: body })
      .then(function (result) {
        if (typeof result.data.unread_notifications === "number") {
          updateUnreadBadges(result.data.unread_notifications);
        }
        // « Tout marquer lu » (sans navigation ticket) : recharge la liste.
        var refresh = button.getAttribute("data-refresh-url");
        if (refresh && !button.hasAttribute("data-fragment-src")) {
          api.loadFragment(refresh, { pushState: false });
        }
      })
      .catch(function (err) {
        api.showNotification(
          (err.data && err.data.message) || err.message || "Action impossible.",
          "error"
        );
      });
  }

  /* --------------------------- ENSEIGNANT --------------------------- */

  function loadDetail(url, opts) {
    var target = document.getElementById("teacher-ticket-detail");
    if (!target) return;
    opts = opts || {};
    lastDetailUrl = url;
    target.classList.remove("hidden");
    api.loadFragment(url, {
      target: "#teacher-ticket-detail",
      pushState: false,
      keepScroll: opts.keepScroll !== false,
    });
  }

  function refreshDetail() {
    if (lastDetailUrl) loadDetail(lastDetailUrl);
  }

  /**
   * Recharge la colonne liste de la boîte enseignant (cible #teacher-ticket-list)
   * en conservant les filtres actifs (data-active-qs) — pas de retour en haut
   * de page, panneau de détail intact.
   */
  function refreshInboxList() {
    var container = document.getElementById("teacher-ticket-list");
    if (!container) return;
    var url = container.getAttribute("data-list-url");
    if (!url) return;
    var qs = container.getAttribute("data-active-qs") || "";
    api.loadFragment(url + (qs ? "?" + qs : ""), {
      target: "#teacher-ticket-list",
      pushState: false,
      keepScroll: true,
    });
  }

  function submitStatus(button, status, reason, moreInfo, resolutionNote) {
    var url = button.getAttribute("data-status-url");
    var body = new FormData();
    body.append("ticket_id", button.getAttribute("data-ticket-id"));
    body.append("status", status);
    if (reason) body.append("rejection_reason", reason);
    if (moreInfo) body.append("more_info_request", moreInfo);
    if (resolutionNote) body.append("resolution_note", resolutionNote);

    setBusy(button, true);
    return api
      .apiFetch(url, { method: "POST", body: body })
      .then(function (result) {
        api.closeModal();
        api.showNotification(result.data.message || "Statut mis à jour.", "success");
        refreshDetail();
        refreshInboxList();
      })
      .catch(function (err) {
        api.showNotification(
          (err.data && err.data.message) || err.message || "Action impossible.",
          "error"
        );
      })
      .then(function () {
        setBusy(button, false);
      });
  }

  function handleDecisionForm(form) {
    var submit = form.querySelector('[type="submit"]');
    var errorBox = form.querySelector("#decision-error");

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var status = form.querySelector('[name="status"]').value;
      var reasonField = form.querySelector('[name="rejection_reason"]');
      var reason = reasonField ? reasonField.value.trim() : "";
      var infoField = form.querySelector('[name="more_info_request"]');
      var moreInfo = infoField ? infoField.value.trim() : "";
      var resolutionField = form.querySelector('[name="resolution_note"]');
      var resolutionNote = resolutionField ? resolutionField.value.trim() : "";

      if (status === "RESOLVED" && !resolutionNote) {
        errorBoxOf(errorBox, "La réponse à l'étudiant est obligatoire.");
        if (resolutionField) resolutionField.focus();
        return;
      }
      if (status === "REJECTED" && !reason) {
        errorBoxOf(errorBox, "Le motif du rejet est obligatoire.");
        if (reasonField) reasonField.focus();
        return;
      }
      if (status === "MORE_INFO" && !moreInfo) {
        errorBoxOf(errorBox, "La question posée à l'étudiant est obligatoire.");
        if (infoField) infoField.focus();
        return;
      }
      var fakeButton = submit;
      fakeButton.setAttribute("data-status-url", form.getAttribute("data-status-url"));
      fakeButton.setAttribute("data-ticket-id", form.querySelector('[name="ticket_id"]').value);
      setBusy(submit, true);

      submitStatus(fakeButton, status, reason, moreInfo, resolutionNote).then(function () {
        setBusy(submit, false);
      });
    });
  }

  /** Transmission enseignant → enseignant/service (avec motif + notifs). */
  function handleTeacherTransferForm(form) {
    var submit = form.querySelector('[type="submit"]');
    var errorBox = form.querySelector("#transfer-error");

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (errorBox) errorBox.classList.add("hidden");

      var teacher = form.querySelector('[name="to_teacher"]');
      var service = form.querySelector('[name="to_service"]');
      var reason = form.querySelector('[name="reason"]');
      if (!reason || !reason.value.trim()) {
        errorBoxOf(errorBox, "Le motif de la transmission est obligatoire.");
        if (reason) reason.focus();
        return;
      }
      if (
        (!teacher || !teacher.value) &&
        (!service || !service.value)
      ) {
        errorBoxOf(errorBox, "Choisissez un intervenant ou un service destinataire.");
        if (teacher) teacher.focus();
        return;
      }

      setBusy(submit, true);
      api
        .apiFetch(form.getAttribute("data-transfer-url"), {
          method: "POST",
          body: new FormData(form),
        })
        .then(function (result) {
          api.closeModal();
          api.showNotification(result.data.message || "Dossier transmis.", "success");
          // Le dossier peut ne plus être accessible : on revient à la boîte.
          var inbox = form.getAttribute("data-inbox-url");
          if (inbox) {
            api.loadFragment(inbox, { pushState: true });
          } else {
            refreshInboxList();
            refreshDetail();
          }
        })
        .catch(function (err) {
          var message =
            (err.data && err.data.message) || err.message || "Transmission impossible.";
          errorBoxOf(errorBox, message);
          api.showNotification(message, "error");
        })
        .then(function () {
          setBusy(submit, false);
        });
    });
  }

  /* ---------------------------- CÂBLAGE ---------------------------- */

  function wire(root) {
    var ticketForm = root.querySelector("#ticket-form");
    if (ticketForm && !ticketForm.dataset.wired) {
      ticketForm.dataset.wired = "1";
      handleTicketForm(ticketForm);
    }
    var decisionForm = root.querySelector("#teacher-decision-form");
    if (decisionForm && !decisionForm.dataset.wired) {
      decisionForm.dataset.wired = "1";
      handleDecisionForm(decisionForm);
    }
    var replyForm = root.querySelector("#student-reply-form");
    if (replyForm && !replyForm.dataset.wired) {
      replyForm.dataset.wired = "1";
      handleReplyForm(replyForm);
    }
    var transferForm = root.querySelector("#teacher-transfer-form");
    if (transferForm && !transferForm.dataset.wired) {
      transferForm.dataset.wired = "1";
      handleTeacherTransferForm(transferForm);
    }
    var feedFilter = root.querySelector("#feed-filter");
    if (feedFilter) handleFeedFilter(feedFilter);
    var inboxFilter = root.querySelector("#inbox-filter");
    if (inboxFilter) handleInboxFilter(inboxFilter);
  }

  document.addEventListener("DOMContentLoaded", function () {
    wire(document);
  });

  // Fragments injectés dans #spa-viewport (navigation sans rechargement).
  api.onContentLoaded = (function (previous) {
    return function (body) {
      if (typeof previous === "function") previous(body);
      wire(body);
    };
  })(api.onContentLoaded);

  var previousHook = api.onModalContentLoaded;
  api.onModalContentLoaded = function (body) {
    if (typeof previousHook === "function") previousHook(body);
    wire(body);
  };

  document.addEventListener("click", function (event) {
    var read = event.target.closest("[data-notifications-read]");
    if (read) {
      markNotificationsRead(read);
      if (!read.hasAttribute("data-fragment-src")) event.preventDefault();
      if (read.hasAttribute("data-fragment-src")) return; // la navigation gère le reste
    }

    var toggle = event.target.closest("[data-toggle-reason]");
    if (toggle) {
      event.preventDefault();
      var panelId = toggle.getAttribute("aria-controls");
      var panel = panelId ? document.getElementById(panelId) : null;
      if (panel) {
        var isOpen = !panel.classList.toggle("hidden");
        toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
      }
      return;
    }

    var select = event.target.closest("[data-ticket-select]");
    if (select) {
      event.preventDefault();
      loadDetail(select.getAttribute("data-detail-url"));
      return;
    }
    var action = event.target.closest("[data-status-action]");
    if (action) {
      event.preventDefault();
      submitStatus(action, action.getAttribute("data-status-action"), null, null);
    }
  });
})();
