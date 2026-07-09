#!/usr/bin/env python3
"""PEV agent runner: one interface, two drivers.

- tmux driver: the original behavior. Agents live in tmux panes; send =
  paste-buffer + Enter, tail = capture-pane, idle = prompt heuristics.
- headless driver: no tmux. Each turn is one `claude -p --resume <id>` or
  `codex exec resume <id>` invocation spawned in the background. Session IDs
  are stored per project in logs/pev-sessions.json so a project can be
  stopped and resumed later (across reboots) with full conversation history.

Used as a library by hermes-cycle-bot.py and dashboard/server.py, and as a
CLI for manual operation:

    pev_runner.py --root /path/to/project status
    pev_runner.py --root /path/to/project send claude "prompt..."
    pev_runner.py --root /path/to/project tail claude
    pev_runner.py --root /path/to/project stop claude
    pev_runner.py --root /path/to/project harvest        # adopt existing sessions
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shlex
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AGENTS = ("claude", "codex")
SESSIONS_FILE = "pev-sessions.json"
TURN_DIR = "pev-turns"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def extra_bin_dirs() -> list[str]:
    """Common user-install bin dirs to search when a bare tool name isn't on
    PATH. Override with PEV_EXTRA_PATH (colon-separated)."""
    env = os.environ.get("PEV_EXTRA_PATH")
    if env:
        return [d for d in env.split(os.pathsep) if d]
    home = Path.home()
    return [
        str(home / ".local" / "bin"),
        str(home / ".npm-global" / "bin"),
        "/mnt/data/pi_storage/.npm-global/bin",
        "/usr/local/bin",
    ]


def resolve_bin(name: str) -> str:
    """Resolve a CLI binary robustly: an absolute path is trusted as-is;
    otherwise try PATH, then the extra user-install dirs. Falls back to the
    bare name so the original 'not found' error still surfaces."""
    import shutil as _shutil
    if os.path.isabs(name):
        return name
    found = _shutil.which(name)
    if found:
        return found
    for directory in extra_bin_dirs():
        candidate = Path(directory) / name
        if candidate.exists():
            return str(candidate)
    return name


# ---------------------------------------------------------------------------
# Config


@dataclass
class RunnerConfig:
    root: Path
    driver: str = "tmux"  # "tmux" | "headless"
    log_dir: Path | None = None
    # tmux driver
    claude_pane: str = ""
    codex_pane: str = ""
    claude_session: str = ""
    codex_session: str = ""
    submit_key: str = "C-m"
    submit_delay: float = 0.35
    # binaries / args
    claude_bin: str = "claude"
    codex_bin: str = "codex"
    claude_args: str = "--continue --dangerously-skip-permissions"
    codex_args: str = "--no-alt-screen --dangerously-bypass-approvals-and-sandbox"
    # headless driver
    claude_model: str = ""
    codex_model: str = ""
    claude_headless_args: str = "--dangerously-skip-permissions"
    codex_headless_args: str = "--dangerously-bypass-approvals-and-sandbox --skip-git-repo-check"
    dry_run: bool = False

    def resolved_log_dir(self) -> Path:
        return self.log_dir if self.log_dir else self.root / "logs"

    @classmethod
    def from_env(cls, root: Path | None = None, *, dry_run: bool = False) -> "RunnerConfig":
        env = os.environ
        resolved_root = Path(env.get("HERMES_ROOT", str(root or Path.cwd()))).resolve()
        log_dir = Path(env.get("HERMES_LOG_DIR", str(resolved_root / "logs"))).resolve()
        return cls(
            root=resolved_root,
            driver=env.get("PEV_DRIVER", "tmux").strip() or "tmux",
            log_dir=log_dir,
            claude_pane=env.get("HERMES_CLAUDE_PANE", ""),
            codex_pane=env.get("HERMES_CODEX_PANE", ""),
            claude_session=env.get("PEV_CLAUDE_SESSION", ""),
            codex_session=env.get("PEV_CODEX_SESSION", ""),
            submit_key=env.get("HERMES_SUBMIT_KEY", "C-m"),
            submit_delay=float(env.get("HERMES_SUBMIT_DELAY", "0.35")),
            claude_bin=env.get("PEV_CLAUDE_BIN", "claude"),
            codex_bin=env.get("PEV_CODEX_BIN", "codex"),
            claude_args=env.get("PEV_CLAUDE_ARGS", cls.claude_args),
            codex_args=env.get("PEV_CODEX_ARGS", cls.codex_args),
            claude_model=env.get("PEV_CLAUDE_MODEL", ""),
            codex_model=env.get("PEV_CODEX_MODEL", ""),
            claude_headless_args=env.get("PEV_CLAUDE_HEADLESS_ARGS", cls.claude_headless_args),
            codex_headless_args=env.get("PEV_CODEX_HEADLESS_ARGS", cls.codex_headless_args),
            dry_run=dry_run,
        )

    @classmethod
    def from_project(cls, item: dict[str, Any]) -> "RunnerConfig":
        """Build from a dashboard projects.json entry. Unknown keys ignored."""
        root = Path(item["root"]).expanduser().resolve()
        cfg = cls(root=root)
        cfg.driver = str(item.get("driver") or "tmux")
        cfg.claude_pane = str(item.get("claudePane") or "")
        cfg.codex_pane = str(item.get("codexPane") or "")
        cfg.claude_session = str(item.get("claudeSession") or "")
        cfg.codex_session = str(item.get("codexSession") or "")
        for attr, key in (
            ("claude_bin", "claudeBin"),
            ("codex_bin", "codexBin"),
            ("claude_model", "claudeModel"),
            ("codex_model", "codexModel"),
            ("claude_headless_args", "claudeHeadlessArgs"),
            ("codex_headless_args", "codexHeadlessArgs"),
            ("claude_args", "claudeArgs"),
            ("codex_args", "codexArgs"),
        ):
            if item.get(key):
                setattr(cfg, attr, str(item[key]))
        # fall back to the live environment for binary paths if not given
        if cfg.claude_bin == "claude":
            cfg.claude_bin = os.environ.get("PEV_CLAUDE_BIN", cfg.claude_bin)
        if cfg.codex_bin == "codex":
            cfg.codex_bin = os.environ.get("PEV_CODEX_BIN", cfg.codex_bin)
        return cfg


# ---------------------------------------------------------------------------
# Session store (logs/pev-sessions.json)


class SessionStore:
    def __init__(self, cfg: RunnerConfig):
        self.path = cfg.resolved_log_dir() / SESSIONS_FILE
        self.lock_path = self.path.with_suffix(".lock")

    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.lock_path, "w", encoding="utf-8")
        fcntl.flock(fh, fcntl.LOCK_EX)
        return fh

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def update(self, agent: str, **fields: Any) -> dict[str, Any]:
        fh = self._locked()
        try:
            data = self.load()
            entry = data.get(agent)
            if not isinstance(entry, dict):
                entry = {}
            entry.update(fields)
            entry["updatedAt"] = utc_now()
            data[agent] = entry
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, self.path)
            return entry
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
            fh.close()

    def get(self, agent: str) -> dict[str, Any]:
        entry = self.load().get(agent)
        return entry if isinstance(entry, dict) else {}


# ---------------------------------------------------------------------------
# Session harvesting (adopt sessions created outside the runner, e.g. tmux)


def claude_project_dir(root: Path) -> Path:
    slug = str(root).replace("/", "-")
    return Path.home() / ".claude" / "projects" / slug


def harvest_claude_session(root: Path) -> str | None:
    """Most recent Claude Code session ID for this project directory."""
    project_dir = claude_project_dir(root)
    if not project_dir.is_dir():
        return None
    best: tuple[float, str] | None = None
    for path in project_dir.glob("*.jsonl"):
        try:
            uuid.UUID(path.stem)
        except ValueError:
            continue
        mtime = path.stat().st_mtime
        if best is None or mtime > best[0]:
            best = (mtime, path.stem)
    return best[1] if best else None


def harvest_codex_session(root: Path, scan_limit: int = 200) -> str | None:
    """Most recent Codex session whose recorded cwd matches this project."""
    sessions_dir = Path.home() / ".codex" / "sessions"
    if not sessions_dir.is_dir():
        return None
    rollouts = sorted(
        sessions_dir.glob("*/*/*/rollout-*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in rollouts[:scan_limit]:
        try:
            with path.open(encoding="utf-8") as fh:
                first = json.loads(fh.readline())
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if first.get("type") != "session_meta":
            continue
        payload = first.get("payload") or {}
        if str(payload.get("cwd") or "") == str(root):
            sid = payload.get("session_id") or payload.get("id")
            if sid:
                return str(sid)
    return None


# ---------------------------------------------------------------------------
# Drivers


class TmuxDriver:
    """Original behavior: agents are interactive CLIs inside tmux panes."""

    def __init__(self, cfg: RunnerConfig):
        self.cfg = cfg

    # -- helpers
    def _pane(self, agent: str) -> str:
        return self.cfg.claude_pane if agent == "claude" else self.cfg.codex_pane

    def _session_name(self, agent: str) -> str:
        explicit = self.cfg.claude_session if agent == "claude" else self.cfg.codex_session
        if explicit:
            return explicit
        pane = self._pane(agent)
        return pane.split(":", 1)[0] if pane else ""

    def _run(self, args: list[str], check: bool = False, timeout: int = 10) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, cwd=self.cfg.root, capture_output=True, text=True, timeout=timeout, check=check)

    # -- interface
    def _ensure_alive(self, agent: str) -> bool:
        """True if the tmux session was already alive. If it was gone (reboot,
        killed), (re)create it and return False so the caller skips writing into
        a still-booting CLI — the operator/flow resends once it's ready."""
        session = self._session_name(agent)
        if not session:
            return True  # not configured — let the normal path report it
        if self._run(["tmux", "has-session", "-t", session]).returncode == 0:
            return True
        self.start(agent)
        return False

    def send(self, agent: str, text: str) -> str:
        pane = self._pane(agent)
        if not pane:
            return f"{agent}: tmux pane not configured"
        if self.cfg.dry_run:
            return f"[dry-run] would paste to {pane}: {text}"
        if not self._ensure_alive(agent):
            return f"{agent}: tmux session (re)created — CLI is booting, resend in a few seconds"
        self._run(["tmux", "set-buffer", "--", text], check=True)
        self._run(["tmux", "paste-buffer", "-t", pane], check=True)
        return self.press_enter(agent)

    def press_enter(self, agent: str, delay: bool = True) -> str:
        pane = self._pane(agent)
        if not pane:
            return f"{agent}: tmux pane not configured"
        if self.cfg.dry_run:
            return f"[dry-run] would press {self.cfg.submit_key} in {pane}"
        if not self._ensure_alive(agent):
            return f"{agent}: tmux session (re)created — CLI is booting, resend in a few seconds"
        if delay and self.cfg.submit_delay > 0:
            time.sleep(self.cfg.submit_delay)
        self._run(["tmux", "send-keys", "-t", pane, self.cfg.submit_key], check=True)
        return f"{agent}: submitted ({self.cfg.submit_key})"

    def tail(self, agent: str, lines: int = 80) -> str:
        pane = self._pane(agent)
        if not pane:
            return "tmux pane not configured"
        try:
            result = self._run(["tmux", "capture-pane", "-p", "-t", pane, "-S", f"-{lines}"], timeout=5)
        except (OSError, subprocess.SubprocessError) as exc:
            return f"tmux capture failed for {pane}: {exc}"
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
            return f"tmux capture failed for {pane}: {detail}"
        return result.stdout or "(empty pane)"

    def idle(self, agent: str) -> bool | None:
        text = self.tail(agent, 40)
        if not text or text.startswith("tmux capture failed") or text == "tmux pane not configured":
            return None
        tail = text[-2500:]
        if agent == "codex":
            working = ["Running", "Working", "thinking", "Thinking", "exec_command", "apply_patch", "Waiting for"]
            if any(marker in tail for marker in working):
                return False
            return bool(re.search(r"(?m)^›\s", tail))
        prompt_idx = tail.rfind("❯")
        current = tail[prompt_idx:] if prompt_idx >= 0 else tail[-800:]
        working = ["Perusing", "Running", "Working", "Waiting", "Esc to interrupt", "Bash("]
        if any(marker in current for marker in working):
            return False
        idle_markers = ["accept edits on", "❯", "? for shortcuts"]
        return any(marker in current for marker in idle_markers)

    def start(self, agent: str) -> str:
        session = self._session_name(agent)
        if not session:
            return f"{agent}: no tmux session configured"
        if self._run(["tmux", "has-session", "-t", session]).returncode == 0:
            return f"{agent}: tmux session {session} already running"
        if agent == "claude":
            command = f"{self.cfg.claude_bin} {self.cfg.claude_args}"
        else:
            command = f"{self.cfg.codex_bin} {self.cfg.codex_args}"
        if self.cfg.dry_run:
            return f"[dry-run] would create tmux session {session}: {command}"
        self._run(
            ["tmux", "new-session", "-d", "-s", session, "-c", str(self.cfg.root),
             f"bash -lc {shlex.quote(command + '; exec bash -l')}"],
            check=True,
        )
        return f"{agent}: tmux session {session} started"

    def stop(self, agent: str) -> str:
        session = self._session_name(agent)
        if not session:
            return f"{agent}: no tmux session configured"
        if self.cfg.dry_run:
            return f"[dry-run] would kill tmux session {session}"
        result = self._run(["tmux", "kill-session", "-t", session])
        if result.returncode != 0:
            return f"{agent}: kill-session failed: {(result.stderr or '').strip()}"
        return f"{agent}: tmux session {session} stopped (conversation kept on disk)"

    def status(self, agent: str) -> dict[str, Any]:
        pane = self._pane(agent)
        session = self._session_name(agent)
        alive = bool(session) and self._run(["tmux", "has-session", "-t", session]).returncode == 0
        return {"driver": "tmux", "pane": pane, "session": session, "alive": alive, "idle": self.idle(agent)}


