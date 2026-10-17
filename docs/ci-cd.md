# CI/CD

Three GitHub Actions workflows in `.github/workflows/`:

| Workflow | Trigger | What it does |
|---|---|---|
| `ci.yml` | auto on push/PR to `main` | Runs the full pytest suite (Python 3.12 + postgres service). Tells you if `main` is green. **Never deploys.** |
| `deploy-linux.yml` | **manual** (`workflow_dispatch`) | SSH → VPS → `git pull` → `docker compose up -d --build telebot` → health-check `/health`. |
| `deploy-windows-bridge.yml` | **manual** (`workflow_dispatch`) | Self-hosted runner on the Windows VPS → `git pull` → reinstall venv deps → restart `mt5-rest-*` services. Only needed when `mt5-rest-server/**` changed. |

Deploys are **manual by design** — trigger from the Actions tab (or `gh workflow run "Deploy — Linux (bot + dashboard)" -f confirm=deploy`) only when the book is in a safe state. Each deploy requires typing `deploy` in the confirm box.

## One-time setup

### 1. Repository secrets (Settings → Secrets and variables → Actions → Secrets)

- `LINUX_SSH_HOST` — VPS host/IP
- `LINUX_SSH_USER` — deploy user (e.g. `murx`)
- `LINUX_SSH_KEY` — **private** key whose public half is in the VPS user's `~/.ssh/authorized_keys`

Generate a dedicated deploy key (do NOT reuse a personal key):
```bash
ssh-keygen -t ed25519 -C "telebot-deploy" -f telebot_deploy -N ""
# paste telebot_deploy.pub into the VPS: ~/.ssh/authorized_keys
# paste the private telebot_deploy into the LINUX_SSH_KEY secret
```

### 2. Repository variables (Settings → Secrets and variables → Actions → Variables)

- `LINUX_APP_DIR` — path to the clone on the Linux VPS (default `/home/murx/apps/telebot`)
- `MT5_REPO_DIR` — path to the clone on the Windows VPS (default `C:\Apps\telebot`, per `docs/windows-vps-setup.md`)

Confirm both before the first deploy — the guides mention more than one location historically (`~/telebot` vs `/home/murx/apps/telebot`). Run the discovery snippets in "Retrieving the values" below.

### 3. Windows self-hosted runner (for the bridge deploy)

On the Windows VPS: Settings → Actions → Runners → New self-hosted runner → Windows. When configuring, give it the labels `windows` and `mt5-bridge`. Install it as a service so it survives reboots. It needs permission to `Restart-Service` the `mt5-rest-*` services (run the runner as an account with service-control rights, or grant it).

The Windows clone must be the same repo, and the bridge venv must live at `mt5-rest-server\venv` (as `install-service.ps1` expects).

### 4. (Recommended) Approval gate

Create an Environment named `production` (Settings → Environments) with **required reviewers = you**. Both deploy workflows reference it, so each deploy then also needs a one-click approval — a second safety net on top of the manual trigger.

## Notes

- The VPS's own git credentials handle `git pull` (the repos are already cloned/authenticated). The deploy key above is only for SSH access, not repo access.
- The Linux deploy only rebuilds the `telebot` container; shared postgres/nginx are on external networks and untouched.
- First-time deploy caveats from the audit still apply: set `TRUST_PROXY=true` and expect a one-time re-login (see `project_wave3_auth_deploy_reqs`).
