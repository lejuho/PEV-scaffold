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

CODEX_HOOKS = [
    "block-dangerous.sh",
    "track-failures.sh",
    "auto-format.sh",
    "force-advisor-check.sh",
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
                {"type": "command", "command": ".codex/hooks/force-advisor-check.sh"},
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

    # source == "new": create on GitHub, then clone
    repo_name = args.repo or args.name
    run(["gh", "repo", "create", repo_name, f"--{args.visibility}", "--clone", str(dest)],
        cwd=dest.parent, timeout=300)
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


def inject_artifacts(dest: Path, driver: str, log: StepLogger) -> tuple[list[str], list[str]]:
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

    # self-contained control scripts (hermes bridge + runner)
    for script_name in ("hermes-cycle-bot.py", "pev_runner.py"):
        target = dest / "scripts" / script_name
        if copy_if_absent(SCRIPT_DIR / script_name, target, copied, skipped):
            make_executable(target)

    # runtime env for the hermes bridge / runner
    env_lines = [
        f"HERMES_ROOT={dest}",
        f"HERMES_LOG_DIR={dest / 'logs'}",
        f"PEV_DRIVER={driver}",
        f"PEV_CLAUDE_BIN={os.environ.get('PEV_CLAUDE_BIN', shutil.which('claude') or 'claude')}",
        f"PEV_CODEX_BIN={os.environ.get('PEV_CODEX_BIN', shutil.which('codex') or 'codex')}",
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


def register_project(args: argparse.Namespace, dest: Path, log: StepLogger) -> None:
    path = Path(args.projects_file) if args.projects_file else default_projects_file()
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
        "hermesScript": "scripts/hermes-cycle-bot.py",
        "driver": args.driver,
    }
    if args.driver == "tmux":
        entry["claudePane"] = f"{args.name}-claude:0"
        entry["codexPane"] = f"{args.name}-codex:0"
    if args.claude_model:
        entry["claudeModel"] = args.claude_model
    projects.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log.log("dashboard registered", f"{args.name} in {path}")


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


def cmd_init(args: argparse.Namespace) -> int:
    log = StepLogger(args.json)
    dest = Path(args.dest).expanduser().resolve() if args.dest else Path.home() / args.name
    acquire_repo(args, dest, log)
    ensure_first_commit(dest, args.name, log)
    inject_artifacts(dest, args.driver, log)
    if args.stack:
        tailor_agents_md(dest, args.stack, log)
    commit_and_push(dest, push=not args.no_push, log=log)
    register_project(args, dest, log)
    prepare_sessions(dest, args.driver, log)
    summary = {
        "ok": all(s["ok"] for s in log.steps),
        "root": str(dest),
        "driver": args.driver,
        "startedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "steps": log.steps,
        "next": [
            "Review AGENTS.md sections (Architecture/Commands/Testing) before the first cycle.",
            f"Create the first plan: {dest}/.review/cycle-1/plan.md",
            "Then /implement from the dashboard or Telegram.",
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2) if not args.json
          else json.dumps({"summary": summary}, ensure_ascii=False), flush=True)
    return 0 if summary["ok"] else 1


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
    p.add_argument("--claude-model", help="model recorded for the dashboard runner config")
    p.add_argument("--projects-file", help="dashboard projects.json to register into")
    p.add_argument("--no-push", action="store_true")
    p.add_argument("--json", action="store_true", help="stream steps as JSON lines")
    args = parser.parse_args()
    if args.cmd == "init":
        try:
            return cmd_init(args)
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()[-500:]
            print(json.dumps({"step": "fatal", "ok": False,
                              "detail": f"{' '.join(exc.cmd)} → {detail}"}, ensure_ascii=False))
            return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
