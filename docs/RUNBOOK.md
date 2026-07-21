# PEV Operator Runbook

This is the first document for a new human operator, Claude executor, or Codex planner/reviewer. It explains what to copy into a target project, how agents know their roles, and how to run one cycle from start to merge.

If an agent only receives `README.md`, it should follow the `Start Here` link to this runbook and execute the relevant setup sections in order.

## Mental Model

PEV means Planner, Executor, Verifier.

- Codex as Planner writes `.review/cycle-N/plan.md`.
- Claude as Executor implements the plan or fixes review findings.
- Codex as Cycle Reviewer writes `.review/cycle-N/review-vN.md`.
- Opus/Advisor is called by Claude during executor steps and its feedback is saved under `.review/cycle-N/advisor-feedback/`.
- Hermes and the dashboard only route commands to the tmux panes and track state.

Markdown artifacts are the source of truth. Conversation history is not.

## Target Project Bootstrap

Run these from this scaffold repo. Replace `/path/to/project` with the repo to be managed.

```bash
PROJECT=/path/to/project

cp templates/multi-agent-artifact/AGENTS.md "$PROJECT/AGENTS.md"
cp templates/multi-agent-artifact/CONTRACT_MARKERS.md "$PROJECT/CONTRACT_MARKERS.md"
mkdir -p "$PROJECT/.review/_templates"
cp templates/multi-agent-artifact/plan-template.md "$PROJECT/.review/_templates/plan-template.md"

mkdir -p "$PROJECT/.claude/hooks"
cp templates/multi-agent-artifact/*.sh "$PROJECT/.claude/hooks/"
chmod +x "$PROJECT/.claude/hooks/"*.sh

mkdir -p "$PROJECT/.codex/hooks"
cp templates/multi-agent-artifact/block-dangerous.sh "$PROJECT/.codex/hooks/"
cp templates/multi-agent-artifact/track-failures.sh "$PROJECT/.codex/hooks/"
cp templates/multi-agent-artifact/auto-format.sh "$PROJECT/.codex/hooks/"
cp templates/multi-agent-artifact/force-advisor-check.sh "$PROJECT/.codex/hooks/"
cp templates/multi-agent-artifact/check-cycle-cap.sh "$PROJECT/.codex/hooks/"
chmod +x "$PROJECT/.codex/hooks/"*.sh
```

If the target repo already has `AGENTS.md`, `.claude/`, `.codex/`, or `.gitignore`, do not overwrite blindly. Merge sections manually.

Append this to target `.gitignore` when useful:

```bash
cat templates/multi-agent-artifact/.gitignore.fragment >> "$PROJECT/.gitignore"
```

## AGENTS.md Setup

`AGENTS.md` is the shared source of truth for Codex and Claude.

After copying, edit these sections before running a real cycle:

- `Architecture`: target stack, storage, tests, deployment, external APIs.
- `Commands`: exact install/build/test/check commands.
- `Prohibited Patterns`: domain-specific skill mapping.
- `Testing & Verify`: exact automatic checks and integration expectations.
- `Context Discipline`: codebase-map rules if the project needs broad exploration.

Minimum required lines in each cycle plan:

```markdown
Branch: feature/cycle-N-short-name
Skills: backend-fastify, frontend-react-pwa
```

If no domain skills exist yet, set `Skills: none` only for docs/config-only work.

## Claude Setup

Claude uses `.claude/CLAUDE.md` plus `.claude/settings.json`.

Create `.claude/CLAUDE.md` in target repo:

```markdown
# CLAUDE.md

Read ../AGENTS.md first. AGENTS.md is source of truth for architecture,
cycle workflow, artifact contracts, and prohibited patterns.

Claude role: Executor.
- Implement `.review/cycle-N/plan.md`.
- On BLOCKED review, append exactly one RESOLVED section below the
  RESOLVED-BOUNDARY in `review-vN.md`.
- Save advisor feedback under `.review/cycle-N/advisor-feedback/step-NNN.md`.
- Create `.review/cycle-N/executor/pass-NNN-done.json`.
- End completed work with `[[EXECUTOR_DONE:cycle=N pass=NNN kind=implement]]`
  or `[[EXECUTOR_DONE:cycle=N pass=NNN kind=fix]]`.
- Never edit Codex review text above RESOLVED-BOUNDARY.
- Never mutate plan.md mid-cycle unless escalation explicitly allows it.
```

