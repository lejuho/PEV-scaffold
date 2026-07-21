from __future__ import annotations

import fcntl
import os
import pty
import re
import shutil
import struct
import subprocess
import termios
import threading
from datetime import datetime, timezone
from typing import Any

AUTH_URL_RE = re.compile(r"https://claude\.com/cai/oauth/authorize\?[^\s\x1b]+")
ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class ClaudeAuthSession:
    """Own one interactive `claude auth login` process for the dashboard."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._master_fd: int | None = None
        self._generation = 0
        self._state = "idle"
        self._url: str | None = None
        self._output = ""
        self._error: str | None = None
        self._started_at: str | None = None
        self._finished_at: str | None = None

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return self._status_unlocked()

            binary = os.environ.get("PEV_CLAUDE_BIN") or shutil.which("claude")
            if not binary and os.path.isfile("/home/pi/.local/bin/claude"):
                binary = "/home/pi/.local/bin/claude"
            if not binary:
                raise RuntimeError("Claude CLI not found")

            master_fd, slave_fd = pty.openpty()
            # Prevent the long OAuth URL from wrapping in the pseudo-terminal.
            fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 4096, 0, 0))
            env = {**os.environ, "NO_COLOR": "1", "TERM": "dumb"}
            try:
                process = subprocess.Popen(
                    [binary, "auth", "login"],
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    close_fds=True,
                    start_new_session=True,
                    env=env,
                )
            except Exception:
                os.close(master_fd)
                os.close(slave_fd)
                raise
            finally:
                try:
                    os.close(slave_fd)
                except OSError:
                    pass

            self._generation += 1
            generation = self._generation
            self._process = process
            self._master_fd = master_fd
            self._state = "running"
            self._url = None
            self._output = ""
            self._error = None
            self._started_at = utc_now()
            self._finished_at = None
            threading.Thread(
                target=self._read_output,
                args=(generation, process, master_fd),
                name="claude-auth-login",
                daemon=True,
            ).start()
            return self._status_unlocked()

    def submit_code(self, code: str) -> dict[str, Any]:
        value = code.strip()
        if not value or len(value) > 4096:
            raise ValueError("Invalid authorization code")
        with self._lock:
            if self._state != "running" or self._master_fd is None:
                raise RuntimeError("Claude login is not waiting for input")
            os.write(self._master_fd, value.encode("utf-8") + b"\n")
            return self._status_unlocked()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_unlocked()

    def _read_output(self, generation: int, process: subprocess.Popen[bytes], master_fd: int) -> None:
        while True:
            try:
                chunk = os.read(master_fd, 2048)
            except OSError:
                break
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            with self._lock:
                if generation != self._generation:
                    break
                self._output = (self._output + text)[-12000:]
                clean = ANSI_RE.sub("", self._output).replace("\r", "")
                match = AUTH_URL_RE.search(clean)
                if match:
                    self._url = match.group(0)

        return_code = process.wait()
        try:
            os.close(master_fd)
        except OSError:
            pass
        with self._lock:
            if generation != self._generation:
                return
            clean = ANSI_RE.sub("", self._output).replace("\r", "")
            if "Login successful" in clean:
                self._state = "success"
            else:
                self._state = "error"
                self._error = f"claude auth login exited with code {return_code}"
            self._finished_at = utc_now()
            self._master_fd = None

    def _status_unlocked(self) -> dict[str, Any]:
        clean = ANSI_RE.sub("", self._output).replace("\r", "")
        return {
            "state": self._state,
            "url": self._url,
            "needsCode": self._state == "running" and "Paste code here if prompted" in clean,
            "message": self._message(clean),
            "error": self._error,
            "startedAt": self._started_at,
            "finishedAt": self._finished_at,
        }

    def _message(self, clean: str) -> str:
        if self._state == "success":
            return "Login successful."
        if self._state == "error":
            return self._error or "Claude login failed."
        if self._url:
            return "Complete sign-in in the opened browser tab."
        if self._state == "running":
            return "Starting Claude login…"
        return ""


claude_auth = ClaudeAuthSession()
