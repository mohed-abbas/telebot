---
phase: quick
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - mt5-bridge/Dockerfile
  - mt5-bridge/scripts/entrypoint.sh
  - mt5-bridge/docker-compose.yml
  - mt5-bridge/MT5_BRIDGE_GUIDE.md
  - Dockerfile
  - .dockerignore
autonomous: true
requirements: []

must_haves:
  truths:
    - "mt5-bridge runs as single container serving multiple MT5 accounts"
    - "Each account gets isolated Wine prefix, MT5 terminal, and RPyC server"
    - "supervisord.conf is generated dynamically at runtime from MT5_ACCOUNTS env var"
    - "Static supervisord.conf no longer exists in the repo"
    - "Telebot Docker image excludes test files, mt5-bridge dir, docs, and nginx"
  artifacts:
    - path: "mt5-bridge/Dockerfile"
      provides: "Optimized single-layer Docker image without hardcoded single-account env vars"
    - path: "mt5-bridge/scripts/entrypoint.sh"
      provides: "Multi-account Wine init loop and dynamic supervisord.conf generation"
    - path: "mt5-bridge/docker-compose.yml"
      provides: "Single-service multi-account compose config"
    - path: "mt5-bridge/MT5_BRIDGE_GUIDE.md"
      provides: "Updated documentation reflecting multi-account single-container architecture"
    - path: "Dockerfile"
      provides: "Cleaned telebot Dockerfile without unnecessary COPY lines"
    - path: ".dockerignore"
      provides: "Extended ignore list excluding tests, mt5-bridge, dev files, planning"
  key_links:
    - from: "mt5-bridge/scripts/entrypoint.sh"
      to: "MT5_ACCOUNTS env var"
      via: "Parsing name:port,name:port format to loop init and generate supervisord.conf"
    - from: "mt5-bridge/docker-compose.yml"
      to: "mt5-bridge/scripts/entrypoint.sh"
      via: "MT5_ACCOUNTS env var and per-account volume mounts"
---

<objective>
Refactor mt5-bridge from multi-container single-account to single-container multi-account architecture, optimize both Docker images.

Purpose: Reduce resource overhead (one container instead of N), simplify account management (env var instead of new compose service), and shrink telebot image by excluding unnecessary files.
Output: Optimized Dockerfile and entrypoint for mt5-bridge with dynamic multi-account support, cleaned telebot Dockerfile and .dockerignore.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@mt5-bridge/Dockerfile
@mt5-bridge/scripts/entrypoint.sh
@mt5-bridge/supervisord.conf
@mt5-bridge/docker-compose.yml
@mt5-bridge/MT5_BRIDGE_GUIDE.md
@Dockerfile
@.dockerignore
</context>

<tasks>

<task type="auto">
  <name>Task 1: Refactor mt5-bridge to single-container multi-account architecture</name>
  <files>mt5-bridge/Dockerfile, mt5-bridge/scripts/entrypoint.sh, mt5-bridge/docker-compose.yml, mt5-bridge/supervisord.conf</files>
  <action>
**mt5-bridge/Dockerfile** — Merge and optimize:
- Merge all 3 RUN apt-get layers into a single RUN layer:
  - Combine system deps, wine install (dpkg --add-architecture i386, apt-get update, install wine wine64), and download step into one layer
  - Include `unzip` in the main apt-get install list (currently in the download layer)
  - After downloads complete, purge build-only packages: `apt-get purge -y --auto-remove software-properties-common gnupg2`
  - Single `rm -rf /var/lib/apt/lists/*` at end
- Remove these ENV lines: `ENV WINEPREFIX=/root/.wine` (per-account), `ENV RPYC_PORT=18812` (per-account)
- Remove `VOLUME ["/root/.wine"]` (volumes defined per-account in compose)
- Remove `COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf` (generated at runtime)
- Remove `EXPOSE 18812` — keep only `EXPOSE 6080` for noVNC
- Change `ENV ENABLE_VNC=true` to `ENV ENABLE_VNC=false` (production default)
- Keep: `ENV DEBIAN_FRONTEND=noninteractive`, `ENV DISPLAY=:99`, `ENV WINEARCH=win64`, `ENV WINEDLLOVERRIDES=...`
- Keep: `COPY scripts/ /scripts/`, `RUN chmod +x /scripts/*.sh`, `ENTRYPOINT ["/scripts/entrypoint.sh"]`

**mt5-bridge/scripts/entrypoint.sh** — Rewrite for multi-account:
- Parse `MT5_ACCOUNTS` env var (format: "name:port,name:port,...", default: "default:18812")
- Print startup banner listing all accounts and their RPyC ports
- Start Xvfb for Wine init (same as current)
- Loop through each account entry parsed from MT5_ACCOUNTS:
  - Set WINEPREFIX="/root/.wine-{name}" for this iteration
  - If `/root/.wine-{name}/.initialized` does not exist:
    - Run wineboot --init with WINEDEBUG=-all (same fallback logic as current)
    - Extract Python 3.9 embeddable to /root/.wine-{name}/drive_c/Python39
    - Enable site-packages in python39._pth
    - Install pip via get-pip.py, then install MetaTrader5 mt5linux packages
    - Verify with rpyc import check
    - Touch /root/.wine-{name}/.initialized
  - Check for MT5 at "/root/.wine-{name}/drive_c/Program Files/MetaTrader 5/terminal64.exe"
  - If missing, print setup instructions with correct WINEPREFIX path and docker exec command referencing the account name
  - If ANY account is missing MT5, force ENABLE_VNC=true
