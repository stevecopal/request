document.addEventListener('DOMContentLoaded', function () {
  var api = window.UnivReq || {};
  var LOGIN_URL = '/accounts/login/';

  function getCookie(name) {
    var value = '; ' + document.cookie;
    var parts = value.split('; ' + name + '=');
    if (parts.length !== 2) return null;
    return parts.pop().split(';').shift();
  }

  function csrfFromForm(form) {
    var input = form.querySelector('[name=csrfmiddlewaretoken]');
    if (input && input.value) return input.value;
    return getCookie('csrftoken') || '';
  }

  function setBusy(form, busy) {
    // Ne jamais desactiver les inputs : un champ disabled est exclu de
    // FormData et le POST arriverait vide (400). On verrouille le submit.
    var submit = form.querySelector('[type=submit]');
    if (submit) submit.disabled = busy;
    form.setAttribute('aria-busy', busy ? 'true' : 'false');
    if (!submit) return;
    if (busy) {
      if (!submit.dataset.label) submit.dataset.label = submit.innerHTML;
      submit.innerHTML = 'Connexion...';
      submit.classList.add('opacity-80');
    } else if (submit.dataset.label) {
      submit.innerHTML = submit.dataset.label;
      submit.classList.remove('opacity-80');
    }
  }

  function notify(msg, kind) {
    if (typeof api.showNotification === 'function') api.showNotification(msg, kind);
  }

  function closeModal() {
    if (typeof api.closeModal === 'function') api.closeModal();
  }

  function loginErrorMessage(status, data) {
    if (data && data.message) return data.message;
    if (status === 400) return 'Matricule et mot de passe sont requis.';
    if (status === 401) return 'Matricule ou mot de passe incorrect.';
    if (status === 403) return 'Session expiree ou jeton CSRF invalide. Rechargez la page et reessayez.';
    if (status === 405) return 'Methode non autorisee : rechargez le formulaire via /login/ puis reessayez.';
    if (status === 429) return 'Trop de tentatives. Reessayez dans quelques minutes.';
    if (status) return 'Erreur de connexion (' + status + ').';
    return 'Erreur de connexion.';
  }

  async function parseBodySafe(response) {
    // Les erreurs Django non-JSON (405/403 HTML de @require_POST ou du
    // middleware CSRF) ne doivent jamais faire planter sur response.json().
    var text = '';
    try {
      text = await response.text();
    } catch (e) {
      return {};
    }
    if (!text) return {};
    try {
      return JSON.parse(text);
    } catch (e) {
      return {};
    }
  }

  function bindLogin(loginForm) {
    loginForm.addEventListener('submit', async function (e) {
      e.preventDefault();
      var errorBox = loginForm.querySelector('#login-error');
      var passwordInput = loginForm.querySelector('input[name=password]');
      var matriculeInput = loginForm.querySelector('input[name=matricule]');
      if (errorBox) errorBox.classList.add('hidden');
      // Validation locale : ne jamais envoyer un POST vide (400 + compteur
      // rate-limit inutilement incremente). Le backend revalide de toute facon.
      var matriculeVal = matriculeInput ? matriculeInput.value.trim() : '';
      var passwordVal = passwordInput ? passwordInput.value : '';
      if (!matriculeVal || !passwordVal) {
        if (errorBox) {
          errorBox.textContent = 'Saisissez votre matricule et votre mot de passe.';
          errorBox.classList.remove('hidden');
        }
        if (!matriculeVal && matriculeInput) matriculeInput.focus();
        else if (passwordInput) passwordInput.focus();
        return;
      }
      // Capturer les donnees AVANT de verrouiller le formulaire.
      var formData = new FormData(loginForm);
      setBusy(loginForm, true);
      try {
        var url = loginForm.getAttribute('data-login-url') || loginForm.getAttribute('action') || LOGIN_URL;
        var response = await fetch(url, {
          method: 'POST',
          headers: { 'X-CSRFToken': csrfFromForm(loginForm) },
          body: formData,
          credentials: 'same-origin'
        });
        var data = await parseBodySafe(response);
        if (response.ok) {
          closeModal();
          notify('Connexion reussie', 'success');
          // Navigation complète : la connexion bascule de l'espace public vers
          // la coque applicative. Un swap de fragment injecterait la coque
          // entière (avec son propre #spa-viewport) dans la page publique, qui
          // ne rejouerait pas son initialisation (squelette figé).
          window.location.href = data.next || '/dashboard/';
        } else {
          if (passwordInput) passwordInput.value = '';
          if (errorBox) {
            errorBox.textContent = loginErrorMessage(response.status, data);
            errorBox.classList.remove('hidden');
          }
          notify(loginErrorMessage(response.status, data), 'error');
        }
      } catch (err) {
        if (errorBox) {
          errorBox.textContent = 'Connexion impossible. Reessayez dans un instant.';
          errorBox.classList.remove('hidden');
        }
        notify('Connexion impossible.', 'error');
      } finally {
        setBusy(loginForm, false);
      }
    });
  }

  function bindLogout(button) {
    var url = button.getAttribute('data-logout-url') || '/accounts/logout/';
    fetch(url, {
      method: 'POST',
      headers: { 'X-CSRFToken': getCookie('csrftoken') || '' },
      credentials: 'same-origin'
    }).then(function (response) {
      return response.json().then(function (data) {
        return { status: response.status, data: data };
      });
    }).then(function (result) {
      var next = (result.data && result.data.next) ? result.data.next : '/';
      window.location.href = next;
    }).catch(function () {
      notify('Deconnexion impossible.', 'error');
    });
  }

  function escapeHtml(value) {
    var div = document.createElement('div');
    div.textContent = value == null ? '' : value;
    return div.innerHTML;
  }

  function loadDepartments(facultySelect) {
    var targetSelector = facultySelect.getAttribute('data-department-target');
    var url = facultySelect.getAttribute('data-departments-url');
    var target = targetSelector ? document.querySelector(targetSelector) : null;
    if (!target || !url) return;
    var facultyId = facultySelect.value;
    target.disabled = true;
    target.innerHTML = '<option value=\"\">Chargement...</option>';
    if (!facultyId) {
      target.innerHTML = '<option value=\"\">Selectionnez une faculte</option>';
      return;
    }
    var fetcher = (typeof api.apiFetch === 'function')
      ? api.apiFetch(url + '?faculty=' + encodeURIComponent(facultyId))
      : fetch(url + '?faculty=' + encodeURIComponent(facultyId), { credentials: 'same-origin' }).then(function (r) { return r.json().then(function (d) { return { data: d }; }); });
    fetcher.then(function (result) {
      var list = (result.data && result.data.departments) ? result.data.departments : [];
      var options = ['<option value=\"\">Selectionnez un departement</option>'];
      list.forEach(function (dept) {
        options.push('<option value=\"' + dept.id + '\">' + escapeHtml(dept.name) + '</option>');
      });
      target.innerHTML = options.join('');
      target.disabled = false;
    }).catch(function () {
      target.innerHTML = '<option value=\"\">Erreur de chargement</option>';
    });
  }

  function bindOnboarding(form) {
    var errorBox = form.querySelector('#onboarding-error');
    var facultySelect = form.querySelector('[data-department-target]');
    if (facultySelect) {
      facultySelect.addEventListener('change', function () { loadDepartments(facultySelect); });
    }
    form.addEventListener('submit', async function (e) {
      e.preventDefault();
      if (errorBox) errorBox.classList.add('hidden');
      // Capturer les donnees AVANT de verrouiller le formulaire.
      var formData = new FormData(form);
      setBusy(form, true);
      try {
        var url = form.getAttribute('data-onboarding-url') || form.getAttribute('action') || '/accounts/ajax/onboarding/';
        var response = await fetch(url, {
          method: 'POST',
          headers: { 'X-CSRFToken': csrfFromForm(form) },
          body: formData,
          credentials: 'same-origin'
        });
        var data = await parseBodySafe(response);
        if (response.ok) {
          closeModal();
          notify(data.message || 'Profil enregistre.', 'success');
          window.location.href = data.next || '/dashboard/';
        } else {
          if (errorBox) {
            errorBox.textContent = data.message || 'Erreur de sauvegarde.';
            errorBox.classList.remove('hidden');
          }
          notify(data.message || 'Erreur de sauvegarde.', 'error');
        }
      } catch (err) {
        if (errorBox) {
          errorBox.textContent = 'Connexion impossible. Reessayez dans un instant.';
          errorBox.classList.remove('hidden');
        }
        notify('Enregistrement impossible.', 'error');
      } finally {
        setBusy(form, false);
      }
    });
  }

  function wire(root) {
    if (!root || !root.querySelector) return;
    var loginForm = root.querySelector('#login-form');
    if (loginForm && !loginForm.dataset.wired) {
      loginForm.dataset.wired = '1';
      bindLogin(loginForm);
    }
    var onboardingForm = root.querySelector('#onboarding-form');
    if (onboardingForm && !onboardingForm.dataset.wired) {
      onboardingForm.dataset.wired = '1';
      bindOnboarding(onboardingForm);
    }
  }

  wire(document);

  document.addEventListener('click', function (event) {
    var btn = event.target.closest ? event.target.closest('[data-logout]') : null;
    if (btn) {
      event.preventDefault();
      bindLogout(btn);
    }
  });

  api.getCookie = getCookie;
  var previousHook = api.onModalContentLoaded;
  api.onModalContentLoaded = function (body) {
    if (typeof previousHook === 'function') previousHook(body);
    wire(body);
  };
});
