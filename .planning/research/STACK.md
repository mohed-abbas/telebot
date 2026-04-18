# Technology Stack — v1.1

**Project:** Telebot v1.1 (staged-entry execution + settings page + shadcn UI + login form)
**Researched:** 2026-04-18
**Scope:** Additions / changes only. The v1.0 core stack (Python 3.12, FastAPI 0.115, asyncpg 0.31, Jinja2 3.1, HTMX 2, Telethon 1.42, PostgreSQL 16, Docker) stays. Nothing is being replaced.
**Overall confidence:** HIGH for UI substrate (multiple primary sources), HIGH for auth deps (PyPI/docs-verified), MEDIUM on Tailwind v3-vs-v4 choice (both viable; we recommend v3 for lower migration risk).

---

## TL;DR — What's Being Added

| Category | Add | Version | Why |
|----------|-----|---------|-----|
| **UI substrate** | `basecoat-css` (vendored) | 0.3.3 | shadcn/ui look & feel with zero JS framework; stays in the HTMX+Jinja model we already have |
| **CSS tooling** | Tailwind CSS **standalone CLI** | v3.4.x (recommended) or v4.1.x | Replace the dev-only `cdn.tailwindcss.com` script currently in `templates/base.html:7` with a built stylesheet — production-required |
| **Password hashing** | `argon2-cffi` | 25.1.0 | Hash the dashboard password at rest; Passlib is unmaintained, direct argon2-cffi is the current idiomatic pick |
| **Session cookies** | `starlette.middleware.sessions.SessionMiddleware` | n/a (already installed) | Signed session cookie for the login form; comes with FastAPI's Starlette. `itsdangerous` is also already transitive |
| **Staged-entry logic** | *(nothing)* | — | Pure in-repo code — new price-monitor loop in `executor.py`, new DB tables; no new dependency |
| **Settings persistence** | *(nothing)* | — | Existing asyncpg + a new `account_settings` table; alembic stays deferred (see DBE-01 tension below) |

Everything else below is explanation and rationale.

---

## 1. Frontend Substrate — the "shadcn with HTMX" question resolved

### Recommended: **Basecoat UI** (`basecoat-css`)

A Tailwind-based, framework-agnostic port of shadcn/ui's visual language and component patterns. "All of the shadcn/ui magic, none of the React." ([basecoatui.com](https://basecoatui.com/), [hunvreus/basecoat](https://github.com/hunvreus/basecoat))

- **Latest release:** v0.3.3 (2025-11-05), MIT license
- **JS requirement:** none for most components; for 6 interactive components (Dropdown Menu, Popover, Select, Sidebar, Tabs, Toast) a small vanilla JS file ships. **Does NOT require Alpine.js, React, or Vue.** Verified against install docs and dropdown component docs.
- **Install for our stack:** include `basecoat.css` (vendored or CDN) and the JS module for any interactive components used, and import `basecoat-css` into the Tailwind input CSS file. No npm runtime, no build tool beyond Tailwind CLI.
- **Component surface:** 40+ components including everything we need (button, card, form, input, select, dialog, table, tabs, toast, sidebar, dropdown-menu, alert-dialog, command/combobox, badge).

### Why this over the alternatives

| Option | Verdict | Reason |
|--------|---------|--------|
| **(A) Basecoat UI on existing HTMX + Jinja** | **Chosen** | Keeps Jinja/HTMX substrate; no SPA; minimal JS; shadcn aesthetic the user asked for; actively maintained |
| **(B) Basic Components (basicmachines-co)** | Rejected | **Archived 2026-04-05, read-only** — dead upstream. Also requires JinjaX (we're on plain Jinja2) and Alpine.js |
| **(C) SPA rewrite (Vue/Nuxt or React/Next)** | Rejected | Violates "minimize new dependencies" (v1.0 constraint); introduces a build toolchain, a second container, CORS/auth plumbing, and weeks of integration for a dashboard that's read-heavy and already works well with HTMX |
| **(D) daisyUI / Franken UI / Park UI** | Rejected | Fine libraries, but the user explicitly asked for shadcn. Their design tokens/classnames diverge from shadcn, which breaks the `/frontend-design` workflow that expects shadcn conventions |
| **(E) Vanilla Tailwind + hand-rolled components** | Rejected | Duplicates what Basecoat does for free and gives up shadcn visual parity |

### Maturity disclaimer

Basecoat is **pre-1.0 (v0.3.3)**. It's the right choice because every alternative is worse (Basic Components is dead, SPA violates scope, everything else isn't shadcn), but we should:
- Pin to an **exact** version (`basecoat-css@0.3.3`), not `@latest`.
- **Vendor** the CSS + JS files into `static/` rather than hot-loading from jsDelivr so a CDN outage doesn't brick the dashboard (matches the v1.0 discipline around HTMX — we already pin `htmx.org@2.0.4`).
- Treat Basecoat CSS as a starting layer; hand-write Tailwind freely for anything missing. This is the shadcn philosophy anyway — copy, don't depend.

