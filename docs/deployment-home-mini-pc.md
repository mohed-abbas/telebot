# Deployment Option: Home Mini PC

Alternative to renting a Windows VPS. Uses a local mini PC as the MT5 REST server host, saving ~$15-20/mo in VPS costs.

> The REST API architecture is provider-agnostic. The RestApiConnector only needs `host:port`. Switching between cloud VPS and home PC is just a config change in `accounts.json`.

---

## Hardware Requirements

| Component | Minimum | Your Mini PC |
|---|---|---|
| OS | Windows 10/11 | Yes (used for RDP) |
| RAM | 4 GB (2-3 accounts) | 8 GB (~6-8 accounts) |
| Storage | 50 GB | 240 GB SSD |
| Network | Stable broadband | Home ISP |
| Power | Always-on during market hours | Needs UPS (recommended) |

Each MT5 terminal uses ~500MB-1GB RAM. With 8GB, you can comfortably run 6-8 terminals plus the REST server processes.

---

## Network Architecture

```
Hostinger VPS (Linux)                 Home Network
┌──────────────────┐                 ┌─────────────────────────────────────┐
│ telebot (prod)   │                 │                                     │
│                  │                 │  Router (public IP / DuckDNS)       │
│ RestApiConnector─┼──HTTPS──────→   │    │                                │
│                  │  :8001-8010     │    │ Port Forward                   │
│                  │                 │    │  8001 → 192.168.x.x:8001      │
│                  │                 │    │  8002 → 192.168.x.x:8002      │
│                  │                 │    ▼                                │
│                  │                 │  Mini PC (192.168.x.x)             │
│                  │                 │  ┌─────────────────────────────┐   │
│                  │                 │  │ mt5-rest-server (NSSM)      │   │
│                  │                 │  │  :8001 → MT5 Terminal #1    │   │
│                  │                 │  │  :8002 → MT5 Terminal #2    │   │
│                  │                 │  │  ...                        │   │
│                  │                 │  └─────────────────────────────┘   │
└──────────────────┘                 └─────────────────────────────────────┘
```

---

## Step-by-Step Setup

### Step 1: Static Local IP

Assign a static IP to the mini PC so port forwarding doesn't break when DHCP renews.

**Windows Settings:**
1. Settings > Network & Internet > Ethernet > Edit IP assignment
2. Set to Manual, enable IPv4
3. Example:
   - IP: `192.168.1.100`
   - Subnet: `255.255.255.0`
   - Gateway: `192.168.1.1` (your router)
   - DNS: `8.8.8.8`, `8.8.4.4`

**Or via router:** Most routers support DHCP reservation — bind the mini PC's MAC address to a fixed IP.

### Step 2: Dynamic DNS

Home ISPs assign dynamic public IPs that change periodically. Dynamic DNS gives you a stable hostname.

