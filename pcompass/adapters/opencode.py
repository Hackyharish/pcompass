"""OpenCode (`opencode.ai`) adapter for Prompt Compass.

Verified against official OpenCode documentation (2026-10-20):
- Skills: https://opencode.ai/docs/skills/
  Discovers `.opencode/skills/<name>/SKILL.md` (project), `~/.config/opencode/skills/<name>/SKILL.md` (global),
  plus `.agents/skills/*/SKILL.md` and `.claude/skills/*/SKILL.md`.
  Supports `metadata: {"opencode/slash": "true", "opencode/autoinvoke": "true"}` in frontmatter.
- MCP Servers: https://opencode.ai/docs/mcp-servers/
  Configured in `opencode.json` / `opencode.jsonc` (project) and `~/.config/opencode/opencode.json` (global)
  under top-level `"mcp"` object. Local servers use `"type": "local"`, `"command": ["pcompass-mcp"]` (array),
  `"enabled": true`, and `"environment": {...}`. Remote servers use `"type": "remote"` and `"url"`.
- Rules: https://opencode.ai/docs/rules/
  Reads `AGENTS.md` (project), `~/.config/opencode/AGENTS.md` (global), and `"instructions": [...]` in `opencode.json`.
- Plugins: https://opencode.ai/docs/plugins/
  OpenCode uses TypeScript/JS plugins in `.opencode/plugins/` rather than shell JSON hooks, so primary
  delivery is Tier 2 (`SKILL.md` with `/prompt-compass` slash support) + Tier 3 (`pcompass-mcp` in `opencode.json`).
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


class OpenCodeAdapter:
    """Adapter for OpenCode CLI, TUI, and IDE (`opencode.ai`)."""

    id = "opencode"

    def __init__(self, project_dir: Path | None = None, home_dir: Path | None = None) -> None:
        self.project_dir = (project_dir or Path.cwd()).resolve()
        self.home_dir = (home_dir or Path.home()).resolve()

    def detect(self) -> bool:
        return (
            (self.project_dir / ".opencode").is_dir()
            or (self.project_dir / "opencode.json").is_file()
            or (self.project_dir / "opencode.jsonc").is_file()
            or (self.home_dir / ".config" / "opencode").is_dir()
            or shutil.which("opencode") is not None
        )

    def paths(self) -> AgentPaths:
        return AgentPaths(
            skills_dirs=[
                self.project_dir / ".opencode" / "skills",
                self.project_dir / ".agents" / "skills",
                self.home_dir / ".config" / "opencode" / "skills",
                self.home_dir / ".agents" / "skills",
            ],
            mcp_configs=[
                self.project_dir / "opencode.json",
                self.project_dir / "opencode.jsonc",
                self.home_dir / ".config" / "opencode" / "opencode.json",
            ],
            rules_files=[
                self.project_dir / "AGENTS.md",
                self.home_dir / ".config" / "opencode" / "AGENTS.md",
            ],
            hook_configs=[
                self.project_dir / "opencode.json",
                self.home_dir / ".config" / "opencode" / "opencode.json",
            ],
        )

    def caps(self) -> AdapterCaps:
        return AdapterCaps(
            can_inject=False,  # Uses TS/JS plugins rather than shell command JSON hooks
            can_rewrite=False,
            can_block=False,
            can_message=False,
            primary_tier=2,  # Tier 2 (.opencode/skills/prompt-compass/SKILL.md) + Tier 3 (opencode.json mcp)
            hook_event="skill+mcp",
        )

    def parse_hook_input(self, raw: dict[str, Any]) -> HookInput:
        return HookInput(
            agent=self.id,
            event_name=str(raw.get("event") or "chat.message"),
            prompt=str(raw.get("prompt") or ""),
            cwd=str(raw.get("cwd") or self.project_dir),
            session_id=str(raw.get("sessionId") or ""),
            raw=raw,
        )

    def render_hook_output(
        self,
        out: RenderedOutput,
        hook_input: HookInput | None = None,
    ) -> dict[str, Any]:
        if out.skipped or not out.context_block:
            return {}
        return {
            "banner": out.banner,
            "additionalContext": out.context_block,
        }

    def _target_paths(self, scope: str) -> tuple[Path, Path]:
        if scope == "user":
            return (
                self.home_dir / ".config" / "opencode" / "opencode.json",
                self.home_dir / ".config" / "opencode" / "skills" / "prompt-compass" / "SKILL.md",
            )
        return (
            self.project_dir / "opencode.json",
            self.project_dir / ".opencode" / "skills" / "prompt-compass" / "SKILL.md",
        )

    def setup(
        self,
        scope: str = "project",
        dry_run: bool = False,
        skill_template_path: Path | None = None,
    ) -> list[Change]:
        cfg_path, skill_dest = self._target_paths(scope)
        changes: list[Change] = []

        # 1. Merge pcompass-mcp into opencode.json under "mcp" (OpenCode schema: type="local", command=["pcompass-mcp"])
        cfg_data = load_json_dict(cfg_path)
        cfg_data.setdefault("$schema", "https://opencode.ai/config.json")
        mcp_obj = cfg_data.setdefault("mcp", {})
        if not isinstance(mcp_obj, dict):
            mcp_obj = {}
            cfg_data["mcp"] = mcp_obj
        if "pcompass" not in mcp_obj:
            mcp_obj["pcompass"] = {
                "type": "local",
                "command": ["pcompass-mcp"],
                "enabled": True,
            }
        changes.append(
            backup_and_write_text(
                cfg_path,
                json.dumps(cfg_data, indent=2) + "\n",
                dry_run=dry_run,
                description="Register pcompass-mcp in OpenCode opencode.json under 'mcp' (Tier 3)",
            )
        )

        # 2. Install SKILL.md with opencode/slash metadata into .opencode/skills/prompt-compass/SKILL.md (Tier 2)
        default_skill_src = (
            skill_template_path
            or Path(__file__).resolve().parents[2] / "skills" / "prompt-compass" / "SKILL.md"
        )
        if default_skill_src.is_file():
            raw_skill = default_skill_src.read_text(encoding="utf-8")
            # Inject OpenCode metadata block in frontmatter if not already present
            if "opencode/slash" not in raw_skill and raw_skill.startswith("---\n"):
                parts = raw_skill.split("---\n", 2)
                if len(parts) == 3:
                    fm_plus = (
                        parts[1].rstrip()
                        + "\ncompatibility: opencode\nmetadata:\n  opencode/slash: \"true\"\n  opencode/autoinvoke: \"true\"\n"
                    )
                    raw_skill = f"---\n{fm_plus}---\n{parts[2]}"
            changes.append(
                backup_and_write_text(
                    skill_dest,
                    raw_skill,
                    dry_run=dry_run,
                    description="Install Prompt Compass SKILL.md for OpenCode (Tier 2 + /prompt-compass TUI command)",
                )
            )
        return changes

    def uninstall(self, scope: str = "project", dry_run: bool = False) -> list[Change]:
        cfg_path, skill_dest = self._target_paths(scope)
        changes: list[Change] = []

        if cfg_path.is_file():
            cfg_data = load_json_dict(cfg_path)
            if isinstance(cfg_data.get("mcp"), dict) and "pcompass" in cfg_data["mcp"]:
                cfg_data["mcp"].pop("pcompass", None)
                if not cfg_data["mcp"]:
                    cfg_data.pop("mcp", None)
                changes.append(
                    backup_and_write_text(
                        cfg_path,
                        json.dumps(cfg_data, indent=2) + "\n",
                        dry_run=dry_run,
                        description="Remove pcompass-mcp from OpenCode opencode.json",
                    )
                )

        if skill_dest.is_file():
            if not dry_run:
                skill_dest.unlink()
            changes.append(
                Change(
                    action="remove",
                    path=str(skill_dest),
                    description="Remove Prompt Compass SKILL.md from OpenCode skills",
                )
            )

        if not changes:
            changes.append(Change(action="noop", path=str(cfg_path), description="Nothing to remove"))
        return changes
