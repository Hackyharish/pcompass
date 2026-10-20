"""Cursor (IDE & CLI) adapter for Prompt Compass (Verified against cursor.com/docs/hooks).

Honest capability note: Cursor's `beforeSubmitPrompt` hook only supports `{continue, user_message}`
and cannot inject `additional_context` per turn (`additional_context` is only supported on
`sessionStart` and `postToolUse`). Therefore Cursor defaults to Tier 2 (Universal SKILL.md in
`.cursor/skills/prompt-compass/SKILL.md`) + Tier 3 (`pcompass-mcp` in `.cursor/mcp.json`), plus
an optional `sessionStart` hook that warms the index and injects a workspace capability summary.
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


class CursorAdapter:
    """Adapter for Cursor IDE & CLI."""

    id = "cursor"

    def __init__(self, project_dir: Path | None = None, home_dir: Path | None = None) -> None:
        self.project_dir = (project_dir or Path.cwd()).resolve()
        self.home_dir = (home_dir or Path.home()).resolve()

    def detect(self) -> bool:
        return (
            (self.project_dir / ".cursor").is_dir()
            or (self.project_dir / ".cursorrules").is_file()
            or (self.home_dir / ".cursor").is_dir()
            or shutil.which("cursor") is not None
        )

    def paths(self) -> AgentPaths:
        return AgentPaths(
            skills_dirs=[
                self.project_dir / ".agents" / "skills",
                self.project_dir / ".cursor" / "skills",
                self.home_dir / ".agents" / "skills",
                self.home_dir / ".cursor" / "skills",
            ],
            mcp_configs=[
                self.project_dir / ".cursor" / "mcp.json",
                self.home_dir / ".cursor" / "mcp.json",
            ],
            rules_files=[
                self.project_dir / ".cursorrules",
                self.project_dir / "AGENTS.md",
            ],
            hook_configs=[
                self.project_dir / ".cursor" / "hooks.json",
                self.home_dir / ".cursor" / "hooks.json",
            ],
        )

    def caps(self) -> AdapterCaps:
        return AdapterCaps(
            can_inject=False,  # beforeSubmitPrompt cannot inject additional_context
            can_rewrite=False,
            can_block=True,
            can_message=False,  # user_message only shown when blocked
            primary_tier=2,  # Tier 2 (SKILL.md) + Tier 3 (pcompass-mcp)
            hook_event="beforeSubmitPrompt",
        )

    def parse_hook_input(self, raw: dict[str, Any]) -> HookInput:
        roots = raw.get("workspace_roots")
        default_cwd = roots[0] if isinstance(roots, list) and roots else str(self.project_dir)
        return HookInput(
            agent=self.id,
            event_name=str(raw.get("hook_event_name") or "beforeSubmitPrompt"),
            prompt=str(raw.get("prompt") or ""),
            cwd=str(default_cwd),
            session_id=str(raw.get("conversation_id") or ""),
            raw=raw,
        )

    def render_hook_output(
        self,
        out: RenderedOutput,
        hook_input: HookInput | None = None,
    ) -> dict[str, Any]:
        event = hook_input.event_name if hook_input else "beforeSubmitPrompt"
        if event == "sessionStart":
            if out.skipped or not out.context_block:
                return {"env": {}}
            return {
                "env": {},
                "additional_context": out.context_block,
            }
        # For beforeSubmitPrompt, always allow continuation (fail-open, non-blocking)
        return {"continue": True}

    def _target_paths(self, scope: str, skill_source: Path | None = None) -> tuple[Path, Path, Path]:
        base = self.home_dir if scope == "user" else self.project_dir
        mcp_path = base / ".cursor" / "mcp.json"
        skill_dest = base / ".cursor" / "skills" / "prompt-compass" / "SKILL.md"
        hooks_path = base / ".cursor" / "hooks.json"
        return mcp_path, skill_dest, hooks_path

    def setup(
        self,
        scope: str = "project",
        dry_run: bool = False,
        skill_template_path: Path | None = None,
    ) -> list[Change]:
        mcp_path, skill_dest, hooks_path = self._target_paths(scope)
        changes: list[Change] = []

        # 1. Merge pcompass-mcp into .cursor/mcp.json (Tier 3)
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
                description="Register pcompass-mcp server in Cursor mcp.json (Tier 3)",
            )
        )

        # 2. Install universal SKILL.md into .cursor/skills/prompt-compass/SKILL.md (Tier 2)
        default_skill_src = (
            skill_template_path
            or Path(__file__).resolve().parents[2] / "skills" / "prompt-compass" / "SKILL.md"
        )
        if default_skill_src.is_file():
            skill_text = default_skill_src.read_text(encoding="utf-8")
            changes.append(
                backup_and_write_text(
                    skill_dest,
                    skill_text,
                    dry_run=dry_run,
                    description="Install Prompt Compass SKILL.md for Cursor (Tier 2)",
                )
            )

        # 3. Register sessionStart warmup hook in .cursor/hooks.json
        hooks_data = load_json_dict(hooks_path)
        hooks_data.setdefault("version", 1)
        h_obj = hooks_data.setdefault("hooks", {})
        if not isinstance(h_obj, dict):
            h_obj = {}
            hooks_data["hooks"] = h_obj
        ss_list = h_obj.setdefault("sessionStart", [])
        if not isinstance(ss_list, list):
            ss_list = []
            h_obj["sessionStart"] = ss_list
        if not any(isinstance(x, dict) and "pcompass" in str(x.get("command", "")) for x in ss_list):
            ss_list.append(
                {
                    "command": "pcompass hook cursor --event sessionStart",
                    "type": "command",
                    "timeout": 5,
                    "failClosed": False,
                }
            )
        changes.append(
            backup_and_write_text(
                hooks_path,
                json.dumps(hooks_data, indent=2) + "\n",
                dry_run=dry_run,
                description="Register sessionStart warmup hook in Cursor hooks.json",
            )
        )
        return changes

    def uninstall(self, scope: str = "project", dry_run: bool = False) -> list[Change]:
        mcp_path, skill_dest, hooks_path = self._target_paths(scope)
        changes: list[Change] = []

        if mcp_path.is_file():
            mcp_data = load_json_dict(mcp_path)
            if isinstance(mcp_data.get("mcpServers"), dict) and "pcompass" in mcp_data["mcpServers"]:
                mcp_data["mcpServers"].pop("pcompass", None)
                if not mcp_data["mcpServers"]:
                    mcp_data.pop("mcpServers", None)
                changes.append(
                    backup_and_write_text(
                        mcp_path,
                        json.dumps(mcp_data, indent=2) + "\n",
                        dry_run=dry_run,
                        description="Remove pcompass-mcp from Cursor mcp.json",
                    )
                )

        if skill_dest.is_file():
            if not dry_run:
                skill_dest.unlink()
            changes.append(
                Change(
                    action="remove",
                    path=str(skill_dest),
                    description="Remove Prompt Compass SKILL.md from Cursor skills",
                )
            )

        if hooks_path.is_file():
            hooks_data = load_json_dict(hooks_path)
            h_obj = hooks_data.get("hooks")
            if isinstance(h_obj, dict) and isinstance(h_obj.get("sessionStart"), list):
                h_obj["sessionStart"] = [
                    x
                    for x in h_obj["sessionStart"]
                    if not (isinstance(x, dict) and "pcompass" in str(x.get("command", "")))
                ]
                if not h_obj["sessionStart"]:
                    h_obj.pop("sessionStart", None)
                changes.append(
                    backup_and_write_text(
                        hooks_path,
                        json.dumps(hooks_data, indent=2) + "\n",
                        dry_run=dry_run,
                        description="Remove Prompt Compass sessionStart hook from Cursor hooks.json",
                    )
                )

        if not changes:
            changes.append(Change(action="noop", path=str(mcp_path), description="Nothing to remove"))
        return changes
