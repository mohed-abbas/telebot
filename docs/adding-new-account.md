# Adding a New MT5 Account

Step-by-step guide for adding a new broker account to the trading bot.
This involves changes on both the Windows VPS (MT5 terminal + REST server)
and the Linux VPS (telebot configuration).

## Overview

Each MT5 account requires:
- Its own MT5 terminal copy (separate directory)
- Its own uvicorn process (separate port)
- Its own `.env.accountN` file
- An entry in `accounts.json` on the Linux VPS
- An MT5 password env var on the Linux VPS

## Step 1: Create MT5 Terminal Copy (Windows VPS)

RDP into the Windows VPS and copy the existing MT5 installation:

```powershell
Copy-Item "C:\Program Files\MetaTrader 5" -Destination "C:\MT5\Account2" -Recurse
```

Launch the copy and log in with the new account credentials:

```powershell
Start-Process "C:\MT5\Account2\MetaTrader 5\terminal64.exe" -ArgumentList "/portable"
```

In the terminal:
1. File > Login to Trade Account
2. Search for your broker (e.g., "Vantage", "FundedNext")
3. Select the server, enter login and password
4. Verify green connection icon in bottom-right
5. Note the exact **server name** shown (e.g., `VantageInternational-Demo`)

## Step 2: Create .env File (Windows VPS)

```powershell
cd C:\Apps\telebot\mt5-rest-server
```

Create `.env.account2` with the new account's credentials. Use the **same API key**
as your other accounts:

```powershell
Set-Content -Path ".env.account2" -Value "MT5_API_KEY=YOUR_EXISTING_API_KEY
MT5_LOGIN=NEW_ACCOUNT_LOGIN
MT5_PASSWORD=NEW_ACCOUNT_PASSWORD
MT5_SERVER=BrokerName-Server
MT5_TERMINAL_PATH=C:\MT5\Account2\MetaTrader 5\terminal64.exe
MT5_MAGIC_NUMBER=202603
PORT=8002"
```

Use the next available port (8001, 8002, 8003, etc.).

## Step 3: Test Manually (Windows VPS)

With the new MT5 terminal open:

```powershell
cd C:\Apps\telebot\mt5-rest-server
copy .env.account2 .env
.\venv\Scripts\python.exe -m uvicorn server:app --host 0.0.0.0 --port 8002
```

In another PowerShell window:

```powershell
curl.exe http://localhost:8002/api/v1/ping
$headers = @{"X-API-Key" = "YOUR_API_KEY"}
Invoke-RestMethod -Uri "http://localhost:8002/api/v1/account" -Headers $headers
```

Verify you see the new account's balance. Press `Ctrl+C` to stop the test server.

**Restore the original `.env`:**

```powershell
cd C:\Apps\telebot\mt5-rest-server
copy .env.account1 .env
```

## Step 4: Update Startup Script (Windows VPS)

Edit `C:\Apps\start-all.bat` to include the new account. Open it in Notepad:

```powershell
notepad C:\Apps\start-all.bat
```

Add lines for the new terminal and uvicorn process:

```batch
@echo off
REM Account 1
start "" "C:\MT5\Account1\MetaTrader 5\terminal64.exe" /portable

REM Account 2
start "" "C:\MT5\Account2\MetaTrader 5\terminal64.exe" /portable

timeout /t 15 /nobreak >nul

cd /d C:\Apps\telebot\mt5-rest-server

REM Start REST server for Account 1
set ENV_FILE=C:\Apps\telebot\mt5-rest-server\.env.account1
start /B "" "C:\Apps\telebot\mt5-rest-server\venv\Scripts\python.exe" -m uvicorn server:app --host 0.0.0.0 --port 8001

REM Small delay between server starts
timeout /t 5 /nobreak >nul

REM Start REST server for Account 2
set ENV_FILE=C:\Apps\telebot\mt5-rest-server\.env.account2
start /B "" "C:\Apps\telebot\mt5-rest-server\venv\Scripts\python.exe" -m uvicorn server:app --host 0.0.0.0 --port 8002
```

Save and close Notepad.

## Step 5: Update Firewall (Windows VPS)

If you used a port range (8001-8010) in the original firewall rule, no changes needed.
Otherwise, add the new port:

```powershell
$LinuxVpsIp = "YOUR_LINUX_VPS_IP"
New-NetFirewallRule -DisplayName "MT5 REST API Account2" `
    -Direction Inbound -Protocol TCP -LocalPort 8002 `
    -RemoteAddress $LinuxVpsIp -Action Allow -Profile Any
```

