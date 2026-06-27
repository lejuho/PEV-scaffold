# PEV Scaffold

Planner-Executor-Verifier local scaffold for running a Claude executor, a Codex reviewer, Telegram/Hermes controls, and a small mobile PEV dashboard around a single project.

This repo is a packaging layer. It contains portable scripts/dashboard files from a live Raspberry Pi setup plus generic multi-agent templates under `templates/multi-agent-artifact/`.

## Start Here

- Human/operator/agent runbook: [`docs/RUNBOOK.md`](docs/RUNBOOK.md)
- Template bundle guide: [`templates/multi-agent-artifact/README.md`](templates/multi-agent-artifact/README.md)
- Hook registration details: [`templates/multi-agent-artifact/HOOKS_REGISTRATION.md`](templates/multi-agent-artifact/HOOKS_REGISTRATION.md)

Read the runbook first if you need to know what Claude and Codex should do, where `.claude`, `.codex`, and `AGENTS.md` go in the target project, or how to operate one full cycle.

## Contents

- `docs/RUNBOOK.md`
  - first-stop operating guide for humans, Claude, and Codex.
- `scripts/`
  - `ensure-pev-tmux.sh`: creates stable tmux sessions for Claude and Codex.
  - `hermes-cycle-bot.py`: Telegram/Hermes bridge for `/tail`, `/say`, `/implement`, `/fix`, `/review`, `/recheck`, `/merge`, and flow commands.
  - `claude-auto-responder.py`: watches Claude's tmux pane for approval prompts and idle notifications.
  - `claude-auto-confirm.py`, `telegram-claude-check.py`: older helper scripts kept for reference.
- `dashboard/`
  - `server.py`: local HTTP API and static file server.
  - `static/`: mobile-first dashboard UI.
  - `projects.example.json`: project list template.
- `systemd/`
  - user services for tmux boot, Hermes bot, Claude auto responder, and PEV dashboard.
- `config/hermes.env.example`
  - local env template. Copy to `config/hermes.env`; never commit real tokens.
- `templates/multi-agent-artifact/`
  - generic `AGENTS.md`, `CLAUDE.md`, hooks, marker contracts, and plan templates.

## Install

Clone where the systemd unit paths expect it:

```bash
git clone https://github.com/lejuho/PEV-scaffold.git /home/pi/PEV-scaffold
cd /home/pi/PEV-scaffold
```

Create local config:

```bash
cp config/hermes.env.example config/hermes.env
cp dashboard/projects.example.json dashboard/projects.json
chmod +x scripts/*.sh scripts/*.py
```

Edit:

```bash
nano config/hermes.env
nano dashboard/projects.json
```

Required values:

- `HERMES_ROOT`: project repo managed by the cycle system, for example `/home/pi/cairn`.
- `HERMES_LOG_DIR`: usually `$HERMES_ROOT/logs`.
- `HERMES_TELEGRAM_TOKEN`, `HERMES_CHAT_ID`: optional unless Telegram control is used.
- `PEV_CLAUDE_BIN`, `PEV_CODEX_BIN`: local Claude/Codex executable paths.
- `PEV_DASHBOARD_HOST`: `127.0.0.1` for local-only, or a private VPN/Tailscale IP.

Install user services:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pev-tmux.service
systemctl --user enable --now hermes-cycle-bot.service
systemctl --user enable --now claude-auto-responder.service
systemctl --user enable --now pev-dashboard.service
```

## Tmux Model

`pev-tmux.service` runs:

- `cairn-claude:0`
- `codex-hermes:0`

Default Claude startup:

```bash
claude --continue --dangerously-skip-permissions
```

Default Codex startup:

```bash
codex --no-alt-screen
```

To attach:

```bash
tmux attach -t cairn-claude
tmux attach -t codex-hermes
```

To recreate missing sessions:

```bash
scripts/ensure-pev-tmux.sh
```

Claude/Codex commands are launched without `exec`, so closing the CLI leaves a shell in the tmux pane. Restart from that shell with the same flags if needed.

## Dashboard

Run manually:

```bash
cd /home/pi/PEV-scaffold/dashboard
PEV_DASHBOARD_HOST=127.0.0.1 PEV_DASHBOARD_PORT=8765 python3 server.py
```

Open:

```text
http://127.0.0.1:8765
```

If bound to Tailscale/VPN:

```text
http://<private-ip>:8765
```

Dashboard actions:

- `Status`, `Safe`, `Full`, `Off`: flow mode commands.
- `Implement`, `Fix`, `Review`, `Recheck`, `Merge`: cycle movement.
- `Tail Claude`, `Tail Codex`: tmux pane tails.
- `Enter Claude`, `Enter Codex`: submits current pane input.
- `Create Done`: manually creates expected executor done signal.
- Mobile quickbar: fixed bottom actions for the selected project.

The dashboard now returns explicit `tmux capture failed ...` text instead of silently showing an empty tail when the tmux session is missing.

## Telegram/Hermes Commands

Common commands:

```text
/tail claude
/tail codex
/say claude <text>
/say codex <text>
/enter claude
/enter codex
/flow status
/flow safe
/flow full
/flow off
/implement
/fix
/review
/recheck
/merge
```

Flow state is stored in:

```text
$HERMES_ROOT/logs/hermes-flow.json
$HERMES_ROOT/logs/hermes-state.json
$HERMES_ROOT/logs/hermes-events.jsonl
```

## Project Template Setup

Copy generic artifacts into a project repo:

```bash
cp templates/multi-agent-artifact/AGENTS.md /path/to/project/AGENTS.md
cp templates/multi-agent-artifact/CONTRACT_MARKERS.md /path/to/project/CONTRACT_MARKERS.md
mkdir -p /path/to/project/.claude/hooks
cp templates/multi-agent-artifact/*.sh /path/to/project/.claude/hooks/
chmod +x /path/to/project/.claude/hooks/*.sh
```

Use `templates/multi-agent-artifact/plan-template.md` for new cycles.

Cycle shape:

```text
.review/cycle-N/
  plan.md
  advisor-feedback/step-NNN.md
  review-v1.md
  executor/pass-001-done.json
```

Executor completion marker:

```text
[[EXECUTOR_DONE:cycle=N pass=NNN kind=implement]]
```

Review append boundary:

```text
<!-- RESOLVED-BOUNDARY · 위=Codex immutable, 아래=Executor append-only · check-resolved-immutable.sh가 강제 -->
```

## Safety

- Do not commit `config/hermes.env`, `dashboard/projects.json`, or `dashboard/state.json`.
- Bind dashboard to `127.0.0.1` or private VPN/Tailscale only.
- `--dangerously-skip-permissions` bypasses Claude Code approvals. Use only in an isolated local environment you can restore.
- Telegram tokens and chat IDs must live only in `config/hermes.env`.

## Verify

```bash
python3 dashboard/server.py --check
bash -n scripts/ensure-pev-tmux.sh
systemd-analyze verify --user systemd/*.service
```

Runtime checks:

```bash
tmux list-sessions
tmux list-panes -a -F '#{session_name}:#{window_index}.#{pane_index} #{pane_id} #{pane_current_command}'
curl -sS http://127.0.0.1:8765/api/projects
```
