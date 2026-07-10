#!/usr/bin/env python3
"""pevctl — bootstrap and manage PEV projects.

`pevctl init` takes a project from nothing to PEV-ready in one command:

    # brand-new GitHub repo (created, cloned, scaffolded, pushed)
    pevctl.py init myproj --source new --visibility private

    # existing remote repo
    pevctl.py init myproj --source clone --repo https://github.com/me/myproj.git

    # existing local directory
    pevctl.py init myproj --source local --dest /home/pi/myproj

Steps: acquire repo → inject rule artifacts (AGENTS.md, hooks, .claude/.codex
config, plan templates) → optionally tailor AGENTS.md with a one-shot cheap
model call → commit/push → register in the dashboard projects.json → prepare
runner sessions. Existing files are never overwritten; they are reported as
skipped so you can merge manually (per RUNBOOK).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SCAFFOLD_ROOT = SCRIPT_DIR.parent
TEMPLATE_DIR = SCAFFOLD_ROOT / "templates" / "multi-agent-artifact"

# Project context: operator-supplied spec / design-system files that guide the
# agents. Two fixed categories, each a directory holding any number of files.
CONTEXT_CATEGORIES = {
    "spec": {
        "dir": "docs/spec",
        "exts": (".md", ".txt"),
        "default": "spec.md",
        "pointer": "- `docs/spec/` — product specifications. Read the relevant file before planning a cycle.",
    },
    "design": {
        "dir": "docs/design",
        "exts": (".md", ".css", ".txt", ".json"),
        "default": "design.md",
        "pointer": "- `docs/design/` — design-system tokens and UI rules. Read before building or changing UI.",
    },
}
CONTEXT_MARKER = "<!-- PEV_CONTEXT_POINTER -->"
CONTEXT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# force-advisor-check.sh is deliberately absent: the Step Advisor is the
# Executor's obligation (AGENTS.md role table), and Codex runs as Planner and
# Cycle Reviewer. Its Stop hook treats any staged file as a code change, so the
# Planner tripped it on the very plan.md it exists to write, then called an
# Advisor to escape the block.
CODEX_HOOKS = [
    "block-dangerous.sh",
    "track-failures.sh",
    "auto-format.sh",
    "check-cycle-cap.sh",
]

CLAUDE_SETTINGS = {
    "hooks": {
        "PreToolUse": [
            {"matcher": "Bash", "hooks": [
                {"type": "command", "command": ".claude/hooks/block-dangerous.sh"}]}
        ],
        "PostToolUse": [
            {"matcher": "Bash", "hooks": [
                {"type": "command", "command": ".claude/hooks/track-failures.sh"}]},
            {"matcher": "Edit|Write", "hooks": [
                {"type": "command", "command": ".claude/hooks/auto-format.sh"}]},
            {"matcher": "Read", "hooks": [
                {"type": "command", "command": ".claude/hooks/check-context-budget.sh"}]},
        ],
        "Stop": [
            {"hooks": [
                {"type": "command", "command": ".claude/hooks/force-advisor-check.sh"},
                {"type": "command", "command": ".claude/hooks/save-advisor-feedback.sh"},
                {"type": "command", "command": ".claude/hooks/check-resolved-immutable.sh"},
                {"type": "command", "command": ".claude/hooks/check-skill-loaded.sh"},
                {"type": "command", "command": ".claude/hooks/check-cycle-cap.sh"},
            ]}
        ],
    }
}

CODEX_HOOKS_JSON = {
    "hooks": {
        "PreToolUse": [
            {"matcher": "Bash", "hooks": [
                {"type": "command", "command": ".codex/hooks/block-dangerous.sh"}]}
        ],
        "PostToolUse": [
            {"matcher": "Bash", "hooks": [
                {"type": "command", "command": ".codex/hooks/track-failures.sh"}]},
            {"matcher": "Edit|Write", "hooks": [
                {"type": "command", "command": ".codex/hooks/auto-format.sh"}]},
        ],
        "Stop": [
            {"hooks": [
                {"type": "command", "command": ".codex/hooks/check-cycle-cap.sh"},
            ]}
        ],
    }
}

GITIGNORE_FRAGMENT = [
    "# PEV scaffold",
    "logs/",
    ".cairn/hermes.env",
    "__pycache__/",
    "*.pyc",
]


class StepLogger:
    def __init__(self, as_json: bool):
        self.as_json = as_json
        self.steps: list[dict[str, Any]] = []

    def log(self, step: str, detail: str = "", ok: bool = True) -> None:
        entry = {"step": step, "detail": detail, "ok": ok}
        self.steps.append(entry)
        if self.as_json:
            print(json.dumps(entry, ensure_ascii=False), flush=True)
        else:
            mark = "✓" if ok else "✗"
            print(f"{mark} {step}" + (f" — {detail}" if detail else ""), flush=True)


def run(args: list[str], cwd: Path | None = None, timeout: int = 120,
        check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, check=check)


def make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def copy_if_absent(src: Path, dst: Path, copied: list[str], skipped: list[str]) -> bool:
    if dst.exists():
        skipped.append(str(dst))
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    copied.append(str(dst))
    return True


def write_if_absent(dst: Path, content: str, copied: list[str], skipped: list[str]) -> bool:
    if dst.exists():
        skipped.append(str(dst))
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(content, encoding="utf-8")
    copied.append(str(dst))
    return True


# ---------------------------------------------------------------------------
# project context (spec / design-system files)


def validate_context(category: str, name: str) -> tuple[dict[str, Any], str]:
    """Return (category-config, safe-filename). Raises SystemExit on bad input."""
    cfg = CONTEXT_CATEGORIES.get(category)
    if not cfg:
        raise SystemExit(f"unknown context category: {category} (use {', '.join(CONTEXT_CATEGORIES)})")
    name = (name or "").strip() or cfg["default"]
    if not CONTEXT_NAME_RE.fullmatch(name) or "/" in name or ".." in name:
        raise SystemExit(f"invalid context filename: {name!r}")
    if not name.lower().endswith(cfg["exts"]):
        name += cfg["exts"][0]
    return cfg, name


def ensure_agents_pointer(dest: Path) -> bool:
    """Add the Project Context section to AGENTS.md once (idempotent)."""
    agents = dest / "AGENTS.md"
    text = agents.read_text(encoding="utf-8") if agents.exists() else "# AGENTS.md\n"
    if CONTEXT_MARKER in text:
        return False
    block = "\n".join([
        "",
        f"## Project Context {CONTEXT_MARKER}",
        "",
        "Operator-supplied context files. Follow just-in-time retrieval — read the",
        "relevant file when the task calls for it, not preemptively:",
        "",
        CONTEXT_CATEGORIES["spec"]["pointer"],
        CONTEXT_CATEGORIES["design"]["pointer"],
        "",
    ])
    if not text.endswith("\n"):
        text += "\n"
    agents.write_text(text + block, encoding="utf-8")
    return True


def inject_context(dest: Path, category: str, name: str, content: str) -> dict[str, Any]:
    """Write one context file under docs/<category>/ and ensure the AGENTS.md
    pointer exists. Returns metadata; does not commit."""
    cfg, safe_name = validate_context(category, name)
    target = dest / cfg["dir"] / safe_name
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    target.write_text(content, encoding="utf-8")
    pointer_added = ensure_agents_pointer(dest)
    rel = str(target.relative_to(dest))
    return {"path": rel, "category": category, "replaced": existed, "pointerAdded": pointer_added}


def list_context(dest: Path) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for category, cfg in CONTEXT_CATEGORIES.items():
        entries: list[dict[str, Any]] = []
        directory = dest / cfg["dir"]
        if directory.is_dir():
            for path in sorted(directory.iterdir()):
                if path.is_file():
                    try:
                        size = path.stat().st_size
                    except OSError:
                        size = 0
                    entries.append({"name": path.name, "path": str(path.relative_to(dest)), "bytes": size})
        out[category] = entries
    return out


# ---------------------------------------------------------------------------
# init steps


def acquire_repo(args: argparse.Namespace, dest: Path, log: StepLogger) -> None:
    if args.source == "local":
        if not dest.is_dir():
            raise SystemExit(f"local source requires existing directory: {dest}")
        if not (dest / ".git").exists():
            run(["git", "init", "-b", "main"], cwd=dest)
            log.log("git init", str(dest))
        else:
            log.log("repo found", str(dest))
        if args.repo:
            remotes = run(["git", "remote"], cwd=dest).stdout.split()
            if "origin" not in remotes:
                run(["git", "remote", "add", "origin", args.repo], cwd=dest)
                log.log("remote added", args.repo)
        return

    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"destination already exists and is not empty: {dest}")

    if args.source == "clone":
        if not args.repo:
            raise SystemExit("--repo <url> is required with --source clone")
        run(["git", "clone", args.repo, str(dest)], timeout=300)
        log.log("cloned", f"{args.repo} → {dest}")
        return

    # source == "new": create the empty repo on GitHub, then clone into dest.
    # `--clone` is a bare flag (clones into ./<name>); it can't target a path,
    # so create without it and clone explicitly to dest.
    repo_name = args.repo or args.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(["gh", "repo", "create", repo_name, f"--{args.visibility}"], cwd=dest.parent, timeout=300)
    run(["gh", "repo", "clone", repo_name, str(dest)], cwd=dest.parent, timeout=300)
    log.log("github repo created", f"{repo_name} ({args.visibility}) → {dest}")


def ensure_first_commit(dest: Path, name: str, log: StepLogger) -> None:
    head = run(["git", "rev-parse", "--verify", "HEAD"], cwd=dest, check=False)
    if head.returncode == 0:
        return
    readme = dest / "README.md"
    if not readme.exists():
        readme.write_text(f"# {name}\n", encoding="utf-8")
    run(["git", "add", "-A"], cwd=dest)
    run(["git", "commit", "-m", "chore: initial commit"], cwd=dest)
    log.log("initial commit", "README.md")


def scaffold_rev() -> str:
    """Scaffold commit this project was set up against (drift visibility)."""
    result = run(["git", "rev-parse", "--short", "HEAD"], cwd=SCAFFOLD_ROOT, check=False)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def inject_artifacts(dest: Path, driver: str, log: StepLogger,
                     claude_model: str = "", claude_effort: str = "") -> tuple[list[str], list[str]]:
    if not TEMPLATE_DIR.is_dir():
        raise SystemExit(f"template bundle missing: {TEMPLATE_DIR}")
    copied: list[str] = []
    skipped: list[str] = []

    copy_if_absent(TEMPLATE_DIR / "AGENTS.md", dest / "AGENTS.md", copied, skipped)
    copy_if_absent(TEMPLATE_DIR / "CONTRACT_MARKERS.md", dest / "CONTRACT_MARKERS.md", copied, skipped)
    copy_if_absent(TEMPLATE_DIR / "plan-template.md",
                   dest / ".review" / "_templates" / "plan-template.md", copied, skipped)
    copy_if_absent(TEMPLATE_DIR / "meta-cycle-template.md",
                   dest / ".review" / "_templates" / "meta-cycle-template.md", copied, skipped)

    copy_if_absent(TEMPLATE_DIR / "CLAUDE.md", dest / ".claude" / "CLAUDE.md", copied, skipped)
    # Advisor runs as a dedicated subagent: effort can ONLY be set in the
    # definition file, never per Agent-tool invocation.
    copy_if_absent(TEMPLATE_DIR / "advisor-agent.md", dest / ".claude" / "agents" / "advisor.md",
                   copied, skipped)
    for hook in sorted(TEMPLATE_DIR.glob("*.sh")):
        target = dest / ".claude" / "hooks" / hook.name
        if copy_if_absent(hook, target, copied, skipped):
            make_executable(target)
    write_if_absent(dest / ".claude" / "settings.json",
                    json.dumps(CLAUDE_SETTINGS, ensure_ascii=False, indent=2) + "\n", copied, skipped)

    for hook_name in CODEX_HOOKS:
        target = dest / ".codex" / "hooks" / hook_name
        if copy_if_absent(TEMPLATE_DIR / hook_name, target, copied, skipped):
            make_executable(target)
    write_if_absent(dest / ".codex" / "hooks.json",
                    json.dumps(CODEX_HOOKS_JSON, ensure_ascii=False, indent=2) + "\n", copied, skipped)

    # NOTE: the runner and hermes bridge are NOT copied into the project.
    # They are operator tooling, not product code. Copying them made every
    # project carry a stale fork (upstream fixes never propagated), created a
    # split brain against the dashboard's own runner import, let a cycle edit
    # the very machinery running it, and — worst — made the Planner read the
    # injected scripts as the project's subject matter. The project references
    # the scaffold via projects.json `hermesScript` + HERMES_ROOT instead.

    # runtime env for the hermes bridge / runner. Resolve bins to absolute
    # paths (searching common install dirs, not just this process's PATH) so a
    # headless service can find them even when launched from a restricted PATH.
    sys.path.insert(0, str(SCRIPT_DIR))
    from pev_runner import resolve_bin  # noqa: E402
    env_lines = [
        f"HERMES_ROOT={dest}",
        f"HERMES_LOG_DIR={dest / 'logs'}",
        f"PEV_DRIVER={driver}",
        f"PEV_SCAFFOLD_REV={scaffold_rev()}",
        f"PEV_CLAUDE_BIN={os.environ.get('PEV_CLAUDE_BIN') or resolve_bin('claude')}",
        f"PEV_CODEX_BIN={os.environ.get('PEV_CODEX_BIN') or resolve_bin('codex')}",
        "",
        "# Always pin the model. A headless `claude -p` with no --model silently",
        "# inherits the operator's default model (e.g. an Opus tier), which is the",
        "# wrong cost/role fit for the Executor (CLAUDE.md specifies Sonnet).",
        f"PEV_CLAUDE_MODEL={claude_model or DEFAULT_CLAUDE_MODEL}",
        f"PEV_CLAUDE_EFFORT={claude_effort or DEFAULT_CLAUDE_EFFORT}",
        "# PEV_CODEX_MODEL=",
        "",
        "# HERMES_TELEGRAM_TOKEN=",
        "# HERMES_CHAT_ID=",
    ]
    write_if_absent(dest / ".cairn" / "hermes.env", "\n".join(env_lines) + "\n", copied, skipped)

    gitignore = dest / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    additions = [line for line in GITIGNORE_FRAGMENT if line not in existing]
    if additions:
        with gitignore.open("a", encoding="utf-8") as fh:
            if existing and existing[-1].strip():
                fh.write("\n")
            fh.write("\n".join(additions) + "\n")
        copied.append(str(gitignore) + " (appended)")

    (dest / "logs").mkdir(exist_ok=True)
    log.log("artifacts injected", f"{len(copied)} new, {len(skipped)} kept as-is")
    for path in skipped:
        log.log("kept existing", path)
    return copied, skipped


# ---------------------------------------------------------------------------
# deploy skeleton (Tailscale-exposed systemd service + redeploy script)

# Executor role model. Never leave this unset: a headless `claude -p` with no
# --model inherits the operator's default (possibly an Opus tier).
DEFAULT_CLAUDE_MODEL = os.environ.get("PEV_DEFAULT_CLAUDE_MODEL", "sonnet")
# Executor session effort (low|medium|high|xhigh|max). Empty = CLI default.
# The Advisor subagent gets its own effort from .claude/agents/advisor.md.
DEFAULT_CLAUDE_EFFORT = os.environ.get("PEV_DEFAULT_CLAUDE_EFFORT", "")

TAILNET_IP = os.environ.get("PEV_TAILNET_IP", "100.96.172.67")
DEPLOY_PORT_BASE = int(os.environ.get("PEV_DEPLOY_PORT_BASE", "8800"))
DEPLOY_PORT_END = int(os.environ.get("PEV_DEPLOY_PORT_END", "8900"))

REDEPLOY_SKELETON = """#!/usr/bin/env bash
# PEV redeploy for __NAME__ — fill the TODO build/start steps for this stack.
# Triggered by the dashboard 🚀 Deploy button, or run directly.
set -Eeuo pipefail
cd "$(dirname "$0")/.."   # -> project root

