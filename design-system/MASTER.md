# MASTER.md — Design System UnivReq (source de vérité visuelle)

> Toute interface (landing, dashboards, modals, toasters, badges, PWA) doit respecter ce fichier.
> Scope : mobile-first (375–480 px en priorité), colonne centrée `max-w-md`.
> En cas de conflit avec un prompt, **le brief de l'utilisateur prime** (palette navy/Inter imposée).

---

## 1. Direction artistique (revue frontend-design)

**Concept : « clarté institutionnelle »** — un portail académique doit inspirer la confiance et
la rigueur administrative, pas le marketing SaaS. La référence n'est pas une landing page
produit, mais l'objet métier réel : un **dossier de requête suivi de bout en bout**.

- **Élément mémorable** : le *rail de statut* — chaque carte de requête porte un liseré
  coloré de 4 px à gauche qui change de couleur au fil du cycle de vie (gris → bleu → ambre →
  émeraude → rouge). En temps réel, le liseré change sans rechargement : c'est la signature visuelle.
- **Grille** : une seule colonne stricte (pas de grilles de cartes identiques), hiérarchie par
  typographie et rail de couleur, pas par ombres décoratives.
- **Zéro décor non fonctionnel** : pas de gradient, pas d'emoji-icône (SVG inline uniquement),
  pas de glassmorphism hors la bâche floutée des modals (imposée par le brief), pas de padding
  marketing vide — c'est un outil de travail, la densité reste honnête.
- **Détail typographique porteur** : chiffres tabulaires (`font-variant-numeric: tabular-nums`)
  pour matricules, compteurs et horodatages — la donnée administrative se lit au millimètre.

## 2. Palette (imposée par le brief — valeurs exactes)

### 2.1 Tokens de marque (Tailwind config)

| Token | Hex | Usage strict |
|---|---|---|
| `navy` (PRIMARY) | `#1E3A8A` | headers de modal, header applicatif, bouton principal, marque |
| `navy.light` (ACCENT) | `#2563EB` | liens, sélection active, bordure de champ en focus, focus UI |
| `navy.dark` (INK) | `#1E293B` | texte corps, titres, texte sur surfaces claires |
| `background` | `#F8FAFC` | canvas de l'application |
| `white` | `#FFFFFF` | surfaces (cards, modals, champs) |

### 2.2 Tokens sémantiques

| Token | Hex | Usage |
|---|---|---|
| success | `#059669` (emerald-600) | toaster succès, statut RÉSOLU, bouton [Valider] |
| danger | `#DC2626` (red-600) | toaster erreur, statut REJETÉ, bouton [Rejeter] |
| warning | `#B45309` (amber-700) | statut EN COURS |
| border | `#E2E8F0` (slate-200) | bordures de champs et cartes |
| muted | `#64748B` (slate-500) | texte secondaire, placeholder (jamais sous slate-400 sur blanc) |

**Règle de contraste (WCAG AA, non négociable)** : texte normal ≥ 4,5:1.
Sur les badges, on pose toujours la **teinte foncée sur fond teinté clair**
(ex. `text-amber-700 bg-amber-100`), jamais `text-amber-600` sur blanc.

### 2.3 Cartographie des statuts de requête

| Statut (clé) | Label `{% trans %}` | Badge (fond / texte) | Rail carte |
|---|---|---|---|
| `SENT` | Envoyé | `bg-slate-100 text-slate-700` | `bg-slate-400` |
| `RECEIVED` | Reçu | `bg-blue-100 text-blue-700` | `bg-blue-600` |
| `PROCESSING` | En cours | `bg-amber-100 text-amber-700` | `bg-amber-500` |
| `RESOLVED` | Résolu | `bg-emerald-100 text-emerald-700` | `bg-emerald-600` |
| `REJECTED` | Rejeté | `bg-red-100 text-red-700` | `bg-red-600` |

Le code statut (anglais) est la clé JS (`data-status`), le label est toujours traduit côté template.

## 3. Typographie

- **Famille unique : Inter** (400/500/600/700), **auto-hébergée** en `static/fonts/*.woff2`
  (licence SIL OFL) — pas de CDN en production. Fallback : `system-ui, -apple-system, "Segoe UI", sans-serif`.
- Taille de base 16 px ; corps mobile 15–16 px (**jamais < 14 px** pour du texte utile).
- Échelle : 12 (meta) / 14 (support) / 16 (corps) / 18 (card title) / 22 (h2) / 28 (h1 mobile) / 36 (hero landing).
- Line-height 1,5 pour le corps ; titres `tracking-tight` (`-0.025em`).
- Règles anti-génériques du brief design : **pas de label CAPS au-dessus de chaque titre**,
  **pas de mot isolé en italique/accents colorés dans un titre**, pas de pseudo-label `WORD — fragment`.

