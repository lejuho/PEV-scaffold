#!/usr/bin/env python3
"""Server-side subscription usage collectors for Claude Code and Codex.

Credentials never leave this module. The dashboard receives only normalized
percentages, reset timestamps, plan labels, and non-sensitive errors.
"""
from __future__ import annotations

import json
import os
import selectors
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

USAGE_CACHE_SECONDS = int(os.environ.get("PEV_USAGE_CACHE_SECONDS", "60"))
CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_cache: tuple[float, dict[str, Any]] | None = None
_cache_lock = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _window(label: str, raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    utilization = raw.get("utilization")
    if not isinstance(utilization, (int, float)):
        return None
    return {
        "label": label,
        "usedPercent": round(float(utilization), 2),
        "resetsAt": raw.get("resets_at"),
    }


def claude_usage(timeout: float = 8.0) -> dict[str, Any]:
    credentials = Path(os.environ.get("CLAUDE_CREDENTIALS", Path.home() / ".claude" / ".credentials.json"))
    try:
        auth = json.loads(credentials.read_text(encoding="utf-8")).get("claudeAiOauth") or {}
        token = auth.get("accessToken")
        if not token:
            raise ValueError("Claude OAuth token not found")
        refresh_expires_at = auth.get("refreshTokenExpiresAt")
        if isinstance(refresh_expires_at, (int, float)) and refresh_expires_at / 1000 <= time.time():
            return {
                "available": False,
                "reauthRequired": True,
                "error": "Claude login expired — run `claude auth login`",
                "windows": [],
            }
        req = Request(
            CLAUDE_USAGE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
                "Accept": "application/json",
                "User-Agent": "pev-dashboard/0.1",
            },
        )
        with urlopen(req, timeout=timeout) as response:
            raw = json.loads(response.read().decode("utf-8"))
        windows = [
            item for item in (
                _window("5h", raw.get("five_hour")),
                _window("7d", raw.get("seven_day")),
                _window("7d Sonnet", raw.get("seven_day_sonnet")),
                _window("7d Opus", raw.get("seven_day_opus")),
            ) if item
        ]
        extra = raw.get("extra_usage") or {}
        extra_usage = None
        if extra.get("is_enabled"):
            places = int(extra.get("decimal_places") or 2)
            scale = 10 ** places
            extra_usage = {
                "usedPercent": round(float(extra.get("utilization") or 0), 2),
                "used": float(extra.get("used_credits") or 0) / scale,
                "limit": float(extra.get("monthly_limit") or 0) / scale,
                "currency": extra.get("currency") or "USD",
            }
        return {
            "available": True,
            "plan": auth.get("subscriptionType"),
            "windows": windows,
            "extraUsage": extra_usage,
        }
    except HTTPError as err:
        if err.code == 401:
            return {
                "available": False,
                "reauthRequired": True,
                "error": "Claude login expired — run `claude auth login`",
                "windows": [],
            }
        return {"available": False, "error": f"HTTPError: HTTP {err.code}", "windows": []}
    except Exception as err:  # credentials/network failures are display state
        return {"available": False, "error": f"{type(err).__name__}: {str(err)[:180]}", "windows": []}


def _read_codex_response(proc: subprocess.Popen[str], request_id: int, timeout: float) -> dict[str, Any]:
    selector = selectors.DefaultSelector()
    assert proc.stdout is not None
    selector.register(proc.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events = selector.select(max(0.0, deadline - time.monotonic()))
        if not events:
            break
        line = proc.stdout.readline()
        if not line:
            break
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("id") == request_id:
            return message
    raise TimeoutError("Codex usage query timed out")


def _codex_window(label: str, raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("usedPercent"), (int, float)):
        return None
    resets = raw.get("resetsAt")
    resets_at = None
    if isinstance(resets, (int, float)):
        resets_at = datetime.fromtimestamp(resets, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {
        "label": label,
        "usedPercent": round(float(raw["usedPercent"]), 2),
        "resetsAt": resets_at,
        "windowMinutes": raw.get("windowDurationMins"),
    }


def codex_usage(timeout: float = 10.0) -> dict[str, Any]:
    candidates = (
        os.environ.get("PEV_CODEX_BIN"),
        shutil.which("codex"),
        "/mnt/data/pi_storage/.npm-global/bin/codex",
        str(Path.home() / ".npm-global" / "bin" / "codex"),
    )
    binary = next((item for item in candidates if item and Path(item).is_file()), None)
    if not binary:
        return {"available": False, "error": "Codex binary not found", "windows": []}
    proc: subprocess.Popen[str] | None = None
    try:
        proc = subprocess.Popen(
            [binary, "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        assert proc.stdin is not None
        init = {"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "pev-dashboard", "version": "0.1"}}}
        proc.stdin.write(json.dumps(init) + "\n")
        proc.stdin.flush()
        _read_codex_response(proc, 1, timeout / 2)
        proc.stdin.write(json.dumps({"id": 2, "method": "account/rateLimits/read"}) + "\n")
        proc.stdin.flush()
        message = _read_codex_response(proc, 2, timeout / 2)
        if message.get("error"):
            raise RuntimeError(str(message["error"])[:180])
        result = message.get("result") or {}
        snapshots = result.get("rateLimitsByLimitId") or {}
        if not snapshots and result.get("rateLimits"):
            snapshots = {"codex": result["rateLimits"]}
        limits = []
        for limit_id, snapshot in snapshots.items():
            if not isinstance(snapshot, dict):
                continue
            windows = [item for item in (
                _codex_window("primary", snapshot.get("primary")),
                _codex_window("secondary", snapshot.get("secondary")),
            ) if item]
            limits.append({
                "id": limit_id,
                "name": snapshot.get("limitName") or ("Codex" if limit_id == "codex" else limit_id),
                "plan": snapshot.get("planType"),
                "windows": windows,
            })
        return {"available": True, "limits": limits, "windows": limits[0]["windows"] if limits else []}
    except Exception as err:
        return {"available": False, "error": f"{type(err).__name__}: {str(err)[:180]}", "windows": []}
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()


def collect_usage(force: bool = False) -> dict[str, Any]:
    global _cache
    with _cache_lock:
        now = time.monotonic()
        if not force and _cache and now - _cache[0] < USAGE_CACHE_SECONDS:
            return _cache[1]
        result = {"generatedAt": utc_now(), "claude": claude_usage(), "codex": codex_usage()}
        _cache = (now, result)
        return result