SERVICE="${PEV_DEPLOY_SERVICE:-__NAME__}"
HOST=__TAILNET_IP__
PORT=__PORT__

echo "==> pull"
git pull --ff-only || echo "(skip pull)"

# TODO: install deps  (e.g. corepack pnpm install --frozen-lockfile)
# TODO: build         (e.g. corepack pnpm -r build; interpreted servers may skip)

echo "==> restart ${SERVICE}"
systemctl --user restart "${SERVICE}.service"

# TODO: health check  (e.g. curl -fsS "http://${HOST}:${PORT}/health")
echo "==> deployed -> http://${HOST}:${PORT} (tailnet)"
"""

SERVICE_SKELETON = """[Unit]
Description=__NAME__ (PEV-deployed)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=__ROOT__
Environment=HOST=__TAILNET_IP__
Environment=PORT=__PORT__
# TODO: set ExecStart to your server start command; bind it to $HOST:$PORT.
#   node:   ExecStart=/usr/bin/node server/dist/index.js
#   python: ExecStart=/usr/bin/python3 server.py
ExecStart=/bin/false
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def inject_deploy(dest: Path, name: str, port: int, log: StepLogger) -> None:
    sub = {"__NAME__": name, "__ROOT__": str(dest), "__PORT__": str(port), "__TAILNET_IP__": TAILNET_IP}

    def fill(text: str) -> str:
        for key, value in sub.items():
            text = text.replace(key, value)
        return text

    copied: list[str] = []
    skipped: list[str] = []
    sh = dest / "deploy" / "redeploy.sh"
    if write_if_absent(sh, fill(REDEPLOY_SKELETON), copied, skipped):
        make_executable(sh)
    write_if_absent(dest / "deploy" / f"{name}.service", fill(SERVICE_SKELETON), copied, skipped)
    log.log("deploy skeleton", f"port {port} -> {TAILNET_IP} ({len(copied)} new, {len(skipped)} kept)")
    for path in skipped:
        log.log("kept existing", path)


