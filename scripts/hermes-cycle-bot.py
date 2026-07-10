#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request

for _candidate in (Path(__file__).resolve().parent, Path("/home/pi/PEV-scaffold/scripts")):
    if (_candidate / "pev_runner.py").exists():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break
from pev_runner import AgentRunner, RunnerConfig  # noqa: E402


VERDICTS = ("BLOCKED", "PASS", "READY_TO_MERGE")
EXECUTOR_DONE_RE = re.compile(r"pass-(\d+)-done\.json")

# Supervisor mode reads the dashboard's project registry so both agree on which
# projects exist and which are archived. state.json is written by the dashboard.
PROJECTS_PATH = Path(os.environ.get("PEV_PROJECTS", "/home/pi/PEV-dashboard/projects.json"))
DASHBOARD_STATE_PATH = Path(os.environ.get("PEV_STATE", "/home/pi/PEV-dashboard/state.json"))
SUPERVISOR_STATE_PATH = Path(os.environ.get("PEV_SUPERVISOR_STATE", "/home/pi/PEV-dashboard/supervisor.json"))

# Set by supervisor_loop(). The Telegram update offset must be process-global:
# one getUpdates consumer, one cursor. Keeping it per-project would replay old
# updates every time the operator switched projects with /project.
SUPERVISOR_MODE = False

BOT_COMMANDS = [
    {"command": "status", "description": "현재 cycle 상태"},
    {"command": "menu", "description": "누르는 Hermes 버튼"},
    {"command": "tail", "description": "tmux pane tail: /tail claude|codex"},
    {"command": "remaining", "description": "Codex에 남은 구현 스펙 요청"},
    {"command": "prepare_next", "description": "Codex에 다음 사이클 준비 요청"},
    {"command": "implement", "description": "Claude에 최신 cycle 구현 시작 요청"},
    {"command": "review", "description": "Codex에 구현 검증 요청"},
    {"command": "recheck", "description": "Codex에 재검증 요청"},
    {"command": "fix", "description": "Claude에 최신 review 수정 요청"},
    {"command": "merge", "description": "ready_to_merge일 때 Codex에 머지 요청"},
    {"command": "flow", "description": "cycle 자동 흐름: /flow safe|full|off|status|step|reset"},
    {"command": "project", "description": "대상 프로젝트 조회/전환: /project [id]"},
    {"command": "enter", "description": "현재 pane 입력창 제출: /enter codex|claude"},
    {"command": "hold", "description": "Hermes 자동 조작 정지"},
    {"command": "resume", "description": "Hermes hold 해제"},
    {"command": "help", "description": "명령 도움말"},
]

FLOW_IDLE_GRACE_SECONDS = 45


@dataclass
class Config:
    root: Path
    log_dir: Path
    token: str
    chat_id: str
    claude_pane: str
    codex_pane: str
    poll_seconds: int
    submit_key: str
    submit_delay: float
    dry_run: bool
    driver: str = "tmux"
    # Supervisor mode only. `label` disambiguates Telegram notices once more than
    # one project can emit them; `raw` is the projects.json entry, which carries
    # per-project model/effort/args that the env-based config cannot express.
    label: str = ""
    raw: dict[str, Any] | None = None


@dataclass
class CycleState:
    cycle: int | None
    phase: str
    status: str | None
    verdict: str | None
    latest_review: str | None
    branch_expected: str | None
    branch_current: str | None
    git_clean: bool
    head: str | None
    needs_user: str | None
    held: bool
    updated_at: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_env_file(root: Path) -> None:
    env_path = Path(os.environ.get("HERMES_ENV", root / ".cairn" / "hermes.env"))
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def config_from_env(args: argparse.Namespace) -> Config:
    root = Path(os.environ.get("HERMES_ROOT", "/home/pi/cairn")).resolve()
    load_env_file(root)
    log_dir = Path(os.environ.get("HERMES_LOG_DIR", root / "logs")).resolve()
    return Config(
        root=root,
        log_dir=log_dir,
        token=os.environ.get("HERMES_TELEGRAM_TOKEN", ""),
        chat_id=os.environ.get("HERMES_CHAT_ID", ""),
        claude_pane=os.environ.get("HERMES_CLAUDE_PANE", ""),
        codex_pane=os.environ.get("HERMES_CODEX_PANE", ""),
        poll_seconds=int(os.environ.get("HERMES_POLL_SECONDS", args.poll_seconds)),
        submit_key=os.environ.get("HERMES_SUBMIT_KEY", "C-m"),
        submit_delay=float(os.environ.get("HERMES_SUBMIT_DELAY", "0.35")),
        dry_run=args.dry_run,
        driver=os.environ.get("PEV_DRIVER", "tmux").strip() or "tmux",
    )


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def config_from_project(item: dict[str, Any], args: argparse.Namespace) -> Config:
    """Build a per-project Config. Telegram credentials and poll cadence stay
    process-global: there is exactly one bot token and one getUpdates consumer."""
    root = Path(str(item["root"])).expanduser().resolve()
    log_dir = Path(str(item.get("logDir") or root / "logs")).resolve()
    return Config(
        root=root,
        log_dir=log_dir,
        token=os.environ.get("HERMES_TELEGRAM_TOKEN", ""),
        chat_id=os.environ.get("HERMES_CHAT_ID", ""),
        claude_pane=str(item.get("claudePane") or ""),
        codex_pane=str(item.get("codexPane") or ""),
        poll_seconds=int(os.environ.get("HERMES_POLL_SECONDS", args.poll_seconds)),
        submit_key=os.environ.get("HERMES_SUBMIT_KEY", "C-m"),
        submit_delay=float(os.environ.get("HERMES_SUBMIT_DELAY", "0.35")),
        dry_run=args.dry_run,
        driver=str(item.get("driver") or "tmux"),
        label=str(item.get("name") or item["id"]),
        raw=dict(item),
    )


@dataclass
class ProjectEntry:
    id: str
    label: str
    cfg: Config
    archived: bool


def load_project_entries(args: argparse.Namespace) -> list[ProjectEntry]:
    registry = _read_json(PROJECTS_PATH, {"projects": []})
    meta = (_read_json(DASHBOARD_STATE_PATH, {}) or {}).get("projects") or {}
    entries: list[ProjectEntry] = []
    for item in registry.get("projects", []):
        try:
            pid = str(item["id"])
            cfg = config_from_project(item, args)
        except (KeyError, TypeError, ValueError):
            continue
        archived = bool((meta.get(pid) or {}).get("archived"))
        entries.append(ProjectEntry(id=pid, label=cfg.label, cfg=cfg, archived=archived))
    return entries


def run_cmd(args: list[str], cwd: Path, timeout: int = 10, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=check)


def git_out(cfg: Config, args: list[str]) -> str | None:
    result = run_cmd(["git", *args], cfg.root)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


# Resolved per project root. The default branch does not change during a run,
# and probing git on every scan_state would cost three subprocesses a tick.
_main_branch_cache: dict[str, str] = {}