- Generate /etc/supervisor/conf.d/supervisord.conf DYNAMICALLY:
  - Write [supervisord] section (nodaemon=true, logfile, pidfile)
  - Write shared [program:xvfb] section (always on, priority=10)
  - Write shared [program:x11vnc] section (autostart=$ENABLE_VNC, priority=20)
  - Write shared [program:novnc] section (autostart=$ENABLE_VNC, priority=25)
  - For each account "{name}:{port}" in MT5_ACCOUNTS:
    - Write [program:mt5-{name}] — command=wine "/root/.wine-{name}/drive_c/Program Files/MetaTrader 5/terminal64.exe" /portable, environment=DISPLAY=":99",WINEPREFIX="/root/.wine-{name}", priority=30, autorestart=true, startsecs=10, startretries=5
    - Write [program:rpyc-{name}] — command=wine /root/.wine-{name}/drive_c/Python39/python.exe -m mt5linux --host 0.0.0.0 -p {port}, environment=DISPLAY=":99",WINEPREFIX="/root/.wine-{name}", priority=40, autorestart=true, startsecs=15, startretries=10
    - Both get stdout/stderr to /dev/stdout and /dev/stderr with maxbytes=0
- Kill init-time Xvfb (same as current: kill $(cat /tmp/.X99-lock))
- exec supervisord with generated config

**mt5-bridge/docker-compose.yml** — Single service:
- Replace two services (mt5-vantage, mt5-fundednext) with ONE `mt5-bridge` service
- container_name: mt5-bridge
- build: .
- restart: unless-stopped
- environment:
  - MT5_ACCOUNTS: "vantage:18812"  (single account example, add more with comma)
  - ENABLE_VNC: "${ENABLE_VNC:-false}"
- volumes:
  - mt5_vantage_wine:/root/.wine-vantage
  - Comment showing: # mt5_other_wine:/root/.wine-other  (add per account)
- ports:
  - "6080:6080"  (single noVNC port, shared display)
- networks: [data-net]
- logging: json-file, max-size 10m, max-file 3
- volumes section: mt5_vantage_wine (comment showing how to add more)
- networks section: data-net external
- Add comments showing how to add fundednext: MT5_ACCOUNTS: "vantage:18812,fundednext:18813", additional volume mount, additional volume declaration

**mt5-bridge/supervisord.conf** — DELETE this file (git rm).
  </action>
  <verify>
    <automated>cd /Users/murx/Developer/personal/telebot && test ! -f mt5-bridge/supervisord.conf && grep -q "MT5_ACCOUNTS" mt5-bridge/scripts/entrypoint.sh && grep -q "MT5_ACCOUNTS" mt5-bridge/docker-compose.yml && ! grep -q "VOLUME" mt5-bridge/Dockerfile && ! grep -q "RPYC_PORT" mt5-bridge/Dockerfile && ! grep -q "supervisord.conf" mt5-bridge/Dockerfile && echo "PASS" || echo "FAIL"</automated>
  </verify>
  <done>
- mt5-bridge/Dockerfile has single merged apt-get layer, no WINEPREFIX/RPYC_PORT/VOLUME/EXPOSE 18812, no supervisord.conf COPY, ENABLE_VNC defaults to false
- mt5-bridge/scripts/entrypoint.sh parses MT5_ACCOUNTS, loops per-account Wine init, generates supervisord.conf dynamically
- mt5-bridge/docker-compose.yml has single mt5-bridge service with MT5_ACCOUNTS env var
- mt5-bridge/supervisord.conf is deleted
  </done>
</task>

<task type="auto">
  <name>Task 2: Optimize telebot Dockerfile and .dockerignore</name>
  <files>Dockerfile, .dockerignore</files>
  <action>
**.dockerignore** — Add these entries (keep existing ones):
- tests/
- mt5-bridge/
- *.example
- docker-compose*.yml
- requirements-dev.txt
- .planning/

**Dockerfile** — Remove unnecessary COPY lines:
- Remove `COPY nginx/ ./nginx/` (nginx config is on host/reverse proxy, not needed in bot container)
- Remove `COPY docs/ ./docs/` (documentation not needed at runtime)
- Keep all other COPY lines as-is
  </action>
  <verify>
    <automated>cd /Users/murx/Developer/personal/telebot && ! grep -q "COPY nginx/" Dockerfile && ! grep -q "COPY docs/" Dockerfile && grep -q "tests/" .dockerignore && grep -q "mt5-bridge/" .dockerignore && grep -q ".planning/" .dockerignore && echo "PASS" || echo "FAIL"</automated>
  </verify>
  <done>
