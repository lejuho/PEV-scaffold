#!/usr/bin/env python3
"""PEV metrics calculator.

Pure derivation module: given a project root (with .review/ artifacts and
logs/hermes-events.jsonl) plus the Claude Code and Codex transcript directories, it
reconstructs per-cycle autonomy time, cost, first-pass rate and error
clusters. Nothing here is a source of truth — deleting the cache and
recomputing must yield the same numbers.

Importable (compute_metrics) and runnable as a CLI:

    python3 dashboard/metrics.py --root /home/pi/cairn            # stdout
    python3 dashboard/metrics.py --root /home/pi/cairn --write    # -> logs/pev-metrics.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

APP_DIR = Path(__file__).resolve().parent
CYCLE_DIR_RE = re.compile(r"^cycle-(\d+)$")
REVIEW_RE = re.compile(r"^review-v(\d+)\.md$")
DONE_RE = re.compile(r"pass-(\d+)-done\.json")
VERDICTS = ("BLOCKED", "PASS", "READY_TO_MERGE")
PASS_VERDICTS = ("PASS", "READY_TO_MERGE")
VERDICT_RE = re.compile(r"^## Verdict\s*\n\s*(BLOCKED|PASS|READY_TO_MERGE)\s*$", re.M)
ERROR_GAP_SECONDS = 30 * 60
INFRA_RE = re.compile(r"urlopen|ssl|timeout|resolution|name resolution|handshake", re.I)
# JSONL files are parsed one line at a time, so large long-running sessions do
# not need to be discarded. A positive caller override can still impose a cap.
DEFAULT_MAX_TRANSCRIPT_BYTES = 0
INTERVENTION_EVENTS = {
    "telegram_command",
    "telegram_callback",
    "dashboard_command",
    "dashboard_done",
    "dashboard_agent",
}
SELECTION_FILE = "selection.json"
SCORE_KEYS = (
    "userValue",
    "dependencyUnlock",
    "codeAffinity",
    "independentVerification",
    "changeRisk",
    "testCost",
    "repetitionPenalty",
)
FRAGMENTATION_SCORE_KEY = "fragmentationPenalty"
CYCLE_SUBJECT_RE = re.compile(r"\bcycle(?:[- _])?(\d+)\b", re.I)
SPEC_ID_RE = re.compile(r"\b(?:FR|SPEC)-[A-Z0-9]+(?:-[A-Z0-9]+)+\b", re.I)
EMPTY_GIT_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

# Per-cycle autonomySec remains elapsed start→verdict for compatibility. The
# aggregate autonomy/handsOff total includes only event-timestamped cycles;
# artifact-mtime backfills are reported separately. We do not guess a duration
# for each intervention, so the count remains visible alongside elapsed time.


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _to_iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_ts(value: Any) -> float | None:
    """Parse an ISO-8601 timestamp (with Z or offset, optional ms) to epoch seconds."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def parse_verdict(text: str) -> str | None:
    match = VERDICT_RE.search(text)
    if match:
        return match.group(1)
    for verdict in VERDICTS:
        if re.search(rf"\b{verdict}\b", text):
            return verdict
    return None


def load_events(root: Path) -> list[dict[str, Any]]:
    path = root / "logs" / "hermes-events.jsonl"
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    for line in read_text(path).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def last_meta_cycle_at(root: Path) -> int | None:
    """Highest cyclesAt recorded in logs/meta-cycles.jsonl, or None."""
    path = root / "logs" / "meta-cycles.jsonl"
    if not path.exists():
        return None
    best: int | None = None
    for line in read_text(path).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        val = rec.get("cyclesAt")
        if isinstance(val, int) and (best is None or val > best):
            best = val
    return best


def load_pricing() -> dict[str, Any]:
    for name in ("pricing.json", "pricing.example.json"):
        path = APP_DIR / name
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data.get("models"), dict) and data["models"]:
                    return data
            except (OSError, json.JSONDecodeError):
                continue
    return {"models": {"default": {}}}


def default_transcript_dir(root: Path) -> Path:
    flattened = str(root).replace("/", "-")
    return Path.home() / ".claude" / "projects" / flattened


def default_codex_dir() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"


# --- cycle artifact scanning ------------------------------------------------


def scan_cycle(cycle_dir: Path, root: Path) -> dict[str, Any]:
    num = int(CYCLE_DIR_RE.match(cycle_dir.name).group(1))
    # done files (executor/ preferred, fall back to cycle root)
    dones: dict[int, dict[str, Any]] = {}
    for base in (cycle_dir / "executor", cycle_dir):
        if not base.exists():
            continue
        for path in base.glob("pass-*-done.json"):
            match = DONE_RE.search(path.name)
            if not match:
                continue
            pass_no = int(match.group(1))
            if pass_no in dones:
                continue
            info: dict[str, Any] = {}
            try:
                info = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                info = {}
            created = parse_ts(info.get("createdAt"))
            if created is None:
                try:
                    created = path.stat().st_mtime
                except OSError:
                    created = None
            dones[pass_no] = {
                "kind": info.get("kind"),
                "createdAt": created,
                "path": path,
                "checks": info.get("checks") if isinstance(info.get("checks"), list) else [],
            }

    # reviews: number -> (verdict, mtime)
    reviews: dict[int, dict[str, Any]] = {}
    for path in cycle_dir.glob("review-v*.md"):
        match = REVIEW_RE.match(path.name)
        if not match:
            continue
        n = int(match.group(1))
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = None
        reviews[n] = {
            "verdict": parse_verdict(read_text(path)),
            "mtime": mtime,
            "rel": str(path.relative_to(root)),
        }

    # earliest file mtime as startedAt fallback
    earliest = None
    for path in cycle_dir.rglob("*"):
        try:
            mt = path.stat().st_mtime
        except OSError:
            continue
        if earliest is None or mt < earliest:
            earliest = mt

    plan_text = read_text(cycle_dir / "plan.md")
    spec_line = next((line for line in plan_text.splitlines() if line.lstrip().startswith("Spec:")), "")
    spec_ids = list(dict.fromkeys(value.upper() for value in SPEC_ID_RE.findall(spec_line)))
    selection, selection_errors = scan_selection(cycle_dir / SELECTION_FILE, num)
    return {
        "cycle": num,
        "dir": cycle_dir,
        "dones": dones,
        "reviews": reviews,
        "earliest_mtime": earliest,
        "selection": selection,
        "selection_errors": selection_errors,
        "spec_ids": spec_ids,
    }


