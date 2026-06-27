# PEV Dashboard

Planner-Executor-Verifier cycle dashboard for local projects.

This dashboard is intentionally outside individual repositories. A project keeps
its cycle source of truth (`AGENTS.md`, `.review/`, hooks, and scripts), while
PEV Dashboard keeps view-only metadata such as archived/hidden/pinned notes in
`state.json`.

## Run

```bash
cd /home/pi/PEV-scaffold/dashboard
python3 server.py
```

Then open:

```text
http://127.0.0.1:8765
```

## Systemd

```bash
mkdir -p ~/.config/systemd/user
cp /home/pi/PEV-scaffold/systemd/pev-dashboard.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pev-dashboard.service
```

## Project Config

Copy and edit `projects.json`:

```bash
cp projects.example.json projects.json
```

```json
{
  "projects": [
    {
      "id": "cairn",
      "name": "Cairn",
      "root": "/home/pi/cairn",
      "hermesScript": "/home/pi/PEV-scaffold/scripts/hermes-cycle-bot.py",
      "claudePane": "cairn-claude:0",
      "codexPane": "codex-hermes:0"
    }
  ]
}
```

## Safety

Bind to `127.0.0.1` or a private VPN/Tailscale interface only. This dashboard can
send commands to project tmux panes through each project's Hermes bridge.