Create or merge `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": ".claude/hooks/block-dangerous.sh" }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": ".claude/hooks/track-failures.sh" }
        ]
      },
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": ".claude/hooks/auto-format.sh" }
        ]
      },
      {
        "matcher": "Read",
        "hooks": [
          { "type": "command", "command": ".claude/hooks/check-context-budget.sh" }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": ".claude/hooks/force-advisor-check.sh" },
          { "type": "command", "command": ".claude/hooks/save-advisor-feedback.sh" },
          { "type": "command", "command": ".claude/hooks/check-resolved-immutable.sh" },
          { "type": "command", "command": ".claude/hooks/check-skill-loaded.sh" },
          { "type": "command", "command": ".claude/hooks/check-cycle-cap.sh" },
          { "type": "command", "command": ".claude/hooks/write-executor-done.sh" }
        ]
      }
    ]
  }
}
```

If `write-executor-done.sh` is not present in your template bundle, omit that hook.

## Codex Setup

Codex uses `AGENTS.md` plus `.codex/hooks.json`. Codex role is Planner and Cycle Reviewer, not Executor.

Create or merge `.codex/hooks.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": ".codex/hooks/block-dangerous.sh" }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": ".codex/hooks/track-failures.sh" }
        ]
      },
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": ".codex/hooks/auto-format.sh" }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": ".codex/hooks/force-advisor-check.sh" },
          { "type": "command", "command": ".codex/hooks/check-cycle-cap.sh" }
        ]
      }
    ]
  }
}
```

Codex should not use Claude-only Stop hooks:

- `save-advisor-feedback.sh`
- `check-resolved-immutable.sh`
- `check-skill-loaded.sh`
- `check-context-budget.sh`
- `write-executor-done.sh`

Codex writes new plan/review files. It must not append Executor RESOLVED sections.

## Scaffold Runtime Setup

Configure this scaffold:

```bash
cd /home/pi/PEV-scaffold
cp config/hermes.env.example config/hermes.env
cp dashboard/projects.example.json dashboard/projects.json
nano config/hermes.env
nano dashboard/projects.json
```

Important fields:

- `HERMES_ROOT`: target project root.
- `HERMES_CLAUDE_PANE`: usually `cairn-claude:0`.
- `HERMES_CODEX_PANE`: usually `codex-hermes:0`.
- `PEV_CLAUDE_ARGS`: default `--continue --dangerously-skip-permissions`.
- `PEV_CODEX_ARGS`: default `--no-alt-screen --dangerously-bypass-approvals-and-sandbox`.
- `PEV_DASHBOARD_HOST`: private bind address.

