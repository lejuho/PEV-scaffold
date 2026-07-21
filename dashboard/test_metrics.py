#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import metrics


class MetricsUsageTests(unittest.TestCase):
    def test_deduplicates_claude_and_adds_codex_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "project"
            claude = base / "claude"
            codex = base / "codex"
            (root / ".review" / "cycle-1").mkdir(parents=True)
            (root / "logs").mkdir()
            claude.mkdir()
            codex.mkdir()
            (root / ".review" / "cycle-1" / "plan.md").write_text("plan\n")
            (root / "logs" / "hermes-events.jsonl").write_text(
                json.dumps({"ts": "2026-01-01T00:00:00Z", "event": "cycle_started", "cycle": 1}) + "\n"
            )

            usage = {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50}
            records = [
                {"timestamp": "2026-01-01T00:00:01Z", "uuid": f"u{i}", "message": {"id": "same-api-message", "model": "claude-sonnet-4-6", "usage": usage}}
                for i in range(2)
            ]
            (claude / "session.jsonl").write_text("".join(json.dumps(row) + "\n" for row in records))

            codex_rows = [
                {"timestamp": "2026-01-01T00:00:00Z", "type": "session_meta", "payload": {"cwd": str(root)}},
                {"timestamp": "2026-01-01T00:00:01Z", "type": "turn_context", "payload": {"model": "gpt-5.6-sol"}},
                {"timestamp": "2026-01-01T00:00:02Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 10}}}},
                {"timestamp": "2026-01-01T00:00:03Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 150, "cached_input_tokens": 120, "output_tokens": 20}}}},
            ]
            (codex / "rollout.jsonl").write_text("".join(json.dumps(row) + "\n" for row in codex_rows))

            result = metrics.compute_metrics(root, transcript_dir=claude, codex_dir=codex)
            cycle = result["cycles"][0]
            self.assertEqual(cycle["agentTokens"]["claude"]["input"], 100)
            self.assertEqual(cycle["agentTokens"]["codex"]["input"], 150)
            self.assertEqual(cycle["tokens"]["input"], 250)
            self.assertGreater(cycle["agentCostsUsd"]["claude"], 0)
            self.assertGreater(cycle["agentCostsUsd"]["codex"], 0)
            self.assertEqual(result["skippedTranscripts"], [])

    def test_event_timeline_phase_costs_and_selection_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "project"
            claude = base / "claude"
            codex = base / "codex"
            cycle = root / ".review" / "cycle-1"
            (cycle / "executor").mkdir(parents=True)
            (root / "logs").mkdir()
            claude.mkdir()
            codex.mkdir()
            (cycle / "plan.md").write_text("Spec: FR-1\n")
            (cycle / "review-v1.md").write_text("## Verdict\nBLOCKED\n")
            (cycle / "review-v2.md").write_text("## Verdict\nREADY_TO_MERGE\n")
            for pass_no, created in ((1, "2026-01-01T00:00:10Z"), (2, "2026-01-01T00:00:30Z")):
                (cycle / "executor" / f"pass-{pass_no:03d}-done.json").write_text(
                    json.dumps({"createdAt": created, "kind": "implement" if pass_no == 1 else "fix"})
                )
            (cycle / "selection.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "scoreVersion": "pev-selection-v1",
                        "cycle": 1,
                        "selectedAt": "2026-01-01T00:00:00Z",
                        "chosen": "T1",
                        "candidates": [
                            {
                                "task": "T1",
                                "requirement": "FR-1",
                                "scores": {"userValue": 5, "changeRisk": 4},
                                "predictions": {"durationMin": 1, "firstPassProbability": 0.25},
                                "total": 10,
                            },
                            {"task": "T2", "scores": {"userValue": 2}, "total": 7},
                        ],
                    }
                )
            )
            events = [
                {"ts": "2026-01-01T00:00:00Z", "event": "cycle_started", "cycle": 1},
                {"ts": "2026-01-01T00:00:10Z", "event": "pass_done", "cycle": 1, "pass": 1},
                {"ts": "2026-01-01T00:00:20Z", "event": "verdict", "cycle": 1, "review": ".review/cycle-1/review-v1.md", "verdict": "BLOCKED"},
                {"ts": "2026-01-01T00:00:30Z", "event": "pass_done", "cycle": 1, "pass": 2},
                {"ts": "2026-01-01T00:00:40Z", "event": "verdict", "cycle": 1, "review": ".review/cycle-1/review-v2.md", "verdict": "READY_TO_MERGE"},
                {"ts": "2026-01-01T00:00:45Z", "event": "state_changed", "cycle": 1, "phase": "merged"},
                {"ts": "2026-01-01T00:00:12Z", "event": "dashboard_command", "cycle": 1, "intervention_type": "guidance"},
            ]
            (root / "logs" / "hermes-events.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in events)
            )
            usage = {"input_tokens": 1000, "output_tokens": 100}
            transcript = [
                {"timestamp": timestamp, "message": {"id": f"m{index}", "model": "claude-sonnet-4-6", "usage": usage}}
                for index, timestamp in enumerate(
                    ("2026-01-01T00:00:05Z", "2026-01-01T00:00:15Z", "2026-01-01T00:00:25Z", "2026-01-01T00:00:42Z")
                )
            ]
            (claude / "session.jsonl").write_text("".join(json.dumps(row) + "\n" for row in transcript))

            result = metrics.compute_metrics(root, transcript_dir=claude, codex_dir=codex)
            row = result["cycles"][0]
            self.assertEqual(row["durationSec"], 40)
            self.assertEqual(row["phaseDurationSec"], {"implementation": 10, "verification": 10, "rework": 20, "merge": 5})
            self.assertEqual(row["blockedToFixSec"], 10)
            self.assertEqual(row["interventions"], 1)
            self.assertGreater(row["phaseCostsUsd"]["implementation"], 0)
            self.assertGreater(row["phaseCostsUsd"]["verification"], 0)
            self.assertGreater(row["phaseCostsUsd"]["rework"], 0)
            self.assertGreater(row["phaseCostsUsd"]["merge"], 0)
            self.assertEqual(row["reworkCostUsd"], row["phaseCostsUsd"]["rework"])
            self.assertEqual(row["selection"]["scoreMargin"], 3)
            self.assertEqual(result["totals"]["selection"]["recorded"], 1)
            self.assertEqual(result["totals"]["selection"]["averageUserValue"], 5)

    def test_first_pass_review_cost_is_not_rework(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "project"
            claude = base / "claude"
            codex = base / "codex"
            cycle = root / ".review" / "cycle-1"
            (cycle / "executor").mkdir(parents=True)
            (root / "logs").mkdir()
            claude.mkdir()
            codex.mkdir()
            (cycle / "plan.md").write_text("plan\n")
            (cycle / "review-v1.md").write_text("## Verdict\nREADY_TO_MERGE\n")
            (cycle / "executor" / "pass-001-done.json").write_text(
                json.dumps({"createdAt": "2026-01-01T00:00:10Z", "kind": "implement"})
            )
            events = [
                {"ts": "2026-01-01T00:00:00Z", "event": "cycle_started", "cycle": 1},
                {"ts": "2026-01-01T00:00:10Z", "event": "pass_done", "cycle": 1, "pass": 1},
                {"ts": "2026-01-01T00:00:20Z", "event": "verdict", "cycle": 1, "verdict": "READY_TO_MERGE"},
            ]
            (root / "logs" / "hermes-events.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in events)
            )
            row = {"timestamp": "2026-01-01T00:00:15Z", "message": {"id": "review", "model": "claude-sonnet-4-6", "usage": {"input_tokens": 1000, "output_tokens": 100}}}
            (claude / "session.jsonl").write_text(json.dumps(row) + "\n")

            result = metrics.compute_metrics(root, transcript_dir=claude, codex_dir=codex)
            self.assertGreater(result["cycles"][0]["phaseCostsUsd"]["verification"], 0)
            self.assertEqual(result["cycles"][0]["reworkCostUsd"], 0)

    def test_turn_intervention_check_and_unit_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, claude, codex = base / "project", base / "claude", base / "codex"
            cycle = root / ".review" / "cycle-1"
            (cycle / "executor").mkdir(parents=True)
            (root / "logs").mkdir()
            claude.mkdir()
            codex.mkdir()
            (cycle / "plan.md").write_text("Spec: FR-CORE-01\n")
            (cycle / "review-v1.md").write_text("## Verdict\nREADY_TO_MERGE\n")
            (cycle / "selection.json").write_text(json.dumps({
                "cycle": 1, "chosen": "T-1", "candidates": [{
                    "task": "T-1", "includedTasks": ["T-1", "T-2"], "requirement": "FR-CORE-01",
                    "scores": {}, "predictions": {},
                }],
            }))
            checks = [
                {"command": "unit", "durationSec": 3.5, "exitCode": 0},
                {"command": "lint", "durationSec": 1.5, "exitCode": 2},
                "legacy check text",
            ]
            (cycle / "executor" / "pass-001-done.json").write_text(json.dumps({
                "createdAt": "2026-01-01T00:00:10Z", "checks": checks,
            }))
            events = [
                {"ts": "2026-01-01T00:00:00Z", "event": "cycle_started", "cycle": 1},
                {"ts": "2026-01-01T00:00:01Z", "event": "agent_turn_started", "cycle": 1, "turnId": "a", "agent": "claude"},
                {"ts": "2026-01-01T00:00:09Z", "event": "agent_turn_finished", "cycle": 1, "turnId": "a", "agent": "claude"},
                {"ts": "2026-01-01T00:00:10Z", "event": "pass_done", "cycle": 1, "pass": 1},
                {"ts": "2026-01-01T00:00:12Z", "event": "dashboard_command", "cycle": 1, "intervention_type": "observation", "origin": "dashboard"},
                {"ts": "2026-01-01T00:00:13Z", "event": "telegram_command", "cycle": 1, "intervention_type": "guidance", "origin": "telegram", "duration_ms": 250},
                {"ts": "2026-01-01T00:00:20Z", "event": "verdict", "cycle": 1, "verdict": "READY_TO_MERGE"},
            ]
            (root / "logs" / "hermes-events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in events))

            result = metrics.compute_metrics(root, transcript_dir=claude, codex_dir=codex)
            row = result["cycles"][0]
            self.assertEqual(result["schemaVersion"], 3)
            self.assertEqual(row["activeAgentSec"], 8)
            self.assertEqual(row["interventions"], 1)
            self.assertEqual(row["intervention"]["observations"], 1)
            self.assertIsNone(row["handsOffElapsedSec"])
            self.assertEqual(row["checks"]["failed"], 1)
            self.assertEqual(row["checks"]["unknownOutcome"], 1)
            self.assertEqual(result["totals"]["execution"]["failedStages"][0]["command"], "lint")
            self.assertEqual(result["totals"]["units"]["requirementCount"], 1)
            self.assertEqual(result["totals"]["units"]["taskCount"], 2)
            self.assertEqual(result["totals"]["interventions"]["byType"], {"observation": 1, "guidance": 1})

    def test_git_timestamps_and_diff_are_durable_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, claude, codex = base / "project", base / "claude", base / "codex"
            cycle = root / ".review" / "cycle-7"
            cycle.mkdir(parents=True)
            (root / "logs").mkdir()
            claude.mkdir()
            codex.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "PEV Test"], cwd=root, check=True)
            (cycle / "plan.md").write_text("Spec: FR-GIT-07\n")
            (root / "feature.txt").write_text("one\n")
            self._git_commit(root, "cycle-7 implement", "2026-01-01T00:00:00Z")
            (root / "feature.txt").write_text("one\ntwo\n")
            (cycle / "review-v1.md").write_text("## Verdict\nREADY_TO_MERGE\n")
            self._git_commit(root, "cycle-7 ready", "2026-01-01T00:10:00Z")
            os.utime(cycle / "review-v1.md", (1900000000, 1900000000))

            result = metrics.compute_metrics(root, transcript_dir=claude, codex_dir=codex)
            row = result["cycles"][0]
            self.assertEqual(row["timingSource"], "git")
            self.assertEqual(row["durationSec"], 600)
            self.assertEqual(row["git"]["commits"], 2)
            self.assertGreaterEqual(row["normalized"]["changedLines"], 2)
            self.assertEqual(result["totals"]["execution"]["gitCoveredCycles"], 1)

    def test_fragmentation_cost_counts_cross_cycle_repeated_checks(self) -> None:
        cycles = []
        for number, duration, verification_cost in ((1, 10, 2.0), (2, 14, 3.0)):
            cycles.append({
                "cycle": number,
                "startedAt": f"2026-01-0{number}T00:00:00Z",
                "endedAt": f"2026-01-0{number}T00:10:00Z",
                "mergedAt": None,
                "finalVerdict": "READY_TO_MERGE",
                "costUsd": 10,
                "phaseCostsUsd": {"verification": verification_cost},
                "specIds": ["FR-CORE-01"],
                "selection": None,
                "checks": {"stages": [{"command": "npm test", "durationSec": duration, "exitCode": 0}]},
            })
        result = metrics.aggregate_unit_metrics(cycles)
        requirement = result["requirements"][0]
        self.assertEqual(requirement["cycles"], 2)
        self.assertEqual(requirement["repeatedCheckExecutions"], 1)
        self.assertEqual(requirement["repeatedCheckOverheadSec"], 14)
        self.assertEqual(requirement["additionalCycleVerificationCostUsd"], 3)
        self.assertTrue(requirement["fragmented"])
        self.assertEqual(result["fragmentedRequirements"], 1)

    @staticmethod
    def _git_commit(root: Path, subject: str, when: str) -> None:
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
        subprocess.run(["git", "commit", "-q", "-m", subject], cwd=root, env=env, check=True)


if __name__ == "__main__":
    unittest.main()
