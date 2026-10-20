"""Contract, setup/uninstall idempotency, and fail-open tests for Phase 3 CLI adapters."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pcompass.adapters.claude_code import ClaudeCodeAdapter
from pcompass.adapters.codex import CodexAdapter
from pcompass.adapters.gemini_cli import GeminiCliAdapter
from pcompass.core.index import build_or_load_index
from pcompass.core.render import render_prompt_compass_block
from pcompass.core.restructure import restructure_prompt
from pcompass.core.router import route_prompt

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class TestPhase3CliAdapters(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = build_or_load_index(
            project_dir=FIXTURES_DIR / "project_dir",
            home_dir=FIXTURES_DIR / "home_dir",
            bin_dirs=[FIXTURES_DIR / "bin_dir"],
            use_cache=False,
        )

    def _make_rendered(self, prompt: str):
        brief = restructure_prompt(prompt, signals=self.index.signals)
        routed = route_prompt(prompt, self.index, top_k=5)
        return render_prompt_compass_block(brief, routed)

    def test_claude_code_contract_and_idempotent_setup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "proj"
            home = Path(tmp) / "home"
            (proj / ".claude").mkdir(parents=True)
            settings_path = proj / ".claude" / "settings.json"
            settings_path.write_text(json.dumps({"theme": "dark"}, indent=2), encoding="utf-8")

            adapter = ClaudeCodeAdapter(project_dir=proj, home_dir=home)
            self.assertTrue(adapter.detect())
            self.assertTrue(adapter.caps().can_inject)
            self.assertFalse(adapter.caps().can_rewrite)

            # Dry run does not modify file
            dry_changes = adapter.setup(scope="project", dry_run=True)
            self.assertEqual(dry_changes[0].action, "update")
            self.assertNotIn("UserPromptSubmit", settings_path.read_text(encoding="utf-8"))

            # Real setup creates .bak and merges JSON preserving "theme": "dark"
            changes1 = adapter.setup(scope="project", dry_run=False)
            self.assertEqual(changes1[0].action, "update")
            self.assertTrue(Path(changes1[0].backup_path).is_file())
            merged = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(merged["theme"], "dark")
            self.assertEqual(len(merged["hooks"]["UserPromptSubmit"]), 1)

            # Second setup is a no-op (idempotent)
            changes2 = adapter.setup(scope="project", dry_run=False)
            self.assertEqual(changes2[0].action, "noop")

            # Hook input/output contract check
            h_in = adapter.parse_hook_input({
                "session_id": "s1",
                "cwd": str(proj),
                "hook_event_name": "UserPromptSubmit",
                "prompt": "Extract tables from the quarterly PDF invoice",
            })
            rendered = self._make_rendered(h_in.prompt)
            h_out = adapter.render_hook_output(rendered, h_in)
            self.assertIsInstance(h_out, dict)
            self.assertIn("systemMessage", h_out)
            self.assertEqual(h_out["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
            self.assertIn("<prompt-compass>", h_out["hookSpecificOutput"]["additionalContext"])

            # Uninstall removes only pcompass hook and preserves "theme": "dark"
            u_changes = adapter.uninstall(scope="project", dry_run=False)
            self.assertEqual(u_changes[0].action, "update")
            after_uninstall = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(after_uninstall, {"theme": "dark"})

    def test_codex_contract_and_idempotent_setup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "proj"
            home = Path(tmp) / "home"
            (proj / ".codex").mkdir(parents=True)
            adapter = CodexAdapter(project_dir=proj, home_dir=home)
            self.assertTrue(adapter.detect())

            changes1 = adapter.setup(scope="project", dry_run=False)
            self.assertEqual(changes1[0].action, "create")
            hooks_file = proj / ".codex" / "hooks.json"
            data = json.loads(hooks_file.read_text(encoding="utf-8"))
            hook_def = data["hooks"]["UserPromptSubmit"][0]["hooks"][0]
            self.assertEqual(hook_def["additionalContextLimit"], 2500)

            changes2 = adapter.setup(scope="project", dry_run=False)
            self.assertEqual(changes2[0].action, "noop")

            rendered = self._make_rendered("Write a Playwright test for login")
            h_out = adapter.render_hook_output(rendered)
            self.assertTrue(h_out["continue"])
            self.assertEqual(h_out["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")

            adapter.uninstall(scope="project", dry_run=False)
            self.assertEqual(json.loads(hooks_file.read_text(encoding="utf-8")), {})

    def test_gemini_cli_contract_and_strict_json_silence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "proj"
            home = Path(tmp) / "home"
            (proj / ".gemini").mkdir(parents=True)
            adapter = GeminiCliAdapter(project_dir=proj, home_dir=home)
            self.assertTrue(adapter.detect())
            self.assertEqual(adapter.caps().hook_event, "BeforeAgent")

            adapter.setup(scope="project", dry_run=False)
            settings_file = proj / ".gemini" / "settings.json"
            data = json.loads(settings_file.read_text(encoding="utf-8"))
            hook_def = data["hooks"]["BeforeAgent"][0]["hooks"][0]
            self.assertEqual(hook_def["timeout"], 1500)

            rendered = self._make_rendered("Audit Kubernetes manifests in k8s/")
            h_out = adapter.render_hook_output(rendered)
            self.assertEqual(h_out["decision"], "allow")
            self.assertTrue(h_out["continue"])
            self.assertIn("additionalContext", h_out["hookSpecificOutput"])


if __name__ == "__main__":
    unittest.main()
