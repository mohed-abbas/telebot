---
id: SEED-001
status: dormant
planted: 2026-04-20
planted_during: Phase 06 — staged-entry-execution (under review)
trigger_when: Phase 7 discuss-phase runs (Dashboard redesign milestone)
scope: Medium
---

# SEED-001: Settings page UX polish — toasts, inline help, copywriting

## Why This Matters

Operator feedback during Phase 6 SET-03 live dev testing:

> "Really bad UI with no visual presentation, no toasts/notifications, and nothing clear about what each setting does."

Phase 6 shipped the data contract, server-side validation, two-step dangerous-change modal, and audit timeline. **The logic works; the operator-facing presentation does not.** An operator new to the system cannot edit settings confidently because:

1. **No feedback on save** — Successful `/settings/{account}/confirm` POST returns modal HTML but no success toast. The operator has to re-read the audit timeline to confirm their change landed.
2. **No feedback on validation errors** — Hard-cap rejections render inside the tab but are easy to miss; an explicit toast would surface errors at the viewport level.
3. **No inline help** — Fields like `risk_mode`, `risk_value`, `max_stages`, `default_sl_pips`, `max_daily_trades` have no tooltip, help text, or recommended-range hint. The operator must read source code or guess.
4. **Copywriting is engineer-speak** — Labels match DB column names, not operator mental models. "Risk Value" could be "Per-trade risk (% of balance)" with units.

This is not a safety bug — Phase 6 enforces hard caps server-side — but it is a **trust bug**: operators who can't interpret a form won't trust the bot with real money.

## When to Surface

**Trigger:** When `/gsd-discuss-phase 7` runs for the Dashboard redesign milestone.

This seed should be presented during `/gsd-new-milestone` or `/gsd-discuss-phase` when the milestone/phase scope matches any of these conditions:
- Phase 7 (Dashboard redesign) is being planned
- Any phase that restyles or adds form surfaces on Basecoat
- Any phase addressing dashboard UX or operator onboarding

Phase 7's existing SC #1 already covers "every dashboard view is rendered with Basecoat components" — but does NOT explicitly call out toasts, help text, or copywriting. This seed ensures those three items are folded into Phase 7 scope explicitly rather than silently dropped.

## Scope Estimate

**Medium** — warrants its own plan inside Phase 7 (suggested slug: `07-0X-settings-ux-polish`).

Three distinct pieces of work:
1. **Toast primitive** (Basecoat provides `basecoat/toast.html`) — wire into HTMX response swap pattern so POST handlers can trigger toasts from server. Feedback target: save success, validation rejection, revert confirmation.
2. **Inline help / tooltips** — per-field help text living next to each input. Describe what the field controls, its units, its recommended range, and its footgun (e.g., "max_stages=10 with high risk_value=3% can put 30% of balance at risk on a single bad signal").
3. **Copywriting pass** — rewrite labels, placeholders, and confirmation modal text for operator legibility. Consider a glossary block on the settings page.

Estimated effort: 1 plan, 3 tasks, roughly 1–2 days for a careful pass including visual review.

## Breadcrumbs

Related code and decisions from current codebase:

- `dashboard.py:480-499` — `settings_page` renders settings.html with no toast scaffolding
- `dashboard.py:631-726` — `settings_validate` / `settings_confirm` / `settings_revert` POST handlers return partial HTML; no `HX-Trigger` header for toast events
- `dashboard.py:520` — `validate_settings_form` hard-cap ranges (source of truth for help-text recommended ranges)
- `templates/settings.html` — base settings page; has inline `onclick` tab JS (IN-05 in code review)
- `templates/partials/account_settings_tab.html` — per-account form; no help text, no tooltips
- `templates/partials/settings_confirm_modal.html` — two-step dangerous-change modal (copy: "This applies to signals received AFTER you confirm")
- `templates/partials/settings_audit_timeline.html` — audit trail; revert button triggers modal
- `.planning/phases/06-staged-entry-execution/06-REVIEW.md` — Code review IN-05 flags the inline onclick tab JS as violating Basecoat conventions
- `.planning/phases/06-staged-entry-execution/06-UI-SPEC.md` — original SET-03 design contract (used by executor); does not specify toasts or help text
- `.planning/phases/06-staged-entry-execution/06-HUMAN-UAT.md` — carries the "applies to future signals only" verification test
- `static/basecoat/` — Basecoat vendored components; `toast.html` primitive exists but is not wired into SET-03

## Notes

- **Relation to Phase 7 SC #1:** Phase 7 already promises to restyle every view on Basecoat. This seed adds three concrete deliverables that are likely to be overlooked otherwise.
- **Relation to Phase 6 HUMAN-UAT:** Test #6 (settings form validates hard caps and applies only to future signals) is gated on the operator being able to read the form. The current UI makes this UAT awkward; polishing settings UX will also make HUMAN-UAT #6 less painful to execute.
- **Post-VPS UAT decision:** Operator's plan is to complete Phase 7 first, then do full VPS test with real data + demo accounts. Settings UX polish inside Phase 7 will improve the quality of that VPS UAT session.
- **Not blocking:** Phase 6 code is functionally complete; Phase 7 can proceed directly without gap-closing Phase 6.