def scan_selection(path: Path, cycle: int) -> tuple[dict[str, Any] | None, list[str]]:
    """Read a planner's immutable candidate decision without inventing data.

    The schema is intentionally permissive for forward compatibility, but the
    fields needed for comparison are validated and surfaced as data-quality
    errors instead of silently becoming zeros.
    """
    if not path.exists():
        return None, []
    data = read_json_object(path)
    if data is None:
        return None, ["selection.json is not a JSON object"]
    errors: list[str] = []
    if data.get("cycle") != cycle:
        errors.append(f"selection cycle must be {cycle}")
    chosen = data.get("chosen")
    chosen_id = chosen.get("id") if isinstance(chosen, dict) else chosen
    if not isinstance(chosen_id, str) or not chosen_id.strip():
        errors.append("selection chosen task id is missing")
        chosen_id = None
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        errors.append("selection candidates must be a non-empty list")
        candidates = []
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(candidates):
        if not isinstance(row, dict):
            errors.append(f"candidate {index + 1} is not an object")
            continue
        task_id = row.get("task") or row.get("id")
        if not isinstance(task_id, str) or not task_id.strip():
            errors.append(f"candidate {index + 1} has no task id")
            continue
        scores = row.get("scores") if isinstance(row.get("scores"), dict) else {}
        clean_scores: dict[str, float] = {}
        required_score_keys = SCORE_KEYS + ((FRAGMENTATION_SCORE_KEY,) if data.get("scoreVersion") == "pev-selection-v2" else ())
        for key in required_score_keys:
            value = scores.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                clean_scores[key] = float(value)
                minimum = 0 if key in {"repetitionPenalty", FRAGMENTATION_SCORE_KEY} else 1
                if not minimum <= float(value) <= 5:
                    errors.append(f"candidate {task_id} score {key} must be {minimum}..5")
            else:
                errors.append(f"candidate {task_id} score {key} is missing")
        predictions = row.get("predictions") if isinstance(row.get("predictions"), dict) else {}
        prediction_keys = ["durationMin", "testDurationMin", "costUsd", "firstPassProbability", "filesChanged"]
        if data.get("scoreVersion") == "pev-selection-v2":
            prediction_keys.extend(("repeatedTestDurationMin", "fixedVerificationCostUsd"))
        for key in prediction_keys:
            if not isinstance(predictions.get(key), (int, float)) or isinstance(predictions.get(key), bool):
                errors.append(f"candidate {task_id} prediction {key} is missing")
        normalized.append({**row, "task": task_id.strip(), "scores": clean_scores})
    if chosen_id and normalized and chosen_id not in {row["task"] for row in normalized}:
        errors.append("chosen task is not present in candidates")
    return {**data, "chosen": chosen_id, "candidates": normalized}, errors


def cycle_started_map(events: Iterable[dict[str, Any]]) -> dict[int, float]:
    started: dict[int, float] = {}
    for ev in events:
        if ev.get("event") != "cycle_started":
            continue
        num = ev.get("cycle")
        ts = parse_ts(ev.get("ts"))
        if isinstance(num, int) and ts is not None and num not in started:
            started[num] = ts
    return started


def cycle_events(events: Iterable[dict[str, Any]], event_name: str) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for event in events:
        if event.get("event") != event_name or not isinstance(event.get("cycle"), int):
            continue
        if parse_ts(event.get("ts")) is None:
            continue
        grouped.setdefault(event["cycle"], []).append(event)
    for rows in grouped.values():
        rows.sort(key=lambda row: parse_ts(row.get("ts")) or 0.0)
    return grouped


