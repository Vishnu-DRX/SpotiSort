// SpotiSort service worker: cache-first for the app shell so the builder works offline.
// Bump CACHE_VERSION whenever any cached file changes. All URLs are relative to this file
// (works under the /SpotiSort/ GitHub Pages base path).
const CACHE_VERSION = 'v8';
const CACHE_NAME = 'spotisort-shell-' + CACHE_VERSION;
const SHELL = [
  './',
  'index.html',
  'style.css',
  'app.js',
  'manifest.webmanifest',
  '404.html',
  'site.config.json',
  'setup/',
  'setup/index.html',
  'builder/',
  'builder/index.html',
  'builder/builder.css',
  'builder/app.js',
  'builder/validate.js',
  'builder/languages.js',
  'builder/schema.js',
  'vendor/js-yaml.min.js',
  'icons/favicon-32.png',
  'icons/icon-180.png',
  'icons/icon-192.png',
  'icons/icon-512.png',
  'icons/icon-maskable-512.png',
  'assets/favicon.svg',
  'assets/og.png',
  'assets/tokens.css',
  'assets/components.css',
  'assets/site.css',
  'assets/ui.js',
  'assets/shell.js',
  'dashboard/',
  'dashboard/index.html',
  'dashboard/dashboard.css',
  'dashboard/data.js',
  'dashboard/views.js',
  'dashboard/app.js',
  'dashboard/fixtures/2026-09-14.json',
  'dashboard/fixtures/2026-09-15.json',
  'dashboard/fixtures/2026-09-16.json',
  'dashboard/fixtures/2026-09-17.json',
  'dashboard/fixtures/2026-09-18.json',
  'dashboard/fixtures/2026-09-19.json',
  'dashboard/fixtures/2026-09-20.json',
  'dashboard/fixtures/2026-09-21.json',
  'dashboard/fixtures/backtest-detail.json',
  'dashboard/fixtures/backtest.json',
  'dashboard/fixtures/enrichment-coverage.json',
  'dashboard/fixtures/latest-plan.json',
  'dashboard/fixtures/runs.json',
  'dashboard/fixtures/signal-precision.json',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL.map((p) => new Request(new URL(p, self.location).href, { cache: 'reload' }))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('spotisort-shell-') && k !== CACHE_NAME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  event.respondWith(
    caches.open(CACHE_NAME).then(async (cache) => {
      const hit = await cache.match(req, { ignoreSearch: true });
      if (hit) return hit;
      try {
        return await fetch(req);
      } catch (err) {
        if (req.mode === 'navigate') {
          const shell = await cache.match(new URL('index.html', self.location).href);
          if (shell) return shell;
        }
        throw err;
      }
    })
  );
});
