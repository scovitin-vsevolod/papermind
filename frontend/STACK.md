> Last updated: 2026-05-15

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
| `typescript` ^5.7.0 | Type checking (`tsc -b` then `vite build`) |

## Structure

- `src/App.tsx` — single-file UI: header (model badges) + documents (upload/list/delete) + ask (question + answer + citations)
- `src/api.ts` — typed `fetch` wrappers over the backend REST API; owns the wire types
- `src/index.css` — single `@import "tailwindcss";` line
- `vite.config.ts` — `react()` + `tailwindcss()` plugins, dev port 5209 (strictPort:true — fails if taken)

## Commands

```sh
npm install         # one-time
npm run dev         # Vite dev server with HMR
npm run build       # tsc -b && vite build → dist/
```