Install services:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pev-tmux.service
systemctl --user enable --now hermes-cycle-bot.service
systemctl --user enable --now claude-auto-responder.service
systemctl --user enable --now pev-dashboard.service
```

## Happy Path

1. Create a cycle plan as Codex Planner:

   ```text
   Write .review/cycle-N/selection.json from the selection template, comparing
   the top 2–5 remaining candidates. Then write plan.md for the chosen slice.
   Include Branch, Spec, Skills, and Selection lines.
   ```

   If the project uses Spec Kit, prepare the same handoff without an extension:

   ```bash
   scripts/pevctl.py import-spec --root /path/to/project --spec 001-feature
   ```

   Run the `/say codex ...` command printed by `import-spec`. The bridge only
   parses and indexes the upstream artifacts; Codex still chooses and scores
   the cycle slice, and `/speckit.implement` remains outside the PEV flow.

2. Start flow:

   ```text
   /flow safe
   ```

3. Ask Claude to implement:

   ```text
   /implement
   ```

4. Claude implements, saves advisor feedback, creates done JSON, and emits:

   ```text
   [[EXECUTOR_DONE:cycle=N pass=001 kind=implement]]
   ```

5. Ask Codex to review:

   ```text
   /review
   ```

6. If review is `BLOCKED`, ask Claude to fix:

   ```text
   /fix
   ```

7. Ask Codex to recheck:

   ```text
   /recheck
   ```

8. If review is `READY_TO_MERGE`, merge:

   ```text
   /merge
   ```

## Command Map

- `/tail claude`: show Claude executor pane.
- `/tail codex`: show Codex planner/reviewer pane.
- `/say claude <text>`: send direct text to Claude.
- `/say codex <text>`: send direct text to Codex.
- `/enter claude`: press Enter in Claude pane.
- `/enter codex`: press Enter in Codex pane.
- `/flow status`: show flow state.
- `/flow safe`: auto-advance until ready-to-merge, but do not merge automatically.
- `/flow full`: also request merge/next-cycle actions.
- `/flow off`: stop auto-advance.
- `/implement`: send implementation prompt to Claude.
- `/fix`: send review-fix prompt to Claude.
- `/review`: send first review prompt to Codex.
- `/recheck`: send next review prompt to Codex.
- `/merge`: ask Codex pane to merge when allowed.

## Artifact Checklist

Planner output:

```text
.review/cycle-N/selection.json
.review/cycle-N/plan.md
```

Executor output:

```text
.review/cycle-N/advisor-feedback/step-NNN.md
.review/cycle-N/executor/pass-NNN-done.json
```

Reviewer output:

```text
.review/cycle-N/review-vN.md
```

State/logs:

```text
$HERMES_ROOT/logs/hermes-state.json
$HERMES_ROOT/logs/hermes-flow.json
$HERMES_ROOT/logs/hermes-events.jsonl
```

## Agent Prompts

Claude first prompt when manually driving:

```text
You are Executor for the active PEV cycle. Read AGENTS.md and
.review/cycle-N/plan.md. Implement only plan scope. Save advisor feedback per
step. Create the executor done JSON and final EXECUTOR_DONE marker when complete.
```

Claude blocked-fix prompt:

```text
You are Executor fixing Codex review findings. Read AGENTS.md and
.review/cycle-N/review-vN.md. Append RESOLVED only below RESOLVED-BOUNDARY.
Do not edit Codex review body. Create pass-(N+1)-done.json and final marker.
```

Codex review prompt:

```text
You are clean-context Cycle Reviewer. Read AGENTS.md, plan.md, and git diff.
Do not read Executor reasoning. Verify implementation from spec backwards.
Write .review/cycle-N/review-vN.md with verdict, findings, sprint contract
check, automatic checks, and changes outside plan.
```

## Drivers: tmux vs headless

Agent I/O goes through `scripts/pev_runner.py`. Two drivers, selected with
`PEV_DRIVER` in `hermes.env` (or `"driver"` in the dashboard `projects.json`):

- `tmux` (default): original behavior — interactive CLIs in tmux panes.
- `headless`: no tmux. Every `/implement`, `/fix`, `/say` becomes one
  background `claude -p --resume <session-id>` / `codex exec resume <id>`
  invocation. Session IDs persist in `logs/pev-sessions.json`, so a project
  survives reboots and can be stopped/resumed at any time with full
  conversation history. Per-turn output lands in `logs/pev-turns/`.

Runner CLI (works standalone):

```bash
scripts/pev_runner.py --root /path/to/project status
scripts/pev_runner.py --root /path/to/project send claude "..."
scripts/pev_runner.py --root /path/to/project tail claude
scripts/pev_runner.py --root /path/to/project stop claude    # turn stops, session kept
scripts/pev_runner.py --root /path/to/project harvest        # adopt latest tmux-era sessions
```

Migrating a tmux project to headless: run `harvest` once (it picks up the most
recent Claude session for the project directory and the most recent Codex
session whose cwd matches), then set `PEV_DRIVER=headless`. Headless runs
inherit no interactive model choice — set `PEV_CLAUDE_MODEL` /
`PEV_CODEX_MODEL` explicitly in `hermes.env` if the default is wrong.

**tmux self-heal.** With the tmux driver, `init` creates the sessions, and if a
session later dies (reboot, kill) the next `send`/`enter` **recreates it** and
returns "CLI is booting, resend in a few seconds" instead of writing into a
half-booted CLI — resend once (the flow's next tick does this automatically).
`tail` does not spin up a CLI; it just reports the pane is gone, and the
dashboard shows `alive:false`. The boot-time `pev-tmux.service` still pre-warms
sessions so the first real command usually finds them already up.

## Bootstrapping a new project (pevctl)

`scripts/pevctl.py init` automates the whole Target Project Bootstrap section:

```bash
# new GitHub repo → clone → artifacts → commit → push → dashboard register
scripts/pevctl.py init myproj --source new --visibility private \
  --stack "FastAPI + SQLite + React PWA"

