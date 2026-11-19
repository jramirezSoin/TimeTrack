// Service worker de TimeTrack. Se sirve desde /sw.js para que su alcance sea todo el sitio.
//
// Reglas (ver README, «PWA»):
//  - Las páginas HTML NUNCA se cachean: cada arranque del servidor genera un token CSRF nuevo incrustado en el
//    HTML; una página cacheada tendría un token viejo y todos los POST darían 403.
//  - Solo se cachean los estáticos. No se interceptan POST ni los fragmentos HTMX.
//  - Sin servidor, las navegaciones muestran /offline.
// Al cambiar la lista de precarga o las reglas, suba el número de CACHE.
const CACHE = "timetrack-v3";
const PRECACHE = [
  "/offline",
  "/static/app.css",
  "/static/tareas.js",
  "/static/utilidades.js",
  "/static/vendor/bootstrap/bootstrap.min.css",
  "/static/vendor/bootstrap/bootstrap.bundle.min.js",
  "/static/vendor/bootstrap-icons/bootstrap-icons.min.css",
  "/static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff2",
  "/static/vendor/htmx/htmx.min.js",
  "/static/vendor/fonts/fonts.css",
  "/static/vendor/fonts/instrument-sans-latin.woff2",
  "/static/vendor/fonts/dm-mono-400-latin.woff2",
  "/static/vendor/fonts/dm-mono-500-latin.woff2",
  "/static/vendor/fonts/caveat-latin.woff2",
  "/static/pwa/icon-192.png",
  "/static/pwa/icon-512.png",
];
const FUENTES = ["fonts.googleapis.com", "fonts.gstatic.com"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((claves) => Promise.all(claves.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Primero caché (lo que no cambia: Bootstrap, iconos, htmx). ignoreSearch: las fuentes llevan ?hash.
function primeroCache(req) {
  return caches.open(CACHE).then((cache) =>
    cache.match(req, { ignoreSearch: true }).then((hit) => hit || fetch(req).then((res) => {
      if (res.ok) cache.put(req, res.clone());
      return res;
    }))
  );
}

// Sirve lo cacheado al instante y lo actualiza en segundo plano (app.css, JS propio, Google Fonts).
function revalidar(req) {
  return caches.open(CACHE).then((cache) =>
    cache.match(req).then((hit) => {
      const red = fetch(req)
        .then((res) => {
          if (res.ok || res.type === "opaque") cache.put(req, res.clone());
          return res;
        })
        .catch(() => hit || Response.error());
      return hit || red;
    })
  );
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;                       // los POST van directo a la red
  const url = new URL(req.url);
  const propio = url.origin === self.location.origin;

  if (req.mode === "navigate") {                          // HTML: solo red; sin servidor, pantalla /offline
    event.respondWith(fetch(req).catch(() => caches.match("/offline")));
    return;
  }
  if (propio && url.pathname.startsWith("/static/vendor/")) {
    event.respondWith(primeroCache(req));
  } else if ((propio && url.pathname.startsWith("/static/")) || FUENTES.includes(url.hostname)) {
    event.respondWith(revalidar(req));
  }
  // Todo lo demás (fragmentos HTMX, /horas/jobs/…): no se intercepta.
});
