---
slug: settings-save-freezes-ui
status: fixed-pending-verification
trigger: |
  After updating settings on /settings and clicking "Save settings", the page appears
  to register the save but the UI becomes completely frozen — no clicks work anywhere.
  Refreshing the page or navigating away and returning shows the form reverted to
  default values, even though the new values DID persist in the database. Risky and
  annoying — operator cannot tell if save succeeded without a hard refresh + DB check.
created: 2026-04-26T16:32:40Z
updated: 2026-04-26T17:10:00Z
---

# Debug: settings-save-freezes-ui

## Symptoms

- **Expected:** Click "Save settings" → settings persist + UI reflects saved values + page remains responsive
- **Actual:**
  1. Click Save → no visible feedback (no toast, no spinner, no button state change)
  2. Page becomes completely frozen — clicks anywhere don't work
  3. User must hard-refresh to recover
  4. After refresh OR after navigating away and back, UI shows DEFAULT values
  5. BUT the database has the NEW values persisted correctly
- **Errors:** None — DevTools console & network tab clean
- **Timeline:** Reported 2026-04-26 on milestone v1.1 (post Phase 7 dashboard redesign)
- **Reproduction:** /settings page → modify any field → click "Save settings"
- **Page:** /settings (global settings page; no per-account /accounts/<id>/settings route exists)
- **Account in use:** "Vantage Demo-10k" (the only configured account, with whitespace)

## Symptom Triad (data vs UI divergence)

1. **Backend works** — DB write succeeds (new values present)
2. **Frontend save handler hangs** — entire UI freezes, no toast, no error
3. **GET on reload returns defaults** — either the read path doesn't return persisted values, or the form initializer ignores them

## Investigation findings

### What the post-Phase 7-08 flow IS doing

Settings save is a **two-step modal flow** (not a single-click save):

1. User clicks "Save Changes" on `/settings`
   → POST `/settings/{name}` (URL-encoded space → `/settings/Vantage%20Demo-10k`)
   → Server validates hard caps, returns confirm-modal partial
   → HTMX swaps response into `#modal-root` (innerHTML)
   → Modal appears as a fixed-inset overlay (`bg-dark-900/80 z-50`)

2. User clicks "Confirm change" inside the modal
   → POST `/settings/{name}/confirm`
   → Server runs `SettingsStore.update()` per-changed-field (DB write + cache reload)
   → Response: `partials/account_settings_tab.html` (replacement form + audit timeline)
     PLUS appended OOB toast (`<div hx-swap-oob="beforeend:#toaster">`)
     PLUS appended OOB modal-clear (`<div id="modal-root" hx-swap-oob="true"></div>`)
   → HTMX swaps main response into `#tab-{slug} .card` (innerHTML)
   → OOB swaps clear modal-root and append toast

### Code reviewed and found OK

- `_slug` Jinja filter (dashboard.py:72) → `Vantage Demo-10k` → `Vantage-Demo-10k` ✓
- Tab id matches modal hx-target (settings.html:25, settings_confirm_modal.html:44) ✓
- `_append_to_response_body` updates both `.body` and `Content-Length` correctly ✓
- `SettingsStore.update()` writes through to DB and reloads cache for that account ✓
- `SettingsStore.effective()` returns from cache after write ✓
- DB schema for `account_settings` is correct (single row per name, ON CONFLICT update) ✓
- Single-process / single-worker uvicorn (no cache divergence between workers) ✓
- All cf591b4 regression tests assert this end-to-end and were "verified in browser" ✓
- The audit timeline partial uses `a.name` (raw) only inside form-encoded URLs and HTML text — no fragile selectors ✓

### Plausible root causes (ranked)

