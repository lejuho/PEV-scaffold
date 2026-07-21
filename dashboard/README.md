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

## Usage and API-equivalent cost

The dashboard reads subscription windows server-side from the credentials
already managed by Claude Code and Codex. `/api/usage` returns only normalized
percentages and reset times; OAuth/access tokens are never sent to the browser.
Bind the dashboard only to localhost or a private VPN as described above.

Cycle metrics stream Claude JSONL transcripts of any size, deduplicate repeated
Claude `message.id` usage snapshots, and add Codex `token_count` deltas from
`~/.codex/sessions`. Amounts are API-equivalent estimates, not charges incurred
by a Claude/ChatGPT subscription. `pricing.example.json` contains dated public
list prices; copy it to `pricing.json` when you need local overrides.

New cycles may also carry `.review/cycle-N/selection.json`. The Planner records
the top candidate set, score rubric, evidence and duration/cost/first-pass
predictions before implementation. Metrics keep that prediction immutable and
compare it with the eventual result. `reworkCostUsd` means cost after a BLOCKED
verdict; first-pass review cost is reported as verification, not rework.

Relevant environment overrides:

- `CLAUDE_CREDENTIALS`: Claude Code credentials JSON path.
- `PEV_CODEX_BIN`: Codex CLI binary used for `account/rateLimits/read`.
- `CODEX_HOME`: Codex session log root (defaults to `~/.codex`).
- `PEV_USAGE_CACHE_SECONDS`: subscription usage cache lifetime (default 60).
