"""Google Antigravity (App, Antigravity CLI `agy`, and Antigravity IDE) adapter.

Verified against official Google Antigravity docs (2026-10-20):
- Hooks: https://antigravity.google/docs/hooks/
  Configured in `.agents/hooks.json` (workspace), `~/.gemini/config/hooks.json` (global),
  or `~/.gemini/antigravity-cli/settings.json` (CLI).
  Uses named hook objects mapping to events (`SessionStart`, `PreInvocation`, `PreToolUse`,
  `PostToolUse`, `PostInvocation`, `Stop`). `SessionStart` and `PreInvocation` return
  `{"injectSteps": [{"ephemeralMessage": "<prompt-compass>...</prompt-compass>"}]}`.
- Skills: https://antigravity.google/docs/skills/
  Workspace `.agents/skills/<name>/SKILL.md` (and legacy `.agent/skills/`),
  Global `~/.gemini/config/skills/` and `~/.gemini/antigravity-cli/skills/`.
- MCP: https://antigravity.google/docs/mcp/
  Workspace `.agents/mcp_config.json` and Global `~/.gemini/config/mcp_config.json`
  (`mcpServers` object; remote servers use `serverUrl`).
- Rules: https://antigravity.google/docs/rules/
  Workspace `AGENTS.md`, `GEMINI.md`, `.agents/rules/*.md` (and legacy `.agent/rules/*.md`),
  Global `~/.gemini/AGENTS.md`, `~/.gemini/GEMINI.md`, `~/.gemini/config/rules/*.md`,
  and `~/.gemini/antigravity-cli/rules/*.md`.
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


class AntigravityAdapter:
    """Adapter for Google Antigravity (Antigravity CLI `agy`, App, and IDE)."""

    id = "antigravity"

    def __init__(self, project_dir: Path | None = None, home_dir: Path | None = None) -> None:
        self.project_dir = (project_dir or Path.cwd()).resolve()
        self.home_dir = (home_dir or Path.home()).resolve()

    def detect(self) -> bool:
        return (
            (self.project_dir / ".agents").is_dir()
            or (self.project_dir / ".agent").is_dir()
            or (self.project_dir / "GEMINI.md").is_file()
            or (self.home_dir / ".gemini" / "antigravity-cli").is_dir()
            or (self.home_dir / ".gemini" / "antigravity").is_dir()
            or (self.home_dir / ".gemini" / "config").is_dir()
            or (self.home_dir / ".gemini").is_dir()
            or shutil.which("agy") is not None
            or shutil.which("antigravity") is not None
        )

    def paths(self) -> AgentPaths:
        return AgentPaths(
            skills_dirs=[
                self.project_dir / ".agents" / "skills",
                self.project_dir / ".agent" / "skills",
                self.home_dir / ".gemini" / "config" / "skills",
                self.home_dir / ".gemini" / "antigravity-cli" / "skills",
                self.home_dir / ".gemini" / "antigravity" / "skills",
            ],
            mcp_configs=[
                self.project_dir / ".agents" / "mcp_config.json",
                self.home_dir / ".gemini" / "config" / "mcp_config.json",
                self.home_dir / ".gemini" / "antigravity" / "mcp_config.json",
            ],
            rules_files=[
                self.project_dir / "AGENTS.md",
                self.project_dir / "GEMINI.md",
                self.project_dir / ".agents" / "AGENTS.md",
                self.project_dir / ".agents" / "GEMINI.md",
                self.home_dir / ".gemini" / "AGENTS.md",
                self.home_dir / ".gemini" / "GEMINI.md",
                self.home_dir / ".gemini" / "config" / "AGENTS.md",
                self.home_dir / ".gemini" / "config" / "GEMINI.md",
            ],
            hook_configs=[
                self.project_dir / ".agents" / "hooks.json",
                self.home_dir / ".gemini" / "config" / "hooks.json",
                self.home_dir / ".gemini" / "antigravity-cli" / "settings.json",
            ],
        )

    def caps(self) -> AdapterCaps:
        return AdapterCaps(
            can_inject=True,  # via PreInvocation / SessionStart injectSteps
            can_rewrite=False,
            can_block=True,
            can_message=True,
            primary_tier=1,
            hook_event="PreInvocation",
        )

    def parse_hook_input(self, raw: dict[str, Any]) -> HookInput:
        ws_paths = raw.get("workspacePaths")
        default_cwd = (
            ws_paths[0]
            if isinstance(ws_paths, list) and ws_paths
            else str(raw.get("cwd") or self.project_dir)
        )
        event = str(
            raw.get("hook_event_name")
            or ("PreInvocation" if "invocationNum" in raw else "SessionStart")
        )
        prompt_str = str(raw.get("prompt") or raw.get("userMessage") or "")
        if not prompt_str and isinstance(raw.get("transcriptPath"), str) and raw["transcriptPath"]:
            tp = Path(raw["transcriptPath"]).expanduser()
            if tp.is_file():
                try:
                    tail = tp.read_bytes()[-16384:].decode("utf-8", errors="replace")
                    for line in reversed(tail.splitlines()):
                        if not line.strip():
                            continue
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            for k in ("prompt", "userMessage", "user_prompt", "text", "content"):
                                val = obj.get(k)
                                if isinstance(val, str) and val.strip():
                                    prompt_str = val.strip()
                                    break
                            if prompt_str:
                                break
                except Exception:
                    pass

        return HookInput(
            agent=self.id,
            event_name=event,
            prompt=prompt_str,
            cwd=str(default_cwd),
            session_id=str(raw.get("conversationId") or raw.get("session_id") or ""),
            raw=raw,
        )

    def render_hook_output(
        self,
        out: RenderedOutput,
        hook_input: HookInput | None = None,
    ) -> dict[str, Any]:
        # Only inject on the first invocation of a turn (invocationNum == 0) if present
        if hook_input and isinstance(hook_input.raw.get("invocationNum"), int):
            if int(hook_input.raw["invocationNum"]) > 0:
                return {"injectSteps": []}

        if out.skipped or not out.context_block:
            return {"injectSteps": []}

        return {
            "injectSteps": [
                {
                    "ephemeralMessage": out.context_block,
                }
            ]
        }

    def _target_paths(self, scope: str) -> tuple[Path, Path, Path]:
        if scope == "user":
            return (
                self.home_dir / ".gemini" / "config" / "hooks.json",
                self.home_dir / ".gemini" / "config" / "mcp_config.json",
                self.home_dir / ".gemini" / "config" / "skills" / "prompt-compass" / "SKILL.md",
            )
        return (
            self.project_dir / ".agents" / "hooks.json",
            self.project_dir / ".agents" / "mcp_config.json",
            self.project_dir / ".agents" / "skills" / "prompt-compass" / "SKILL.md",
        )

    def setup(
        self,
        scope: str = "project",
        dry_run: bool = False,
        skill_template_path: Path | None = None,
    ) -> list[Change]:
        hooks_path, mcp_path, skill_dest = self._target_paths(scope)
        changes: list[Change] = []

        # 1. Register PreInvocation & SessionStart hook in .agents/hooks.json (Tier 1)
        hooks_data = load_json_dict(hooks_path)
        if "pcompass" not in hooks_data:
            hooks_data["pcompass"] = {
                "enabled": True,
                "SessionStart": [
                    {
                        "type": "command",
                        "command": "pcompass hook antigravity --event sessionStart",
                        "timeout": 5,
                    }
                ],
                "PreInvocation": [
                    {
                        "type": "command",
                        "command": "pcompass hook antigravity --event PreInvocation",
                        "timeout": 5,
                    }
                ],
            }
        changes.append(
            backup_and_write_text(
                hooks_path,
                json.dumps(hooks_data, indent=2) + "\n",
                dry_run=dry_run,
                description="Register Prompt Compass hooks in Antigravity hooks.json (Tier 1)",
            )
        )

        # 2. Register pcompass-mcp in .agents/mcp_config.json (Tier 3)
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
                description="Register pcompass-mcp in Antigravity mcp_config.json (Tier 3)",
            )
        )

        # 3. Install SKILL.md into .agents/skills/prompt-compass/SKILL.md (Tier 2, auto-exposes /prompt-compass in agy TUI)
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
                    description="Install Prompt Compass SKILL.md for Antigravity (Tier 2 + /prompt-compass slash command)",
                )
            )
        return changes

    def uninstall(self, scope: str = "project", dry_run: bool = False) -> list[Change]:
        hooks_path, mcp_path, skill_dest = self._target_paths(scope)
        changes: list[Change] = []

        if hooks_path.is_file():
            hooks_data = load_json_dict(hooks_path)
            if "pcompass" in hooks_data:
                hooks_data.pop("pcompass", None)
                changes.append(
                    backup_and_write_text(
                        hooks_path,
                        json.dumps(hooks_data, indent=2) + "\n",
                        dry_run=dry_run,
                        description="Remove Prompt Compass hook from Antigravity hooks.json",
                    )
                )

        if mcp_path.is_file():
            mcp_data = load_json_dict(mcp_path)
            if isinstance(mcp_data.get("mcpServers"), dict) and "pcompass" in mcp_data["mcpServers"]:
                mcp_data["mcpServers"].pop("pcompass", None)
                changes.append(
                    backup_and_write_text(
                        mcp_path,
                        json.dumps(mcp_data, indent=2) + "\n",
                        dry_run=dry_run,
                        description="Remove pcompass-mcp from Antigravity mcp_config.json",
                    )
                )

        if skill_dest.is_file():
            if not dry_run:
                skill_dest.unlink()
            changes.append(
                Change(
                    action="remove",
                    path=str(skill_dest),
                    description="Remove Prompt Compass SKILL.md from Antigravity skills",
                )
            )

        if not changes:
            changes.append(Change(action="noop", path=str(hooks_path), description="Nothing to remove"))
        return changes