**H1 (most likely): User confusion with the two-step modal flow.**
The "Save Changes" button does NOT save — it opens a confirm modal. The modal is
a fixed-position overlay with `bg-dark-900/80` covering the whole viewport. If the
user does not realize a modal is shown (e.g. it appears below the fold on a long
form, or the user is scrolled to the bottom and the modal centers off-screen),
they would experience exactly:
  - "Site froze, can't click anywhere" (modal backdrop steals all clicks)
  - "Have to refresh to escape"
  - DB still has new values *from a prior session* where they did click Confirm
  - The form on reload shows the *previously-saved* DB values (which the user may
    be misreporting as "defaults" if they recently reverted via SQL or never
    successfully clicked Confirm in the broken session)
However: user said console+network are clean and there is "no toast, no spinner,
no button state change". A modal *appearing* is itself a state change, so this
hypothesis requires the user to have missed the modal entirely.

**H2: HTMX 2.0.4 not URL-encoding the literal-space `hx-post` URL on the live form.**
The first-click form has `hx-post="/settings/Vantage Demo-10k"` (space, not `%20`).
Some HTMX versions/configurations send the URL unencoded, which uvicorn rejects
with a 400 before any handler runs. This would explain "click does nothing" with
NO network entry visible (browsers may suppress 400s in some panels). Need to
confirm by checking the actual request URL in DevTools Network → All filter.

**H3: A new top-level error in basecoat.min.js or the bridge JS thrown during
the post-confirm afterSwap callback that aborts the HTMX swap mid-flight,
leaving the modal-root NOT cleared.**
`/static/vendor/basecoat/basecoat.min.js` is **0 bytes** on disk. The bridge guards
with `if (window.basecoat && ...)` so this should be a no-op. But if the deployed
container has a non-empty basecoat.min.js whose `init()` throws on a re-rendered
form, the modal-clear OOB would never visually take effect (modal stays up,
backdrop blocks clicks, no toast appears). The user would see exactly the
reported symptoms.

**H4: Browser-level form caching of select/number inputs across navigation.**
Some browsers restore form state from bfcache on back/forward navigation. Hard
refresh would defeat this. User says hard refresh ALSO shows defaults, which
makes H4 less likely on its own — unless "default" actually means "the value
that's in DB". A misnaming on the user side is plausible.

## Current Focus

```yaml
hypothesis: |
  ROOT CAUSE: Basecoat's `.dialog` component class (static/vendor/basecoat/basecoat.css:594)
  applies `opacity-0` by default and only flips to `opacity-100` when the element
  matches `:is([open],:popover-open)` — i.e. when it's an HTML5 <dialog> with the
  [open] attribute or a popover-API element. The settings confirm modal is a plain
  <div role="dialog"> with no [open] attribute, so the .dialog rule made the entire
  overlay invisible while the `fixed inset-0` backdrop kept trapping pointer events.
  The user saw nothing happen, every click was swallowed by the transparent
  backdrop, and the page felt "frozen". A previous accidental Confirm click (or
  Enter keypress while a hidden form input was focused) explains how new values
  reached the DB despite the user never seeing the dialog.
test: |
  - Add regression: assert the modal HTML does NOT include the `dialog` class on
    the role="dialog" element.
  - Run pytest tests/test_settings_form.py to verify all flows still pass.
  - Browser verification: open /settings, edit risk_value, click Save, observe
    that the confirm modal is now visibly rendered and clickable.
expecting: |
  - test_post_valid_renders_modal passes with the new "no .dialog class" assertion
  - All 12 settings_form tests pass
  - User can see the modal in the browser; backdrop click outside the card now
    dismisses (extra safety), and the Save button briefly disables during the
    POST so there is immediate visual feedback even before the modal renders.
next_action: |
  Hand off to user to redeploy the container (CSS rebuild not required — only
  template changes — but a Docker rebuild + restart is) and verify the modal
  appears when clicking Save Changes on /settings.
reasoning_checkpoint: confirmed
tdd_checkpoint: regression-test-added
```

## Evidence

- timestamp: 2026-04-26T16:55:00Z
  type: code_review
  file: dashboard.py:540-861
  finding: |
    Two-step modal flow confirmed. cf591b4 test
    `test_settings_renders_with_space_in_account_name` already covers spaced names.
    `_append_to_response_body` correctly updates Content-Length.