- Dockerfile no longer copies nginx/ or docs/ into the image
- .dockerignore excludes tests/, mt5-bridge/, *.example, docker-compose*.yml, requirements-dev.txt, .planning/
  </done>
</task>

<task type="auto">
  <name>Task 3: Update MT5_BRIDGE_GUIDE.md for multi-account single-container architecture</name>
  <files>mt5-bridge/MT5_BRIDGE_GUIDE.md</files>
  <action>
Update the guide to reflect the new architecture:

**Architecture diagram** — Replace the diagram showing two separate containers (mt5-vantage, mt5-fundednext) with a single mt5-bridge container containing multiple Wine prefixes. Show:
- One container with Xvfb (shared), x11vnc/novnc (shared, VNC toggle)
- Per-account: Wine prefix (.wine-vantage), MT5 terminal, RPyC server on unique port
- Telebot connecting to mt5-bridge:18812, mt5-bridge:18813, etc.

**"Why Separate Containers?" section** — Rename to "Why Single Container, Multiple Accounts?" and update rationale:
- Single container reduces overhead (one Xvfb, one noVNC instance)
- Each account still gets isolated Wine prefix (no cross-contamination)
- Add/remove accounts via env var change, no new compose service needed
- Shared display means one noVNC URL for all accounts

**"Adding a New Account" section** — Rewrite completely:
- Step 1: Update MT5_ACCOUNTS env var in docker-compose.yml (e.g., "vantage:18812,newaccount:18813")
- Step 2: Add volume mount for new account (mt5_newaccount_wine:/root/.wine-newaccount)
- Step 3: Add volume declaration
- Step 4: docker compose up -d (rebuilds with new config)
- Step 5: Wait for Wine init, install MT5 via noVNC (same noVNC port 6080 for all)
- Step 6: docker exec command uses container name mt5-bridge with WINEPREFIX=/root/.wine-newaccount
- Step 7: Configure telebot accounts.json (mt5_host stays "mt5-bridge", mt5_port is the new port)

**Directory Structure** — Update:
- Remove supervisord.conf from listing (generated at runtime)
- Note that supervisord.conf is generated dynamically by entrypoint.sh

**Persistent data** — Update volume names to reflect new mount paths:
- mt5-bridge_mt5_vantage_wine mounted at /root/.wine-vantage
- Note about migration: existing volumes contain same data, just mounted at different path

**Container Management Commands** — Update:
- All commands reference `mt5-bridge` (single container name) instead of per-account names
- docker exec commands need WINEPREFIX=/root/.wine-{name} set explicitly
- RPyC check uses mt5-bridge hostname with account-specific port

**Troubleshooting** — Update docker exec examples to use mt5-bridge container name and explicit WINEPREFIX
  </action>
  <verify>
    <automated>cd /Users/murx/Developer/personal/telebot && grep -q "MT5_ACCOUNTS" mt5-bridge/MT5_BRIDGE_GUIDE.md && grep -q ".wine-vantage" mt5-bridge/MT5_BRIDGE_GUIDE.md && ! grep -q "mt5-fundednext" mt5-bridge/MT5_BRIDGE_GUIDE.md && echo "PASS" || echo "FAIL"</automated>
  </verify>
  <done>
- Architecture diagram shows single container with multiple Wine prefixes
- "Adding a New Account" section reflects env var approach (not new compose service)
- All commands reference mt5-bridge container name
- Volume paths use /root/.wine-{name} convention
- No references to old per-container architecture (mt5-fundednext as separate service)
  </done>
</task>

</tasks>

<verification>
All changes are configuration/documentation — no runtime code to test automatically beyond file content checks. Full verification requires building the Docker image and running with MT5_ACCOUNTS, which is a deployment-time check.

Quick structural verification:
- mt5-bridge/Dockerfile: single apt-get RUN, no hardcoded single-account ENVs
- mt5-bridge/scripts/entrypoint.sh: parses MT5_ACCOUNTS, generates supervisord.conf
- mt5-bridge/docker-compose.yml: single service, MT5_ACCOUNTS env var
- mt5-bridge/supervisord.conf: deleted
- Dockerfile: no nginx/ or docs/ COPY
- .dockerignore: excludes tests/, mt5-bridge/, .planning/
</verification>

<success_criteria>
1. mt5-bridge uses single-container multi-account architecture driven by MT5_ACCOUNTS env var
2. Dockerfile has single optimized apt-get layer, no single-account assumptions
3. supervisord.conf is generated dynamically at runtime (static file deleted)
4. Telebot Docker image excludes unnecessary files (nginx/, docs/, tests/, mt5-bridge/)
5. MT5_BRIDGE_GUIDE.md accurately documents the new architecture
</success_criteria>

<output>
After completion, create `.planning/quick/260330-shy-optimize-mt5-bridge-and-telebot-docker-i/260330-shy-SUMMARY.md`
</output>
