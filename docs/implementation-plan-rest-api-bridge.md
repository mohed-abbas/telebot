# Implementation Plan: REST API Bridge

## Phase 0: Remove Old Wine Bridge

Delete the Wine + RPyC approach entirely. No backward compatibility.

### Changes

| Action | File |
|--------|------|
| Delete | `mt5-bridge/` (entire directory) |
| Modify | `mt5_connector.py` — remove `MT5LinuxConnector` class |
| Modify | `requirements.txt` — remove `rpyc==5.2.3` |
| Modify | `Dockerfile` — remove `pip install mt5linux` line |
| Modify | `config.py` — update `mt5_backend` comment |
| Modify | `.env.example` — update `MT5_BACKEND` default to `rest_api` |

---

## Phase 1: MT5 Simulator (local testing on Mac + Linux)

Docker-based simulator implementing the REST API contract. Enables full pipeline testing on any OS.

### New files

| File | Description |
|------|-------------|
| `mt5-simulator/simulator.py` | FastAPI app (~200 lines), same REST API as real server |
| `mt5-simulator/state.py` | In-memory state: positions, orders, balance, P&L |
| `mt5-simulator/Dockerfile` | python:3.12-slim, runs uvicorn |
| `mt5-simulator/requirements.txt` | fastapi, uvicorn |
| `tests/test_simulator.py` | Tests via `httpx.ASGITransport` (in-process) |

### Simulator capabilities

- Static or random-walk price simulation
- Market orders fill instantly at simulated price
- Limit/stop orders fill when price crosses trigger
- P&L calculation on close (XAUUSD: 1 lot = 100 oz)
- Account balance updates on position close
- Realistic error codes for invalid operations

---

## Phase 2: RestApiConnector

New `MT5Connector` subclass using `httpx.AsyncClient` for HTTP calls.

### Changes

| Action | File |
|--------|------|
| Modify | `mt5_connector.py` — add `RestApiConnector` class, update `create_connector()` factory |
| Create | `tests/test_rest_api_connector.py` — unit tests with mocked HTTP |
| Create | `tests/test_rest_api_integration.py` — E2E test with simulator in-process |

### RestApiConnector details

- Constructor: `host`, `port`, `api_key`, `use_tls`
- `httpx.AsyncClient` with base_url, 15s timeout, `X-API-Key` header
- Each method: HTTP call -> parse JSON envelope -> return dataclass
- Retry: up to 2 times with 1s delay on connection errors
- On HTTP 503: set `_connected = False`

### Factory update

```python
create_connector(backend="rest_api", ...)
# Supported backends: "dry_run", "rest_api"
```

---

## Phase 3: Config & Wiring

### Changes

| Action | File | Detail |
|--------|------|--------|
| Modify | `config.py` | Add `mt5_api_key: str`, `mt5_use_tls: bool` to Settings |
| Modify | `bot.py` | Pass `mt5_api_key`, `mt5_use_tls` kwargs to `create_connector()` |
| Modify | `docker-compose.dev.yml` | Add `mt5-simulator` service |
| Modify | `.env.example` | Add `MT5_API_KEY`, `MT5_USE_TLS` |
| Modify | `accounts.example.json` | Update example ports to 8001, 8002 |

---

## Phase 4: Windows VPS REST Server

Standalone FastAPI app wrapping the native MetaTrader5 Python API. Runs on Windows VPS only.

### New files

| File | Description |
|------|-------------|
| `mt5-rest-server/server.py` | FastAPI app (~250 lines), all mt5.* calls via `run_in_executor` |
| `mt5-rest-server/config.py` | Reads env vars: API key, MT5 credentials, terminal path, port |
| `mt5-rest-server/requirements.txt` | fastapi, uvicorn, MetaTrader5, python-dotenv |
| `mt5-rest-server/install-service.ps1` | PowerShell: install per-account NSSM Windows services |

### Server details

- `import MetaTrader5 as mt5` (Windows-only C++ DLL)
- All `mt5.*` calls in `run_in_executor(None, ...)` with 10s timeout
- Startup: `mt5.initialize(path=TERMINAL_PATH)` then `mt5.login()`
- Auth: `X-API-Key` + `secrets.compare_digest()`
- Auto-reconnect: if `mt5.terminal_info()` disconnected, retry login

---

## Phase 5: Deployment & Cutover

1. Set up Windows VPS (OVHcloud $9.99/mo recommended)
2. Install MT5 terminals (separate dirs: `C:\MT5\Account1\`, `C:\MT5\Account2\`)
3. Deploy `mt5-rest-server`, install as NSSM Windows services
4. Windows Firewall: allow only Hostinger VPS IP on ports 8001-8010
5. Update Hostinger config: `MT5_BACKEND=rest_api`, `MT5_API_KEY=<key>`
6. Update `accounts.json`: `mt5_host` = Windows VPS IP, `mt5_port` per account
7. Test with `TRADING_DRY_RUN=true` + `MT5_BACKEND=rest_api`
8. Go live: `TRADING_DRY_RUN=false`
9. Delete old `mt5-bridge/` directory from VPS

---

## Complete Files Summary

| Action | File | Phase |
|--------|------|-------|
| **Delete** | `mt5-bridge/` (entire directory) | 0 |
| Modify | `mt5_connector.py` — remove `MT5LinuxConnector` | 0 |
| Modify | `requirements.txt` — remove `rpyc` | 0 |
| Modify | `Dockerfile` — remove `mt5linux` install | 0 |
| Create | `mt5-simulator/simulator.py` | 1 |
| Create | `mt5-simulator/state.py` | 1 |
| Create | `mt5-simulator/Dockerfile` | 1 |
| Create | `mt5-simulator/requirements.txt` | 1 |
| Create | `tests/test_simulator.py` | 1 |
| Modify | `mt5_connector.py` — add `RestApiConnector` + update factory | 2 |
| Create | `tests/test_rest_api_connector.py` | 2 |
| Create | `tests/test_rest_api_integration.py` | 2 |
| Modify | `config.py` — add `mt5_api_key`, `mt5_use_tls` | 3 |
| Modify | `bot.py` — pass new kwargs to factory | 3 |
| Modify | `docker-compose.dev.yml` — add simulator service | 3 |
| Modify | `.env.example` — update examples | 3 |
| Modify | `accounts.example.json` — update example ports | 3 |
| Create | `mt5-rest-server/server.py` | 4 |
| Create | `mt5-rest-server/config.py` | 4 |
| Create | `mt5-rest-server/requirements.txt` | 4 |
| Create | `mt5-rest-server/install-service.ps1` | 4 |

---

## Verification Checklist

1. Simulator on Mac/Linux: `docker build` + `curl /api/v1/ping`
2. Tests pass: `pytest tests/test_simulator.py tests/test_rest_api_connector.py tests/test_rest_api_integration.py`
3. Full local pipeline: simulator + telebot locally, send test signal, verify execution + Discord
4. Windows VPS connectivity: `curl` from Hostinger to Windows VPS
5. Dry-run with real MT5: dashboard shows real account balance
6. Live trade: small lot test on demo account
