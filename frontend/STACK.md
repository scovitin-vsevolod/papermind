> Last updated: 2026-05-26

# Frontend

## Language & Framework

- **TypeScript:** 5.7
- **Framework:** React 19
- **Build tool:** Vite 6
- **Styling:** Tailwind CSS 4 (CSS-based config via `@tailwindcss/vite` — no `tailwind.config.js`, no PostCSS)
- **Package manager:** npm

## Key dependencies

| Package | Purpose |
|---|---|
| `react` ^19.0.0 | UI runtime |
| `react-dom` ^19.0.0 | DOM renderer |
| `vite` ^6.0.0 | Dev server + bundler |
| `@vitejs/plugin-react` ^4.3.0 | Fast Refresh / JSX transform |
| `tailwindcss` ^4.0.0 | Utility CSS framework |
| `@tailwindcss/vite` ^4.0.0 | Tailwind 4 Vite integration |
| `@tailwindcss/typography` ^0.5.19 | `prose` class for Markdown answers |
| `react-markdown` ^10.1.0 + `remark-gfm` ^4.0.1 | Render Claude's Markdown answers (tables, lists, code) |
| `react-force-graph-2d` ^1.29.1 | Knowledge graph visualization (Phase 3) |
| `typescript` ^5.7.0 | Type checking (`tsc -b` then `vite build`) |

## Structure

- `src/App.tsx` — top-level UI shell (header with model badges, documents pane, ask pane)
- `src/api.ts` — typed `fetch` wrappers over the backend REST API; owns the wire types
- `src/index.css` — single `@import "tailwindcss";` line
- `vite.config.ts` — `react()` + `tailwindcss()` plugins, dev port 5209 (strictPort:true — fails if taken)

## Commands

```sh
npm install         # one-time
npm run dev         # Vite dev server with HMR
npm run build       # tsc -b && vite build → dist/
```
