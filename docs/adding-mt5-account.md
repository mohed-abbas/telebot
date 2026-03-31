# Adding a New MT5 Account

This guide covers adding a new broker account (e.g., FundedNext) to the mt5-bridge.

## Prerequisites

- mt5-bridge already running with at least one account
- SSH access to VPS
- Broker login credentials for the new account

## Overview

Three things to change, everything else is automated:

| What | Where | Change |
|------|-------|--------|
| `MT5_ACCOUNTS` env | `mt5-bridge/docker-compose.yml` | Add `accountname:port` |
| Volume mount | `mt5-bridge/docker-compose.yml` | Add named volume for Wine prefix |
| Account config | `accounts.json` on VPS | Add entry with `mt5_host`, `mt5_port` |

## Step 1: Update docker-compose.yml

Edit `mt5-bridge/docker-compose.yml` on your local machine.

Add the new account to `MT5_ACCOUNTS` (comma-separated `name:port`), add a volume
mount, and declare the volume:

```yaml
services:
  mt5-bridge:
    environment:
      MT5_ACCOUNTS: "vantage:18812,fundednext:18813"  # add new account here
    volumes:
      - mt5_vantage_wine:/root/.wine-vantage
      - mt5_fundednext_wine:/root/.wine-fundednext     # add volume mount

volumes:
  mt5_vantage_wine:
  mt5_fundednext_wine:   # declare the volume
```

**Port assignment:** Each account needs a unique RPyC port. Use sequential ports
starting from 18812 (18812, 18813, 18814, ...).

## Step 2: Update accounts.json

Add the new account to `accounts.json` on VPS. The `mt5_host` is always `mt5-bridge`
(the Docker container name). The `mt5_port` matches what you set in `MT5_ACCOUNTS`:

```json
{
  "account_name": "FundedNext",
  "mt5_host": "mt5-bridge",
  "mt5_port": 18813,
  "login": 12345678,
  "password_env": "MT5_PASS_FUNDEDNEXT",
  "server": "FundedNext-Server",
  "risk_pct": 1.0,
  "max_positions": 5
}
```

Add the password to the telebot `.env` file:

```env
MT5_PASS_FUNDEDNEXT=your_broker_password
```

## Step 3: Push and Deploy

```bash
# Local: commit and push
git add mt5-bridge/docker-compose.yml
git commit -m "feat: add fundednext account to mt5-bridge"
git push origin main

# VPS: pull and copy to deploy directory
cd /home/murx/apps/telebot
git pull origin main
cp -r mt5-bridge/* /home/murx/apps/mt5-bridge/

# VPS: rebuild mt5-bridge with VNC enabled (new account needs MT5 installed)
cd /home/murx/apps/mt5-bridge
docker compose down
ENABLE_VNC=true docker compose up -d --build

# Clean up build cache
docker builder prune -f
```

## Step 4: Wait for Wine Initialization

The entrypoint automatically detects the new account and initializes its Wine prefix.
This takes 2-5 minutes on first run. Monitor with:

```bash
docker logs -f mt5-bridge
```

You should see:

```
[fundednext] FIRST RUN - Initializing Wine
[fundednext] Installing Python 3.9 (embeddable)...
[fundednext] Installing pip and MT5 packages...
[fundednext] Wine initialization complete!

[fundednext] MT5 NOT INSTALLED - Setup required!
```

The "MT5 NOT INSTALLED" message is expected - you install MT5 in the next step.
VNC is automatically force-enabled when any account is missing MT5.

## Step 5: Install MT5 via noVNC

Open an SSH tunnel to access noVNC:

```bash
ssh -L 6080:localhost:6080 murx@vps
```

Run the MT5 installer targeting the new account's Wine prefix:

```bash
docker exec -d mt5-bridge bash -c \
  'DISPLAY=:99 WINEPREFIX=/root/.wine-fundednext WINEDEBUG=-all wine /opt/mt5setup.exe'
```

Open `http://localhost:6080/vnc.html` in your browser, then:

1. Complete the MT5 installation wizard
2. Log into your broker account
3. **Check "Save password"** (important - MT5 needs to auto-login on restart)
4. Go to Tools > Options > Expert Advisors:
   - Enable **"Allow algorithmic trading"**
   - Enable **"Allow DLL imports"**
5. Close MT5 (supervisord will auto-restart it)

## Step 6: Verify and Disable VNC

Check that all processes are running:

```bash
docker exec mt5-bridge supervisorctl status
```

Expected output:

```
mt5-vantage       RUNNING   pid 19, uptime 0:05:00
rpyc-vantage      RUNNING   pid 20, uptime 0:05:00
mt5-fundednext    RUNNING   pid 21, uptime 0:02:00
rpyc-fundednext   RUNNING   pid 22, uptime 0:02:00
novnc             RUNNING   ...
x11vnc            RUNNING   ...
xvfb              RUNNING   ...
```

Verify RPyC is reachable on the new port:

```bash
docker exec mt5-bridge bash -c 'echo "RPyC CHECK" | timeout 2 bash -c "cat < /dev/tcp/localhost/18813" 2>/dev/null && echo "PORT OPEN" || echo "PORT OPEN"'
```

Disable VNC for production:

```bash
cd /home/murx/apps/mt5-bridge
docker compose down
docker compose up -d
```

## Step 7: Restart Telebot

Restart the telebot so it picks up the new account from `accounts.json`:

```bash
cd /home/murx/apps/telebot
docker compose up -d
```

Check logs to confirm the new account connected:

```bash
docker logs telebot 2>&1 | grep -i fundednext
```

## How It Works Under the Hood

When the container starts, the entrypoint:

1. Parses `MT5_ACCOUNTS` env var (e.g., `"vantage:18812,fundednext:18813"`)
2. For each account, checks if `/root/.wine-{name}/.initialized` exists
3. If not initialized: runs `wineboot`, extracts Python 3.9, installs pip + MetaTrader5 + mt5linux
4. Checks if MT5 terminal is installed in each prefix
5. Generates `/etc/supervisor/conf.d/supervisord.conf` dynamically with:
   - Shared processes: Xvfb, x11vnc, noVNC
   - Per-account processes: `mt5-{name}` (terminal) and `rpyc-{name}` (bridge server)
6. Starts supervisord

Each account is fully isolated via separate Wine prefixes (`/root/.wine-vantage`,
`/root/.wine-fundednext`). They share the same virtual display (`:99`) and noVNC port
(`6080`) but cannot interfere with each other.

## Removing an Account

1. Remove the account from `MT5_ACCOUNTS` in `docker-compose.yml`
2. Remove the volume mount line
3. Remove the volume declaration
4. Remove from `accounts.json` on VPS
5. Rebuild: `docker compose down && docker compose up -d --build`
6. (Optional) Delete the orphaned volume: `docker volume rm mt5-bridge_mt5_accountname_wine`
