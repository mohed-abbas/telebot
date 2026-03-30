# MT5 Bridge — Wine + RPyC Setup Guide

Complete guide for running MetaTrader 5 on Linux via Wine with RPyC bridge,
enabling the telebot to execute live trades through the MT5 Python API.

## Architecture

```
                         VPS (Ubuntu 22.04)
  ┌──────────────────────────────────────────────────────────────────┐
  │                                                                  │
  │  ┌────────────────────────────────────────┐                      │
  │  │  mt5-bridge (single Docker container)  │                      │
  │  │                                        │                      │
  │  │  ┌──────────────────┐                  │                      │
  │  │  │ Xvfb (:99)       │  (shared)        │                      │
  │  │  │ virtual display   │                  │                      │
  │  │  └────────┬─────────┘                  │                      │
  │  │           │                             │                      │
  │  │  ┌────────▼─────────┐                  │                      │
  │  │  │ x11vnc + noVNC   │  (shared, VNC    │                      │
  │  │  │ :6080            │   toggle)         │                      │
  │  │  └──────────────────┘                  │                      │
  │  │                                        │                      │
  │  │  ┌─── .wine-vantage ──────────────┐    │   ┌──────────────┐  │
  │  │  │  Wine prefix (isolated)        │    │   │  telebot      │  │
  │  │  │  ┌────────────┐ ┌────────────┐ │    │   │              │  │
  │  │  │  │ MT5        │ │ Python 3.9 │ │    │   │  RPyC client │  │
  │  │  │  │ terminal64 │ │ RPyC :18812│◄├────┼───┤  :18812      │  │
  │  │  │  └────────────┘ └────────────┘ │    │   │              │  │
  │  │  └────────────────────────────────┘    │   │              │  │
  │  │                                        │   │              │  │
  │  │  ┌─── .wine-fundednext ───────────┐    │   │              │  │
  │  │  │  Wine prefix (isolated)        │    │   │  RPyC client │  │
  │  │  │  ┌────────────┐ ┌────────────┐ │    │   │  :18813      │  │
  │  │  │  │ MT5        │ │ Python 3.9 │ │    │   │              │  │
  │  │  │  │ terminal64 │ │ RPyC :18813│◄├────┼───┤              │  │
  │  │  │  └────────────┘ └────────────┘ │    │   └──────────────┘  │
  │  │  └────────────────────────────────┘    │                      │
  │  │                                        │   data-net           │
  │  └────────────────────────────────────────┘   (Docker network)   │
  │                                                                  │
  │  ┌──────────────────────────────────────────┐                    │
  │  │  postgres (shared)  |  nginx  |  redis   │                    │
  │  └──────────────────────────────────────────┘                    │
  └──────────────────────────────────────────────────────────────────┘
```

### How the RPyC Bridge Works

```
  Linux side (telebot)              Wine side (mt5-bridge)
  ─────────────────────             ──────────────────────

  from mt5linux                     import MetaTrader5 as mt5
    import MetaTrader5              (Windows .pyd DLL)
         │                                    │
         │  RPyC client                       │  RPyC server
         │  mt5.initialize()                  │  mt5.initialize()
         │  mt5.login(...)                    │  mt5.login(...)
         │  mt5.order_send(...)               │  mt5.order_send(...)
         │                                    │
         └──── TCP :18812 ───────────────────►┘
              (data-net Docker network)

  Every method call on the client side is serialized,
  sent over TCP to the RPyC server, executed inside Wine
  where the real MetaTrader5 DLL communicates with the
  MT5 terminal via named pipes, and the result is sent back.
```

### Why Single Container, Multiple Accounts?

Each MT5 terminal can only be logged into ONE broker account at a time.
You cannot run two accounts on a single terminal. The solution is
isolated Wine prefixes inside a single container:

- **Single container** — reduces overhead (one Xvfb, one noVNC instance)
- **Isolated Wine prefixes** — each account gets its own `.wine-{name}` directory (no cross-contamination)
- **Add/remove accounts via env var** — no new compose service needed, just update `MT5_ACCOUNTS`
- **Shared display** — one noVNC URL (port 6080) for all accounts
- **Dynamic supervisord config** — generated at runtime from `MT5_ACCOUNTS` env var

### Why Separate from Telebot?

| Concern        | Telebot             | MT5 Bridge                  |
|----------------|---------------------|-----------------------------|
| Base image     | python:3.12-slim    | ubuntu:22.04 + Wine (~2GB)  |
| Restart speed  | 2 seconds           | 30-60 seconds (Wine boot)   |
| Update freq    | Frequent (code)     | Rare (only new accounts)    |
| Crash impact   | Signal relay lost    | Only that account affected  |

Combining them would mean every bot code change restarts MT5 (slow),
and a Wine crash would kill signal relay + dashboard.

## Critical Compatibility Notes

### Wine Version (IMPORTANT)

| Wine Version   | MT5 Status                                          |
|----------------|-----------------------------------------------------|
| 6.0 (Ubuntu)   | WORKS — no debugger detection, stable in Docker    |
| 9.x            | Works — need manual .deb install (not in apt)      |
| 10.0-10.2      | Works — if available in WineHQ repo                |
| 10.3+          | BROKEN — triggers "debugger detected" error        |
| 11.x (current) | BROKEN — same debugger detection + init failures   |

**We use Ubuntu 22.04's native Wine 6.0.3** (`apt install wine wine64`).

The "debugger detected" error looks like this in noVNC:
```
"A debugger has been found running in your system.
 Please, unload it from memory and restart your program."
```

This is MT5's anti-tampering system detecting Wine 10.3+'s debug
infrastructure. Wine 6.0 predates this change and works fine.

### Python Version (IMPORTANT)

| Approach                      | Status                                |
|-------------------------------|---------------------------------------|
| Python 3.12 MSI installer     | FAILS — requires Windows 8.1+        |
| Python 3.9 MSI installer      | FAILS — Wine 6.0 can't run MSI       |
| Python 3.9 embeddable ZIP     | WORKS — no installer needed           |

**We use the embeddable Python 3.9.13 ZIP** — just extract and run.

The embeddable package requires extra setup:
1. Extract the ZIP to `C:\Python39\`
2. Edit `python39._pth` — uncomment `#import site` to enable pip
3. Run `get-pip.py` to bootstrap pip
4. Install packages normally with pip

### supervisord Path Escaping

