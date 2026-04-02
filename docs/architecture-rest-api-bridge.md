# Architecture: Windows VPS + REST API Bridge

## Overview

Replace the Wine + RPyC MT5 bridge with a native Windows VPS running a lightweight REST API. The telebot on Hostinger Linux VPS connects to the REST API over HTTPS. A Docker-based simulator enables full pipeline testing on Mac and Linux.

## System Architecture

```
Mac/Linux (dev)                 Hostinger VPS (Linux)           Windows VPS (~$10/mo)
┌──────────────────┐           ┌──────────────────┐           ┌────────────────────────┐
│ telebot           │           │ telebot (prod)   │           │ mt5-rest-server        │
│ + mt5-simulator   │           │                  │           │ (1 FastAPI per account) │
│   (Docker)        │           │ RestApiConnector─┼──HTTPS──→ │                        │
│                   │           │                  │           │ MetaTrader5 Python API │
│ RestApiConnector──┼──HTTP──→  │                  │           │ MT5 Terminals x N      │
│ (localhost:8001)  │           │                  │           │ Ports: 8001, 8002...   │
└──────────────────┘           └──────────────────┘           └────────────────────────┘
```

## Windows VPS — Native Processes (No Docker)

The MetaTrader5 Python package is a Windows DLL that communicates with a running MT5 terminal via named pipes. This requires the Python process and MT5 terminal to be on the same Windows machine. Docker would break this IPC.

```
Windows VPS (OVHcloud, $10/mo)
┌────────────────────────────────────────────────────────────────────┐
│                                                                    │
│  Windows Desktop Session (auto-login at boot)                      │
│                                                                    │
│  ┌─── Account 1 (FN-6k) ──────────────────────────────────┐       │
│  │                                                         │       │
│  │  C:\MT5\Account1\terminal64.exe     ◄── MT5 GUI app     │       │
│  │       │  (logged into FundedNext     │  (runs at boot)  │       │
│  │       │   server, account 12345678)  │                  │       │
│  │       │                              │                  │       │
│  │       │ named pipes (Windows IPC)    │                  │       │
│  │       ▼                              │                  │       │
│  │  Python process (NSSM service)       │                  │       │
│  │  uvicorn server:app --port 8001      │                  │       │
│  │       │                              │                  │       │
│  │       │ import MetaTrader5 as mt5    │                  │       │
│  │       │ mt5.initialize(path=         │                  │       │
│  │       │   "C:\MT5\Account1\...")     │                  │       │
│  │       │                              │                  │       │
│  │       ▼                              │                  │       │
│  │  REST API on port 8001  ◄────────────┼── from Hostinger │       │
│  └─────────────────────────────────────┘                   │       │
│                                                            │       │
│  ┌─── Account 2 (FN-10k) ─────────────────────────────────┐       │
│  │                                                         │       │
│  │  C:\MT5\Account2\terminal64.exe     ◄── separate MT5    │       │
│  │       │  (logged into FundedNext     │  installation    │       │
│  │       │   server, account 87654321)  │                  │       │
│  │       │                              │                  │       │
│  │       │ named pipes                  │                  │       │
│  │       ▼                              │                  │       │
│  │  Python process (NSSM service)       │                  │       │
│  │  uvicorn server:app --port 8002      │                  │       │
│  │       │                              │                  │       │
│  │       │ mt5.initialize(path=         │                  │       │
│  │       │   "C:\MT5\Account2\...")     │                  │       │
│  │       ▼                              │                  │       │
│  │  REST API on port 8002  ◄────────────┼── from Hostinger │       │
│  └─────────────────────────────────────┘                   │       │
│                                                            │       │
│  Windows Firewall: only allow Hostinger IP on 8001-8010    │       │
│                                                            │       │
└────────────────────────────────────────────────────────────────────┘
```

### Per-Account Isolation

