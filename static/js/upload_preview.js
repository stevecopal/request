/**
 * upload_preview.js — aperçu local des documents **avant** envoi.
 *
 * Cible : tous les `input[type=file]` des formulaires de dépôt (création de
 * requête, réponse à une demande d'information, etc.).
 *
 * À la sélection d'un fichier, un bloc d'aperçu apparaît sous le champ :
 *   - image (png, jpg, jpeg, webp) : miniature + lien « Aperçu » ;
 *   - PDF                        : lien « Aperçu » dans un nouvel onglet ;
 *   - autre type                 : nom, taille et type affichés seuls.
 *
 * Les aperçus utilisent des URLs d'objets locales (aucun envoi réseau) et sont
 * révoqués à chaque changement pour ne pas fuiter de mémoire. L'envoi reste
 * géré par le formulaire existant.
 */
(function () {
  "use strict";

  var IMAGE_TYPES = { "image/png": 1, "image/jpeg": 1, "image/webp": 1 };
  var PREVIEWABLE = { "application/pdf": 1 };

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + " o";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " Ko";
    return (bytes / (1024 * 1024)).toFixed(1) + " Mo";
  }

  function clearPreviews(input) {
    var zone = input.__previewZone;
    if (!zone) return;
    (zone.__objectUrls || []).forEach(function (url) {
      URL.revokeObjectURL(url);
    });
    zone.__objectUrls = [];
    zone.innerHTML = "";
    zone.classList.add("hidden");
  }

  function renderPreviews(input) {
    var zone = input.__previewZone;
    if (!zone) return;
    clearPreviews(input);

    var files = input.files ? Array.prototype.slice.call(input.files) : [];
    if (!files.length) return;

    zone.__objectUrls = [];
    files.forEach(function (file) {
      var row = document.createElement("div");
      row.className =
        "mt-2 flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3";

      var isImage = !!IMAGE_TYPES[file.type];
      var isPdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);

      if (isImage) {
        var img = document.createElement("img");
        var url = URL.createObjectURL(file);
        zone.__objectUrls.push(url);
        img.src = url;
        img.alt = file.name;
        img.className = "h-14 w-14 shrink-0 rounded-lg object-cover border border-slate-200";
        row.appendChild(img);
      }

      var details = document.createElement("div");
      details.className = "min-w-0 flex-1";

      var name = document.createElement("p");
      name.className = "truncate text-sm font-medium text-navy-dark";
      name.textContent = file.name;
      details.appendChild(name);

      var meta = document.createElement("p");
      meta.className = "text-xs text-slate-500";
      meta.textContent = formatSize(file.size) + (file.type ? " · " + file.type : "");
      details.appendChild(meta);

      if (isImage || isPdf) {
        var link = document.createElement("a");
        var previewUrl = URL.createObjectURL(file);
        zone.__objectUrls.push(previewUrl);
        link.href = previewUrl;
        link.target = "_blank";
        link.rel = "noopener";
        link.className = "mt-1 inline-block text-xs font-semibold text-navy-light hover:underline";
        link.textContent = "Aperçu";
        details.appendChild(link);
      }

      row.appendChild(details);
      zone.appendChild(row);
    });

    zone.classList.remove("hidden");
  }

  function wire(input) {
    if (input.__previewWired) return;
    input.__previewWired = "1";

    var zone = document.createElement("div");
    zone.className = "hidden";
    zone.setAttribute("data-upload-preview", "");
    input.insertAdjacentElement("afterend", zone);
    input.__previewZone = zone;

    input.addEventListener("change", function () {
      renderPreviews(input);
    });
  }

  function wireAll(root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll('form input[type="file"]').forEach(wire);
  }

  document.addEventListener("DOMContentLoaded", function () {
    wireAll(document);
  });

  // Fragments injectés (SPA) : mêmes aperçus après chaque navigation/modale.
  var api = window.UnivReq || {};
  var previousContentHook = api.onContentLoaded;
  api.onContentLoaded = function (body) {
    if (typeof previousContentHook === "function") previousContentHook(body);
    wireAll(body);
  };
  var previousModalHook = api.onModalContentLoaded;
  api.onModalContentLoaded = function (body) {
    if (typeof previousModalHook === "function") previousModalHook(body);
    wireAll(body);
  };
})();
