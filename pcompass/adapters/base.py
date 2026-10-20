"""Adapter protocol and common data structures for Prompt Compass."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
import json
from pathlib import Path
import shutil
from typing import Any, Protocol

from pcompass.core.render import RenderedOutput


@dataclass(frozen=True)
class AgentPaths:
    """Filesystem locations scanned or configured by an agent adapter."""

    skills_dirs: list[Path] = field(default_factory=list)
    mcp_configs: list[Path] = field(default_factory=list)
    rules_files: list[Path] = field(default_factory=list)
    hook_configs: list[Path] = field(default_factory=list)


@dataclass(frozen=True)
class AdapterCaps:
    """Verified capabilities of an agent's user-prompt submit hook."""

    can_inject: bool
    can_rewrite: bool
    can_block: bool
    can_message: bool
    primary_tier: int  # 1 = Hook, 2 = SKILL.md, 3 = MCP/CLI
    hook_event: str


@dataclass(frozen=True)
class HookInput:
    """Normalized input parsed from an agent's hook stdin payload."""

    agent: str
    event_name: str
    prompt: str
    cwd: str
    session_id: str = ""
    transformed_prompt: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Change:
    """A single file modification performed (or planned) by setup/uninstall."""

    action: str  # "create" | "update" | "remove" | "noop"
    path: str
    backup_path: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Adapter(Protocol):
    """Protocol implemented by all 6 coding-agent adapters."""

    id: str

    def detect(self) -> bool: ...
    def paths(self) -> AgentPaths: ...
    def caps(self) -> AdapterCaps: ...
    def parse_hook_input(self, raw: dict[str, Any]) -> HookInput: ...
    def render_hook_output(self, out: RenderedOutput, hook_input: HookInput | None = None) -> str | dict[str, Any]: ...
    def setup(self, scope: str = "project", dry_run: bool = False) -> list[Change]: ...
    def uninstall(self, scope: str = "project", dry_run: bool = False) -> list[Change]: ...


def backup_and_write_text(target: Path, new_content: str, dry_run: bool, description: str) -> Change:
    """Create a .bak backup before updating an existing config file, or create new."""
    existed = target.is_file()
    if existed:
        old_content = target.read_text(encoding="utf-8", errors="replace")
        if old_content == new_content:
            return Change(action="noop", path=str(target), description="Already up to date")

    backup_str = f"{target}.bak" if existed else ""
    action = "update" if existed else "create"
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        if existed:
            shutil.copy2(target, backup_str)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(new_content, encoding="utf-8")
        tmp.replace(target)

    return Change(
        action=action,
        path=str(target),
        backup_path=backup_str,
        description=description,
    )


def load_json_dict(path: Path) -> dict[str, Any]:
    """Safely load a JSON object from disk, returning {} if missing."""
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}
