/* SpotiSort site shell (Master decision 25/26). Renders the sticky header and footer into ONE placeholder
   element and appends the footer to <body>. No build step, no bundler: works from the Pages root
   (/SpotiSort/), from a fork's own path (/<repo>/), and from a local `python -m http.server` root.

   ---------------------------------------------------------------------------------------------------
   USAGE (every page that wants the shell):
     1. One script tag, anywhere, ideally right after <body> opens:
          <script src="RELATIVE/PATH/TO/assets/shell.js" defer data-active="home"></script>
        `data-active` is one of: home | configure | dashboard | setup | none (default). It only controls
        which nav link gets `aria-current="page"`.
     2. One placeholder element, where the header should appear (normally the very first thing in <body>):
          <div id="site-shell">
            <noscript>
              <p><a href="RELATIVE/index.html">SpotiSort</a> ·
                 <a href="RELATIVE/builder/">Configure</a> ·
                 <a href="RELATIVE/dashboard/">Dashboard</a> ·
                 <a href="RELATIVE/setup/">Setup guide</a> ·
                 <a href="https://github.com/Vishnu-DRX/SpotiSort">GitHub</a></p>
            </noscript>
          </div>
        The <noscript> fallback is REQUIRED (decision 25: "must also work with a <noscript> fallback of
        plain links"). Everything inside #site-shell other than the <noscript> block is replaced.
     3. The footer is appended to the end of <body> automatically; give <body> a normal `<main id="main">`
        in between so the skip link (rendered by the header) has something to jump to.
     4. Site config (name/socials) lives in ONE file: docs/site.config.json, fetched relative to the
        script's own location (so it works from any depth/fork). Render only keys that are present.

   No other page may special-case the header/footer HTML: change THIS file only.
   --------------------------------------------------------------------------------------------------- */
