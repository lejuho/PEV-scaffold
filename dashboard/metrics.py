#!/usr/bin/env python3
"""PEV metrics calculator.

Pure derivation module: given a project root (with .review/ artifacts and
logs/hermes-events.jsonl) plus the Claude Code transcript directory, it
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
import re
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
DEFAULT_MAX_TRANSCRIPT_BYTES = 50 * 1024 * 1024
INTERVENTION_EVENTS = {"telegram_command", "telegram_callback", "dashboard_command"}

# autonomySec v1 == durationSec. We do NOT model "time from an intervention to
# the next automated action"; the whole cycle span counts as time a human did
# not have to drive, and `interventions` is shown alongside so the reader can
# discount it. Keep this note in sync with the dashboard tooltip.


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
            dones[pass_no] = {"kind": info.get("kind"), "createdAt": created, "path": path}

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

    return {"cycle": num, "dir": cycle_dir, "dones": dones, "reviews": reviews, "earliest_mtime": earliest}


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


def token_cost(tokens: dict[str, int], model: str | None, pricing: dict[str, Any]) -> float:
    models = pricing.get("models", {})
    rate = models.get(model) if model else None
    if not rate:
        rate = models.get("default", {})
    per = lambda key: float(rate.get(key) or 0.0)  # noqa: E731
    return (
        tokens["input"] / 1e6 * per("inputPerMTok")
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
    max_transcript_bytes: int = DEFAULT_MAX_TRANSCRIPT_BYTES,
) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    tags = tags or {}
    pricing = load_pricing()
    events = load_events(root)
    started_events = cycle_started_map(events)

    review_root = root / ".review"
    scans: list[dict[str, Any]] = []
    if review_root.exists():
        for child in review_root.iterdir():
            if child.is_dir() and CYCLE_DIR_RE.match(child.name):
                scans.append(scan_cycle(child, root))
    scans.sort(key=lambda s: s["cycle"])

    # derive per-cycle time windows
    cycles: list[dict[str, Any]] = []
    for idx, s in enumerate(scans):
        num = s["cycle"]
        start = started_events.get(num, s["earliest_mtime"])
        # endedAt: first review whose verdict is a pass verdict
        ended = None
        for n in sorted(s["reviews"]):
            r = s["reviews"][n]
            if r["verdict"] in PASS_VERDICTS and r["mtime"] is not None:
                ended = r["mtime"]
                break
        next_start = None
        if idx + 1 < len(scans):
            nxt = scans[idx + 1]
            next_start = started_events.get(nxt["cycle"], nxt["earliest_mtime"])
        # clamp ended to next cycle start if earlier
        if ended is not None and next_start is not None and next_start < ended:
            ended = next_start
        cycles.append(
            {
                "cycle": num,
                "_start": start,
                "_ended": ended,
                "_next_start": next_start,
                "scan": s,
            }
        )

    # attribution window per cycle: [start, ended or next_start or +inf)
    for c in cycles:
        start = c["_start"]
        upper = c["_ended"] or c["_next_start"]
        c["_attr_lo"] = start
        c["_attr_hi"] = upper  # None means open-ended (active cycle)
        c["tokens"] = empty_tokens()
        c["costUsd"] = 0.0
        c["reworkCostUsd"] = 0.0
        # rework boundary: after pass-001 (implement) done createdAt
        dones = c["scan"]["dones"]
        first = dones.get(1)
        c["_rework_after"] = first["createdAt"] if first else None

    unattributed = empty_tokens()
    unattributed_cost = [0.0]
    skipped: list[str] = []

    tdir = Path(transcript_dir) if transcript_dir else default_transcript_dir(root)
    min_start = min((c["_start"] for c in cycles if c["_start"] is not None), default=None)

    if tdir.exists():
        for path in sorted(tdir.glob("*.jsonl")):
            try:
                st = path.stat()
            except OSError:
                continue
            if st.st_size > max_transcript_bytes:
                skipped.append(path.name)
                continue
            # whole-file skip: mtime before any cycle began => entirely stale
            if min_start is not None and st.st_mtime < min_start:
                continue
            _scan_transcript(path, cycles, pricing, unattributed, unattributed_cost)

    # assemble cycle output
    out_cycles: list[dict[str, Any]] = []
    total_cost = 0.0
    total_rework = 0.0
    autonomy_sec = 0.0
    first_pass_count = 0
    counted = 0
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
        interventions = _count_interventions(events, c["_attr_lo"], c["_attr_hi"])
        blocked_to_fix = _blocked_to_fix(s)
        if duration is not None:
            autonomy_sec += duration
        total_cost += c["costUsd"]
        total_rework += c["reworkCostUsd"]
        if final_verdict is not None:
            counted += 1
            if first_pass:
                first_pass_count += 1
        out_cycles.append(
            {
                "cycle": c["cycle"],
                "startedAt": _to_iso(start),
                "endedAt": _to_iso(ended or c["_next_start"]),
                "durationSec": duration,
                "passes": passes,
                "firstPass": first_pass,
                "finalVerdict": final_verdict,
                "interventions": interventions,
                "autonomySec": duration,
                "blockedToFixSec": blocked_to_fix,
                "tokens": c["tokens"],
                "costUsd": round(c["costUsd"], 4),
                "reworkCostUsd": round(c["reworkCostUsd"], 4),
                "failureTag": tags.get(str(c["cycle"])),
            }
        )

    totals = {
        "cycles": len(out_cycles),
        "firstPassRate": round(first_pass_count / counted, 4) if counted else None,
        "autonomyHours": round(autonomy_sec / 3600, 2),
        "costUsd": round(total_cost, 4),
        "reworkCostUsd": round(total_rework, 4),
        "unattributedTokens": unattributed,
        "unattributedCostUsd": round(unattributed_cost[0], 4),
    }

    return {
        "generatedAt": utc_now(),
        "root": str(root),
        "transcriptDir": str(tdir),
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
) -> None:
    try:
        fh = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return
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
            cost = token_cost(toks, model, pricing)
            target = _cycle_for_ts(cycles, ts)
            if target is None:
                add_tokens(unattributed, toks)
                unattributed_cost[0] += cost
                continue
            add_tokens(target["tokens"], toks)
            target["costUsd"] += cost
            rework_after = target["_rework_after"]
            if rework_after is not None and ts >= rework_after:
                target["reworkCostUsd"] += cost


def _cycle_for_ts(cycles: list[dict[str, Any]], ts: float) -> dict[str, Any] | None:
    for c in cycles:
        lo, hi = c["_attr_lo"], c["_attr_hi"]
        if lo is None:
            continue
        if ts >= lo and (hi is None or ts < hi):
            return c
    return None


def _count_interventions(events: list[dict[str, Any]], lo: float | None, hi: float | None) -> int:
    if lo is None:
        return 0
    count = 0
    for ev in events:
        if ev.get("event") not in INTERVENTION_EVENTS:
            continue
        ts = parse_ts(ev.get("ts"))
        if ts is None:
            continue
        if ts >= lo and (hi is None or ts < hi):
            count += 1
    return count


def _blocked_to_fix(scan: dict[str, Any]) -> int | None:
    reviews, dones = scan["reviews"], scan["dones"]
    for n in sorted(reviews):
        if reviews[n]["verdict"] == "BLOCKED" and reviews[n]["mtime"] is not None:
            fix = dones.get(n + 1)
            if fix and fix["createdAt"] is not None:
                return max(0, int(fix["createdAt"] - reviews[n]["mtime"]))
            return None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute PEV metrics from artifacts + transcripts.")
    parser.add_argument("--root", required=True, help="project root (contains .review/ and logs/)")
    parser.add_argument("--transcripts", help="override transcript directory")
    parser.add_argument("--write", action="store_true", help="write logs/pev-metrics.json instead of stdout")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    tdir = Path(args.transcripts).expanduser().resolve() if args.transcripts else None
    result = compute_metrics(root, tdir)

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
