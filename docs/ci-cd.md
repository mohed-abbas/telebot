# CI/CD

Three GitHub Actions workflows in `.github/workflows/`:

| Workflow | Trigger | What it does |
|---|---|---|
| `ci.yml` | auto on push/PR to `main` | Runs the full pytest suite (Python 3.12 + postgres service). Tells you if `main` is green. **Never deploys.** |
| `deploy-linux.yml` | auto after green CI on a push to `main` → **approval** | SSH → VPS → fast-forward to the CI-tested commit → `docker compose up -d --build telebot` → health-check `/health`. |
| `deploy-windows-bridge.yml` | auto after green CI on a push to `main`, **only if `mt5-rest-server/**` changed** → **approval** | Self-hosted runner on the Windows VPS → fast-forward to the CI-tested commit → stop the bridge (uvicorn) → reinstall venv deps → start the bridge in the desktop session → wait for `/api/v1/ping` to report `alive`. Never touches the MT5 terminal. |

Flow: push to `main` → CI runs → if green, both deploy workflows start and each
**waits for an approval click** on the `production` Environment (Actions tab →
the run → *Review deployments*). Approve only when the book is in a safe state —
a deploy restarts the bot (Linux) or drops the MT5 connection (Windows). Reject
to skip that deploy; the next approved one includes everything since.

The Windows workflow first checks (on the runner, without changing anything)
whether `mt5-rest-server/**` differs between the commit the Windows clone is on
and the new one. If not, it ends there — no approval request, no restart.

Both can also be run by hand: Actions tab → workflow → *Run workflow*, type
`deploy` (or `gh workflow run "Deploy — Linux (bot + dashboard)" -f confirm=deploy`).
A manual Windows run always deploys.

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
- `MT5_BRIDGE_INSTANCES` — bridges to restart, as `<env file suffix>=<port>` pairs (default `account1=8001`, i.e. `.env.account1` on port 8001, matching `start-all.bat`). With more accounts: `account1=8001,account2=8002`.

Confirm both before the first deploy — the guides mention more than one location historically (`~/telebot` vs `/home/murx/apps/telebot`). Run the discovery snippets in "Retrieving the values" below.

### 3. Windows self-hosted runner (for the bridge deploy)

The bridge must run in the same desktop session as the MT5 terminal (Issue #10 in
`issues-solved.md`), so the runner is **not** installed as a Windows service. It
runs as the auto-logged-in desktop user (the same account as `start-all.bat`),
started from the Startup folder:

1. RDP in as that user. Install PowerShell 7 if `pwsh -v` fails (the workflow
   uses `shell: pwsh`): `winget install --id Microsoft.PowerShell -e`.
2. GitHub → Settings → Actions → Runners → *New self-hosted runner* → Windows x64.
   Run the shown download commands in `C:\actions-runner` (keep it outside the
   repo clone).
3. Run `.\config.cmd --url … --token …` as shown, and when asked:
   - labels: `mt5-bridge` (`self-hosted` and `windows` are added automatically)
   - **run as service: N**
4. Start it at logon, minimized, next to `start-all.bat`:
   ```powershell
   $s = (New-Object -ComObject WScript.Shell).CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\GitHubRunner.lnk")
   $s.TargetPath = 'C:\actions-runner\run.cmd'; $s.WorkingDirectory = 'C:\actions-runner'; $s.WindowStyle = 7; $s.Save()
   ```
   Then start it now: `Start-Process C:\actions-runner\run.cmd -WorkingDirectory C:\actions-runner -WindowStyle Minimized`.
   It should show as *Idle* under Settings → Actions → Runners.

Like the terminal, the runner keeps running when you **Disconnect** RDP and stops
if you **Log off**.

The deploy restarts only the bridge. It stops whatever listens on each bridge
port, then launches the bridge through a scheduled task
(`telebot-bridge-<account>`, Interactive logon) so it runs in the desktop session
and survives the end of the job. Deployed bridges log to
`mt5-rest-server\logs\<account>.log` (watch with
`Get-Content C:\Apps\telebot\mt5-rest-server\logs\account1.log -Wait`). After a
reboot, `start-all.bat` starts the bridge the old way again; the next deploy takes
over from it.

The Windows clone must be the same repo, and the bridge venv must live at
`mt5-rest-server\venv`.

### 4. Approval gate (required)

Create an Environment named `production` (Settings → Environments) with **required reviewers = you**. Both deploy workflows reference it. **Without required reviewers, every green push to `main` deploys immediately** — this gate is what keeps a push from restarting the bot mid-trade.

### 5. Fork PR safety (public repo + self-hosted runner)

The repo is public and the Windows runner can restart the bridge services, so code from a stranger's pull request must never run on it. Set Settings → Actions → General → *Fork pull request workflows from outside collaborators* → **Require approval for all outside collaborators**, and never approve a workflow run on a PR you haven't read. The deploy workflows themselves only trust pushes to this repo's `main`.

## Notes

- The VPS's own git credentials handle `git pull` (the repos are already cloned/authenticated). The deploy key above is only for SSH access, not repo access.
- The Linux deploy only rebuilds the `telebot` container; shared postgres/nginx are on external networks and untouched.
- First-time deploy caveats from the audit still apply: set `TRUST_PROXY=true` and expect a one-time re-login (see `project_wave3_auth_deploy_reqs`).
