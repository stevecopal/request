/**
 * Tailwind CSS v3.4 — configuration du design system UnivReq.
 *
 * Source de vérité des tokens : design-system/MASTER.md
 * Build : npm run build   →  static/css/output.css (minifié)
 * Watch : npm run watch
 *
 * Règle : aucun style hors de input.css/output.css ; les templates ne
 * consomment que des utilitaires et les composants définis dans @layer.
 *
 * Responsivité (mobile-first) :
 *   base  → < 640px    : colonne unique, bottom-navigation fixe
 *   sm/md → ≥ 640/768  : cartes élargies, grilles 2 colonnes
 *   lg/xl → ≥ 1024/1280: navigation horizontale en en-tête, contenu centré
 */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/js/**/*.js",
  ],

  // Classes générées dynamiquement côté JS (patch des cartes, badges, toasters)
  // : préservées malgré le tree-shaking de @layer components.
  safelist: [
    "btn", "btn-primary", "btn-success", "btn-danger", "btn-ghost",
    "field", "field-error", "label", "helper",
    "toast", "toast-success", "toast-error",
    "bottom-nav", "bottom-nav__item",
    "ticket-card", "skeleton", "badge-status", "spinner", "card",
    // Badges de statut (fond / texte)
    "bg-slate-100", "text-slate-700",
    "bg-blue-100", "text-blue-700",
    "bg-amber-100", "text-amber-700",
    "bg-violet-100", "text-violet-700",
    "bg-emerald-100", "text-emerald-700",
    "bg-red-100", "text-red-700",
    // Rails de statut des cartes
    "bg-slate-400", "bg-blue-600", "bg-amber-500", "bg-violet-600", "bg-emerald-600", "bg-red-600",
  ],

  theme: {
    extend: {
      colors: {
        // Palette imposée par le brief (MASTER.md §2.1)
        navy: {
          50: "#EEF3FF",
          100: "#DCE6FF",
          200: "#BACDFF",
          300: "#8DAAFF",
          400: "#5B82FF",
          500: "#3358F5",
          600: "#2563EB", // Accent — liens, focus de champ, sélection active
          700: "#1D4FD8",
          800: "#1E3A8A", // PRIMARY — marque, headers, boutons principaux
          900: "#172C6B",
          950: "#0F1D47",
          DEFAULT: "#1E3A8A",
          light: "#2563EB",
          dark: "#1E293B", // Ink — texte corps et titres
        },
        background: "#F8FAFC", // Canvas de l'application
      },

      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
      },

      maxWidth: {
        app: "28rem",    // 448px — colonne mobile étroite
        content: "42rem", // 672px — contenu principal lisible
        shell: "76rem",  // 1216px — coque large (desktop)
      },

      borderRadius: {
        "4xl": "2rem",
      },

      boxShadow: {
        card: "0 1px 2px rgba(15, 23, 42, 0.04), 0 8px 24px -12px rgba(15, 23, 42, 0.12)",
        "card-hover": "0 2px 4px rgba(15, 23, 42, 0.06), 0 16px 32px -16px rgba(15, 23, 42, 0.18)",
        brand: "0 10px 30px -12px rgba(30, 58, 138, 0.45)",
      },

      keyframes: {
        rise: {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
        "slide-in": {
          "0%": { opacity: "0", transform: "translateY(-16px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },

      animation: {
        rise: "rise 0.5s cubic-bezier(0.16, 1, 0.3, 1) both",
        shimmer: "shimmer 1.8s infinite",
        "slide-in": "slide-in 0.35s cubic-bezier(0.16, 1, 0.3, 1) both",
      },
    },
  },

  plugins: [],
};
