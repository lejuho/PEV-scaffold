#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


BOT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "hermes-cycle-bot.py"
SPEC = importlib.util.spec_from_file_location("hermes_cycle_bot", BOT_PATH)
assert SPEC and SPEC.loader
bot = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bot
SPEC.loader.exec_module(bot)


class CycleSelectionContractTests(unittest.TestCase):
    def test_flow_launch_is_not_structural_intervention(self) -> None:
        self.assertEqual(bot.classify_intervention("/flow safe"), "flow_start")
        self.assertEqual(bot.classify_intervention("/flow status"), "observation")
        self.assertEqual(bot.classify_intervention("/flow reset"), "override")

    def test_legacy_plan_does_not_require_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cycle = root / ".review" / "cycle-3"
            cycle.mkdir(parents=True)
            (cycle / "plan.md").write_text("Branch: feature/legacy\n")
            self.assertIsNone(bot.validate_selection_artifact(root, 3))

    def test_opted_in_plan_requires_two_candidates_and_chosen_membership(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cycle = root / ".review" / "cycle-4"
            cycle.mkdir(parents=True)
            (cycle / "plan.md").write_text(
                "Branch: feature/scored\nSelection: .review/cycle-4/selection.json\n"
            )
            self.assertIn("missing", bot.validate_selection_artifact(root, 4) or "")
            (cycle / "selection.json").write_text(
                json.dumps(
                    {
                        "cycle": 4,
                        "chosen": "T2",
                        "candidates": [{"task": "T1"}, {"task": "T2"}],
                    }
                )
            )
            self.assertIsNone(bot.validate_selection_artifact(root, 4))

    def test_v2_single_task_same_requirement_requires_split_rationale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cycle = root / ".review" / "cycle-5"
            cycle.mkdir(parents=True)
            (cycle / "plan.md").write_text("Selection: .review/cycle-5/selection.json\n")
            data = {
                "cycle": 5,
                "scoreVersion": "pev-selection-v2",
                "chosen": "T1",
                "candidates": [
                    {
                        "task": "T1",
                        "includedTasks": ["T1"],
                        "requirement": "FR-A-01",
                        "scores": {"fragmentationPenalty": 4},
                        "predictions": {
                            "durationMin": 20, "testDurationMin": 8, "costUsd": 5,
                            "firstPassProbability": 0.8, "filesChanged": 2,
                            "repeatedTestDurationMin": 8, "fixedVerificationCostUsd": 1.5,
                        },
                    },
                    {
                        "task": "T2",
                        "requirement": "FR-A-01",
                        "scores": {"fragmentationPenalty": 2},
                        "predictions": {
                            "durationMin": 30, "testDurationMin": 3, "costUsd": 8,
                            "firstPassProbability": 0.9, "filesChanged": 3,
                            "repeatedTestDurationMin": 3, "fixedVerificationCostUsd": 0.5,
                        },
                    },
                ],
            }
            (cycle / "selection.json").write_text(json.dumps(data))
            self.assertIn("splitRationale", bot.validate_selection_artifact(root, 5) or "")
            data["candidates"][0]["fragmentation"] = {
                "splitRationale": "Separating this migration prevents an irreversible data risk despite rerunning tests."
            }
            (cycle / "selection.json").write_text(json.dumps(data))
            self.assertIsNone(bot.validate_selection_artifact(root, 5))
            data["candidates"][0].pop("fragmentation")
            data["candidates"][1]["requirement"] = "FR-B-01"
            (cycle / "selection.json").write_text(json.dumps(data))
            self.assertIn("test-heavy", bot.validate_selection_artifact(root, 5) or "")


if __name__ == "__main__":
    unittest.main()