def tailor_agents_md(dest: Path, stack: str, log: StepLogger) -> None:
    claude_bin = os.environ.get("PEV_CLAUDE_BIN", shutil.which("claude") or "claude")
    prompt = (
        "You are setting up AGENTS.md for a new PEV-managed project. "
        f"The operator describes the project as: {stack!r}. "
        "Edit ONLY these sections of AGENTS.md in place to match that description: "
        "Architecture, Commands, Testing & Verify. Keep every other section untouched. "
        "If exact commands are unknowable, write the most likely ones and mark them TODO-verify. "
        "Do not create new files. Do not touch any file except AGENTS.md."
    )
    try:
        result = run(
            [claude_bin, "-p", prompt, "--model", "sonnet", "--dangerously-skip-permissions",
             "--output-format", "text"],
            cwd=dest, timeout=600, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.log("AGENTS.md tailoring failed", str(exc), ok=False)
        return
    if result.returncode == 0:
        log.log("AGENTS.md tailored", f"stack: {stack}")
    else:
        log.log("AGENTS.md tailoring failed", (result.stderr or result.stdout)[-300:], ok=False)


def commit_and_push(dest: Path, push: bool, log: StepLogger) -> None:
    status = run(["git", "status", "--porcelain"], cwd=dest).stdout.strip()
    if status:
        run(["git", "add", "-A"], cwd=dest)
        run(["git", "commit", "-m", "chore: add PEV multi-agent scaffold"], cwd=dest)
        log.log("committed", "chore: add PEV multi-agent scaffold")
    else:
        log.log("commit skipped", "working tree clean")
    if not push:
        return
    remotes = run(["git", "remote"], cwd=dest).stdout.split()
    if "origin" not in remotes:
        log.log("push skipped", "no origin remote")
        return
    branch = run(["git", "branch", "--show-current"], cwd=dest).stdout.strip() or "main"
    result = run(["git", "push", "-u", "origin", branch], cwd=dest, timeout=300, check=False)
    if result.returncode == 0:
        log.log("pushed", f"origin/{branch}")
    else:
        log.log("push failed", (result.stderr or result.stdout)[-300:], ok=False)


def default_projects_file() -> Path:
    env = os.environ.get("PEV_PROJECTS")
    if env:
        return Path(env)
    live = Path("/home/pi/PEV-dashboard/projects.json")
    if live.exists():
        return live
    return SCAFFOLD_ROOT / "dashboard" / "projects.json"


def projects_file_path(args: argparse.Namespace) -> Path:
    return Path(args.projects_file) if args.projects_file else default_projects_file()


def load_projects_list(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except json.JSONDecodeError:
        data = {}
    projects = data.get("projects") if isinstance(data, dict) else None
    return projects if isinstance(projects, list) else []


def assign_deploy_port(args: argparse.Namespace) -> int:
    """Next free port in the deploy range, avoiding ports already in projects.json."""
    used = set()
    for entry in load_projects_list(projects_file_path(args)):
        try:
            used.add(int(entry.get("port")))
        except (TypeError, ValueError):
            continue
    for port in range(DEPLOY_PORT_BASE, DEPLOY_PORT_END):
        if port not in used:
            return port
    return DEPLOY_PORT_BASE  # range exhausted — fall back (operator resolves)


def register_project(args: argparse.Namespace, dest: Path, log: StepLogger, port: int) -> None:
    path = projects_file_path(args)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"projects": []}
    except json.JSONDecodeError:
        data = {"projects": []}
    projects = data.setdefault("projects", [])
    if any(p.get("id") == args.name for p in projects):
        log.log("dashboard registration skipped", f"id '{args.name}' already in {path}")
        return
    entry: dict[str, Any] = {
        "id": args.name,
        "name": args.display_name or args.name,
        "root": str(dest),
        "hermesScript": str(SCRIPT_DIR / "hermes-cycle-bot.py"),
        "driver": args.driver,
        "port": port,
        "deployScript": "deploy/redeploy.sh",
    }
    if args.driver == "tmux":
        entry["claudePane"] = f"{args.name}-claude:0"
        entry["codexPane"] = f"{args.name}-codex:0"
    # Always record the model — an unset one means headless inherits the
    # operator's default model, which is the wrong role/cost fit.
    entry["claudeModel"] = args.claude_model or DEFAULT_CLAUDE_MODEL
    if args.claude_effort or DEFAULT_CLAUDE_EFFORT:
        entry["claudeEffort"] = args.claude_effort or DEFAULT_CLAUDE_EFFORT
    projects.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log.log("dashboard registered", f"{args.name} in {path} (port {port})")


def prepare_sessions(dest: Path, driver: str, log: StepLogger) -> None:
    sys.path.insert(0, str(SCRIPT_DIR))
    from pev_runner import AgentRunner, RunnerConfig  # noqa: E402

    cfg = RunnerConfig.from_env(dest)
    cfg.root = dest
    cfg.log_dir = dest / "logs"
    cfg.driver = driver
    runner = AgentRunner(cfg)
    for agent in ("claude", "codex"):
        try:
            log.log(f"session {agent}", runner.start(agent))
        except (OSError, subprocess.SubprocessError) as exc:
            log.log(f"session {agent} failed", str(exc), ok=False)


def load_context_entries(args: argparse.Namespace) -> list[dict[str, str]]:
    """Read context entries from --context-json (a file path or '-' for stdin)."""
    if not getattr(args, "context_json", None):
        return []
    raw = sys.stdin.read() if args.context_json == "-" else Path(args.context_json).read_text(encoding="utf-8")
    data = json.loads(raw) if raw.strip() else []
    if not isinstance(data, list):
        raise SystemExit("--context-json must be a JSON array of {category,name,content}")
    return data


def inject_context_entries(dest: Path, entries: list[dict[str, str]], log: StepLogger) -> None:
    for entry in entries:
        category = str(entry.get("category") or "")
        content = str(entry.get("content") or "")
        try:
            result = inject_context(dest, category, str(entry.get("name") or ""), content)
            log.log("context added", f"{result['path']} ({'replaced' if result['replaced'] else 'new'})")
        except SystemExit as exc:
            log.log("context failed", str(exc), ok=False)


def cmd_init(args: argparse.Namespace) -> int:
    log = StepLogger(args.json)
    dest = Path(args.dest).expanduser().resolve() if args.dest else Path.home() / args.name
    context_entries = load_context_entries(args)
    port = assign_deploy_port(args)
    acquire_repo(args, dest, log)
    ensure_first_commit(dest, args.name, log)
    inject_artifacts(dest, args.driver, log, args.claude_model or "", args.claude_effort or "")
    inject_deploy(dest, args.name, port, log)
    if args.stack:
        tailor_agents_md(dest, args.stack, log)
    if context_entries:
        inject_context_entries(dest, context_entries, log)
    commit_and_push(dest, push=not args.no_push, log=log)
    register_project(args, dest, log, port)
    prepare_sessions(dest, args.driver, log)
    summary = {
        "ok": all(s["ok"] for s in log.steps),
        "root": str(dest),
        "driver": args.driver,
        "port": port,
        "startedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "steps": log.steps,
        "next": [
            "Review AGENTS.md sections (Architecture/Commands/Testing) before the first cycle.",
            f"Create the first plan: {dest}/.review/cycle-1/plan.md",
            f"Wire deployment in a cycle: fill deploy/redeploy.sh + deploy/{args.name}.service (binds {TAILNET_IP}:{port}), then use the 🚀 Deploy button.",
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2) if not args.json
          else json.dumps({"summary": summary}, ensure_ascii=False), flush=True)
    return 0 if summary["ok"] else 1


def cmd_context(args: argparse.Namespace) -> int:
    dest = Path(args.root).expanduser().resolve()
    if not dest.is_dir():
        raise SystemExit(f"project root not found: {dest}")
    if args.action == "list":
        print(json.dumps({"ok": True, "context": list_context(dest)}, ensure_ascii=False))
        return 0
    # add
    if args.content_file:
        content = sys.stdin.read() if args.content_file == "-" else Path(args.content_file).read_text(encoding="utf-8")
    else:
        content = args.content or ""
    result = inject_context(dest, args.category, args.name or "", content)
    committed = False
    if not args.no_commit:
        run(["git", "add", "-A"], cwd=dest, check=False)
        status = run(["git", "status", "--porcelain"], cwd=dest, check=False).stdout.strip()
        if status:
            run(["git", "commit", "-m", f"docs: add context {result['path']}"], cwd=dest, check=False)
            committed = True
        if args.push:
            branch = run(["git", "branch", "--show-current"], cwd=dest, check=False).stdout.strip() or "main"
            if "origin" in run(["git", "remote"], cwd=dest, check=False).stdout.split():
                run(["git", "push", "origin", branch], cwd=dest, timeout=300, check=False)
    print(json.dumps({"ok": True, "result": {**result, "committed": committed}}, ensure_ascii=False))
    return 0



# ---------------------------------------------------------------------------
# teardown


def codex_rollouts_for(root: Path) -> list[Path]:
    """Codex session transcripts recorded with this project as cwd."""
    sessions = Path.home() / ".codex" / "sessions"
    hits: list[Path] = []
    if not sessions.is_dir():
        return hits
    for path in sessions.glob("*/*/*/rollout-*.jsonl"):
        try:
            with path.open(encoding="utf-8") as fh:
                first = json.loads(fh.readline())
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if str((first.get("payload") or {}).get("cwd") or "") == str(root):
            hits.append(path)
    return hits


def destroy_targets(entry: dict[str, Any], projects_path: Path) -> list[tuple[str, Any]]:
    """Everything a project leaves behind, in removal order."""
    name = str(entry["id"])
    root = Path(str(entry["root"])).expanduser().resolve()
    targets: list[tuple[str, Any]] = []

    # tmux sessions (derived from configured panes, else <name>-claude/-codex)
    for key, fallback in (("claudePane", f"{name}-claude"), ("codexPane", f"{name}-codex")):
        pane = str(entry.get(key) or "")
        session = pane.split(":", 1)[0] if pane else fallback
        if session and run(["tmux", "has-session", "-t", session], check=False).returncode == 0:
            targets.append(("tmux session", session))

    unit = Path.home() / ".config" / "systemd" / "user" / f"{name}.service"
    if unit.exists():
        targets.append(("systemd unit", unit))

    if root.is_dir():
        targets.append(("repo dir", root))

    targets.append(("projects.json entry", projects_path))

    state_path = Path(os.environ.get("PEV_STATE", projects_path.parent / "state.json"))
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if name in (state.get("projects") or {}):
                targets.append(("dashboard state entry", state_path))
        except (OSError, json.JSONDecodeError):
            pass

    jobs_dir = projects_path.parent / "init-jobs"
    if jobs_dir.is_dir():
        jobs = [p for p in jobs_dir.iterdir()
                if p.name.startswith(f"{name}-") or p.name.startswith(f"deploy-{name}-")]
        for job in jobs:
            targets.append(("job log", job))

    transcripts = Path.home() / ".claude" / "projects" / str(root).replace("/", "-")
    if transcripts.is_dir():
        targets.append(("claude transcripts", transcripts))

    for rollout in codex_rollouts_for(root):
        targets.append(("codex rollout", rollout))

    return targets


def cmd_destroy(args: argparse.Namespace) -> int:
    log = StepLogger(False)
    projects_path = projects_file_path(args)
    projects = load_projects_list(projects_path)
    entry = next((p for p in projects if p.get("id") == args.name), None)
    if entry is None:
        raise SystemExit(f"project {args.name!r} not in {projects_path}")

    root = Path(str(entry["root"])).expanduser().resolve()
    # Guardrails: never let a bad entry point destroy something important.
    if root in (Path.home(), Path("/")) or root == SCAFFOLD_ROOT or not str(root).startswith(str(Path.home())):
        raise SystemExit(f"refusing to destroy suspicious root: {root}")

    targets = destroy_targets(entry, projects_path)
    if not args.yes:
        print(f"DRY RUN — would destroy project {args.name!r} (root {root}):")
        for kind, target in targets:
            print(f"  - {kind}: {target}")
        print(f"  - github repo: {args.name} (needs delete_repo scope; see note below)")
        print("\nRe-run with --yes to execute.")
        return 0

    for kind, target in targets:
        try:
            if kind == "tmux session":
                run(["tmux", "kill-session", "-t", str(target)], check=False)
            elif kind == "systemd unit":
                run(["systemctl", "--user", "disable", "--now", f"{args.name}.service"], check=False)
                Path(target).unlink(missing_ok=True)
                run(["systemctl", "--user", "daemon-reload"], check=False)
            elif kind == "repo dir":
                if args.keep_dir:
                    log.log("repo dir kept", str(target)); continue
                shutil.rmtree(target, ignore_errors=True)
            elif kind == "projects.json entry":
                data = json.loads(Path(target).read_text(encoding="utf-8"))
                data["projects"] = [p for p in data.get("projects", []) if p.get("id") != args.name]
                Path(target).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            elif kind == "dashboard state entry":
                data = json.loads(Path(target).read_text(encoding="utf-8"))
                (data.get("projects") or {}).pop(args.name, None)
                Path(target).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            elif kind in ("job log", "codex rollout"):
                Path(target).unlink(missing_ok=True)
            elif kind == "claude transcripts":
                shutil.rmtree(target, ignore_errors=True)
            log.log(f"removed {kind}", str(target))
        except OSError as exc:
            log.log(f"failed {kind}", f"{target}: {exc}", ok=False)

    if not args.keep_remote:
        result = run(["gh", "repo", "delete", args.name, "--yes"], check=False)
        if result.returncode == 0:
            log.log("github repo deleted", args.name)
        else:
            log.log("github repo NOT deleted", "token lacks delete_repo scope — delete it "
                    f"manually, or: gh auth refresh -h github.com -s delete_repo && "
                    f"gh repo delete {args.name} --yes", ok=False)

    port = entry.get("port")
    log.log("done", f"port {port} freed" if port else "done")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="PEV project bootstrap")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="bootstrap a project for PEV")
    p.add_argument("name", help="project id (also default repo/dir name)")
    p.add_argument("--source", choices=["new", "clone", "local"], default="new")
    p.add_argument("--repo", help="repo url (clone/local remote) or name (new)")
    p.add_argument("--dest", help="target directory (default: ~/<name>)")
    p.add_argument("--display-name", help="dashboard display name")
    p.add_argument("--visibility", choices=["private", "public"], default="private")
    p.add_argument("--driver", choices=["headless", "tmux"], default="headless")
    p.add_argument("--stack", help="one-line stack description; tailors AGENTS.md via a cheap model call")
    p.add_argument("--claude-model", help="Executor model (default: sonnet). Never left unset.")
    p.add_argument("--claude-effort", choices=["low", "medium", "high", "xhigh", "max"],
                   help="Executor session effort. Advisor effort lives in .claude/agents/advisor.md")
    p.add_argument("--projects-file", help="dashboard projects.json to register into")
    p.add_argument("--context-json", help="path (or '-') to a JSON array of {category,name,content} context files")
    p.add_argument("--no-push", action="store_true")
    p.add_argument("--json", action="store_true", help="stream steps as JSON lines")

    d = sub.add_parser("destroy", help="remove a project and everything it left behind")
    d.add_argument("name", help="project id as registered in projects.json")
    d.add_argument("--projects-file", help="dashboard projects.json to read/update")
    d.add_argument("--yes", action="store_true", help="actually do it (default: dry run)")
    d.add_argument("--keep-dir", action="store_true", help="leave the local repo directory")
    d.add_argument("--keep-remote", action="store_true", help="do not attempt to delete the GitHub repo")

    c = sub.add_parser("context", help="add or list spec/design context files")
    c.add_argument("action", choices=["add", "list"])
    c.add_argument("--root", required=True, help="project root directory")
    c.add_argument("--category", choices=list(CONTEXT_CATEGORIES))
    c.add_argument("--name", help="filename (default per category)")
    c.add_argument("--content", help="file content inline")
    c.add_argument("--content-file", help="read content from path, or '-' for stdin")
    c.add_argument("--no-commit", action="store_true")
    c.add_argument("--push", action="store_true")

    args = parser.parse_args()
    try:
        if args.cmd == "init":
            return cmd_init(args)
        if args.cmd == "destroy":
            return cmd_destroy(args)
        if args.cmd == "context":
            if args.action == "add" and not args.category:
                raise SystemExit("--category is required for 'context add'")
            return cmd_context(args)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()[-500:]
        print(json.dumps({"step": "fatal", "ok": False,
                          "detail": f"{' '.join(exc.cmd)} → {detail}"}, ensure_ascii=False))
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