**DuckDNS (free):**
1. Go to [duckdns.org](https://www.duckdns.org), sign in with GitHub/Google
2. Create a subdomain (e.g., `yourname.duckdns.org`)
3. Install the DuckDNS updater on the mini PC:

```powershell
# Create scheduled task to update DuckDNS every 5 minutes
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument @"
-Command "Invoke-RestMethod -Uri 'https://www.duckdns.org/update?domains=YOURDOMAIN&token=YOUR_TOKEN&ip='"
"@
$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 5) -At "00:00" -Daily
Register-ScheduledTask -TaskName "DuckDNS" -Action $action -Trigger $trigger -RunLevel Highest
```

Or use the [DuckDNS Windows GUI client](https://www.duckdns.org/install.jsp).

**Alternative:** No-IP (free tier, 1 hostname, requires monthly confirmation).

### Step 3: Router Port Forwarding

Access your router admin panel (usually `192.168.1.1`) and forward ports:

| External Port | Internal IP | Internal Port | Protocol |
|---|---|---|---|
| 8001 | 192.168.1.100 | 8001 | TCP |
| 8002 | 192.168.1.100 | 8002 | TCP |
| ... | ... | ... | TCP |

Forward as many ports as you have accounts (8001-8010 covers 10 accounts).

### Step 4: Windows Firewall

Allow only your Hostinger VPS IP on the forwarded ports:

```powershell
# Replace HOSTINGER_IP with your Hostinger VPS public IP
New-NetFirewallRule -DisplayName "MT5 REST API - Hostinger Only" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 8001-8010 `
    -RemoteAddress HOSTINGER_IP `
    -Action Allow

# Block all other inbound traffic on these ports (default behavior, but explicit)
New-NetFirewallRule -DisplayName "MT5 REST API - Block Others" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 8001-8010 `
    -Action Block
```

### Step 5: Install MT5 Terminals

Same as cloud VPS — one installation per account in separate directories:

```
C:\MT5\Account1\terminal64.exe  (logged into broker account 1)
C:\MT5\Account2\terminal64.exe  (logged into broker account 2)
```

1. Download MT5 from your broker (FundedNext provides a link)
2. Install to `C:\MT5\Account1\`
3. Log in, enable "Allow Algo Trading"
4. Repeat for each account in a separate directory

### Step 6: Deploy mt5-rest-server

```powershell
# Clone or copy the mt5-rest-server directory
cd C:\mt5-rest-server

# Install Python 3.12 from python.org (add to PATH)
pip install -r requirements.txt

# Create .env files per account
# .env.account1
# MT5_LOGIN=12345678
# MT5_PASSWORD=yourpassword
# MT5_SERVER=FundedNext-Server
# MT5_TERMINAL_PATH=C:\MT5\Account1\terminal64.exe
# MT5_API_KEY=<your-64-char-hex-key>
# PORT=8001

# .env.account2
# MT5_LOGIN=87654321
# MT5_PASSWORD=yourpassword
# MT5_SERVER=FundedNext-Server
# MT5_TERMINAL_PATH=C:\MT5\Account2\terminal64.exe
# MT5_API_KEY=<your-64-char-hex-key>
# PORT=8002
```

### Step 7: Install as NSSM Services

```powershell
# Download NSSM from nssm.cc, place in PATH
# Run the install script
.\install-service.ps1
```

Or manually:
```powershell
nssm install mt5-rest-account1 "C:\Python312\python.exe" "-m uvicorn server:app --host 0.0.0.0 --port 8001"
nssm set mt5-rest-account1 AppDirectory "C:\mt5-rest-server"
nssm set mt5-rest-account1 AppEnvironmentExtra "ENV_FILE=.env.account1"
nssm start mt5-rest-account1
```

### Step 8: Hostinger Config

Update `accounts.json` on Hostinger:
```json
{
  "accounts": [
    {
      "name": "FN-6k",
      "mt5_host": "yourname.duckdns.org",
      "mt5_port": 8001,
      "mt5_login": 12345678,
      "mt5_server": "FundedNext-Server"
    },
    {
      "name": "FN-10k",
      "mt5_host": "yourname.duckdns.org",
      "mt5_port": 8002,
      "mt5_login": 87654321,
      "mt5_server": "FundedNext-Server"
    }
  ]
}
```

Update `.env` on Hostinger:
```bash
MT5_BACKEND=rest_api
MT5_API_KEY=<same-64-char-hex-key-as-mini-pc>
MT5_USE_TLS=false   # TLS optional for home setup, see security section
```

---

## Reliability Hardening

Home infrastructure has no SLA. These steps minimize downtime:

### Auto-Boot After Power Loss

1. Enter BIOS (Del/F2 at boot)
2. Find "Power" or "AC Power Recovery" setting
3. Set to "Power On" (auto-start when electricity returns)

### Windows Auto-Login

```powershell
# Set auto-login (so MT5 terminals can start without manual login)
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v AutoAdminLogon /t REG_SZ /d 1 /f
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v DefaultUserName /t REG_SZ /d "YourUsername" /f
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v DefaultPassword /t REG_SZ /d "YourPassword" /f
```

### MT5 Auto-Start

Add MT5 terminal shortcuts to the Windows Startup folder:
```
C:\Users\<YourUser>\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\
```

Create a shortcut for each terminal:
- Target: `C:\MT5\Account1\terminal64.exe /portable`
- Target: `C:\MT5\Account2\terminal64.exe /portable`

The `/portable` flag keeps config in the installation directory.

### NSSM Auto-Recovery

NSSM services restart automatically on crash. Verify:
```powershell
nssm get mt5-rest-account1 AppExit Default   # Should be "Restart"
nssm set mt5-rest-account1 AppRestartDelay 5000  # 5s delay before restart
```

### UPS (Recommended)

A small UPS ($30-50) provides 15-30 minutes of battery backup, enough to survive brief power flickers.

| UPS | Price | Runtime | Outlets |
|---|---|---|---|
| APC BE425M | ~$40 | ~20 min (mini PC) | 6 |
| CyberPower EC450G | ~$45 | ~25 min | 8 |

Connect: mini PC + router + modem to UPS.

---

## Security Considerations

### Without TLS (simpler)

- Traffic between Hostinger and your home is unencrypted HTTP
- Acceptable if: API key is strong (64-char hex) + firewall restricts to Hostinger IP only
- Risk: ISP or network-level attacker could sniff the API key (unlikely but possible)

### With TLS (recommended for production)

Option A — **Caddy reverse proxy** (easiest):
```powershell
# Install Caddy on the mini PC
# Caddyfile:
yourname.duckdns.org {
    reverse_proxy localhost:8001
    tls {
        dns duckdns YOUR_TOKEN
    }
}
```
Caddy auto-obtains Let's Encrypt certificates via DNS challenge.

Option B — **Cloudflare Tunnel** (no port forwarding needed):
```powershell
# Install cloudflared on the mini PC
cloudflared tunnel create mt5-api
cloudflared tunnel route dns mt5-api mt5.yourdomain.com
# Config: route mt5.yourdomain.com → localhost:8001
```
This eliminates port forwarding entirely — Cloudflare handles the routing. Requires a domain.

### IP Monitoring

DuckDNS + firewall means your home IP changes are handled, but your Hostinger IP is static. If Hostinger IP changes (rare), update the Windows Firewall rule.

---

## Monitoring (Optional)

### Health Check from Hostinger

Add a cron job on Hostinger to ping the mini PC and alert on failure:

```bash
# /etc/cron.d/mt5-health
*/5 * * * * curl -sf -H "X-API-Key: $MT5_API_KEY" http://yourname.duckdns.org:8001/api/v1/ping || echo "MT5 REST server down" | mail -s "ALERT" you@email.com
```

### Windows Task Scheduler

Create a scheduled task that checks if the NSSM services are running:

```powershell
# check-services.ps1
$services = @("mt5-rest-account1", "mt5-rest-account2")
foreach ($svc in $services) {
    $status = (Get-Service $svc).Status
    if ($status -ne "Running") {
        Start-Service $svc
        # Optionally send alert via webhook
    }
}
```

---

## Comparison: Cloud VPS vs Home Mini PC

| Factor | Cloud VPS (OVHcloud) | Home Mini PC |
|---|---|---|
| **Monthly cost** | ~$15-20 (Windows license) | ~$3-5 (electricity) |
| **Uptime SLA** | 99.9% | No SLA (ISP-dependent) |
| **Setup complexity** | Simple (just RDP in) | Moderate (DNS, port forward, firewall) |
| **Network latency** | Datacenter-to-datacenter (~5ms) | Home-to-datacenter (~20-50ms) |
| **IP stability** | Static IP included | Dynamic IP (DuckDNS needed) |
| **Scaling** | Upgrade plan for more RAM | Limited to 8GB hardware |
| **Power outages** | Datacenter UPS/generator | Your UPS + local grid |
| **Maintenance** | Provider handles hardware | You handle everything |
| **FundedNext compliance** | Same | Same |

### When to use each

- **Home mini PC**: Budget-conscious, 2-6 accounts, reliable home internet, acceptable ~20-50ms latency
- **Cloud VPS**: Maximum reliability needed, 6+ accounts, or unreliable home internet

### Switching between them

Change in `accounts.json`:
```json
// Home mini PC
"mt5_host": "yourname.duckdns.org"

// Cloud VPS
"mt5_host": "145.239.x.x"
```

That's it. The REST API contract is identical — only the host changes.

---

## FundedNext Compliance

No difference from cloud VPS:
- **VPN/VPS allowed**: Your home IP or a VPS — both permitted for automated trading
- **Consistent IP**: DuckDNS hostname resolves to your current home IP; trades originate from there
- **Multiple accounts, same IP**: Allowed for your own accounts
- **Anti-detection**: Stagger delays and jitter are in the telebot, not the server

---

## Quick Start Checklist

1. [ ] Assign static local IP to mini PC (`192.168.1.100`)
2. [ ] Set up DuckDNS subdomain + updater
3. [ ] Configure router port forwarding (8001-8010 → mini PC)
4. [ ] Configure Windows Firewall (allow Hostinger IP only)
5. [ ] Install MT5 terminals in separate directories
6. [ ] Deploy `mt5-rest-server` + create `.env` per account
7. [ ] Install NSSM services
8. [ ] Enable BIOS auto-power-on + Windows auto-login
9. [ ] Add MT5 terminals to Windows Startup folder
10. [ ] Update Hostinger `accounts.json` with DuckDNS hostname
11. [ ] Generate and set `MT5_API_KEY` on both sides
12. [ ] Test: `curl http://yourname.duckdns.org:8001/api/v1/ping -H "X-API-Key: <key>"`
13. [ ] Dry-run: `TRADING_DRY_RUN=true` + `MT5_BACKEND=rest_api`
14. [ ] Go live: `TRADING_DRY_RUN=false`
