"""Unit and integration tests for Phase 4 (Cursor, Copilot, Windsurf adapters, MCP server, universal SKILL.md)."""

from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pcompass.adapters.copilot import CopilotAdapter
from pcompass.adapters.antigravity import AntigravityAdapter
from pcompass.adapters.opencode import OpenCodeAdapter
from pcompass.adapters.cursor import CursorAdapter
from pcompass.adapters.windsurf import WindsurfAdapter
from pcompass.cli import main as cli_main
from pcompass.core.index import build_or_load_index
from pcompass.core.render import render_prompt_compass_block
from pcompass.core.restructure import restructure_prompt
from pcompass.core.router import route_prompt
from pcompass.mcp_server.server import handle_jsonrpc_request

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[1]


class TestPhase4IdeAdaptersAndMcpServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = build_or_load_index(
            project_dir=FIXTURES_DIR / "project_dir",
            home_dir=FIXTURES_DIR / "home_dir",
            bin_dirs=[FIXTURES_DIR / "bin_dir"],
            use_cache=False,
        )

    def test_universal_skill_under_500_lines_and_valid_frontmatter(self) -> None:
        skill_md = REPO_ROOT / "skills" / "prompt-compass" / "SKILL.md"
        self.assertTrue(skill_md.is_file())
        lines = skill_md.read_text(encoding="utf-8").splitlines()
        self.assertLess(len(lines), 500)
        self.assertEqual(lines[0].strip(), "---")
        self.assertTrue((REPO_ROOT / "skills" / "prompt-compass" / "references" / "output_schema.md").is_file())
        self.assertTrue((REPO_ROOT / "skills" / "prompt-compass" / "references" / "security_gate.md").is_file())

    def test_cursor_adapter_tier2_tier3_and_session_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "proj"
            home = Path(tmp) / "home"
            (proj / ".cursor").mkdir(parents=True)
            adapter = CursorAdapter(project_dir=proj, home_dir=home)
            self.assertTrue(adapter.detect())
            self.assertFalse(adapter.caps().can_inject)
            self.assertEqual(adapter.caps().primary_tier, 2)

            changes = adapter.setup(scope="project", dry_run=False)
            self.assertEqual(len(changes), 3)
            self.assertTrue((proj / ".cursor" / "mcp.json").is_file())
            self.assertTrue((proj / ".cursor" / "skills" / "prompt-compass" / "SKILL.md").is_file())
            self.assertTrue((proj / ".cursor" / "hooks.json").is_file())

            # Idempotent second setup
            changes2 = adapter.setup(scope="project", dry_run=False)
            self.assertTrue(all(c.action == "noop" for c in changes2))

            # Uninstall cleans up
            adapter.uninstall(scope="project", dry_run=False)
            self.assertFalse((proj / ".cursor" / "skills" / "prompt-compass" / "SKILL.md").is_file())

    def test_copilot_adapter_user_prompt_transformed_and_setup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "proj"
            home = Path(tmp) / "home"
            (proj / ".github").mkdir(parents=True)
            adapter = CopilotAdapter(project_dir=proj, home_dir=home)
            self.assertTrue(adapter.detect())
            self.assertTrue(adapter.caps().can_inject)
            self.assertEqual(adapter.caps().hook_event, "userPromptTransformed")

            adapter.setup(scope="project", dry_run=False)
            self.assertTrue((proj / ".github" / "hooks" / "pcompass.json").is_file())
            self.assertTrue((proj / ".vscode" / "mcp.json").is_file())
            self.assertTrue((proj / ".github" / "skills" / "prompt-compass" / "SKILL.md").is_file())

            h_in = adapter.parse_hook_input({
                "sessionId": "cop-1",
                "cwd": str(proj),
                "prompt": "Debug failing GitHub Actions workflow",
                "transformedPrompt": "Debug failing GitHub Actions workflow",
            })
            brief = restructure_prompt(h_in.prompt, signals=self.index.signals)
            routed = route_prompt(h_in.prompt, self.index, top_k=3)
            rendered = render_prompt_compass_block(brief, routed)
            out_str = adapter.render_hook_output(rendered, h_in)
            self.assertIsInstance(out_str, str)
            out_lines = out_str.strip().splitlines()
            self.assertEqual(len(out_lines), 2)
            progress_obj = json.loads(out_lines[0])
            decision_obj = json.loads(out_lines[1])
            self.assertEqual(progress_obj["type"], "progress")
            self.assertIn("<prompt-compass>", decision_obj["modifiedTransformedPrompt"])

            adapter.uninstall(scope="project", dry_run=False)
            self.assertFalse((proj / ".github" / "hooks" / "pcompass.json").is_file())

    def test_windsurf_adapter_setup_and_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "proj"
            home = Path(tmp) / "home"
            (proj / ".devin").mkdir(parents=True)
            adapter = WindsurfAdapter(project_dir=proj, home_dir=home)
            self.assertTrue(adapter.detect())
            self.assertFalse(adapter.caps().can_inject)

            adapter.setup(scope="project", dry_run=False)
            self.assertTrue((proj / ".devin" / "skills" / "prompt-compass" / "SKILL.md").is_file())
            self.assertTrue((home / ".codeium" / "windsurf" / "mcp_config.json").is_file())

            adapter.uninstall(scope="project", dry_run=False)
            self.assertFalse((proj / ".devin" / "skills" / "prompt-compass" / "SKILL.md").is_file())


    def test_antigravity_adapter_hooks_mcp_and_skills_setup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "proj"
            home = Path(tmp) / "home"
            (proj / ".agents").mkdir(parents=True)
            adapter = AntigravityAdapter(project_dir=proj, home_dir=home)
            self.assertTrue(adapter.detect())
            self.assertTrue(adapter.caps().can_inject)
            self.assertEqual(adapter.caps().hook_event, "PreInvocation")

            changes = adapter.setup(scope="project", dry_run=False)
            self.assertEqual(len(changes), 3)
            self.assertTrue((proj / ".agents" / "hooks.json").is_file())
            self.assertTrue((proj / ".agents" / "mcp_config.json").is_file())
            self.assertTrue((proj / ".agents" / "skills" / "prompt-compass" / "SKILL.md").is_file())

            # Verify PreInvocation injectSteps output contract
            h_in = adapter.parse_hook_input({
                "conversationId": "ag-1",
                "workspacePaths": [str(proj)],
                "invocationNum": 0,
                "prompt": "Audit Kubernetes deployment manifests",
            })
            brief = restructure_prompt(h_in.prompt, signals=self.index.signals)
            routed = route_prompt(h_in.prompt, self.index, top_k=3)
            rendered = render_prompt_compass_block(brief, routed)
            h_out = adapter.render_hook_output(rendered, h_in)
            self.assertIn("injectSteps", h_out)
            self.assertEqual(len(h_out["injectSteps"]), 1)
            self.assertIn("<prompt-compass>", h_out["injectSteps"][0]["ephemeralMessage"])

            adapter.uninstall(scope="project", dry_run=False)
            self.assertFalse((proj / ".agents" / "skills" / "prompt-compass" / "SKILL.md").is_file())

    def test_opencode_adapter_opencode_json_mcp_and_skill_setup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "proj"
            home = Path(tmp) / "home"
            (proj / ".opencode").mkdir(parents=True)
            adapter = OpenCodeAdapter(project_dir=proj, home_dir=home)
            self.assertTrue(adapter.detect())
            self.assertEqual(adapter.caps().primary_tier, 2)

            changes = adapter.setup(scope="project", dry_run=False)
            self.assertEqual(len(changes), 2)
            opencode_json = proj / "opencode.json"
            skill_md = proj / ".opencode" / "skills" / "prompt-compass" / "SKILL.md"
            self.assertTrue(opencode_json.is_file())
            self.assertTrue(skill_md.is_file())

            cfg = json.loads(opencode_json.read_text(encoding="utf-8"))
            self.assertEqual(cfg["mcp"]["pcompass"]["type"], "local")
            self.assertEqual(cfg["mcp"]["pcompass"]["command"], ["pcompass-mcp"])
            self.assertIn("opencode/slash", skill_md.read_text(encoding="utf-8"))

            adapter.uninstall(scope="project", dry_run=False)
            self.assertFalse(skill_md.is_file())

    def test_mcp_server_jsonrpc_tools(self) -> None:
        init_resp = handle_jsonrpc_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(init_resp["result"]["serverInfo"]["name"], "pcompass-mcp")

        list_resp = handle_jsonrpc_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tool_names = {t["name"] for t in list_resp["result"]["tools"]}
        self.assertEqual(tool_names, {"analyze_prompt", "list_capabilities", "recommend", "install_plan"})

        call_resp = handle_jsonrpc_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "analyze_prompt",
                    "arguments": {
                        "prompt": "Extract tables from the attached PDF report",
                        "project_dir": str(FIXTURES_DIR / "project_dir"),
                    },
                },
            },
            default_project_dir=FIXTURES_DIR / "project_dir",
            default_home_dir=FIXTURES_DIR / "home_dir",
        )
        self.assertFalse(call_resp["result"]["isError"])
        analyzed = json.loads(call_resp["result"]["content"][0]["text"])
        self.assertFalse(analyzed["skipped"])
        self.assertIn("<prompt-compass>", analyzed["context_block"])

    def test_hook_fail_open_on_corrupt_stdin(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli_main([
                "hook",
                "--project-dir", str(FIXTURES_DIR / "project_dir"),
                "--home-dir", str(FIXTURES_DIR / "home_dir"),
                "--stdin-json", "{corrupt_json_payload!!!",
                "claude-code",
            ])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
