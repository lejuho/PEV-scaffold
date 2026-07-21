#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


RUNNER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "pev_runner.py"
SPEC = importlib.util.spec_from_file_location("pev_runner_metrics_test", RUNNER_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class TurnTrackerTests(unittest.TestCase):
    def test_busy_to_idle_writes_pair_with_cycle_and_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".review" / "cycle-12").mkdir(parents=True)
            tracker = runner.TurnTracker(runner.RunnerConfig(root=root, driver="tmux"))

            tracker.start("claude", "cycle 구현하라", "tmux")
            tracker.observe("claude", False)
            tracker.observe("claude", True)

            events = [json.loads(line) for line in (root / "logs" / "hermes-events.jsonl").read_text().splitlines()]
            self.assertEqual([row["event"] for row in events], ["agent_turn_started", "agent_turn_finished"])
            self.assertEqual(events[0]["cycle"], 12)
            self.assertEqual(events[0]["action"], "implement")
            self.assertEqual(events[0]["turnId"], events[1]["turnId"])
            self.assertEqual(events[1]["outcome"], "completed")


if __name__ == "__main__":
    unittest.main()