Sources: [Basecoat home](https://basecoatui.com/), [Basecoat install](https://basecoatui.com/installation/), [Basecoat GitHub](https://github.com/hunvreus/basecoat), [Show HN discussion](https://news.ycombinator.com/item?id=43971688), [Basic Components GitHub (archived)](https://github.com/basicmachines-co/basic-components), [Basic Components docs](https://components.basicmachines.co/docs/introduction), [htmx.org endorsement on X](https://x.com/htmx_org/status/1920526787710497263).

---

## 2. Tailwind CSS — a production blocker in v1.0 that v1.1 must fix

### Current state (a liability, not "already handled")

`templates/base.html:7` loads Tailwind via the Play CDN:

```html
<script src="https://cdn.tailwindcss.com"></script>
```

Tailwind labels this **development-only** — it JIT-compiles classes in the browser on every request, doesn't include the full feature set, and has no reasonable caching. Any v1.1 work layering Basecoat on top of this compounds the debt. **v1.1 MUST replace this** — it is not optional.

### Recommendation: Tailwind **v3.4.x standalone CLI** (preferred), or v4.1.x

| Choice | Pros | Cons |
|--------|------|------|
| **v3.4 standalone CLI** (recommended) | Minimal migration — existing Tailwind classes in templates keep working; no `@theme` rewrite; stable and widely known; standalone binary = no node_modules | Older engine; no Oxide speed gains |
| **v4.1 standalone CLI** | 5× faster builds, CSS-first `@theme`, modern | Breaking changes: `@tailwind` → `@import "tailwindcss"`, `bg-gradient-to-*` → `bg-linear-to-*`, default border color changed, browser floor is Safari 16.4 / Chrome 111 / Firefox 128; more moving parts during an already-large UI phase |

**Recommendation:** Ship v1.1 on **Tailwind v3.4 standalone CLI**. The v1.1 scope is already "redesign the UI + add features"; stacking a v4 migration on top widens the blast radius for no immediate runtime benefit. Plan a focused v1.2 migration using Tailwind's official `@tailwindcss/upgrade` codemod.

### Integration in Docker

Add a build stage to `Dockerfile`:

1. Download the standalone CLI binary for linux/amd64 into the image (no Node.js).
2. Run `tailwindcss -i static/css/input.css -o static/css/app.css --minify` against the templates.
3. Serve `static/css/app.css` via the existing `StaticFiles` mount at `/static`.

This keeps the runtime image Python-only. `npm`, `node`, `package.json`, `package-lock.json` should **not** appear. The existing `drizzle.config.json` at the repo root appears to be stray (drizzle is a JS ORM unused by this project) and should be deleted in this phase.

Sources: [Tailwind standalone CLI blog](https://tailwindcss.com/blog/standalone-cli), [Tailwind standalone CLI beginner tutorial](https://github.com/tailwindlabs/tailwindcss/discussions/15855), [Tailwind v4 upgrade guide](https://tailwindcss.com/docs/upgrade-guide), [Tailwind v4 migration summary](https://medium.com/@mernstackdevbykevin/tailwind-css-v4-0-complete-migration-guide-breaking-changes-you-need-to-know-7f99944a9f95).

---

## 3. Login Form — replacing HTTP Basic

### Recommended: `SessionMiddleware` + `argon2-cffi`

The current dashboard uses FastAPI's `HTTPBasic` (`dashboard.py:33,47-64`). Browser basic-auth prompts are ugly, can't be themed with the UI, and can't log out cleanly. Replace with a signed-cookie session and a real HTML login form.

### Components

| Piece | Library | Version | Notes |
|-------|---------|---------|-------|
| Signed session cookie | `starlette.middleware.sessions.SessionMiddleware` | ships with Starlette 0.x (already transitive via FastAPI 0.115) | Set `https_only=True`, `same_site="lax"`, `max_age=` (e.g. 8h) |
| Signing backend | `itsdangerous` | already transitive via Starlette | Nothing to add — Starlette uses it under the hood |
| Password hash | **`argon2-cffi`** | **25.1.0** | Verify `DASHBOARD_PASS_HASH` against submitted password on login; never store plaintext after init |
| CSRF | existing `_verify_csrf` (checks `hx-request`) | — | Keep it; login POST uses `hx-post` so the header is set automatically |

### Why argon2-cffi, not Passlib

Passlib is the historical Python umbrella for password hashing, **but**:
- Last release was 2020; maintainers have been seeking a replacement for years.
- It raises deprecation warnings on `crypt` that turn into breakages on Python 3.13.
- We're on 3.12 today, but 3.13 is the near-term default; adopting a dead library for a 2026 milestone is the wrong trajectory.

`argon2-cffi` (v25.1.0, published Nov 2025) is actively maintained by Hynek Schlawack, supports Python 3.13/3.14 officially, ships platform wheels via `argon2-cffi-bindings`, and exposes exactly the API we need:

```python
from argon2 import PasswordHasher
ph = PasswordHasher()
hash_ = ph.hash(plaintext)              # at setup-time, to produce env var value
ph.verify(hash_, submitted_password)    # at login; raises on mismatch
ph.check_needs_rehash(hash_)            # for future parameter tuning
```

### What NOT to add

- **`fastapi-users`** / **`fastapi-login`** / **`authlib`** — overkill for a single-admin dashboard. We're not managing user registration, OAuth flows, JWT rotation, password reset, or multi-tenant identity. A single env-var-driven admin with a signed session cookie is adequate and matches v1.0's "one admin" model, just with better UX.
- **`python-jose`**, JWT libraries — session cookies are simpler, safer (server-side secret, no client-held claims), and revocable by rotating the secret.
- **`fastapi-csrf-protect`** — we already have HTMX-header-based CSRF in `_verify_csrf`; extending it to the login POST is a one-line change.

### Config additions (env)

| Var | Purpose |
|-----|---------|
| `DASHBOARD_PASS_HASH` (new) | Argon2 hash of the admin password, generated by a small helper script |
| `SESSION_SECRET` (new, required) | ≥32 bytes random; bot fails to start if unset (matches `SEC-02` discipline) |

Keep `DASHBOARD_PASS` for one release as a fallback that is auto-upgraded to the hashed form on first successful login, then remove.

Sources: [FastAPI cookie docs](https://fastapi.tiangolo.com/advanced/response-cookies/), [Starlette middleware docs](https://starlette.dev/middleware/), [argon2-cffi 25.1.0 docs](https://argon2-cffi.readthedocs.io/), [argon2-cffi PyPI](https://pypi.org/project/argon2-cffi/), [Passlib maintenance issue](https://github.com/pypi/warehouse/issues/15454).

---

## 4. Staged-Entry Execution — no new stack

The orchestrator flagged staged-entry as an open stack question. After reading `executor.py`, `trade_manager.py`, `risk_calculator.py`, and `models.py`: **no new Python dependencies are needed.**

What's already in place we'll reuse:
- `Executor._heartbeat_loop` and `Executor._cleanup_loop` patterns (asyncio.Tasks with cancellation) — add a `_zone_watch_loop` in the same style for price monitoring of follow-up zones.
- `trade_manager.determine_order_type` already handles "price in zone → market; else limit at mid" — staged entry is a generalisation: split the lot across N stages, open one immediately, queue the rest on price-in-zone events.
- `risk_calculator.calculate_lot_size` already accepts risk-percent; adding a fixed-lot mode is a ~10-line change (new branch: if `risk_mode == "fixed"`, return `min(acct.fixed_lot, max_lot)`).

New code (not new deps):
- `AccountSettings` dataclass in `models.py` with `risk_mode: Literal["percent", "fixed"]`, `fixed_lot: float`, `max_stages: int`, `stage_allocation: list[float]`.
- DB table `account_settings` (one row per account, overrides `accounts.json` at runtime).
- DB table `staged_entries` to track pending stages per signal (`signal_id`, `account`, `stage_number`, `status`, `target_zone_low`, `target_zone_high`, `triggered_at`).
- Zone watcher loop polls MT5 prices on a cadence (e.g. 10s) and fills queued stages when price enters the zone; reuses the existing stale-signal and daily-limit checks.

Sources: in-tree code (`executor.py`, `trade_manager.py`, `risk_calculator.py`, `models.py`).

---

## 5. Per-Account Settings Page — no new stack

UI: a new Jinja template + HTMX forms that POST to new `/api/settings/{account}` endpoints, exactly like the existing `modify_sl` / `modify_tp` / `close_partial` endpoints in `dashboard.py:224-299`.

Persistence: the new `account_settings` table (see §4). Load at startup, write on form submit. Settings override `accounts.json` (which becomes the bootstrap/default layer). On container restart, DB wins — `accounts.json` is now a one-time seed.

No new dependencies.

### Schema-migration tooling tension (flag for roadmap)

v1.0 `REQUIREMENTS.md` explicitly lists **DBE-01 alembic** as a v2 item. v1.1 introduces at least two new tables (`account_settings`, `staged_entries`). Options:

1. **Stay on the v1.0 pattern** — hand-write DDL in `db.py init_schema()` guarded by `CREATE TABLE IF NOT EXISTS`. This is what v1.0 did for all its tables. Cheap, zero new tooling, acceptable for small schema additions. **Recommended for v1.1.**
2. **Promote DBE-01 into v1.1** — introduce alembic mid-milestone. Correct long-term but adds a migration-authoring workflow mid-milestone.

**Recommendation:** Option 1 for v1.1. Promote DBE-01 to v1.2 as a focused data-layer milestone once we have 3–4 tables added this round. The orchestrator should flag this as a v1.2 candidate.

---

## Dependency Delta Summary

### `requirements.txt` additions

```
argon2-cffi==25.1.0
```

That is the only new Python runtime package. `itsdangerous` and `starlette` are already transitive via FastAPI.

### `requirements-dev.txt` additions

None.

### Build toolchain additions (not Python)

- Tailwind v3.4 standalone CLI binary (downloaded in Dockerfile, no npm).
- Vendored Basecoat CSS + JS files in `static/` (no package manager needed — the v0.3.3 release ships drop-in files from jsDelivr).

### Files to delete / clean up

- `drizzle.config.json` at repo root — stray JS ORM config, unrelated to this Python project.

---

## Installation Cheat Sheet (for the roadmap's phase plans)

```bash
# Python side
pip install argon2-cffi==25.1.0
```

Dockerfile additions (illustrative, final placement to be decided in phase plan):

```dockerfile
# Tailwind standalone CLI — no Node.js required
RUN curl -sL -o /usr/local/bin/tailwindcss \
      https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-linux-x64 \
 && chmod +x /usr/local/bin/tailwindcss

# At build time, compile the stylesheet
RUN tailwindcss -i static/css/input.css -o static/css/app.css --minify
```

Vendor Basecoat into the repo (one-time, checked in):

```bash
curl -sL -o static/css/basecoat.css \
  https://cdn.jsdelivr.net/npm/basecoat-css@0.3.3/dist/basecoat.css
curl -sL -o static/js/basecoat.min.js \
  https://cdn.jsdelivr.net/npm/basecoat-css@0.3.3/dist/js/all.min.js
```

Input CSS file (`static/css/input.css`):

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

/* Basecoat provides shadcn-style CSS variables and component primitives */
@import "./basecoat.css";
```

---

## Confidence Assessment

| Area | Level | Basis |
|------|-------|-------|
| Basecoat as substrate choice | HIGH | Verified license, version, JS deps against primary sources (GitHub, install docs, component docs) |
| Basic Components rejection | HIGH | Archive status confirmed in upstream GitHub |
| argon2-cffi over Passlib | HIGH | Release dates and maintenance issue are primary-source verified |
| Tailwind v3 vs v4 choice | MEDIUM | Both are supportable; v3 recommended for migration-risk reduction, but v4 is workable for a team comfortable with the breaking changes |
| Staged-entry "no new deps" | HIGH | Read the existing executor/trade_manager; the pattern slots in cleanly |
| Login via SessionMiddleware | HIGH | Primary Starlette/FastAPI docs |

## Gaps / Open Questions for Later Phases

- **Tailwind v3 vs v4 final call** — a one-line decision the user/orchestrator should confirm before the UI phase starts; no downstream research needed.
- **Whether to promote DBE-01 (alembic) into v1.1** — scope call, not research.
- **Password-hash migration path** — one-shot "first login writes the hash" vs. an out-of-band `hash-password` CLI script. Implementation detail for the login phase.

---

*Stack research defined: 2026-04-18 for milestone v1.1.*
