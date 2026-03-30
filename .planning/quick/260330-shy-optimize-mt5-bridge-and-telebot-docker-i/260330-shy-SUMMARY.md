---
phase: quick
plan: 01
subsystem: infra
tags: [docker, wine, mt5, supervisord, multi-account]

requires: []
provides:
  - Single-container multi-account MT5 bridge architecture
  - Dynamic supervisord.conf generation from MT5_ACCOUNTS env var
  - Optimized telebot Docker image excluding test/dev files
affects: [deployment, mt5-bridge]

tech-stack:
  added: []
  patterns:
    - "Multi-account Wine prefixes in single container via MT5_ACCOUNTS env var"
    - "Dynamic supervisord.conf generation at container startup"
    - "Per-account priority offsets in supervisord (30+N*10, 40+N*10)"

key-files:
  created: []
  modified:
    - mt5-bridge/Dockerfile
    - mt5-bridge/scripts/entrypoint.sh
    - mt5-bridge/docker-compose.yml
    - mt5-bridge/MT5_BRIDGE_GUIDE.md
    - Dockerfile
    - .dockerignore

key-decisions:
  - "Single container with isolated Wine prefixes per account instead of one container per account"
  - "ENABLE_VNC defaults to false (production), auto-enabled when any MT5 install is missing"
  - "supervisord.conf generated dynamically at runtime, static file deleted from repo"
  - "Kept cabextract, xz-utils, wget in image; only purged software-properties-common and gnupg2"

patterns-established:
  - "MT5_ACCOUNTS env var format: name:port,name:port for account configuration"
  - "Wine prefix path convention: /root/.wine-{name}"

requirements-completed: []

duration: 4min
completed: 2026-03-30
---

# Quick Task 260330-shy: MT5 Bridge Multi-Account + Docker Optimization Summary

**Single-container multi-account MT5 bridge with dynamic supervisord.conf, plus optimized telebot Dockerfile excluding dev/test files**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-30T18:34:45Z
- **Completed:** 2026-03-30T18:39:00Z
- **Tasks:** 3
- **Files modified:** 6 (plus 1 deleted)

## Accomplishments
- Consolidated mt5-bridge from multi-container (one per account) to single-container architecture with isolated Wine prefixes
- Entrypoint.sh now parses MT5_ACCOUNTS env var, initializes per-account Wine prefixes, and generates supervisord.conf dynamically
- Merged 3 Dockerfile RUN layers into 1, removed hardcoded single-account assumptions (WINEPREFIX, RPYC_PORT, VOLUME)
- Optimized telebot Dockerfile by removing unnecessary COPY lines (nginx/, docs/) and expanding .dockerignore

## Task Commits

Each task was committed atomically:

1. **Task 1: Refactor mt5-bridge to single-container multi-account architecture** - `1149d67` (feat)
2. **Task 2: Optimize telebot Dockerfile and .dockerignore** - `fdc32a7` (chore)
3. **Task 3: Update MT5_BRIDGE_GUIDE.md for multi-account single-container architecture** - `02b15b0` (docs)

## Files Created/Modified
- `mt5-bridge/Dockerfile` - Single merged apt-get layer, no hardcoded per-account ENVs, ENABLE_VNC defaults false
- `mt5-bridge/scripts/entrypoint.sh` - Parses MT5_ACCOUNTS, per-account Wine init loop, dynamic supervisord.conf generation
- `mt5-bridge/docker-compose.yml` - Single mt5-bridge service with MT5_ACCOUNTS env var
- `mt5-bridge/supervisord.conf` - DELETED (now generated at runtime)
- `mt5-bridge/MT5_BRIDGE_GUIDE.md` - Updated architecture diagram, setup guide, and commands for single-container approach
- `Dockerfile` - Removed COPY nginx/ and COPY docs/ lines
- `.dockerignore` - Added tests/, mt5-bridge/, *.example, docker-compose*.yml, requirements-dev.txt, .planning/

## Decisions Made
- Kept cabextract and xz-utils in the image (needed by Wine for fonts); only purged software-properties-common and gnupg2 as build-only packages
- Kept wget in the image for debugging convenience
- ENABLE_VNC defaults to false for production; entrypoint auto-enables when any account is missing MT5 installation
- Priority numbering: shared procs at 10/20/25, per-account at 30+offset/40+offset (increment by 10 per account)
- wineserver --wait after each wine command in init to avoid race conditions

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. Deployment-time verification (building the Docker image and running with MT5_ACCOUNTS) is needed to confirm the container works end-to-end.

## Known Stubs

None - all files contain complete, production-ready configurations.

## Self-Check: PASSED

All 6 modified files confirmed present. Deleted file (supervisord.conf) confirmed absent. All 3 task commits verified in git log.

---
*Quick task: 260330-shy*
*Completed: 2026-03-30*
