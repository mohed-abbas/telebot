# VPS Deployment Guide — Telebot Trading System

Complete step-by-step guide to deploy the Telegram signal auto-execution bot on your Hostinger VPS.

---

## Prerequisites

- Hostinger VPS with SSH access
- Ubuntu 22.04+ (or Debian 12+)
- Domain name (optional, for HTTPS dashboard)
- FundedNext MT5 account credentials
- Discord server with 3 channels (#signals, #executions, #alerts)
- Telegram API credentials (already have from current setup)

---

## Phase 1: VPS Initial Setup

### 1.1 SSH into your VPS

```bash
ssh root@YOUR_VPS_IP
```

### 1.2 Create a non-root user (if not done already)

```bash
adduser telebot
usermod -aG sudo telebot
su - telebot
```

### 1.3 Update system packages

```bash
sudo apt update && sudo apt upgrade -y
```

### 1.4 Install Docker and Docker Compose

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh

# Add your user to docker group (avoids needing sudo for docker)
sudo usermod -aG docker $USER

# Log out and back in for group change to take effect
exit
ssh telebot@YOUR_VPS_IP

# Verify
docker --version
docker compose version
```

### 1.5 Install essential tools

```bash
sudo apt install -y git ufw fail2ban htop
```

### 1.6 Configure firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 8080/tcp   # Dashboard (or 443 if using Nginx)
sudo ufw enable
sudo ufw status
```

---

## Phase 2: Clone and Configure

### 2.1 Clone the repository

```bash
cd ~
git clone https://github.com/mohed-abbas/telebot.git
cd telebot
```

### 2.2 Create the data directory

```bash
mkdir -p data
```

### 2.3 Create accounts.json

```bash
cp accounts.example.json accounts.json
nano accounts.json
```

Edit with your actual FundedNext account details:

```json
{
  "accounts": [
    {
      "name": "FN-6k",
      "server": "FundedNext-Server",
      "login": YOUR_MT5_LOGIN,
      "password_env": "MT5_PASS_1",
      "risk_percent": 1.0,
      "max_lot_size": 0.5,
      "max_daily_loss_percent": 3.0,
      "max_open_trades": 3,
      "enabled": true
    }
  ],
  "global": {
    "default_target_tp": 2,
    "limit_order_expiry_minutes": 30,
    "max_daily_trades_per_account": 30,
    "max_daily_server_messages": 500,
    "stagger_delay_min": 1.0,
    "stagger_delay_max": 5.0,
    "lot_jitter_percent": 4.0,
    "sl_tp_jitter_points": 0.8
  }
}
```

**Finding your FundedNext MT5 details:**
- Login to FundedNext dashboard → My Accounts → click your account
- MT5 Server: usually `FundedNext-Server` or `FundedNext-Server 2`
- Login: your MT5 account number
- Password: your MT5 investor or trading password

### 2.4 Create Discord webhooks

In your Discord server:
1. Create channel `#signals` → Settings → Integrations → Webhooks → New Webhook → Copy URL
2. Create channel `#executions` → same process → Copy URL
3. Create channel `#alerts` → same process → Copy URL

### 2.5 Create the .env file

```bash
cp .env.example .env
nano .env
```

Fill in ALL values:

```bash
# ── Telegram (copy from your existing .env) ──
TG_API_ID=your_api_id
TG_API_HASH=your_api_hash
TG_SESSION=your_session_string
TG_CHAT_IDS=-100xxxxxxxxxx,-100xxxxxxxxxx

# ── Discord Webhooks ──
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxxx/xxxx
DISCORD_WEBHOOK_EXECUTIONS=https://discord.com/api/webhooks/xxxx/xxxx
DISCORD_WEBHOOK_ALERTS=https://discord.com/api/webhooks/xxxx/xxxx

# ── General ──
TIMEZONE=Europe/Berlin

# ── Trading ──
TRADING_ENABLED=true
TRADING_DRY_RUN=true          # START WITH DRY-RUN!
MT5_BACKEND=dry_run            # Start with dry_run
MT5_HOST=localhost
MT5_PORT=18812
ACCOUNTS_CONFIG=accounts.json
DB_PATH=data/telebot.db

# ── Dashboard (Phase 5 auth — styled /login + argon2 + sessions) ──
DASHBOARD_ENABLED=true
DASHBOARD_PORT=8080
DASHBOARD_PASS_HASH=$argon2id$v=19$m=65536,t=3,p=4$...    # Generate via scripts/hash_password.py
SESSION_SECRET=...                                         # Generate via: openssl rand -base64 48
SESSION_COOKIE_SECURE=true                                 # set to false only for local HTTP dev

# ── MT5 Passwords ──
MT5_PASS_1=your_mt5_password
# MT5_PASS_2=second_account_password
# MT5_PASS_3=third_account_password
```

**IMPORTANT: Start with `TRADING_DRY_RUN=true` and `MT5_BACKEND=dry_run` first!**

---

## Phase 5 auth migration (v1.1)

The dashboard replaces HTTPBasic with a styled login form backed by argon2 + Starlette sessions.
Hard cutover — the bot refuses to start if plaintext `DASHBOARD_PASS` is still set.

**On the VPS (or any machine with the new image pulled):**

```bash
# 1. Generate the argon2 hash (interactive — type password twice):
docker run --rm -it <image-tag> python scripts/hash_password.py
# Copy the `DASHBOARD_PASS_HASH=$argon2id$...` line it prints.

# 2. Edit /home/murx/apps/telebot/.env:
#    - REMOVE: DASHBOARD_USER=...   (silently ignored if left; remove anyway)
#    - REMOVE: DASHBOARD_PASS=...   (bot refuses to start if present)
#    - ADD:    DASHBOARD_PASS_HASH=$argon2id$v=19$m=65536,t=3,p=4$...
#    - ADD:    SESSION_SECRET=$(openssl rand -base64 48)
#    - ADD:    SESSION_COOKIE_SECURE=true     # prod only; leave false for local HTTP

# 3. Install the nginx rate-limit snippet (optional but recommended):
cp nginx/limit_req_zones.conf /home/murx/shared/nginx/conf.d/limit_req_zones.conf
cp nginx/telebot.conf          /home/murx/shared/nginx/conf.d/telebot.conf
docker exec shared-nginx nginx -t && docker exec shared-nginx nginx -s reload

# 4. Redeploy:
docker compose up -d telebot
docker logs -f telebot | head -30   # should NOT show FATAL; should show
                                    # "SettingsStore loaded N account(s)" and dashboard startup
```

Visit `https://dashboard.YOURDOMAIN.com/login` — enter the plaintext password you chose in step 1.

---

## Phase 3: Deploy with Docker

### 3.1 Build and start

```bash
docker compose up -d --build
```

### 3.2 Check logs

```bash
# Follow live logs
docker logs -f telebot

# You should see:
# Trading ENABLED (DRY-RUN) — X account(s) configured
# Dashboard running on http://0.0.0.0:8080
# Bot started. Listening to X chat(s)
```

### 3.3 Verify the dashboard

Open in browser: `http://YOUR_VPS_IP:8080`

Visit `/login` and enter the plaintext password matching `DASHBOARD_PASS_HASH`
(see the Phase 5 auth migration section below for hash generation).

You should see:
- Overview page with account cards (showing simulated $10,000 balance in dry-run)
- Empty positions table
- Navigation working between all pages

### 3.4 Verify signal parsing

Send a test signal in one of your monitored Telegram groups (or wait for a real one).

Check:
- `#signals` Discord channel: raw message relayed (existing behavior)
- Dashboard → Signal Log: parsed signal appears
- Docker logs: `Signal detected: PARSED SIGNAL: SELL XAUUSD | Zone: ...`

In dry-run mode, you'll see `[DRY-RUN]` log entries showing what WOULD be executed.

---

## Phase 4: Go Live (when ready)

### 4.1 Validate dry-run results

Run in dry-run mode for at least **3-5 days**. Check:
- [ ] All signals from your Telegram group are correctly parsed
- [ ] Zone detection is working (market vs limit decisions make sense)
- [ ] Stale signals are correctly skipped
- [ ] Lot sizes are reasonable for your account sizes
- [ ] No false positives (random messages not parsed as signals)
- [ ] Dashboard shows all activity correctly
- [ ] Discord #executions and #alerts channels receiving messages

### 4.2 Set up MT5 connection

You have two options:

**Option A: mt5linux (free, runs on your VPS)**

This requires running MT5 in Wine. Add to your docker-compose.yml or run separately:

```bash
# This is complex — you need Wine + MT5 terminal + RPyC server.
# If this proves too difficult, use Option B instead.
```

**Option B: Windows VPS for MT5 (recommended, ~$10/month)**

1. Rent a cheap Windows VPS (e.g., Contabo, Hetzner)
2. Install MT5 terminal
3. Install Python 3.12 + `mt5linux` server component
4. Configure it to accept RPyC connections from your Hostinger VPS IP
5. Update `.env`:
   ```
   MT5_BACKEND=mt5linux
   MT5_HOST=YOUR_WINDOWS_VPS_IP
   MT5_PORT=18812
   ```

**Option C: MetaAPI (easiest, $30+/month)**

1. Sign up at metaapi.cloud
2. Add your FundedNext MT5 account
3. Get API token
4. (Requires adding MetaAPI backend to mt5_connector.py — not yet implemented)

### 4.3 Switch to live trading

**On a CHALLENGE account first, NOT a funded account:**

```bash
# Edit .env
nano .env

# Change these:
TRADING_DRY_RUN=false
MT5_BACKEND=mt5linux

# Restart
docker compose up -d --build
```

### 4.4 Monitor closely

For the first week:
- Watch every signal execution in `#executions`
- Check dashboard positions after each signal
- Verify lot sizes, SL/TP values are correct
- Check FundedNext dashboard for any warnings

### 4.5 Scale to funded accounts

Only after successful challenge account testing:
1. Add funded account credentials to `accounts.json`
2. Set appropriate risk % (lower for funded: 0.5-1%)
3. Restart: `docker compose up -d --build`

---

## Phase 5: Secure the Dashboard (HTTPS)

### 5.1 Option A: Nginx reverse proxy with Let's Encrypt (if you have a domain)

```bash
sudo apt install -y nginx certbot python3-certbot-nginx

# Create Nginx config
sudo nano /etc/nginx/sites-available/telebot
```

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE support
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/telebot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

# Get SSL certificate
sudo certbot --nginx -d your-domain.com

# Update firewall
sudo ufw allow 443/tcp
sudo ufw delete allow 8080/tcp
```

### 5.2 Option B: IP-restricted access (no domain needed)

If no domain, restrict dashboard to your IP only:

```bash
sudo ufw delete allow 8080/tcp
sudo ufw allow from YOUR_HOME_IP to any port 8080
```

---

## Phase 6: Monitoring and Maintenance

### 6.1 Useful commands

```bash
# View logs
docker logs -f telebot
docker logs --tail 100 telebot

# Restart bot
docker compose restart

# Rebuild after code changes
git pull
docker compose up -d --build

# Check resource usage
docker stats telebot

# Check database size
ls -lh data/telebot.db

# Enter container for debugging
docker exec -it telebot bash
```

### 6.2 Set up automatic updates

```bash
# Create update script
cat > ~/update-telebot.sh << 'SCRIPT'
#!/bin/bash
cd ~/telebot
git pull
docker compose up -d --build
echo "Updated at $(date)"
SCRIPT
chmod +x ~/update-telebot.sh
```

### 6.3 Monitor VPS health

```bash
# Install simple uptime monitoring
sudo apt install -y monit

# Or use a free service like UptimeRobot to ping your dashboard URL
```

### 6.4 Log rotation

Already configured in `docker-compose.yml` (10MB x 3 files). No action needed.

### 6.5 Database maintenance

The SQLite database will grow over time. To check and vacuum:

```bash
docker exec telebot python3 -c "
import sqlite3
conn = sqlite3.connect('data/telebot.db')
# Check size
cursor = conn.execute('SELECT COUNT(*) FROM trades')
print(f'Total trades: {cursor.fetchone()[0]}')
cursor = conn.execute('SELECT COUNT(*) FROM signals')
print(f'Total signals: {cursor.fetchone()[0]}')
conn.execute('VACUUM')
print('Database vacuumed')
conn.close()
"
```

---

## Troubleshooting

### Bot not starting
```bash
docker logs telebot 2>&1 | head -50
# Check for missing env vars or config errors
```

### Dashboard not accessible
```bash
# Check if port is open
sudo ufw status
# Check if container is running
docker ps
# Check if dashboard started
docker logs telebot 2>&1 | grep -i dashboard
```

### Signals not being parsed
```bash
# Check logs for signal detection
docker logs telebot 2>&1 | grep -i "signal"
# Look for parser errors
docker logs telebot 2>&1 | grep -i "error"
```

### MT5 connection failing
```bash
# Check MT5 host is reachable
docker exec telebot python3 -c "import socket; s=socket.create_connection(('MT5_HOST', 18812), timeout=5); print('OK'); s.close()"
```

### Discord notifications not sending
```bash
# Test webhook manually
curl -X POST YOUR_WEBHOOK_URL -H "Content-Type: application/json" -d '{"content": "Test message"}'
```

---

## Deployment Checklist

### Before going live:
- [ ] VPS set up with Docker
- [ ] Repository cloned
- [ ] `.env` configured with all credentials
- [ ] `accounts.json` configured with MT5 account details
- [ ] 3 Discord channels created with webhooks
- [ ] Firewall configured (SSH + dashboard port only)
- [ ] `DASHBOARD_PASS_HASH` generated via `scripts/hash_password.py` and set in `.env`
- [ ] `SESSION_SECRET` generated (`openssl rand -base64 48`) and set in `.env`
- [ ] Legacy `DASHBOARD_PASS=` removed from `.env` (bot refuses to start otherwise)
- [ ] `TRADING_DRY_RUN=true` — dry-run mode first
- [ ] Bot running and parsing signals correctly (3-5 days)
- [ ] Dashboard accessible and showing data

### Before switching to live:
- [ ] MT5 connection working (mt5linux or Windows VPS)
- [ ] Test on CHALLENGE account first (not funded)
- [ ] Lot sizes verified for each account size
- [ ] SL/TP values verified
- [ ] Stale signal detection working
- [ ] Zone execution logic verified
- [ ] Run for 1 week on challenge account
- [ ] No FundedNext warnings or flags

### After going live:
- [ ] Monitor #executions channel daily
- [ ] Check dashboard positions after each signal
- [ ] Review daily stats (trades count, server messages)
- [ ] Verify P&L matches FundedNext dashboard
- [ ] Set up HTTPS for dashboard (Phase 5)
- [ ] Set up VPS monitoring

---

## Cost Summary

| Item | Cost | Notes |
|------|------|-------|
| Hostinger VPS | Already have | Running the bot |
| Windows VPS (for MT5) | ~$10/month | Optional, if mt5linux doesn't work |
| Domain name | ~$10/year | Optional, for HTTPS |
| FundedNext EA fee | Varies | Required for automated trading |
| **Total additional** | **$0-20/month** | |

---

## Architecture on VPS

```
┌─── Hostinger VPS ────────────────────────────────┐
│                                                    │
│  Docker Container: telebot                         │
│  ┌──────────────────────────────────────────────┐  │
│  │  bot.py (Telegram listener)                  │  │
│  │  ├─ signal_parser.py (parse signals)         │  │
│  │  ├─ trade_manager.py (zone logic)            │  │
│  │  ├─ executor.py (multi-account)              │  │
│  │  ├─ notifier.py (Discord channels)           │  │
│  │  └─ dashboard.py (FastAPI :8080)             │  │
│  │                                              │  │
│  │  data/telebot.db (SQLite)                    │  │
│  │  accounts.json (config)                      │  │
│  └──────────────────────────────────────────────┘  │
│            │                    │                   │
│            ▼                    ▼                   │
│     Telegram API          Discord Webhooks          │
│                                                    │
│     Optional: Nginx → :443 (HTTPS)                 │
│                                                    │
└──────────────────┬───────────────────────────────┘
                   │ RPyC :18812
                   ▼
         ┌─── Windows VPS (optional) ──┐
         │  MT5 Terminal               │
         │  FundedNext-Server          │
         └─────────────────────────────┘
```