def main_branch(cfg: Config) -> str:
    """The branch a merged cycle lands on.

    This used to be the literal "master", which silently disabled the entire
    post-merge phase for any repo on "main": phase never became "merged", so
    flow full never asked Codex to prepare the next cycle and an operator had to
    send it by hand every time.

    Resolution order: an explicit mainBranch in projects.json, then origin/HEAD,
    then whichever of main/master exists locally. The last-resort fallback is
    the current branch, which during a cycle is a feature branch — never cache
    that, or the wrong answer sticks for the life of the supervisor.
    """
    key = str(cfg.root)
    cached = _main_branch_cache.get(key)
    if cached:
        return cached

    explicit = (cfg.raw or {}).get("mainBranch")
    if not explicit and cfg.raw is None:
        # Single-project CLI only: in supervisor mode one env var would name a
        # branch for every project at once.
        explicit = os.environ.get("HERMES_MAIN_BRANCH")
    branch = str(explicit).strip() if explicit else ""

    if not branch:
        ref = git_out(cfg, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
        if ref and "/" in ref:
            branch = ref.split("/", 1)[1]

    if not branch:
        for candidate in ("main", "master"):
            probe = run_cmd(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{candidate}"], cfg.root)
            if probe.returncode == 0:
                branch = candidate
                break

    if not branch:
        return git_out(cfg, ["branch", "--show-current"]) or "main"

    _main_branch_cache[key] = branch
    return branch


def latest_cycle(root: Path) -> int | None:
    review_dir = root / ".review"
    if not review_dir.exists():
        return None
    found: list[int] = []
    for path in review_dir.iterdir():
        match = re.fullmatch(r"cycle-(\d+)", path.name)
        if match and path.is_dir():
            found.append(int(match.group(1)))
    return max(found) if found else None


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def parse_plan_branch(plan_text: str) -> str | None:
    for line in plan_text.splitlines():
        if line.startswith("Branch:"):
            return line.split(":", 1)[1].strip().strip("`") or None
    return None


def parse_plan_skills(plan_text: str) -> str | None:
    for line in plan_text.splitlines():
        if line.startswith("Skills:"):
            return line.split(":", 1)[1].strip().strip("`") or None
    return None


def latest_review_file(cycle_dir: Path) -> Path | None:
    reviews: list[tuple[int, Path]] = []
    for path in cycle_dir.glob("review-v*.md"):
        match = re.fullmatch(r"review-v(\d+)\.md", path.name)
        if match:
            reviews.append((int(match.group(1)), path))
    if not reviews:
        return None
    return max(reviews, key=lambda item: item[0])[1]


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


def expected_done_pass(state: CycleState) -> int | None:
    if state.cycle is None:
        return None
    if state.latest_review is None and state.status == "in_progress":
        return 1
    if state.verdict == "BLOCKED":
        n = review_number(state.latest_review)
        return n + 1 if n is not None else None
    return None


def executor_done_rel(cycle: int, pass_no: int) -> str:
    return f".review/cycle-{cycle}/executor/pass-{pass_no:03d}-done.json"


def executor_done_instruction(cycle: int, pass_no: int, kind: str, review: str | None = None) -> str:
    path = executor_done_rel(cycle, pass_no)
    marker = f"[[EXECUTOR_DONE:cycle={cycle} pass={pass_no:03d} kind={kind}]]"
    fields = [
        f"완료 신호: 작업이 끝나면 반드시 {path}를 생성하라.",
        "형식:",
        "{",
        f'  "cycle": {cycle},',
        f'  "pass": {pass_no},',
        f'  "kind": "{kind}",',
        f'  "review": {json.dumps(review, ensure_ascii=False)},',
        '  "createdAt": "<UTC ISO timestamp>",',
        '  "summary": "<short summary>",',
        '  "checks": ["<commands run>"]',
        "}",
        "이 done 파일은 Hermes가 Codex 검증/재검증으로 넘어가는 트리거다.",
        f"마지막 응답에는 완료 마커 {marker}를 한 줄로 포함하라.",
        ".claude Stop hook이 이 마커를 보고 done 파일 누락을 보완한다."
    ]
    return "\n".join(fields)


def processed_done_files(flow: dict[str, Any]) -> list[str]:
    raw = flow.get("processed_done_files")
    return [str(x) for x in raw] if isinstance(raw, list) else []


def mark_done_processed(flow: dict[str, Any], rel_path: str) -> None:
    processed = processed_done_files(flow)
    if rel_path not in processed:
        processed.append(rel_path)
    flow["processed_done_files"] = processed


def find_executor_done(cfg: Config, state: CycleState, pass_no: int, flow: dict[str, Any]) -> str | None:
    if state.cycle is None:
        return None
    cycle_dir = cfg.root / ".review" / f"cycle-{state.cycle}"
    candidates = [
        cycle_dir / "executor" / f"pass-{pass_no:03d}-done.json",
        cycle_dir / f"pass-{pass_no:03d}-done.json",
        cycle_dir / "executor" / f"pass-{pass_no}-done.json",
        cycle_dir / f"pass-{pass_no}-done.json",
    ]
    processed = set(processed_done_files(flow))
    for path in candidates:
        if path.exists():
            rel = str(path.relative_to(cfg.root))
            if rel not in processed:
                return rel
    return None


def hold_file(cfg: Config) -> Path:
    return cfg.log_dir / "hermes-hold"


def flow_file(cfg: Config) -> Path:
    return cfg.log_dir / "hermes-flow.json"


def scan_state(cfg: Config) -> CycleState:
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    cycle = latest_cycle(cfg.root)
    branch_current = git_out(cfg, ["branch", "--show-current"])
    trunk = main_branch(cfg)
    head = git_out(cfg, ["rev-parse", "--short", "HEAD"])
    status_short = git_out(cfg, ["status", "--short"]) or ""
    git_clean = status_short == ""
    held = hold_file(cfg).exists()

    status_value: str | None = None
    latest_review: str | None = None
    verdict: str | None = None
    branch_expected: str | None = None

    if cycle is None:
        phase = "no_cycle"
        needs_user = None
    else:
        cycle_dir = cfg.root / ".review" / f"cycle-{cycle}"
        status_text = read_text(cycle_dir / "status.txt").strip()
        status_value = status_text or None
        branch_expected = parse_plan_branch(read_text(cycle_dir / "plan.md"))
        review_path = latest_review_file(cycle_dir)
        if review_path is not None:
            latest_review = str(review_path.relative_to(cfg.root))
            verdict = parse_verdict(read_text(review_path))

        if status_value == "escalated":
            phase = "escalated"
            needs_user = "escalation decision"
        elif held:
            phase = "held"
            needs_user = "resume"
        elif (
            status_value == "ready_to_merge"
            and verdict == "READY_TO_MERGE"
            and branch_current == trunk
            and branch_expected not in (None, trunk)
        ):
            phase = "merged"
            needs_user = "next cycle decision"
        elif status_value == "ready_to_merge" and verdict == "READY_TO_MERGE":
            phase = "ready_to_merge"
            needs_user = "merge approval"
        elif verdict == "BLOCKED":
            phase = "review_blocked"
            needs_user = "executor fix"
        elif verdict in ("PASS", "READY_TO_MERGE"):
            phase = "review_pass"
            needs_user = "mark ready or merge decision"
        elif status_value == "in_progress":
            phase = "in_progress"
            needs_user = None
        else:
            phase = "unknown"
            needs_user = "inspect cycle files"

    return CycleState(
        cycle=cycle,
        phase=phase,
        status=status_value,
        verdict=verdict,
        latest_review=latest_review,
        branch_expected=branch_expected,
        branch_current=branch_current,
        git_clean=git_clean,
        head=head,
        needs_user=needs_user,
        held=held,
        updated_at=utc_now(),
    )


def state_path(cfg: Config) -> Path:
    return cfg.log_dir / "hermes-state.json"


def offset_path(cfg: Config) -> Path:
    return cfg.log_dir / "hermes-offset.txt"


def events_path(cfg: Config) -> Path:
    return cfg.log_dir / "hermes-events.jsonl"


def load_previous_state(cfg: Config) -> dict[str, Any] | None:
    path = state_path(cfg)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def save_state(cfg: Config, state: CycleState) -> None:
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    state_path(cfg).write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def default_flow_state() -> dict[str, Any]:
    return {
        "mode": "off",
        "waiting_for": None,
        "saw_busy": False,
        "last_action_key": None,
        "last_notice_key": None,
        "last_action_at": None,
        "waiting_for_review_from": None,
        "processed_done_files": [],
        "last_metric_keys": {},
        "updated_at": utc_now(),
    }


# The flow file has two writers: the supervisor's tick and the short-lived
# `--command` process the dashboard spawns per button press. Each did a plain
# read-modify-write, so a tick that loaded the file before a `/flow full` landed
# would write its stale copy back and silently revert the mode.
#
# Ownership makes the merge unambiguous: `mode` is set by commands only, every
# other field by the flow engine only. A writer persists just the fields it owns,
# under an exclusive lock, and the file is replaced atomically so no reader ever
# sees a half-written JSON.
FLOW_COMMAND_OWNED_KEYS = ("mode",)


def _normalize_flow(data: Any) -> dict[str, Any]:
    base = default_flow_state()
    if isinstance(data, dict):
        base.update(data)
    if base.get("mode") not in {"off", "safe", "full"}:
        base["mode"] = "off"
    if not isinstance(base.get("processed_done_files"), list):
        base["processed_done_files"] = []
    if not isinstance(base.get("last_metric_keys"), dict):
        base["last_metric_keys"] = {}
    return base


def _read_flow_unlocked(cfg: Config) -> dict[str, Any]:
    path = flow_file(cfg)
    if not path.exists():
        return default_flow_state()
    try:
        return _normalize_flow(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return default_flow_state()


@contextmanager
def flow_lock(cfg: Config):
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    lock_path = flow_file(cfg).with_suffix(".lock")
    with open(lock_path, "w", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def load_flow_state(cfg: Config) -> dict[str, Any]:
    return _read_flow_unlocked(cfg)


def save_flow_state(cfg: Config, flow: dict[str, Any], *, owns_mode: bool = False) -> None:
    """Persist only the fields this writer owns, merged onto the current file.

    owns_mode=True marks the caller as the command path (set_flow_mode): it
    writes `mode` and nothing else. Everyone else is the flow engine: it writes
    everything except `mode`.
    """
    with flow_lock(cfg):
        disk = _read_flow_unlocked(cfg)
        if owns_mode:
            disk["mode"] = flow.get("mode", disk.get("mode", "off"))
        else:
            for key, value in flow.items():
                if key not in FLOW_COMMAND_OWNED_KEYS:
                    disk[key] = value
        disk["updated_at"] = utc_now()
        path = flow_file(cfg)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(disk, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    # Let the caller's in-memory copy see fields it does not own but did not write.
    for key in FLOW_COMMAND_OWNED_KEYS:
        flow[key] = disk[key]


def log_event(cfg: Config, event: str, data: dict[str, Any]) -> None:
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    record = {"ts": utc_now(), "event": event, **data}
    with events_path(cfg).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def format_status(state: CycleState) -> str:
    return "\n".join(
        [
            f"Cycle: {state.cycle if state.cycle is not None else '-'}",
            f"Phase: {state.phase}",
            f"Status: {state.status or '-'}",
            f"Verdict: {state.verdict or '-'}",
            f"Review: {state.latest_review or '-'}",
            f"Branch: {state.branch_current or '-'}",
            f"Expected: {state.branch_expected or '-'}",
            f"Git clean: {'yes' if state.git_clean else 'no'}",
            f"HEAD: {state.head or '-'}",
            f"Needs: {state.needs_user or '-'}",
            f"Held: {'yes' if state.held else 'no'}",
        ]
    )


def telegram_api(cfg: Config, method: str, payload: dict[str, Any], timeout: int = 20) -> dict[str, Any] | None:
    if not cfg.token:
        return None
    url = f"https://api.telegram.org/bot{cfg.token}/{method}"
    body = parse.urlencode(payload).encode("utf-8")
    req = request.Request(url, data=body)
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_telegram(cfg: Config, text: str, reply_markup: dict[str, Any] | None = None) -> None:
    if cfg.dry_run or not cfg.token or not cfg.chat_id:
        print(f"[telegram dry-run]\n{text}")
        if reply_markup:
            print(json.dumps(reply_markup, ensure_ascii=False))
        return
    payload: dict[str, Any] = {"chat_id": cfg.chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    telegram_api(cfg, "sendMessage", payload)


def set_bot_commands(cfg: Config) -> None:
    payload = {"commands": json.dumps(BOT_COMMANDS, ensure_ascii=False)}
    if cfg.dry_run or not cfg.token:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    telegram_api(cfg, "setMyCommands", payload)


def menu_markup(state: CycleState) -> dict[str, Any]:
    rows: list[list[dict[str, str]]] = [
        [
            {"text": "상태", "callback_data": "/status"},
            {"text": "Codex tail", "callback_data": "/tail codex"},
        ],
        [
            {"text": "Claude tail", "callback_data": "/tail claude"},
            {"text": "구현 시작", "callback_data": "/implement"},
        ],
        [
            {"text": "남은 스펙", "callback_data": "/remaining"},
            {"text": "다음 준비", "callback_data": "/prepare_next"},
        ],
        [
            {"text": "검증", "callback_data": "/review"},
            {"text": "재검증", "callback_data": "/recheck"},
        ],
        [
            {"text": "수정 요청", "callback_data": "/fix"},
        ],
        [
            {"text": "Codex Enter", "callback_data": "/enter codex"},
            {"text": "Claude Enter", "callback_data": "/enter claude"},
        ],
        [
            {"text": "Hold", "callback_data": "/hold"},
            {"text": "Resume", "callback_data": "/resume"},
        ],
        [
            {"text": "Flow 상태", "callback_data": "/flow status"},
            {"text": "Flow safe", "callback_data": "/flow safe"},
            {"text": "Flow off", "callback_data": "/flow off"},
        ],
    ]
    if state.phase == "ready_to_merge":
        rows.insert(2, [{"text": "머지", "callback_data": "/merge"}])
    return {"inline_keyboard": rows}


def send_menu(cfg: Config, state: CycleState) -> None:
    send_telegram(cfg, f"Hermes menu\n\n{format_status(state)}", reply_markup=menu_markup(state))


def load_supervisor_state() -> dict[str, Any]:
    if not SUPERVISOR_STATE_PATH.exists():
        return {}
    try:
        data = json.loads(SUPERVISOR_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_supervisor_state(data: dict[str, Any]) -> None:
    SUPERVISOR_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUPERVISOR_STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_offset(cfg: Config) -> int | None:
    if SUPERVISOR_MODE:
        value = load_supervisor_state().get("offset")
        return int(value) if isinstance(value, int) else None
    path = offset_path(cfg)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return int(text) if text.isdigit() else None


def write_offset(cfg: Config, offset: int) -> None:
    if SUPERVISOR_MODE:
        data = load_supervisor_state()
        data["offset"] = offset
        save_supervisor_state(data)
        return
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    offset_path(cfg).write_text(str(offset) + "\n", encoding="utf-8")


def get_updates(cfg: Config, once: bool) -> list[dict[str, Any]]:
    if not cfg.token or not cfg.chat_id:
        return []
    payload: dict[str, Any] = {"timeout": 0 if once else min(25, cfg.poll_seconds)}
    offset = read_offset(cfg)
    if offset is not None:
        payload["offset"] = offset
    data = telegram_api(cfg, "getUpdates", payload, timeout=35)
    if not data or not data.get("ok"):
        return []
    updates = data.get("result", [])
    if updates:
        write_offset(cfg, max(int(u["update_id"]) for u in updates) + 1)
    return updates


# --- agent I/O layer -------------------------------------------------------
# All agent interaction goes through pev_runner (tmux or headless driver).
# Agents are addressed by name ("claude" / "codex"), no longer by pane string.

_runners: dict[tuple[str, bool], AgentRunner] = {}


def get_runner(cfg: Config) -> AgentRunner:
    """One runner per (project root, dry_run).

    Keyed by root because the supervisor drives several projects from a single
    process: a module-wide singleton would route every project's prompts into
    whichever project happened to build it first.
    """
    key = (str(cfg.root), cfg.dry_run)
    runner = _runners.get(key)
    if runner is not None:
        return runner
    if cfg.raw is not None:
        rc = RunnerConfig.from_project(cfg.raw)
        rc.dry_run = cfg.dry_run
    else:
        rc = RunnerConfig.from_env(cfg.root, dry_run=cfg.dry_run)
    rc.root = cfg.root
    rc.log_dir = cfg.log_dir
    rc.driver = cfg.driver
    if cfg.claude_pane:
        rc.claude_pane = cfg.claude_pane
    if cfg.codex_pane:
        rc.codex_pane = cfg.codex_pane
    # Sessions are derived from the panes, never inherited from the environment:
    # PEV_CLAUDE_SESSION in the unit's EnvironmentFile names *one* project, so
    # honoring it here would aim every project at that project's tmux sessions.
    # Derivation also preserves historical names like cairn's "codex-hermes".
    rc.claude_session = ""
    rc.codex_session = ""
    runner = AgentRunner(rc)
    _runners[key] = runner
    return runner


def capture_pane(cfg: Config, agent: str, lines: int = 80) -> str:
    if agent not in ("claude", "codex"):
        return "agent not configured"
    return get_runner(cfg).tail(agent, lines).strip()[-3500:] or "(empty)"


def pane_label(cfg: Config, agent: str) -> str:
    return {"claude": "Claude", "codex": "Codex"}.get(agent, agent or "unknown")


def submit_pane(cfg: Config, agent: str, label: str | None = None, delay: bool = True) -> str:
    if agent not in ("claude", "codex"):
        return "agent not configured"
    return get_runner(cfg).press_enter(agent, delay)


def paste_to_pane(cfg: Config, agent: str, text: str, label: str | None = None) -> str:
    if agent not in ("claude", "codex"):
        return "agent not configured"
    target = label or pane_label(cfg, agent)
    reply = get_runner(cfg).send(agent, text)
    return f"{target}: {reply}" if not reply.startswith(agent) else f"{target} — {reply.split(': ', 1)[-1]}"


def pane_for(cfg: Config, target: str) -> str:
    return target if target in ("claude", "codex") else ""


def agent_idle(cfg: Config, agent: str) -> bool:
    return bool(get_runner(cfg).idle(agent))


def agent_alive(cfg: Config, agent: str) -> bool | None:
    """True/False for tmux (session exists?), None for headless (n/a)."""
    try:
        return get_runner(cfg).alive(agent)
    except (OSError, subprocess.SubprocessError):
        return None


def session_label(alive: bool | None) -> str:
    if alive is None:
        return "n/a (headless)"
    return "alive" if alive else "DEAD"


def flow_status_text(cfg: Config, state: CycleState) -> str:
    flow = load_flow_state(cfg)
    claude_alive = agent_alive(cfg, "claude")
    codex_alive = agent_alive(cfg, "codex")
    claude_idle = agent_idle(cfg, "claude")
    codex_idle = agent_idle(cfg, "codex")
    done_pass = expected_done_pass(state)
    pending_done = find_executor_done(cfg, state, done_pass, flow) if done_pass is not None else None
    return "\n".join(
        [
            f"Flow mode: {flow.get('mode', 'off')}",
            f"Waiting for: {flow.get('waiting_for') or '-'}",
            f"Saw busy: {'yes' if flow.get('saw_busy') else 'no'}",
            f"Last action: {flow.get('last_action_key') or '-'}",
            f"Last notice: {flow.get('last_notice_key') or '-'}",
            f"Expected done pass: {done_pass if done_pass is not None else '-'}",
            f"Pending done: {pending_done or '-'}",
            f"Processed done: {len(processed_done_files(flow))}",
            f"Claude session: {session_label(claude_alive)}",
            f"Codex session: {session_label(codex_alive)}",
            f"Claude idle: {'yes' if claude_idle else 'no'}",
            f"Codex idle: {'yes' if codex_idle else 'no'}",
            "",
            format_status(state),
        ]
    )


def set_flow_mode(cfg: Config, mode: str) -> str:
    """Change the mode and nothing else.

    This used to clear last_action_key and processed_done_files as a "fresh
    start". But those are the flow's idempotency guards: wiping them makes it
    forget that it already sent 머지하라 or already fed a done file to Codex, so
    flipping safe→full right after a manual merge re-sent the merge prompt
    seconds later. Mode is the only field a command owns.
    """
    flow = load_flow_state(cfg)
    flow["mode"] = mode
    save_flow_state(cfg, flow, owns_mode=True)
    return _flow_mode_reply(mode)


def reset_flow_state(cfg: Config) -> str:
    """Clear the engine's progress memory, keeping the mode.

    Mode changes used to do this implicitly, which is how an operator unstuck a
    flow parked on a stale waiting_for. Now that the guards survive a mode flip,
    the escape hatch has to be asked for."""
    flow = load_flow_state(cfg)
    flow.update({
        "waiting_for": None,
        "saw_busy": False,
        "last_action_key": None,
        "last_notice_key": None,
        "last_action_at": None,
        "waiting_for_review_from": None,
        "processed_done_files": [],
    })
    save_flow_state(cfg, flow)
    return f"Flow progress reset. Mode stays {flow.get('mode', 'off')}."


def _flow_mode_reply(mode: str) -> str:
    if mode == "off":
        return "Flow stopped."
    if mode == "safe":
        return "Flow safe enabled. Auto: implement → review → fix/recheck. Stops before merge/next-cycle."
    return "Flow full enabled. Auto includes merge and next-cycle preparation after ready state."


def mark_flow_action(flow: dict[str, Any], key: str, waiting_for: str | None = None) -> None:
    flow["last_action_key"] = key
    flow["waiting_for"] = waiting_for
    flow["saw_busy"] = False
    flow["last_action_at"] = utc_now()


def paste_delivered(reply: str) -> bool:
    """False when the pane had to be (re)created, so the text never reached the CLI."""
    return "resend in a few seconds" not in reply


def stamp_manual_action(cfg: Config, key: str, waiting_for: str, review_from: str | None = None) -> None:
    """Record a hand-issued command under the key the flow would have used.

    Manual /merge used to leave the flow state untouched, so the next tick still
    saw the transition as pending and sent its own 머지하라 — Codex received the
    prompt twice, seconds apart. Sharing the key makes the flow's existing
    dedupe cover operator actions too."""
    flow = load_flow_state(cfg)
    if review_from is not None:
        flow["waiting_for_review_from"] = review_from
    mark_flow_action(flow, key, waiting_for)
    save_flow_state(cfg, flow)


def flow_idle_grace_elapsed(flow: dict[str, Any]) -> bool:
    raw = flow.get("last_action_at")
    if not raw:
        return False
    try:
        last_action_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    elapsed = datetime.now(timezone.utc) - last_action_at
    return elapsed.total_seconds() >= FLOW_IDLE_GRACE_SECONDS


def tagged(cfg: Config, message: str) -> str:
    return f"[{cfg.label}] {message}" if cfg.label else message


def send_flow_notice(cfg: Config, flow: dict[str, Any], key: str, message: str) -> None:
    if flow.get("last_notice_key") == key:
        return
    flow["last_notice_key"] = key
    send_telegram(cfg, tagged(cfg, message))


def flow_send_review(cfg: Config, flow: dict[str, Any], state: CycleState, prompt: str) -> str:
    key = f"cycle-{state.cycle}:codex:{prompt}"
    if flow.get("last_action_key") == key:
        return "Flow: review command already sent"
    reply = paste_to_pane(cfg, "codex", prompt, "Codex")
    flow["waiting_for_review_from"] = state.latest_review
    mark_flow_action(flow, key, "codex_review")
    return reply


def flow_send_review_for_done(
    cfg: Config,
    flow: dict[str, Any],
    state: CycleState,
    done_rel: str,
    prompt: str,
) -> str:
    key = f"cycle-{state.cycle}:done:{done_rel}:{prompt}"
    if flow.get("last_action_key") == key:
        return "Flow: done file already sent to Codex"
    reply = paste_to_pane(cfg, "codex", prompt, "Codex")
    mark_done_processed(flow, done_rel)
    flow["waiting_for_review_from"] = state.latest_review
    mark_flow_action(flow, key, "codex_review")
    return reply


def ensure_agents_ready(cfg: Config, flow: dict[str, Any]) -> str | None:
    """Recreate any dead tmux session before the flow reads idle state.

    A dead pane makes idle() return None, which reads as 'busy' upstream — the
    flow would then wait forever and never reach the send() that self-heals.
    Returns a message when something was (re)created so the caller skips this
    tick and lets the CLI boot; None when both sessions are usable."""
    recreated: list[str] = []
    for agent in ("claude", "codex"):
        if agent_alive(cfg, agent) is False:
            get_runner(cfg).start(agent)
            recreated.append(agent)
    if not recreated:
        return None
    names = ", ".join(recreated)
    send_flow_notice(cfg, flow, f"pane-recreated:{names}",
                     f"Flow: recreated tmux session(s) for {names}; waiting for CLI boot.")
    return f"Flow: recreated tmux session(s) for {names}. Waiting for boot; advancing next tick."


def maybe_advance_flow(cfg: Config, state: CycleState, force: bool = False) -> str | None:
    flow = load_flow_state(cfg)
    mode = flow.get("mode", "off")
    if mode == "off" and not force:
        return None
    if state.held or state.phase == "held":
        return None
    if state.phase == "escalated":
        send_flow_notice(cfg, flow, f"cycle-{state.cycle}:escalated", "Flow paused: cycle escalated.")
        save_flow_state(cfg, flow)
        return None

    ready_msg = ensure_agents_ready(cfg, flow)
    if ready_msg:
        save_flow_state(cfg, flow)
        return ready_msg

    claude_idle = agent_idle(cfg, "claude")
    codex_idle = agent_idle(cfg, "codex")
    waiting_for = flow.get("waiting_for")
    done_pass = expected_done_pass(state)
    pending_done = find_executor_done(cfg, state, done_pass, flow) if done_pass is not None else None

    if waiting_for == "claude_implement" and state.phase != "in_progress":
        flow["waiting_for"] = None
        flow["saw_busy"] = False
        waiting_for = None
        save_flow_state(cfg, flow)
    if waiting_for == "claude_fix" and state.phase != "review_blocked":
        flow["waiting_for"] = None
        flow["saw_busy"] = False
        waiting_for = None
        save_flow_state(cfg, flow)

    if waiting_for == "claude_implement":
        if pending_done:
            if not codex_idle and not force:
                send_flow_notice(cfg, flow, f"{pending_done}:codex-wait", f"Flow waiting: Codex is not idle for {pending_done}.")
                save_flow_state(cfg, flow)
                return None
            reply = flow_send_review_for_done(cfg, flow, state, pending_done, "구현 검증")
            save_flow_state(cfg, flow)
            send_telegram(cfg, f"Flow advanced: {pending_done} → Codex review\n{reply}")
            return reply
        if not claude_idle:
            flow["saw_busy"] = True
            save_flow_state(cfg, flow)
            return None
        if force:
            reply = flow_send_review(cfg, flow, state, "구현 검증")
            save_flow_state(cfg, flow)
            send_telegram(cfg, f"Flow forced: Codex review without done file\n{reply}")
            return reply
        expected = executor_done_rel(state.cycle, done_pass) if done_pass is not None else "executor done file"
        send_flow_notice(cfg, flow, f"{expected}:implement:done-wait", f"Flow waiting: {expected} before Codex review.")
        save_flow_state(cfg, flow)
        return None

    if waiting_for == "claude_fix":
        if pending_done:
            if not codex_idle and not force:
                send_flow_notice(cfg, flow, f"{pending_done}:codex-wait", f"Flow waiting: Codex is not idle for {pending_done}.")
                save_flow_state(cfg, flow)
                return None
            reply = flow_send_review_for_done(cfg, flow, state, pending_done, "재검증")
            save_flow_state(cfg, flow)
            send_telegram(cfg, f"Flow advanced: {pending_done} → Codex recheck\n{reply}")
            return reply
        if not claude_idle:
            flow["saw_busy"] = True
            save_flow_state(cfg, flow)
            return None
        if force:
            reply = flow_send_review(cfg, flow, state, "재검증")
            save_flow_state(cfg, flow)
            send_telegram(cfg, f"Flow forced: Codex recheck without done file\n{reply}")
            return reply
        expected = executor_done_rel(state.cycle, done_pass) if done_pass is not None else "executor done file"
        send_flow_notice(cfg, flow, f"{expected}:fix:done-wait", f"Flow waiting: {expected} before Codex recheck.")
        save_flow_state(cfg, flow)
        return None

    if waiting_for == "codex_review":
        if not codex_idle:
            flow["saw_busy"] = True
            save_flow_state(cfg, flow)
            return None
        baseline_review = flow.get("waiting_for_review_from")
        if state.latest_review == baseline_review:
            send_flow_notice(cfg, flow, f"cycle-{state.cycle}:codex-review:file-wait", "Flow waiting: Codex review file/state change.")
            save_flow_state(cfg, flow)
            return None
        flow["waiting_for"] = None
        flow["saw_busy"] = False
        flow.pop("waiting_for_review_from", None)
        waiting_for = None
        save_flow_state(cfg, flow)

    if waiting_for in {"codex_merge", "codex_next_cycle"}:
        if not codex_idle:
            flow["saw_busy"] = True
            save_flow_state(cfg, flow)
            return None
        save_flow_state(cfg, flow)

    if state.cycle is None:
        return None

    if pending_done:
        prompt = "구현 검증" if state.latest_review is None else "재검증"
        if not codex_idle and not force:
            send_flow_notice(cfg, flow, f"{pending_done}:codex-wait", f"Flow waiting: Codex is not idle for {pending_done}.")
            save_flow_state(cfg, flow)
            return None
        reply = flow_send_review_for_done(cfg, flow, state, pending_done, prompt)
        save_flow_state(cfg, flow)
        send_telegram(cfg, f"Flow advanced: {pending_done} → Codex {prompt}\n{reply}")
        return reply

    if state.status == "in_progress" and state.latest_review is None:
        key = f"cycle-{state.cycle}:implement"
        if flow.get("last_action_key") == key:
            return None
        if not claude_idle and not force:
            send_flow_notice(cfg, flow, f"{key}:wait", f"Flow waiting: Claude is not idle for cycle {state.cycle} implement.")
            save_flow_state(cfg, flow)
            return None
        prompt, err = build_implement_prompt(cfg, state)
        if err:
            send_flow_notice(cfg, flow, f"{key}:blocked", f"Flow paused: {err}")
            save_flow_state(cfg, flow)
            return err
        reply = paste_to_pane(cfg, "claude", prompt or "", "Claude")
        mark_flow_action(flow, key, "claude_implement")
        save_flow_state(cfg, flow)
        send_telegram(cfg, f"Flow advanced: implement started\n{reply}")
        return reply

    if state.verdict == "BLOCKED" and state.latest_review:
        key = f"cycle-{state.cycle}:fix:{state.latest_review}"
        if flow.get("last_action_key") == key:
            return None
        if not claude_idle and not force:
            send_flow_notice(cfg, flow, f"{key}:wait", f"Flow waiting: Claude is not idle for {state.latest_review} fix.")
            save_flow_state(cfg, flow)
            return None
        review = state.latest_review
        pass_no = done_pass or ((review_number(review) or 0) + 1)
        prompt = "\n\n".join(
            [
                f"{review}의 Findings대로 수정하고 RESOLVED를 sentinel 아래에 append하라. plan scope를 넘기지 마라.",
                executor_done_instruction(state.cycle, pass_no, "fix", review),
            ]
        )
        reply = paste_to_pane(cfg, "claude", prompt, "Claude")
        mark_flow_action(flow, key, "claude_fix")
        save_flow_state(cfg, flow)
        send_telegram(cfg, f"Flow advanced: fix started\n{reply}")
        return reply

    if state.phase == "ready_to_merge":
        key = f"cycle-{state.cycle}:ready_to_merge:{state.latest_review or '-'}"
        if mode != "full" and not force:
            send_flow_notice(cfg, flow, key, "Flow safe paused: ready_to_merge. Use /merge or /flow full.")
            save_flow_state(cfg, flow)
            return None
        merge_key = f"cycle-{state.cycle}:merge:{state.latest_review or '-'}"
        if flow.get("last_action_key") == merge_key:
            return None
        if not codex_idle and not force:
            send_flow_notice(cfg, flow, f"{merge_key}:wait", "Flow waiting: Codex is not idle for merge.")
            save_flow_state(cfg, flow)
            return None
        reply = paste_to_pane(cfg, "codex", "머지하라", "Codex")
        mark_flow_action(flow, merge_key, "codex_merge")
        save_flow_state(cfg, flow)
        send_telegram(cfg, f"Flow advanced: merge requested\n{reply}")
        return reply

    if state.phase == "merged" and mode == "full":
        key = f"cycle-{state.cycle}:next_cycle"
        if flow.get("last_action_key") == key:
            return None
        if not codex_idle and not force:
            send_flow_notice(cfg, flow, f"{key}:wait", "Flow waiting: Codex is not idle for next-cycle preparation.")
            save_flow_state(cfg, flow)
            return None
        prompt = "남은 구현 스펙을 판단하고, 가장 적합한 다음 스펙 하나를 추천한 뒤 그 스펙으로 바로 사이클 준비하라."
        reply = paste_to_pane(cfg, "codex", prompt, "Codex")
        mark_flow_action(flow, key, "codex_next_cycle")
        save_flow_state(cfg, flow)
        send_telegram(cfg, f"Flow advanced: next-cycle preparation requested\n{reply}")
        return reply

    save_flow_state(cfg, flow)
    return None


def automation_allowed(state: CycleState, command: str) -> tuple[bool, str | None]:
    always = {"/status", "/cycle", "/tail", "/say", "/enter", "/help", "/start", "/menu", "/hold", "/resume", "/flow"}
    if command in always:
        return True, None
    if state.phase == "escalated":
        return False, "cycle is escalated; use /say or /resume after deciding"
    if state.phase == "held":
        return False, "Hermes is held; use /resume first"
    return True, None


def append_manual_check(cfg: Config, cycle: int, evidence: str) -> str:
    path = cfg.root / ".review" / f"cycle-{cycle}" / "manual-checks.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = f"\n## Telegram Evidence — {utc_now()}\n\n{evidence.strip()}\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(entry)
    return str(path.relative_to(cfg.root))


def command_title(text: str) -> str:
    parts = text.strip().split(maxsplit=2)
    if not parts:
        return "명령 처리"
    command = parts[0].lower()
    if command == "/prepare-next":
        command = "/prepare_next"
    labels = {
        "/status": "상태 확인 중",
        "/cycle": "상태 확인 중",
        "/menu": "메뉴 여는 중",
        "/tail": "로그 불러오는 중",
        "/tail codex": "Codex 로그 불러오는 중",
        "/tail claude": "Claude 로그 불러오는 중",
        "/remaining": "Codex에 남은 구현 스펙 요청 중",
        "/prepare_next": "Codex에 다음 사이클 준비 요청 중",
        "/implement": "Claude에 최신 cycle 구현 시작 요청 중",
        "/review": "Codex에 구현 검증 요청 중",
        "/recheck": "Codex에 재검증 요청 중",
        "/fix": "Claude에 수정 요청 중",
        "/merge": "Codex에 머지 요청 중",
        "/flow": "Flow 상태 처리 중",
        "/hold": "Hermes hold 처리 중",
        "/resume": "Hermes resume 처리 중",
        "/help": "도움말 여는 중",
        "/start": "도움말 여는 중",
    }
    if command == "/tail" and len(parts) >= 2:
        specific = f"/tail {parts[1].lower()}"
        return labels.get(specific, labels["/tail"])
    if command == "/say" and len(parts) >= 2:
        return f"{parts[1]}에게 직접 지시 전송 중"
    if command == "/enter" and len(parts) >= 2:
        target = "Codex" if parts[1].lower() == "codex" else "Claude" if parts[1].lower() == "claude" else parts[1]
        return f"{target}에 Enter 전송 중"
    return labels.get(command, f"{parts[0]} 처리 중")


def help_text(state: CycleState) -> str:
    merge_line = "available" if state.phase == "ready_to_merge" else f"blocked now: phase={state.phase}"
    return (
        "Hermes command help\n\n"
        "Projects\n"
        "/project — 프로젝트 목록과 현재 대상 표시\n"
        "/project <id> — 이후 모든 명령의 대상 전환\n\n"
        "Status / observation\n"
        "/status — 현재 cycle, phase, verdict, branch, clean 상태\n"
        "/cycle — /status alias\n"
        "/menu — 누르는 버튼 메뉴 표시\n"
        "/tail claude — Claude tmux pane 최근 화면\n"
        "/tail codex — Codex tmux pane 최근 화면\n\n"
        "Cycle actions\n"
        "/remaining — Codex에 '남은 구현 스펙' 전송\n"
        "/prepare_next — Codex에 '그것으로 사이클 준비' 전송\n"
        "/implement — 최신 cycle plan 기준으로 Claude executor 시작\n"
        "/review — Codex에 '구현 검증' 전송\n"
        "/recheck — Codex에 '재검증' 전송\n"
        "/fix — Claude에 최신 review Findings 수정 요청\n"
        f"/merge — Codex에 '머지하라' 전송 ({merge_line})\n\n"
        "Auto flow\n"
        "/flow status — 자동 흐름 상태와 idle 감지 상태\n"
        "/flow safe — 구현→검증→수정→재검증 자동, merge 앞에서 정지\n"
        "/flow full — safe + merge + 다음 cycle 준비까지 자동\n"
        "/flow step — 현재 상태에서 가능한 다음 단계 1회 강제 시도\n"
        "/flow reset — 진행 기억(waiting_for·중복 가드) 초기화, 모드는 유지\n"
        "/flow off — 자동 흐름 정지\n\n"
        "Manual intervention\n"
        "/say claude <text> — Claude pane에 직접 지시\n"
        "/say codex <text> — Codex pane에 직접 지시\n"
        "/enter codex — Codex 현재 입력창에 Enter만 전송\n"
        "/enter claude — Claude 현재 입력창에 Enter만 전송\n"
        "/approve-ui <cycle> <evidence> — 수동 UI 확인 기록 저장\n\n"
        "Safety\n"
        "/hold — Hermes 자동 조작 중지\n"
        "/resume — hold 해제\n"
        "escalated/held 상태에서는 /status, /tail, /say, /resume 중심으로만 다룹니다.\n\n"
        "Current\n"
        f"{format_status(state)}"
    )


def build_implement_prompt(cfg: Config, state: CycleState) -> tuple[str | None, str | None]:
    if state.cycle is None:
        return None, "Refused: no cycle directory found"
    if state.status != "in_progress":
        return None, f"Refused: cycle-{state.cycle} status is {state.status or '-'}, not in_progress"
    if state.latest_review is not None:
        return None, f"Refused: cycle-{state.cycle} already has {state.latest_review}; use /fix, /recheck, or /merge"

    plan_path = cfg.root / ".review" / f"cycle-{state.cycle}" / "plan.md"
    plan_text = read_text(plan_path)
    if not plan_text:
        return None, f"Refused: missing .review/cycle-{state.cycle}/plan.md"

    branch = state.branch_expected or parse_plan_branch(plan_text)
    if not branch:
        return None, f"Refused: .review/cycle-{state.cycle}/plan.md has no Branch line"
    skills = parse_plan_skills(plan_text) or "none"

    prompt = "\n".join(
        [
            f"Cycle {state.cycle} executor 시작.",
            "",
            "AGENTS.md와 .review/cycle-{cycle}/plan.md를 읽고 구현하라.".format(cycle=state.cycle),
            "첫 동작은 현재 branch 확인 후 필요하면:",
            f"git switch {branch}",
            "",
            f"Skills: {skills}. plan의 Skills 선언과 실제 로드를 맞춰라.",
            "Scope는 .review/cycle-{cycle}/plan.md 안으로 제한한다.".format(cycle=state.cycle),
            "plan.md는 mid-cycle 수정하지 마라.",
            "Codex review 본문이나 review-vN.md는 작성하지 마라.",
            "",
            "자연스러운 구현 step마다 Advisor feedback을",
            ".review/cycle-{cycle}/advisor-feedback/step-NNN.md에 저장하라.".format(cycle=state.cycle),
            "Advisor 의견을 무시하면 Sonnet Response에 이유를 명시하라.",
            "",
            "구현 후 Sprint Contract의 자동 체크를 실행하고 결과를 요약하라.",
            "docs/codebase-map.md 업데이트가 필요한 변경이면 같은 cycle 안에서 반영하라.",
            "status.txt는 Cycle Reviewer가 통과시키기 전까지 in_progress로 둔다.",
            "",
            executor_done_instruction(state.cycle, 1, "implement", None),
        ]
    )
    return prompt, None


def handle_command(cfg: Config, text: str, state: CycleState) -> str:
    parts = text.strip().split(maxsplit=2)
    if not parts:
        return ""
    command = parts[0].lower()
    if command == "/approve_ui":
        command = "/approve-ui"
    if command == "/prepare-next":
        command = "/prepare_next"
    ok, reason = automation_allowed(state, command)
    if not ok:
        return f"Refused: {reason}"

    if command in {"/help", "/start"}:
        return help_text(state)
    if command == "/menu":
        send_menu(cfg, state)
        return ""
    if command in {"/status", "/cycle"}:
        return format_status(state)
    if command == "/tail":
        target = parts[1] if len(parts) >= 2 else ""
        return capture_pane(cfg, pane_for(cfg, target))
    if command == "/say":
        if len(parts) < 3:
            return "Usage: /say claude|codex <text>"
        return paste_to_pane(cfg, pane_for(cfg, parts[1]), parts[2])
    if command == "/enter":
        target = parts[1] if len(parts) >= 2 else "codex"
        label = "Codex" if target == "codex" else "Claude" if target == "claude" else target
        return submit_pane(cfg, pane_for(cfg, target), label, delay=False)
    if command == "/remaining":
        return paste_to_pane(cfg, "codex", "남은 구현 스펙", "Codex")
    if command == "/prepare_next":
        reply = paste_to_pane(cfg, "codex", "그것으로 사이클 준비", "Codex")
        if state.cycle is not None and paste_delivered(reply):
            stamp_manual_action(cfg, f"cycle-{state.cycle}:next_cycle", "codex_next_cycle")
        return reply
    if command == "/implement":
        prompt, err = build_implement_prompt(cfg, state)
        if err:
            return err
        reply = paste_to_pane(cfg, "claude", prompt or "", "Claude")
        if state.cycle is not None and paste_delivered(reply):
            stamp_manual_action(cfg, f"cycle-{state.cycle}:implement", "claude_implement")
        return reply
    if command in {"/review", "/recheck"}:
        prompt = "구현 검증" if command == "/review" else "재검증"
        reply = paste_to_pane(cfg, "codex", prompt, "Codex")
        if state.cycle is not None and paste_delivered(reply):
            stamp_manual_action(cfg, f"cycle-{state.cycle}:codex:{prompt}", "codex_review", state.latest_review)
        return reply
    if command == "/fix":
        review = state.latest_review or "latest review"
        prompt_parts = [
            f"{review}의 Findings대로 수정하고 RESOLVED를 sentinel 아래에 append하라. plan scope를 넘기지 마라."
        ]
        if state.cycle is not None:
            pass_no = expected_done_pass(state) or ((review_number(state.latest_review) or 0) + 1)
            prompt_parts.append(executor_done_instruction(state.cycle, pass_no, "fix", state.latest_review))
        prompt = "\n\n".join(prompt_parts)
        reply = paste_to_pane(cfg, "claude", prompt, "Claude")
        if state.cycle is not None and state.latest_review and paste_delivered(reply):
            stamp_manual_action(cfg, f"cycle-{state.cycle}:fix:{state.latest_review}", "claude_fix")
        return reply
    if command == "/merge":
        if state.phase != "ready_to_merge":
            return f"Refused: phase is {state.phase}, not ready_to_merge"
        reply = paste_to_pane(cfg, "codex", "머지하라", "Codex")
        if state.cycle is not None and paste_delivered(reply):
            stamp_manual_action(cfg, f"cycle-{state.cycle}:merge:{state.latest_review or '-'}", "codex_merge")
        return reply
    if command == "/flow":
        action = parts[1].lower() if len(parts) >= 2 else "status"
        if action in {"status", "state"}:
            return flow_status_text(cfg, state)
        if action in {"off", "stop"}:
            return set_flow_mode(cfg, "off")
        if action in {"on", "safe"}:
            return set_flow_mode(cfg, "safe")
        if action == "full":
            return set_flow_mode(cfg, "full")
        if action == "step":
            reply = maybe_advance_flow(cfg, state, force=True)
            return reply or "Flow step: no available transition"
        if action == "reset":
            return reset_flow_state(cfg)
        return "Usage: /flow safe|full|off|status|step|reset"
    if command == "/hold":
        cfg.log_dir.mkdir(parents=True, exist_ok=True)
        hold_file(cfg).write_text(utc_now() + "\n", encoding="utf-8")
        return "Hermes held. Automation commands paused."
    if command == "/resume":
        path = hold_file(cfg)
        if path.exists():
            path.unlink()
        return "Hermes resumed."
    if command == "/approve-ui":
        if len(parts) < 3:
            return "Usage: /approve-ui <cycle> <evidence>"
        rest = parts[1] + " " + parts[2]
        match = re.match(r"(\d+)\s+(.+)", rest, re.S)
        if not match:
            return "Usage: /approve-ui <cycle> <evidence>"
        saved = append_manual_check(cfg, int(match.group(1)), match.group(2))
        return f"Saved manual evidence: {saved}"
    return "Unknown command. Use /help"


def answer_callback(cfg: Config, callback_id: str, text: str = "") -> None:
    if cfg.dry_run or not cfg.token:
        return
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text[:180]
    telegram_api(cfg, "answerCallbackQuery", payload, timeout=10)


def process_callback(cfg: Config, callback: dict[str, Any], state: CycleState) -> None:
    data = str(callback.get("data", "")).strip()
    callback_id = str(callback.get("id", ""))
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id", ""))
    if not data:
        return
    if cfg.chat_id and chat_id != cfg.chat_id:
        log_event(cfg, "telegram_ignored_callback_chat", {"chat_id": chat_id})
        return
    title = command_title(data)
    if callback_id:
        answer_callback(cfg, callback_id, title)
    send_telegram(cfg, f"{title}...")
    reply = handle_command(cfg, data, state)
    log_event(cfg, "telegram_callback", {"data": data, "reply": reply[:500]})
    if reply:
        send_telegram(cfg, reply)


def process_message(cfg: Config, message: dict[str, Any], state: CycleState) -> None:
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id", ""))
    text = str(message.get("text", "")).strip()
    if not text:
        return
    if cfg.chat_id and chat_id != cfg.chat_id:
        log_event(cfg, "telegram_ignored_chat", {"chat_id": chat_id})
        return
    reply = handle_command(cfg, text, state)
    log_event(cfg, "telegram_command", {"text": text, "reply": reply[:500]})
    if reply:
        send_telegram(cfg, reply)


def process_updates(cfg: Config, state: CycleState, once: bool) -> None:
    for update in get_updates(cfg, once=once):
        callback = update.get("callback_query")
        if callback:
            process_callback(cfg, callback, state)
            continue
        message = update.get("message") or update.get("edited_message") or {}
        process_message(cfg, message, state)


def notify_if_changed(cfg: Config, previous: dict[str, Any] | None, state: CycleState) -> None:
    if previous is None:
        return
    if previous.get("phase") == state.phase and previous.get("latest_review") == state.latest_review:
        return
    msg = tagged(cfg, f"Hermes cycle state changed\n\n{format_status(state)}")
    log_event(
        cfg,
        "state_changed",
        {
            "previous_phase": previous.get("phase"),
            "phase": state.phase,
            "cycle": state.cycle,
            "status": state.status,
            "verdict": state.verdict,
            "latest_review": state.latest_review,
            "pass": review_number(state.latest_review),
        },
    )
    send_telegram(cfg, msg)


def iter_done_files(cycle_dir: Path, root: Path):
    """Yield (path, rel_path, pass_no) for each executor done file in a cycle dir."""
    seen: set[str] = set()
    search_dirs = [cycle_dir / "executor", cycle_dir]
    for base in search_dirs:
        if not base.exists():
            continue
        for path in sorted(base.glob("pass-*-done.json")):
            match = EXECUTOR_DONE_RE.search(path.name)
            if not match:
                continue
            rel = str(path.relative_to(root))
            if rel in seen:
                continue
            seen.add(rel)
            yield path, rel, int(match.group(1))


def record_metric_events(cfg: Config, state: CycleState) -> None:
    """Emit cycle-context metric events (cycle_started, pass_done, verdict) once each.

    Deduplicated via flow state's ``last_metric_keys``. Historical cycles are
    reconstructed by dashboard/metrics.py directly from artifacts; these live
    events give it precise timestamps going forward.
    """
    if state.cycle is None:
        return
    flow = load_flow_state(cfg)
    keys = flow.get("last_metric_keys")
    if not isinstance(keys, dict):
        keys = {}
    now = utc_now()
    changed = False

    started_key = f"cycle_started:{state.cycle}"
    if started_key not in keys:
        log_event(cfg, "cycle_started", {"cycle": state.cycle})
        keys[started_key] = now
        changed = True

    cycle_dir = cfg.root / ".review" / f"cycle-{state.cycle}"
    for path, rel, pass_no in iter_done_files(cycle_dir, cfg.root):
        done_key = f"pass_done:{rel}"
        if done_key in keys:
            continue
        info: dict[str, Any] = {}
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            info = {}
        kind = info.get("kind") or ("implement" if pass_no <= 1 else "fix")
        log_event(
            cfg,
            "pass_done",
            {
                "cycle": state.cycle,
                "pass": pass_no,
                "kind": kind,
                "done_path": rel,
                "created_at": info.get("createdAt"),
            },
        )
        keys[done_key] = now
        changed = True

    if state.verdict and state.latest_review:
        verdict_key = f"verdict:{state.latest_review}:{state.verdict}"
        if verdict_key not in keys:
            log_event(
                cfg,
                "verdict",
                {"cycle": state.cycle, "review": state.latest_review, "verdict": state.verdict},
            )
            keys[verdict_key] = now
            changed = True

    if changed:
        flow["last_metric_keys"] = keys
        save_flow_state(cfg, flow)


def project_tick(cfg: Config) -> CycleState:
    """Scan + notify + metrics for one project. No Telegram polling: in
    supervisor mode a single consumer drains getUpdates for all projects."""
    previous = load_previous_state(cfg)
    state = scan_state(cfg)
    save_state(cfg, state)
    notify_if_changed(cfg, previous, state)
    record_metric_events(cfg, state)
    return state


def tick(cfg: Config, once: bool) -> CycleState:
    state = project_tick(cfg)
    process_updates(cfg, state, once=once)
    maybe_advance_flow(cfg, state, force=False)
    return state


# --- supervisor ------------------------------------------------------------

LOOP_ERRORS = (OSError, RuntimeError, ValueError, subprocess.SubprocessError, error.URLError, TimeoutError)


def project_list_text(entries: list[ProjectEntry], current_id: str | None) -> str:
    lines = ["Projects:"]
    for entry in entries:
        marker = "→" if entry.id == current_id else " "
        suffix = " (archived)" if entry.archived else ""
        lines.append(f"{marker} {entry.id}{suffix}")
    lines.append("")
    lines.append("Switch with: /project <id>")
    return "\n".join(lines)


def handle_project_command(entries: list[ProjectEntry], current_id: str | None, text: str) -> tuple[str, str | None]:
    parts = text.strip().split()
    if len(parts) < 2:
        return project_list_text(entries, current_id), current_id
    target = parts[1].strip().lower()
    match = next((e for e in entries if e.id.lower() == target), None)
    if match is None:
        return f"Unknown project: {parts[1]}\n\n{project_list_text(entries, current_id)}", current_id
    if match.archived:
        return f"Refused: {match.id} is archived. Unarchive it from the dashboard first.", current_id
    data = load_supervisor_state()
    data["currentProject"] = match.id
    save_supervisor_state(data)
    return f"Current project → {match.id}", match.id


def update_text(update: dict[str, Any]) -> str:
    callback = update.get("callback_query")
    if callback:
        return str(callback.get("data") or "").strip()
    message = update.get("message") or update.get("edited_message") or {}
    return str(message.get("text", "")).strip()


def supervisor_process_updates(
    entries: list[ProjectEntry],
    active: list[ProjectEntry],
    current_id: str | None,
    states: dict[str, CycleState],
    once: bool,
) -> str | None:
    """Drain Telegram once and route each update to the current project.

    /project is handled here rather than in handle_command because switching is
    a supervisor concern: handle_command only ever sees one project's Config."""
    telegram_cfg = next((e.cfg for e in active if e.id == current_id), None)
    if telegram_cfg is None:
        telegram_cfg = active[0].cfg if active else entries[0].cfg
    for update in get_updates(telegram_cfg, once=once):
        text = update_text(update)
        callback = update.get("callback_query")
        if text.split(maxsplit=1)[:1] == ["/project"]:
            reply, current_id = handle_project_command(entries, current_id, text)
            if callback:
                answer_callback(telegram_cfg, str(callback.get("id")))
            send_telegram(telegram_cfg, reply)
            continue
        current = next((e for e in active if e.id == current_id), None)
        if current is None:
            send_telegram(telegram_cfg, "No active project. Unarchive one from the dashboard.")
            continue
        state = states.get(current.id)
        if state is None:
            state = scan_state(current.cfg)
        if callback:
            process_callback(current.cfg, callback, state)
        else:
            process_message(current.cfg, update.get("message") or update.get("edited_message") or {}, state)
    return current_id


def reconcile_archived(entry: ProjectEntry) -> list[str]:
    """An archived project owns no tmux sessions.

    Enforced every tick rather than only at the moment the dashboard archives,
    so the invariant also holds for projects archived before this wiring existed
    and for sessions revived by hand. stop() kills the session but leaves the
    agent's conversation on disk, so unarchiving resumes where it left off.
    Keyed on session_exists, not alive: a pane whose CLI already exited still
    holds a session worth reclaiming. Headless projects own none.
    """
    runner = get_runner(entry.cfg)
    stopped: list[str] = []
    for agent in ("claude", "codex"):
        if not runner.session_exists(agent):
            continue
        result = runner.stop(agent)
        stopped.append(agent)
        log_event(entry.cfg, "archived_agent_stopped", {"agent": agent, "result": result})
    return stopped


def supervisor_loop(args: argparse.Namespace) -> int:
    global SUPERVISOR_MODE
    SUPERVISOR_MODE = True
    poll = int(os.environ.get("HERMES_POLL_SECONDS", args.poll_seconds))
    print(f"Hermes supervisor running. registry={PROJECTS_PATH} poll={poll}s dry_run={args.dry_run}")
    while True:
        entries = load_project_entries(args)
        active = [e for e in entries if not e.archived]
        supervisor = load_supervisor_state()
        current_id = supervisor.get("currentProject")
        if current_id not in {e.id for e in active}:
            current_id = active[0].id if active else None
            supervisor["currentProject"] = current_id
            save_supervisor_state(supervisor)

        for entry in entries:
            if not entry.archived:
                continue
            try:
                stopped = reconcile_archived(entry)
            except LOOP_ERRORS as err:
                log_event(entry.cfg, "loop_error", {"stage": "reconcile", "error": str(err)})
                continue
            if stopped:
                send_telegram(entry.cfg, tagged(entry.cfg, f"Archived: stopped {', '.join(stopped)} session(s)."))

        states: dict[str, CycleState] = {}
        for entry in active:
            try:
                entry.cfg.log_dir.mkdir(parents=True, exist_ok=True)
                states[entry.id] = project_tick(entry.cfg)
            except LOOP_ERRORS as err:
                log_event(entry.cfg, "loop_error", {"stage": "scan", "error": str(err)})

        if entries:
            try:
                current_id = supervisor_process_updates(entries, active, current_id, states, once=args.once)
            except LOOP_ERRORS as err:
                print(f"supervisor telegram error: {err}", file=sys.stderr)

        for entry in active:
            state = states.get(entry.id)
            if state is None:
                continue
            try:
                maybe_advance_flow(entry.cfg, state, force=False)
            except LOOP_ERRORS as err:
                log_event(entry.cfg, "loop_error", {"stage": "flow", "error": str(err)})

        if args.once:
            for entry in active:
                state = states.get(entry.id)
                print(f"--- {entry.id} ---")
                print(format_status(state) if state else "(scan failed)")
            return 0
        time.sleep(poll)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Hermes cycle bridge for Telegram + tmux.")
    parser.add_argument("--once", action="store_true", help="scan/process once and exit")
    parser.add_argument("--status", action="store_true", help="print current cycle state and exit")
    parser.add_argument("--tail", choices=["claude", "codex"], help="print tmux pane tail and exit")
    parser.add_argument("--send", choices=["claude", "codex"], help="send one message to a pane and exit")
    parser.add_argument("--command", help="handle one Hermes command locally and exit")
    parser.add_argument("--set-commands", action="store_true", help="register Telegram slash command suggestions")
    parser.add_argument("--send-menu", action="store_true", help="send the inline button menu to Telegram")
    parser.add_argument("message", nargs="*", help="message used with --send")
    parser.add_argument("--dry-run", action="store_true", help="do not send Telegram or tmux actions")
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument(
        "--supervisor",
        action="store_true",
        help="drive every non-archived project in projects.json from one process",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    cfg = config_from_env(args)
    cfg.log_dir.mkdir(parents=True, exist_ok=True)

    if args.supervisor:
        return supervisor_loop(args)

    if args.status:
        state = scan_state(cfg)
        save_state(cfg, state)
        print(format_status(state))
        return 0

    if args.tail:
        print(capture_pane(cfg, pane_for(cfg, args.tail)))
        return 0

    if args.send:
        text = " ".join(args.message).strip()
        if not text:
            parser.error("--send requires message")
        print(paste_to_pane(cfg, pane_for(cfg, args.send), text))
        return 0

    if args.command:
        state = scan_state(cfg)
        save_state(cfg, state)
        reply = handle_command(cfg, args.command, state)
        if reply:
            print(reply)
        return 0

    if args.set_commands:
        set_bot_commands(cfg)
        print("Telegram bot commands registered")
        return 0

    if args.send_menu:
        state = scan_state(cfg)
        save_state(cfg, state)
        send_menu(cfg, state)
        return 0

    if args.once:
        state = tick(cfg, once=True)
        print(format_status(state))
        return 0

    print(f"Hermes cycle bot running. root={cfg.root} poll={cfg.poll_seconds}s dry_run={cfg.dry_run}")
    while True:
        try:
            tick(cfg, once=False)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, error.URLError, TimeoutError) as err:
            log_event(cfg, "loop_error", {"error": str(err)})
            if cfg.dry_run:
                print(f"loop error: {err}", file=sys.stderr)
        time.sleep(cfg.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
