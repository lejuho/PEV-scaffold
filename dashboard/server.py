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

import metrics

APP_ROOT = Path(__file__).resolve().parent
for _candidate in (APP_ROOT.parent / "scripts", Path("/home/pi/PEV-scaffold/scripts")):
    if (_candidate / "pev_runner.py").exists():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break
from pev_runner import AgentRunner, RunnerConfig  # noqa: E402

METRICS_CACHE_SECONDS = 60
PROJECTS_PATH = Path(os.environ.get("PEV_PROJECTS", APP_ROOT / "projects.json"))
STATE_PATH = Path(os.environ.get("PEV_STATE", APP_ROOT / "state.json"))
HOST = os.environ.get("PEV_DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("PEV_DASHBOARD_PORT", "8765"))

INIT_JOBS_DIR = Path(os.environ.get("PEV_INIT_JOBS", APP_ROOT / "init-jobs"))
PEVCTL_PATH = next(
    (c / "pevctl.py" for c in (APP_ROOT.parent / "scripts", Path("/home/pi/PEV-scaffold/scripts"))
     if (c / "pevctl.py").exists()),
    None,
)

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
    driver: str = "tmux"
    raw: dict[str, Any] | None = None

    def runner(self) -> AgentRunner:
        item = dict(self.raw or {})
        item.setdefault("root", str(self.root))
        return AgentRunner(RunnerConfig.from_project(item))


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
                    driver=str(item.get("driver") or "tmux"),
                    raw=dict(item),
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


def append_event(project: Project, event: str, data: dict[str, Any]) -> None:
    """Append an event to the project's hermes-events.jsonl. Failures are ignored
    so dashboard actions are never blocked by logging problems."""
    try:
        path = project.root / "logs" / "hermes-events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"ts": utc_now(), "event": event, **data}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def run_cmd(args: list[str], cwd: Path, timeout: int = 8, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)


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


def agent_states(project: Project) -> dict[str, Any]:
    runner = project.runner()
    out: dict[str, Any] = {}
    for agent in ("claude", "codex"):
        try:
            out[agent] = runner.status(agent)
        except (OSError, subprocess.SubprocessError) as exc:
            out[agent] = {"driver": project.driver, "error": str(exc), "idle": None}
    return out


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
    spec_dir = project.root / "docs" / "spec"
    try:
        has_spec = spec_dir.is_dir() and any(p.is_file() for p in spec_dir.iterdir())
    except OSError:
        has_spec = False
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
        "driver": project.driver,
        "hasSpec": has_spec,
        "agents": agent_states(project),
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
    env = dict(os.environ)
    env["HERMES_ROOT"] = str(project.root)
    env.setdefault("PEV_DRIVER", project.driver)
    if project.claude_pane:
        env.setdefault("HERMES_CLAUDE_PANE", project.claude_pane)
    if project.codex_pane:
        env.setdefault("HERMES_CODEX_PANE", project.codex_pane)
    result = run_cmd([str(script), "--command", command], project.root, timeout=30, env=env)
    append_event(project, "dashboard_command", {"command": command, "returncode": result.returncode})
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
    append_event(
        project,
        "dashboard_done",
        {"cycle": done["cycle"], "pass": done["pass"], "kind": done["kind"], "path": rel},
    )
    return {"path": rel, "done": done}


INIT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


CONTEXT_CATEGORIES = ("spec", "design")
CONTEXT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def sanitize_context_entries(raw: Any) -> list[dict[str, str]]:
    """Validate a list of {category, name?, content} context entries."""
    if not isinstance(raw, list):
        return []
    entries: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "")
        content = str(item.get("content") or "")
        if category not in CONTEXT_CATEGORIES or not content.strip():
            continue
        name = str(item.get("name") or "").strip()
        if name and (not CONTEXT_NAME_RE.fullmatch(name) or "/" in name or ".." in name):
            raise ValueError(f"invalid context filename: {name}")
        entry = {"category": category, "content": content}
        if name:
            entry["name"] = name
        entries.append(entry)
    return entries