- timestamp: 2026-04-26T17:00:00Z
  type: file_inspection
  file: static/vendor/basecoat/basecoat.min.js
  finding: |
    0 bytes on the developer machine. If the deployed container is also 0 bytes,
    the bridge `if (window.basecoat) { ... }` short-circuits (no error).
    If the deployed file is non-empty (different build), basecoat.init() runs on
    the swap target — could throw on a malformed component. Worth verifying
    the actual deployed asset size.
- timestamp: 2026-04-26T17:05:00Z
  type: code_review
  file: templates/partials/account_settings_tab.html:2
  finding: |
    First-click form has `hx-post="/settings/{{ a.name }}"` — `a.name` is the raw
    account name with space. HTMX 2.0.4 normally URL-encodes the path, but if it
    doesn't (e.g. a CDN-blocked load fell back to a different bundled version),
    uvicorn would reject the request with a 400 before any handler runs.

## Eliminated

- Cache divergence between bot and dashboard processes (single uvicorn worker).
- Content-Length mismatch in OOB-appended responses (cf591b4 fixed via `_append_to_response_body`).
- Slugified vs raw-name selector mismatch (cf591b4 fixed; verified in tests).
- `SettingsStore` write-through correctness (DB write + cache reload are atomic per field).

## Resolution

**Root cause:**
The settings confirm modal (`templates/partials/settings_confirm_modal.html`) used
`<div role="dialog" class="dialog fixed inset-0 ...">`. Basecoat's `.dialog`
component CSS (`static/vendor/basecoat/basecoat.css:594-617`) is designed for the
HTML5 `<dialog>` element or popover-API elements:

```css
.dialog {
  @apply inset-y-0 opacity-0 transition-all transition-discrete;
  &:is([open],:popover-open) {
    @apply opacity-100;
    ...
  }
}
```

Because the modal is a plain `<div>` (not a `<dialog>` element with `[open]`,
nor a popover-API element), the `:is([open],:popover-open)` branch never
matched. The base rule's `opacity-0` made the entire overlay — backdrop AND
inner card — completely invisible, while the `fixed inset-0` backdrop continued
to capture every click. The page appeared frozen.

This was not caught by `test_confirm_fixed_lot_mode_persists` because that test
POSTs directly to `/settings/{name}/confirm`, bypassing the visual modal flow.
The cf591b4 "verified in browser" claim was likely true at the moment of
verification but became invalid as the Phase 7-08 compat-shim removal (267aa50)
exposed the underlying Basecoat .dialog rule.

**Fix (3 changes):**

1. `templates/partials/settings_confirm_modal.html` — removed `dialog` class
   from the modal overlay div. The remaining utilities
   (`fixed inset-0 bg-dark-900/80 flex items-center justify-center z-50`) are
   sufficient to render and position the overlay correctly.

2. Same file — added `onclick="if(event.target===event.currentTarget){…clear modal-root…}"`
   so clicking the backdrop (not the inner card) dismisses the modal — operator
   safety net even if a future regression makes the dialog content invisible
   again.

3. `templates/partials/account_settings_tab.html` and
   `templates/partials/settings_confirm_modal.html` — added
   `hx-disabled-elt="find button[type=submit]"` to the Save and Confirm forms
   so the buttons greys out immediately on click. Operators now get visible
   feedback even on slow connections, and a stuck button is an obvious signal
   that the request never completed.

**Verification:**

- `tests/test_settings_form.py::test_post_valid_renders_modal` updated with a
  regression assertion that `class="dialog"` is NOT present on the
  `role="dialog"` element. All 12 tests pass.
- Browser verification pending — user must rebuild Docker image and restart
  the container (template changes only, no CSS rebuild needed).

**Files changed:**
- templates/partials/settings_confirm_modal.html
- templates/partials/account_settings_tab.html
- tests/test_settings_form.py

