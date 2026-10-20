"""End-to-end tests for Phase 6 (CLI subcommands, doctor, setup, open-source hygiene, docs)."""

from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pcompass.cli import main as cli_main

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class TestPhase6EndToEndAndHygiene(unittest.TestCase):
    def test_required_open_source_and_documentation_files_exist(self) -> None:
        required = [
            "README.md",
            "LICENSE",
            "NOTICE",
            "CONTRIBUTING.md",
            "CODE_OF_CONDUCT.md",
            "SECURITY.md",
            "CHANGELOG.md",
            "pyproject.toml",
            "docs/COMPATIBILITY.md",
            "docs/PRIOR_ART.md",
            "docs/POSITIONING.md",
            "docs/DECISIONS.md",
            "docs/ADAPTERS.md",
            "docs/SECURITY_MODEL.md",
            "docs/CONFIGURATION.md",
            ".github/workflows/ci.yml",
            ".github/ISSUE_TEMPLATE/bug_report.md",
            ".github/ISSUE_TEMPLATE/adapter_request.md",
            ".github/PULL_REQUEST_TEMPLATE.md",
            "skills/prompt-compass/SKILL.md",
            "evals/prompts.jsonl",
            "evals/runner.py",
        ]
        for rel in required:
            p = REPO_ROOT / rel
            self.assertTrue(p.is_file(), f"Missing required repo file: {rel}")

    def test_cli_doctor_brief_recommend_setup_and_audit(self) -> None:
        # 1. doctor --json
        buf_doc = io.StringIO()
        with redirect_stdout(buf_doc):
            rc = cli_main([
                "doctor",
                "--project-dir", str(FIXTURES_DIR / "project_dir"),
                "--home-dir", str(FIXTURES_DIR / "home_dir"),
                "--bin-dir", str(FIXTURES_DIR / "bin_dir"),
                "--no-cache",
                "--json",
            ])
        self.assertEqual(rc, 0)
        doc_data = json.loads(buf_doc.getvalue())
        self.assertEqual(len(doc_data["adapters"]), 7)
        adapter_ids = {a["agent"] for a in doc_data["adapters"]}
        self.assertIn("antigravity", adapter_ids)
        self.assertIn("opencode", adapter_ids)

        # 2. brief --json
        buf_brief = io.StringIO()
        with redirect_stdout(buf_brief):
            rc = cli_main([
                "brief",
                "--project-dir", str(FIXTURES_DIR / "project_dir"),
                "--home-dir", str(FIXTURES_DIR / "home_dir"),
                "--bin-dir", str(FIXTURES_DIR / "bin_dir"),
                "--no-cache",
                "--json",
                "Audit our Kubernetes deployment manifests and Helm charts",
            ])
        self.assertEqual(rc, 0)
        brief_data = json.loads(buf_brief.getvalue())
        self.assertFalse(brief_data["skipped"])
        self.assertLessEqual(brief_data["added_tokens_estimate"], 400)

        # 3. recommend --json
        buf_rec = io.StringIO()
        with redirect_stdout(buf_rec):
            rc = cli_main([
                "recommend",
                "--project-dir", str(FIXTURES_DIR / "project_dir"),
                "--home-dir", str(FIXTURES_DIR / "home_dir"),
                "--no-cache",
                "--json",
                "Inspect Redis cache TTLs and Stripe payment webhooks",
            ])
        self.assertEqual(rc, 0)
        rec_data = json.loads(buf_rec.getvalue())
        rec_ids = [r["candidate"]["id"] for r in rec_data["recommendations"]]
        self.assertIn("mcp:registry:redis", rec_ids)
        self.assertIn("mcp:registry:stripe", rec_ids)

        # 4. setup --dry-run --json across all detected agents in a temp workspace
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "proj"
            home = Path(tmp) / "home"
            (proj / ".claude").mkdir(parents=True)
            (proj / ".cursor").mkdir(parents=True)
            home.mkdir(parents=True)

            buf_setup = io.StringIO()
            with redirect_stdout(buf_setup):
                rc = cli_main([
                    "setup",
                    "--project-dir", str(proj),
                    "--home-dir", str(home),
                    "--dry-run",
                    "--json",
                ])
            self.assertEqual(rc, 0)
            setup_data = json.loads(buf_setup.getvalue())
            self.assertTrue(setup_data["dry_run"])
            self.assertGreaterEqual(len(setup_data["changes"]), 2)


if __name__ == "__main__":
    unittest.main()