def run_context(project: Project, body: dict[str, Any]) -> dict[str, Any]:
    """Add one context file to an existing project via `pevctl context add`."""
    if PEVCTL_PATH is None:
        raise FileNotFoundError("pevctl.py not found next to dashboard")
    entries = sanitize_context_entries([body])
    if not entries:
        raise ValueError("category (spec|design) and non-empty content are required")
    entry = entries[0]
    argv = [sys.executable, str(PEVCTL_PATH), "context", "add",
            "--root", str(project.root), "--category", entry["category"],
            "--content-file", "-"]
    if entry.get("name"):
        argv += ["--name", entry["name"]]
    if body.get("push"):
        argv += ["--push"]
    env = dict(os.environ)
    env["PEV_CLAUDE_BIN"] = env.get("PEV_CLAUDE_BIN", "claude")
    result = subprocess.run(argv, input=entry["content"], capture_output=True, text=True,
                            timeout=60, cwd=str(project.root), env=env)
    if result.returncode != 0:
        raise ValueError((result.stderr or result.stdout).strip() or "pevctl context failed")
    append_event(project, "dashboard_context", {"category": entry["category"]})
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    return payload.get("result", payload)


def list_context(project: Project) -> dict[str, Any]:
    if PEVCTL_PATH is None:
        raise FileNotFoundError("pevctl.py not found next to dashboard")
    result = subprocess.run(
        [sys.executable, str(PEVCTL_PATH), "context", "list", "--root", str(project.root)],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        raise ValueError((result.stderr or result.stdout).strip() or "pevctl context list failed")
    return json.loads(result.stdout.strip().splitlines()[-1])


def start_init_job(body: dict[str, Any]) -> dict[str, Any]:
    if PEVCTL_PATH is None:
        raise FileNotFoundError("pevctl.py not found next to dashboard")
    name = str(body.get("name") or "").strip()
    if not INIT_NAME_RE.fullmatch(name):
        raise ValueError("Invalid project name (use lowercase letters, digits, . _ -)")
    source = str(body.get("source") or "new")
    if source not in {"new", "clone", "local"}:
        raise ValueError("source must be new|clone|local")
    driver = str(body.get("driver") or "headless")
    if driver not in {"headless", "tmux"}:
        raise ValueError("driver must be headless|tmux")
    argv = [sys.executable, str(PEVCTL_PATH), "init", name,
            "--source", source, "--driver", driver, "--json",
            "--projects-file", str(PROJECTS_PATH)]
    if body.get("repo"):
        argv += ["--repo", str(body["repo"])]
    if body.get("dest"):
        argv += ["--dest", str(body["dest"])]
    if body.get("stack"):
        argv += ["--stack", str(body["stack"])]
    if body.get("displayName"):
        argv += ["--display-name", str(body["displayName"])]
    if body.get("visibility") in {"private", "public"}:
        argv += ["--visibility", str(body["visibility"])]
    if body.get("claudeModel"):
        argv += ["--claude-model", str(body["claudeModel"])]
    if body.get("noPush"):
        argv += ["--no-push"]
    job_id = f"{name}-{int(time.time())}"
    INIT_JOBS_DIR.mkdir(parents=True, exist_ok=True)
    context = sanitize_context_entries(body.get("context"))
    if context:
        ctx_path = INIT_JOBS_DIR / f"{job_id}.context.json"
        ctx_path.write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
        argv += ["--context-json", str(ctx_path)]
    log_path = INIT_JOBS_DIR / f"{job_id}.jsonl"
    with log_path.open("w", encoding="utf-8") as log_fh:
        proc = subprocess.Popen(
            argv, stdout=log_fh, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True, cwd=str(Path.home()),
        )
    write_json(INIT_JOBS_DIR / f"{job_id}.meta.json", {
        "job": job_id, "name": name, "pid": proc.pid, "startedAt": utc_now(),
        "source": source, "driver": driver,
    })
    return {"job": job_id}


def init_job_status(job_id: str) -> dict[str, Any]:
    meta_path = INIT_JOBS_DIR / f"{job_id}.meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"Unknown init job: {job_id}")
    meta = read_json(meta_path, {})
    steps: list[dict[str, Any]] = []
    summary: dict[str, Any] | None = None
    log_path = INIT_JOBS_DIR / f"{job_id}.jsonl"
    for raw in read_text(log_path).splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            line = json.loads(raw)
        except json.JSONDecodeError:
            steps.append({"step": "output", "detail": raw[:300], "ok": True})
            continue
        if "summary" in line:
            summary = line["summary"]
        else:
            steps.append(line)
    pid = meta.get("pid")
    running = False
    if isinstance(pid, int):
        try:
            os.kill(pid, 0)
            running = True
        except (OSError, ProcessLookupError):
            running = False
    return {"job": job_id, "meta": meta, "running": running, "steps": steps, "summary": summary}


def start_deploy_job(project: Project) -> dict[str, Any]:
    """Run the project's redeploy script in the background, streaming output
    through the same job-log mechanism as init."""
    rel = str((project.raw or {}).get("deployScript") or "deploy/redeploy.sh")
    if rel.startswith("/") or ".." in rel.split("/"):
        raise ValueError("Invalid deployScript path")
    script = (project.root / rel).resolve()
    if not str(script).startswith(str(project.root.resolve())):
        raise ValueError("deployScript escapes project root")
    if not script.exists():
        raise FileNotFoundError(f"No deploy script at {rel} — wire it in a cycle first")
    job_id = f"deploy-{project.id}-{int(time.time())}"
    INIT_JOBS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = INIT_JOBS_DIR / f"{job_id}.jsonl"
    env = dict(os.environ)
    env["HERMES_ROOT"] = str(project.root)
    # Run the script, then emit a summary line carrying the exit code so the
    # job-status reader (shared with init) can report success/failure.
    wrapper = ('bash "$1"; ec=$?; if [ $ec -eq 0 ]; then ok=true; else ok=false; fi; '
               "printf '{\"summary\":{\"ok\":%s,\"exit\":%s}}\\n' \"$ok\" \"$ec\"")
    with log_path.open("w", encoding="utf-8") as log_fh:
        proc = subprocess.Popen(
            ["bash", "-c", wrapper, "pev-deploy", str(script)],
            stdout=log_fh, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True, cwd=str(project.root), env=env,
        )
    write_json(INIT_JOBS_DIR / f"{job_id}.meta.json", {
        "job": job_id, "name": project.id, "pid": proc.pid, "startedAt": utc_now(),
        "kind": "deploy", "script": rel,
    })
    append_event(project, "dashboard_deploy", {"script": rel})
    return {"job": job_id}


def project_cycle_tags(meta: dict[str, Any]) -> dict[str, str]:
    tags = meta.get("cycleTags")
    if not isinstance(tags, dict):
        return {}
    return {str(k): str(v) for k, v in tags.items() if v}


def project_metrics(project: Project, meta: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """Return metrics for a project, reusing logs/pev-metrics.json when it is
    fresh (<60s) and no failure tags have changed since it was written."""
    cache_path = project.root / "logs" / "pev-metrics.json"
    tags = project_cycle_tags(meta)
    if not force and cache_path.exists():
        try:
            age = time.time() - cache_path.stat().st_mtime
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = None
            age = None
        if cached is not None and age is not None and age < METRICS_CACHE_SECONDS:
            return cached
    result = metrics.compute_metrics(project.root, tags=tags)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    return result


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
        if path == "/api/metrics/summary":
            state = load_state()
            summaries = []
            combined = {
                "cycles": 0,
                "autonomyHours": 0.0,
                "costUsd": 0.0,
                "reworkCostUsd": 0.0,
            }
            for project in load_projects():
                meta = state["projects"].get(project.id, {})
                try:
                    data = project_metrics(project, meta)
                except (OSError, ValueError) as err:
                    summaries.append({"id": project.id, "name": project.name, "error": str(err)})
                    continue
                totals = data.get("totals", {})
                summaries.append({"id": project.id, "name": project.name, "totals": totals})
                combined["cycles"] += totals.get("cycles") or 0
                combined["autonomyHours"] += totals.get("autonomyHours") or 0.0
                combined["costUsd"] += totals.get("costUsd") or 0.0
                combined["reworkCostUsd"] += totals.get("reworkCostUsd") or 0.0
            for key in ("autonomyHours", "costUsd", "reworkCostUsd"):
                combined[key] = round(combined[key], 4)
            self.send_json({"ok": True, "projects": summaries, "combined": combined, "updatedAt": utc_now()})
            return
        match = re.fullmatch(r"/api/projects/([^/]+)/metrics", path)
        if match:
            project = project_by_id(unquote(match.group(1)))
            if not project:
                self.send_error_json("Unknown project", 404)
                return
            meta = load_state()["projects"].get(project.id, {})
            force = parse_qs(parsed.query).get("force", ["0"])[0] in ("1", "true")
            try:
                data = project_metrics(project, meta, force=force)
            except (OSError, ValueError) as err:
                self.send_error_json(str(err), 500)
                return
            self.send_json({"ok": True, "metrics": data, "updatedAt": utc_now()})
            return
        match = re.fullmatch(r"/api/(?:init|deploy)/([^/]+)", path)
        if match:
            try:
                self.send_json({"ok": True, **init_job_status(unquote(match.group(1)))})
            except (OSError, ValueError) as err:
                self.send_error_json(str(err), 404)
            return
        match = re.fullmatch(r"/api/projects/([^/]+)/context", path)
        if match:
            project = project_by_id(unquote(match.group(1)))
            if not project:
                self.send_error_json("Unknown project", 404)
                return
            try:
                self.send_json({"ok": True, **list_context(project)})
            except (OSError, ValueError, json.JSONDecodeError) as err:
                self.send_error_json(str(err), 500)
            return
        match = re.fullmatch(r"/api/projects/([^/]+)/tail", path)
        if match:
            project = project_by_id(unquote(match.group(1)))
            if not project:
                self.send_error_json("Unknown project", 404)
                return
            target = parse_qs(parsed.query).get("target", ["claude"])[0]
            if target not in ("claude", "codex"):
                self.send_error_json("Unknown target", 400)
                return
            try:
                tail = project.runner().tail(target, 120)
            except (OSError, subprocess.SubprocessError) as exc:
                tail = f"tail failed: {exc}"
            self.send_json({"ok": True, "target": target, "tail": tail})
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/projects/init":
            try:
                result = start_init_job(self.read_body())
                self.send_json({"ok": True, **result})
            except (OSError, ValueError, json.JSONDecodeError) as err:
                self.send_error_json(str(err), 400)
            return
        tag_match = re.fullmatch(r"/api/projects/([^/]+)/cycles/(\d+)/tag", path)
        if tag_match:
            project = project_by_id(unquote(tag_match.group(1)))
            if not project:
                self.send_error_json("Unknown project", 404)
                return
            cycle_n = tag_match.group(2)
            try:
                body = self.read_body()
                tag = str(body.get("tag") or "").strip()
                valid = {"executor", "plan", "reviewer", "infra"}
                if tag and tag not in valid and tag not in {"none", "clear"}:
                    raise ValueError(f"Unknown failure tag: {tag}")
                state = load_state()
                meta = state["projects"].setdefault(project.id, {})
                tags = meta.get("cycleTags")
                if not isinstance(tags, dict):
                    tags = {}
                if tag in valid:
                    tags[cycle_n] = tag
                else:
                    tags.pop(cycle_n, None)
                meta["cycleTags"] = tags
                write_json(STATE_PATH, state)
                # drop the metrics cache so failureTag reflects immediately
                try:
                    (project.root / "logs" / "pev-metrics.json").unlink(missing_ok=True)
                except OSError:
                    pass
                self.send_json({"ok": True, "cycleTags": tags})
            except (OSError, ValueError, json.JSONDecodeError) as err:
                self.send_error_json(str(err), 400)
            return
        match = re.fullmatch(r"/api/projects/([^/]+)/(command|meta|done|agent|context|deploy)", path)
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
            if action == "deploy":
                result = start_deploy_job(project)
                self.send_json({"ok": True, **result})
                return
            if action == "context":
                result = run_context(project, body)
                self.send_json({"ok": True, "result": result})
                return
            if action == "agent":
                agent = str(body.get("agent") or "")
                op = str(body.get("op") or "")
                runner = project.runner()
                if op == "harvest":
                    result: Any = runner.harvest()
                elif op in {"start", "stop"} and agent in ("claude", "codex"):
                    result = getattr(runner, op)(agent)
                else:
                    raise ValueError("Unknown agent operation")
                append_event(project, "dashboard_agent", {"agent": agent, "op": op})
                self.send_json({"ok": True, "result": result})
                return
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
