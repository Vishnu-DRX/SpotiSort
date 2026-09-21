/* Dashboard data layer: sources, fetching, freshness. No external requests except the configured GitHub raw folder. */
(function () {
  'use strict';

  var FILES = {
    plan: 'latest-plan.json',
    runs: 'runs.json',
    coverage: 'enrichment-coverage.json',
    precision: 'signal-precision.json',
    backtest: 'backtest.json',
    detail: 'backtest-detail.json'
  };
  var COMMANDS = {
    plan: 'python -m src.sync',
    runs: 'python -m src.sync',
    coverage: 'python -m src.enrich --report',
    precision: 'python -m src.backtest',
    backtest: 'python -m src.backtest',
    detail: 'python -m src.backtest'
  };
  var LABELS = {
    plan: 'Inbox snapshot', runs: 'Run history', coverage: 'Enrichment coverage',
    precision: 'Signal precision', backtest: 'Backtest', detail: 'Backtest detail'
  };
  var SOURCES = ['local', 'repo', 'fixtures'];
  var FIXTURE_NOW = '2026-09-21T07:00:00Z'; // fixtures are frozen in time; the demo must not look stale
  var STALE_MS = 2 * 24 * 3600 * 1000;
  var KEY = { source: 'spotisort.dashboard.source', repo: 'spotisort.dashboard.repo', theme: 'spotisort.theme' };
  var RAW_RE = /^https:\/\/raw\.githubusercontent\.com\/[\w.-]+\/[\w.-]+\/[\w.\/-]+\/$/;

  function store(op, key, value) {
    try {
      if (op === 'get') return window.localStorage.getItem(key);
      if (op === 'set') window.localStorage.setItem(key, value);
      if (op === 'del') window.localStorage.removeItem(key);
    } catch (e) { /* storage blocked: fall back to defaults */ }
    return null;
  }

  function params() { return new URLSearchParams(location.search); }

  function isLoopback() { return /^(127\.0\.0\.1|localhost|\[::1\])$/.test(location.hostname); }

  function currentSource() {
    var q = params().get('source');
    if (q && SOURCES.indexOf(q) >= 0) return q;
    var saved = store('get', KEY.source);
    if (saved && SOURCES.indexOf(saved) >= 0) return saved;
    return isLoopback() ? 'local' : 'repo';
  }

  function deriveRepoBase() {
    var m = /^([^.]+)\.github\.io$/i.exec(location.hostname);
    var seg = location.pathname.split('/')[1];
    if (m && seg && seg.indexOf('.') < 0) return 'https://raw.githubusercontent.com/' + m[1] + '/' + seg + '/main/logs/';
    return '';
  }

  function normalizeRepoBase(v) {
    v = (v || '').trim();
    if (v && v.charAt(v.length - 1) !== '/') v += '/';
    return v;
  }

  function validRepoBase(v) { return RAW_RE.test(v); }

  function repoBase() {
    var saved = store('get', KEY.repo);
    return saved ? saved : deriveRepoBase();
  }

  function baseFor(source) {
    if (source === 'fixtures') return new URL('fixtures/', document.baseURI).href;
    if (source === 'local') return new URL('/data/', location.href).href;
    return repoBase();
  }

  function now() {
    var q = params().get('now');
    var t = q ? Date.parse(q) : NaN;
    if (!isNaN(t)) return t;
    return currentSource() === 'fixtures' ? Date.parse(FIXTURE_NOW) : Date.now();
  }

  function fetchJson(url) {
    if (!url) return Promise.resolve({ status: 'error', message: 'No source URL is configured.' });
    return fetch(url, { cache: 'no-store', credentials: 'omit' }).then(function (r) {
      if (r.status === 404) return { status: 'missing' };
      if (!r.ok) return { status: 'error', message: 'HTTP ' + r.status + ' from ' + url };
      return r.text().then(function (t) {
        try { return { status: 'ok', data: JSON.parse(t) }; }
        catch (e) { return { status: 'error', message: 'The file is not valid JSON (' + url + ').' }; }
      });
    }).catch(function (e) {
      return { status: 'error', message: 'Could not reach ' + url + ' (' + (e && e.message ? e.message : 'network error') + ').' };
    });
  }

  function loadAll(source) {
    var base = baseFor(source);
    var keys = Object.keys(FILES);
    return Promise.all(keys.map(function (k) { return fetchJson(base ? base + FILES[k] : ''); })).then(function (res) {
      var files = {};
      keys.forEach(function (k, i) { files[k] = res[i]; });
      return { source: source, base: base, files: files };
    });
  }

  var logCache = {};
  function fetchLog(base, name) {
    var url = base + name;
    if (!logCache[url]) logCache[url] = fetchJson(url);
    return logCache[url];
  }
  function clearLogCache() { logCache = {}; }

  function stampOf(file) {
    if (!file || file.status !== 'ok' || !file.data) return null;
    var g = file.data.generated_at || file.data.date;
    if (!g) return null;
    if (/^\d{4}-\d{2}-\d{2}$/.test(g)) g += 'T00:00:00Z';
    return isNaN(Date.parse(g)) ? null : g;
  }

  function fmtTime(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return String(iso || '');
    return d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
  }
  function fmtDate(iso) {
    var d = new Date(iso);
    return isNaN(d) ? String(iso || '') : d.toISOString().slice(0, 10);
  }
  function rel(iso) {
    var diff = now() - Date.parse(iso);
    if (isNaN(diff)) return '';
    if (diff < -60000) return 'in the future';
    var m = Math.floor(Math.abs(diff) / 60000);
    if (m < 2) return 'just now';
    if (m < 90) return m + ' min ago';
    var h = Math.floor(m / 60);
    if (h < 36) return h + ' h ago';
    return Math.floor(h / 24) + ' d ago';
  }
  function isStale(iso) { return now() - Date.parse(iso) > STALE_MS; }

  window.DashData = {
    FILES: FILES, COMMANDS: COMMANDS, LABELS: LABELS, SOURCES: SOURCES, KEY: KEY,
    store: store, params: params, currentSource: currentSource, deriveRepoBase: deriveRepoBase, repoBase: repoBase,
    normalizeRepoBase: normalizeRepoBase, validRepoBase: validRepoBase, baseFor: baseFor,
    now: now, loadAll: loadAll, fetchLog: fetchLog, clearLogCache: clearLogCache,
    stampOf: stampOf, fmtTime: fmtTime, fmtDate: fmtDate, rel: rel, isStale: isStale
  };
})();
