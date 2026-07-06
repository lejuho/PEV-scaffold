#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECTS_PATH = Path(os.environ.get("PEV_PROJECTS", "/home/pi/PEV-dashboard/projects.json"))
STATE_PATH = Path(os.environ.get("PEV_STATE", "/home/pi/PEV-dashboard/state.json"))
SAFE_COMMANDS = {
    "/status",
    "/cycle",
    "/flow",
    "/remaining",
    "/prepare_next",
    "/implement",
    "/review",
    "/recheck",
    "/fix",
    "/merge",
    "/hold",
    "/resume",
    "/enter",
    "/say",
}


@dataclass
class Project:
    id: str
    name: str
    root: Path
    hermes_script: str
    claude_pane: str | None
    codex_pane: str | None


TOOLS: list[dict[str, Any]] = [
    {
        "name": "pev_projects",
        "description": "List configured PEV projects with cycle, git, and agent status.",
        "inputSchema": {"type": "object", "additionalProperties": False},
    },
    {
        "name": "pev_project",
        "description": "Read one PEV project state.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["projectId"],
            "properties": {"projectId": {"type": "string"}},
        },
    },
    {
        "name": "pev_tail",
        "description": "Read a Claude/Codex tmux pane tail for a PEV project.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["projectId", "target"],
            "properties": {
                "projectId": {"type": "string"},
                "target": {"type": "string", "enum": ["claude", "codex"]},
                "lines": {"type": "number"},
            },
        },
    },
    {
        "name": "pev_command",
        "description": "Run one allowlisted Hermes command for a project, e.g. /status, /review, /say codex text.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["projectId", "command"],
            "properties": {
                "projectId": {"type": "string"},
                "command": {"type": "string"},
            },
        },
    },
    {
        "name": "pev_flow",
        "description": "Set/read Hermes flow mode.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["projectId", "mode"],
            "properties": {
                "projectId": {"type": "string"},
                "mode": {"type": "string", "enum": ["status", "safe", "full", "off", "step"]},
            },
        },
    },
    {
        "name": "pev_enter",
        "description": "Send Enter to Claude or Codex pane through Hermes.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["projectId", "target"],
            "properties": {
                "projectId": {"type": "string"},
                "target": {"type": "string", "enum": ["claude", "codex"]},
            },
        },
    },
    {
        "name": "pev_say",
        "description": "Paste text into Claude or Codex pane through Hermes.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["projectId", "target", "text"],
            "properties": {
                "projectId": {"type": "string"},
                "target": {"type": "string", "enum": ["claude", "codex"]},
                "text": {"type": "string"},
            },
        },
    },
    {
        "name": "pev_create_done",
        "description": "Create the expected executor done signal for current project state.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["projectId"],
            "properties": {
                "projectId": {"type": "string"},
                "summary": {"type": "string"},
                "checks": {"type": "array", "items": {"type": "string"}},
                "overwrite": {"type": "boolean"},
            },
        },
    },
    {
        "name": "pev_tmux_sessions",
        "description": "List tmux sessions visible to PEV.",
        "inputSchema": {"type": "object", "additionalProperties": False},
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_projects() -> list[Project]:
    raw = read_json(PROJECTS_PATH, {"projects": []})
    out: list[Project] = []
    for item in raw.get("projects", []):
        if not isinstance(item, dict):
            continue
        try:
            out.append(
                Project(
                    id=str(item["id"]),
                    name=str(item.get("name") or item["id"]),
                    root=Path(item["root"]).expanduser().resolve(),
                    hermes_script=str(item.get("hermesScript") or "scripts/hermes-cycle-bot.py"),
                    claude_pane=item.get("claudePane"),
                    codex_pane=item.get("codexPane"),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def project_by_id(project_id: str) -> Project:
    for project in load_projects():
        if project.id == project_id:
            return project
    raise ValueError(f"unknown project: {project_id}")


def run_cmd(args: list[str], cwd: Path | None = None, timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def git_out(project: Project, args: list[str]) -> str | None:
    result = run_cmd(["git", *args], cwd=project.root)
    return result.stdout.strip() if result.returncode == 0 else None


def latest_cycle(root: Path) -> int | None:
    review = root / ".review"
    if not review.exists():
        return None
    cycles: list[int] = []
    for path in review.iterdir():
        match = re.fullmatch(r"cycle-(\d+)", path.name)
        if match and path.is_dir():
            cycles.append(int(match.group(1)))
    return max(cycles) if cycles else None


def latest_review(cycle_dir: Path) -> Path | None:
    reviews: list[tuple[int, Path]] = []
    for path in cycle_dir.glob("review-v*.md"):
        match = re.fullmatch(r"review-v(\d+)\.md", path.name)
        if match:
            reviews.append((int(match.group(1)), path))
    return max(reviews, key=lambda item: item[0])[1] if reviews else None


def parse_verdict(text: str) -> str | None:
    match = re.search(r"^## Verdict\s*\n\s*(BLOCKED|PASS|READY_TO_MERGE)\s*$", text, re.M)
    if match:
        return match.group(1)
    for verdict in ("BLOCKED", "PASS", "READY_TO_MERGE"):
        if re.search(rf"\b{verdict}\b", text):
            return verdict
    return None


def review_number(review_path: str | None) -> int | None:
    if not review_path:
        return None
    match = re.search(r"review-v(\d+)\.md$", review_path)
    return int(match.group(1)) if match else None


def expected_done(cycle: int | None, status: str | None, latest_review_rel: str | None, verdict: str | None) -> dict[str, Any] | None:
    if cycle is None:
        return None
    if latest_review_rel is None and status == "in_progress":
        return {"pass": 1, "kind": "implement", "review": None, "path": f".review/cycle-{cycle}/executor/pass-001-done.json"}
    if verdict == "BLOCKED":
        n = review_number(latest_review_rel)
        if n is not None:
            pass_no = n + 1
            return {"pass": pass_no, "kind": "fix", "review": latest_review_rel, "path": f".review/cycle-{cycle}/executor/pass-{pass_no:03d}-done.json"}
    return None


def pane_tail(pane: str | None, lines: int = 80) -> str:
    if not pane:
        return "tmux pane not configured"
    result = run_cmd(["tmux", "capture-pane", "-p", "-t", pane, "-S", f"-{lines}"], timeout=5)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
        return f"tmux capture failed for {pane}: {detail}"
    return result.stdout or "(empty pane)"


def simple_idle(text: str, agent: str) -> bool | None:
    if not text:
        return None
    tail = text[-2500:]
    if any(marker in tail for marker in ("Running", "Working", "Waiting", "Bash(")):
        return False
    if agent == "codex":
        return bool(re.search(r"(?m)^›\s", tail))
    return "❯" in tail or "accept edits on" in tail


def scan_project(project: Project) -> dict[str, Any]:
    cycle = latest_cycle(project.root)
    cycle_dir = project.root / ".review" / f"cycle-{cycle}" if cycle is not None else None
    status = read_text(cycle_dir / "status.txt").strip() if cycle_dir else None
    review_path = latest_review(cycle_dir) if cycle_dir else None
    latest_review_rel = str(review_path.relative_to(project.root)) if review_path else None
    verdict = parse_verdict(read_text(review_path)) if review_path else None
    flow = read_json(project.root / "logs" / "hermes-flow.json", {})
    expected = expected_done(cycle, status, latest_review_rel, verdict)
    pending_done = None
    if expected:
        done_path = project.root / expected["path"]
        if done_path.exists() and expected["path"] not in set(flow.get("processed_done_files") or []):
            pending_done = expected["path"]
    if status == "ready_to_merge" or verdict in {"PASS", "READY_TO_MERGE"}:
        phase = "ready_to_merge"
    elif status == "escalated":
        phase = "escalated"
    elif verdict == "BLOCKED":
        phase = "review_blocked"
    elif cycle is None:
        phase = "no_cycle"
    elif status == "in_progress":
        phase = "in_progress"
    else:
        phase = "unknown"
    claude_tail = pane_tail(project.claude_pane, 40)
    codex_tail = pane_tail(project.codex_pane, 40)
    return {
        "id": project.id,
        "name": project.name,
        "root": str(project.root),
        "cycle": cycle,
        "phase": phase,
        "status": status,
        "verdict": verdict,
        "latestReview": latest_review_rel,
        "expectedDone": expected,
        "pendingDone": pending_done,
        "flow": {
            "mode": flow.get("mode"),
            "waitingFor": flow.get("waiting_for"),
            "lastAction": flow.get("last_action_key"),
            "lastNotice": flow.get("last_notice_key"),
            "processedDoneCount": len(flow.get("processed_done_files") or []),
        },
        "git": {
            "branch": git_out(project, ["branch", "--show-current"]),
            "head": git_out(project, ["rev-parse", "--short", "HEAD"]),
            "dirty": bool(git_out(project, ["status", "--porcelain"])),
        },
        "agents": {
            "claude": {"pane": project.claude_pane, "idle": simple_idle(claude_tail, "claude")},
            "codex": {"pane": project.codex_pane, "idle": simple_idle(codex_tail, "codex")},
        },
    }


def command_allowed(command: str) -> bool:
    parts = command.strip().split()
    if not parts:
        return False
    base = parts[0]
    if base not in SAFE_COMMANDS:
        return False
    if base == "/flow":
        return len(parts) <= 2 and (len(parts) == 1 or parts[1] in {"status", "state", "safe", "on", "full", "off", "stop", "step"})
    if base == "/enter":
        return len(parts) == 2 and parts[1] in {"claude", "codex"}
    if base == "/say":
        return len(parts) >= 3 and parts[1] in {"claude", "codex"}
    return len(parts) == 1


def run_project_command(project: Project, command: str) -> dict[str, Any]:
    if not command_allowed(command):
        raise ValueError("command not allowed")
    script = project.root / project.hermes_script
    if not script.exists():
        raise FileNotFoundError(f"Hermes script not found: {script}")
    result = run_cmd([str(script), "--command", command], cwd=project.root, timeout=30)
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def create_done(project: Project, args: dict[str, Any]) -> dict[str, Any]:
    state = scan_project(project)
    expected = state.get("expectedDone")
    if not expected:
        raise ValueError("no expected done file for current project state")
    rel = expected["path"]
    done_path = project.root / rel
    if done_path.exists() and args.get("overwrite") is not True:
        raise FileExistsError(f"done file already exists: {rel}")
    checks = args.get("checks")
    if not isinstance(checks, list):
        checks = []
    done = {
        "cycle": state["cycle"],
        "pass": expected["pass"],
        "kind": expected["kind"],
        "review": expected["review"],
        "createdAt": utc_now(),
        "summary": str(args.get("summary") or "Manual PEV MCP done signal."),
        "checks": [str(item) for item in checks],
        "generatedBy": "PEV-MCP",
    }
    done_path.parent.mkdir(parents=True, exist_ok=True)
    done_path.write_text(json.dumps(done, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": rel, "done": done}


def require_string(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def ok_result(data: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}]}


def error_result(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps({"ok": False, "error": message}, ensure_ascii=False, indent=2)}], "isError": True}


def call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        if name == "pev_projects":
            return ok_result({"ok": True, "projects": [scan_project(project) for project in load_projects()]})
        if name == "pev_project":
            return ok_result({"ok": True, "project": scan_project(project_by_id(require_string(args, "projectId")))})
        if name == "pev_tail":
            project = project_by_id(require_string(args, "projectId"))
            target = require_string(args, "target")
            pane = project.claude_pane if target == "claude" else project.codex_pane if target == "codex" else None
            lines = args.get("lines")
            line_count = int(lines) if isinstance(lines, (int, float)) else 120
            return ok_result({"ok": True, "target": target, "tail": pane_tail(pane, line_count)})
        if name == "pev_command":
            return ok_result({"ok": True, "result": run_project_command(project_by_id(require_string(args, "projectId")), require_string(args, "command"))})
        if name == "pev_flow":
            project = project_by_id(require_string(args, "projectId"))
            return ok_result({"ok": True, "result": run_project_command(project, f"/flow {require_string(args, 'mode')}")})
        if name == "pev_enter":
            project = project_by_id(require_string(args, "projectId"))
            return ok_result({"ok": True, "result": run_project_command(project, f"/enter {require_string(args, 'target')}")})
        if name == "pev_say":
            project = project_by_id(require_string(args, "projectId"))
            return ok_result({"ok": True, "result": run_project_command(project, f"/say {require_string(args, 'target')} {require_string(args, 'text')}")})
        if name == "pev_create_done":
            return ok_result({"ok": True, "result": create_done(project_by_id(require_string(args, "projectId")), args)})
        if name == "pev_tmux_sessions":
            result = run_cmd(["tmux", "list-sessions"], timeout=5)
            return ok_result({"ok": result.returncode == 0, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        raise ValueError(f"unknown tool: {name}")
    except Exception as exc:
        return error_result(str(exc))


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    msg_id = message.get("id")
    method = message.get("method")
    if msg_id is None:
        return None
    try:
        if method == "initialize":
            params = message.get("params") if isinstance(message.get("params"), dict) else {}
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                    "capabilities": {"tools": {"listChanged": False}, "resources": {}, "prompts": {}},
                    "serverInfo": {"name": "pev-mcp", "version": "0.1.0"},
                    "instructions": "Use PEV tools to inspect cycle state and operate Hermes/tmux through allowlisted commands.",
                },
            }
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
        if method == "tools/call":
            params = message.get("params")
            if not isinstance(params, dict):
                raise ValueError("tools/call params must be object")
            name = params.get("name")
            args = params.get("arguments") or {}
            if not isinstance(name, str) or not isinstance(args, dict):
                raise ValueError("invalid tool call")
            return {"jsonrpc": "2.0", "id": msg_id, "result": call_tool(name, args)}
        if method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
        if method == "resources/list":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"resources": []}}
        if method == "prompts/list":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"prompts": []}}
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    except Exception as exc:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32603, "message": str(exc)}}


def main() -> int:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
            if not isinstance(message, dict):
                raise ValueError("message must be object")
            response = handle(message)
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
