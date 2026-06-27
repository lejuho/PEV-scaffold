#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


APP_ROOT = Path(__file__).resolve().parent
PROJECTS_PATH = Path(os.environ.get("PEV_PROJECTS", APP_ROOT / "projects.json"))
STATE_PATH = Path(os.environ.get("PEV_STATE", APP_ROOT / "state.json"))
HOST = os.environ.get("PEV_DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("PEV_DASHBOARD_PORT", "8765"))

VERDICTS = ("BLOCKED", "PASS", "READY_TO_MERGE")
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
    claude_pane: str | None = None
    codex_pane: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_projects() -> list[Project]:
    raw = read_json(PROJECTS_PATH, {"projects": []})
    projects: list[Project] = []
    for item in raw.get("projects", []):
        try:
            root = Path(item["root"]).expanduser().resolve()
            projects.append(
                Project(
                    id=str(item["id"]),
                    name=str(item.get("name") or item["id"]),
                    root=root,
                    hermes_script=str(item.get("hermesScript") or "scripts/hermes-cycle-bot.py"),
                    claude_pane=item.get("claudePane"),
                    codex_pane=item.get("codexPane"),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return projects


def load_state() -> dict[str, Any]:
    state = read_json(STATE_PATH, {"projects": {}})
    if not isinstance(state, dict):
        state = {"projects": {}}
    if not isinstance(state.get("projects"), dict):
        state["projects"] = {}
    return state


def project_by_id(project_id: str) -> Project | None:
    for project in load_projects():
        if project.id == project_id:
            return project
    return None


def run_cmd(args: list[str], cwd: Path, timeout: int = 8) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def git_out(project: Project, args: list[str]) -> str | None:
    try:
        result = run_cmd(["git", *args], project.root)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


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


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def parse_verdict(review_text: str) -> str | None:
    match = re.search(r"^## Verdict\s*\n\s*(BLOCKED|PASS|READY_TO_MERGE)\s*$", review_text, re.M)
    if match:
        return match.group(1)
    for verdict in VERDICTS:
        if re.search(rf"\b{verdict}\b", review_text):
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
        return {
            "pass": 1,
            "kind": "implement",
            "review": None,
            "path": f".review/cycle-{cycle}/executor/pass-001-done.json",
        }
    if verdict == "BLOCKED":
        n = review_number(latest_review_rel)
        if n is not None:
            pass_no = n + 1
            return {
                "pass": pass_no,
                "kind": "fix",
                "review": latest_review_rel,
                "path": f".review/cycle-{cycle}/executor/pass-{pass_no:03d}-done.json",
            }
    return None


def flow_state(project: Project) -> dict[str, Any]:
    return read_json(project.root / "logs" / "hermes-flow.json", {})


def pane_tail(pane: str | None, lines: int = 80) -> str:
    if not pane:
        return "tmux pane not configured"
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", pane, "-S", f"-{lines}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"tmux capture failed for {pane}: {exc}"
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


def scan_project(project: Project, meta: dict[str, Any]) -> dict[str, Any]:
    cycle = latest_cycle(project.root)
    cycle_dir = project.root / ".review" / f"cycle-{cycle}" if cycle is not None else None
    status = read_text(cycle_dir / "status.txt").strip() if cycle_dir else None
    review_path = latest_review(cycle_dir) if cycle_dir else None
    latest_review_rel = str(review_path.relative_to(project.root)) if review_path else None
    verdict = parse_verdict(read_text(review_path)) if review_path else None
    branch = git_out(project, ["branch", "--show-current"])
    head = git_out(project, ["rev-parse", "--short", "HEAD"])
    dirty = bool(git_out(project, ["status", "--porcelain"]))
    flow = flow_state(project)
    expected = expected_done(cycle, status, latest_review_rel, verdict)
    pending_done = None
    if expected:
        done_path = project.root / expected["path"]
        if done_path.exists():
            processed = set(flow.get("processed_done_files") or [])
            if expected["path"] not in processed:
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

    hide_until = meta.get("hiddenUntilCycleGreaterThan")
    auto_hidden = isinstance(hide_until, int) and cycle is not None and cycle <= hide_until
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
            "processedDoneFiles": flow.get("processed_done_files") or [],
        },
        "git": {"branch": branch, "head": head, "dirty": dirty},
        "agents": {
            "claude": {"pane": project.claude_pane, "idle": simple_idle(pane_tail(project.claude_pane, 40), "claude")},
            "codex": {"pane": project.codex_pane, "idle": simple_idle(pane_tail(project.codex_pane, 40), "codex")},
        },
        "meta": {
            "archived": bool(meta.get("archived")),
            "hidden": bool(meta.get("hidden")) or auto_hidden,
            "autoHidden": auto_hidden,
            "pinned": bool(meta.get("pinned")),
            "snoozedUntil": meta.get("snoozedUntil"),
            "note": meta.get("note") or "",
            "hiddenUntilCycleGreaterThan": hide_until,
            "archivedAt": meta.get("archivedAt"),
            "archiveReason": meta.get("archiveReason") or "",
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
        raise ValueError("Command not allowed by PEV dashboard allowlist")
    script = project.root / project.hermes_script
    if not script.exists():
        raise FileNotFoundError(f"Hermes script not found: {script}")
    result = run_cmd([str(script), "--command", command], project.root, timeout=30)
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def create_done(project: Project, payload: dict[str, Any]) -> dict[str, Any]:
    state = scan_project(project, load_state().get("projects", {}).get(project.id, {}))
    expected = state.get("expectedDone")
    if not expected:
        raise ValueError("No expected done file for current project state")
    rel = expected["path"]
    done_path = project.root / rel
    if done_path.exists() and not payload.get("overwrite"):
        raise FileExistsError(f"Done file already exists: {rel}")
    summary = str(payload.get("summary") or "Manual PEV dashboard done signal.")
    checks = payload.get("checks")
    if isinstance(checks, str):
        checks = [line.strip() for line in checks.splitlines() if line.strip()]
    if not isinstance(checks, list):
        checks = []
    done = {
        "cycle": state["cycle"],
        "pass": expected["pass"],
        "kind": expected["kind"],
        "review": expected["review"],
        "createdAt": utc_now(),
        "summary": summary,
        "checks": checks,
        "generatedBy": "PEV-dashboard",
    }
    done_path.parent.mkdir(parents=True, exist_ok=True)
    done_path.write_text(json.dumps(done, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": rel, "done": done}


class Handler(BaseHTTPRequestHandler):
    server_version = "PEVDashboard/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))

    def send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message: str, status: int = 400) -> None:
        self.send_json({"ok": False, "error": message}, status)

    def read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self.serve_static(APP_ROOT / "static" / "index.html", "text/html; charset=utf-8")
            return
        if path.startswith("/static/"):
            rel = path.removeprefix("/static/")
            target = (APP_ROOT / "static" / rel).resolve()
            if not str(target).startswith(str((APP_ROOT / "static").resolve())):
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            content_type = "text/plain"
            if target.suffix == ".js":
                content_type = "text/javascript; charset=utf-8"
            elif target.suffix == ".css":
                content_type = "text/css; charset=utf-8"
            self.serve_static(target, content_type)
            return
        if path == "/api/projects":
            state = load_state()
            items = [scan_project(project, state["projects"].get(project.id, {})) for project in load_projects()]
            self.send_json({"ok": True, "projects": items, "updatedAt": utc_now()})
            return
        match = re.fullmatch(r"/api/projects/([^/]+)", path)
        if match:
            project_id = unquote(match.group(1))
            project = project_by_id(project_id)
            if not project:
                self.send_error_json("Unknown project", 404)
                return
            meta = load_state()["projects"].get(project.id, {})
            self.send_json({"ok": True, "project": scan_project(project, meta), "updatedAt": utc_now()})
            return
        match = re.fullmatch(r"/api/projects/([^/]+)/tail", path)
        if match:
            project = project_by_id(unquote(match.group(1)))
            if not project:
                self.send_error_json("Unknown project", 404)
                return
            target = parse_qs(parsed.query).get("target", ["claude"])[0]
            pane = project.claude_pane if target == "claude" else project.codex_pane if target == "codex" else None
            self.send_json({"ok": True, "target": target, "tail": pane_tail(pane, 120)})
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        match = re.fullmatch(r"/api/projects/([^/]+)/(command|meta|done)", path)
        if not match:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        project = project_by_id(unquote(match.group(1)))
        action = match.group(2)
        if not project:
            self.send_error_json("Unknown project", 404)
            return
        try:
            body = self.read_body()
            if action == "command":
                result = run_project_command(project, str(body.get("command") or ""))
                self.send_json({"ok": True, "result": result})
                return
            if action == "done":
                result = create_done(project, body)
                self.send_json({"ok": True, "result": result})
                return
            state = load_state()
            meta = state["projects"].setdefault(project.id, {})
            op = str(body.get("op") or "")
            if op == "archive":
                meta["archived"] = True
                meta["archivedAt"] = utc_now()
                meta["archiveReason"] = str(body.get("reason") or "")
            elif op == "unarchive":
                meta["archived"] = False
                meta.pop("archivedAt", None)
                meta.pop("archiveReason", None)
            elif op == "hide":
                meta["hidden"] = True
            elif op == "show":
                meta["hidden"] = False
                meta.pop("hiddenUntilCycleGreaterThan", None)
            elif op == "hideUntilNextCycle":
                current = latest_cycle(project.root)
                if current is not None:
                    meta["hiddenUntilCycleGreaterThan"] = current
                    meta["hidden"] = True
            elif op == "pin":
                meta["pinned"] = True
            elif op == "unpin":
                meta["pinned"] = False
            elif op == "note":
                meta["note"] = str(body.get("note") or "")
            else:
                raise ValueError("Unknown meta operation")
            write_json(STATE_PATH, state)
            self.send_json({"ok": True, "meta": meta})
        except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as err:
            self.send_error_json(str(err), 400)

    def serve_static(self, path: Path, content_type: str) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def check() -> int:
    projects = load_projects()
    state = load_state()
    print(json.dumps({"projects": [scan_project(p, state["projects"].get(p.id, {})) for p in projects]}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="print project scan JSON and exit")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    if args.check:
        return check()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"PEV Dashboard running on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