class HeadlessDriver:
    """No tmux. Each send() is one background CLI invocation resuming a
    stored session ID. State lives in logs/pev-sessions.json; per-turn
    output in logs/pev-turns/<agent>-turn-NNN.jsonl."""

    def __init__(self, cfg: RunnerConfig):
        self.cfg = cfg
        self.store = SessionStore(cfg)

    # -- helpers
    def _turn_dir(self) -> Path:
        path = self.cfg.resolved_log_dir() / TURN_DIR
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _pid_alive(self, entry: dict[str, Any]) -> bool:
        pid = entry.get("pid")
        if not isinstance(pid, int):
            return False
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return False
        return True

    def _refresh(self, agent: str) -> dict[str, Any]:
        """Reconcile stored state with reality (finalize finished turns)."""
        entry = self.store.get(agent)
        if entry.get("status") == "running" and not self._pid_alive(entry):
            fields: dict[str, Any] = {"status": "idle", "pid": None, "lastTurnEndedAt": utc_now()}
            if agent == "codex" and not entry.get("sessionId"):
                sid = self._session_id_from_log(entry.get("log")) or harvest_codex_session(self.cfg.root)
                if sid:
                    fields["sessionId"] = sid
            entry = self.store.update(agent, **fields)
        return entry

    def _session_id_from_log(self, rel_log: str | None) -> str | None:
        if not rel_log:
            return None
        path = self.cfg.root / rel_log
        if not path.exists():
            return None
        try:
            with path.open(encoding="utf-8") as fh:
                for raw in fh:
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    for key in ("session_id", "sessionId", "thread_id", "conversation_id"):
                        value = _deep_find(event, key)
                        if value:
                            return str(value)
        except OSError:
            return None
        return None

    def _build_command(self, agent: str, text: str, entry: dict[str, Any]) -> tuple[list[str], str | None]:
        """Return (argv, presetSessionId). presetSessionId is only set when we
        assign the ID ourselves (claude first turn)."""
        if agent == "claude":
            args = [resolve_bin(self.cfg.claude_bin), "-p", text, "--output-format", "stream-json", "--verbose"]
            args += shlex.split(self.cfg.claude_headless_args)
            if self.cfg.claude_model:
                args += ["--model", self.cfg.claude_model]
            sid = entry.get("sessionId")
            if sid:
                args += ["--resume", str(sid)]
                return args, None
            new_sid = str(uuid.uuid4())
            args += ["--session-id", new_sid]
            return args, new_sid
        # codex
        base = [resolve_bin(self.cfg.codex_bin), "exec"]
        sid = entry.get("sessionId")
        if sid:
            base += ["resume", str(sid)]
        base += ["--json"]
        base += shlex.split(self.cfg.codex_headless_args)
        if self.cfg.codex_model:
            base += ["-m", self.cfg.codex_model]
        base += [text]
        return base, None

    # -- interface
    def send(self, agent: str, text: str) -> str:
        entry = self._refresh(agent)
        if entry.get("status") == "running":
            return f"{agent}: a turn is still running (pid {entry.get('pid')}); wait or stop first"
        turn = int(entry.get("turn") or 0) + 1
        log_path = self._turn_dir() / f"{agent}-turn-{turn:03d}.jsonl"
        try:
            rel_log = str(log_path.relative_to(self.cfg.root))
        except ValueError:
            rel_log = str(log_path)
        argv, preset_sid = self._build_command(agent, text, entry)
        if self.cfg.dry_run:
            return f"[dry-run] would run: {' '.join(shlex.quote(a) for a in argv[:8])}..."
        env = dict(os.environ)
        env.setdefault("TERM", "xterm-256color")
        # Augment PATH so the CLI (and the node/child processes it spawns)
        # resolve even when launched from a non-login-shell service.
        env["PATH"] = os.pathsep.join([*extra_bin_dirs(), env.get("PATH", "")])
        with open(log_path, "w", encoding="utf-8") as log_fh:
            proc = subprocess.Popen(
                argv,
                cwd=self.cfg.root,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )
        fields: dict[str, Any] = {
            "status": "running",
            "pid": proc.pid,
            "turn": turn,
            "log": rel_log,
            "lastPrompt": text[:400],
            "lastTurnAt": utc_now(),
            "driver": "headless",
        }
        if preset_sid:
            fields["sessionId"] = preset_sid
        self.store.update(agent, **fields)
        return f"{agent}: turn {turn} started (pid {proc.pid}, log {rel_log})"

    def press_enter(self, agent: str, delay: bool = True) -> str:
        return f"{agent}: headless driver has no input buffer (Enter not needed)"

    def tail(self, agent: str, lines: int = 80) -> str:
        entry = self._refresh(agent)
        rel_log = entry.get("log")
        if not rel_log:
            return (f"{agent}: no turns yet. This project uses the headless driver, so there is "
                    f"no tmux pane to capture — output streams here (live) once a turn starts, "
                    f"e.g. via /implement. Switch the project to driver=tmux if you want a pane.")
        path = self.cfg.root / rel_log
        if not path.exists():
            return f"{agent}: turn log missing: {rel_log}"
        rendered = render_turn_log(path, max_lines=lines)
        header = f"[{agent} headless · turn {entry.get('turn')} · {entry.get('status')}]"
        return header + "\n" + (rendered or "(no output yet)")

    def idle(self, agent: str) -> bool | None:
        # No entry yet means no turn has ever run — nothing is busy, so the
        # agent is ready. Returning None here would read as "busy" upstream and
        # stall the flow on a freshly created project.
        entry = self._refresh(agent)
        return entry.get("status") != "running"

    def start(self, agent: str) -> str:
        """Ensure a session entry exists; adopt the latest on-disk session if
        none is stored yet (migration from tmux/interactive use)."""
        entry = self.store.get(agent)
        if entry.get("sessionId"):
            return f"{agent}: session {entry['sessionId']} ready (turn {entry.get('turn') or 0})"
        sid = harvest_claude_session(self.cfg.root) if agent == "claude" else harvest_codex_session(self.cfg.root)
        if sid:
            self.store.update(agent, sessionId=sid, status="idle", driver="headless")
            return f"{agent}: adopted existing session {sid}"
        self.store.update(agent, status="idle", driver="headless")
        return f"{agent}: no prior session found; a new one will be created on first send"

    def stop(self, agent: str) -> str:
        entry = self._refresh(agent)
        pid = entry.get("pid")
        if entry.get("status") != "running" or not isinstance(pid, int):
            return f"{agent}: nothing running"
        if self.cfg.dry_run:
            return f"[dry-run] would SIGTERM pgid of {pid}"
        try:
            os.killpg(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                os.kill(pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
        self.store.update(agent, status="idle", pid=None, stoppedAt=utc_now())
        return f"{agent}: turn stopped (session {entry.get('sessionId')} kept; resume with next send)"

    def status(self, agent: str) -> dict[str, Any]:
        entry = self._refresh(agent)
        return {
            "driver": "headless",
            "sessionId": entry.get("sessionId"),
            "turn": entry.get("turn") or 0,
            "running": entry.get("status") == "running",
            "pid": entry.get("pid"),
            "log": entry.get("log"),
            "idle": entry.get("status") != "running" if entry else None,
            "lastTurnAt": entry.get("lastTurnAt"),
        }


def _deep_find(obj: Any, key: str, depth: int = 4) -> Any:
    if depth < 0:
        return None
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], (str, int)):
            return obj[key]
        for value in obj.values():
            found = _deep_find(value, key, depth - 1)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj[:20]:
            found = _deep_find(value, key, depth - 1)
            if found:
                return found
    return None