## 4. Espacements, rayons, ombres

- Grille 4 px ; rythme courant : 8 / 12 / 16 / 24 / 32.
- Conteneur page : `max-w-md mx-auto px-4 pb-28 pt-4` (`pb-28` = 112 px pour bottom-nav 64 px + marge).
- Rayons : champs `rounded-xl` (12 px), cards `rounded-2xl` (16 px), modals `rounded-t-2xl` mobile.
- Ombres : une seule rampe, légère (`shadow-sm` cards, `shadow-lg` toaster, `shadow-2xl` modal).
  Pas d'empilement d'ombres ni d'ombres colorées.
- Z-index : `nav=40`, `modal/toaster=50` — **jamais de `z-[9999]`**.

## 5. Composants (contrat de classes — `@layer components` dans `input.css`)

### 5.1 Bouton principal (thumb-friendly, plein largeur)

```html
<button class="btn btn-primary">Soumettre la requête</button>
```
```css
.btn { @apply inline-flex items-center justify-center min-h-12 px-6 rounded-xl
        font-semibold text-base select-none transition-transform duration-150
        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy
        focus-visible:ring-offset-2 disabled:opacity-50 disabled:pointer-events-none; }
.btn-primary { @apply w-full bg-navy text-white shadow-md active:scale-95; }
.btn-success { @apply w-full bg-emerald-600 text-white shadow-md active:scale-95; }
.btn-danger  { @apply w-full bg-red-600 text-white shadow-md active:scale-95; }
.btn-ghost   { @apply w-full bg-white text-navy border border-slate-200 active:scale-95; }
```
- **Hauteur minimale 48 px** (`min-h-12`) sur *tous* les contrôles cliquables.
- Feedback tactile : `active:scale-95` + `transition-transform` (durée 150 ms, jamais 0 ms).
- Les variantes sémantiques vert/rouge sont réservées aux décisions enseignantes.

### 5.2 Champ de saisie

```html
<label class="label" for="email">Matricule <span class="text-red-600">*</span></label>
<input id="email" class="field" inputmode="numeric" autocomplete="username">
```
```css
.field  { @apply w-full min-h-12 px-4 rounded-xl border border-slate-200 bg-white
           text-navy-dark placeholder:text-slate-400 transition-colors
           focus:outline-none focus:border-navy-light focus:ring-2 focus:ring-navy/30; }
.field-error { @apply border-red-600 ring-2 ring-red-600/30; }
.label  { @apply block text-sm font-medium text-navy-dark mb-1.5; }
.helper{ @apply mt-1.5 text-xs text-slate-500; }
```
- **Reconciliation brief** : bordure/champ actif = accent bleu (`#2563EB`),
  *focus ring* clavier = navy (`#1E3A8A`). On ne pose jamais de focus sans anneau visible.
- Label toujours visible au-dessus du champ (pas de label placeholder-only),
  astérisque `*` en `text-red-600` pour les champs requis.

### 5.3 Toaster global (#global-toaster)

```css
.toast          { @apply flex items-center gap-3 bg-white rounded-xl p-4 shadow-lg
                      border-l-4 pointer-events-auto; }
.toast-success  { @apply border-l-emerald-600; }   /* icône check emerald */
.toast-error    { @apply border-l-red-600; }       /* icône alerte red */
```
- Cadré en haut (`fixed top-4 left-4 right-4 max-w-sm mx-auto`), entrée `-translate-y-24 → 0`
  + fade, 300 ms, **auto-dismiss 4 s** (jamais persistant), `role="status" aria-live="polite"`.
- Icônes SVG inline, jamais d'emoji dans le composant.

### 5.4 Modale maîtresse (#master-modal)

- Mobile : **bottom-sheet** — le panneau monte de `translate-y-full` à `translate-y-0` (300 ms,
  `ease-out`), backdrop `bg-slate-900/60 backdrop-blur-sm`.
- `sm:` : centrée, `sm:max-w-md`, `rounded-2xl`.
- Header collant `bg-navy text-white` (couleur imposée : header de modal = navy), titre
  `font-bold text-base`, bouton fermer ≥ 44×44 px avec `aria-label="Fermer"`.
- Corps scrollable `overflow-y-auto` + `max-h-[85vh]`.
- Avant tout fetch : squelette `animate-pulse` (`bg-slate-200`, 2 lignes + bloc + bouton).
- Accessibilité : `role="dialog" aria-modal="true"`, fermeture `Escape`, clic backdrop,
  piège de focus, focus restitué à l'élément déclencheur.

### 5.5 Bottom navigation (mobile-native)

