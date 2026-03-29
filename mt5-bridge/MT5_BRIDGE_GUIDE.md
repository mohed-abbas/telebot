# MT5 Bridge — Wine + RPyC Setup Guide

Complete guide for running MetaTrader 5 on Linux via Wine with RPyC bridge,
enabling the telebot to execute live trades through the MT5 Python API.

## Architecture

```
                         VPS (Ubuntu 22.04)
  ┌──────────────────────────────────────────────────────────────────┐
  │                                                                  │
  │  ┌─────────────────────┐     ┌──────────────────────────────┐   │
  │  │  mt5-vantage         │     │  telebot                     │   │
  │  │  (Docker container)  │     │  (Docker container)          │   │
  │  │                      │     │                              │   │
  │  │  ┌────────────────┐  │     │  bot.py                      │   │
  │  │  │ Xvfb (:99)     │  │     │    │                         │   │
  │  │  │ virtual display │  │     │    ▼                         │   │
  │  │  └───────┬────────┘  │     │  MT5LinuxConnector           │   │
  │  │          │            │     │    │ from mt5linux            │   │
  │  │  ┌───────▼────────┐  │     │    │ import MetaTrader5       │   │
  │  │  │ Wine 6.0       │  │     │    │                         │   │
  │  │  │ ┌────────────┐ │  │     │    │ RPyC client             │   │
  │  │  │ │ MT5        │ │  │     │    │ (pure Python)           │   │
  │  │  │ │ terminal64 │ │  │     └────┼─────────────────────────┘   │
  │  │  │ │ .exe       │ │  │          │                             │
  │  │  │ └──────┬─────┘ │  │          │                             │
  │  │  │        │        │  │          │                             │
  │  │  │ ┌──────▼─────┐ │  │          │                             │
  │  │  │ │ Python 3.9 │ │  │          │ TCP :18812                  │
  │  │  │ │ RPyC server│◄├──┼──────────┘                             │
  │  │  │ │ :18812     │ │  │    data-net (Docker network)           │
  │  │  │ └────────────┘ │  │                                        │
  │  │  └────────────────┘  │                                        │
  │  └─────────────────────┘                                         │
  │                                                                  │
  │  ┌─────────────────────┐     ┌──────────────────────────────┐   │
  │  │  mt5-fundednext      │     │  postgres (shared)           │   │
  │  │  (same setup,        │     │  nginx    (shared)           │   │
  │  │   different account) │     │  redis    (shared)           │   │
  │  └─────────────────────┘     └──────────────────────────────┘   │
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

### Why Separate Containers?

Each MT5 terminal can only be logged into ONE broker account at a time.
You cannot run two accounts on a single terminal. Therefore:

- **One container per account** — complete isolation
- **Independent restarts** — updating one account doesn't affect others
- **Separate Wine prefixes** — different MT5 configs per broker
- **Same Docker image** — only volumes differ

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
command=wine /root/.wine/drive_c/Python39/python.exe
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
├── docker-compose.yml                # One service per MT5 account
├── supervisord.conf                  # Process management
├── scripts/
│   └── entrypoint.sh                # First-run init + supervisord
├── .env                              # VNC toggle per account
└── .env.example

/home/murx/apps/telebot/             <── Telebot (connects to bridges)
├── accounts.json                     # mt5_host per account
├── .env                              # MT5_BACKEND=mt5linux
└── ...
```

Persistent data is in Docker volumes:
```
mt5-bridge_mt5_vantage_wine          # Wine prefix + MT5 install
mt5-bridge_mt5_fundednext_wine       # Wine prefix + MT5 install
```

## Setup Guide — Adding a New Account

### Step 1: Add Service to docker-compose.yml

Edit `/home/murx/apps/mt5-bridge/docker-compose.yml`:

```yaml
services:
  # ... existing services ...

  mt5-newaccount:
    build: .
    container_name: mt5-newaccount
    restart: unless-stopped
    environment:
      RPYC_PORT: "18812"
      ENABLE_VNC: "${ENABLE_VNC_NEWACCOUNT:-false}"
    volumes:
      - mt5_newaccount_wine:/root/.wine
    ports:
      - "6082:6080"    # noVNC — unique port per account
    networks:
      - data-net
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

volumes:
  # ... existing volumes ...
  mt5_newaccount_wine:
```

Port assignment for noVNC (only needed during setup):
- Account 1: `6080:6080`
- Account 2: `6081:6080`
- Account 3: `6082:6080`
- etc.

### Step 2: Enable VNC and Start Container

```bash
# Add VNC toggle to .env
echo "ENABLE_VNC_NEWACCOUNT=true" >> /home/murx/apps/mt5-bridge/.env

# Start only the new container (others keep running)
cd /home/murx/apps/mt5-bridge
docker compose up -d mt5-newaccount
```

Wait ~2 minutes for Wine initialization + Python install:

```bash
docker logs mt5-newaccount 2>&1 | tail -10
# Look for: "Wine initialization complete!"
```

### Step 3: Install MT5 via noVNC

Set up SSH tunnel from your local machine:
```bash
ssh -L 6082:localhost:6082 murx@your-vps-ip
```

