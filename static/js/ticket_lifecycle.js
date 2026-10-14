/**
 * ticket_lifecycle.js — cycle de vie des requêtes (soumission + décisions).
 *
 *   - #ticket-form (étudiant)  : envoi multipart → rafraîchit le flux, toaster ;
 *   - [data-ticket-select]     : charge le détail dans #teacher-ticket-detail ;
 *   - [data-status-action]     : transition directe (ex. Démarrer l'analyse) ;
 *   - #teacher-decision-form   : Valider / Rejeter (motif obligatoire).
 */
(function () {
  "use strict";

  var api = window.UnivReq;
  var lastDetailUrl = null;

  function setBusy(button, busy) {
    if (!button) return;
    button.disabled = busy;
    button.setAttribute("aria-busy", busy ? "true" : "false");
  }

  /* ---------------------------- ÉTUDIANT ---------------------------- */

  function handleTicketForm(form) {
    var submit = form.querySelector("#ticket-submit");
    var errorBox = form.querySelector("#ticket-error");

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (errorBox) errorBox.classList.add("hidden");
      setBusy(submit, true);

      api
        .apiFetch(form.getAttribute("data-create-url"), {
          method: "POST",
          body: new FormData(form),
        })
        .then(function (result) {
          api.closeModal();
          api.showNotification(result.data.message || "Requête envoyée.", "success");
          var feed = form.getAttribute("data-feed-url");
          if (feed) api.loadFragment(feed, { pushState: false });
        })
        .catch(function (err) {
          var payload = err.data || {};
          var message = payload.message || err.message || "Envoi impossible.";
          if (errorBox) {
            errorBox.textContent = message;
            errorBox.classList.remove("hidden");
          }
          api.showNotification(message, "error");
        })
        .then(function () {
          setBusy(submit, false);
        });
    });
  }

  /* --------------------------- ENSEIGNANT --------------------------- */

  function loadDetail(url) {
    var target = document.getElementById("teacher-ticket-detail");
    if (!target) return;
    lastDetailUrl = url;
    target.classList.remove("hidden");
    api.loadFragment(url, { target: "#teacher-ticket-detail", pushState: false });
  }

  function refreshDetail() {
    if (lastDetailUrl) loadDetail(lastDetailUrl);
  }

  function submitStatus(button, status, reason) {
    var url = button.getAttribute("data-status-url");
    var body = new FormData();
    body.append("ticket_id", button.getAttribute("data-ticket-id"));
    body.append("status", status);
    if (reason) body.append("rejection_reason", reason);

    setBusy(button, true);
    return api
      .apiFetch(url, { method: "POST", body: body })
      .then(function (result) {
        api.closeModal();
        api.showNotification(result.data.message || "Statut mis à jour.", "success");
        refreshDetail();
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

      if (status === "REJECTED" && !reason) {
        if (errorBox) {
          errorBox.textContent = "Le motif du rejet est obligatoire.";
          errorBox.classList.remove("hidden");
        }
        return;
      }
      var fakeButton = submit;
      fakeButton.setAttribute("data-status-url", form.getAttribute("data-status-url"));
      fakeButton.setAttribute("data-ticket-id", form.querySelector('[name="ticket_id"]').value);
      setBusy(submit, true);

      submitStatus(fakeButton, status, reason).then(function () {
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
  }

  document.addEventListener("DOMContentLoaded", function () {
    wire(document);
  });

  document.addEventListener("click", function (event) {
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
      submitStatus(action, action.getAttribute("data-status-action"), null);
    }
  });

  var previousHook = api.onModalContentLoaded;
  api.onModalContentLoaded = function (body) {
    if (typeof previousHook === "function") previousHook(body);
    wire(body);
  };
})();