```html
<nav class="bottom-nav" aria-label="Navigation principale"> … 3 items … </nav>
```
```css
.bottom-nav { @apply fixed bottom-0 left-0 right-0 z-40 bg-white border-t border-slate-200
               shadow-xl; padding-bottom: env(safe-area-inset-bottom); }
.bottom-nav__item { @apply flex flex-col items-center justify-center gap-0.5
                     min-h-12 flex-1 text-xs font-semibold text-slate-500
                     transition-colors duration-150; }
.bottom-nav__item[aria-current="page"] { @apply text-navy; }
```
- **3 entrées maximum** : *Mes requêtes / Nouvelle (➕ central) / Profil* côté étudiant ;
  *Boîte de réception / Détail / Profil* côté enseignant (le même composant, items injectés par rôle).
- Item actif : icône + label navy ; inactif slate-500 ; icônes SVG 24 px, zone de tap ≥ 48 px,
  gap ≥ 8 px entre items.

### 5.6 Carte de requête

```css
.ticket-card { @apply relative bg-white rounded-2xl border border-slate-100 shadow-sm
                p-4 pl-5 overflow-hidden transition-colors duration-200; }
.ticket-card::before { content: ""; @apply absolute left-0 top-0 bottom-0 w-1 bg-slate-400; }
/* w-1 = liseré de statut ; couleur pilotée par [data-status] */
.ticket-card[data-status="RECEIVED"]::before  { @apply bg-blue-600; }
.ticket-card[data-status="PROCESSING"]::before{ @apply bg-amber-500; }
.ticket-card[data-status="RESOLVED"]::before  { @apply bg-emerald-600; }
.ticket-card[data-status="REJECTED"]::before  { @apply bg-red-600; }
```
- Bouton carte = `<article>` entier cliquable via un `<button>` dédié (jamais `<div onclick>`).
- Si `data-status="REJECTED"` : clic → panneau de repli inline
  (`hidden → block`, 200 ms) affichant `rejection_reason` sous le motif « Motif du rejet ».
- Méta en `tabular-nums` : `[#2026-0042] · 14/10/2026`.

### 5.7 Squelette de chargement

```css
.skeleton { @apply animate-pulse bg-slate-200 rounded-xl; }
```
Hauteurs réelles réservées pour éviter le CLS (title 16 px, ligne 14 px, bloc 96 px).
`prefers-reduced-motion: reduce` → `animation: none` sur `.skeleton` et
`transition: none` sur `.btn-primary:active` (le reste des états reste visible).

## 6. États système (à implémenter partout)

| État | Règle |
|---|---|
| Chargement | skeleton `animate-pulse` + boutons `disabled` (jamais de spinner seul sans désactivation) |
| Succès | toaster success + mise à jour optimiste de la carte |
| Erreur | toaster error **et** message inline sous le champ concerné (jamais uniquement top-of-page) |
| Vide | état vide dessiné (icône + phrase d'action : « Aucune requête pour le moment ») |
| Hors-ligne / WS coupé | pastille discrète dans le header + reconnexion backoff (voir ARCHITECTURE §10) |

## 7. Accessibilité & mobile (checklist de revue)

- Cibles tactiles ≥ 48 px (`min-h-12`), espacement ≥ 8 px entre cibles adjacentes.
- Contraste 4,5:1 vérifié pour chaque variante de badge (cf. §2.2).
- Focus visible partout (`focus-visible:ring-2 ring-navy`), jamais de `outline: none` nu.
- Bottom-nav : `pb-28` sur le contenu, `env(safe-area-inset-bottom)` respecté (iPhone).
- Pas de défilement horizontal ; `overscroll-behavior: contain` sur le corps.
- Vibration `navigator.vibrate(50)` **uniquement** sur événement serveur (pas sur chaque tap).
- Vérification finale navigateur (skill `webapp-testing` si disponible) à 375 px / 768 px :
  contraste, focus clavier, modale, erreurs, débordements.

## 8. Anti-patterns interdits (revue avant livraison)

1. Emoji comme icône (SVG inline uniquement) ; `cursor:pointer` absent sur un élément cliquable.
2. Tailwind CDN en production, styles inline, CSS hors des 2 fichiers `input.css`/`output.css`.
3. `bg-blue-500`/`bg-red-500` (paliers par défaut) hors des tokens définis ici.
4. Bouton < 48 px, transition 0 ms, hover comme seul affordant.
5. Champ sans label visible, erreur affichée uniquement en haut de page.
6. Spinner infini (toaster persistant, skeleton sans fin) — auto-dismiss 4 s, timeouts raisonnables.
7. `z-[…]` arbitraire, second défilement horizontal, modal qui masque le champ actif sous le clavier
   (tester `visualViewport`/scrollIntoView sur les modals de formulaire).
8. Texte utile < 14 px, gris sur gris (`slate-400` sur `slate-100`).