Open `http://localhost:6082/vnc.html` in your browser, click Connect.

Launch the MT5 installer:
```bash
docker exec -d mt5-newaccount bash -c "DISPLAY=:99 WINEDEBUG=-all wine /opt/mt5setup.exe"
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

### Step 4: Verify Auto-Restart

After closing MT5, supervisord should restart it within 10-15 seconds.
Check noVNC — the terminal should reappear and auto-login.

Also verify via logs:
```bash
docker logs mt5-newaccount 2>&1 | grep -E "RUNNING" | tail -5
# Look for:
#   success: mt5 entered RUNNING state
#   success: rpyc entered RUNNING state
```

Verify RPyC connectivity:
```bash
docker run --rm --network data-net alpine \
  sh -c "timeout 3 nc -z mt5-newaccount 18812 && echo 'RPyC OK' || echo 'FAILED'"
```

### Step 5: Disable VNC (Production)

```bash
# Update .env
sed -i 's/ENABLE_VNC_NEWACCOUNT=true/ENABLE_VNC_NEWACCOUNT=false/' \
  /home/murx/apps/mt5-bridge/.env

# Recreate container (picks up new env)
cd /home/murx/apps/mt5-bridge
docker compose up -d mt5-newaccount

# Optionally remove the noVNC port mapping from docker-compose.yml
```

### Step 6: Configure Telebot

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
  "mt5_host": "mt5-newaccount",
  "mt5_port": 18812
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
- [ ] `accounts.json` has correct `mt5_host` and `mt5_port`
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
docker exec mt5-vantage wine --version
# Should show: wine-6.0.3 (Ubuntu 6.0.3~repack-1)
```

### MT5 Terminal Doesn't Auto-Restart

**Cause**: supervisord path issue or MT5 not installed.
**Fix**: Check supervisord status:
```bash
docker logs mt5-vantage 2>&1 | grep -E "(mt5|RUNNING|FATAL|exited)" | tail -10
```

Verify MT5 is installed:
```bash
docker exec mt5-vantage ls -la "/root/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"
```

Start MT5 manually to test:
```bash
docker exec -d mt5-vantage bash -c \
  'DISPLAY=:99 WINEPREFIX=/root/.wine wine "C:/Program Files/MetaTrader 5/terminal64.exe" /portable'
```

### RPyC Server Not Starting

**Cause**: Python not installed or wrong path.
**Fix**: Verify Python:
```bash
docker exec mt5-vantage ls -la /root/.wine/drive_c/Python39/python.exe
docker exec mt5-vantage bash -c 'DISPLAY=:99 wine /root/.wine/drive_c/Python39/python.exe -c "import rpyc; print(rpyc.__version__)"'
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
sed -i 's/ENABLE_VNC_VANTAGE=false/ENABLE_VNC_VANTAGE=true/' \
  /home/murx/apps/mt5-bridge/.env
cd /home/murx/apps/mt5-bridge
docker compose up -d mt5-vantage
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
docker compose up -d mt5-ACCOUNTNAME
# Then re-install MT5 via noVNC
```

### Python Package Install Fails

**Cause**: Network issue or pip version mismatch.
**Fix**: Re-run initialization:
```bash
# Delete init flag
docker run --rm -v mt5-bridge_mt5_ACCOUNTNAME_wine:/wine alpine rm -f /wine/.initialized

# Restart container (will re-run Python setup)
cd /home/murx/apps/mt5-bridge
docker compose up -d mt5-ACCOUNTNAME
docker logs mt5-ACCOUNTNAME 2>&1 | tail -30
```

## Resource Usage

### Per MT5 Account

| Resource | Usage                          |
|----------|--------------------------------|
| RAM      | ~200-500MB (Wine + MT5)        |
| CPU      | <5% idle, spikes on ticks      |
| Disk     | ~500MB (Wine prefix + MT5)     |
| Network  | ~1-5MB/day (market data)       |

### Total for 2 Accounts

| Resource | Usage                          |
|----------|--------------------------------|
| RAM      | ~1-1.5GB total                 |
| CPU      | <10% on 2 cores                |
| Disk     | ~1.5GB (image) + 1GB (volumes) |

## Container Management Commands

```bash
# Start all MT5 bridges
cd /home/murx/apps/mt5-bridge && docker compose up -d

# Start specific account only
docker compose up -d mt5-vantage

# View logs
docker logs -f mt5-vantage
docker logs -f mt5-fundednext

# Restart specific account
docker compose restart mt5-vantage

# Check if RPyC is reachable
docker run --rm --network data-net alpine \
  sh -c "nc -z mt5-vantage 18812 && echo OK || echo FAIL"

# Check processes inside container
docker exec mt5-vantage ps aux | grep -E "(terminal|python)"

# Enable VNC for maintenance
sed -i 's/ENABLE_VNC_VANTAGE=false/ENABLE_VNC_VANTAGE=true/' .env
docker compose up -d mt5-vantage
# SSH tunnel: ssh -L 6080:localhost:6080 murx@vps
# Browser: http://localhost:6080/vnc.html
```