(function () {
  'use strict';
  var doc = document;

  // Resolve our own <script> element even when loaded with `defer` (currentScript is still valid then).
  var thisScript = doc.currentScript || (function () {
    var s = doc.querySelectorAll('script[src*="shell.js"]');
    return s[s.length - 1];
  })();
  var SCRIPT_URL = new URL(thisScript.getAttribute('src'), doc.baseURI).href;
  // ROOT = the docs/ folder this site is served from, as an absolute URL. Every nav link is built from
  // this, so the header works identically at any depth and on any fork path.
  var ROOT = SCRIPT_URL.replace(/assets\/shell\.js(?:\?.*)?$/, '');
  var ACTIVE = thisScript.getAttribute('data-active') || 'none';
  var UPSTREAM_OWNER = 'Vishnu-DRX';
  var UPSTREAM_REPO = 'SpotiSort';
  var UPSTREAM_URL = 'https://github.com/' + UPSTREAM_OWNER + '/' + UPSTREAM_REPO;

  function el(tag, attrs, html) {
    var e = doc.createElement(tag);
    for (var k in attrs) if (attrs.hasOwnProperty(k)) e.setAttribute(k, attrs[k]);
    if (html != null) e.innerHTML = html;
    return e;
  }

  function svgLogo(size) {
    // Original mark: a rounded square with an upward "sort" chevron stack + a dot — not Spotify's logo/wordmark.
    return '<svg class="brand-mark" width="' + size + '" height="' + size + '" viewBox="0 0 32 32" role="img" aria-hidden="true">' +
      '<rect x="1" y="1" width="30" height="30" rx="9" fill="var(--color-accent)"/>' +
      '<path d="M9 20l7-7 7 7" stroke="var(--color-on-accent)" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>' +
      '<path d="M9 13l7-7 7 7" stroke="var(--color-on-accent)" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round" opacity="0.55"/>' +
      '</svg>';
  }

  var NAV = [
    { id: 'home', label: 'Home', href: ROOT + 'index.html' },
    { id: 'configure', label: 'Configure', href: ROOT + 'builder/' },
    { id: 'dashboard', label: 'Dashboard', href: ROOT + 'dashboard/' },
    { id: 'setup', label: 'Setup guide', href: ROOT + 'setup/' },
    { id: 'github', label: 'GitHub', href: UPSTREAM_URL }
  ];

  function renderHeader() {
    var nav = NAV.map(function (item) {
      var current = item.id === ACTIVE ? ' aria-current="page"' : '';
      var external = item.id === 'github' ? ' rel="noopener"' : '';
      return '<a class="site-nav-link" href="' + item.href + '"' + current + external + '>' + item.label + '</a>';
    }).join('');

    var header = el('header', { class: 'site-header' });
    header.innerHTML =
      '<a class="skip-link" href="#main">Skip to content</a>' +
      '<div class="site-header-bar container">' +
      '<a class="brand" href="' + ROOT + 'index.html">' + svgLogo(28) + '<span class="brand-name">SpotiSort</span></a>' +
      '<nav class="site-nav" id="site-nav" aria-label="Primary">' + nav + '</nav>' +
      '<div class="site-header-actions">' +
      '<button type="button" class="btn btn-icon" data-theme-toggle aria-label="Switch theme">' +
      '<svg class="icon icon-moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12.8A9 9 0 1111.2 3 7 7 0 0021 12.8z"/></svg>' +
      '<svg class="icon icon-sun" viewBox="0 0 24 24" aria-hidden="true" hidden><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>' +
      '</button>' +
      '<button type="button" class="btn btn-icon site-menu-btn" id="site-menu-btn" aria-controls="site-nav" aria-expanded="false" aria-label="Open menu">' +
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>' +
      '</button>' +
      '</div></div>';
    return header;
  }

  function socialIcon(key) {
    var paths = {
      github: '<path d="M12 2a10 10 0 00-3.16 19.49c.5.09.68-.22.68-.48v-1.7c-2.78.6-3.37-1.34-3.37-1.34-.46-1.16-1.11-1.47-1.11-1.47-.9-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.9 1.52 2.34 1.08 2.91.83.09-.65.35-1.08.63-1.33-2.22-.25-4.56-1.11-4.56-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02a9.5 9.5 0 015 0c1.91-1.29 2.75-1.02 2.75-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.68-4.57 4.93.36.31.68.92.68 1.85v2.74c0 .27.18.58.69.48A10 10 0 0012 2z"/>',
      linkedin: '<rect x="2" y="9" width="4" height="12"/><circle cx="4" cy="4" r="2"/><path d="M10 9h4v2c.6-1 1.9-2.2 3.9-2.2 3 0 4.1 2 4.1 5.1V21h-4v-6.4c0-1.5 0-3.4-2.1-3.4s-2.4 1.6-2.4 3.3V21h-4z"/>',
      x: '<path d="M4 4l16 16M20 4L4 20"/>',
      instagram: '<rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1"/>',
      website: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a15 15 0 010 18 15 15 0 010-18z"/>',
      youtube: '<rect x="2" y="5" width="20" height="14" rx="4"/><path d="M10 9l6 3-6 3z" fill="currentColor" stroke="none"/>'
    };
    return paths[key] || null;
  }

  function renderFooter(config) {
    config = config || {};
    var year = new Date().getFullYear();
    var footer = el('footer', { class: 'site-footer' });
    var socialKeys = ['github', 'linkedin', 'x', 'instagram', 'website', 'youtube'];
    var socialsHtml = '';
    socialKeys.forEach(function (key) {
      var url = config[key];
      if (!url) return; // render only keys that exist — no placeholders
      var d = socialIcon(key);
      if (!d) return;
      socialsHtml += '<a class="btn btn-icon btn-sm" href="' + url + '" rel="noopener" aria-label="' + config.name_label_prefix + capitalize(key) + '">' +
        '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6">' + d + '</svg></a>';
    });
    var creditHtml = config.name
      ? '<p class="site-footer-credit">Built by <a href="' + (config.github || '#') + '" rel="noopener">' + escapeHtml(config.name) + '</a></p>'
      : '';

    footer.innerHTML =
      '<div class="container site-footer-inner">' +
      '<p class="site-footer-disclaimer">SpotiSort is an independent open-source project, not affiliated with or endorsed by Spotify.</p>' +
      '<div class="site-footer-row">' +
      '<div class="site-footer-links">' +
      '<a href="' + UPSTREAM_URL + '" rel="noopener">Upstream repository</a>' +
      '<span class="site-footer-star" id="site-star" aria-hidden="true"></span>' +
      '<a id="site-fork-link" href="#" hidden rel="noopener">Your fork</a>' +
      '</div>' +
      (creditHtml || socialsHtml ? '<div class="site-footer-credit-row">' + creditHtml + (socialsHtml ? '<span class="cluster site-footer-socials">' + socialsHtml + '</span>' : '') + '</div>' : '') +
      '</div>' +
      '<p class="site-footer-copy muted small">&copy; ' + year + ' · MIT licence · <a href="' + UPSTREAM_URL + '/blob/main/LICENSE">LICENSE</a></p>' +
      '</div>';
    return footer;
  }

  function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }
  function escapeHtml(s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }

  /* ---- GitHub star count: fetch, cache in sessionStorage, fail silently (decision 26). ---- */
  function loadStars() {
    var slot = doc.getElementById('site-star');
    if (!slot) return;
    var cacheKey = 'spotisort-stars-' + UPSTREAM_OWNER + '-' + UPSTREAM_REPO;
    try {
      var cached = sessionStorage.getItem(cacheKey);
      if (cached) { slot.textContent = '★ ' + cached; return; }
    } catch (e) { /* storage blocked: fall through to a live fetch, still fine */ }
    fetch('https://api.github.com/repos/' + UPSTREAM_OWNER + '/' + UPSTREAM_REPO, { headers: { Accept: 'application/vnd.github+json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || typeof data.stargazers_count !== 'number') return;
        var n = String(data.stargazers_count);
        slot.textContent = '★ ' + n;
        try { sessionStorage.setItem(cacheKey, n); } catch (e) { /* ignore */ }
      })
      .catch(function () { /* offline / rate-limited / blocked: silent, no UI change */ });
  }

  /* ---- "Your fork" link: <owner>.github.io/<repo> => github.com/<owner>/<repo> (decision 26). ---- */
  function deriveFork(loc) {
    loc = loc || window.location;
    var host = loc.hostname || '';
    var m = /^([a-z0-9-]+)\.github\.io$/i.exec(host);
    if (!m) return null; // not served from *.github.io (localhost, a custom domain, a fork's own domain, etc.)
    var owner = m[1];
    var seg = (loc.pathname || '/').split('/').filter(Boolean)[0];
    if (!seg) return null; // served from the root of a user/org page, not a project page
    if (owner.toLowerCase() === UPSTREAM_OWNER.toLowerCase() && seg.toLowerCase() === UPSTREAM_REPO.toLowerCase()) return null; // it IS upstream
    return { owner: owner, repo: seg, url: 'https://github.com/' + owner + '/' + seg };
  }

  function wireFork() {
    var a = doc.getElementById('site-fork-link');
    if (!a) return;
    var fork = deriveFork();
    if (!fork) return;
    a.href = fork.url;
    a.hidden = false;
  }

  /* ---- mobile menu ---- */
  function wireMenu(header) {
    var btn = header.querySelector('#site-menu-btn');
    var nav = header.querySelector('#site-nav');
    function set(openState) {
      btn.setAttribute('aria-expanded', String(openState));
      btn.setAttribute('aria-label', openState ? 'Close menu' : 'Open menu');
      nav.classList.toggle('is-open', openState);
    }
    btn.addEventListener('click', function () { set(btn.getAttribute('aria-expanded') !== 'true'); });
    doc.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && btn.getAttribute('aria-expanded') === 'true') { set(false); btn.focus(); }
    });
    nav.querySelectorAll('a').forEach(function (a) {
      a.addEventListener('click', function () { set(false); });
    });
    // Collapse back to the desktop layout state when resizing past the mobile breakpoint.
    var mq = window.matchMedia('(min-width: 861px)');
    function syncMq() { if (mq.matches) set(false); }
    if (mq.addEventListener) mq.addEventListener('change', syncMq); else if (mq.addListener) mq.addListener(syncMq);
  }

  function mount() {
    var placeholder = doc.getElementById('site-shell');
    if (!placeholder) return;
    var header = renderHeader();
    placeholder.parentNode.insertBefore(header, placeholder);
    placeholder.parentNode.removeChild(placeholder);
    wireMenu(header);

    fetch(ROOT + 'site.config.json')
      .then(function (r) { return r.ok ? r.json() : {}; })
      .catch(function () { return {}; })
      .then(function (config) {
        var footer = renderFooter(config || {});
        doc.body.appendChild(footer);
        wireFork();
        loadStars();
        if (window.SpotiUI) window.SpotiUI.init(footer);
      });

    if (window.SpotiUI) window.SpotiUI.init(header);
  }

  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', mount); else mount();

  // Exposed for the fork-link unit test (decision 30: "unit-tested via URL override") and for debugging.
  window.SpotiShell = { deriveFork: deriveFork, ROOT: ROOT, UPSTREAM_URL: UPSTREAM_URL };
})();