def render_turn_log(path: Path, max_lines: int = 80) -> str:
    """Render a stream-json / codex --json turn log into readable lines."""
    out: list[str] = []
    try:
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"(cannot read log: {exc})"
    for raw in raw_lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            out.append(raw[:300])
            continue
        out.extend(_render_event(event))
    return "\n".join(out[-max_lines:])


def _render_event(event: dict[str, Any]) -> list[str]:
    etype = str(event.get("type") or "")
    # claude stream-json
    if etype == "system" and event.get("subtype") == "init":
        return [f"— session {event.get('session_id')} (model {event.get('model')})"]
    if etype == "assistant":
        lines: list[str] = []
        message = event.get("message") or {}
        for block in message.get("content") or []:
            btype = block.get("type")
            if btype == "text" and block.get("text", "").strip():
                lines.extend(block["text"].strip().splitlines())
            elif btype == "tool_use":
                name = block.get("name", "?")
                desc = ""
                tool_input = block.get("input") or {}
                for key in ("command", "description", "file_path", "pattern", "prompt"):
                    if tool_input.get(key):
                        desc = str(tool_input[key])[:120]
                        break
                lines.append(f"  ⚒ {name} {desc}".rstrip())
        return lines
    if etype == "result":
        cost = event.get("total_cost_usd")
        dur = event.get("duration_ms")
        parts = ["— turn done"]
        if isinstance(dur, (int, float)):
            parts.append(f"{dur / 1000:.0f}s")
        if isinstance(cost, (int, float)):
            parts.append(f"${cost:.4f}")
        if event.get("is_error"):
            parts.append("ERROR")
        return [" ".join(parts)]
    # codex --json event shapes
    if etype in {"item.completed", "item.updated"}:
        item = event.get("item") or {}
        itype = item.get("item_type") or item.get("type") or ""
        if itype in {"assistant_message", "agent_message"}:
            text = str(item.get("text") or "").strip()
            return text.splitlines() if text else []
        if itype == "command_execution":
            return [f"  ⚒ exec {str(item.get('command') or '')[:120]}"]
        if itype in {"file_change", "patch_apply"}:
            return [f"  ⚒ patch {str(item.get('path') or '')[:120]}"]
        return []
    if etype == "thread.started":
        return [f"— codex thread {event.get('thread_id')}"]
    if etype == "turn.completed":
        usage = event.get("usage") or {}
        return [f"— turn done (in {usage.get('input_tokens', '?')} / out {usage.get('output_tokens', '?')} tokens)"]
    if etype == "error":
        return [f"ERROR: {str(event.get('message') or event)[:300]}"]
    return []


