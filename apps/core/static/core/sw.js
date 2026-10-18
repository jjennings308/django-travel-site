/* The trip page offline (site roadmap R6). Served at /sw.js by apps.core.pwa.service_worker and
 * registered from the trip page with scope /trips/, so it only ever controls trip pages.
 *
 * Saved (per person, in the cache "sbl-offline-<key>", the key from the registration URL):
 *   - the trip page /trips/<pk>/, its booklet /trips/<pk>/booklet.pdf and its tickets
 *     /trips/<pk>/files/<id>/ — network first (4 s), the saved copy when offline;
 *   - /static/ files and the CDN files the page loads — cache first (their names are hashed).
 * Nothing else: edit pages, People, the calendar, other apps and anything with a query string
 * pass straight through. A saved trip page shown offline gets its banner switched on.
 * A new key (another person signed in) deletes every other sbl-offline cache; base.html deletes
 * them all on sign-out and on any signed-out page.
 */
const params = new URL(self.location).searchParams;
const CACHE = "sbl-offline-" + (params.get("u") || "anon");
const DEBUG = params.get("debug") === "1";  // dev: static files aren't hashed, so fetch them fresh
const PAGE = /^\/trips\/\d+\/$/;
const SAVED = [PAGE, /^\/trips\/\d+\/booklet\.pdf$/, /^\/trips\/\d+\/files\/\d+\/$/];
const CDN_HOSTS = ["cdn.jsdelivr.net", "cdnjs.cloudflare.com"];
const TIMEOUT_MS = 4000;
const MATCH = { ignoreVary: true };

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("sbl-offline-") && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "clear") {
    event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k.startsWith("sbl-offline-")).map((k) => caches.delete(k)))));
  }
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin === self.location.origin) {
    if (url.pathname.startsWith("/static/")) {
      event.respondWith(DEBUG ? networkFirst(event, false) : cacheFirst(request));
    } else if (!url.search && SAVED.some((pattern) => pattern.test(url.pathname))) {
      event.respondWith(networkFirst(event, PAGE.test(url.pathname)));
    }
    return;
  }
  if (CDN_HOSTS.includes(url.hostname)) event.respondWith(cacheFirst(request));
});

async function cacheFirst(request) {
  const cache = await caches.open(CACHE);
  const hit = await cache.match(request, MATCH);
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok || response.type === "opaque") cache.put(request, response.clone());
  return response;
}

// The network's answer whenever there is one (a 404 or a login redirect included: access may
// have changed); the saved copy only when the network fails or takes over TIMEOUT_MS.
async function networkFirst(event, isPage) {
  const request = event.request;
  const cache = await caches.open(CACHE);
  const network = fetch(request).then((response) => {
    if (response.ok && !response.redirected && response.type === "basic") {
      return cache.put(request, response.clone()).then(() => response);
    }
    if (response.status === 403 || response.status === 404) cache.delete(request, MATCH);
    return response;
  });
  event.waitUntil(network.catch(() => null));
  const saved = await cache.match(request, MATCH);
  if (!saved) return network;
  const timeout = new Promise((resolve) => setTimeout(() => resolve(null), TIMEOUT_MS));
  const answer = await Promise.race([network, timeout]).catch(() => null);
  if (answer) return answer;
  return isPage ? markOffline(saved) : saved;
}

async function markOffline(response) {
  const html = await response.text();
  return new Response(html.replace("data-sbl-offline hidden", "data-sbl-offline"),
                      { status: 200, headers: response.headers });
}
