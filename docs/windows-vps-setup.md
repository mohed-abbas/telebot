# Windows VPS Setup — MT5 REST Server

Provider: verycloud.fr | Specs: 4 cores, 12GB RAM, 60GB storage, 10TB bandwidth

## Architecture

```
Linux VPS (your existing)          Windows VPS (verycloud.fr)
┌──────────────────────┐          ┌──────────────────────────┐
│ telebot (Docker)     │          │ MT5 Terminal #1 (GUI)    │
│  - Telegram listener │          │ MT5 Terminal #2 (GUI)    │
│  - Signal parser     │   HTTP   │                          │
│  - Trade executor    │────────→ │ mt5-rest-server :8001    │
│  - Dashboard         │          │ mt5-rest-server :8002    │
│  - PostgreSQL        │          │                          │
└──────────────────────┘          │ (NSSM Windows services)  │
                                  └──────────────────────────┘
```

---

## Step 1: Connect via RDP

Use Remote Desktop to connect to your Windows VPS with the credentials from verycloud.fr.

## Step 2: Install Python 3.12

Open PowerShell **as Administrator**:

```powershell
# Download Python 3.12 installer
Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe" -OutFile "$env:TEMP\python-installer.exe"

# Install silently (adds to PATH)
Start-Process -Wait "$env:TEMP\python-installer.exe" -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1"
```

**Close and reopen PowerShell**, then verify:

```powershell
python --version
pip --version
```

## Step 3: Install Git

```powershell
# Download Git installer
Invoke-WebRequest -Uri "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/Git-2.47.1-64-bit.exe" -OutFile "$env:TEMP\git-installer.exe"

# Install silently
Start-Process -Wait "$env:TEMP\git-installer.exe" -ArgumentList "/VERYSILENT /NORESTART"
```

Close and reopen PowerShell, verify: `git --version`

## Step 4: Install NSSM (service manager)

```powershell
New-Item -ItemType Directory -Force -Path "C:\nssm"

Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile "$env:TEMP\nssm.zip"

Expand-Archive "$env:TEMP\nssm.zip" -DestinationPath "$env:TEMP\nssm-extract" -Force

Copy-Item "$env:TEMP\nssm-extract\nssm-2.24\win64\nssm.exe" "C:\nssm\nssm.exe"

# Verify
C:\nssm\nssm.exe version
```

## Step 5: Clone the project and set up the REST server

```powershell
New-Item -ItemType Directory -Force -Path "C:\Apps"
cd C:\Apps
git clone https://github.com/YOUR_USERNAME/telebot.git
cd telebot\mt5-rest-server

# Create virtual environment
python -m venv venv

# Activate and install dependencies
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Step 6: Install MT5 Terminals

One separate MT5 installation per account (Python API is singleton per process).

```powershell
New-Item -ItemType Directory -Force -Path "C:\MT5\Account1"
New-Item -ItemType Directory -Force -Path "C:\MT5\Account2"
```

For each account:
1. Download MT5 installer from your broker (FundedNext, Vantage, etc.)
2. Install Account 1 to `C:\MT5\Account1\`
3. Install Account 2 to `C:\MT5\Account2\`
4. **Launch each terminal once** and log in manually to accept EULA
5. Verify each terminal shows green connection icon (bottom-right)

## Step 7: Create .env files for each account

```powershell
cd C:\Apps\telebot\mt5-rest-server
```

Generate a secure API key:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Create `.env.account1`:

```powershell
@"
MT5_API_KEY=YOUR_GENERATED_API_KEY
MT5_LOGIN=YOUR_ACCOUNT1_LOGIN
MT5_PASSWORD=YOUR_ACCOUNT1_PASSWORD
MT5_SERVER=FundedNext-Server
MT5_TERMINAL_PATH=C:\MT5\Account1\terminal64.exe
MT5_MAGIC_NUMBER=202603
PORT=8001
"@ | Out-File -Encoding utf8 .env.account1
```

Create `.env.account2`:

```powershell
@"
MT5_API_KEY=YOUR_GENERATED_API_KEY
MT5_LOGIN=YOUR_ACCOUNT2_LOGIN
MT5_PASSWORD=YOUR_ACCOUNT2_PASSWORD
MT5_SERVER=FundedNext-Server
MT5_TERMINAL_PATH=C:\MT5\Account2\terminal64.exe
MT5_MAGIC_NUMBER=202603
PORT=8002
"@ | Out-File -Encoding utf8 .env.account2
```

Use the **same API key** for both (it just needs to match your Linux bot's `MT5_API_KEY`).

## Step 8: Test manually

Make sure the corresponding MT5 terminal is open, then:

```powershell
cd C:\Apps\telebot\mt5-rest-server
$env:ENV_FILE = ".env.account1"
.\venv\Scripts\python.exe -m uvicorn server:app --host 0.0.0.0 --port 8001
```

In another PowerShell window:

```powershell
# Test ping (no auth needed)
Invoke-RestMethod -Uri "http://localhost:8001/api/v1/ping"

# Test with auth
$headers = @{"X-API-Key" = "YOUR_API_KEY"}
Invoke-RestMethod -Uri "http://localhost:8001/api/v1/account" -Headers $headers
```

If you see balance/equity, it works. Press `Ctrl+C` to stop.

## Step 9: Install as Windows Services

```powershell
cd C:\Apps\telebot\mt5-rest-server
powershell -ExecutionPolicy Bypass -File .\install-service.ps1
```

Start services:

```powershell
net start mt5-rest-account1
net start mt5-rest-account2
```

Check status:

```powershell
Get-Service mt5-rest-*
```

## Step 10: Configure Windows Firewall

Only allow your Linux VPS IP:

```powershell
$LinuxVpsIp = "YOUR_LINUX_VPS_IP"

New-NetFirewallRule -DisplayName "MT5 REST API" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 8001-8010 `
    -RemoteAddress $LinuxVpsIp `
    -Action Allow

New-NetFirewallRule -DisplayName "MT5 REST API Block Others" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 8001-8010 `
    -Action Block
```

## Step 11: Auto-start MT5 Terminals on Boot

```powershell
@"
Start-Process "C:\MT5\Account1\terminal64.exe" -ArgumentList "/portable"
Start-Process "C:\MT5\Account2\terminal64.exe" -ArgumentList "/portable"
"@ | Out-File -Encoding utf8 "C:\Apps\start-mt5-terminals.ps1"

# Add to Windows startup
$shortcutPath = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\StartMT5.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = "-ExecutionPolicy Bypass -File C:\Apps\start-mt5-terminals.ps1"
$shortcut.Save()
```

## Step 12: Configure Linux VPS

On your **Linux VPS**, update `accounts.json`:

```json
{
  "accounts": [
    {
      "name": "Account1",
      "server": "FundedNext-Server",
      "login": 12345678,
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
      "name": "Account2",
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

Update `.env` on the Linux VPS:

```
MT5_BACKEND=rest_api
MT5_API_KEY=same_key_from_windows_vps
MT5_USE_TLS=false
TRADING_ENABLED=true
TRADING_DRY_RUN=false
```

---

## Checklist

- [ ] RDP into Windows VPS
- [ ] Install Python 3.12
- [ ] Install Git
- [ ] Install NSSM
- [ ] Clone repo, set up venv
- [ ] Install MT5 terminals (one per account, separate folders)
- [ ] Create `.env.account*` files with credentials
- [ ] Test manually with uvicorn
- [ ] Install as Windows services
- [ ] Configure firewall (whitelist Linux VPS IP only)
- [ ] Set up MT5 auto-start on boot
- [ ] Update Linux VPS accounts.json and .env