def agent_turn_intervals(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    starts: dict[str, dict[str, Any]] = {}
    finishes: dict[str, dict[str, Any]] = {}
    for event in events:
        turn_id = event.get("turnId")
        if not isinstance(turn_id, str):
            continue
        if event.get("event") == "agent_turn_started":
            starts[turn_id] = event
        elif event.get("event") == "agent_turn_finished":
            finishes[turn_id] = event
    intervals: list[dict[str, Any]] = []
    for turn_id in starts.keys() | finishes.keys():
        start_event = starts.get(turn_id, {})
        finish_event = finishes.get(turn_id, {})
        start = parse_ts(start_event.get("ts")) or parse_ts(finish_event.get("started_at"))
        end = parse_ts(finish_event.get("ts"))
        if start is None:
            continue
        intervals.append(
            {
                "turnId": turn_id,
                "cycle": start_event.get("cycle", finish_event.get("cycle")),
                "agent": start_event.get("agent", finish_event.get("agent")),
                "action": start_event.get("action", finish_event.get("action")),
                "start": start,
                "end": end,
                "outcome": finish_event.get("outcome"),
            }
        )
    return intervals


def git_cycle_map(root: Path) -> dict[int, dict[str, Any]]:
    """Map cycle-labelled commits and their aggregate diff size.

    Git is a durable timestamp fallback when event/artifact timestamps were
    copied or rewritten. Only commits whose subject names a cycle are used.
    """
    try:
        result = subprocess.run(
            ["git", "log", "--all", "--reverse", "--format=%H%x09%ct%x09%s"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if result.returncode != 0:
        return {}
    grouped: dict[int, list[dict[str, Any]]] = {}
    for line in result.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        sha, raw_ts, subject = parts
        match = CYCLE_SUBJECT_RE.search(subject)
        try:
            ts = float(raw_ts)
        except ValueError:
            continue
        if match:
            grouped.setdefault(int(match.group(1)), []).append({"sha": sha, "ts": ts, "subject": subject})
    output: dict[int, dict[str, Any]] = {}
    for cycle, commits in grouped.items():
        commits.sort(key=lambda row: row["ts"])
        terminal = next(
            (
                row
                for row in reversed(commits)
                if re.search(r"\b(review|ready|merge)\b", row["subject"], re.I)
            ),
            None,
        )
        stats = git_diff_stats(root, commits[0]["sha"], commits[-1]["sha"])
        output[cycle] = {
            "firstAt": commits[0]["ts"],
            "lastAt": commits[-1]["ts"],
            "terminalAt": terminal["ts"] if terminal else None,
            "firstSha": commits[0]["sha"],
            "lastSha": commits[-1]["sha"],
            "commits": len(commits),
            **stats,
        }
    return output


def git_diff_stats(root: Path, first_sha: str, last_sha: str) -> dict[str, int]:
    try:
        parent = subprocess.run(
            ["git", "rev-parse", f"{first_sha}^"], cwd=root, capture_output=True, text=True, timeout=5
        )
        if parent.returncode == 0:
            result = subprocess.run(
                ["git", "diff", "--numstat", parent.stdout.strip(), last_sha],
                cwd=root, capture_output=True, text=True, timeout=20,
            )
        else:
            result = subprocess.run(
                ["git", "diff", "--numstat", EMPTY_GIT_TREE, last_sha],
                cwd=root, capture_output=True, text=True, timeout=20,
            )
    except (OSError, subprocess.SubprocessError):
        return {"filesChanged": 0, "linesAdded": 0, "linesDeleted": 0}
    files = added = deleted = 0
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            parts = line.split("\t", 2)
            if len(parts) != 3:
                continue
            files += 1
            if parts[0].isdigit():
                added += int(parts[0])
            if parts[1].isdigit():
                deleted += int(parts[1])
    return {"filesChanged": files, "linesAdded": added, "linesDeleted": deleted}


# --- token / cost -----------------------------------------------------------


def empty_tokens() -> dict[str, int]:
    return {"input": 0, "output": 0, "cacheWrite5m": 0, "cacheWrite1h": 0, "cacheRead": 0}


def line_tokens(usage: dict[str, Any]) -> dict[str, int]:
    cache_creation = usage.get("cache_creation") or {}
    cw5 = int(cache_creation.get("ephemeral_5m_input_tokens") or 0)
    cw1 = int(cache_creation.get("ephemeral_1h_input_tokens") or 0)
    if cw5 == 0 and cw1 == 0:
        # no breakdown available: attribute all creation to the 5m bucket
        cw5 = int(usage.get("cache_creation_input_tokens") or 0)
    return {
        "input": int(usage.get("input_tokens") or 0),
        "output": int(usage.get("output_tokens") or 0),
        "cacheWrite5m": cw5,
        "cacheWrite1h": cw1,
        "cacheRead": int(usage.get("cache_read_input_tokens") or 0),
    }


def _model_rate(model: str | None, pricing: dict[str, Any], provider: str) -> dict[str, Any]:
    models = pricing.get("models", {})
    rate = models.get(model) if model else None
    if not rate and model:
        # Prefix keys make dated/internal aliases (for example claude-opus-4-8-
        # 20260701) use the intended public model rate without code changes.
        matches = [(key[:-1], value) for key, value in models.items() if key.endswith("*") and model.startswith(key[:-1])]
        if matches:
            rate = max(matches, key=lambda item: len(item[0]))[1]
    if not rate:
        rate = models.get(f"{provider}Default") or models.get("default", {})
    return rate


def token_cost(tokens: dict[str, int], model: str | None, pricing: dict[str, Any], provider: str = "claude") -> float:
    rate = _model_rate(model, pricing, provider)
    per = lambda key: float(rate.get(key) or 0.0)  # noqa: E731
    input_tokens = tokens["input"]
    if provider == "codex":
        # Codex input_tokens includes cached_input_tokens; API billing applies
        # the full input rate only to the uncached remainder.
        input_tokens = max(0, input_tokens - tokens["cacheRead"])
    return (
        input_tokens / 1e6 * per("inputPerMTok")
        + tokens["output"] / 1e6 * per("outputPerMTok")
        + tokens["cacheWrite5m"] / 1e6 * per("cacheWrite5mPerMTok")
        + tokens["cacheWrite1h"] / 1e6 * per("cacheWrite1hPerMTok")
        + tokens["cacheRead"] / 1e6 * per("cacheReadPerMTok")
    )


def add_tokens(dst: dict[str, int], src: dict[str, int]) -> None:
    for key in dst:
        dst[key] += src.get(key, 0)


# --- error clustering -------------------------------------------------------


def cluster_errors(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = sorted(
        ((parse_ts(ev.get("ts")), str(ev.get("error") or "")) for ev in events if ev.get("event") == "loop_error"),
        key=lambda r: (r[0] is None, r[0] or 0.0),
    )
    clusters: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for ts, message in rows:
        if ts is None:
            continue
        if current is None or ts - current["_last"] > ERROR_GAP_SECONDS:
            kind = "infra" if INFRA_RE.search(message) else "unknown"
            current = {"kind": kind, "_first": ts, "_last": ts, "count": 1, "sample": message[:200]}
            clusters.append(current)
        else:
            current["_last"] = ts
            current["count"] += 1
            if current["kind"] != "infra" and INFRA_RE.search(message):
                current["kind"] = "infra"
    out: list[dict[str, Any]] = []
    for c in clusters:
        out.append(
            {
                "kind": c["kind"],
                "firstTs": _to_iso(c["_first"]),
                "lastTs": _to_iso(c["_last"]),
                "count": c["count"],
                "sample": c["sample"],
            }
        )
    return out


# --- main computation -------------------------------------------------------


def compute_metrics(
    root: Path,
    transcript_dir: Path | None = None,
    tags: dict[str, str] | None = None,
    codex_dir: Path | None = None,
    max_transcript_bytes: int = DEFAULT_MAX_TRANSCRIPT_BYTES,
) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    tags = tags or {}
    pricing = load_pricing()
    events = load_events(root)
    review_root = root / ".review"
    scans: list[dict[str, Any]] = []
    if review_root.exists():
        for child in review_root.iterdir():
            if child.is_dir() and CYCLE_DIR_RE.match(child.name):
                scans.append(scan_cycle(child, root))
    scans.sort(key=lambda s: s["cycle"])

    starts_by_cycle = cycle_started_map(events)
    verdict_events = cycle_events(events, "verdict")
    done_events = cycle_events(events, "pass_done")
    state_events = cycle_events(events, "state_changed")
    git_cycles = git_cycle_map(root)
    turn_intervals = agent_turn_intervals(events)

    # Derive event-first timelines. Artifact timestamps remain a backfill
    # fallback, but a late synthetic cycle_started event must never move a
    # historical cycle start past its already-recorded completion.
    cycles: list[dict[str, Any]] = []
    for s in scans:
        num = s["cycle"]
        quality: list[str] = list(s["selection_errors"])
        git_info = git_cycles.get(num, {})

        done_times = {pass_no: info.get("createdAt") for pass_no, info in s["dones"].items()}
        for event in done_events.get(num, []):
            pass_no = event.get("pass")
            if not isinstance(pass_no, int):
                continue
            event_time = parse_ts(event.get("created_at")) or parse_ts(event.get("ts"))
            if event_time is not None:
                done_times[pass_no] = event_time

        event_verdicts: list[dict[str, Any]] = []
        for event in verdict_events.get(num, []):
            ts = parse_ts(event.get("ts"))
            verdict = event.get("verdict")
            if ts is not None and verdict in VERDICTS:
                event_verdicts.append({"ts": ts, "verdict": verdict, "review": event.get("review")})

        artifact_verdicts: list[dict[str, Any]] = []
        for review_no in sorted(s["reviews"]):
            review = s["reviews"][review_no]
            if review["verdict"] and review["mtime"] is not None:
                artifact_verdicts.append(
                    {"ts": review["mtime"], "verdict": review["verdict"], "review": review["rel"]}
                )
        activity_times = [value for value in done_times.values() if value is not None]
        event_start = starts_by_cycle.get(num)
        earliest_done = min(activity_times, default=None)
        late_event_backfill = event_start is not None and earliest_done is not None and event_start > earliest_done
        if late_event_backfill:
            quality.append("metric events were emitted after historical executor completion; artifact verdict fallback used")
        git_verdicts: list[dict[str, Any]] = []
        if git_info.get("terminalAt") is not None:
            final_artifact_verdict = next(
                (row["verdict"] for row in reversed(artifact_verdicts) if row["verdict"] in PASS_VERDICTS),
                None,
            )
            if final_artifact_verdict:
                git_verdicts.append(
                    {"ts": git_info["terminalAt"], "verdict": final_artifact_verdict, "review": "git:terminal"}
                )
        timeline_verdicts = (
            (event_verdicts if not late_event_backfill else [])
            or git_verdicts
            or artifact_verdicts
        )

        activity_times.extend(row["ts"] for row in timeline_verdicts)
        earliest_activity = min(activity_times, default=None)
        start = event_start
        if start is not None and earliest_activity is not None and start > earliest_activity:
            quality.append("cycle_started occurred after recorded cycle activity; artifact fallback used")
            start = None
        if start is None:
            start = git_info.get("firstAt")
        if start is None:
            candidates = [value for value in (earliest_activity, s["earliest_mtime"]) if value is not None]
            start = min(candidates, default=None)

        ended = next((row["ts"] for row in timeline_verdicts if row["verdict"] in PASS_VERDICTS), None)
        if ended is not None and start is not None and ended < start:
            quality.append("completion timestamp predates cycle start")
            ended = None
        blocked = next((row["ts"] for row in timeline_verdicts if row["verdict"] == "BLOCKED"), None)
        first_verdict = timeline_verdicts[0]["ts"] if timeline_verdicts else None
        merge = next(
            (
                parse_ts(row.get("ts"))
                for row in state_events.get(num, [])
                if row.get("phase") == "merged" and parse_ts(row.get("ts")) is not None
            ),
            None,
        )
        cycles.append(
            {
                "cycle": num,
                "_start": start,
                "_ended": ended,
                "_next_start": None,
                "_done_times": done_times,
                "_verdicts": timeline_verdicts,
                "_first_verdict": first_verdict,
                "_blocked": blocked,
                "_merge": merge,
                "_quality": quality,
                "_timing_source": "events"
                if event_start is not None and not late_event_backfill and bool(event_verdicts)
                else "git"
                if git_info.get("firstAt") is not None and bool(git_verdicts)
                else "artifacts",
                "_git": git_info,
                "scan": s,
            }
        )

    for index, cycle in enumerate(cycles[:-1]):
        cycle["_next_start"] = cycles[index + 1]["_start"]
        if cycle["_ended"] is None and cycle["_next_start"] is not None:
            cycle["_quality"].append("completion missing; next cycle start used as fallback")

    # attribution window per cycle: [start, ended or next_start or +inf)
    for c in cycles:
        start = c["_start"]
        upper = c["_merge"] or c["_ended"] or c["_next_start"]
        c["_attr_lo"] = start
        c["_attr_hi"] = upper  # None means open-ended (active cycle)
        c["tokens"] = empty_tokens()
        c["costUsd"] = 0.0
        c["reworkCostUsd"] = 0.0
        c["agentCostsUsd"] = {"claude": 0.0, "codex": 0.0}
        c["agentTokens"] = {"claude": empty_tokens(), "codex": empty_tokens()}
        c["phaseCostsUsd"] = {"implementation": 0.0, "verification": 0.0, "rework": 0.0, "merge": 0.0}

    unattributed = empty_tokens()
    unattributed_cost = [0.0]
    unattributed_by_agent = {
        "claude": {"tokens": empty_tokens(), "costUsd": 0.0},
        "codex": {"tokens": empty_tokens(), "costUsd": 0.0},
    }
    skipped: list[str] = []

    tdir = Path(transcript_dir) if transcript_dir else default_transcript_dir(root)
    min_start = min((c["_start"] for c in cycles if c["_start"] is not None), default=None)

    if tdir.exists():
        for path in sorted(tdir.glob("*.jsonl")):
            try:
                st = path.stat()
            except OSError:
                continue
            if max_transcript_bytes > 0 and st.st_size > max_transcript_bytes:
                skipped.append(path.name)
                continue
            # whole-file skip: mtime before any cycle began => entirely stale
            if min_start is not None and st.st_mtime < min_start:
                continue
            _scan_transcript(path, cycles, pricing, unattributed, unattributed_cost, unattributed_by_agent)

    cdir = Path(codex_dir) if codex_dir else default_codex_dir()
    if cdir.exists():
        for path in sorted(cdir.rglob("*.jsonl")):
            try:
                st = path.stat()
            except OSError:
                continue
            if max_transcript_bytes > 0 and st.st_size > max_transcript_bytes:
                skipped.append(str(path.relative_to(cdir)))
                continue
            if min_start is not None and st.st_mtime < min_start:
                continue
            _scan_codex_transcript(path, root, cycles, pricing, unattributed, unattributed_cost, unattributed_by_agent)

    # assemble cycle output
    out_cycles: list[dict[str, Any]] = []
    total_cost = 0.0
    total_rework = 0.0
    backfilled_rework = 0.0
    total_agent_costs = {"claude": 0.0, "codex": 0.0}
    total_agent_tokens = {"claude": empty_tokens(), "codex": empty_tokens()}
    total_phase_costs = {"implementation": 0.0, "verification": 0.0, "rework": 0.0, "merge": 0.0}
    measured_hands_off_sec = 0.0
    measured_cycle_elapsed_sec = 0.0
    active_agent_sec = 0.0
    active_agent_cycles = 0
    backfilled_elapsed_sec = 0.0
    first_pass_count = 0
    counted = 0
    quality_issue_cycles = 0
    for c in cycles:
        s = c["scan"]
        start, ended = c["_start"], c["_ended"]
        duration = None
        end_for_duration = ended or c["_next_start"]
        if start is not None and end_for_duration is not None:
            duration = max(0, int(end_for_duration - start))
        passes = len(s["dones"])
        v1 = s["reviews"].get(1, {}).get("verdict")
        first_pass = v1 in PASS_VERDICTS
        final_verdict = None
        for n in sorted(s["reviews"], reverse=True):
            if s["reviews"][n]["verdict"]:
                final_verdict = s["reviews"][n]["verdict"]
                break
        intervention = _intervention_metrics(events, c["cycle"], c["_attr_lo"], c["_attr_hi"])
        blocked_to_fix = _blocked_to_fix(c)
        first_done = c["_done_times"].get(1)
        implementation_sec = _elapsed(start, first_done)
        verification_sec = _elapsed(first_done, c["_first_verdict"])
        rework_sec = _elapsed(c["_blocked"], ended) if c["_blocked"] is not None else None
        merge_sec = _elapsed(ended, c["_merge"])
        active = _active_agent_metrics(
            turn_intervals,
            c["cycle"],
            start,
            ended or c["_merge"] or c["_next_start"],
        )
        checks = check_metrics(s["dones"])
        check_duration_sec = checks["durationSec"]
        selection = selection_metrics(
            s["selection"], duration, check_duration_sec, c["costUsd"], first_pass, final_verdict
        )
        if c["_quality"]:
            quality_issue_cycles += 1
        if duration is not None and c["_timing_source"] == "events":
            measured_cycle_elapsed_sec += duration
            if intervention["total"] == 0:
                measured_hands_off_sec += duration
        elif duration is not None:
            backfilled_elapsed_sec += duration
        if active["covered"]:
            active_agent_sec += active["totalSec"]
            active_agent_cycles += 1
        total_cost += c["costUsd"]
        if c["_timing_source"] == "events":
            total_rework += c["reworkCostUsd"]
        else:
            backfilled_rework += c["reworkCostUsd"]
        for phase in total_phase_costs:
            total_phase_costs[phase] += c["phaseCostsUsd"][phase]
        for agent in total_agent_costs:
            total_agent_costs[agent] += c["agentCostsUsd"][agent]
            add_tokens(total_agent_tokens[agent], c["agentTokens"][agent])
        if final_verdict is not None:
            counted += 1
            if first_pass:
                first_pass_count += 1
        out_cycles.append(
            {
                "cycle": c["cycle"],
                "startedAt": _to_iso(start),
                "endedAt": _to_iso(ended or c["_next_start"]),
                "mergedAt": _to_iso(c["_merge"]),
                "durationSec": duration,
                "phaseDurationSec": {
                    "implementation": implementation_sec,
                    "verification": verification_sec,
                    "rework": rework_sec,
                    "merge": merge_sec,
                },
                "passes": passes,
                "firstPass": first_pass,
                "finalVerdict": final_verdict,
                "interventions": intervention["total"],
                "intervention": intervention,
                "autonomySec": duration if intervention["total"] == 0 else None,
                "handsOffElapsedSec": duration if intervention["total"] == 0 else None,
                "activeAgentSec": active["totalSec"],
                "agentActiveSec": active["byAgent"],
                "activeTimeCoverage": active["covered"],
                "timingSource": c["_timing_source"],
                "blockedToFixSec": blocked_to_fix,
                "checkDurationSec": round(check_duration_sec, 3),
                "checks": checks,
                "tokens": c["tokens"],
                "agentTokens": c["agentTokens"],
                "agentCostsUsd": {key: round(value, 4) for key, value in c["agentCostsUsd"].items()},
                "costUsd": round(c["costUsd"], 4),
                "reworkCostUsd": round(c["reworkCostUsd"], 4),
                "phaseCostsUsd": {key: round(value, 4) for key, value in c["phaseCostsUsd"].items()},
                "failureTag": tags.get(str(c["cycle"])),
                "selection": selection,
                "specIds": s["spec_ids"],
                "git": c["_git"],
                "normalized": cycle_normalized_metrics(
                    c["_git"], c["phaseCostsUsd"], implementation_sec, verification_sec
                ),
                "dataQuality": c["_quality"],
            }
        )

    selection_totals = aggregate_selection_metrics(out_cycles)
    unit_totals = aggregate_unit_metrics(out_cycles)
    execution_totals = aggregate_execution_metrics(out_cycles)
    intervention_totals = aggregate_intervention_metrics(out_cycles)
    totals = {
        "cycles": len(out_cycles),
        "firstPassRate": round(first_pass_count / counted, 4) if counted else None,
        "autonomyHours": round(measured_hands_off_sec / 3600, 2),
        "handsOffHours": round(measured_hands_off_sec / 3600, 2),
        "measuredCycleElapsedHours": round(measured_cycle_elapsed_sec / 3600, 2),
        "activeAgentHours": round(active_agent_sec / 3600, 2),
        "activeAgentCycles": active_agent_cycles,
        "backfilledElapsedHours": round(backfilled_elapsed_sec / 3600, 2),
        "timedCycles": sum(1 for row in out_cycles if row["timingSource"] == "events" and row["durationSec"] is not None),
        "backfilledCycles": sum(1 for row in out_cycles if row["timingSource"] != "events" and row["durationSec"] is not None),
        "costUsd": round(total_cost, 4),
        "reworkCostUsd": round(total_rework, 4),
        "backfilledReworkCostUsd": round(backfilled_rework, 4),
        "agentCostsUsd": {key: round(value, 4) for key, value in total_agent_costs.items()},
        "agentTokens": total_agent_tokens,
        "phaseCostsUsd": {key: round(value, 4) for key, value in total_phase_costs.items()},
        "unattributedTokens": unattributed,
        "unattributedCostUsd": round(unattributed_cost[0], 4),
        "unattributedByAgent": {
            key: {"tokens": value["tokens"], "costUsd": round(value["costUsd"], 4)}
            for key, value in unattributed_by_agent.items()
        },
        "lastMetaCycleAt": last_meta_cycle_at(root),
        "dataQualityIssueCycles": quality_issue_cycles,
        "selection": selection_totals,
        "units": unit_totals,
        "execution": execution_totals,
        "interventions": intervention_totals,
    }

    return {
        "schemaVersion": 3,
        "generatedAt": utc_now(),
        "root": str(root),
        "transcriptDir": str(tdir),
        "transcriptDirs": {"claude": str(tdir), "codex": str(cdir)},
        "skippedTranscripts": skipped,
        "cycles": out_cycles,
        "totals": totals,
        "errors": cluster_errors(events),
    }


def _scan_transcript(
    path: Path,
    cycles: list[dict[str, Any]],
    pricing: dict[str, Any],
    unattributed: dict[str, int],
    unattributed_cost: list[float],
    unattributed_by_agent: dict[str, dict[str, Any]],
) -> None:
    try:
        fh = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return
    # Claude Code emits several JSONL records for one API response (thinking,
    # tool use, text), each carrying the same message.id and usage. Retain only
    # the final usage snapshot for each API message to avoid multiplying cost.
    messages: dict[str, tuple[float, dict[str, int], str | None]] = {}
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = rec.get("message") or {}
            usage = message.get("usage")
            if not usage:
                continue
            ts = parse_ts(rec.get("timestamp"))
            if ts is None:
                continue
            toks = line_tokens(usage)
            model = message.get("model")
            key = str(message.get("id") or rec.get("uuid") or f"{ts}:{len(messages)}")
            messages[key] = (ts, toks, model)
    for ts, toks, model in messages.values():
        _attribute_usage(cycles, ts, toks, token_cost(toks, model, pricing, "claude"), "claude",
                         unattributed, unattributed_cost, unattributed_by_agent)


def _codex_tokens(usage: dict[str, Any]) -> dict[str, int]:
    return {
        "input": int(usage.get("input_tokens") or 0),
        "output": int(usage.get("output_tokens") or 0),
        "cacheWrite5m": 0,
        "cacheWrite1h": 0,
        "cacheRead": int(usage.get("cached_input_tokens") or 0),
    }


def _token_delta(current: dict[str, int], previous: dict[str, int]) -> dict[str, int]:
    return {key: max(0, current.get(key, 0) - previous.get(key, 0)) for key in current}


def _scan_codex_transcript(
    path: Path,
    root: Path,
    cycles: list[dict[str, Any]],
    pricing: dict[str, Any],
    unattributed: dict[str, int],
    unattributed_cost: list[float],
    unattributed_by_agent: dict[str, dict[str, Any]],
) -> None:
    try:
        fh = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return
    model: str | None = None
    previous = empty_tokens()
    project_matches = False
    with fh:
        for line_no, line in enumerate(fh):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if line_no == 0 and rec.get("type") == "session_meta":
                cwd = (rec.get("payload") or {}).get("cwd")
                try:
                    project_matches = Path(str(cwd)).expanduser().resolve() == root
                except (OSError, ValueError):
                    project_matches = False
                if not project_matches:
                    return
            if not project_matches:
                continue
            payload = rec.get("payload") or {}
            if rec.get("type") == "turn_context" and payload.get("model"):
                model = str(payload["model"])
                continue
            if rec.get("type") != "event_msg" or payload.get("type") != "token_count":
                continue
            info = payload.get("info") or {}
            total = _codex_tokens(info.get("total_token_usage") or {})
            toks = _token_delta(total, previous)
            previous = total
            ts = parse_ts(rec.get("timestamp"))
            if ts is None or not any(toks.values()):
                continue
            cost = token_cost(toks, model, pricing, "codex")
            _attribute_usage(cycles, ts, toks, cost, "codex", unattributed, unattributed_cost, unattributed_by_agent)


def _attribute_usage(
    cycles: list[dict[str, Any]],
    ts: float,
    toks: dict[str, int],
    cost: float,
    agent: str,
    unattributed: dict[str, int],
    unattributed_cost: list[float],
    unattributed_by_agent: dict[str, dict[str, Any]],
) -> None:
    target = _cycle_for_ts(cycles, ts)
    if target is None:
        add_tokens(unattributed, toks)
        unattributed_cost[0] += cost
        add_tokens(unattributed_by_agent[agent]["tokens"], toks)
        unattributed_by_agent[agent]["costUsd"] += cost
        return
    add_tokens(target["tokens"], toks)
    add_tokens(target["agentTokens"][agent], toks)
    target["costUsd"] += cost
    target["agentCostsUsd"][agent] += cost
    phase = _cost_phase(target, ts)
    target["phaseCostsUsd"][phase] += cost
    if phase == "rework":
        target["reworkCostUsd"] += cost


def _cost_phase(cycle: dict[str, Any], ts: float) -> str:
    merge = cycle.get("_merge")
    ended = cycle.get("_ended")
    if ended is not None and merge is not None and ended <= ts < merge:
        return "merge"
    blocked = cycle.get("_blocked")
    if blocked is not None and ts >= blocked:
        return "rework"
    first_done = cycle.get("_done_times", {}).get(1)
    if first_done is not None and ts >= first_done:
        return "verification"
    return "implementation"


def _cycle_for_ts(cycles: list[dict[str, Any]], ts: float) -> dict[str, Any] | None:
    for c in cycles:
        lo, hi = c["_attr_lo"], c["_attr_hi"]
        if lo is None:
            continue
        if ts >= lo and (hi is None or ts < hi):
            return c
    return None


def _intervention_metrics(
    events: list[dict[str, Any]], cycle: int, lo: float | None, hi: float | None
) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    by_origin: dict[str, int] = {}
    handling_sec = 0.0
    for ev in events:
        if ev.get("event") not in INTERVENTION_EVENTS:
            continue
        ts = parse_ts(ev.get("ts"))
        if ts is None:
            continue
        event_cycle = ev.get("cycle")
        if not (event_cycle == cycle or (event_cycle is None and lo is not None and ts >= lo and (hi is None or ts < hi))):
            continue
        kind = str(ev.get("intervention_type") or _infer_intervention_type(ev))
        origin = str(ev.get("origin") or ("telegram" if ev.get("event", "").startswith("telegram") else "dashboard"))
        by_type[kind] = by_type.get(kind, 0) + 1
        by_origin[origin] = by_origin.get(origin, 0) + 1
        duration_ms = ev.get("duration_ms")
        if isinstance(duration_ms, (int, float)) and not isinstance(duration_ms, bool):
            handling_sec += max(0.0, float(duration_ms) / 1000)
    actionable = sum(
        count for kind, count in by_type.items() if kind not in {"observation", "flow_start", "unclassified"}
    )
    return {
        "total": actionable,
        "observations": by_type.get("observation", 0),
        "byType": by_type,
        "byOrigin": by_origin,
        "commandHandlingSec": round(handling_sec, 3),
    }


def _infer_intervention_type(event: dict[str, Any]) -> str:
    if event.get("event") in {"dashboard_done", "dashboard_agent"}:
        return "override"
    command = str(event.get("command") or event.get("text") or event.get("data") or "")
    if not command.strip():
        return "unclassified"
    base = command.strip().split(maxsplit=1)[0].lower() if command.strip() else ""
    if base in {"/status", "/cycle", "/tail", "/help", "/start", "/menu", "/remaining"}:
        return "observation"
    if base == "/say":
        return "guidance"
    if base in {"/fix", "/recheck"}:
        return "retry"
    if base == "/merge":
        return "manual_merge"
    if base in {"/enter", "/approve-ui", "/hold", "/resume"}:
        return "override"
    if base in {"/implement", "/review", "/prepare_next", "/prepare-next"}:
        return "manual_progress"
    if base == "/flow":
        parts = command.strip().lower().split()
        mode = parts[1] if len(parts) > 1 else "status"
        if mode in {"safe", "on", "full"}:
            return "flow_start"
        if mode in {"status", "state"}:
            return "observation"
        if mode == "reset":
            return "override"
        return "flow_control"
    return "other"


def _active_agent_metrics(
    intervals: list[dict[str, Any]], cycle: int, lo: float | None, hi: float | None
) -> dict[str, Any]:
    if lo is None or hi is None or hi < lo:
        return {"totalSec": None, "byAgent": {"claude": None, "codex": None}, "covered": False}
    clipped: list[tuple[float, float]] = []
    per_agent: dict[str, list[tuple[float, float]]] = {"claude": [], "codex": []}
    for interval in intervals:
        start = interval["start"]
        # An unmatched start is not proof that the agent stayed active through
        # the rest of the cycle (runner/service crashes are possible). Count
        # only closed intervals; live turns become measurable on their finish.
        end = interval.get("end")
        if end is None:
            continue
        if interval.get("cycle") not in {None, cycle} or end <= lo or start >= hi:
            continue
        item = (max(lo, start), min(hi, end))
        if item[1] <= item[0]:
            continue
        clipped.append(item)
        agent = interval.get("agent")
        if agent in per_agent:
            per_agent[agent].append(item)
    if not clipped:
        return {"totalSec": None, "byAgent": {"claude": None, "codex": None}, "covered": False}
    return {
        "totalSec": _union_seconds(clipped),
        "byAgent": {agent: _union_seconds(rows) if rows else 0 for agent, rows in per_agent.items()},
        "covered": True,
    }


def _union_seconds(intervals: list[tuple[float, float]]) -> int:
    total = 0.0
    current_start = current_end = None
    for start, end in sorted(intervals):
        if current_start is None:
            current_start, current_end = start, end
        elif start <= current_end:
            current_end = max(current_end, end)
        else:
            total += current_end - current_start
            current_start, current_end = start, end
    if current_start is not None:
        total += current_end - current_start
    return int(total)


def _blocked_to_fix(cycle: dict[str, Any]) -> int | None:
    blocked = cycle.get("_blocked")
    if blocked is None:
        return None
    later = sorted(ts for pass_no, ts in cycle.get("_done_times", {}).items() if pass_no > 1 and ts is not None and ts >= blocked)
    if later:
        return int(later[0] - blocked)
    return None


def _elapsed(start: float | None, end: float | None) -> int | None:
    if start is None or end is None or end < start:
        return None
    return int(end - start)


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def check_metrics(dones: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Summarize executor checks while preserving legacy/unknown coverage."""
    total = failed = unknown = 0
    duration = 0.0
    failed_stages: list[dict[str, Any]] = []
    stages: list[dict[str, Any]] = []
    for pass_no, done in sorted(dones.items()):
        for index, check in enumerate(done.get("checks", []), 1):
            total += 1
            if not isinstance(check, dict):
                unknown += 1
                continue
            seconds = _number(check.get("durationSec"))
            if seconds is not None:
                duration += max(0.0, seconds)
            exit_code = check.get("exitCode")
            stage = {
                "pass": pass_no,
                "index": index,
                "command": str(check.get("command") or check.get("name") or "unknown"),
                "exitCode": exit_code if isinstance(exit_code, int) and not isinstance(exit_code, bool) else None,
                "durationSec": round(max(0.0, seconds), 3) if seconds is not None else None,
            }
            stages.append(stage)
            if not isinstance(exit_code, int) or isinstance(exit_code, bool):
                unknown += 1
            elif exit_code != 0:
                failed += 1
                failed_stages.append(stage)
    return {
        "recorded": total,
        "failed": failed,
        "unknownOutcome": unknown,
        "durationSec": round(duration, 3),
        "coverage": round((total - unknown) / total, 4) if total else None,
        "failedStages": failed_stages,
        "stages": stages,
    }


def selection_metrics(
    selection: dict[str, Any] | None,
    duration_sec: int | None,
    check_duration_sec: float,
    cost_usd: float,
    first_pass: bool,
    final_verdict: str | None,
) -> dict[str, Any] | None:
    if selection is None:
        return None
    candidates = selection.get("candidates") or []
    chosen_id = selection.get("chosen")
    chosen = next((row for row in candidates if row.get("task") == chosen_id), None)
    if chosen is None:
        return {
            "scoreVersion": selection.get("scoreVersion"),
            "chosen": chosen_id,
            "candidateCount": len(candidates),
            "taskIds": [chosen_id] if chosen_id else [],
        }
    predictions = chosen.get("predictions") if isinstance(chosen.get("predictions"), dict) else {}
    weights = selection.get("weights") if isinstance(selection.get("weights"), dict) else {}
    calculated_total = _candidate_total(chosen, weights)
    totals = sorted(
        (value for value in (_candidate_total(row, weights) for row in candidates) if value is not None),
        reverse=True,
    )
    predicted_duration = _number(predictions.get("durationMin"))
    predicted_test_duration = _number(predictions.get("testDurationMin"))
    predicted_cost = _number(predictions.get("costUsd"))
    predicted_first_pass = _number(predictions.get("firstPassProbability"))
    actual_duration = duration_sec / 60 if duration_sec is not None else None
    completed = final_verdict is not None
    included_tasks = chosen.get("includedTasks")
    task_ids = (
        [str(value).strip() for value in included_tasks if isinstance(value, str) and value.strip()]
        if isinstance(included_tasks, list)
        else [chosen_id]
    )
    if chosen_id and chosen_id not in task_ids:
        task_ids.insert(0, chosen_id)
    return {
        "scoreVersion": selection.get("scoreVersion"),
        "chosen": chosen_id,
        "title": chosen.get("title"),
        "requirement": chosen.get("requirement"),
        "taskIds": list(dict.fromkeys(task_ids)),
        "candidateCount": len(candidates),
        "total": calculated_total,
        "reportedTotal": _number(chosen.get("total")),
        "scoreMargin": round(totals[0] - totals[1], 3) if len(totals) > 1 else None,
        "scores": chosen.get("scores") or {},
        "predictions": predictions,
        "fragmentation": chosen.get("fragmentation") if isinstance(chosen.get("fragmentation"), dict) else None,
        "actual": {
            "durationMin": round(actual_duration, 2) if actual_duration is not None else None,
            "testDurationMin": round(check_duration_sec / 60, 2),
            "costUsd": round(cost_usd, 4),
            "firstPass": first_pass if completed else None,
        },
        "errors": {
            "durationMin": round(abs(actual_duration - predicted_duration), 2)
            if completed and actual_duration is not None and predicted_duration is not None
            else None,
            "costUsd": round(abs(cost_usd - predicted_cost), 4)
            if completed and predicted_cost is not None
            else None,
            "testDurationMin": round(abs(check_duration_sec / 60 - predicted_test_duration), 2)
            if completed and predicted_test_duration is not None
            else None,
            "firstPassSquared": round((float(first_pass) - predicted_first_pass) ** 2, 4)
            if completed and predicted_first_pass is not None and 0 <= predicted_first_pass <= 1
            else None,
        },
    }


def _candidate_total(candidate: dict[str, Any], weights: dict[str, Any]) -> float | None:
    scores = candidate.get("scores") if isinstance(candidate.get("scores"), dict) else {}
    products: list[float] = []
    keys = SCORE_KEYS + ((FRAGMENTATION_SCORE_KEY,) if FRAGMENTATION_SCORE_KEY in weights else ())
    for key in keys:
        score = _number(scores.get(key))
        weight = _number(weights.get(key))
        if score is not None and weight is not None:
            products.append(score * weight)
    if products:
        return round(sum(products), 3)
    return _number(candidate.get("total"))


def aggregate_selection_metrics(cycles: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in cycles if row.get("finalVerdict") is not None]
    selected = [row for row in completed if row.get("selection") is not None]
    first_recorded_cycle = min((row["cycle"] for row in selected), default=None)
    eligible = [row for row in completed if first_recorded_cycle is not None and row["cycle"] >= first_recorded_cycle]
    values = [
        _number(row["selection"].get("scores", {}).get("userValue"))
        for row in selected
        if row["selection"].get("scores")
    ]
    values = [value for value in values if value is not None]
    duration_errors = [row["selection"].get("errors", {}).get("durationMin") for row in selected]
    cost_errors = [row["selection"].get("errors", {}).get("costUsd") for row in selected]
    test_duration_errors = [row["selection"].get("errors", {}).get("testDurationMin") for row in selected]
    brier = [row["selection"].get("errors", {}).get("firstPassSquared") for row in selected]
    duration_errors = [value for value in duration_errors if value is not None]
    cost_errors = [value for value in cost_errors if value is not None]
    test_duration_errors = [value for value in test_duration_errors if value is not None]
    brier = [value for value in brier if value is not None]
    low_value_streak = 0
    for row in reversed(completed):
        value = _number((row.get("selection") or {}).get("scores", {}).get("userValue"))
        if value is None or value > 2:
            break
        low_value_streak += 1
    v2_selected = [row for row in selected if row["selection"].get("scoreVersion") == "pev-selection-v2"]
    single_task = [row for row in v2_selected if len(row["selection"].get("taskIds") or []) <= 1]
    documented_splits = [
        row
        for row in single_task
        if isinstance((row["selection"].get("fragmentation") or {}).get("splitRationale"), str)
        and len((row["selection"].get("fragmentation") or {})["splitRationale"].strip()) >= 20
    ]
    fragmentation_scores = [
        _number(row["selection"].get("scores", {}).get(FRAGMENTATION_SCORE_KEY)) for row in v2_selected
    ]
    fragmentation_scores = [value for value in fragmentation_scores if value is not None]
    return {
        "recorded": len(selected),
        "firstRecordedCycle": first_recorded_cycle,
        "eligibleCycles": len(eligible),
        "coverage": round(len(selected) / len(eligible), 4) if eligible else None,
        "averageUserValue": round(sum(values) / len(values), 3) if values else None,
        "lowValueStreak": low_value_streak,
        "durationPredictionMaeMin": round(sum(duration_errors) / len(duration_errors), 2) if duration_errors else None,
        "costPredictionMaeUsd": round(sum(cost_errors) / len(cost_errors), 4) if cost_errors else None,
        "testDurationPredictionMaeMin": round(sum(test_duration_errors) / len(test_duration_errors), 2)
        if test_duration_errors
        else None,
        "firstPassBrierScore": round(sum(brier) / len(brier), 4) if brier else None,
        "singleTaskSelections": len(single_task),
        "documentedSplitRationales": len(documented_splits),
        "splitRationaleCoverage": round(len(documented_splits) / len(single_task), 4) if single_task else None,
        "averageFragmentationPenalty": _average(fragmentation_scores),
    }


def aggregate_unit_metrics(cycles: list[dict[str, Any]]) -> dict[str, Any]:
    """Build requirement/task denominators without inflating shared-cycle cost."""
    requirements: dict[str, dict[str, Any]] = {}
    tasks: dict[str, dict[str, Any]] = {}
    requirement_covered = task_covered = 0
    for row in cycles:
        selection = row.get("selection") or {}
        requirement_ids = [str(value) for value in row.get("specIds", []) if value]
        selected_requirement = selection.get("requirement")
        if isinstance(selected_requirement, str) and selected_requirement:
            requirement_ids.append(selected_requirement.upper())
        requirement_ids = list(dict.fromkeys(requirement_ids))
        task_ids = list(dict.fromkeys(str(value) for value in selection.get("taskIds", []) if value))
        requirement_covered += bool(requirement_ids)
        task_covered += bool(task_ids)
        _add_units(requirements, requirement_ids, row)
        _add_units(tasks, task_ids, row)
    requirement_rows = _finish_units(requirements)
    task_rows = _finish_units(tasks)
    amplified = [row for row in requirement_rows if row["cycles"] > 1]
    timed_amplified = [row for row in amplified if row["timedCheckRuns"] > 0]
    fragmented = [
        row
        for row in requirement_rows
        if row["cycles"] > 1
        and ((row["repeatedCheckOverheadSec"] or 0) > 0 or row["additionalCycleVerificationCostUsd"] > 0)
    ]
    return {
        "requirements": requirement_rows,
        "tasks": task_rows,
        "requirementCount": len(requirement_rows),
        "taskCount": len(task_rows),
        "amplifiedRequirements": len(amplified),
        "fragmentedRequirements": len(fragmented),
        "repeatedCheckOverheadSec": round(
            sum(row["repeatedCheckOverheadSec"] or 0 for row in timed_amplified), 3
        )
        if timed_amplified
        else None,
        "fragmentationCheckCoverage": round(len(timed_amplified) / len(amplified), 4) if amplified else None,
        "additionalCycleVerificationCostUsd": round(
            sum(row["additionalCycleVerificationCostUsd"] for row in requirement_rows), 4
        ),
        "averageCyclesPerRequirement": _average([row["cycles"] for row in requirement_rows]),
        "averageCostPerRequirementUsd": _average([row["allocatedCostUsd"] for row in requirement_rows], 4),
        "averageCostPerTaskUsd": _average([row["allocatedCostUsd"] for row in task_rows], 4),
        "coverage": {
            "requirements": round(requirement_covered / len(cycles), 4) if cycles else None,
            "tasks": round(task_covered / len(cycles), 4) if cycles else None,
        },
    }


def _add_units(store: dict[str, dict[str, Any]], ids: list[str], cycle: dict[str, Any]) -> None:
    if not ids:
        return
    allocated_cost = float(cycle.get("costUsd") or 0.0) / len(ids)
    allocated_verification_cost = float((cycle.get("phaseCostsUsd") or {}).get("verification") or 0.0) / len(ids)
    for unit_id in ids:
        item = store.setdefault(
            unit_id,
            {
                "id": unit_id,
                "cycleNumbers": [],
                "allocatedCostUsd": 0.0,
                "verificationCosts": [],
                "checkRuns": [],
                "startedAt": [],
                "endedAt": [],
                "completed": False,
            },
        )
        item["cycleNumbers"].append(cycle["cycle"])
        item["allocatedCostUsd"] += allocated_cost
        item["verificationCosts"].append((cycle["cycle"], allocated_verification_cost))
        for stage in (cycle.get("checks") or {}).get("stages", []):
            duration = _number(stage.get("durationSec"))
            command = stage.get("command")
            if isinstance(command, str) and command and duration is not None:
                item["checkRuns"].append((command, cycle["cycle"], max(0.0, duration) / len(ids)))
        if cycle.get("startedAt"):
            item["startedAt"].append(cycle["startedAt"])
        if cycle.get("finalVerdict") in PASS_VERDICTS:
            item["completed"] = True
            completed_at = cycle.get("mergedAt") or cycle.get("endedAt")
            if completed_at:
                item["endedAt"].append(completed_at)


def _finish_units(store: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for unit_id in sorted(store):
        item = store[unit_id]
        starts = sorted(item.pop("startedAt"))
        ends = sorted(item.pop("endedAt"))
        first_at = starts[0] if starts else None
        last_at = ends[-1] if ends else None
        lead_time = _elapsed(parse_ts(first_at), parse_ts(last_at))
        verification_costs = sorted(item.pop("verificationCosts"))
        additional_verification_cost = sum(value for _, value in verification_costs[1:])
        check_runs = item.pop("checkRuns")
        checks_by_command: dict[str, dict[int, float]] = {}
        for command, cycle, duration in check_runs:
            by_cycle = checks_by_command.setdefault(command, {})
            by_cycle[cycle] = by_cycle.get(cycle, 0.0) + duration
        repeated_check_overhead = 0.0
        repeated_check_executions = 0
        repeated_checks: list[dict[str, Any]] = []
        for command, by_cycle in sorted(checks_by_command.items()):
            ordered = sorted(by_cycle.items())
            if len(ordered) <= 1:
                continue
            overhead = sum(duration for _, duration in ordered[1:])
            repeated_check_overhead += overhead
            repeated_check_executions += len(ordered) - 1
            repeated_checks.append(
                {"command": command, "cycles": len(ordered), "overheadSec": round(overhead, 3)}
            )
        output.append(
            {
                **item,
                "cycleNumbers": sorted(set(item["cycleNumbers"])),
                "cycles": len(set(item["cycleNumbers"])),
                "allocatedCostUsd": round(item["allocatedCostUsd"], 4),
                "firstStartedAt": first_at,
                "lastCompletedAt": last_at,
                "leadTimeSec": lead_time,
                "additionalCycleVerificationCostUsd": round(additional_verification_cost, 4),
                "repeatedCheckExecutions": repeated_check_executions,
                "timedCheckRuns": len(check_runs),
                "repeatedCheckOverheadSec": round(repeated_check_overhead, 3) if check_runs else None,
                "repeatedChecks": repeated_checks,
                "fragmented": len(set(item["cycleNumbers"])) > 1
                and (repeated_check_overhead > 0 or additional_verification_cost > 0),
            }
        )
    return output


def cycle_normalized_metrics(
    git_info: dict[str, Any], phase_costs: dict[str, float], implementation_sec: int | None, verification_sec: int | None
) -> dict[str, Any]:
    lines = int(git_info.get("linesAdded") or 0) + int(git_info.get("linesDeleted") or 0)
    verification_cost = float(phase_costs.get("verification") or 0)
    return {
        "changedLines": lines if git_info.get("commits") else None,
        "verificationCostPerChangedLineUsd": round(verification_cost / lines, 6) if lines else None,
        "verificationToImplementationTimeRatio": round(verification_sec / implementation_sec, 4)
        if verification_sec is not None and implementation_sec
        else None,
    }


def aggregate_intervention_metrics(cycles: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    by_origin: dict[str, int] = {}
    actionable = observations = 0
    handling_sec = 0.0
    for row in cycles:
        metric = row.get("intervention") or {}
        actionable += int(metric.get("total") or 0)
        observations += int(metric.get("observations") or 0)
        handling_sec += float(metric.get("commandHandlingSec") or 0)
        for key, value in (metric.get("byType") or {}).items():
            by_type[key] = by_type.get(key, 0) + int(value)
        for key, value in (metric.get("byOrigin") or {}).items():
            by_origin[key] = by_origin.get(key, 0) + int(value)
    return {
        "actionable": actionable,
        "observations": observations,
        "flowStarts": by_type.get("flow_start", 0),
        "byType": by_type,
        "byOrigin": by_origin,
        "commandHandlingSec": round(handling_sec, 3),
    }


def aggregate_execution_metrics(cycles: list[dict[str, Any]]) -> dict[str, Any]:
    git_rows = [row for row in cycles if (row.get("git") or {}).get("commits")]
    files_changed = sum(int(row["git"].get("filesChanged") or 0) for row in git_rows)
    lines_changed = sum(
        int(row["git"].get("linesAdded") or 0) + int(row["git"].get("linesDeleted") or 0) for row in git_rows
    )
    verification_cost = sum(float((row.get("phaseCostsUsd") or {}).get("verification") or 0) for row in git_rows)
    implementation_sec = sum(
        int(row["phaseDurationSec"]["implementation"])
        for row in cycles
        if (row.get("phaseDurationSec") or {}).get("implementation") is not None
    )
    verification_sec = sum(
        int(row["phaseDurationSec"]["verification"])
        for row in cycles
        if (row.get("phaseDurationSec") or {}).get("verification") is not None
    )
    recorded_checks = sum(int((row.get("checks") or {}).get("recorded") or 0) for row in cycles)
    failed_checks = sum(int((row.get("checks") or {}).get("failed") or 0) for row in cycles)
    unknown_checks = sum(int((row.get("checks") or {}).get("unknownOutcome") or 0) for row in cycles)
    timed_checks = sum(
        1
        for row in cycles
        for stage in (row.get("checks") or {}).get("stages", [])
        if stage.get("durationSec") is not None
    )
    check_duration = sum(float((row.get("checks") or {}).get("durationSec") or 0) for row in cycles)
    failed_stages: dict[str, int] = {}
    for row in cycles:
        for stage in (row.get("checks") or {}).get("failedStages", []):
            command = stage.get("command") or "unknown"
            failed_stages[command] = failed_stages.get(command, 0) + 1
    return {
        "gitCoveredCycles": len(git_rows),
        "filesChanged": files_changed,
        "linesChanged": lines_changed,
        "verificationCostPerChangedLineUsd": round(verification_cost / lines_changed, 6) if lines_changed else None,
        "verificationToImplementationTimeRatio": round(verification_sec / implementation_sec, 4)
        if implementation_sec
        else None,
        "checkDurationSec": round(check_duration, 3),
        "recordedChecks": recorded_checks,
        "failedChecks": failed_checks,
        "unknownOutcomeChecks": unknown_checks,
        "timedChecks": timed_checks,
        "timedCheckCoverage": round(timed_checks / recorded_checks, 4) if recorded_checks else None,
        "failedCheckRate": round(failed_checks / recorded_checks, 4) if recorded_checks else None,
        "failedStages": [{"command": key, "count": value} for key, value in sorted(failed_stages.items())],
    }


def _average(values: list[float | int], digits: int = 3) -> float | None:
    return round(sum(values) / len(values), digits) if values else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute PEV metrics from artifacts + transcripts.")
    parser.add_argument("--root", required=True, help="project root (contains .review/ and logs/)")
    parser.add_argument("--transcripts", help="override transcript directory")
    parser.add_argument("--codex-sessions", help="override Codex sessions directory")
    parser.add_argument("--write", action="store_true", help="write logs/pev-metrics.json instead of stdout")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    tdir = Path(args.transcripts).expanduser().resolve() if args.transcripts else None
    cdir = Path(args.codex_sessions).expanduser().resolve() if args.codex_sessions else None
    result = compute_metrics(root, transcript_dir=tdir, codex_dir=cdir)

    if args.write:
        out = root / "logs" / "pev-metrics.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
