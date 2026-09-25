/* Dashboard shell: hash routing, source switching, Explain drawer. */
(function () {
  'use strict';
  var D = window.DashData, VW = window.DashViews, V = VW.VIEWS, esc = VW.esc;

  var root = document.getElementById('view-root');
  var tabsEl = document.getElementById('tabs');
  var drawerRoot = document.getElementById('drawer-root');
  var srcSel = document.getElementById('source-select');
  var repoField = document.getElementById('repo-field');
  var repoUrl = document.getElementById('repo-url');
  var repoSave = document.getElementById('repo-save');
  var repoHint = document.getElementById('repo-hint');
  var themeBtn = document.getElementById('theme-btn');
  var sourceCurrent = document.getElementById('source-current');
  var filesField = document.getElementById('files-field');
  var filesDrop = document.getElementById('files-drop');
  var filesInput = document.getElementById('files-input');
  var filesStatus = document.getElementById('files-status');
  var glossaryBody = document.getElementById('glossary-body');

  var data = null;          // {source, base, files}
  var state = {};           // per-view UI state that survives re-render
  var token = 0;
  var drawer = { open: false, trigger: null };
  window.__dash = { ready: false, renders: 0, source: null };

  // ------------------------------------------------------------------ theme
  function applyTheme(t) {
    if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t);
    else document.documentElement.removeAttribute('data-theme');
    var name = t === 'light' || t === 'dark' ? t : 'auto';
    themeBtn.setAttribute('aria-label', 'Colour theme: ' + name + '. Activate to change.');
    themeBtn.title = 'Colour theme: ' + name;
  }
  var theme = D.store('get', D.KEY.theme) || 'auto';
  applyTheme(theme);
  themeBtn.addEventListener('click', function () {
    theme = theme === 'auto' ? 'light' : (theme === 'light' ? 'dark' : 'auto');
    D.store('set', D.KEY.theme, theme);
    applyTheme(theme);
  });

  // ------------------------------------------------------------------ routing
  function parseRoute() {
    var h = location.hash.replace(/^#\/?/, '');
    var qi = h.indexOf('?');
    var query = new URLSearchParams(qi >= 0 ? h.slice(qi + 1) : '');
    var path = (qi >= 0 ? h.slice(0, qi) : h).split('/');
    var name = path[0] && V[path[0]] ? path[0] : 'overview';
    var arg = path[1] ? decodeURIComponent(path.slice(1).join('/')) : '';
    return { name: name, arg: arg, query: query };
  }

  function buildTabs(active) {
    tabsEl.innerHTML = VW.ORDER.map(function (k) {
      return '<li><a href="#/' + k + '"' + (k === active ? ' aria-current="page"' : '') + '>' + esc(V[k].label) + '</a></li>';
    }).join('');
  }

  function go(hash) { location.hash = hash; }

  function render(focusHeading) {
    var my = ++token;
    var route = parseRoute();
    var view = V[route.name];
    buildTabs(route.name);
    document.title = view.label + ' · SpotiSort dashboard';
    if (!data) return Promise.resolve();
    var ctx = { files: data.files, base: data.base, source: data.source, state: state, query: route.query, arg: route.arg, go: go };
    var body;
    try { body = view.render(ctx); } catch (e) { body = '<div class="errorbox" role="alert"><h3>This view failed to draw</h3><p>' + esc(e && e.message) + '</p></div>'; }
    root.setAttribute('aria-busy', 'true');
    return Promise.resolve(body).catch(function (e) {
      return '<div class="errorbox" role="alert"><h3>This view failed to draw</h3><p>' + esc(e && e.message) + '</p></div>';
    }).then(function (html) {
      if (my !== token) return;
      root.innerHTML = VW.viewHead(ctx, view, route.name) + html;
      root.setAttribute('data-view', route.name);
      root.setAttribute('data-state', 'ready');
      root.removeAttribute('aria-busy');
      try { if (view.bind) view.bind(root, ctx); } catch (e) { /* a view's optional interactions failed; content is still shown */ }
      if (focusHeading) { var h = document.getElementById('view-title'); if (h) h.focus({ preventScroll: false }); }
      window.__dash.renders++;
      window.__dash.ready = true;
    });
  }

  // ------------------------------------------------------------------ data + source bar
  function hintText(source) {
    if (source === 'files') return 'Read entirely in this browser from files you choose or drop below. Nothing is uploaded anywhere, including to us. This is the only source that shows real song titles on a public site, because it never leaves your computer.';
    if (source === 'fixtures') return 'Demo data bundled with this site. Nothing is fetched from your computer or GitHub.';
    return 'Reads the JSON files from your fork on raw.githubusercontent.com. Only that address is contacted.';
  }
  function filesStatusText() {
    var names = D.localFileNames();
    if (!names.length) return 'No files chosen yet.';
    return 'Loaded: ' + names.join(', ') + '.';
  }
  function syncBar(source) {
    srcSel.value = source;
    var isRepo = source === 'repo';
    var isFiles = source === 'files';
    repoField.hidden = !isRepo;
    repoSave.hidden = !isRepo;
    filesField.hidden = !isFiles;
    if (isRepo) repoUrl.value = D.repoBase();
    if (isFiles) filesStatus.textContent = filesStatusText();
    repoHint.textContent = hintText(source) + (isRepo && !D.repoBase() ? ' Enter the raw URL of your logs folder, for example https://raw.githubusercontent.com/OWNER/REPO/main/logs/' : '');
    // decision 31: a persistent, unmissable label of which source is showing (not just the dropdown's own value,
    // which can scroll out of view or be easy to skim past).
    sourceCurrent.textContent = 'Showing: ' + D.SOURCE_LABELS[source];
    window.__dash.source = source;
  }

  function load() {
    var source = D.currentSource();
    syncBar(source);
    root.setAttribute('data-state', 'loading');
    root.setAttribute('aria-busy', 'true');
    root.innerHTML = '<p class="loading" role="status">Loading data…</p>';
    D.clearLogCache();
    return D.loadAll(source).then(function (d) { data = d; return render(false); });
  }

  function setSourceParam(source) {
    var u = new URL(location.href);
    u.searchParams.set('source', source);
    history.replaceState(null, '', u.pathname + u.search + u.hash);
  }

  srcSel.addEventListener('change', function () {
    D.store('set', D.KEY.source, srcSel.value);
    setSourceParam(srcSel.value);
    load();
  });
  document.getElementById('reload-btn').addEventListener('click', function () { load(); });
  function saveRepo() {
    var v = D.normalizeRepoBase(repoUrl.value);
    if (!D.validRepoBase(v)) {
      repoHint.textContent = 'That does not look right. It must be a folder on raw.githubusercontent.com, like https://raw.githubusercontent.com/OWNER/REPO/main/logs/';
      repoUrl.setAttribute('aria-invalid', 'true');
      return;
    }
    repoUrl.removeAttribute('aria-invalid');
    repoUrl.value = v;
    D.store('set', D.KEY.repo, v);
    load();
  }
  repoSave.addEventListener('click', saveRepo);
  repoUrl.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); saveRepo(); } });

  // ------------------------------------------------------------------ Open local files (decision 31)
  function handleFiles(fileList) {
    if (!fileList || !fileList.length) return;
    filesStatus.textContent = 'Reading ' + fileList.length + ' file(s)…';
    D.readLocalFiles(fileList).then(function (result) {
      var msg = filesStatusText();
      if (result.errors.length) msg += ' Could not read: ' + result.errors.map(function (e) { return e.name; }).join(', ') + '.';
      filesStatus.textContent = msg;
      if (D.currentSource() === 'files') load();
    });
  }
  filesInput.addEventListener('change', function () { handleFiles(filesInput.files); });
  filesDrop.addEventListener('click', function () { filesInput.click(); });
  filesDrop.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); filesInput.click(); } });
  ['dragenter', 'dragover'].forEach(function (evt) {
    filesDrop.addEventListener(evt, function (e) { e.preventDefault(); e.stopPropagation(); filesDrop.classList.add('is-drag'); });
  });
  ['dragleave', 'dragend'].forEach(function (evt) {
    filesDrop.addEventListener(evt, function (e) { e.preventDefault(); filesDrop.classList.remove('is-drag'); });
  });
  filesDrop.addEventListener('drop', function (e) {
    e.preventDefault(); e.stopPropagation();
    filesDrop.classList.remove('is-drag');
    var dt = e.dataTransfer;
    if (dt && dt.files && dt.files.length) handleFiles(dt.files);
  });

  // ------------------------------------------------------------------ glossary drawer (decision 34)
  var GLOSSARY = [
    ['Inbox', 'The songs currently sitting in Liked Songs, waiting to be evaluated or moved.'],
    ['Eligible', 'A song has waited long enough (its rule’s threshold) and can move on the next run.'],
    ['Shadowed rule', 'A rule that songs would match, but an earlier rule in the list always takes them first, so this one never wins.'],
    ['Dead rule', 'A rule that no song in the current inbox matches at all.'],
    ['Signal tier', 'How a song’s language was worked out: your own playlists, the title’s script, a weaker hint, or a country default — in that order of trust.'],
    ['Confidence', 'How sure SpotiSort is about a signal such as language, shown as a percentage.'],
    ['Precision', 'Of the songs a signal or rule sent somewhere, the share that were actually right.'],
    ['Recall', 'Of all the songs that truly belong somewhere, the share that were actually found and routed there.'],
    ['Reconcile', 'The safety check after a real run: before minus removed should equal after. A mismatch means something needs attention.'],
    ['Journal', 'The record of every song removed from Liked Songs during a run, kept so it can be restored.'],
    ['What-if', 'A preview mode that treats disabled rules as if they were enabled, so you can see what they would do before switching them on.']
  ];
  if (glossaryBody) {
    glossaryBody.innerHTML = '<dl class="kv">' + GLOSSARY.map(function (g) {
      return '<dt>' + g[0] + '</dt><dd>' + g[1] + '</dd>';
    }).join('') + '</dl>';
  }

  // ------------------------------------------------------------------ explain drawer
  function focusables(el) {
    return Array.prototype.slice.call(el.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')).filter(function (n) { return !n.disabled && n.offsetParent !== null; });
  }
  function setInert(on) {
    Array.prototype.forEach.call(document.querySelectorAll('.site-head, .wrap, .site-foot, .skip'), function (n) {
      if (on) n.setAttribute('inert', ''); else n.removeAttribute('inert');
    });
  }
  function openDrawer(index, trigger) {
    var p = data && data.files.plan.status === 'ok' ? data.files.plan.data : null;
    var song = p && p.songs[index];
    if (!song) return;
    drawer.open = true;
    drawer.trigger = trigger || null;
    var titlesHidden = !!p.titles_hidden;
    var heading = titlesHidden ? 'Title hidden — open local files to see titles' : song.title;
    drawerRoot.innerHTML = '<div class="scrim" data-close="1"></div><aside class="drawer" id="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title">' +
      '<div class="drawer-head"><h2 id="drawer-title">' + esc(heading) + '<span class="sub">' + (titlesHidden ? '' : esc((song.artists || []).join(', '))) + '</span></h2>' +
      '<button type="button" class="icon-btn" data-close="1" aria-label="Close explanation">✕</button></div>' +
      '<div class="drawer-body" data-testid="explain-body">' + VW.explainHtml(song, p) + '</div></aside>';
    setInert(true);
    var close = drawerRoot.querySelector('button[data-close]');
    if (close) close.focus();
  }
  function closeDrawer() {
    if (!drawer.open) return;
    drawer.open = false;
    drawerRoot.innerHTML = '';
    setInert(false);
    var t = drawer.trigger;
    if (t && document.contains(t)) t.focus();
    else { var h = document.getElementById('view-title'); if (h) h.focus(); }
    drawer.trigger = null;
  }
  document.addEventListener('keydown', function (e) {
    if (!drawer.open) return;
    if (e.key === 'Escape') { e.preventDefault(); closeDrawer(); return; }
    if (e.key === 'Tab') {
      var dlg = document.getElementById('drawer');
      var items = dlg ? focusables(dlg) : [];
      if (!items.length) { e.preventDefault(); return; }
      var first = items[0], last = items[items.length - 1];
      if (e.shiftKey && (document.activeElement === first || !dlg.contains(document.activeElement))) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (document.activeElement === last || !dlg.contains(document.activeElement))) { e.preventDefault(); first.focus(); }
    }
  });
  drawerRoot.addEventListener('click', function (e) { if (e.target.closest('[data-close]')) closeDrawer(); });

  // ------------------------------------------------------------------ delegated actions
  root.addEventListener('click', function (e) {
    var ex = e.target.closest('[data-explain]');
    if (ex) { openDrawer(parseInt(ex.getAttribute('data-explain'), 10), ex); return; }
    if (e.target.closest('[data-action="reload"]')) { load(); return; }
    var cp = e.target.closest('[data-copy]');
    if (cp) {
      var text = cp.getAttribute('data-copy');
      var done = function () { var old = cp.textContent; cp.textContent = 'Copied'; setTimeout(function () { cp.textContent = old; }, 1500); };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, function () { });
    }
  });

  window.addEventListener('hashchange', function () { if (drawer.open) closeDrawer(); render(true); });

  if ('serviceWorker' in navigator && /^https?:$/.test(location.protocol)) {
    navigator.serviceWorker.register('../sw.js').catch(function () { /* offline support is optional */ });
  }

  load();
})();