# existing remote / existing local directory
scripts/pevctl.py init myproj --source clone --repo https://github.com/me/myproj.git
scripts/pevctl.py init myproj --source local --dest /home/pi/myproj
```

`--stack` runs one `claude -p --model sonnet` call that fills the
Architecture/Commands/Testing sections of AGENTS.md. Existing files are never
overwritten (reported as "kept existing" — merge manually). The dashboard has
the same flow behind the **＋ New** button; progress streams into the console
panel via `/api/projects/init` + `/api/init/<job>`.

## Deployment (Tailscale-exposed, per-project)

The scaffold provides the *trigger + exposure harness*; each project fills the
*build/start* specifics in a cycle. Concretely, `init` provisions:

- a free port in `8800–8899` (recorded as `port` in `projects.json`, no
  collisions — `PEV_DEPLOY_PORT_BASE`/`_END` to change the range),
- `deploy/redeploy.sh` (skeleton: pull → **TODO build** → restart service →
  **TODO health check**), and
- `deploy/<name>.service` (systemd --user template binding `HOST=<tailnet-ip>`
  `PORT=<port>`; `ExecStart=/bin/false` placeholder). Tailnet IP defaults to
  this box (`PEV_TAILNET_IP`, `100.96.172.67`).

A project's PEV cycle fills the TODO build/start commands (the Executor knows
the stack from AGENTS.md), installs+enables the unit
(`systemctl --user enable --now <name>`), and makes the server bind to
`$HOST:$PORT`. Because Tailscale is already up on the box, there's no external
console step — the cycle completes the whole deploy path.

The dashboard's 🚀 **Deploy** button runs `deploy/redeploy.sh` in the
background (`POST /api/projects/<id>/deploy` → `/api/deploy/<job>`), streaming
output to the console. `redeploy.sh`'s own `pnpm verify` (or equivalent) is the
CI gate; Codex's READY_TO_MERGE is the second gate. Existing projects can opt
in by setting `deployScript` in their `projects.json` entry (e.g. cairn's
`deploy/scripts/redeploy-production.sh`).

## Recovery

Empty dashboard tail:

```bash
tmux list-sessions
tmux list-panes -a -F '#{session_name}:#{window_index}.#{pane_index} #{pane_id} #{pane_current_command}'
scripts/ensure-pev-tmux.sh
```

Stale `%pane_id` after reboot:

```bash
grep HERMES_.*_PANE config/hermes.env
```

Use stable targets, not `%0` or `%4`:

```text
HERMES_CLAUDE_PANE=cairn-claude:0
HERMES_CODEX_PANE=codex-hermes:0
```

Services not reading updated env:

```bash
systemctl --user restart pev-tmux.service hermes-cycle-bot.service claude-auto-responder.service pev-dashboard.service
```

Dashboard bind check:

```bash
systemctl --user status pev-dashboard.service --no-pager --full
curl -sS http://127.0.0.1:8765/api/projects
```

Hook smoke test in target project:

```bash
for hook in .claude/hooks/*.sh; do printf '{}\n' | "$hook"; done
bash .claude/hooks/check-marker-sync.sh
```

If the same error signature appears twice, stop repeating the same command. Inspect root cause or ask a clean-context advisor/reviewer.

## Meta-cycle operation (self-improvement loop)

The metrics lab (`dashboard/metrics.py` + the dashboard metrics block) measures
PEV so PEV can improve itself. Every ~10 cycles, run one **meta-cycle**: a
retrospective that turns those numbers into concrete changes to the PEV machine.

**When to run.** The dashboard shows a "meta-cycle suggested" banner when a
project's `totals.cycles` is a multiple of 10 and no meta-cycle has been logged
in the last 10 cycles. The banner's button only **copies the meta-cycle prompt
to the clipboard** — it never auto-starts anything. A human decides to run it.

**How to run.**

1. Refresh the metrics block and read `totals`, the sparkline, the history
   table, and the failure-tag distribution.
2. Open `templates/multi-agent-artifact/meta-cycle-template.md`, paste in the
   baseline numbers, and work through it. Product = ≤3 concrete diff proposals,
   each naming a target metric and value (e.g. "first-pass 0.70 → 0.80, remeasure
   after 10 cycles").
3. Apply the agreed diffs as ordinary cycles in the following iterations.

**Record every meta-cycle** by appending one line to `logs/meta-cycles.jsonl`:

```bash
python3 - <<'PY'
import json, datetime, pathlib
line = {
    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    "cyclesAt": 82,                       # totals.cycles at the moment of change
    "changes": ["no-new-deps assertion in AGENTS.md"],
    "baseline": {                         # totals snapshot for later comparison
        "firstPassRate": 0.37, "autonomyHours": 136.1,
        "costUsd": 367.2, "reworkCostUsd": 115.4,
    },
}
p = pathlib.Path("logs/meta-cycles.jsonl")
with p.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(line, ensure_ascii=False) + "\n")
print("appended", p)
PY
```

The `baseline` snapshot is what the *next* meta-cycle diffs against to judge
whether the previous change actually moved the metric it targeted. Without this
record, "did it help?" is unanswerable and the loop degrades into guesswork.
