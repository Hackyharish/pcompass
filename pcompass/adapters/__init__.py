"""Registry of coding-agent adapters for Prompt Compass."""

from __future__ import annotations

from pathlib import Path

from pcompass.adapters.antigravity import AntigravityAdapter
from pcompass.adapters.base import Adapter
from pcompass.adapters.claude_code import ClaudeCodeAdapter
from pcompass.adapters.codex import CodexAdapter
from pcompass.adapters.copilot import CopilotAdapter
from pcompass.adapters.cursor import CursorAdapter
from pcompass.adapters.gemini_cli import GeminiCliAdapter
from pcompass.adapters.opencode import OpenCodeAdapter
from pcompass.adapters.windsurf import WindsurfAdapter

ADAPTER_CLASSES = {
    "claude-code": ClaudeCodeAdapter,
    "codex": CodexAdapter,
    "antigravity": AntigravityAdapter,
    "opencode": OpenCodeAdapter,
    "cursor": CursorAdapter,
    "copilot": CopilotAdapter,
    "windsurf": WindsurfAdapter,
    "gemini-cli": GeminiCliAdapter,  # Legacy alias preserved for backward compatibility
}

PRIMARY_ADAPTER_IDS = (
    "claude-code",
    "codex",
    "antigravity",
    "opencode",
    "cursor",
    "copilot",
    "windsurf",
)


def get_adapter(
    agent_id: str,
    project_dir: Path | None = None,
    home_dir: Path | None = None,
) -> Adapter:
    key = agent_id.strip().lower()
    if key == "agy":
        key = "antigravity"
    if key not in ADAPTER_CLASSES:
        raise ValueError(f"Unsupported agent {agent_id!r}. Valid agents: {', '.join(sorted(ADAPTER_CLASSES))}")
    return ADAPTER_CLASSES[key](project_dir=project_dir, home_dir=home_dir)


def get_all_adapters(
    project_dir: Path | None = None,
    home_dir: Path | None = None,
) -> list[Adapter]:
    return [
        ADAPTER_CLASSES[aid](project_dir=project_dir, home_dir=home_dir)
        for aid in PRIMARY_ADAPTER_IDS
    ]
