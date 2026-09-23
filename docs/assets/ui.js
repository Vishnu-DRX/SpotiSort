/* SpotiSort UI behaviours (Master decision 23/24). Vanilla, no dependencies. API: docs/assets/COMPONENTS.md.
   Exposes window.SpotiUI. Most behaviour is event-delegated, so dynamically inserted markup just works;
   call SpotiUI.init(root) after inserting markup that needs setup (tooltips, tabs, tag inputs, copy buttons, sortable tables). */
(function () {
  'use strict';
  var THEME_KEY = 'spotisort-theme';
  var doc = document, root = doc.documentElement;
  var uid = 0;
  // Apply a persisted theme choice as early as possible (before the rest of this file even parses further),
  // so a reload restores dark/light without waiting for DOMContentLoaded. A tiny inline snippet in each
  // page's <head> (before stylesheets) does the same thing synchronously to avoid a flash; this is the
  // fallback for any page that loads ui.js without that snippet.
  if (!root.hasAttribute('data-theme')) {
    try {
      var earlyTheme = localStorage.getItem(THEME_KEY);
      if (earlyTheme === 'light' || earlyTheme === 'dark') root.setAttribute('data-theme', earlyTheme);
    } catch (e) { /* storage blocked: falls back to prefers-color-scheme */ }
  }
  function $(s, r) { return (r || doc).querySelector(s); }
  function $$(s, r) { return Array.prototype.slice.call((r || doc).querySelectorAll(s)); }
  function nid(p) { uid += 1; return (p || 'ui') + '-' + uid; }
  function el(tag, cls, text) { var e = doc.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function store(k, v) {
    try { if (v === undefined) return localStorage.getItem(k); if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* storage blocked */ }
    return null;
  }
  function visible(e) { return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
  var FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]):not([type="hidden"]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex]:not([tabindex="-1"])';
  function focusables(c) { return $$(FOCUSABLE, c).filter(visible); }

  /* ---------------------------------------------------------------- theme */
  var theme = {
    stored: function () { var v = store(THEME_KEY); return v === 'light' || v === 'dark' ? v : null; },
    current: function () {
      var a = root.getAttribute('data-theme');
      if (a === 'light' || a === 'dark') return a;
      return window.matchMedia && matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    },
    set: function (t) {
      if (t !== 'light' && t !== 'dark') { root.removeAttribute('data-theme'); store(THEME_KEY, null); } else { root.setAttribute('data-theme', t); store(THEME_KEY, t); }
      theme.sync();
      doc.dispatchEvent(new CustomEvent('ui:theme', { detail: theme.current() }));
    },
    toggle: function () { theme.set(theme.current() === 'dark' ? 'light' : 'dark'); },
    sync: function () {
      var t = theme.current();
      $$('[data-theme-toggle]').forEach(function (b) {
        b.setAttribute('data-theme-now', t);
        b.setAttribute('aria-label', t === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
        b.title = b.getAttribute('aria-label');
      });
    }
  };

  /* ---------------------------------------------------------------- live announcer */
  var status;
  function announce(msg) {
    if (!status) { status = el('div', 'sr-only'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite'); doc.body.appendChild(status); }
    status.textContent = '';
    setTimeout(function () { status.textContent = msg; }, 30);
  }

  /* ---------------------------------------------------------------- overlays (modal + drawer) */
  var stack = []; // {ov, trigger, inerted}
  function resolve(t) { return typeof t === 'string' ? doc.getElementById(t) : t; }
  function panelOf(ov) { return $('.dialog, .drawer', ov) || ov; }
  function open(target, opts) {
    var ov = resolve(target);
    if (!ov || !ov.hidden && stack.some(function (s) { return s.ov === ov; })) return ov;
    opts = opts || {};
    var rec = { ov: ov, trigger: opts.trigger || doc.activeElement, inerted: [] };
    ov.hidden = false;
    var panel = panelOf(ov);
    panel.setAttribute('role', panel.getAttribute('role') || 'dialog');
    panel.setAttribute('aria-modal', 'true');
    if (!panel.hasAttribute('tabindex')) panel.setAttribute('tabindex', '-1');
    // make everything outside the overlay inert (also removes it from the a11y tree)
    var node = ov;
    while (node && node !== doc.body) {
      Array.prototype.forEach.call(node.parentNode.children, function (sib) {
        if (sib !== node && !sib.hasAttribute('inert') && !sib.classList.contains('toasts') && sib.tagName !== 'SCRIPT' && !sib.hasAttribute('role') === false ? false : (sib !== node && !sib.hasAttribute('inert') && !sib.classList.contains('toasts') && sib.tagName !== 'SCRIPT')) {
          sib.setAttribute('inert', ''); rec.inerted.push(sib);
        }
      });
      node = node.parentNode;
    }
    stack.push(rec);
    doc.body.classList.add('ui-locked');
    hideTip(true); closePopover();
    var f = $('[data-autofocus]', panel) || focusables(panel)[0] || panel;
    // focus after paint so the animation/hidden change has settled (WebKit needs this)
    setTimeout(function () { f.focus(); }, 0);
    doc.dispatchEvent(new CustomEvent('ui:open', { detail: ov }));
    return ov;
  }
  function close(target) {
    var ov = target ? resolve(target) : (stack.length ? stack[stack.length - 1].ov : null);
    if (!ov) return;
    if (ov.closest && !ov.classList.contains('overlay')) ov = ov.closest('.overlay') || ov;
    var i = stack.map(function (s) { return s.ov; }).indexOf(ov);
    if (i < 0) return;
    var rec = stack.splice(i, 1)[0];
    ov.hidden = true;
    rec.inerted.forEach(function (n) { n.removeAttribute('inert'); });
    if (!stack.length) doc.body.classList.remove('ui-locked');
    if (rec.trigger && doc.contains(rec.trigger) && rec.trigger.focus) rec.trigger.focus();
    doc.dispatchEvent(new CustomEvent('ui:close', { detail: ov }));
    if (ov.hasAttribute('data-ui-temp')) ov.remove();
  }
  /* confirm({title, message, confirmLabel, cancelLabel, danger}) -> Promise<boolean> */
  function confirmDialog(o) {
    o = o || {};
    return new Promise(function (res) {
      var ov = el('div', 'overlay'), tid = nid('dlg');
      ov.hidden = true; ov.setAttribute('data-ui-temp', '');
      var d = el('div', 'dialog'); d.setAttribute('role', 'alertdialog'); d.setAttribute('aria-labelledby', tid);
      var head = el('div', 'dialog-head'), h = el('h2', '', o.title || 'Are you sure?'); h.id = tid; head.appendChild(h);
      var body = el('div', 'dialog-body'); body.appendChild(el('p', '', o.message || ''));
      var foot = el('div', 'dialog-foot');
      var no = el('button', 'btn btn-secondary', o.cancelLabel || 'Cancel'); no.type = 'button'; no.setAttribute('data-autofocus', '');
      var yes = el('button', 'btn ' + (o.danger ? 'btn-danger' : 'btn-primary'), o.confirmLabel || 'Confirm'); yes.type = 'button';
      foot.appendChild(no); foot.appendChild(yes);
      d.appendChild(head); d.appendChild(body); d.appendChild(foot); ov.appendChild(d); doc.body.appendChild(ov);
      var done = false;
      function fin(v) { if (done) return; done = true; doc.removeEventListener('ui:close', onc); res(v); }
      function onc(e) { if (e.detail === ov) fin(false); }
      doc.addEventListener('ui:close', onc);
      no.addEventListener('click', function () { fin(false); close(ov); });
      yes.addEventListener('click', function () { fin(true); close(ov); });
      open(ov);
    });
  }

  /* ---------------------------------------------------------------- toasts */
  var toastBox;
  function toast(msg, o) {
    o = o || {};
    if (!toastBox) { toastBox = el('div', 'toasts'); toastBox.setAttribute('role', 'region'); toastBox.setAttribute('aria-label', 'Notifications'); toastBox.setAttribute('aria-live', 'polite'); doc.body.appendChild(toastBox); }
    var type = o.type || 'info';
    var t = el('div', 'toast toast-' + type);
    if (type === 'error') t.setAttribute('role', 'alert');
    t.appendChild(el('span', 'toast-msg', msg));
    if (o.action) { var a = el('button', 'btn btn-ghost btn-sm', o.action.label); a.type = 'button'; a.addEventListener('click', function () { o.action.onClick && o.action.onClick(); dismiss(); }); t.appendChild(a); }
    var x = el('button', 'btn btn-icon btn-sm', '×'); x.type = 'button'; x.setAttribute('aria-label', 'Dismiss notification'); x.addEventListener('click', dismiss); t.appendChild(x);
    toastBox.appendChild(t);
    var ms = o.timeout != null ? o.timeout : (type === 'error' ? 8000 : 5000), timer;
    function arm() { if (ms > 0) timer = setTimeout(dismiss, ms); }
    function dismiss() { clearTimeout(timer); if (t.parentNode) t.parentNode.removeChild(t); }
    t.addEventListener('mouseenter', function () { clearTimeout(timer); });
    t.addEventListener('mouseleave', arm);
    t.addEventListener('focusin', function () { clearTimeout(timer); });
    arm();
    return { dismiss: dismiss, el: t };
  }

  /* ---------------------------------------------------------------- tooltip + popover */
  var tipLayer, tipShown = null, tipTimer, lastPointer = 'mouse';
  function tipFor(trigger) {
    var id = trigger.getAttribute('data-tip-id');
    var tip = id && doc.getElementById(id);
    if (!tip) {
      if (!tipLayer) { tipLayer = el('div'); doc.body.appendChild(tipLayer); }
      id = nid('tip'); tip = el('div', 'tooltip'); tip.id = id; tip.setAttribute('role', 'tooltip'); tip.hidden = true;
      tip.addEventListener('mouseenter', function () { clearTimeout(tipTimer); });
      tip.addEventListener('mouseleave', function () { hideTip(); });
      tipLayer.appendChild(tip);
      trigger.setAttribute('data-tip-id', id);
      var d = (trigger.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean); d.push(id);
      trigger.setAttribute('aria-describedby', d.join(' '));
      if (!trigger.matches(FOCUSABLE)) trigger.setAttribute('tabindex', '0');
    }
    tip.textContent = trigger.getAttribute('data-tip') || '';
    return tip;
  }
  function place(node, trigger, pref) {
    node.style.left = '0px'; node.style.top = '0px'; node.hidden = false;
    var r = trigger.getBoundingClientRect(), w = node.offsetWidth, h = node.offsetHeight, vw = root.clientWidth, vh = root.clientHeight, m = 8;
    var top = (pref === 'bottom' || r.top - h - m < m) && r.bottom + h + m < vh ? r.bottom + m : r.top - h - m;
    if (top < m) top = m;
    var left = Math.min(Math.max(m, r.left + r.width / 2 - w / 2), vw - w - m);
    node.style.left = Math.round(left) + 'px'; node.style.top = Math.round(top) + 'px';
  }
  function showTip(trigger) {
    clearTimeout(tipTimer);
    if (!trigger.getAttribute('data-tip')) return;
    if (tipShown && tipShown !== trigger) hideTip(true);
    var tip = tipFor(trigger); place(tip, trigger); tipShown = trigger;
  }
  function hideTip(now) {
    clearTimeout(tipTimer);
    var go = function () { if (tipShown) { var t = doc.getElementById(tipShown.getAttribute('data-tip-id')); if (t) t.hidden = true; tipShown = null; } };
    if (now) go(); else tipTimer = setTimeout(go, 120);
  }
  var pop = null; // {trigger, node}
  function openPopover(trigger) {
    var node = doc.getElementById(trigger.getAttribute('data-popover'));
    if (!node) return;
    closePopover(); hideTip(true);
    node.classList.add('popover'); if (!node.hasAttribute('role')) node.setAttribute('role', 'group');
    place(node, trigger, 'bottom'); trigger.setAttribute('aria-expanded', 'true'); pop = { trigger: trigger, node: node };
  }
  function closePopover(returnFocus) {
    if (!pop) return;
    pop.node.hidden = true; pop.trigger.setAttribute('aria-expanded', 'false');
    if (returnFocus) pop.trigger.focus();
    pop = null;
  }

  /* ---------------------------------------------------------------- tabs */
  function selectTab(tab, focus) {
    var list = tab.closest('[role="tablist"]'); if (!list) return;
    $$('[role="tab"]', list).forEach(function (t) {
      var on = t === tab, p = doc.getElementById(t.getAttribute('aria-controls'));
      t.setAttribute('aria-selected', on ? 'true' : 'false'); t.tabIndex = on ? 0 : -1;
      if (p) p.hidden = !on;
    });
    if (focus) tab.focus();
    tab.dispatchEvent(new CustomEvent('ui:tab', { bubbles: true, detail: tab }));
  }
  function initTabs(r) {
    $$('[role="tablist"]', r).forEach(function (list) {
      if (list.getAttribute('data-ui-init')) return; list.setAttribute('data-ui-init', '1');
      var tabs = $$('[role="tab"]', list);
      selectTab(tabs.filter(function (t) { return t.getAttribute('aria-selected') === 'true'; })[0] || tabs[0]);
    });
  }

  /* ---------------------------------------------------------------- tag input */
  function tagInput(box, o) {
    if (box.uiTags) return box.uiTags;
    o = o || {};
    var input = $('input', box), values = [];
    function render() {
      $$('.chip', box).forEach(function (c) { c.remove(); });
      values.forEach(function (v, i) {
        var c = el('span', 'chip', v), x = el('button', 'chip-x', '×'); x.type = 'button'; x.setAttribute('aria-label', 'Remove ' + v);
        x.addEventListener('click', function (e) { e.stopPropagation(); values.splice(i, 1); render(); changed(); input.focus(); announce('Removed ' + v); });
        c.appendChild(x); box.insertBefore(c, input);
      });
    }
    function changed() { box.dispatchEvent(new CustomEvent('ui:tags-change', { bubbles: true, detail: values.slice() })); o.onChange && o.onChange(values.slice()); }
    function add(raw) {
      var any = false;
      String(raw).split(/[,\n]/).forEach(function (s) {
        s = s.trim();
        if (!s || (values.indexOf(s) >= 0 && !o.allowDuplicates)) return;
        if (o.validate && o.validate(s) === false) { box.setAttribute('aria-invalid', 'true'); return; }
        box.removeAttribute('aria-invalid'); values.push(s); any = true;
      });
      input.value = '';
      if (any) { render(); changed(); }
    }
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ',') { if (input.value.trim() || e.key === ',') { e.preventDefault(); add(input.value); } }
      else if (e.key === 'Backspace' && !input.value && values.length) { var v = values.pop(); render(); changed(); announce('Removed ' + v); }
    });
    input.addEventListener('blur', function () { if (input.value.trim()) add(input.value); });
    input.addEventListener('paste', function (e) { var t = (e.clipboardData || window.clipboardData).getData('text'); if (/[,\n]/.test(t)) { e.preventDefault(); add(t); } });
    box.addEventListener('click', function (e) { if (e.target === box) input.focus(); });
    var api = { get: function () { return values.slice(); }, set: function (v) { values = (v || []).map(String); render(); }, add: add };
    box.uiTags = api;
    api.set(o.values || (box.getAttribute('data-values') ? box.getAttribute('data-values').split(',').map(function (s) { return s.trim(); }).filter(Boolean) : []));
    return api;
  }

  /* ---------------------------------------------------------------- sortable table */
  function cellValue(tr, idx, type) {
    var c = tr.children[idx]; if (!c) return '';
    var v = c.getAttribute('data-value'); if (v == null) v = c.textContent.trim();
    if (type === 'num') { var n = parseFloat(String(v).replace(/[^0-9.\-]/g, '')); return isNaN(n) ? -Infinity : n; }
    return String(v).toLowerCase();
  }
  function sortBy(th, dir) {
    var table = th.closest('table'), tbody = table.tBodies[0]; if (!tbody) return;
    var idx = Array.prototype.indexOf.call(th.parentNode.children, th), type = th.getAttribute('data-sort');
    dir = dir || (th.getAttribute('aria-sort') === 'ascending' ? 'descending' : 'ascending');
    $$('th[aria-sort]', table).forEach(function (h) { h.setAttribute('aria-sort', 'none'); });
    th.setAttribute('aria-sort', dir);
    var rows = Array.prototype.slice.call(tbody.rows).map(function (r, i) { return { r: r, i: i, v: cellValue(r, idx, type) }; });
    rows.sort(function (a, b) { var c = a.v < b.v ? -1 : a.v > b.v ? 1 : 0; return (dir === 'ascending' ? c : -c) || a.i - b.i; });
    rows.forEach(function (x) { tbody.appendChild(x.r); });
    announce('Sorted by ' + th.textContent.trim() + ', ' + dir);
    table.dispatchEvent(new CustomEvent('ui:sort', { bubbles: true, detail: { th: th, dir: dir } }));
  }
  function initTables(r) {
    $$('th[data-sort]', r).forEach(function (th) {
      if ($('.th-sort', th)) return;
      var b = el('button', 'th-sort'); b.type = 'button';
      while (th.firstChild) b.appendChild(th.firstChild);
      th.appendChild(b); if (!th.hasAttribute('aria-sort')) th.setAttribute('aria-sort', 'none');
    });
  }

  /* ---------------------------------------------------------------- copy */
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    return new Promise(function (res, rej) {
      var ta = el('textarea'); ta.value = text; ta.setAttribute('readonly', ''); ta.style.cssText = 'position:fixed;left:-9999px;top:0';
      doc.body.appendChild(ta); ta.select();
      try { doc.execCommand('copy') ? res() : rej(new Error('copy failed')); } catch (e) { rej(e); } finally { ta.remove(); }
    });
  }
  function initCopy(r) {
    $$('.code[data-copyable]', r).forEach(function (c) {
      if ($('.code-copy', c)) return;
      var b = el('button', 'btn btn-secondary btn-sm code-copy'); b.type = 'button'; b.setAttribute('data-copy', '');
      b.innerHTML = '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 012-2h9"/></svg><span class="copy-label">Copy</span>';
      var lbl = c.getAttribute('data-copy-label'); b.setAttribute('aria-label', lbl ? 'Copy ' + lbl : 'Copy to clipboard');
      c.appendChild(b);
    });
  }
  function doCopy(btn) {
    var text = btn.getAttribute('data-copy');
    if (!text) { var tgt = btn.getAttribute('data-copy-target'); var src = tgt ? $(tgt) : (btn.closest('.code') && $('code, pre', btn.closest('.code'))); text = src ? src.textContent.replace(/\n$/, '') : ''; }
    var lab = $('.copy-label', btn) || btn;
    var was = btn.getAttribute('data-label') || lab.textContent;
    btn.setAttribute('data-label', was);
    function flash(msg, cls) { lab.textContent = msg; btn.classList.toggle('is-copied', cls); announce(msg === 'Copied' ? 'Copied to clipboard' : 'Could not copy'); clearTimeout(btn._t); btn._t = setTimeout(function () { lab.textContent = was; btn.classList.remove('is-copied'); }, 1800); }
    copyText(text).then(function () { flash('Copied', true); }, function () { flash('Press Ctrl+C', false); });
  }

  /* ---------------------------------------------------------------- init + delegation */
  function init(r) {
    r = r || doc;
    $$('[data-tip]', r).forEach(tipFor);
    initTabs(r); initTables(r); initCopy(r);
    $$('[data-tag-input]', r).forEach(function (b) { tagInput(b); });
    theme.sync();
  }

  doc.addEventListener('click', function (e) {
    var t = e.target;
    if (!t.closest) return;
    var b;
    if ((b = t.closest('[data-theme-toggle]'))) { theme.toggle(); return; }
    if ((b = t.closest('[data-open]'))) { e.preventDefault(); open(b.getAttribute('data-open'), { trigger: b }); return; }
    if ((b = t.closest('[data-close]'))) { close(b.closest('.overlay')); return; }
    if (t.classList.contains('overlay')) { close(t); return; }
    if ((b = t.closest('[data-copy]'))) { doCopy(b); return; }
    if ((b = t.closest('[role="tab"]'))) { selectTab(b); return; }
    if ((b = t.closest('th[data-sort]'))) { sortBy(b); return; }
    if ((b = t.closest('[data-dismiss]'))) { var tg = b.closest('.banner') || b.closest('[role]'); if (tg) tg.remove(); return; }
    if ((b = t.closest('[data-popover]'))) { if (pop && pop.trigger === b) closePopover(); else openPopover(b); return; }
    if ((b = t.closest('[data-tip]'))) {
      if (lastPointer === 'touch') { if (tipShown === b) hideTip(true); else showTip(b); } else showTip(b);
      return;
    }
    if (pop && !pop.node.contains(t)) closePopover();
    if (tipShown && !t.closest('.tooltip')) hideTip(true);
  });
  doc.addEventListener('pointerdown', function (e) { lastPointer = e.pointerType || 'mouse'; }, true);
  doc.addEventListener('mouseover', function (e) { var b = e.target.closest && e.target.closest('[data-tip]'); if (b && lastPointer !== 'touch') showTip(b); });
  doc.addEventListener('mouseout', function (e) { var b = e.target.closest && e.target.closest('[data-tip]'); if (b && lastPointer !== 'touch' && !(doc.activeElement === b)) hideTip(); });
  doc.addEventListener('focusin', function (e) {
    var b = e.target.closest && e.target.closest('[data-tip]'); if (b) showTip(b);
    if (pop && !pop.node.contains(e.target) && e.target !== pop.trigger) closePopover();
  });
  doc.addEventListener('focusout', function (e) { var b = e.target.closest && e.target.closest('[data-tip]'); if (b) hideTip(true); });
  doc.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      if (tipShown) { hideTip(true); e.stopPropagation(); return; }
      if (pop) { closePopover(true); e.stopPropagation(); return; }
      if (stack.length) { e.preventDefault(); close(); return; }
    }
    if (e.key === 'Tab' && stack.length) {
      var panel = panelOf(stack[stack.length - 1].ov), f = focusables(panel);
      if (!f.length) { e.preventDefault(); panel.focus(); return; }
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && (doc.activeElement === first || doc.activeElement === panel)) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && doc.activeElement === last) { e.preventDefault(); first.focus(); }
    }
    var tab = e.target.closest && e.target.closest('[role="tab"]');
    if (tab && /^(ArrowLeft|ArrowRight|Home|End)$/.test(e.key)) {
      var tabs = $$('[role="tab"]', tab.closest('[role="tablist"]')), i = tabs.indexOf(tab);
      i = e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : (i + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      e.preventDefault(); selectTab(tabs[i], true);
    }
  });
  window.addEventListener('scroll', function () { if (tipShown) hideTip(true); if (pop) closePopover(); }, true);
  window.addEventListener('resize', function () { hideTip(true); closePopover(); });
  if (window.matchMedia) { try { matchMedia('(prefers-color-scheme: light)').addEventListener('change', theme.sync); } catch (e) { /* old Safari */ } }

  window.SpotiUI = { theme: theme, open: open, close: close, confirm: confirmDialog, toast: toast, announce: announce, init: init, tagInput: tagInput,
    sortBy: sortBy, selectTab: selectTab, copy: copyText, showTip: showTip, hideTip: function () { hideTip(true); }, openPopover: openPopover, closePopover: closePopover };
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', function () { init(); }); else init();
})();