Backslashes (`\`) in supervisord.conf are interpreted as escape characters.

```
# WRONG — supervisord eats the backslashes
command=wine C:\Python39\python.exe
# Result: wine C:Python39python.exe

# CORRECT — use Linux paths (Wine resolves them)
command=wine /root/.wine-vantage/drive_c/Python39/python.exe
```

### MetaTrader5 Python Package Import

The `MetaTrader5` Python package tries to connect to a running MT5
terminal on `import`. If no terminal is running, it hangs indefinitely.

**Never do `import MetaTrader5` in setup/verification scripts.**
Verify with `import rpyc` instead.

## Directory Structure

```
/home/murx/apps/mt5-bridge/          <── On VPS
├── Dockerfile                        # Ubuntu + Wine + Xvfb + noVNC
├── docker-compose.yml                # Single service, multi-account via env var
├── scripts/
│   └── entrypoint.sh                # Per-account Wine init + dynamic supervisord.conf
├── .env                              # VNC toggle
└── .env.example

Note: supervisord.conf is generated dynamically by entrypoint.sh
      at container startup based on the MT5_ACCOUNTS env var.

/home/murx/apps/telebot/             <── Telebot (connects to bridge)
├── accounts.json                     # mt5_host: "mt5-bridge", mt5_port per account
├── .env                              # MT5_BACKEND=mt5linux
└── ...
```

Persistent data is in Docker volumes:
```
mt5-bridge_mt5_vantage_wine          # Wine prefix + MT5 at /root/.wine-vantage
```

Note: If migrating from the old multi-container setup, existing volumes
contain the same data — just mounted at a different path (`/root/.wine-{name}`
instead of `/root/.wine`). You may need to recreate volumes or copy data.

## Setup Guide — Adding a New Account

### Step 1: Update MT5_ACCOUNTS in docker-compose.yml

Edit `/home/murx/apps/mt5-bridge/docker-compose.yml`:

```yaml
services:
  mt5-bridge:
    environment:
      # Add the new account with a unique RPyC port
      MT5_ACCOUNTS: "vantage:18812,newaccount:18813"
```

### Step 2: Add Volume Mount for New Account

```yaml
services:
  mt5-bridge:
    volumes:
      - mt5_vantage_wine:/root/.wine-vantage
      - mt5_newaccount_wine:/root/.wine-newaccount    # New account

volumes:
  mt5_vantage_wine:
  mt5_newaccount_wine:    # New account volume
```

### Step 3: Start (or Recreate) the Container

```bash
cd /home/murx/apps/mt5-bridge

# Enable VNC for setup
echo "ENABLE_VNC=true" > .env

# Recreate with new config
docker compose up -d
```

Wait ~2 minutes for Wine initialization of the new account:

```bash
docker logs mt5-bridge 2>&1 | tail -20
# Look for: "[newaccount] Wine initialization complete!"
```

### Step 4: Install MT5 via noVNC

Set up SSH tunnel from your local machine:
```bash
ssh -L 6080:localhost:6080 murx@your-vps-ip
```

Open `http://localhost:6080/vnc.html` in your browser, click Connect.

Launch the MT5 installer for the new account:
```bash
docker exec -d mt5-bridge bash -c \
  'DISPLAY=:99 WINEPREFIX=/root/.wine-newaccount WINEDEBUG=-all wine /opt/mt5setup.exe'
```

In the noVNC window:
1. Complete the MT5 installation wizard (accept defaults)
2. Click **"Later"** on the update dialog (avoid breaking Wine compat)
3. Log into your broker account:
   - File > Login to Trade Account
   - Enter server, login, password
   - CHECK "Save password" (critical for auto-login on restart)
   - Click OK
4. Go to **Tools > Options > Expert Advisors**:
   - Enable "Allow algorithmic trading"
   - Enable "Allow DLL imports"
5. Close MT5 (File > Exit)

### Step 5: Verify Auto-Restart

After closing MT5, supervisord should restart it within 10-15 seconds.
Check noVNC — the terminal should reappear and auto-login.

Also verify via logs:
```bash
docker logs mt5-bridge 2>&1 | grep -E "RUNNING" | tail -5
# Look for:
#   success: mt5-newaccount entered RUNNING state
#   success: rpyc-newaccount entered RUNNING state
```

Verify RPyC connectivity:
```bash
docker run --rm --network data-net alpine \
  sh -c "timeout 3 nc -z mt5-bridge 18813 && echo 'RPyC OK' || echo 'FAILED'"
```

### Step 6: Disable VNC (Production)

```bash
# Update .env
echo "ENABLE_VNC=false" > /home/murx/apps/mt5-bridge/.env

# Recreate container (picks up new env)
cd /home/murx/apps/mt5-bridge
docker compose up -d
```

### Step 7: Configure Telebot

Add the account to `/home/murx/apps/telebot/accounts.json`:

```json
{
  "name": "New Account Name",
  "server": "BrokerServer-Name",
  "login": 99999999,
  "password_env": "MT5_PASS_3",
  "risk_percent": 1.0,
  "max_lot_size": 0.5,
  "max_daily_loss_percent": 3.0,
  "max_open_trades": 3,
  "enabled": true,
  "mt5_host": "mt5-bridge",
  "mt5_port": 18813
}
```

Add the password to `/home/murx/apps/telebot/.env`:
```
MT5_PASS_3=your_mt5_password_here
```

Update telebot's `.env` to use live trading:
```
MT5_BACKEND=mt5linux
TRADING_DRY_RUN=false    # Only when ready for live!
```

Restart telebot:
```bash
cd /home/murx/apps/telebot
docker compose up -d --force-recreate
```

## Switching from Dry-Run to Live Trading

```
               DRY-RUN MODE                    LIVE MODE
  ┌──────────────────────────┐    ┌──────────────────────────┐
  │  .env:                   │    │  .env:                   │
  │  TRADING_ENABLED=true    │    │  TRADING_ENABLED=true    │
  │  TRADING_DRY_RUN=true    │    │  TRADING_DRY_RUN=false   │
  │  MT5_BACKEND=dry_run     │    │  MT5_BACKEND=mt5linux    │
  │                          │    │                          │
  │  Signal → Parse → Log    │    │  Signal → Parse → MT5    │
  │  (no real orders)        │    │  (real orders placed)    │
  └──────────────────────────┘    └──────────────────────────┘
```

**Checklist before going live:**

- [ ] MT5 bridge container running with `rpyc` in RUNNING state
- [ ] MT5 terminal logged in with saved password
- [ ] `accounts.json` has correct `mt5_host: "mt5-bridge"` and `mt5_port`
- [ ] `MT5_PASS_N` env vars set in telebot's `.env`
- [ ] Test with `TRADING_DRY_RUN=true` + `MT5_BACKEND=mt5linux` first
      (connects to MT5 but logs orders instead of executing)
- [ ] Verify dashboard shows account balance/equity
- [ ] Then set `TRADING_DRY_RUN=false` for live execution

## Broker Safety Notes

### Vantage International (Demo)

- **Risk: VERY LOW** — retail broker, explicitly supports EAs
- Offers free VPS for automation
- No restrictions on Wine/Linux
- Demo account = zero ban risk

### FundedNext (Prop Firm)

- **Risk: MODERATE** — strict rules apply
- EAs are allowed on MT5 but must be customized
- Wine shows in MT5 journal logs (`"on Wine X.X"`)
- **Consider native Windows VPS for funded accounts**

Key limits:
| Rule                         | Limit           |
|------------------------------|-----------------|
| Max trades/day               | 50 (aim <30)    |
| Max simultaneous positions   | 5 (aim <4)      |
| Min hold time                | 15-20s (aim 60+)|
| Max margin usage             | <70% (aim <30%) |

Prohibited: grid trading, latency arbitrage, tick scalping,
cross-account hedging, off-the-shelf challenge-passing EAs.

### Anti-Detection Features (Already Built Into Telebot)

The bot's `accounts.json` global settings provide:
- **Trade stagger**: Random 1-5s delay between accounts
- **Lot jitter**: 4% size variation per account
- **SL/TP jitter**: 0.8 point offset per account
- **Different risk profiles**: Per-account risk_percent

**Recommendation**: Use different magic numbers per account
(currently shared 202603 — update in future).

## Troubleshooting

### "debugger detected" Error in noVNC

**Cause**: Wine version 10.3+ detected by MT5's anti-tampering.
**Fix**: Ensure you're using Wine 6.0 (Ubuntu native), not WineHQ.

Check Wine version inside container:
```bash
docker exec mt5-bridge wine --version
# Should show: wine-6.0.3 (Ubuntu 6.0.3~repack-1)
```

### MT5 Terminal Doesn't Auto-Restart

**Cause**: supervisord path issue or MT5 not installed.
**Fix**: Check supervisord status:
```bash
docker logs mt5-bridge 2>&1 | grep -E "(mt5|RUNNING|FATAL|exited)" | tail -10
```

Verify MT5 is installed:
```bash
docker exec mt5-bridge ls -la "/root/.wine-vantage/drive_c/Program Files/MetaTrader 5/terminal64.exe"
```

Start MT5 manually to test:
```bash
docker exec -d mt5-bridge bash -c \
  'DISPLAY=:99 WINEPREFIX=/root/.wine-vantage wine "/root/.wine-vantage/drive_c/Program Files/MetaTrader 5/terminal64.exe" /portable'
```

### RPyC Server Not Starting

**Cause**: Python not installed or wrong path.
**Fix**: Verify Python:
```bash
docker exec mt5-bridge ls -la /root/.wine-vantage/drive_c/Python39/python.exe
docker exec mt5-bridge bash -c 'DISPLAY=:99 WINEPREFIX=/root/.wine-vantage wine /root/.wine-vantage/drive_c/Python39/python.exe -c "import rpyc; print(rpyc.__version__)"'
```

### RPyC Port Not Reachable from Telebot

**Cause**: Containers not on the same Docker network.
**Fix**: Both must be on `data-net`:
```bash
docker network inspect data-net | grep -E "(mt5|telebot)"
```

### MT5 Not Logged In After Restart

**Cause**: "Save password" was not checked during login.
**Fix**: Enable VNC, connect via noVNC, log in again with "Save password" checked.

```bash
# Enable VNC temporarily
echo "ENABLE_VNC=true" > /home/murx/apps/mt5-bridge/.env
cd /home/murx/apps/mt5-bridge
docker compose up -d
# Connect via SSH tunnel + noVNC, fix login, then disable VNC
```

### Container Uses Too Much RAM

Each MT5 terminal uses ~200-500MB RAM under Wine.
Minimize resource usage:
- Remove unnecessary charts from MT5
- Reduce Market Watch symbol list to only traded instruments
- Lower "Max Bars in Chart" in Tools > Options > Charts

### Wine Initialization Fails on Fresh Volume

**Cause**: Corrupted Wine prefix.
**Fix**: Delete volume and start fresh:
```bash
cd /home/murx/apps/mt5-bridge
docker compose down
docker volume rm mt5-bridge_mt5_ACCOUNTNAME_wine
docker compose up -d
# Then re-install MT5 via noVNC
```

### Python Package Install Fails

**Cause**: Network issue or pip version mismatch.
**Fix**: Re-run initialization:
```bash
# Delete init flag
docker run --rm -v mt5-bridge_mt5_ACCOUNTNAME_wine:/wine alpine rm -f /wine/.initialized

# Restart container (will re-run setup for that account)
cd /home/murx/apps/mt5-bridge
docker compose up -d
docker logs mt5-bridge 2>&1 | tail -30
```

## Resource Usage

### Per MT5 Account

| Resource | Usage                          |
|----------|--------------------------------|
| RAM      | ~200-500MB (Wine + MT5)        |
| CPU      | <5% idle, spikes on ticks      |
| Disk     | ~500MB (Wine prefix + MT5)     |
| Network  | ~1-5MB/day (market data)       |

### Total for 2 Accounts (Single Container)

| Resource | Usage                           |
|----------|---------------------------------|
| RAM      | ~0.8-1.2GB total (shared Xvfb)  |
| CPU      | <10% on 2 cores                 |
| Disk     | ~1.5GB (image) + 1GB (volumes)  |

Single container saves ~100-200MB RAM vs two containers
(shared Xvfb, supervisord, and base OS overhead).

## Container Management Commands

```bash
# Start the MT5 bridge
cd /home/murx/apps/mt5-bridge && docker compose up -d

# View logs
docker logs -f mt5-bridge

# Restart the bridge
docker compose restart mt5-bridge

# Check RPyC per account
docker run --rm --network data-net alpine \
  sh -c "nc -z mt5-bridge 18812 && echo 'vantage OK' || echo 'vantage FAIL'"
docker run --rm --network data-net alpine \
  sh -c "nc -z mt5-bridge 18813 && echo 'fundednext OK' || echo 'fundednext FAIL'"

# Check processes inside container
docker exec mt5-bridge ps aux | grep -E "(terminal|python)"

# Enable VNC for maintenance
echo "ENABLE_VNC=true" > .env
docker compose up -d
# SSH tunnel: ssh -L 6080:localhost:6080 murx@vps
# Browser: http://localhost:6080/vnc.html

# Run command in specific account Wine prefix
docker exec mt5-bridge bash -c 'WINEPREFIX=/root/.wine-vantage wine --version'
```
