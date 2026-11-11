// Offline support: pages are fetched fresh when online (network first) and served from cache when offline.
const CACHE = "digest-__VERSION__";
const CORE = ["./", "./index.html", "./style.css", "./app.js", "./features.js", "./search.json",
              "./glossary.html", "./archive.html", "./icons/icon-192.png", "./account.js", "./supabase.js"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(CORE)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  // "no-cache" = always ask the server if there's something newer (cheap: unchanged files come back as 304),
  // instead of trusting the browser's 10-minute copy from GitHub Pages. Audio can use the normal cache.
  const fresh = url.pathname.endsWith(".mp3") ? e.request : new Request(e.request, { cache: "no-cache" });
  e.respondWith(
    fetch(fresh).then((res) => {
      if (res.ok && !url.pathname.endsWith(".mp3")) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
      }
      return res;
    // offline: cached copy, else send page visits to today's page (never serve HTML in place of a script or image)
    }).catch(() => caches.match(e.request).then((hit) => hit ||
      (e.request.mode === "navigate" && !url.pathname.endsWith("/index.html") ? Response.redirect("./index.html") : Response.error())))
  );
});