## Step 6: Add Account to accounts.json (Linux VPS)

On your Linux VPS, edit `accounts.json`:

```bash
nano /home/murx/apps/telebot/accounts.json
```

Add the new account to the `accounts` array:

```json
{
  "accounts": [
    {
      "name": "Vantage Demo",
      "server": "VantageInternational-Demo",
      "login": 24493425,
      "password_env": "MT5_PASS_1",
      "risk_percent": 1.0,
      "max_lot_size": 0.5,
      "max_daily_loss_percent": 3.0,
      "max_open_trades": 3,
      "enabled": true,
      "mt5_host": "WINDOWS_VPS_IP",
      "mt5_port": 8001
    },
    {
      "name": "FundedNext 10k",
      "server": "FundedNext-Server",
      "login": 87654321,
      "password_env": "MT5_PASS_2",
      "risk_percent": 0.8,
      "max_lot_size": 1.0,
      "max_daily_loss_percent": 3.0,
      "max_open_trades": 3,
      "enabled": true,
      "mt5_host": "WINDOWS_VPS_IP",
      "mt5_port": 8002
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

### Account Configuration Fields

| Field | Description |
|-------|-------------|
| `name` | Display name (shown in dashboard and Discord notifications) |
| `server` | MT5 broker server name (must match exactly) |
| `login` | MT5 account login number |
| `password_env` | Environment variable name containing the MT5 password |
| `risk_percent` | Risk per trade as % of account balance (e.g., 1.0 = 1%) |
| `max_lot_size` | Maximum lot size cap per trade |
| `max_daily_loss_percent` | Daily loss limit as % of balance — stops trading if exceeded |
| `max_open_trades` | Maximum simultaneous open positions |
| `enabled` | Set to `false` to temporarily disable without removing |
| `mt5_host` | Windows VPS IP address |
| `mt5_port` | Port for this account's REST server (8001, 8002, etc.) |

## Step 7: Add MT5 Password to .env (Linux VPS)

Edit the `.env` file on the Linux VPS:

```bash
nano /home/murx/apps/telebot/.env
```

Add the new password variable (matching `password_env` in `accounts.json`):

```
MT5_PASS_2=your_new_account_password
```

## Step 8: Restart and Verify

**On the Windows VPS**, reboot to test the full auto-start:

```powershell
Restart-Computer
```

Wait 90 seconds, then verify both servers from Linux:

```bash
curl http://WINDOWS_VPS_IP:8001/api/v1/ping
curl http://WINDOWS_VPS_IP:8002/api/v1/ping
```

Both should return `alive: true`.

**On the Linux VPS**, restart the bot:

```bash
cd /home/murx/apps/telebot
docker compose up -d --build
docker compose logs -f telebot --tail 30
```

You should see:

```
Trading ENABLED (REST_API) — 2 account(s) configured
HTTP Request: POST http://WINDOWS_VPS_IP:8001/api/v1/connect "HTTP/1.1 200 OK"
HTTP Request: POST http://WINDOWS_VPS_IP:8002/api/v1/connect "HTTP/1.1 200 OK"
```

## Step 9: Test with a Signal

Send a test signal in your Telegram test group. Both accounts should execute
the trade (with staggered delays and jittered lot sizes). Check:

- Discord #executions channel for both account confirmations
- Dashboard shows both accounts online with positions
- Both MT5 terminals show the opened positions

---

## Quick Reference — Port Assignments

| Account | MT5 Directory | Port | .env File |
|---------|---------------|------|-----------|
| Account 1 | `C:\MT5\Account1\` | 8001 | `.env.account1` |
| Account 2 | `C:\MT5\Account2\` | 8002 | `.env.account2` |
| Account 3 | `C:\MT5\Account3\` | 8003 | `.env.account3` |
| ... | ... | ... | ... |

## Disabling an Account

To temporarily disable an account without removing it:

1. Set `"enabled": false` in `accounts.json` on the Linux VPS
2. Restart the bot: `docker compose restart telebot`

The Windows VPS side can keep running — the bot simply won't send trades to disabled accounts.

## Removing an Account

1. Remove the account entry from `accounts.json` on the Linux VPS
2. Remove the `MT5_PASS_N` line from `.env`
3. Restart the bot
4. On the Windows VPS: remove the terminal launch and uvicorn lines from `start-all.bat`
5. Optionally delete the MT5 directory and `.env.accountN` file
