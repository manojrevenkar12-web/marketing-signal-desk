// Copies the browser libraries into Django's static files: no CDN, so the CSP stays 'self'.
import { copyFileSync, mkdirSync, readdirSync } from "node:fs";

const out = "../src/msd/web/static/web/vendor";
mkdirSync(`${out}/fonts`, { recursive: true });
copyFileSync("node_modules/htmx.org/dist/htmx.min.js", `${out}/htmx.min.js`);
copyFileSync("node_modules/@alpinejs/csp/dist/cdn.min.js", `${out}/alpine-csp.min.js`);
for (const f of readdirSync("node_modules/@fontsource-variable/figtree/files")) {
  if (f.startsWith("figtree-latin-wght") && f.endsWith(".woff2")) copyFileSync(`node_modules/@fontsource-variable/figtree/files/${f}`, `${out}/fonts/${f}`);
}
console.log("vendor files copied");
