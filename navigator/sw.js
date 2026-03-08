/**
 * DRGRNav Service Worker — offline tile + asset caching.
 *
 * Strategy:
 *   - App shell (HTML/JS/CSS) → Cache-first, network fallback
 *   - Map tiles (tile.openstreetmap.org) → Stale-while-revalidate, up to 2000 tiles
 *   - Routing API (router.project-osrm.org) → Network-first, cache fallback (1 h TTL)
 */

const CACHE_VERSION = 'drgrnav-v1';
const TILE_CACHE    = 'drgrnav-tiles-v1';
const ROUTE_CACHE   = 'drgrnav-routes-v1';

const APP_SHELL = [
  '/navigator/',
  '/navigator/index.html',
];

const MAX_TILES  = 2000;
const MAX_ROUTES = 200;

// ── Install: cache app shell ─────────────────────────────────────────────────
self.addEventListener('install', (evt) => {
  evt.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

// ── Activate: clean up old caches ────────────────────────────────────────────
self.addEventListener('activate', (evt) => {
  evt.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== CACHE_VERSION && k !== TILE_CACHE && k !== ROUTE_CACHE)
          .map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// ── Fetch interceptor ─────────────────────────────────────────────────────────
self.addEventListener('fetch', (evt) => {
  const { url } = evt.request;

  // Parse origin/hostname once so substring checks cannot be bypassed by
  // malicious hostnames that embed the trusted hostname as a substring.
  let reqHostname = '';
  try { reqHostname = new URL(url).hostname; } catch { /* relative URL — skip */ }

  // Map tiles — stale-while-revalidate
  if (reqHostname === 'tile.openstreetmap.org' || reqHostname.endsWith('.tile.openstreetmap.org')) {
    evt.respondWith(handleTile(evt.request));
    return;
  }

  // OSRM routing — network-first
  if (reqHostname === 'router.project-osrm.org') {
    evt.respondWith(handleRoute(evt.request));
    return;
  }

  // Nominatim geocoding — network-first, short cache
  if (reqHostname === 'nominatim.openstreetmap.org') {
    evt.respondWith(handleRoute(evt.request));
    return;
  }

  // App shell — cache-first
  evt.respondWith(
    caches.match(evt.request).then((cached) => cached || fetch(evt.request))
  );
});

async function handleTile(request) {
  const cache  = await caches.open(TILE_CACHE);
  const cached = await cache.match(request);

  // Always return cached version immediately; refresh in background
  if (cached) {
    fetchAndStore(cache, request, MAX_TILES).catch(() => {});
    return cached;
  }

  try {
    const response = await fetch(request);
    if (response.ok) {
      await trimCache(cache, MAX_TILES);
      await cache.put(request, response.clone());
    }
    return response;
  } catch {
    // Offline and no cached tile — return a transparent 256×256 PNG placeholder
    return new Response(EMPTY_TILE, { headers: { 'Content-Type': 'image/png' } });
  }
}

async function handleRoute(request) {
  const cache = await caches.open(ROUTE_CACHE);
  try {
    const response = await fetch(request);
    if (response.ok) {
      await trimCache(cache, MAX_ROUTES);
      await cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await cache.match(request);
    if (cached) return cached;
    return new Response(JSON.stringify({ error: 'offline' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}

async function fetchAndStore(cache, request, maxEntries) {
  const response = await fetch(request);
  if (response.ok) {
    await trimCache(cache, maxEntries);
    await cache.put(request, response.clone());
  }
}

async function trimCache(cache, maxEntries) {
  const keys = await cache.keys();
  if (keys.length >= maxEntries) {
    // Remove oldest 10 % of the current cache size when limit is reached
    const toDelete = keys.slice(0, Math.ceil(keys.length * 0.1));
    await Promise.all(toDelete.map((k) => cache.delete(k)));
  }
}

// Minimal 1×1 transparent PNG (base64) returned as placeholder for missing tiles
const EMPTY_TILE = Uint8Array.from(
  atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='),
  (c) => c.charCodeAt(0)
);
