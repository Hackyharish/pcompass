"""Windsurf / Devin Desktop (Cascade) adapter for Prompt Compass.

Verified against docs.windsurf.com/windsurf/cascade/hooks and docs.devin.ai/desktop/cascade/skills:
Cascade's `pre_user_prompt` hook can only allow (exit 0) or block (exit 2 with stderr); its stdout
is not injected into Cascade's prompt and `show_output` is disabled on `pre_user_prompt`.
Therefore Windsurf defaults to Tier 2 (`.devin/skills/prompt-compass/SKILL.md` or
`.windsurf/skills/prompt-compass/SKILL.md`) + Tier 3 (`pcompass-mcp` in `mcp_config.json`).
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


class WindsurfAdapter:
    """Adapter for Windsurf / Devin Desktop (Cascade)."""

    id = "windsurf"

    def __init__(self, project_dir: Path | None = None, home_dir: Path | None = None) -> None:
        self.project_dir = (project_dir or Path.cwd()).resolve()
        self.home_dir = (home_dir or Path.home()).resolve()

    def detect(self) -> bool:
        return (
            (self.project_dir / ".devin").is_dir()
            or (self.project_dir / ".windsurf").is_dir()
            or (self.project_dir / ".windsurfrules").is_file()
            or (self.home_dir / ".codeium" / "windsurf").is_dir()
            or (self.home_dir / ".config" / "devin").is_dir()
            or shutil.which("windsurf") is not None
        )

    def paths(self) -> AgentPaths:
        return AgentPaths(
            skills_dirs=[
                self.project_dir / ".devin" / "skills",
                self.project_dir / ".windsurf" / "skills",
                self.project_dir / ".agents" / "skills",
                self.home_dir / ".codeium" / "windsurf" / "skills",
                self.home_dir / ".config" / "devin" / "skills",
            ],
            mcp_configs=[
                self.home_dir / ".codeium" / "windsurf" / "mcp_config.json",
                self.home_dir / ".config" / "devin" / "mcp_config.json",
            ],
            rules_files=[
                self.project_dir / ".windsurfrules",
                self.project_dir / "AGENTS.md",
                self.home_dir / ".codeium" / "windsurf" / "memories" / "global_rules.md",
            ],
            hook_configs=[
                self.project_dir / ".devin" / "hooks.json",
                self.project_dir / ".windsurf" / "hooks.json",
                self.home_dir / ".codeium" / "windsurf" / "hooks.json",
            ],
        )

    def caps(self) -> AdapterCaps:
        return AdapterCaps(
            can_inject=False,  # pre_user_prompt stdout is ignored by Cascade
            can_rewrite=False,
            can_block=True,
            can_message=False,  # show_output does not apply to pre_user_prompt
            primary_tier=2,  # Tier 2 (SKILL.md) + Tier 3 (pcompass-mcp)
            hook_event="pre_user_prompt",
        )

    def parse_hook_input(self, raw: dict[str, Any]) -> HookInput:
        tool_info = raw.get("tool_info") if isinstance(raw.get("tool_info"), dict) else {}
        return HookInput(
            agent=self.id,
            event_name=str(raw.get("agent_action_name") or "pre_user_prompt"),
            prompt=str(tool_info.get("user_prompt") or raw.get("prompt") or ""),
            cwd=str(self.project_dir),
            session_id=str(raw.get("trajectory_id") or ""),
            raw=raw,
        )

    def render_hook_output(
        self,
        out: RenderedOutput,
        hook_input: HookInput | None = None,
    ) -> str:
        # Cascade pre_user_prompt ignores stdout on exit 0; return empty string
        return ""

    def _target_paths(self, scope: str) -> tuple[Path, Path]:
        mcp_path = self.home_dir / ".codeium" / "windsurf" / "mcp_config.json"
        if scope == "user":
            skill_dest = self.home_dir / ".codeium" / "windsurf" / "skills" / "prompt-compass" / "SKILL.md"
        else:
            root_folder = ".devin" if (self.project_dir / ".devin").is_dir() else ".windsurf"
            skill_dest = self.project_dir / root_folder / "skills" / "prompt-compass" / "SKILL.md"
        return mcp_path, skill_dest

    def setup(
        self,
        scope: str = "project",
        dry_run: bool = False,
        skill_template_path: Path | None = None,
    ) -> list[Change]:
        mcp_path, skill_dest = self._target_paths(scope)
        changes: list[Change] = []

        # 1. Register pcompass-mcp in Windsurf mcp_config.json (Tier 3)
        mcp_data = load_json_dict(mcp_path)
        servers = mcp_data.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            servers = {}
            mcp_data["mcpServers"] = servers
        if "pcompass" not in servers:
            servers["pcompass"] = {
                "command": "pcompass-mcp",
                "args": [],
            }
        changes.append(
            backup_and_write_text(
                mcp_path,
                json.dumps(mcp_data, indent=2) + "\n",
                dry_run=dry_run,
                description="Register pcompass-mcp in Windsurf mcp_config.json (Tier 3)",
            )
        )

        # 2. Install SKILL.md (Tier 2)
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
                    description="Install Prompt Compass SKILL.md for Windsurf/Cascade (Tier 2)",
                )
            )
        return changes

    def uninstall(self, scope: str = "project", dry_run: bool = False) -> list[Change]:
        mcp_path, skill_dest = self._target_paths(scope)
        changes: list[Change] = []

        if mcp_path.is_file():
            mcp_data = load_json_dict(mcp_path)
            if isinstance(mcp_data.get("mcpServers"), dict) and "pcompass" in mcp_data["mcpServers"]:
                mcp_data["mcpServers"].pop("pcompass", None)
                changes.append(
                    backup_and_write_text(
                        mcp_path,
                        json.dumps(mcp_data, indent=2) + "\n",
                        dry_run=dry_run,
                        description="Remove pcompass-mcp from Windsurf mcp_config.json",
                    )
                )

        if skill_dest.is_file():
            if not dry_run:
                skill_dest.unlink()
            changes.append(
                Change(action="remove", path=str(skill_dest), description="Remove Windsurf Prompt Compass SKILL.md")
            )

        if not changes:
            changes.append(Change(action="noop", path=str(skill_dest), description="Nothing to remove"))
        return changes
