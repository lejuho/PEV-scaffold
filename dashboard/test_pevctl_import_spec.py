#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


PEVCTL_PATH = Path(__file__).resolve().parents[1] / "scripts" / "pevctl.py"
SPEC = importlib.util.spec_from_file_location("pevctl_import_test", PEVCTL_PATH)
assert SPEC and SPEC.loader
pevctl = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pevctl
SPEC.loader.exec_module(pevctl)


class ImportSpecTests(unittest.TestCase):
    def test_creates_non_implementing_planner_handoff_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "specs" / "001-auth"
            spec.mkdir(parents=True)
            (spec / "spec.md").write_text("# Auth\nFR-AUTH-01 signup\n")
            (spec / "plan.md").write_text("# Technical plan\n")
            (spec / "tasks.md").write_text(
                "- [x] T001 schema\n- [ ] T002 endpoint\n- [ ] T003 tests\n"
            )
            args = argparse.Namespace(root=str(root), spec="001-auth", cycle=None)
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                self.assertEqual(pevctl.cmd_import_spec(args), 0)

            output = json.loads(stream.getvalue())
            manifest = json.loads((root / output["manifest"]).read_text())
            request = (root / output["plannerRequest"]).read_text()
            index = json.loads((root / ".review" / "spec-index.json").read_text())
            self.assertEqual(output["cycle"], 1)
            self.assertEqual([task["id"] for task in manifest["openTasks"]], ["T002", "T003"])
            self.assertEqual(manifest["completedTaskIds"], ["T001"])
            self.assertIn("FR-AUTH-01", manifest["requirementIds"])
            self.assertIn("Do not implement code", request)
            self.assertIn("includedTasks", request)
            self.assertEqual(index["specs"]["001-auth"]["imports"][0]["status"], "awaiting_planner")


if __name__ == "__main__":
    unittest.main()
