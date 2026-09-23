# SpotiSort component library — API reference

Vanilla CSS/JS, no build step. Three files, load in this order on every page:

```html
<link rel="stylesheet" href="assets/tokens.css" />       <!-- colour/type/space/motion variables -->
<link rel="stylesheet" href="assets/components.css" />   <!-- every component below -->
<link rel="stylesheet" href="assets/site.css" />          <!-- marketing-site-only layout (header/footer/hero/etc.) -->
...
<script src="assets/ui.js" defer></script>                <!-- behaviour, exposes window.SpotiUI -->
<script src="assets/shell.js" defer data-active="home"></script> <!-- header/footer, see "Site shell" below -->
```

Adjust relative paths (`../assets/...`) for pages nested one level deep (e.g. `docs/setup/index.html`).
`ui.js` self-initializes on `DOMContentLoaded` and is idempotent — call `SpotiUI.init(container)` again after
injecting new markup (e.g. rows added by a framework-free render function) to wire up tooltips/tabs/tag
inputs/sortable headers/copy buttons inside it.

Tokens are documented as comments in `tokens.css` itself; this file covers `components.css` + `ui.js` only.

---

## Buttons

```html
<button class="btn btn-primary">Primary</button>
<button class="btn btn-secondary">Secondary</button>
<button class="btn btn-ghost">Ghost</button>
<button class="btn btn-danger">Danger</button>
<button class="btn btn-icon" aria-label="Close"><svg class="icon">…</svg></button>
<button class="btn btn-primary btn-sm">Small</button>
```
- Sizes: default (44px min-height, the touch target) and `.btn-sm` (32px).
- States: `disabled` attribute or `aria-disabled="true"` (visually identical, use `aria-disabled` when the
  button must stay focusable/announced); `.is-loading` or `aria-busy="true"` shows a spinner and hides the
  label (keep the label in markup — it's just visually hidden, not removed, so screen readers still get it).
- `.btn-icon` is circular, sized to the touch target; add `.btn-sm` for a 32px icon button.

## Inputs, selects, textareas

```html
<div class="field">
  <label class="label" for="f1">Playlist name <button class="help" data-tip="Must match an existing playlist exactly." aria-label="Why does this matter?">?</button></label>
  <input id="f1" class="input" type="text" />
  <p class="hint">e.g. Chill Hindi</p>
</div>
<select class="select">…</select>
<textarea class="textarea"></textarea>
```
- Invalid state: `aria-invalid="true"` on the control; pair with a `.error-msg` referenced by `aria-describedby`.
- Disabled: native `disabled` attribute (styling is automatic).
- `<select>`, `<input type="file">`, `<input type="number">` are restyled by the base CSS automatically —
  just add `.input`/`.select` classes (file/number inputs use `.input` too).

## Checkbox / radio / switch

```html
<label class="check-row"><input type="checkbox" class="check" /> Enabled</label>
<label class="check-row"><input type="radio" class="radio" name="g" /> Option</label>

<label class="switch">
  <input type="checkbox" class="switch-input" role="switch" aria-checked="false" />
  <span class="switch-ui" aria-hidden="true"></span>
  <span class="switch-label">Advanced mode</span>
</label>
```
`role="switch"` + keep `aria-checked` in sync with `checked` in your own change handler (plain CSS can't do
this for you).

## Segmented control

```html
<div class="segmented" role="radiogroup" aria-label="Density">
  <label><input type="radio" name="density" checked /><span>Comfortable</span></label>
  <label><input type="radio" name="density" /><span>Compact</span></label>
</div>
```

## Tag input

```html
<div class="field">
  <label class="label" for="artists">Artists</label>
  <div class="tags" id="artists-tags" data-tag-input data-values="Bonobo,Tycho">
    <input id="artists" type="text" aria-label="Add an artist, then press Enter" />
  </div>
</div>
```
Auto-wired by `ui.js` on `[data-tag-input]` (also callable manually: `SpotiUI.tagInput(el, opts)`).
- `opts.values` (array) or `data-values="a,b"` sets the initial chips.
- `opts.onChange(values)` fires on every add/remove; also dispatches a bubbling `ui:tags-change` CustomEvent
  (`event.detail` = current array) so a parent controller doesn't need to hold a reference.
- `opts.validate(str) => false` rejects a candidate tag and sets `aria-invalid="true"` on the container.
- API: `el.uiTags.get()`, `.set(array)`, `.add(rawString)`.
- Enter or `,` commits the current text as a tag; Backspace on an empty input removes the last tag; paste of
  comma/newline-separated text splits into multiple tags.

## Cards

```html
<div class="card">…</div>
<div class="card card-elevated">…</div>
<a class="card card-interactive" href="…">…</a>
```

## Tabs

```html
<div role="tablist" aria-label="Config sections">
  <button role="tab" id="t1" aria-controls="p1" aria-selected="true" class="tab">Basics</button>
  <button role="tab" id="t2" aria-controls="p2" aria-selected="false" class="tab">Rules</button>
</div>
<div role="tabpanel" id="p1" aria-labelledby="t1" class="tabpanel">…</div>
<div role="tabpanel" id="p2" aria-labelledby="t2" class="tabpanel" hidden>…</div>
```
`ui.js` auto-selects the first `aria-selected="true"` tab (or the first tab) per `[role="tablist"]` on init,
manages `hidden` on panels, arrow-key/Home/End navigation, and fires a bubbling `ui:tab` CustomEvent
(`detail` = the selected tab element). Programmatic select: `SpotiUI.selectTab(tabEl, focus?)`.

## Modal + side drawer

```html
<div class="overlay" id="my-modal" hidden>
  <div class="dialog" role="dialog" aria-labelledby="my-modal-title">
    <div class="dialog-head"><h2 id="my-modal-title">Title</h2>
      <button class="btn btn-icon" data-close aria-label="Close">×</button></div>
    <div class="dialog-body">…</div>
    <div class="dialog-foot">
      <button class="btn btn-secondary" data-close>Cancel</button>
      <button class="btn btn-primary">Confirm</button>
    </div>
  </div>
</div>
<button data-open="my-modal">Open</button>
```
For a side drawer, swap `.overlay` → `.overlay .overlay-side` and `.dialog` → `.drawer`.
- Open declaratively with `data-open="<id>"` on any trigger, or `SpotiUI.open(idOrEl, {trigger})`.
- Close with `data-close` on any element inside, clicking the scrim, `Esc`, or `SpotiUI.close()`.
- Handles: focus trap (Tab wraps within the panel), focus moves to `[data-autofocus]` or the first focusable
  element on open, focus returns to the trigger on close, everything outside is `inert`, background scroll is
  locked (`body.ui-locked`), nested overlays stack correctly (`Esc`/close always affects the topmost).
- `SpotiUI.confirm({title, message, confirmLabel, cancelLabel, danger}) → Promise<boolean>` builds a
  throwaway confirm dialog with the same accessibility wiring — use this instead of `window.confirm`.
- Events: `ui:open` / `ui:close` (bubbling, `detail` = the overlay element).

## Toasts

```js
SpotiUI.toast('Configuration saved.', { type: 'success' });         // 'info' (default) | 'success' | 'warning' | 'error'
SpotiUI.toast('Could not save.', { type: 'error', timeout: 0 });     // timeout: 0 = sticky until dismissed
SpotiUI.toast('Version dropped.', { action: { label: 'Undo', onClick: fn } });
```
Container is `role="region" aria-live="polite"`; `type: 'error'` toasts additionally get `role="alert"`.
Auto-dismiss pauses on hover/focus. Returns `{ dismiss(), el }`.

## Tooltip

```html
<button class="help" data-tip="Days before a song is eligible to move." aria-label="Why does this matter?">?</button>
<span tabindex="0" data-tip="Matched on any credited artist, case-insensitive.">artist_in</span>
```
Any element with `data-tip="…text…"` gets a tooltip automatically — no manual wiring needed. Shows on hover
**and** keyboard focus, dismisses on `Esc`/blur/scroll, is reachable on touch (tap toggles it), and is wired
as `role="tooltip"` + `aria-describedby` pointing at the trigger. **Never put information nowhere else** — the
tooltip text should be a supplement (e.g. an example), not the only place a required fact is stated.
Non-focusable triggers (e.g. a `<span>`) are auto-tabindexed to `0`. Programmatic: `SpotiUI.showTip(el)` /
`SpotiUI.hideTip()`.

## Popover

```html
<button data-popover="pop-1" aria-expanded="false">Advanced</button>
<div id="pop-1" class="popover" hidden>…richer content, can contain interactive controls…</div>
```
Toggle on click, `Esc` or outside click/focus closes it and returns focus to the trigger on `Esc`.
Use popovers for richer content than a tooltip (multiple lines, a link, a mini-form); use tooltips for a
single line of help text.

## Badge / chip

```html
<span class="badge badge-success">Healthy</span>  <!-- also -danger, -warning, -info, or bare .badge (neutral) -->
<button class="chip" aria-pressed="false">Language: Hindi</button>          <!-- filter chip -->
<span class="chip">Rule 2 <button class="chip-x" aria-label="Remove">×</button></span>  <!-- removable chip -->
```
A badge/chip conveying status must still include a text word — colour is never the only signal (decision 34).

## Table

```html
<div class="table-wrap" style="--table-max: 28rem">  <!-- omit --table-max for no scroll cap -->
  <table class="table">  <!-- add .table-compact for the compact density -->
    <thead><tr>
      <th data-sort="text">Name</th>
      <th data-sort="num" class="num">Count</th>
    </tr></thead>
    <tbody>
      <tr><td>Alpha</td><td class="num" data-value="12">12</td></tr>
    </tbody>
  </table>
</div>
```
- `th[data-sort="text"|"num"]` gets a sort button auto-injected (sticky header is automatic via `.table`).
  Click toggles ascending/descending, updates `aria-sort`, announces the change, and moves `<tr>`s in place —
  no framework needed. Provide `data-value` on `<td>` when the sortable value differs from its rendered text
  (e.g. a raw number backing a formatted string). Programmatic: `SpotiUI.sortBy(thEl, 'ascending'|'descending')`.
  Fires a bubbling `ui:sort` CustomEvent.
- For a phone card layout instead of horizontal scroll (decision 34), that's a page-level concern: render an
  alternate `.card` list at narrow widths rather than relying on this table markup — `components.css` does not
  auto-convert a table to cards.

## Empty state / skeleton / banner

```html
<div class="empty">
  <svg class="icon">…</svg>
  <h3>No songs waiting</h3>
  <p>Your inbox is empty — check back after your next scheduled run.</p>
</div>

<div class="skeleton-line"></div>
<div class="skeleton-line short"></div>

<div class="banner banner-warning" role="status">   <!-- role="alert" for danger banners the user must notice -->
  <svg class="icon">…</svg>
  <div class="banner-body"><strong>Data is 3 days old.</strong> <a href="#">Run now</a> to refresh it.</div>
  <button class="btn btn-icon btn-sm" data-dismiss aria-label="Dismiss">×</button>
</div>
```
`banner-success` / `-warning` / `-danger` or bare `.banner` (info, the default). `[data-dismiss]` removes the
closest `.banner` (or any `[role]` ancestor) from the DOM on click.

## Stepper

```html
<ol class="stepper">
  <li class="is-done">Basics</li>
  <li aria-current="step">Languages</li>
  <li>Rules</li>
  <li>Review</li>
</ol>
```
Numbers are pure CSS counters; `.is-done` shows a check, `aria-current="step"` highlights the active step.

## Code / YAML view with copy button

```html
<div class="code" data-copyable>
  <pre><code>default_days_threshold: 14</code></pre>
</div>
```
`ui.js` injects a `.code-copy` button into any `.code[data-copyable]` on init (idempotent — re-running
`SpotiUI.init()` won't double it up). The button copies the container's `<code>`/`<pre>` text by default;
override with `data-copy="literal text"` on the button yourself, or `data-copy-target="#selector"` on the
`.code` wrapper to copy a different element's text. Uses `navigator.clipboard` when available, falls back to
a hidden-textarea `execCommand('copy')`, and always announces success/failure via the shared live region.
Manual copy anywhere: `SpotiUI.copy(text) → Promise`.

## Disclosure (FAQ / details)

```html
<details class="disclosure">
  <summary>Is it safe to run against my real library?</summary>
  <p>Yes — nothing is removed until…</p>
</details>
```
Plain `<details>`/`<summary>` — no JS required, works with `Ctrl+F`/browser find, keyboard-native.

## Meter

```html
<div class="meter" role="meter" aria-label="Genre coverage" aria-valuenow="72" aria-valuemin="0" aria-valuemax="100" style="--v: 72%">
  <span></span>
</div>
```
`.meter-warning` / `.meter-danger` recolour the fill. `aria-label` (or `aria-labelledby`) is required — axe-core
flags an unnamed `role="meter"` as a serious violation.

---

## Global helpers exposed on `window.SpotiUI`

| Call | Purpose |
|---|---|
| `SpotiUI.init(root?)` | (Re-)wire tooltips/tabs/tag-inputs/sortable-headers/copy-buttons under `root` (default: whole document). Idempotent. |
| `SpotiUI.theme.current()` | `'dark'` \| `'light'` — resolves explicit choice or `prefers-color-scheme`. |
| `SpotiUI.theme.set('dark'\|'light'\|null)` | Set/persist (`localStorage`), or `null` to clear the override and follow the OS. |
| `SpotiUI.theme.toggle()` | Flip between dark/light; wired automatically to any `[data-theme-toggle]` button. |
| `SpotiUI.open(idOrEl, {trigger}?)` / `SpotiUI.close(idOrEl?)` | Modal/drawer control (see above). |
| `SpotiUI.confirm(opts) → Promise<boolean>` | Accessible confirm dialog, see Modal section. |
| `SpotiUI.toast(msg, opts?) → {dismiss, el}` | See Toasts. |
| `SpotiUI.announce(msg)` | Push a message to the shared polite live region (for state changes with no visible focus target). |
| `SpotiUI.tagInput(el, opts?)` | Manually attach/get a tag-input controller. |
| `SpotiUI.sortBy(th, dir?)` / `SpotiUI.selectTab(tab, focus?)` | Programmatic table sort / tab select. |
| `SpotiUI.copy(text) → Promise` | Clipboard write with fallback. |
| `SpotiUI.showTip(el)` / `SpotiUI.hideTip()` / `SpotiUI.openPopover(el)` / `SpotiUI.closePopover()` | Manual tooltip/popover control. |

Theme persistence key: `localStorage['spotisort-theme']` (`'dark'` / `'light'` / absent = follow OS). All
storage access is wrapped in `try/catch` with a silent no-op fallback — the library never throws if storage
is blocked (private browsing, quota, disabled cookies).

CSS custom properties consumed everywhere: see `tokens.css` for the full list (colours, `--space-*`,
`--radius-*`, `--text-*`, `--motion-*`, `--z-*`). Never hardcode a colour or a spacing value in page-level CSS
— add a token if one is missing instead.

---

## Site shell (header/footer): `docs/assets/shell.js`

One `<script>` + one placeholder `<div id="site-shell">` (containing a `<noscript>` fallback of plain links)
renders the sticky header and appends the footer to `<body>`. Full usage, including the exact markup to copy,
is documented at the top of `docs/assets/shell.js` itself — read that file's header comment before wiring up
a new page (Configure and the Dashboard should use the same mechanism unchanged).

Key points for pages that embed it:
- `data-active` on the `<script>` tag (`home` \| `configure` \| `dashboard` \| `setup` \| `none`) sets
  `aria-current="page"` on the matching nav link.
- All nav/asset links are computed from the script's own resolved URL, so the same file works at
  `https://vishnu-drx.github.io/SpotiSort/`, at any fork's `https://<user>.github.io/SpotiSort/`, and from a
  local `python -m http.server` root — never hardcode `/SpotiSort/` anywhere in page markup.
- Footer content (author name + socials) is read once from `docs/site.config.json` at the site root; only
  keys present in that file are rendered (no empty icons/placeholders for missing socials).
- `window.SpotiShell.deriveFork(locationLike?)` is exposed for unit testing the "Your fork" derivation without
  a real navigation (pass a `{hostname, pathname}`-shaped object).

---

## What's out of scope here

Configure-specific widgets (rule cards, YAML editor with error markers, versions diff view) and
Dashboard-specific widgets (Explain drawer narrative, filter-chip bar, glossary drawer) are **not** part of
this library — they are composed from the primitives above by the Configure/Dashboard implementations. If a
primitive is missing something a coming U2/U3 page needs, extend `components.css`/`ui.js` and this file rather
than inventing a one-off pattern in `docs/builder/` or `docs/dashboard/`.
