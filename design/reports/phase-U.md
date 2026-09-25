### U2 — GitHub device flow feasibility

**Method used:** live HTTP probe via `curl` against `https://github.com/login/device/code` (Sept 23, 2026),
inspecting response headers for CORS signalling — **not** a full Playwright browser `fetch()`, but a direct
inspection of the exact header (`Access-Control-Allow-Origin`) that a browser's CORS check depends on, which is
sufficient to determine the outcome a `fetch()` would see.

- `OPTIONS /login/device/code` with `Origin: https://vishnu-drx.github.io`, `Access-Control-Request-Method: POST`
  → `404 Not Found`, **no `Access-Control-Allow-Origin` header** in the response at all.
- `POST /login/device/code` with the same `Origin` header, form-encoded `client_id`/`scope`, `Accept: application/json`
  → `404 Not Found` (the endpoint's current path/shape returned "Not Found" for this probe — GitHub may have moved
  or renamed it, or it requires a registered OAuth App's real `client_id` to respond meaningfully), and again
  **no `Access-Control-Allow-Origin` header** anywhere in the response.

**Finding:** Because neither the preflight `OPTIONS` response nor the actual request carries an
`Access-Control-Allow-Origin` header, a browser running `fetch()` from `https://vishnu-drx.github.io` (or any
fork's Pages origin) would have the response blocked by CORS regardless of status code — `fetch` would reject
with a CORS/network error before the page ever sees the JSON body. This matches GitHub's own public documentation
for the OAuth device flow, which describes it as designed for CLI/native/server clients, not browser JS, and does
not document CORS support for `github.com/login/device/code` or `github.com/login/oauth/access_token`.

**Conclusion:** Device-flow login is **not feasible directly from browser JavaScript** on the static Pages site.
Per decision 29, Phase 7 should implement the documented fallback instead: a guided **fine-grained personal
access token** flow — deep-link the user to GitHub's token-creation page pre-scoped to `Contents: read/write` on
their own fork only, have them paste the token into the page, and keep it in `sessionStorage` only (never
persisted to `localStorage`, never logged, cleared on tab close). This is out of scope for U2 (Phase 7
preparation only) — no token flow was implemented in this session.
