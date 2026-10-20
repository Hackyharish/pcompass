"""Gemini CLI adapter for Prompt Compass (Verified against geminicli.com/docs/hooks/reference/)."""

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


class GeminiCliAdapter:
    """Adapter for Gemini CLI (`BeforeAgent` hook in `.gemini/settings.json`, timeout in ms)."""

    id = "gemini-cli"

    def __init__(self, project_dir: Path | None = None, home_dir: Path | None = None) -> None:
        self.project_dir = (project_dir or Path.cwd()).resolve()
        self.home_dir = (home_dir or Path.home()).resolve()

    def detect(self) -> bool:
        return (
            (self.project_dir / ".gemini").is_dir()
            or (self.home_dir / ".gemini").is_dir()
            or shutil.which("gemini") is not None
        )

    def paths(self) -> AgentPaths:
        return AgentPaths(
            skills_dirs=[
                self.project_dir / ".agents" / "skills",
                self.project_dir / ".gemini" / "skills",
                self.home_dir / ".agents" / "skills",
                self.home_dir / ".gemini" / "skills",
            ],
            mcp_configs=[
                self.project_dir / ".gemini" / "settings.json",
                self.home_dir / ".gemini" / "settings.json",
            ],
            rules_files=[
                self.project_dir / "GEMINI.md",
                self.home_dir / ".gemini" / "GEMINI.md",
            ],
            hook_configs=[
                self.project_dir / ".gemini" / "settings.json",
                self.home_dir / ".gemini" / "settings.json",
            ],
        )

    def caps(self) -> AdapterCaps:
        return AdapterCaps(
            can_inject=True,
            can_rewrite=False,
            can_block=True,
            can_message=True,
            primary_tier=1,
            hook_event="BeforeAgent",
        )

    def parse_hook_input(self, raw: dict[str, Any]) -> HookInput:
        return HookInput(
            agent=self.id,
            event_name=str(raw.get("hook_event_name") or "BeforeAgent"),
            prompt=str(raw.get("prompt") or ""),
            cwd=str(raw.get("cwd") or self.project_dir),
            session_id=str(raw.get("session_id") or ""),
            raw=raw,
        )

    def render_hook_output(
        self,
        out: RenderedOutput,
        hook_input: HookInput | None = None,
    ) -> dict[str, Any]:
        # Gemini CLI requires strict JSON output on stdout ("Silence is Mandatory")
        if out.skipped or not out.context_block:
            return {"continue": True, "decision": "allow", "suppressOutput": True}
        return {
            "systemMessage": out.banner,
            "suppressOutput": False,
            "continue": True,
            "decision": "allow",
            "hookSpecificOutput": {
                "additionalContext": out.context_block,
            },
        }

    def _target_settings_path(self, scope: str) -> Path:
        if scope == "user":
            return self.home_dir / ".gemini" / "settings.json"
        return self.project_dir / ".gemini" / "settings.json"

    def setup(self, scope: str = "project", dry_run: bool = False) -> list[Change]:
        target = self._target_settings_path(scope)
        data = load_json_dict(target)
        hooks_obj = data.setdefault("hooks", {})
        if not isinstance(hooks_obj, dict):
            hooks_obj = {}
            data["hooks"] = hooks_obj

        ba_list = hooks_obj.setdefault("BeforeAgent", [])
        if not isinstance(ba_list, list):
            ba_list = []
            hooks_obj["BeforeAgent"] = ba_list

        # Note: timeout in Gemini CLI is in milliseconds (1500 ms)
        pcompass_entry = {
            "sequential": False,
            "hooks": [
                {
                    "type": "command",
                    "name": "pcompass",
                    "command": "pcompass hook gemini-cli",
                    "timeout": 1500,
                    "description": "Prompt Compass capability router and brief generator",
                }
            ],
        }

        already_present = False
        for group in ba_list:
            if isinstance(group, dict) and isinstance(group.get("hooks"), list):
                for h in group["hooks"]:
                    if isinstance(h, dict) and (
                        h.get("name") == "pcompass" or "pcompass" in str(h.get("command", ""))
                    ):
                        already_present = True
                        break

        if not already_present:
            ba_list.append(pcompass_entry)

        new_text = json.dumps(data, indent=2) + "\n"
        return [
            backup_and_write_text(
                target,
                new_text,
                dry_run=dry_run,
                description="Register Prompt Compass BeforeAgent hook in Gemini CLI settings.json (timeout=1500ms)",
            )
        ]

    def uninstall(self, scope: str = "project", dry_run: bool = False) -> list[Change]:
        target = self._target_settings_path(scope)
        if not target.is_file():
            return [Change(action="noop", path=str(target), description="settings.json does not exist")]

        data = load_json_dict(target)
        hooks_obj = data.get("hooks")
        if not isinstance(hooks_obj, dict) or not isinstance(hooks_obj.get("BeforeAgent"), list):
            return [Change(action="noop", path=str(target), description="No BeforeAgent hooks present")]

        cleaned_groups: list[Any] = []
        for group in hooks_obj["BeforeAgent"]:
            if isinstance(group, dict) and isinstance(group.get("hooks"), list):
                kept = [
                    h
                    for h in group["hooks"]
                    if not (
                        isinstance(h, dict)
                        and (h.get("name") == "pcompass" or "pcompass" in str(h.get("command", "")))
                    )
                ]
                if kept:
                    new_group = dict(group)
                    new_group["hooks"] = kept
                    cleaned_groups.append(new_group)
            else:
                cleaned_groups.append(group)

        if cleaned_groups:
            hooks_obj["BeforeAgent"] = cleaned_groups
        else:
            hooks_obj.pop("BeforeAgent", None)
        if not hooks_obj:
            data.pop("hooks", None)

        new_text = json.dumps(data, indent=2) + "\n"
        return [
            backup_and_write_text(
                target,
                new_text,
                dry_run=dry_run,
                description="Remove Prompt Compass BeforeAgent hook from Gemini CLI settings.json",
            )
        ]