Each account is fully isolated:
- **Separate MT5 installation directory** (`C:\MT5\Account1\`, `C:\MT5\Account2\`)
- **Separate Python process** (MT5 API is a global singleton per process)
- **Separate port** (8001, 8002, 8003...)
- **Separate NSSM Windows service** (independent auto-restart)
- **Separate .env config file** (own credentials)

### Why No Docker on Windows?

```
MetaTrader5 Python package (.pyd DLL)
       │
       │  connects via Windows named pipes
       ▼
MT5 terminal64.exe (running GUI app)
       │
       │  network connection
       ▼
Broker MT5 Server
```

Named pipes don't work across Docker container boundaries. The MT5 terminal must be a visible Windows app, and the Python process must be on the same machine.

## End-to-End Flow (Production)

```
Telegram Signal
       │
       ▼
Hostinger VPS (Linux)
┌──────────────────────────────┐
│  telebot (bot.py)            │
│       │                      │
│       ▼                      │
│  signal_parser.py            │
│       │                      │
│       ▼                      │
│  executor.py                 │
│    ├── Account 1:            │         Windows VPS
│    │   RestApiConnector      │         ┌──────────────┐
│    │   POST http://WinVPS    │─:8001─→ │ server.py #1 │──→ MT5 #1 ──→ Broker
│    │                         │         └──────────────┘
│    ├── (stagger delay 1-5s)  │
│    │                         │         ┌──────────────┐
│    └── Account 2:            │─:8002─→ │ server.py #2 │──→ MT5 #2 ──→ Broker
│        RestApiConnector      │         └──────────────┘
│       │                      │
│       ▼                      │
│  notifier.py → Discord       │
└──────────────────────────────┘
```

## Local Dev Flow (Mac or Linux)

```
Mac/Linux
┌──────────────────────────────────────────────────┐
│                                                  │
│  Docker Compose                                  │
│  ┌────────────────────┐  ┌────────────────────┐  │
│  │ mt5-simulator      │  │ postgres           │  │
│  │ (Python, no MT5)   │  │ (dev database)     │  │
│  │ port 8001          │  │ port 5433          │  │
│  │ simulates trades   │  │                    │  │
│  └────────────────────┘  └────────────────────┘  │
│          ▲                                       │
│          │ HTTP                                   │
│  ┌───────┴──────────────┐                        │
│  │ telebot (local)      │                        │
│  │ MT5_BACKEND=rest_api │                        │
│  │ MT5_HOST=localhost    │                        │
│  │ MT5_PORT=8001         │                        │
│  └──────────────────────┘                        │
│                                                  │
│  Same code, same connector, same config format.  │
│  Only difference: simulator vs real MT5.         │
└──────────────────────────────────────────────────┘
```

## REST API Contract

All endpoints prefixed `/api/v1`. Auth via `X-API-Key` header.

Response envelope:
```json
{"ok": true, "data": {...}, "error": null}
```

| Method | Endpoint | Maps to connector method |
|--------|----------|------------------------|
| GET | `/api/v1/ping` | `ping()` |
| POST | `/api/v1/connect` | `connect()` — body: `{login, password, server}` |
| POST | `/api/v1/disconnect` | `disconnect()` |
| GET | `/api/v1/price/{symbol}` | `get_price()` — returns `{bid, ask}` |
| GET | `/api/v1/account` | `get_account_info()` — returns `{balance, equity, margin, free_margin, currency}` |
| GET | `/api/v1/positions?symbol=` | `get_positions()` — returns `{positions: [...]}` |
| POST | `/api/v1/order` | `open_order()` — body: `{symbol, order_type, volume, price, sl, tp, comment, magic}` |
| PUT | `/api/v1/position/{ticket}` | `modify_position()` — body: `{sl, tp}` |
| DELETE | `/api/v1/position/{ticket}` | `close_position()` — body: `{volume}` (optional) |
| GET | `/api/v1/pending-orders?symbol=` | `get_pending_orders()` |
| DELETE | `/api/v1/pending-order/{ticket}` | `cancel_pending()` |

Error codes: `NOT_CONNECTED` (503), `SYMBOL_NOT_FOUND` (404), `POSITION_NOT_FOUND` (404), `ORDER_REJECTED` (422), `AUTH_FAILED` (401).

## Security

- HTTPS with API key auth (`X-API-Key` header, `secrets.compare_digest()`)
- Windows Firewall: only allow Hostinger VPS IP on ports 8001-8010
- API key: 64-char hex (`python -c "import secrets; print(secrets.token_hex(32))"`)
- Provider-agnostic: switching VPS is just an IP change in `accounts.json`

## FundedNext Compliance

- **VPN/VPS allowed**: Paid VPN with consistent IP is recommended by FundedNext
- **Multiple accounts, same IP**: Allowed for own accounts (up to $300K combined funded)
- **Same VPS for all accounts**: Allowed — they monitor behavioral patterns, not technical setup
- **Anti-detection built in**: stagger delays (1-5s), lot jitter (4%), SL/TP jitter (0.8 pts)
- **Note**: Manual trading via VPS is prohibited — VPS for EA/automated trading only

## Recommended Windows VPS Providers

| Provider | Price/mo | RAM | CPU | Storage | Best for |
|---|---|---|---|---|---|
| **OVHcloud VPS-2** | **$9.99** | **12 GB** | **6 vCores** | **100 GB NVMe** | Best value, 10+ accounts |
| Kamatera | $8 | 2 GB | 1 core | 30 GB | Budget / free trial |
| Time4VPS | ~$7.75 | 2 GB | 2 cores | 40 GB | Cheapest, 2-3 accounts |
| Contabo | ~$13 | 8 GB | 4 vCPU | 75 GB | Reliable, 11 locations |

Each MT5 terminal uses ~500MB-1GB RAM. OVHcloud's 12GB handles 10+ terminals easily.