# ---------------------------------------------------------------------------
# Facade


class AgentRunner:
    def __init__(self, cfg: RunnerConfig):
        self.cfg = cfg
        self.driver = HeadlessDriver(cfg) if cfg.driver == "headless" else TmuxDriver(cfg)

    def send(self, agent: str, text: str) -> str:
        return self.driver.send(agent, text)

    def press_enter(self, agent: str, delay: bool = True) -> str:
        return self.driver.press_enter(agent, delay)

    def tail(self, agent: str, lines: int = 80) -> str:
        return self.driver.tail(agent, lines)

    def idle(self, agent: str) -> bool | None:
        return self.driver.idle(agent)

    def alive(self, agent: str) -> bool | None:
        """True/False for the tmux driver (session exists?). None for headless,
        where there is no long-lived session to be alive or dead."""
        return self.driver.status(agent).get("alive")

    def start(self, agent: str) -> str:
        return self.driver.start(agent)

    def stop(self, agent: str) -> str:
        return self.driver.stop(agent)

    def status(self, agent: str) -> dict[str, Any]:
        return self.driver.status(agent)

    def harvest(self) -> dict[str, str | None]:
        """Adopt latest on-disk sessions for both agents into the store."""
        store = SessionStore(self.cfg)
        result: dict[str, str | None] = {}
        for agent in AGENTS:
            sid = harvest_claude_session(self.cfg.root) if agent == "claude" else harvest_codex_session(self.cfg.root)
            if sid:
                store.update(agent, sessionId=sid)
            result[agent] = sid
        return result


