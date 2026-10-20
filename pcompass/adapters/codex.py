"""OpenAI Codex CLI adapter for Prompt Compass (Verified against learn.chatgpt.com/docs/hooks)."""

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


class CodexAdapter:
    """Adapter for OpenAI Codex CLI (`UserPromptSubmit` in `.codex/hooks.json`)."""

    id = "codex"

    def __init__(self, project_dir: Path | None = None, home_dir: Path | None = None) -> None:
        self.project_dir = (project_dir or Path.cwd()).resolve()
        self.home_dir = (home_dir or Path.home()).resolve()

    def detect(self) -> bool:
        return (
            (self.project_dir / ".codex").is_dir()
            or (self.home_dir / ".codex").is_dir()
            or shutil.which("codex") is not None
        )

    def paths(self) -> AgentPaths:
        return AgentPaths(
            skills_dirs=[
                self.project_dir / ".agents" / "skills",
                self.project_dir / ".codex" / "skills",
                self.home_dir / ".agents" / "skills",
                self.home_dir / ".codex" / "skills",
            ],
            mcp_configs=[
                self.project_dir / ".codex" / "config.toml",
                self.home_dir / ".codex" / "config.toml",
            ],
            rules_files=[
                self.project_dir / "AGENTS.override.md",
                self.project_dir / "AGENTS.md",
                self.home_dir / ".codex" / "AGENTS.override.md",
                self.home_dir / ".codex" / "AGENTS.md",
            ],
            hook_configs=[
                self.project_dir / ".codex" / "hooks.json",
                self.home_dir / ".codex" / "hooks.json",
            ],
        )

    def caps(self) -> AdapterCaps:
        return AdapterCaps(
            can_inject=True,
            can_rewrite=False,
            can_block=True,
            can_message=True,
            primary_tier=1,
            hook_event="UserPromptSubmit",
        )

    def parse_hook_input(self, raw: dict[str, Any]) -> HookInput:
        return HookInput(
            agent=self.id,
            event_name=str(raw.get("hook_event_name") or "UserPromptSubmit"),
            prompt=str(raw.get("prompt") or ""),
            cwd=str(raw.get("cwd") or self.project_dir),
            session_id=str(raw.get("session_id") or ""),
            raw=raw,
        )

    def render_hook_output(
        self,
        out: RenderedOutput,
        hook_input: HookInput | None = None,
    ) -> str | dict[str, Any]:
        if out.skipped or not out.context_block:
            return ""
        return {
            "continue": True,
            "systemMessage": out.banner,
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": out.context_block,
            },
        }

    def _target_hooks_path(self, scope: str) -> Path:
        if scope == "user":
            return self.home_dir / ".codex" / "hooks.json"
        return self.project_dir / ".codex" / "hooks.json"

    def setup(self, scope: str = "project", dry_run: bool = False) -> list[Change]:
        target = self._target_hooks_path(scope)
        data = load_json_dict(target)
        hooks_obj = data.setdefault("hooks", {})
        if not isinstance(hooks_obj, dict):
            hooks_obj = {}
            data["hooks"] = hooks_obj

        ups_list = hooks_obj.setdefault("UserPromptSubmit", [])
        if not isinstance(ups_list, list):
            ups_list = []
            hooks_obj["UserPromptSubmit"] = ups_list

        pcompass_entry = {
            "hooks": [
                {
                    "type": "command",
                    "command": "pcompass hook codex",
                    "timeout": 5,
                    "statusMessage": "Routing prompt with Prompt Compass",
                    "additionalContextLimit": 2500,
                }
            ]
        }

        already_present = False
        for group in ups_list:
            if isinstance(group, dict) and isinstance(group.get("hooks"), list):
                for h in group["hooks"]:
                    if isinstance(h, dict) and "pcompass" in str(h.get("command", "")):
                        already_present = True
                        break

        if not already_present:
            ups_list.append(pcompass_entry)

        new_text = json.dumps(data, indent=2) + "\n"
        return [
            backup_and_write_text(
                target,
                new_text,
                dry_run=dry_run,
                description="Register Prompt Compass UserPromptSubmit hook in Codex hooks.json (approve via /hooks)",
            )
        ]

    def uninstall(self, scope: str = "project", dry_run: bool = False) -> list[Change]:
        target = self._target_hooks_path(scope)
        if not target.is_file():
            return [Change(action="noop", path=str(target), description="hooks.json does not exist")]

        data = load_json_dict(target)
        hooks_obj = data.get("hooks")
        if not isinstance(hooks_obj, dict) or not isinstance(hooks_obj.get("UserPromptSubmit"), list):
            return [Change(action="noop", path=str(target), description="No UserPromptSubmit hooks present")]

        cleaned_groups: list[Any] = []
        for group in hooks_obj["UserPromptSubmit"]:
            if isinstance(group, dict) and isinstance(group.get("hooks"), list):
                kept = [
                    h
                    for h in group["hooks"]
                    if not (isinstance(h, dict) and "pcompass" in str(h.get("command", "")))
                ]
                if kept:
                    new_group = dict(group)
                    new_group["hooks"] = kept
                    cleaned_groups.append(new_group)
            else:
                cleaned_groups.append(group)

        if cleaned_groups:
            hooks_obj["UserPromptSubmit"] = cleaned_groups
        else:
            hooks_obj.pop("UserPromptSubmit", None)
        if not hooks_obj:
            data.pop("hooks", None)

        new_text = json.dumps(data, indent=2) + "\n"
        return [
            backup_and_write_text(
                target,
                new_text,
                dry_run=dry_run,
                description="Remove Prompt Compass UserPromptSubmit hook from Codex hooks.json",
            )
        ]
