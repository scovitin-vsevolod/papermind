import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5209,
    // Fail loudly instead of silently jumping to a sibling port — keeps the
    // Valet proxy (which targets 5209) honest and prevents "why does
    // papermind.test show Sherpa?" surprises.
    strictPort: true,
    // Vite 5+ blocks requests whose Host header is unknown (DNS-rebinding
    // defence). localhost / 127.0.0.1 are allowed by default; the Valet
    // domain isn't, so add it explicitly. Use ".test" suffix to cover any
    // Valet domain in case the project gets aliased.
    allowedHosts: ["papermind.test", ".test"],
    // Proxy /api/* to the FastAPI backend on :8109 so the frontend can
    // call the backend as if it were on the same origin. Eliminates CORS
    // in dev and makes the URLs look the same as production (where a
    // reverse proxy would do the same thing).
    proxy: {
      "/api": {
        target: "http://localhost:8109",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