# ---------------------------------------------------------------------------
# CLI


def main() -> int:
    parser = argparse.ArgumentParser(description="PEV agent session runner (tmux/headless)")
    parser.add_argument("--root", type=Path, default=None, help="project root (default: HERMES_ROOT or cwd)")
    parser.add_argument("--driver", choices=["tmux", "headless"], default=None, help="override PEV_DRIVER")
    parser.add_argument("--dry-run", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p = sub.add_parser("send")
    p.add_argument("agent", choices=AGENTS)
    p.add_argument("text")
    p = sub.add_parser("tail")
    p.add_argument("agent", choices=AGENTS)
    p.add_argument("-n", "--lines", type=int, default=80)
    p = sub.add_parser("idle")
    p.add_argument("agent", choices=AGENTS)
    p = sub.add_parser("start")
    p.add_argument("agent", choices=[*AGENTS, "all"])
    p = sub.add_parser("stop")
    p.add_argument("agent", choices=[*AGENTS, "all"])
    p = sub.add_parser("enter")
    p.add_argument("agent", choices=AGENTS)
    sub.add_parser("harvest")
    args = parser.parse_args()

    cfg = RunnerConfig.from_env(args.root, dry_run=args.dry_run)
    if args.root:
        cfg.root = args.root.resolve()
        if not os.environ.get("HERMES_LOG_DIR"):
            cfg.log_dir = cfg.root / "logs"
    if args.driver:
        cfg.driver = args.driver
    runner = AgentRunner(cfg)

    if args.cmd == "status":
        print(json.dumps({agent: runner.status(agent) for agent in AGENTS}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "harvest":
        print(json.dumps(runner.harvest(), ensure_ascii=False, indent=2))
        return 0
    if args.cmd in {"start", "stop"} and args.agent == "all":
        for agent in AGENTS:
            print(getattr(runner, args.cmd)(agent))
        return 0
    if args.cmd == "send":
        print(runner.send(args.agent, args.text))
    elif args.cmd == "tail":
        print(runner.tail(args.agent, args.lines))
    elif args.cmd == "idle":
        print(f"{args.agent}: idle={runner.idle(args.agent)}")
    elif args.cmd == "enter":
        print(runner.press_enter(args.agent))
    else:
        print(getattr(runner, args.cmd)(args.agent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
