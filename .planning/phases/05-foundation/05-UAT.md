---
status: complete
phase: 05-foundation
source: [05-01-SUMMARY.md, 05-02-SUMMARY.md, 05-03-SUMMARY.md, 05-04-SUMMARY.md]
started: 2026-04-19T13:53:14Z
updated: 2026-04-19T15:10:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Cold Start Smoke Test
expected: Kill any running telebot container/process. Start from scratch (docker compose up -d telebot OR python bot.py with valid .env). Server boots without FATAL errors, SettingsStore loads, accounts seed from accounts.json idempotently, and the dashboard becomes reachable (e.g., http://localhost:8080/health returns OK).
result: pass
notes: "Required pre-flight fixes before boot succeeded: (1) created docker network proxy-net (compose expects external, absent locally); (2) remapped host port 8080→8090 due to devdock-caddy collision; (3) escaped `$`→`$$` in DASHBOARD_PASS_HASH within .env.dev — docker-compose interpolates `$` in env_file values and was eating most of the argon2 hash; (4) regenerated TG_SESSION for dev to avoid AuthKeyDuplicatedError against VPS. Phase 5 cutover itself booted cleanly once env was correct — SettingsStore and dashboard came up. Fail-fast validators (missing SESSION_SECRET, missing hash) fired as designed along the way, providing implicit proof of Test 7."

### 2. Redirect to Login When Unauthenticated
expected: In a fresh browser (no session cookie), visit any dashboard page (e.g., http://localhost:8080/ or /overview). Server responds with 303 redirect to /login. Landing on /login renders the login form.
result: pass

### 3. Login Page Renders with Basecoat Styling
expected: /login shows a styled card-based form with a password input and "Sign In" button. No raw/unstyled HTML, no 404s on CSS (app.{hash}.css loads from /static/css/). No reference to cdn.tailwindcss.com in page source. Dark theme applied.
result: issue
reported: "yes it showed the login page but UI is so bad."
severity: major
notes: "Initially classified cosmetic, upgraded to major after Test 4 diagnostic. Compiled app.css (11134B) contains ZERO Basecoat rules and ZERO compat-shim rules. Integration appeared to work (page 200, hashed link, manifest resolved) but the bundle is missing content. Login form is rendering bare HTML wrapped in Tailwind utilities. See Gap #1 for root cause."

### 4. Wrong Password Shows Error Banner
expected: Submit /login with an incorrect password. Page re-renders with a red "Invalid credentials" alert banner (Basecoat alert-destructive). A fresh CSRF token cookie is issued so the form is immediately retryable. No session cookie set.
result: issue
reported: "it shows the message but there is no styling on the text just pure plain text."
severity: major
notes: "Server-side logic works — error message is rendered server-side and returned. Styling is missing because `.alert alert-destructive` classes are not defined in the compiled CSS. Same root cause as Test 3. See Gap #1."

### 5. Correct Password Logs In
expected: Submit /login with the correct password (the plaintext used when generating DASHBOARD_PASS_HASH). Server sets telebot_session cookie and 303-redirects to / (or next path). Visiting / now renders the authenticated dashboard — sidebar, overview, positions, etc.
result: pass

### 6. Sign Out Link in Sidebar
expected: Authenticated view shows a "Sign out" link in the base.html sidebar. Clicking it hits /logout, clears the session, and lands back on /login. Subsequently visiting / again redirects to /login (session truly cleared).
result: pass

### 7. Config Fail-Fast on Misconfiguration
expected: With DASHBOARD_PASS_HASH removed (or DASHBOARD_PASS plaintext left in .env), the bot refuses to start with a FATAL log line pointing at the missing/malformed env var. No silent fallback. (Skip if you don't want to disturb a running deployment.)
result: pass
notes: "Implicitly confirmed during Test 1 setup. Observed two distinct FATAL messages along the way: (a) 'Missing SESSION_SECRET' when SESSION_SECRET was absent from .env.dev; (b) 'DASHBOARD_PASS_HASH missing or malformed' when the hash was present but mangled by docker-compose `$` interpolation. Both triggered SystemExit before any app code ran — no silent fallback."

### 8. Rate-Limit Lockout After Failed Attempts
expected: Submit /login with 5 consecutive wrong passwords from the same client. The 6th attempt (still wrong) returns "Too many failed attempts" (app-level 429/lockout) instead of "Invalid credentials". A subsequent successful login (after window or manual clear) resets the counter. Skip if this is disruptive to verify live.
result: pass

## Summary

total: 8
passed: 6
issues: 2
pending: 0
skipped: 0
blocked: 0

## Gaps

- truth: "Compiled app.css includes both the v1.0 compat-shim rules and Basecoat primitives so templates render as designed."
  status: failed
  reason: "User reported in tests 3 and 4: UI is bare and alert banners render as plain text — Basecoat classes (.alert-destructive, .card, .card-header, .card-body, .btn-primary, .input, .label) and compat-shim classes (.nav-active, .card, .btn, .profit, .loss, .badge-*, .btn-red/blue/green) are absent from the compiled app.css."
  severity: major
  test: [3, 4]
  root_cause: |
    scripts/build_css.sh uses the Tailwind v3.4.19 standalone CLI which does NOT resolve CSS @import directives (only processes @tailwind, @apply, @layer). static/css/input.css has `@import "./_compat.css"` and `@import "../vendor/basecoat/basecoat.css"` — both are silently dropped. Diagnostic evidence:
      - curl of served compiled CSS grepped for .alert-destructive, .btn-primary, .card-header, .card-body, .input, .label → 0 matches.
      - Same grep for .nav-active, .btn-red/blue/green, .profit, .loss, .badge-* → 0 matches.
      - static/vendor/basecoat/basecoat.css on disk contains .alert-destructive (grep count 2), confirming source is fine.
      - Compiled CSS size 11134B is consistent with pure Tailwind preflight + minimal purged utilities only.
      - base.html emits a single `<link>` to the hashed app.css plus a `<script>` for basecoat.min.js (interactive JS only — does NOT inject Basecoat CSS).
  artifacts:
    - path: scripts/build_css.sh
      issue: "Invokes tailwindcss standalone CLI against input.css without any @import-resolution step; imported CSS files never reach the output."
    - path: static/css/input.css
      issue: "Relies on @import statements that the standalone Tailwind CLI does not process."
    - path: templates/base.html
      issue: "Loads only the compiled app.css — compat-shim + Basecoat rules are therefore absent at runtime even though template classes reference them."
    - path: templates/login.html
      issue: "Uses Basecoat primitives (.card, .card-header, .card-body, .alert-destructive, .btn-primary, .input, .label) that resolve to no styles."
  missing:
    - "An @import-resolution step in the CSS build pipeline (e.g. preprocess input.css by inlining the contents of _compat.css and basecoat.css before piping to tailwindcss CLI; or add a second <link> tag in base.html pointing at /static/vendor/basecoat/basecoat.css)."
    - "A build-time or startup assertion that .alert-destructive (or another known Basecoat class) is present in the compiled CSS, so this regression is caught before release."
    - "tests/test_ui_substrate.py check that compiled app.{hash}.css contains the marker class, not only that the file exists."
