"""GitHub Copilot (CLI/SDK & VS Code) adapter for Prompt Compass.

Verified against docs.github.com/en/copilot/reference/hooks-reference and
code.visualstudio.com/docs/agents/reference/hooks-reference:
- Copilot CLI/SDK drops `modifiedPrompt` on `userPromptSubmitted` command hooks,
  but honors `modifiedTransformedPrompt` on `userPromptTransformed` (preserving the
  user's visible timeline while appending `<prompt-compass>` to model-facing content).
- VS Code Local Harness `UserPromptSubmit` does not inject context, so setup also
  configures Tier 2 (`.github/skills/prompt-compass/SKILL.md`) and Tier 3 (`.vscode/mcp.json`).
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any

from pcompass.adapters.base import (
    AdapterCaps,
    AgentPaths,
    Change,
    HookInput,
    backup_and_write_text,
    load_json_dict,
)
from pcompass.core.render import RenderedOutput


class CopilotAdapter:
    """Adapter for GitHub Copilot CLI and VS Code."""

    id = "copilot"

    def __init__(self, project_dir: Path | None = None, home_dir: Path | None = None) -> None:
        self.project_dir = (project_dir or Path.cwd()).resolve()
        self.home_dir = (home_dir or Path.home()).resolve()

    def detect(self) -> bool:
        return (
            (self.project_dir / ".github").is_dir()
            or (self.project_dir / ".vscode").is_dir()
            or (self.home_dir / ".copilot").is_dir()
            or shutil.which("github-copilot-cli") is not None
        )

    def paths(self) -> AgentPaths:
        return AgentPaths(
            skills_dirs=[
                self.project_dir / ".github" / "skills",
                self.project_dir / ".agents" / "skills",
                self.home_dir / ".copilot" / "skills",
                self.home_dir / ".agents" / "skills",
            ],
            mcp_configs=[
                self.project_dir / ".vscode" / "mcp.json",
                self.project_dir / ".mcp.json",
                self.home_dir / ".copilot" / "mcp-config.json",
                self.home_dir / ".config" / "Code" / "User" / "mcp.json",
            ],
            rules_files=[
                self.project_dir / ".github" / "copilot-instructions.md",
                self.home_dir / ".copilot" / "copilot-instructions.md",
                self.project_dir / "AGENTS.md",
            ],
            hook_configs=[
                self.project_dir / ".github" / "hooks" / "pcompass.json",
                self.home_dir / ".copilot" / "hooks" / "pcompass.json",
            ],
        )

    def caps(self) -> AdapterCaps:
        return AdapterCaps(
            can_inject=True,  # via userPromptTransformed on Copilot CLI/SDK harness
            can_rewrite=True,  # modifiedTransformedPrompt on userPromptTransformed
            can_block=False,  # exit 2 on prompt hooks is warning-only in Copilot CLI
            can_message=True,  # progress JSON line / systemMessage
            primary_tier=1,  # Tier 1 on CLI/SDK + Tier 2/3 on VS Code Local
            hook_event="userPromptTransformed",
        )

    def parse_hook_input(self, raw: dict[str, Any]) -> HookInput:
        event = str(
            raw.get("hook_event_name")
            or ("userPromptTransformed" if "transformedPrompt" in raw else "userPromptSubmitted")
        )
        return HookInput(
            agent=self.id,
            event_name=event,
            prompt=str(raw.get("prompt") or ""),
            cwd=str(raw.get("cwd") or self.project_dir),
            session_id=str(raw.get("sessionId") or raw.get("session_id") or ""),
            transformed_prompt=str(raw.get("transformedPrompt") or raw.get("prompt") or ""),
            raw=raw,
        )

    def render_hook_output(
        self,
        out: RenderedOutput,
        hook_input: HookInput | None = None,
    ) -> str | dict[str, Any]:
        if out.skipped or not out.context_block:
            return {}
        event = hook_input.event_name if hook_input else "userPromptTransformed"
        if event == "UserPromptSubmit":
            # VS Code Local Harness common output
            return {
                "continue": True,
                "systemMessage": out.banner,
            }
        base_prompt = (
            hook_input.transformed_prompt
            if (hook_input and hook_input.transformed_prompt)
            else out.original_prompt
        )
        progress_line = json.dumps(
            {"type": "progress", "message": out.banner, "temporary": True}
        )
        decision_line = json.dumps(
            {"modifiedTransformedPrompt": f"{base_prompt}\n\n{out.context_block}"}
        )
        return f"{progress_line}\n{decision_line}"

    def _target_paths(self, scope: str) -> tuple[Path, Path, Path]:
        if scope == "user":
            return (
                self.home_dir / ".copilot" / "hooks" / "pcompass.json",
                self.home_dir / ".copilot" / "mcp-config.json",
                self.home_dir / ".copilot" / "skills" / "prompt-compass" / "SKILL.md",
            )
        return (
            self.project_dir / ".github" / "hooks" / "pcompass.json",
            self.project_dir / ".vscode" / "mcp.json",
            self.project_dir / ".github" / "skills" / "prompt-compass" / "SKILL.md",
        )

    def setup(
        self,
        scope: str = "project",
        dry_run: bool = False,
        skill_template_path: Path | None = None,
    ) -> list[Change]:
        hook_path, mcp_path, skill_dest = self._target_paths(scope)
        changes: list[Change] = []

        # 1. Hook file (.github/hooks/pcompass.json)
        hook_data = load_json_dict(hook_path)
        hook_data["version"] = 1
        h_obj = hook_data.setdefault("hooks", {})
        if not isinstance(h_obj, dict):
            h_obj = {}
            hook_data["hooks"] = h_obj
        upt = h_obj.setdefault("userPromptTransformed", [])
        if not isinstance(upt, list):
            upt = []
            h_obj["userPromptTransformed"] = upt
        if not any(isinstance(x, dict) and "pcompass" in str(x.get("command", "")) for x in upt):
            upt.append(
                {
                    "type": "command",
                    "command": "pcompass hook copilot",
                    "timeoutSec": 5,
                }
            )
        changes.append(
            backup_and_write_text(
                hook_path,
                json.dumps(hook_data, indent=2) + "\n",
                dry_run=dry_run,
                description="Register userPromptTransformed hook for GitHub Copilot (Tier 1)",
            )
        )

        # 2. MCP config (.vscode/mcp.json uses top-level "servers"; ~/.copilot/mcp-config.json uses "mcpServers")
        mcp_data = load_json_dict(mcp_path)
        top_key = "mcpServers" if scope == "user" else "servers"
        servers = mcp_data.setdefault(top_key, {})
        if not isinstance(servers, dict):
            servers = {}
            mcp_data[top_key] = servers
        if "pcompass" not in servers:
            servers["pcompass"] = {
                "type": "stdio",
                "command": "pcompass-mcp",
                "args": [],
            }
        changes.append(
            backup_and_write_text(
                mcp_path,
                json.dumps(mcp_data, indent=2) + "\n",
                dry_run=dry_run,
                description=f"Register pcompass-mcp in {mcp_path.name} (Tier 3)",
            )
        )

        # 3. Universal SKILL.md (Tier 2)
        default_skill_src = (
            skill_template_path
            or Path(__file__).resolve().parents[2] / "skills" / "prompt-compass" / "SKILL.md"
        )
        if default_skill_src.is_file():
            changes.append(
                backup_and_write_text(
                    skill_dest,
                    default_skill_src.read_text(encoding="utf-8"),
                    dry_run=dry_run,
                    description="Install Prompt Compass SKILL.md for GitHub Copilot (Tier 2)",
                )
            )
        return changes

    def uninstall(self, scope: str = "project", dry_run: bool = False) -> list[Change]:
        hook_path, mcp_path, skill_dest = self._target_paths(scope)
        changes: list[Change] = []

        if hook_path.is_file():
            if not dry_run:
                hook_path.unlink()
            changes.append(
                Change(action="remove", path=str(hook_path), description="Remove Copilot pcompass hook file")
            )

        if mcp_path.is_file():
            mcp_data = load_json_dict(mcp_path)
            top_key = "mcpServers" if scope == "user" else "servers"
            if isinstance(mcp_data.get(top_key), dict) and "pcompass" in mcp_data[top_key]:
                mcp_data[top_key].pop("pcompass", None)
                changes.append(
                    backup_and_write_text(
                        mcp_path,
                        json.dumps(mcp_data, indent=2) + "\n",
                        dry_run=dry_run,
                        description=f"Remove pcompass-mcp from {mcp_path.name}",
                    )
                )

        if skill_dest.is_file():
            if not dry_run:
                skill_dest.unlink()
            changes.append(
                Change(action="remove", path=str(skill_dest), description="Remove Copilot Prompt Compass SKILL.md")
            )

        if not changes:
            changes.append(Change(action="noop", path=str(hook_path), description="Nothing to remove"))
        return changes
