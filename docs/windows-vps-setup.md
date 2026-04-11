# Windows VPS Setup — MT5 REST Server

Complete guide for setting up the MT5 REST API server on a Windows VPS.

## Architecture

```
Linux VPS (telebot)                Windows VPS (MT5)
┌──────────────────────┐          ┌──────────────────────────┐
│ telebot (Docker)     │          │ MT5 Terminal #1 (GUI)    │
│  - Telegram listener │          │ MT5 Terminal #2 (GUI)    │
│  - Signal parser     │   HTTP   │                          │
│  - Trade executor    │────────→ │ uvicorn :8001 (account1) │
│  - Dashboard         │          │ uvicorn :8002 (account2) │
│  - PostgreSQL        │          │                          │
└──────────────────────┘          │ (startup app, same       │
                                  │  desktop session as MT5) │
                                  └──────────────────────────┘
```

**Important:** The MT5 Python API uses Windows named pipes to communicate with
the terminal. Both must run in the **same Windows desktop session**. Running
uvicorn as a Windows service (NSSM/Session 0) will NOT work — it causes
`IPC timeout` errors. See [docs/issues-solved.md](issues-solved.md#issue-10)
for details.

---

## Prerequisites

- Windows VPS (Windows Server 2019/2022/2025)
- RDP access (Microsoft Remote Desktop app on Mac, or mstsc on Windows)
- Your broker's MT5 terminal installer
- Linux VPS with telebot already deployed

## Step 1: Connect via RDP

**On Mac:** Install "Microsoft Remote Desktop" from the Mac App Store (free).
Add a new PC with your VPS IP, username (usually `Administrateur` or `Administrator`),
and the password from your VPS provider.

**On Windows:** Press `Win+R`, type `mstsc`, enter your VPS IP.

## Step 2: Install Python 3.12

Open PowerShell **as Administrator**:

```powershell
Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe" -OutFile "$env:TEMP\python-installer.exe"

Start-Process -Wait "$env:TEMP\python-installer.exe" -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1"
```

**Close and reopen PowerShell**, then verify:

```powershell
python --version
pip --version
```

## Step 3: Install Git

```powershell
Invoke-WebRequest -Uri "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/Git-2.47.1-64-bit.exe" -OutFile "$env:TEMP\git-installer.exe"

Start-Process -Wait "$env:TEMP\git-installer.exe" -ArgumentList "/VERYSILENT /NORESTART"
```

Close and reopen PowerShell, verify: `git --version`

**Note:** If `git` is not recognized after reopening PowerShell, use the full path:
`& "C:\Program Files\Git\bin\git.exe"`

## Step 4: Clone the project and set up the REST server

```powershell
New-Item -ItemType Directory -Force -Path "C:\Apps"
cd C:\Apps
git clone https://github.com/YOUR_USERNAME/telebot.git
cd telebot\mt5-rest-server

python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Step 5: Install MT5 Terminals

Each account needs its own MT5 terminal copy (the Python API is a singleton per process).

**First account — install from broker:**

1. Download MT5 installer from your broker's website
2. Run the installer (it installs to a default location like `C:\Program Files\MetaTrader 5\`)
3. Launch the terminal, log in, and verify it connects (green icon in bottom-right)

**Create a portable copy:**

```powershell
Copy-Item "C:\Program Files\MetaTrader 5" -Destination "C:\MT5\Account1" -Recurse
```

The terminal path will be: `C:\MT5\Account1\MetaTrader 5\terminal64.exe`

**For additional accounts**, copy the same installation:

```powershell
Copy-Item "C:\Program Files\MetaTrader 5" -Destination "C:\MT5\Account2" -Recurse
```

**Launch each copy with `/portable` and log in:**

```powershell
Start-Process "C:\MT5\Account1\MetaTrader 5\terminal64.exe" -ArgumentList "/portable"
```

The `/portable` flag keeps each terminal's data (login, settings) in its own directory,
preventing conflicts between accounts.

## Step 6: Create .env files for each account

```powershell
cd C:\Apps\telebot\mt5-rest-server
```

Generate a secure API key (use the same key for all accounts):

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Create `.env.account1` — replace placeholders with your actual values:

```powershell
Set-Content -Path ".env.account1" -Value "MT5_API_KEY=YOUR_GENERATED_API_KEY
MT5_LOGIN=YOUR_LOGIN_NUMBER
MT5_PASSWORD=YOUR_PASSWORD
MT5_SERVER=YourBroker-Server
MT5_TERMINAL_PATH=C:\MT5\Account1\MetaTrader 5\terminal64.exe
MT5_MAGIC_NUMBER=202603
PORT=8001"
```

Also copy it as `.env` (the server loads `.env` by default, `ENV_FILE` overrides it):

```powershell
Copy-Item ".env.account1" ".env"
```

**Finding the server name:** In MT5 terminal, go to File > Login to Trade Account. The
server name is shown (e.g., `VantageInternational-Demo`, `FundedNext-Server`).

## Step 7: Test manually

Make sure the MT5 terminal is open and connected, then:

```powershell
cd C:\Apps\telebot\mt5-rest-server
.\venv\Scripts\python.exe -m uvicorn server:app --host 0.0.0.0 --port 8001
```

You should see:
```
MT5 initialized
MT5 logged in — balance=10000.00 equity=10000.00
Uvicorn running on http://0.0.0.0:8001
```

In another PowerShell window, test:

```powershell
# Test ping (no auth)
curl.exe http://localhost:8001/api/v1/ping

# Test with auth
$headers = @{"X-API-Key" = "YOUR_API_KEY"}
Invoke-RestMethod -Uri "http://localhost:8001/api/v1/account" -Headers $headers
```

If you see balance/equity data, it works. Press `Ctrl+C` to stop.

## Step 8: Configure Windows Firewall

Only allow your Linux VPS IP to access the MT5 ports:

```powershell
$LinuxVpsIp = "YOUR_LINUX_VPS_IP"

New-NetFirewallRule -DisplayName "MT5 REST API Allow Linux VPS" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 8001-8010 `
    -RemoteAddress $LinuxVpsIp `
    -Action Allow -Profile Any
```

Windows Firewall blocks other inbound connections by default — no need for an explicit block rule.

## Step 9: Set up auto-start (startup app)

The MT5 terminal and uvicorn must run in the **same desktop session**. We use a
startup batch file (not a Windows service) to ensure this.

**Create the startup script:**

```powershell
$lines = @(
    '@echo off',
    'start "" "C:\MT5\Account1\MetaTrader 5\terminal64.exe" /portable',
    'timeout /t 15 /nobreak >nul',
    'cd /d C:\Apps\telebot\mt5-rest-server',
    'set ENV_FILE=C:\Apps\telebot\mt5-rest-server\.env.account1',
    'start /B "" "C:\Apps\telebot\mt5-rest-server\venv\Scripts\python.exe" -m uvicorn server:app --host 0.0.0.0 --port 8001'
)
$lines -join "`r`n" | Out-File -Encoding ascii "C:\Apps\start-all.bat"
```

**Create a startup shortcut:**

```powershell
$shortcutPath = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\StartMT5.lnk"
Remove-Item $shortcutPath -ErrorAction SilentlyContinue
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "C:\Apps\start-all.bat"
$shortcut.WindowStyle = 7
$shortcut.Save()
```

**Configure Windows auto-login** (so the desktop session starts automatically after reboot):

```powershell
Set-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" -Name AutoAdminLogon -Value "1"
Set-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" -Name DefaultUserName -Value "Administrateur"
Set-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" -Name DefaultPassword -Value "YOUR_WINDOWS_PASSWORD"
```

**Note:** Use your actual Windows username. French VPS uses `Administrateur`, English uses `Administrator`.

**Test by rebooting:**

```powershell
Restart-Computer
```

Wait 90 seconds, then from your Linux VPS:

```bash
curl http://WINDOWS_VPS_IP:8001/api/v1/ping
# Should return: {"ok":true,"data":{"alive":true},"error":null}
```

## Step 10: Configure Linux VPS

On your **Linux VPS**, update `accounts.json`:

```json
{
  "accounts": [
    {
      "name": "Account1",
      "server": "YourBroker-Server",
      "login": 12345678,
      "password_env": "MT5_PASS_1",
      "risk_percent": 1.0,
      "max_lot_size": 0.5,
      "max_daily_loss_percent": 3.0,
      "max_open_trades": 3,
      "enabled": true,
      "mt5_host": "WINDOWS_VPS_IP",
      "mt5_port": 8001
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

Update `.env` on the Linux VPS:

```
MT5_BACKEND=rest_api
MT5_API_KEY=same_key_from_windows_vps
MT5_HOST=WINDOWS_VPS_IP
MT5_USE_TLS=false
TRADING_ENABLED=true
TRADING_DRY_RUN=false
```

Set the MT5 password environment variable:

```
MT5_PASS_1=your_mt5_account_password
```

Restart the bot:

```bash
cd /home/murx/apps/telebot
docker compose up -d --build
docker compose logs -f telebot --tail 20
```

You should see:
```
Trading ENABLED (REST_API) — 1 account(s) configured
HTTP Request: POST http://WINDOWS_VPS_IP:8001/api/v1/connect "HTTP/1.1 200 OK"
Executor started — cleanup + heartbeat loops running
```

## Step 11: Verify end-to-end

1. Send a test signal in your Telegram test group
2. Check telebot logs for signal parsing and execution
3. Check Discord #executions channel for trade confirmation
4. Check the MT5 terminal on Windows VPS for the opened position
5. Check the dashboard for the account status and open positions

---

## RDP Disconnect vs Logout

- **Disconnecting RDP** (closing the Remote Desktop app): Everything keeps running. The desktop session stays active.
- **Logging out**: Kills everything. MT5 terminals close, uvicorn stops.
- **VPS reboot**: Auto-login + startup script restarts everything automatically.

You do NOT need to keep RDP connected for the bot to work.

---

## Troubleshooting

### `alive: false` after reboot
The MT5 terminal may not have connected to the broker yet. Wait 60-90 seconds.
If still false, RDP in and check if the terminal shows a green connection icon.

### `IPC timeout` or `No IPC connection`
The MT5 terminal and uvicorn are in different Windows sessions. Make sure both
are running as startup apps (not Windows services). See Issue #10 in
[issues-solved.md](issues-solved.md).

### `AUTH_FAILED` on API calls
The `.env` file isn't being loaded. Make sure `.env` exists in the
`mt5-rest-server` directory (copy from `.env.account1`).

### Port already in use
```powershell
netstat -ano | findstr "8001"
taskkill /PID <PID> /F
```

### Updating the code
```powershell
cd C:\Apps\telebot
& "C:\Program Files\Git\bin\git.exe" pull
```
Then restart uvicorn (kill the python process and re-run `start-all.bat`,
or just reboot the VPS).

---

## Checklist

- [ ] RDP into Windows VPS
- [ ] Install Python 3.12
- [ ] Install Git
- [ ] Clone repo, set up venv, install dependencies
- [ ] Install MT5 terminal, create portable copy in `C:\MT5\Account1\`
- [ ] Launch terminal with `/portable`, log in, verify green icon
- [ ] Create `.env.account1` with credentials and API key
- [ ] Copy `.env.account1` to `.env`
- [ ] Test manually with uvicorn (ping + account endpoint)
- [ ] Configure Windows Firewall (whitelist Linux VPS IP)
- [ ] Create `start-all.bat` startup script
- [ ] Create startup shortcut
- [ ] Configure Windows auto-login
- [ ] Reboot and verify (`curl ping` from Linux VPS)
- [ ] Update Linux VPS `accounts.json` and `.env`
- [ ] Restart telebot and verify logs
- [ ] Send test signal and verify end-to-end
