/* Dashboard views. Each view answers one question. All data is escaped before it reaches the DOM. */
(function () {
  'use strict';
  var D = window.DashData;

  // ------------------------------------------------------------------ helpers
  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function fmtVal(v) {
    if (v === null || v === undefined) return '(none)';
    if (Array.isArray(v)) return v.length ? v.join(', ') : '(empty)';
    if (typeof v === 'boolean') return v ? 'yes' : 'no';
    if (typeof v === 'object') return JSON.stringify(v);
    return String(v);
  }
  function pct(v, digits) { return v == null ? 'n/a' : (v * 100).toFixed(digits == null ? 1 : digits) + '%'; }
  function num(v) { return v == null ? '—' : String(v); }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }

  var ICON = { ok: '✓', warn: '▲', bad: '✕', info: '●', neutral: '–' };
  function badge(kind, text, extra) {
    return '<span class="badge badge-' + kind + '"' + (extra || '') + '><span aria-hidden="true">' + ICON[kind] + '</span> ' + esc(text) + '</span>';
  }
  var DECISIONS = {
    will_move: ['ok', 'Will move'], too_young: ['info', 'Too young'], no_match: ['neutral', 'No match'],
    target_problem: ['bad', 'Target problem'], blocked: ['warn', 'Blocked']
  };
  var DECISION_ORDER = ['will_move', 'too_young', 'blocked', 'target_problem', 'no_match'];
  function decisionBadge(d) { var m = DECISIONS[d] || ['neutral', d]; return badge(m[0], m[1]); }
  var RULE_STATUS = { ok: ['ok', 'Active'], dead: ['bad', 'Dead'], shadowed: ['warn', 'Shadowed'], disabled: ['neutral', 'Disabled'] };
  function ruleStatusBadge(s) { var m = RULE_STATUS[s] || ['neutral', s]; return badge(m[0], m[1]); }
  var VERDICTS = { ok: ['ok', 'OK'], dry_run: ['info', 'Dry run'], mismatch: ['bad', 'Mismatch'], error: ['bad', 'Error'] };
  function verdictBadge(v) { var m = VERDICTS[v] || ['neutral', v]; return badge(m[0], m[1]); }
  var TARGET = { resolved: ['ok', 'Found'], missing: ['bad', 'Missing'], not_writable: ['bad', 'Not writable'], ambiguous: ['warn', 'Ambiguous'] };
  function targetBadge(s) { var m = TARGET[s] || ['neutral', s || 'unknown']; return badge(m[0], m[1]); }
  var TIERS = { playlist: ['ok', 'Playlist'], script: ['ok', 'Script'], hint: ['warn', 'Hint'], country_default: ['warn', 'Country default'] };
  function tierBadge(s) { if (!s) return ''; var m = TIERS[s] || ['neutral', s]; return badge(m[0], m[1]); }
  function posText(p) { return p === 'top' ? 'top of playlist' : 'bottom of playlist'; }
  // decision 31/32: whenever a plan/log has titles_hidden, a public Repo-mode log has song titles/artists
  // redacted (logging.include_track_names: false). Show a plain explanation instead of blank/null text.
  var TITLE_HIDDEN_MSG = 'Title hidden — open local files to see titles';
  function titleOrHidden(name, hidden) {
    return hidden ? '<span class="muted" data-testid="title-hidden">' + esc(TITLE_HIDDEN_MSG) + '</span>' : esc(name);
  }

  function ok(f) { return f && f.status === 'ok'; }
  function plan(ctx) { return ok(ctx.files.plan) ? ctx.files.plan.data : null; }
  function runsOf(ctx) { return ok(ctx.files.runs) ? (ctx.files.runs.data.runs || []) : []; }

  function emptyState(key, files) {
    var cmd = D.COMMANDS[key];
    var file = D.FILES[key];
    return '<section class="empty" data-empty="' + key + '"><h3>No ' + esc(D.LABELS[key].toLowerCase()) + ' yet</h3>' +
      '<p><code>' + esc(file) + '</code> was not found in this data source.</p>' +
      '<p>Create it by running <code class="cmd">' + esc(cmd) + '</code>, then choose <strong>Reload data</strong>.</p></section>';
  }
  function errorState(key, message) {
    return '<section class="errorbox" role="alert" data-error="' + key + '"><h3>Could not load ' + esc(D.LABELS[key].toLowerCase()) + '</h3>' +
      '<p>' + esc(message || 'Unknown error') + '</p>' +
      '<button type="button" class="btn secondary small" data-action="reload">Try again</button></section>';
  }
  /** Problem cards for every listed file that is missing or broken; '' when all are fine. */
  function problems(ctx, keys) {
    var out = '';
    keys.forEach(function (k) {
      var f = ctx.files[k];
      if (f.status === 'missing') out += emptyState(k);
      else if (f.status === 'error') out += errorState(k, f.message);
    });
    return out;
  }

  function banner(kind, icon, html, attrs) {
    return '<div class="banner banner-' + kind + '" ' + (attrs || '') + '><span class="ico" aria-hidden="true">' + icon + '</span><div>' + html + '</div></div>';
  }

  // ------------------------------------------------------------------ plain-language "what does this mean?" per view
  var VIEW_EXPLAIN = {
    overview: 'A health check for the whole sorter: is it running, is anything waiting, and did the last run go cleanly.',
    inbox: 'Every song currently in Liked Songs, and what SpotiSort has decided (or will decide) to do with each one, and why.',
    rules: 'Your rules, in the order they run. The first rule a song matches wins; later rules never see it. A rule can be "shadowed" (an earlier rule always takes its songs first) or "dead" (nothing matches it).',
    playlists: 'Every playlist a rule sends songs to, whether SpotiSort can actually write to it, and how many songs are queued for it.',
    runs: 'The history of every time the sorter has run, dry or real, with a detailed breakdown of each one.',
    safety: 'Whether any song has ever been at risk, and the exact command to bring one back if something needs undoing.',
    signals: 'How SpotiSort works out a song’s language, and how much each method (playlist, script, hint, country) can be trusted before it is allowed to drive a decision.',
    backtest: 'A dry run of your rules against playlists you already sorted by hand, to see how often they would have gotten it right.'
  };
  function helpBtn(text) {
    return '<button type="button" class="help-btn" data-tip="' + esc(text) + '" aria-label="What does this mean?">?</button>';
  }

  function viewHead(ctx, view, key) {
    var out = '<div class="view-head"><h2 id="view-title" tabindex="-1">' + esc(view.label) + '</h2><p class="question">' + esc(view.question) + ' ' + helpBtn(VIEW_EXPLAIN[key] || view.question) + '</p>';
    var stamps = [], stale = [];
    view.files.forEach(function (k) {
      var iso = D.stampOf(ctx.files[k]);
      if (!iso) return;
      stamps.push('<span data-stamp="' + k + '"><span class="lbl">' + esc(D.LABELS[k]) + ':</span> <time datetime="' + esc(iso) + '">' + esc(D.fmtTime(iso)) + '</time> (' + esc(D.rel(iso)) + ')</span>');
      if (D.isStale(iso)) stale.push(D.LABELS[k] + ' (' + D.fmtTime(iso) + ')');
    });
    out += '<p class="stamp" data-testid="freshness">' + (stamps.length ? '<span class="lbl">Data freshness</span>' + stamps.join('') : '<span class="lbl">Data freshness: no data loaded from this source</span>') + '</p>';
    if (stale.length) {
      out += banner('warn', '▲', '<p><strong>This data is more than 2 days old.</strong> ' + esc(stale.join('; ')) +
        '. The sorter may have stopped running. Check your GitHub Actions runs, or run <code>python -m src.sync</code> again.</p>', 'role="status" data-banner="stale"');
    }
    var p = plan(ctx);
    if (p && p.inbox_kind === 'legacy_library') {
      out += banner('info', '●', '<p><strong>This is the old archive, not a live inbox.</strong> These are the songs already in your Liked Songs. SpotiSort is meant to run on a fresh, nearly empty Liked Songs list, so treat this as a preview of how your rules behave, not a to-do list.</p>', 'role="status" data-banner="legacy"');
    }
    if (p && p.what_if) {
      out += banner('warn', '▲', '<p><strong>What-if preview.</strong> Disabled rules were treated as enabled. This is not what a normal run would do.</p>', 'role="status" data-banner="what-if"');
    }
    return out + '</div>';
  }

  function card(label, value, sub, extra) {
    return '<div class="card"' + (extra || '') + '><p class="metric-label">' + esc(label) + '</p><p class="metric-value">' + value + '</p>' + (sub ? '<p class="metric-sub">' + sub + '</p>' : '') + '</div>';
  }

  function tableWrap(html, cards) { return '<div class="table-wrap' + (cards ? ' cards' : '') + '">' + html + '</div>'; }

  function pctCell(v, cls) {
    if (v == null) return '<span class="muted">n/a</span>';
    var w = Math.max(0, Math.min(100, v * 100));
    return '<div class="pct-cell"><div class="bar ' + (cls || '') + '" role="img" aria-label="' + w.toFixed(1) + ' percent"><span style="--w:' + w.toFixed(1) + '%"></span></div><span class="val">' + w.toFixed(1) + '%</span></div>';
  }

  // ------------------------------------------------------------------ explain drawer content
  var TRACE_RESULT = {
    matched: ['ok', 'Matched: this rule decided the song'],
    matched_too_young: ['info', 'Matched, but the song is too young: evaluation stops here'],
    failed: ['neutral', 'Did not match'],
    not_reached: ['neutral', 'Not reached: an earlier rule already decided'],
    not_reached_but_would_match: ['warn', 'Would match, but never reached (an earlier rule wins)'],
    skipped_disabled: ['neutral', 'Skipped: rule is disabled'],
    skipped_empty: ['neutral', 'Skipped: rule has no conditions']
  };

  var TIER_PLAIN = { playlist: 'learned from your own playlists', script: "the title's script", hint: 'a weaker hint', country_default: "a country default" };
  function confWord(c) { return c == null ? '' : (c >= 0.85 ? 'high confidence' : (c >= 0.6 ? 'medium confidence' : 'low confidence')); }
  // decision 34: the Explain drawer opens with a sentence-first plain narrative, built from the same trace data
  // as the technical accordion below it, before any internal identifiers or rule-by-rule detail.
  function narrativeSentence(song) {
    var lang = song.language || {};
    var base;
    if (song.decision === 'will_move') {
      base = 'Matched ' + (song.rule ? '“' + esc(song.rule) + '”' : 'a rule') + (song.target_playlist ? ' → ' + esc(song.target_playlist) : '') +
        '. It is old enough now, so the next run will move it' + (song.target_playlist ? ' into ' + esc(song.target_playlist) : '') + '.';
    } else if (song.decision === 'too_young') {
      base = (song.rule ? '“' + esc(song.rule) + '” matched' : 'A rule matched') + ', but the song is too new' +
        (song.eligible_on ? ' — it becomes eligible on ' + esc(D.fmtDate(song.eligible_on)) : '') + '.';
    } else if (song.decision === 'target_problem') {
      base = 'A rule matched and wanted to send this to “' + esc(song.target_playlist || '') + '”, but that playlist is ' +
        esc((song.target_status || 'unavailable').replace(/_/g, ' ')) + '.';
    } else if (song.decision === 'blocked') {
      base = 'A rule would otherwise match on ' + esc(lang.value || 'a language') + ', but that signal is not trusted enough yet to act on — it is only shown, not used.';
    } else {
      base = 'No enabled rule matched this song.';
    }
    if (lang.value && song.decision !== 'blocked') {
      base += ' The language is ' + esc(lang.value) + ' (' + esc(TIER_PLAIN[lang.source] || lang.source || 'an unknown signal') + (lang.confidence != null ? ', ' + confWord(lang.confidence) : '') + ').';
    }
    var trace = (song.explain && song.explain.trace) || [];
    var shadow = trace.filter(function (e) { return e.result === 'not_reached_but_would_match'; }).map(function (e) { return e.rule; });
    var tooYoungEarlier = trace.filter(function (e) { return e.result === 'matched_too_young' && e.rule !== song.rule; }).map(function (e) { return e.rule; });
    if (shadow.length) base += ' It would also match ' + shadow.map(esc).join(', ') + ', but ' + (shadow.length > 1 ? 'those rules run' : 'that rule runs') + ' later and never get' + (shadow.length > 1 ? '' : 's') + ' the chance.';
    if (tooYoungEarlier.length) base += ' It was too new for ' + tooYoungEarlier.map(esc).join(', ') + '.';
    return base;
  }

  function explainHtml(song, p) {
    var out = '';
    var lang = song.language || {};
    out += '<h3>What happened</h3><p class="callout" data-testid="explain-narrative">' + narrativeSentence(song) + '</p>';
    out += '<h3>Decision</h3><p>' + decisionBadge(song.decision) + '</p><p>' + esc(song.reason) + '</p>';
    var bits = [];
    if (song.rule) bits.push('Rule: <strong>' + esc(song.rule) + '</strong>');
    if (song.target_playlist) bits.push('Target: <strong>' + esc(song.target_playlist) + '</strong> (' + esc(posText(song.target_position)) + ')');
    if (song.age_days != null) bits.push('Age: ' + esc(song.age_days) + ' days');
    if (song.eligible_on) bits.push('Eligible on: ' + esc(D.fmtDate(song.eligible_on)));
    if (bits.length) out += '<p class="small muted">' + bits.join(' &middot; ') + '</p>';

    out += '<details data-testid="technical-trace"><summary>Technical details: rule-by-rule trace</summary>';
    var tr = (song.explain && song.explain.trace) || [];
    if (song.explain && song.explain.decided_by) out += '<p class="small">Decided by <strong>' + esc(song.explain.decided_by) + '</strong>. Rules run top to bottom and the first match wins.</p>';
    else out += '<p class="small">No rule decided this song. Rules run top to bottom and the first match wins.</p>';
    out += '<ol class="trace" data-testid="trace">';
    tr.forEach(function (e) {
      var m = TRACE_RESULT[e.result] || ['neutral', e.result];
      out += '<li class="t-' + esc(e.result) + '" data-rule="' + esc(e.rule) + '" data-result="' + esc(e.result) + '"><div class="t-head"><span class="t-name">' + esc(e.rule) + '</span>' + badge(m[0], m[1]) + '</div>';
      out += '<p class="small muted" style="margin:4px 0 0">Waits ' + esc(e.threshold_days) + ' days' + (e.enabled ? '' : ' &middot; disabled') + '</p>';
      if (e.conditions && e.conditions.length) {
        out += '<ul>';
        e.conditions.forEach(function (c) {
          out += '<li data-passed="' + (c.passed ? 'true' : 'false') + '"><span class="' + (c.passed ? 'ct-ok' : 'ct-no') + '">' + (c.passed ? '✓ passed' : '✕ failed') + '</span><span><code>' + esc(c.key) + '</code> wants ' + esc(fmtVal(c.wanted)) + '; song has ' + esc(fmtVal(c.actual)) + '</span></li>';
        });
        out += '</ul>';
      }
      out += '</li>';
    });
    out += '</ol></details>';

    out += '<h3>Signals</h3><h4 class="small">Language</h4>';
    if (lang.value) {
      var c = lang.confidence;
      out += '<p data-testid="lang-signal"><strong>' + esc(lang.value) + '</strong> ' + tierBadge(lang.source) + ' ' +
        (lang.used_for_rules ? badge('ok', 'Used for rules') : badge('warn', 'Not used for rules')) + '</p>';
      if (c != null) out += '<div class="conf"><span class="small muted">Confidence</span><div class="bar" role="img" aria-label="Confidence ' + Math.round(c * 100) + ' percent"><span style="--w:' + Math.round(c * 100) + '%"></span></div><span class="small">' + Math.round(c * 100) + '%</span></div>';
    } else {
      out += '<p>No language could be determined.</p>';
    }
    if (lang.withheld) {
      var w = lang.withheld;
      out += '<div class="banner banner-warn" data-testid="withheld"><span class="ico" aria-hidden="true">▲</span><div><p><strong>Withheld from rules:</strong> ' + esc(w.language) + ' from the ' + esc(w.source) + ' signal. ' +
        (w.reason === 'unmeasured' ? 'This signal has not been measured for this language yet.' : 'Its measured precision is ' + esc(pct(w.precision)) + ', below the 90% bar.') +
        ' Samples: ' + esc(w.samples) + '. Run <code>python -m src.backtest</code> to measure it.</p></div></div>';
    }
    var g = song.genres || {};
    out += '<h4 class="small">Genres</h4>';
    if (g.values && g.values.length) {
      out += '<ul class="chips">' + g.values.map(function (x) { return '<li class="chip">' + esc(x) + '</li>'; }).join('') + '</ul>';
      out += '<p class="small muted" style="margin-top:8px">Source: ' + esc(g.source || 'unknown') + (g.confidence != null ? ' &middot; confidence ' + Math.round(g.confidence * 100) + '%' : '') + '</p>';
    } else {
      out += '<p>No genres known for this artist.</p>';
    }
    return out;
  }

  // ------------------------------------------------------------------ views
  var V = {};

  // ---- Overview
  V.overview = {
    label: 'Overview', question: 'Is it healthy?', files: ['plan', 'runs'],
    render: function (ctx) {
      var p = plan(ctx), runs = runsOf(ctx), now = D.now();
      // decision 34: a brand-new fork with zero runs gets a short guided tour instead of two separate
      // "file not found" empty states, so the very first thing a new user sees is what to do next.
      if (ctx.files.plan.status === 'missing' && ctx.files.runs.status === 'missing' && ctx.source !== 'files') {
        return '<section class="empty" data-empty="first-run" data-testid="first-run-tour"><h3>Nothing here yet — let’s get your first data</h3>' +
          '<p>This fork has not produced any run data yet. Three steps get you your first Overview:</p>' +
          '<ol><li><strong>Configure</strong> — open <a href="../builder/">Configure</a> and set up your rules for at least one language or playlist.</li>' +
          '<li><strong>Save configuration</strong> — on the Review step, save it, then commit the downloaded <code>config.yaml</code> to your fork’s repository root.</li>' +
          '<li><strong>Run the Sync workflow</strong> — in your fork on GitHub, open the <strong>Actions</strong> tab, choose <strong>Sync</strong>, and run it once (leave “Dry run” ticked). It will commit <code>logs/</code> files back to your repo.</li></ol>' +
          '<p>Once that run finishes, reload this page (or wait for GitHub Pages to redeploy) and this Overview will show your real data.</p></section>';
      }
      var html = problems(ctx, ['plan', 'runs']);
      var last = runs[0];
      var weekAgo = now - 7 * 86400000;
      var week = runs.filter(function (r) { return Date.parse(r.time) >= weekAgo; });
      var movesWeek = week.filter(function (r) { return r.mode === 'apply'; }).reduce(function (a, r) { return a + (r.moved || 0); }, 0);
      var errWeek = week.reduce(function (a, r) { return a + (r.errors || 0); }, 0);
      var warnWeek = week.reduce(function (a, r) { return a + (r.warnings || 0); }, 0);
      var lastApply = runs.filter(function (r) { return r.mode === 'apply'; })[0];
      var mismatches = runs.filter(function (r) { return r.verdict === 'mismatch'; }).length;

      var health;
      if (!last) health = badge('neutral', 'No runs yet');
      else if (last.verdict === 'error' || last.verdict === 'mismatch') health = badge('bad', 'Needs attention');
      else if (last.errors || last.warnings || mismatches) health = badge('warn', 'Healthy, with warnings');
      else health = badge('ok', 'Healthy');
      html += '<p class="callout" data-testid="health"><strong>Overall:</strong> ' + health + '</p>';

      html += '<div class="grid">';
      if (last) {
        html += card('Last run', verdictBadge(last.verdict), esc(last.mode === 'apply' ? 'Apply run' : 'Dry run') + (last.what_if ? ' (what-if)' : '') + ' &middot; <time datetime="' + esc(last.time) + '">' + esc(D.fmtTime(last.time)) + '</time> (' + esc(D.rel(last.time)) + ') &middot; ' + esc(last.duration_seconds) + ' s', ' data-card="last-run"');
      } else {
        html += card('Last run', '<span class="muted">None</span>', 'No run has been recorded.', ' data-card="last-run"');
      }
      var sched = ok(ctx.files.runs) && ctx.files.runs.data.schedule || (p && p.schedule);
      var schedText = 'Not scheduled';
      if (typeof sched === 'string' && sched) schedText = sched;
      else if (sched && typeof sched === 'object') schedText = sched.next_run ? D.fmtTime(sched.next_run) : (sched.description || sched.cron || schedText);
      html += card('Next scheduled run', esc(schedText), sched ? '' : 'Runs only happen when you start them.', ' data-card="next-run"');
      // decision 34: KPI cards show a delta vs. the previous run, where one is meaningful (needs 2+ runs).
      function delta(cur, prev, goodDown) {
        if (prev == null || cur == null) return '';
        var d = cur - prev;
        if (d === 0) return ' &middot; no change since the previous run';
        var good = goodDown ? d < 0 : d > 0;
        return ' &middot; <span class="' + (good ? 'delta-up' : 'delta-down') + '">' + (d > 0 ? '+' : '') + d + ' since the previous run</span>';
      }
      var prevRun = runs[1];
      html += card('Liked songs', p ? esc(p.liked_total) : '—', (p ? 'Currently in the inbox' : '') + (prevRun ? delta(last.liked_after, prevRun.liked_after) : ''), ' data-card="liked"');
      html += card('Pending', p ? esc(p.counts.will_move + p.counts.too_young) : '—', p ? esc(p.counts.will_move) + ' ready to move, ' + esc(p.counts.too_young) + ' too young' : '', ' data-card="pending"');
      html += card('Moves this week', last ? esc(movesWeek) : '—', 'Songs actually moved by apply runs in the last 7 days' + (prevRun ? delta(last.moved, prevRun.moved) : ''), ' data-card="moves"');
      html += card('Errors and warnings', last ? esc(last.errors) + ' / ' + esc(last.warnings) : '—', 'Last run. Past 7 days: ' + esc(errWeek) + ' errors, ' + esc(warnWeek) + ' warnings' + (prevRun ? delta(last.errors + last.warnings, prevRun.errors + prevRun.warnings, true) : ''), ' data-card="errors"');
      var safety;
      if (lastApply) {
        safety = lastApply.verdict === 'ok' ? badge('ok', 'Reconcile OK') : (lastApply.verdict === 'mismatch' ? badge('bad', 'Mismatch') : verdictBadge(lastApply.verdict));
      } else safety = badge('info', 'No apply run yet');
      var safetySub = lastApply ? 'Last apply run ' + esc(D.fmtDate(lastApply.time)) + (mismatches ? ' &middot; ' + esc(plural(mismatches, 'mismatch', 'mismatches')) + ' in history' : '') : 'Everything so far is a dry run; nothing was removed from Liked Songs.';
      html += card('Safety verdict', safety, safetySub + ' <a href="#/safety">Open Safety</a>', ' data-card="safety"');
      html += '</div>';

      if (p) {
        var c = p.counts, targets = {};
        p.songs.forEach(function (s) { if (s.decision === 'will_move') targets[s.target_playlist] = 1; });
        var n = Object.keys(targets).length;
        var next = c.will_move
          ? 'The next run would move ' + plural(c.will_move, 'song') + ' into ' + plural(n, 'playlist') + '. ' + plural(c.too_young, 'song') + ' still too young, ' + c.blocked + ' blocked, ' + c.target_problem + ' with a target problem, ' + c.no_match + ' matching nothing.'
          : 'The next run would move nothing. ' + plural(c.too_young, 'song') + ' still too young, ' + c.blocked + ' blocked, ' + c.target_problem + ' with a target problem, ' + c.no_match + ' matching nothing.';
        if (p.mode !== 'apply') next += ' This snapshot is a dry run: nothing has been written to Spotify.';
        if (p.what_if) next += ' (What-if: disabled rules counted as enabled.)';
        html += '<p class="callout" data-testid="next">' + '<strong>What will happen next:</strong> ' + esc(next) + '</p>';
        html += '<h3 class="small" style="margin:0 0 8px">Inbox by decision</h3><ul class="chips" data-testid="decision-counts">' +
          DECISION_ORDER.map(function (d) { return '<li>' + '<a class="badge badge-' + DECISIONS[d][0] + '" href="#/inbox?decision=' + d + '" style="text-decoration:none">' + esc(DECISIONS[d][1]) + ': ' + c[d] + '</a></li>'; }).join('') + '</ul>';
      }
      return html;
    }
  };

  // ---- Inbox
  V.inbox = {
    label: 'Inbox', question: 'What is waiting, and why?', files: ['plan'],
    render: function (ctx) {
      var bad = problems(ctx, ['plan']);
      if (bad) return bad;
      var p = plan(ctx);
      var st = ctx.state.inbox = ctx.state.inbox || { q: '', decision: '', rule: '', sort: 'age', dir: 'desc', shown: 100 };
      var q = ctx.query;
      if (q.has('decision')) st.decision = q.get('decision');
      if (q.has('rule')) st.rule = q.get('rule');
      if (q.has('q')) st.q = q.get('q');
      var rules = p.rules.map(function (r) { return r.name; });
      var opts = '<option value="">All decisions</option>' + DECISION_ORDER.map(function (d) {
        return '<option value="' + d + '"' + (st.decision === d ? ' selected' : '') + '>' + esc(DECISIONS[d][1]) + ' (' + p.counts[d] + ')</option>';
      }).join('');
      var ropts = '<option value="">All rules</option>' + rules.map(function (r) { return '<option value="' + esc(r) + '"' + (st.rule === r ? ' selected' : '') + '>' + esc(r) + '</option>'; }).join('');
      return '<div class="toolbar" role="search">' +
        '<div class="field grow"><label for="inbox-q">Search title, artist, rule, playlist</label><input id="inbox-q" type="search" value="' + esc(st.q) + '" autocomplete="off" /></div>' +
        '<div class="field"><label for="inbox-decision">Decision</label><select id="inbox-decision">' + opts + '</select></div>' +
        '<div class="field"><label for="inbox-rule">Rule</label><select id="inbox-rule">' + ropts + '</select></div>' +
        '<button type="button" class="btn secondary small" id="inbox-csv" data-testid="inbox-csv">Export CSV</button></div>' +
        '<div id="inbox-results"></div>';
    },
    bind: function (root, ctx) {
      var p = plan(ctx);
      if (!p) return;
      var st = ctx.state.inbox;
      var COLS = [
        ['title', 'Song'], ['age', 'Age (days)', 'num'], ['decision', 'Decision'], ['rule', 'Rule'],
        ['target', 'Target playlist'], ['eligible', 'Eligible on'], ['language', 'Language']
      ];
      function keyOf(s, k) {
        switch (k) {
          case 'title': return (s.title || '').toLowerCase();
          case 'age': return s.age_days == null ? null : s.age_days;
          case 'decision': return DECISION_ORDER.indexOf(s.decision);
          case 'rule': return (s.rule || '').toLowerCase() || null;
          case 'target': return (s.target_playlist || '').toLowerCase() || null;
          case 'eligible': return s.eligible_on || null;
          case 'language': return ((s.language && s.language.value) || '').toLowerCase() || null;
        }
      }
      function paint() {
        var term = st.q.trim().toLowerCase();
        var rows = [];
        p.songs.forEach(function (s, i) {
          if (st.decision && s.decision !== st.decision) return;
          if (st.rule && s.rule !== st.rule) return;
          if (term) {
            var hay = [s.title, (s.artists || []).join(' '), s.rule, s.target_playlist, s.language && s.language.value].join(' ').toLowerCase();
            if (hay.indexOf(term) < 0) return;
          }
          rows.push({ s: s, i: i });
        });
        rows.sort(function (a, b) {
          var x = keyOf(a.s, st.sort), y = keyOf(b.s, st.sort);
          if (x === y) return a.i - b.i;
          if (x === null) return 1;
          if (y === null) return -1;
          return (x < y ? -1 : 1) * (st.dir === 'asc' ? 1 : -1);
        });
        var shown = rows.slice(0, st.shown);
        var h = '<p class="result-count" role="status" data-testid="result-count">Showing ' + shown.length + ' of ' + rows.length + ' songs' + (rows.length !== p.songs.length ? ' (filtered from ' + p.songs.length + ')' : '') + '</p>';
        if (!rows.length) {
          h += '<div class="empty"><h3>No songs match</h3><p>Try clearing the search or filters.</p></div>';
        } else {
          h += '<div class="table-wrap cards"><table class="stack" data-testid="inbox-table"><thead><tr>';
          COLS.forEach(function (c) {
            var active = st.sort === c[0];
            h += '<th scope="col" class="' + (c[2] || '') + '" aria-sort="' + (active ? (st.dir === 'asc' ? 'ascending' : 'descending') : 'none') + '"><button type="button" class="sort-btn" data-sort="' + c[0] + '">' + esc(c[1]) + '<span aria-hidden="true">' + (active ? (st.dir === 'asc' ? '▲' : '▼') : '') + '</span></button></th>';
          });
          h += '</tr></thead><tbody>';
          var hidden = !!p.titles_hidden;
          shown.forEach(function (r) {
            var s = r.s, l = s.language || {};
            h += '<tr data-decision="' + esc(s.decision) + '"><td class="cell-main"><button type="button" class="link-btn" data-explain="' + r.i + '" aria-haspopup="dialog">' + titleOrHidden(s.title, hidden) + '</button><div class="small muted">' + (hidden ? '' : esc((s.artists || []).join(', '))) + '</div></td>' +
              '<td class="num" data-label="Age (days)">' + esc(num(s.age_days)) + '</td>' +
              '<td data-label="Decision">' + decisionBadge(s.decision) + '</td>' +
              '<td data-label="Rule">' + (s.rule ? esc(s.rule) : '<span class="muted">—</span>') + '</td>' +
              '<td data-label="Target">' + (s.target_playlist ? esc(s.target_playlist) + '<div class="small muted">' + esc(posText(s.target_position)) + (s.target_status && s.target_status !== 'resolved' ? ' &middot; ' + esc(s.target_status.replace('_', ' ')) : '') + '</div>' : '<span class="muted">—</span>') + '</td>' +
              '<td data-label="Eligible on">' + (s.decision === 'will_move' ? 'Ready now' : (s.eligible_on ? esc(D.fmtDate(s.eligible_on)) : '<span class="muted">—</span>')) + '</td>' +
              '<td data-label="Language">' + (l.value ? esc(l.value) + ' ' + tierBadge(l.source) : '<span class="muted">unknown</span>') + (l.withheld ? ' ' + badge('warn', 'Withheld') : '') + '</td></tr>';
          });
          h += '</tbody></table></div>';
          if (rows.length > shown.length) h += '<p><button type="button" class="btn secondary" data-more="1">Show ' + Math.min(100, rows.length - shown.length) + ' more</button></p>';
        }
        root.querySelector('#inbox-results').innerHTML = h;
        lastRows = rows;
      }
      var lastRows = [];
      function csvCell(v) { return '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"'; }
      function exportCsv() {
        var hidden = !!p.titles_hidden;
        var head = ['Song', 'Artists', 'Age (days)', 'Decision', 'Rule', 'Target playlist', 'Eligible on', 'Language'];
        var lines = [head.map(csvCell).join(',')];
        lastRows.forEach(function (r) {
          var s = r.s;
          lines.push([
            hidden ? TITLE_HIDDEN_MSG : (s.title || ''),
            hidden ? '' : (s.artists || []).join('; '),
            s.age_days == null ? '' : s.age_days,
            (DECISIONS[s.decision] || [null, s.decision])[1],
            s.rule || '', s.target_playlist || '',
            s.decision === 'will_move' ? 'Ready now' : (s.eligible_on || ''),
            (s.language && s.language.value) || ''
          ].map(csvCell).join(','));
        });
        var blob = new Blob([lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url; a.download = 'spotisort-inbox.csv';
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
      }
      paint();
      root.querySelector('#inbox-q').addEventListener('input', function (e) { st.q = e.target.value; st.shown = 100; paint(); });
      root.querySelector('#inbox-decision').addEventListener('change', function (e) { st.decision = e.target.value; st.shown = 100; paint(); });
      root.querySelector('#inbox-rule').addEventListener('change', function (e) { st.rule = e.target.value; st.shown = 100; paint(); });
      var csvBtn = root.querySelector('#inbox-csv');
      if (csvBtn) csvBtn.addEventListener('click', exportCsv);
      root.querySelector('#inbox-results').addEventListener('click', function (e) {
        var b = e.target.closest('[data-sort]');
        if (b) {
          var k = b.getAttribute('data-sort');
          if (st.sort === k) st.dir = st.dir === 'asc' ? 'desc' : 'asc'; else { st.sort = k; st.dir = 'asc'; }
          paint();
          var again = root.querySelector('[data-sort="' + k + '"]');
          if (again) again.focus();
          return;
        }
        if (e.target.closest('[data-more]')) { st.shown += 100; paint(); }
      });
    }
  };

  // ---- Rules
  V.rules = {
    label: 'Rules', question: 'What does each rule do?', files: ['plan', 'runs'],
    render: function (ctx) {
      var bad = problems(ctx, ['plan']);
      if (bad) return bad;
      var p = plan(ctx), runs = runsOf(ctx), now = D.now();
      var html = ctx.files.runs.status !== 'ok' ? problems(ctx, ['runs']) : '';
      var last = runs[0];
      var monthAgo = now - 30 * 86400000;
      // who shadows whom
      var shadow = {};
      p.songs.forEach(function (s) {
        (s.explain.trace || []).forEach(function (e) {
          if (e.result === 'not_reached_but_would_match') {
            var m = shadow[e.rule] = shadow[e.rule] || {};
            var by = s.explain.decided_by || '?';
            m[by] = (m[by] || 0) + 1;
          }
        });
      });
      html += '<p class="small muted">Rules run top to bottom and the first match wins. <strong>Dead</strong> means no song in the inbox matches; <strong>shadowed</strong> means songs match but an earlier rule always takes them.</p>';
      html += '<div class="table-wrap cards"><table class="stack" data-testid="rules-table"><thead><tr><th scope="col">#</th><th scope="col">Rule</th><th scope="col">Status</th><th scope="col">Conditions</th><th scope="col">Target</th>' +
        '<th scope="col" class="num">Would match</th><th scope="col" class="num">Wins now</th><th scope="col" class="num">Last run</th><th scope="col" class="num">30 days</th><th scope="col">Last matched</th></tr></thead><tbody>';
      p.rules.forEach(function (r, i) {
        var lastWins = last ? ((last.rule_counts || {})[r.name] || 0) : null;
        var thirty = runs.length ? runs.filter(function (x) { return Date.parse(x.time) >= monthAgo; }).reduce(function (a, x) { return a + ((x.rule_counts || {})[r.name] || 0); }, 0) : null;
        var lastMatched = runs.filter(function (x) { return (x.rule_counts || {})[r.name] > 0; })[0];
        var cls = r.status === 'dead' ? 'row-bad' : (r.status === 'shadowed' ? 'row-warn' : '');
        var note = '';
        if (r.status === 'shadowed') {
          var by = shadow[r.name] || {};
          note = '<div class="small muted">Songs match, but earlier ' + esc(Object.keys(by).length > 1 ? 'rules win' : 'rule wins') + ': ' + esc(Object.keys(by).map(function (k) { return k + ' (' + by[k] + ')'; }).join(', ')) + '</div>';
        } else if (r.status === 'dead') note = '<div class="small muted">No song in the inbox matches this rule.</div>';
        else if (r.status === 'disabled') note = '<div class="small muted">Switched off in your config; it never runs.</div>';
        var weak = r.weak_signals_possible && r.weak_signals_possible.length
          ? '<div>' + badge('warn', 'Weak signals: ' + r.weak_signals_possible.map(function (s) { return s.replace('language_in:', ''); }).join(', ')) + '</div>' : '';
        html += '<tr class="' + cls + '" data-rule="' + esc(r.name) + '" data-status="' + esc(r.status) + '"><td class="num" data-label="Priority">' + (i + 1) + '</td>' +
          '<td class="cell-main"><strong>' + esc(r.name) + '</strong>' + note + weak + '</td>' +
          '<td data-label="Status">' + ruleStatusBadge(r.status) + '</td>' +
          '<td data-label="Conditions">' + Object.keys(r.conditions || {}).map(function (k) { return '<div><code>' + esc(k) + '</code> ' + esc(fmtVal(r.conditions[k])) + '</div>'; }).join('') + '<div class="small muted">waits ' + esc(r.threshold_days) + ' days</div></td>' +
          '<td data-label="Target">' + esc(r.target_playlist) + '<div class="small muted">' + esc(posText(r.target_position)) + '</div>' + targetBadge(r.target_status) + '</td>' +
          '<td class="num" data-label="Would match">' + esc(r.would_match) + '</td>' +
          '<td class="num" data-label="Wins now"><a href="#/inbox?rule=' + encodeURIComponent(r.name) + '">' + esc(r.wins) + '</a></td>' +
          '<td class="num" data-label="Last run">' + num(lastWins) + '</td>' +
          '<td class="num" data-label="30 days">' + num(thirty) + '</td>' +
          '<td data-label="Last matched">' + (lastMatched ? esc(D.fmtDate(lastMatched.time)) : '<span class="muted">' + (runs.length ? 'never' : '—') + '</span>') + '</td></tr>';
      });
      html += '</tbody></table></div>';
      return html;
    }
  };

  // ---- Playlists
  V.playlists = {
    label: 'Playlists', question: 'Can every target playlist actually be written to?', files: ['plan'],
    render: function (ctx) {
      var bad = problems(ctx, ['plan']);
      if (bad) return bad;
      var p = plan(ctx);
      var okCount = p.playlists.filter(function (x) { return x.status === 'resolved'; }).length;
      var html = '<p class="small muted">' + esc(okCount + ' of ' + p.playlists.length) + ' target playlists are ready. Every move takes a song out of Liked Songs and into one of these; "Planned in" is how many the next run would add.</p>';
      html += '<div class="table-wrap cards"><table class="stack" data-testid="playlists-table"><thead><tr><th scope="col">Playlist</th><th scope="col">Status</th><th scope="col" class="num">Size</th><th scope="col" class="num">Planned in</th>' +
        '<th scope="col" class="num">Moves out<button type="button" class="help-btn" data-tip="Always 0 for now: playlists are never a source for the sorter. Songs only ever move INTO a playlist, out of Liked Songs — a playlist itself is never sorted from." aria-label="What does moves out mean?">?</button></th>' +
        '<th scope="col">Rules that send here</th></tr></thead><tbody>';
      p.playlists.forEach(function (x) {
        var cls = x.status === 'resolved' ? '' : (x.status === 'ambiguous' ? 'row-warn' : 'row-bad');
        html += '<tr class="' + cls + '" data-status="' + esc(x.status) + '"><td class="cell-main"><strong>' + esc(x.name) + '</strong></td><td data-label="Status">' + targetBadge(x.status) + '</td>' +
          '<td class="num" data-label="Size">' + num(x.size) + '</td><td class="num" data-label="Planned in">' + esc(x.planned_in) + '</td>' +
          '<td class="num" data-label="Moves out"><span data-tip="Playlists are never a source for the sorter in this design, so this is structurally always 0.">0</span></td>' +
          '<td data-label="Rules">' + (x.rules || []).map(esc).join(', ') + '</td></tr>';
      });
      html += '</tbody></table></div>';
      html += '<ul class="small muted"><li><strong>Found</strong>: an owned or collaborative playlist with exactly this name.</li><li><strong>Missing</strong>: no playlist has this name (SpotiSort never creates playlists unless a rule allows it).</li><li><strong>Not writable</strong>: you follow it but do not own it.</li><li><strong>Ambiguous</strong>: more than one playlist has this name.</li></ul>';
      return html;
    }
  };

  // ---- Runs
  var METRICS = [['mode', 'Mode'], ['verdict', 'Verdict'], ['planned_moves', 'Planned moves'], ['moved', 'Moved'], ['too_young', 'Too young'], ['no_match', 'No match'],
    ['blocked', 'Blocked'], ['target_problems', 'Target problems'], ['errors', 'Errors'], ['warnings', 'Warnings'], ['liked_before', 'Liked before'],
    ['liked_after', 'Liked after'], ['duration_seconds', 'Duration (s)']];

  function findRun(runs, id) { return runs.filter(function (r) { return r.run_id === id; })[0]; }
  function listBlock(title, items, empty) {
    if (!items || !items.length) return '<h4>' + esc(title) + '</h4><p class="muted small">' + esc(empty) + '</p>';
    return '<h4>' + esc(title) + ' (' + items.length + ')</h4><ul>' + items.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>';
  }
  function movedTable(moved, hidden) {
    if (!moved || !moved.length) return '<p class="muted small">No songs moved or planned to move in this run.</p>';
    var h = '<div class="table-wrap cards"><table class="stack"><thead><tr><th scope="col">Song</th><th scope="col">Playlist</th><th scope="col">Rule</th><th scope="col">Position</th><th scope="col" class="num">Age / threshold</th><th scope="col">Already there</th></tr></thead><tbody>';
    moved.forEach(function (m) {
      h += '<tr><td class="cell-main"><strong>' + titleOrHidden(m.track, hidden) + '</strong><div class="small muted">' + (hidden ? '' : esc(m.artist)) + '</div></td><td data-label="Playlist">' + esc(m.playlist) + '</td><td data-label="Rule">' + esc(m.rule) + '</td><td data-label="Position">' + esc(m.target_position) + '</td><td class="num" data-label="Age / threshold">' + esc(num(m.age_days)) + ' / ' + esc(num(m.threshold_days)) + '</td><td data-label="Already there">' + (m.already_in_target ? 'yes' : 'no') + '</td></tr>';
    });
    return h + '</tbody></table></div>';
  }
  function journalTable(j, hidden) {
    if (!j || !j.length) return '<p class="muted small">No journal entries (a dry run removes nothing).</p>';
    var h = '<div class="table-wrap cards"><table class="stack" data-testid="journal"><thead><tr><th scope="col">Song</th><th scope="col">Originally liked</th><th scope="col">Target playlist id</th><th scope="col">URI</th></tr></thead><tbody>';
    j.forEach(function (e) {
      h += '<tr><td class="cell-main"><strong>' + titleOrHidden(e.name, hidden) + '</strong><div class="small muted">' + (hidden ? '' : esc((e.artists || []).join(', '))) + '</div></td><td data-label="Originally liked">' + esc(D.fmtDate(e.original_added_at)) + '</td><td data-label="Target playlist id"><code>' + esc(e.target_playlist_id) + '</code></td><td data-label="URI"><code>' + esc(e.uri) + '</code></td></tr>';
    });
    return h + '</tbody></table></div>';
  }
  function writeCount(audit) {
    var n = 0;
    Object.keys(audit || {}).forEach(function (k) { if (!/^GET\b/.test(k)) n += audit[k]; });
    return n;
  }

  function runDetail(run, log) {
    var h = '<p><a href="#/runs">&larr; All runs</a></p><div class="card" data-testid="run-detail"><h3>Run ' + esc(run.run_id) + ' ' + verdictBadge(run.verdict) + '</h3><dl class="kv">' +
      '<dt>Time</dt><dd>' + esc(D.fmtTime(run.time)) + '</dd><dt>Mode</dt><dd>' + esc(run.mode) + (run.what_if ? ' (what-if)' : '') + '</dd>' +
      '<dt>Planned / moved</dt><dd>' + esc(run.planned_moves) + ' / ' + esc(run.moved) + '</dd>' +
      '<dt>Liked songs</dt><dd>' + esc(run.liked_before) + ' before, ' + esc(run.liked_after) + ' after</dd>' +
      '<dt>Duration</dt><dd>' + esc(run.duration_seconds) + ' s</dd></dl>';
    if (!log) return h + '</div>';
    if (log.status !== 'ok') return h + '</div>' + (log.status === 'missing'
      ? '<div class="empty"><h3>Run log not found</h3><p><code>' + esc(run.log) + '</code> is not in this data source. It is created by <code>python -m src.sync</code>.</p></div>'
      : errorState('runs', log.message));
    var l = log.data;
    h += '<dl class="kv"><dt>Evaluated</dt><dd>' + esc(l.evaluated) + '</dd><dt>Skipped, no match</dt><dd>' + esc(l.skipped_no_match) + '</dd>' +
      '<dt>Config hash</dt><dd><code>' + esc(l.config_hash) + '</code></dd><dt>Spotify write calls</dt><dd>' + esc(writeCount(l.http_audit)) + (l.mode === 'dry_run' || l.dry_run ? ' (dry run: must be 0)' : '') + '</dd></dl>';
    if (l.reconcile) {
      h += '<h4>Reconcile</h4><p>' + (l.reconcile.ok ? badge('ok', 'Reconcile OK') : badge('bad', 'Mismatch')) + ' expected ' + esc(l.reconcile.expected_after) + ' liked songs after the run, found ' + esc(l.reconcile.actual_after) + '.</p>';
    }
    if (l.restore_command) h += '<h4>Restore</h4><div class="copy-row"><code>' + esc(l.restore_command) + '</code><button type="button" class="btn secondary small" data-copy="' + esc(l.restore_command) + '">Copy</button></div>';
    h += '</div>';
    var hidden = !!l.titles_hidden;
    h += listBlock('Errors', l.errors, 'No errors.') + listBlock('Warnings', l.warnings, 'No warnings.');
    h += '<h4>' + (l.dry_run ? 'Planned moves' : 'Moved') + ' (' + (l.moved || []).length + ')</h4>' + movedTable(l.moved, hidden);
    var ty = l.skipped_too_young || [];
    h += '<h4>Too young (' + ty.length + ')</h4>' + (ty.length ? '<ul>' + ty.map(function (t) { return '<li>' + titleOrHidden(t.track, hidden) + ' &mdash; ' + (hidden ? '' : esc(t.artist)) + ' (' + esc(t.age_days) + ' of ' + esc(t.threshold_days) + ' days, rule ' + esc(t.rule) + ')</li>'; }).join('') + '</ul>' : '<p class="muted small">None.</p>');
    var pm = l.skipped_playlist_missing || [];
    h += '<h4>Skipped: target problem (' + pm.length + ')</h4>' + (pm.length ? '<ul>' + pm.map(function (t) { return '<li>' + titleOrHidden(t.track, hidden) + ' &rarr; ' + esc(t.target_playlist) + ' (' + esc(t.reason) + ')</li>'; }).join('') + '</ul>' : '<p class="muted small">None.</p>');
    h += '<details><summary>Journal (' + (l.journal || []).length + ' removals recorded)</summary>' + journalTable(l.journal, hidden) + '</details>';
    if (l.batches) h += '<details><summary>Batches (' + l.batches.length + ')</summary><ul>' + l.batches.map(function (b) { return '<li><code>' + esc(b.playlist_id) + '</code>: ' + esc(b.size) + ' songs, ' + (b.committed ? 'committed' : 'NOT committed') + '</li>'; }).join('') + '</ul></details>';
    h += '<details><summary>HTTP audit</summary><dl class="kv">' + Object.keys(l.http_audit || {}).map(function (k) { return '<dt>' + esc(k) + '</dt><dd>' + esc(l.http_audit[k]) + '</dd>'; }).join('') + '</dl></details>';
    return h;
  }

  function runDiff(a, b, la, lb) {
    var h = '<p><a href="#/runs">&larr; All runs</a></p><div class="card" data-testid="run-diff"><h3>Compare runs</h3><p class="small muted">Older run on the left, newer run on the right.</p>';
    h += '<div class="table-wrap"><table><thead><tr><th scope="col">Measure</th><th scope="col">' + esc(D.fmtDate(a.time)) + ' (' + esc(a.mode) + ')</th><th scope="col">' + esc(D.fmtDate(b.time)) + ' (' + esc(b.mode) + ')</th><th scope="col" class="num">Change</th></tr></thead><tbody>';
    METRICS.forEach(function (m) {
      var x = a[m[0]], y = b[m[0]], d = '';
      if (typeof x === 'number' && typeof y === 'number') {
        var diff = Math.round((y - x) * 10) / 10;
        d = diff === 0 ? '0' : '<span class="' + (diff > 0 ? 'delta-up' : 'delta-down') + '">' + (diff > 0 ? '+' : '') + diff + '</span>';
      } else if (x !== y) d = 'changed';
      h += '<tr><th scope="row">' + esc(m[1]) + '</th><td>' + esc(fmtVal(x)) + '</td><td>' + esc(fmtVal(y)) + '</td><td class="num">' + d + '</td></tr>';
    });
    h += '</tbody></table></div>';
    var names = {};
    Object.keys(a.rule_counts || {}).concat(Object.keys(b.rule_counts || {})).forEach(function (k) { names[k] = 1; });
    var rk = Object.keys(names);
    h += '<h4>Rule wins</h4>' + (rk.length ? '<div class="table-wrap"><table><thead><tr><th scope="col">Rule</th><th scope="col" class="num">Older</th><th scope="col" class="num">Newer</th><th scope="col" class="num">Change</th></tr></thead><tbody>' +
      rk.map(function (k) { var x = (a.rule_counts || {})[k] || 0, y = (b.rule_counts || {})[k] || 0; return '<tr><th scope="row">' + esc(k) + '</th><td class="num">' + x + '</td><td class="num">' + y + '</td><td class="num">' + (y - x > 0 ? '+' : '') + (y - x) + '</td></tr>'; }).join('') + '</tbody></table></div>' : '<p class="muted small">Neither run matched any rule.</p>');
    if (la && lb && la.status === 'ok' && lb.status === 'ok') {
      var setA = {}, setB = {};
      (la.data.moved || []).forEach(function (m) { setA[m.uri + '|' + m.playlist] = m; });
      (lb.data.moved || []).forEach(function (m) { setB[m.uri + '|' + m.playlist] = m; });
      var hiddenA = !!la.data.titles_hidden, hiddenB = !!lb.data.titles_hidden;
      var onlyA = Object.keys(setA).filter(function (k) { return !setB[k]; }).map(function (k) { return (hiddenA ? TITLE_HIDDEN_MSG : setA[k].track) + ' → ' + setA[k].playlist; });
      var onlyB = Object.keys(setB).filter(function (k) { return !setA[k]; }).map(function (k) { return (hiddenB ? TITLE_HIDDEN_MSG : setB[k].track) + ' → ' + setB[k].playlist; });
      var both = Object.keys(setA).filter(function (k) { return setB[k]; }).length;
      h += '<h4>Songs</h4><p class="small">' + both + ' in both runs.</p>' + listBlock('Only in the older run', onlyA, 'None.') + listBlock('Only in the newer run', onlyB, 'None.');
    } else {
      h += '<p class="small muted">Song-level differences need both run logs, and at least one was not found.</p>';
    }
    return h + '</div>';
  }

  V.runs = {
    label: 'Runs', question: 'What did each run do?', files: ['runs'],
    render: function (ctx) {
      var bad = problems(ctx, ['runs']);
      if (bad) return bad;
      var runs = runsOf(ctx);
      var arg = ctx.arg;
      if (arg) {
        if (arg.indexOf('~') > 0) {
          var ids = arg.split('~');
          var ra = findRun(runs, ids[0]), rb = findRun(runs, ids[1]);
          if (!ra || !rb) return '<div class="empty"><h3>Run not found</h3><p>One of the runs is no longer in the history.</p><p><a href="#/runs">Back to all runs</a></p></div>';
          if (Date.parse(ra.time) > Date.parse(rb.time)) { var t = ra; ra = rb; rb = t; }
          return Promise.all([D.fetchLog(ctx.base, ra.log), D.fetchLog(ctx.base, rb.log)]).then(function (l) { return runDiff(ra, rb, l[0], l[1]); });
        }
        var run = findRun(runs, arg);
        if (!run) return '<div class="empty"><h3>Run not found</h3><p>That run is no longer in the history.</p><p><a href="#/runs">Back to all runs</a></p></div>';
        return D.fetchLog(ctx.base, run.log).then(function (l) { return runDetail(run, l); });
      }
      if (!runs.length) return '<div class="empty"><h3>No runs recorded</h3><p>Run <code>python -m src.sync</code> to record the first one.</p></div>';
      var st = ctx.state.runs = ctx.state.runs || { sel: [] };
      st.sel = st.sel.filter(function (id) { return findRun(runs, id); });
      var h = '<div class="toolbar"><button type="button" class="btn secondary small" id="compare-btn" disabled>Compare selected runs</button><span class="small muted" id="compare-hint" role="status">Tick two runs to compare them.</span></div>';
      h += '<div class="table-wrap cards"><table class="stack" data-testid="runs-table"><thead><tr><th scope="col"><span class="sr-only">Compare</span></th><th scope="col">Time</th><th scope="col">Mode</th><th scope="col">Verdict</th><th scope="col" class="num">Planned</th><th scope="col" class="num">Moved</th><th scope="col" class="num">Too young</th><th scope="col" class="num">Blocked</th><th scope="col" class="num">Errors</th><th scope="col" class="num">Warnings</th><th scope="col" class="num">Liked</th><th scope="col" class="num">Duration</th><th scope="col"><span class="sr-only">Details</span></th></tr></thead><tbody>';
      runs.forEach(function (r) {
        var cls = r.verdict === 'error' || r.verdict === 'mismatch' ? 'row-bad' : (r.warnings ? 'row-warn' : '');
        h += '<tr class="' + cls + '" data-run="' + esc(r.run_id) + '" data-verdict="' + esc(r.verdict) + '"><td class="check-cell" data-label="Compare"><input type="checkbox" data-pick="' + esc(r.run_id) + '" aria-label="Select run ' + esc(D.fmtDate(r.time)) + ' for comparison"' + (st.sel.indexOf(r.run_id) >= 0 ? ' checked' : '') + ' /></td>' +
          '<td class="cell-main"><strong>' + esc(D.fmtTime(r.time)) + '</strong>' + (r.what_if ? ' ' + badge('warn', 'What-if') : '') + '</td>' +
          '<td data-label="Mode">' + esc(r.mode === 'apply' ? 'Apply' : 'Dry run') + '</td><td data-label="Verdict">' + verdictBadge(r.verdict) + '</td>' +
          '<td class="num" data-label="Planned">' + esc(r.planned_moves) + '</td><td class="num" data-label="Moved">' + esc(r.moved) + '</td><td class="num" data-label="Too young">' + esc(r.too_young) + '</td><td class="num" data-label="Blocked">' + esc(r.blocked) + '</td>' +
          '<td class="num" data-label="Errors">' + esc(r.errors) + '</td><td class="num" data-label="Warnings">' + esc(r.warnings) + '</td>' +
          '<td class="num" data-label="Liked">' + esc(r.liked_before) + ' &rarr; ' + esc(r.liked_after) + '</td><td class="num" data-label="Duration">' + esc(r.duration_seconds) + ' s</td>' +
          '<td data-label="Details"><a href="#/runs/' + encodeURIComponent(r.run_id) + '" aria-label="Details for run ' + esc(D.fmtTime(r.time)) + '">Details</a></td></tr>';
      });
      return h + '</tbody></table></div>';
    },
    bind: function (root, ctx) {
      var btn = root.querySelector('#compare-btn');
      if (!btn) return;
      var st = ctx.state.runs;
      function sync() {
        btn.disabled = st.sel.length !== 2;
        root.querySelector('#compare-hint').textContent = st.sel.length === 2 ? 'Ready to compare.' : (st.sel.length > 2 ? 'Pick exactly two runs.' : 'Tick two runs to compare them (' + st.sel.length + ' selected).');
      }
      root.addEventListener('change', function (e) {
        var c = e.target.closest('[data-pick]');
        if (!c) return;
        var id = c.getAttribute('data-pick');
        st.sel = st.sel.filter(function (x) { return x !== id; });
        if (c.checked) st.sel.push(id);
        if (st.sel.length > 2) { var drop = st.sel.shift(); var box = root.querySelector('[data-pick="' + drop + '"]'); if (box) box.checked = false; }
        sync();
      });
      btn.addEventListener('click', function () { if (st.sel.length === 2) ctx.go('#/runs/' + st.sel.map(encodeURIComponent).join('~')); });
      sync();
    }
  };

  // ---- Safety
  function timeline(runs) {
    var pts = runs.slice().reverse();
    if (!pts.length) return '';
    var W = 480, H = 220, L = 44, R = 14, T = 14, B = 34, pw = W - L - R, ph = H - T - B;
    var vals = pts.map(function (r) { return r.liked_after; }).concat(pts.map(function (r) { return r.liked_before; }));
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    if (hi === lo) { hi += 1; lo -= 1; }
    var pad = Math.max(1, Math.round((hi - lo) * 0.1)); lo = Math.max(0, lo - pad); hi += pad;
    function x(i) { return L + (pts.length === 1 ? pw / 2 : i * pw / (pts.length - 1)); }
    function y(v) { return T + ph - (v - lo) / (hi - lo) * ph; }
    var s = '<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-labelledby="tl-title tl-desc" data-testid="timeline"><title id="tl-title">Liked songs over time</title><desc id="tl-desc">Liked song count after each run, from ' + esc(D.fmtDate(pts[0].time)) + ' to ' + esc(D.fmtDate(pts[pts.length - 1].time)) + '. ' + esc(pts.map(function (r) { return D.fmtDate(r.time) + ': ' + r.liked_after; }).join('; ')) + '.</desc>';
    for (var g = 0; g <= 4; g++) {
      var v = lo + (hi - lo) * g / 4, yy = y(v);
      s += '<line class="grid-line" x1="' + L + '" x2="' + (W - R) + '" y1="' + yy.toFixed(1) + '" y2="' + yy.toFixed(1) + '"/><text class="axis-text" x="' + (L - 6) + '" y="' + (yy + 4).toFixed(1) + '" text-anchor="end">' + Math.round(v) + '</text>';
    }
    s += '<polyline class="line" points="' + pts.map(function (r, i) { return x(i).toFixed(1) + ',' + y(r.liked_after).toFixed(1); }).join(' ') + '"/>';
    pts.forEach(function (r, i) {
      var cx = x(i).toFixed(1), cy = y(r.liked_after).toFixed(1);
      var label = D.fmtDate(r.time) + ' ' + r.mode + ': ' + r.liked_before + ' to ' + r.liked_after + ' (' + r.verdict + ')';
      if (r.verdict === 'mismatch' || r.verdict === 'error') s += '<rect class="pt-bad" x="' + (cx - 5) + '" y="' + (cy - 5) + '" width="10" height="10" transform="rotate(45 ' + cx + ' ' + cy + ')"><title>' + esc(label) + '</title></rect>';
      else if (r.mode === 'apply') s += '<circle class="pt-ok" cx="' + cx + '" cy="' + cy + '" r="5"><title>' + esc(label) + '</title></circle>';
      else s += '<circle class="pt-dry" cx="' + cx + '" cy="' + cy + '" r="4"><title>' + esc(label) + '</title></circle>';
      if (pts.length <= 6 || i % 2 === 0 || i === pts.length - 1) s += '<text class="axis-text" x="' + cx + '" y="' + (H - 12) + '" text-anchor="middle">' + esc(D.fmtDate(r.time).slice(5)) + '</text>';
    });
    return s + '</svg><div class="legend" aria-hidden="true"><span><svg width="14" height="14"><circle class="pt-ok" cx="7" cy="7" r="5" style="fill:var(--color-accent-text)"/></svg>Apply run</span><span><svg width="14" height="14"><circle cx="7" cy="7" r="4" style="fill:var(--color-surface);stroke:var(--color-text-secondary);stroke-width:2"/></svg>Dry run</span><span><svg width="14" height="14"><rect x="3" y="3" width="8" height="8" transform="rotate(45 7 7)" style="fill:var(--color-danger)"/></svg>Mismatch or error</span></div>';
  }

  V.safety = {
    label: 'Safety', question: 'Has anything been lost, and can I undo it?', files: ['runs'],
    render: function (ctx) {
      var bad = problems(ctx, ['runs']);
      if (bad) return bad;
      var runs = runsOf(ctx);
      if (!runs.length) return '<div class="empty"><h3>No runs recorded</h3><p>Run <code>python -m src.sync</code> to record the first one.</p></div>';
      var applyRuns = runs.filter(function (r) { return r.mode === 'apply'; });
      var mism = runs.filter(function (r) { return r.verdict === 'mismatch'; });
      var h = '';
      if (mism.length) h += banner('bad', '✕', '<p><strong>' + esc(plural(mism.length, 'run')) + ' failed the liked-count check.</strong> After the run, Liked Songs did not hold the number of songs it should. Open the run below and use its restore command if a song is missing.</p>', 'role="alert" data-banner="mismatch"');
      h += '<div class="card"><h3>Liked-song count over time</h3>' + timeline(runs) +
        '<details><summary>Show as a table</summary><div class="table-wrap"><table><thead><tr><th scope="col">Run</th><th scope="col">Mode</th><th scope="col" class="num">Before</th><th scope="col" class="num">After</th><th scope="col">Verdict</th></tr></thead><tbody>' +
        runs.map(function (r) { return '<tr><td>' + esc(D.fmtTime(r.time)) + '</td><td>' + esc(r.mode) + '</td><td class="num">' + esc(r.liked_before) + '</td><td class="num">' + esc(r.liked_after) + '</td><td>' + verdictBadge(r.verdict) + '</td></tr>'; }).join('') + '</tbody></table></div></details></div>';

      var logsP = Promise.all(applyRuns.map(function (r) { return D.fetchLog(ctx.base, r.log); }));
      return logsP.then(function (logs) {
        h += '<h3>Apply runs</h3>';
        if (!applyRuns.length) h += '<div class="empty" data-empty="apply"><h3>No apply runs yet</h3><p>Every run so far was a dry run, so nothing has been removed from Liked Songs and there is nothing to restore.</p></div>';
        applyRuns.forEach(function (r, i) {
          var l = logs[i], d = l && l.status === 'ok' ? l.data : null;
          h += '<section class="card" data-testid="apply-run" data-run="' + esc(r.run_id) + '"><h3>' + esc(D.fmtTime(r.time)) + ' ' + verdictBadge(r.verdict) + '</h3>';
          h += '<p class="small muted">' + esc(r.moved) + ' moved &middot; liked songs ' + esc(r.liked_before) + ' &rarr; ' + esc(r.liked_after) + '</p>';
          if (!d) { h += '<p class="small">The run log <code>' + esc(r.log) + '</code> could not be loaded' + (l && l.message ? ': ' + esc(l.message) : ' (not found)') + '.</p></section>'; return; }
          if (d.reconcile) h += '<p><strong>Reconcile:</strong> ' + (d.reconcile.ok ? badge('ok', 'OK') : badge('bad', 'Mismatch')) + ' expected ' + esc(d.reconcile.expected_after) + ', found ' + esc(d.reconcile.actual_after) + '.</p>';
          if (d.restore_command) h += '<p class="small" style="margin-bottom:4px">Restore command</p><div class="copy-row"><code>' + esc(d.restore_command) + '</code><button type="button" class="btn secondary small" data-copy="' + esc(d.restore_command) + '">Copy</button></div>';
          (d.warnings || []).forEach(function (w) { h += '<p class="small">' + badge('warn', 'Warning') + ' ' + esc(w) + '</p>'; });
          h += '<details><summary>Journal of removals (' + (d.journal || []).length + ')</summary>' + journalTable(d.journal, !!d.titles_hidden) + '</details>';
          h += '<p class="small"><a href="#/runs/' + encodeURIComponent(r.run_id) + '">Full run detail</a></p></section>';
        });
        h += '<h3>Vanished-song warnings</h3><div class="card" data-testid="vanished"><p>' + badge('neutral', 'Not available yet') + '</p><p class="small">Spotify has been seen silently dropping liked songs. A future guardian will remember which songs were liked at each run and warn here when one disappears without SpotiSort removing it. Nothing is monitored yet, so an empty list would not mean everything is fine.</p></div>';
        return h;
      });
    }
  };

  // ---- Signals
  var SIGNALS = ['playlist', 'script', 'hint', 'country_default'];
  var SIGNAL_TEXT = {
    playlist: 'Learned from your own language playlists. Trusted by design.',
    script: 'Read from the writing system of the title (for example Malayalam script). Trusted by design.',
    hint: 'A guess from other hints, such as MusicBrainz release language. Only trusted once measured at 90% or better.',
    country_default: 'A guess from the artist’s country (for example English for US artists). Only trusted once measured at 90% or better.'
  };
  function barRows(obj, total, cls) {
    return Object.keys(obj).sort(function (a, b) { return obj[b] - obj[a]; }).map(function (k) {
      var w = total ? obj[k] / total * 100 : 0;
      return '<div class="bar-row"><span>' + esc(k.replace('_', ' ')) + '</span><div class="bar ' + (cls || '') + '" role="img" aria-label="' + w.toFixed(1) + ' percent"><span style="--w:' + w.toFixed(1) + '%"></span></div><span class="num">' + esc(obj[k]) + ' (' + w.toFixed(0) + '%)</span></div>';
    }).join('');
  }

  V.signals = {
    label: 'Signals', question: 'How much can each language and genre signal be trusted?', files: ['coverage', 'precision'],
    render: function (ctx) {
      var h = problems(ctx, ['coverage', 'precision']);
      var cov = ok(ctx.files.coverage) ? ctx.files.coverage.data : null;
      var prec = ok(ctx.files.precision) ? ctx.files.precision.data : null;
      if (cov) {
        var srcTotal = 0;
        Object.keys(cov.language_source_counts || {}).forEach(function (k) { srcTotal += cov.language_source_counts[k]; });
        h += '<h3>Coverage</h3><div class="grid" data-testid="coverage">' +
          card('Songs analysed', esc(cov.tracks), esc(cov.unique_primary_artists) + ' unique primary artists') +
          card('Genre coverage', esc(cov.genre_coverage_pct_of_artists) + '%', 'of artists have at least one genre') +
          card('Language coverage', esc(cov.language_coverage_pct_whole_library) + '%', 'of all songs have a language') +
          card('Target-language coverage', esc(cov.language_coverage_pct_target_language_tracks) + '%', esc(cov.target_language_tracks_resolved) + ' of ' + esc(cov.target_language_tracks) + ' songs in your language playlists') + '</div>';
        h += '<div class="card"><h3>Where languages came from</h3>' + barRows(cov.language_source_counts || {}, srcTotal) + '<p class="small muted">"none" means no language could be found. Hints and country defaults are weak (see the precision table).</p></div>';
        h += '<div class="card"><h3>Language mix</h3>' + barRows(cov.language_distribution || {}, Object.keys(cov.language_distribution || {}).reduce(function (a, k) { return a + cov.language_distribution[k]; }, 0), 'info') + '</div>';
        if (cov.genre_source_counts) h += '<div class="card"><h3>Where genres came from</h3>' + barRows(cov.genre_source_counts, Object.keys(cov.genre_source_counts).reduce(function (a, k) { return a + cov.genre_source_counts[k]; }, 0), 'info') + '</div>';
        if (cov.musicbrainz) h += '<p class="small muted">MusicBrainz: ' + esc(cov.musicbrainz.requests) + ' requests, ' + esc(cov.musicbrainz.retries_after_503_or_429) + ' retries, ' + esc(cov.musicbrainz.errors) + ' errors.</p>';
      }
      if (prec) {
        var langs = {};
        SIGNALS.forEach(function (s) { Object.keys((prec.by_signal || {})[s] || {}).forEach(function (l) { langs[l] = 1; }); });
        var minP = prec.min_precision, minN = prec.min_samples;
        h += '<h3>Precision per signal and language</h3><p class="small muted">A signal may decide a move only when it is right at least ' + esc(pct(minP, 0)) + ' of the time over at least ' + esc(minN) + ' predictions, measured against your own playlists. <strong>Qualified</strong> signals can drive rules; <strong>not qualified</strong> ones are still shown but withheld from rules.</p>';
        h += '<div class="table-wrap cards"><table class="stack" data-testid="precision-table"><thead><tr><th scope="col">Language</th>' + SIGNALS.map(function (s) { return '<th scope="col">' + esc(s.replace('_', ' ')) + '</th>'; }).join('') + '</tr></thead><tbody>';
        Object.keys(langs).sort().forEach(function (lang) {
          h += '<tr><td class="cell-main"><strong>' + esc(lang) + '</strong></td>';
          SIGNALS.forEach(function (s) {
            var st = ((prec.by_signal || {})[s] || {})[lang];
            var label = s.replace('_', ' ');
            if (!st) { h += '<td data-label="' + esc(label) + '" data-signal="' + s + '" data-lang="' + esc(lang) + '"><span class="muted">not measured</span></td>'; return; }
            var q = ((prec.qualified || {})[lang] || []).indexOf(s) >= 0;
            h += '<td data-label="' + esc(label) + '" data-signal="' + s + '" data-lang="' + esc(lang) + '" data-qualified="' + (q ? 'yes' : 'no') + '"><strong>' + esc(pct(st.precision)) + '</strong> <span class="small muted">(' + esc(st.correct) + ' of ' + esc(st.predicted) + ')</span><div>' + (q ? badge('ok', 'Qualified') : badge('bad', 'Not qualified')) + '</div></td>';
          });
          h += '</tr>';
        });
        h += '</tbody></table></div><dl class="kv">' + SIGNALS.map(function (s) { return '<dt>' + esc(s.replace('_', ' ')) + '</dt><dd>' + esc(SIGNAL_TEXT[s]) + '</dd>'; }).join('') + '</dl>';
      }
      return h;
    }
  };

  // ---- Backtest
  V.backtest = {
    label: 'Backtest', question: 'Would the rules put songs in the right playlists?', files: ['backtest', 'detail'],
    render: function (ctx) {
      var det = ok(ctx.files.detail) ? ctx.files.detail : null;
      var bt = ok(ctx.files.backtest) ? ctx.files.backtest : det;
      if (!bt) {
        var f = ctx.files.backtest;
        return f.status === 'error' ? errorState('backtest', f.message) : emptyState('backtest');
      }
      var d = (det || bt).data, named = !!det;
      var pname = {}, rname = {};
      d.playlists.forEach(function (p) { pname[p.id] = p.name || p.id; });
      d.rules.forEach(function (r) { rname[r.name_id] = r.name || r.name_id; });
      var t = d.totals;
      var h = '';
      if (!d.all_rules_enabled) h += banner('info', '●', '<p>This backtest ran with your real enabled/disabled settings, so disabled rules did not take part.</p>');
      h += '<div class="grid" data-testid="backtest-totals">' +
        card('Precision', esc(pct(t.precision)), 'Of songs routed, the share sent to the right playlist') +
        card('Recall', esc(pct(t.recall)), 'Of all songs, the share routed correctly') +
        card('Routed', esc(t.routed), esc(t.correct) + ' correct, ' + esc(t.misrouted) + ' misrouted') +
        card('Unrouted', esc(t.unrouted), 'Matched no rule (of ' + esc(t.tracks) + ' songs)') + '</div>';
      h += '<div class="card"><h3>Per playlist</h3><div class="table-wrap cards" style="border:0;margin:0"><table class="stack" data-testid="backtest-playlists"><thead><tr><th scope="col">Playlist</th><th scope="col" class="num">Songs</th><th scope="col" class="num">Routed here</th><th scope="col" class="num">Correct</th><th scope="col">Precision</th><th scope="col">Recall</th><th scope="col" class="num">Unrouted</th></tr></thead><tbody>';
      d.playlists.forEach(function (p) {
        h += '<tr data-playlist="' + esc(p.id) + '"><td class="cell-main"><strong>' + esc(p.name || p.id) + '</strong></td><td class="num" data-label="Songs">' + esc(p.tracks) + '</td><td class="num" data-label="Routed here">' + esc(p.predicted) + '</td><td class="num" data-label="Correct">' + esc(p.tp) + '</td><td data-label="Precision">' + pctCell(p.precision) + '</td><td data-label="Recall">' + pctCell(p.recall, 'info') + '</td><td class="num" data-label="Unrouted">' + esc(p.unrouted) + '</td></tr>';
      });
      h += '</tbody></table></div></div>';
      var conf = d.confusions.slice().sort(function (a, b) { return b.count - a.count; });
      h += '<div class="card"><h3>Confusions</h3><p class="small muted">Songs that belong in one playlist but were routed to another.</p>' + (conf.length ? '<div class="table-wrap cards" style="border:0;margin:0"><table class="stack" data-testid="confusions"><thead><tr><th scope="col">Belongs in</th><th scope="col">Routed to</th><th scope="col" class="num">Songs</th></tr></thead><tbody>' +
        conf.map(function (c) { return '<tr><td class="cell-main">' + esc(pname[c.true] || c.true) + '</td><td data-label="Routed to">' + esc(pname[c.predicted] || c.predicted) + '</td><td class="num" data-label="Songs">' + esc(c.count) + '</td></tr>'; }).join('') + '</tbody></table></div>' : '<p>No misroutes.</p>') + '</div>';
      h += '<div class="card"><h3>Per rule</h3><div class="table-wrap cards" style="border:0;margin:0"><table class="stack"><thead><tr><th scope="col">Rule</th><th scope="col" class="num">Routed</th><th scope="col" class="num">Correct</th><th scope="col">Precision</th></tr></thead><tbody>' +
        d.rules.map(function (r) { return '<tr><td class="cell-main"><strong>' + esc(r.name || r.name_id) + '</strong></td><td class="num" data-label="Routed">' + esc(r.predicted) + '</td><td class="num" data-label="Correct">' + esc(r.correct) + '</td><td data-label="Precision">' + pctCell(r.precision) + '</td></tr>'; }).join('') + '</tbody></table></div></div>';
      h += '<div class="card" data-testid="misroutes"><h3>Top misroutes</h3>';
      if (named && d.top_misroutes && d.top_misroutes.length) {
        h += '<div class="table-wrap cards" style="border:0;margin:0"><table class="stack"><thead><tr><th scope="col">Song</th><th scope="col">Belongs in</th><th scope="col">Routed to</th><th scope="col">By rule</th></tr></thead><tbody>' +
          d.top_misroutes.map(function (m) { return '<tr><td class="cell-main"><strong>' + esc(m.title) + '</strong><div class="small muted">' + esc((m.artists || []).join(', ')) + '</div></td><td data-label="Belongs in">' + esc((m.true || []).join(', ')) + '</td><td data-label="Routed to">' + esc(m.predicted) + '</td><td data-label="By rule">' + esc(m.rule) + '</td></tr>'; }).join('') + '</tbody></table></div>';
      } else {
        h += '<p>Song names are only shown in Local mode, when <code>logs/backtest-detail.json</code> exists. That file is never published, so playlists appear as P01, P02 and rules as R01, R02 here. Run <code>python -m src.backtest</code> on your computer, then <code>python -m src.dashboard</code>.</p>';
      }
      return h + '</div>';
    }
  };

  window.DashViews = { VIEWS: V, ORDER: ['overview', 'inbox', 'rules', 'playlists', 'runs', 'safety', 'signals', 'backtest'], viewHead: viewHead, explainHtml: explainHtml, esc: esc };
})();
