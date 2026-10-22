/* The Vanguard3 platform builds into ../docs, which GitHub Pages serves.
 * The bots keep writing their results to docs/data/ and the research lab
 * lives in docs/lab/; the build only replaces docs/index.html and its own
 * docs/app/ folder, so neither is ever touched. */
import { createReadStream, existsSync, rmSync, statSync } from "node:fs";
import { extname, join, normalize, resolve } from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const DOCS = resolve(import.meta.dirname, "../docs");
const TYPES: Record<string, string> = {
  ".json": "application/json", ".html": "text/html", ".js": "text/javascript",
  ".css": "text/css", ".svg": "image/svg+xml",
};

/** In development, serve the bots' data and the lab from docs/, at the same
 *  paths GitHub Pages uses, so the app reads real results. */
function serveDocs(): Plugin {
  return {
    name: "v3-serve-docs",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const path = decodeURIComponent((req.url || "").split("?")[0]);
        if (!/^\/(data|lab)\//.test(path)) return next();
        let file = normalize(join(DOCS, path));
        if (!file.startsWith(DOCS + "/")) return next();
        if (existsSync(file) && statSync(file).isDirectory()) file = join(file, "index.html");
        if (!existsSync(file)) return next();
        res.setHeader("Content-Type", TYPES[extname(file)] || "application/octet-stream");
        createReadStream(file).pipe(res);
      });
    },
  };
}

/** Old builds' files are removed first, so docs/app/ only ever holds the
 *  current one (file names carry a hash of their contents). */
function cleanApp(): Plugin {
  return {
    name: "v3-clean-app",
    apply: "build",
    buildStart() { rmSync(join(DOCS, "app"), { recursive: true, force: true }); },
  };
}

export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss(), serveDocs(), cleanApp()],
  build: {
    outDir: DOCS,
    emptyOutDir: false,
    assetsDir: "app",
    chunkSizeWarningLimit: 1600,
    rolldownOptions: {
      output: {
        entryFileNames: "app/[name]-[hash].js",
        chunkFileNames: "app/[name]-[hash].js",
        assetFileNames: "app/[name]-[hash][extname]",
      },
    },
  },
});
