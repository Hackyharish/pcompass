"""Skip rules, modes, bypass prefixes, and per-project configuration for Prompt Compass."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
from typing import Any

BYPASS_PREFIXES: tuple[str, ...] = ("*", "/", "#")

CONFIRMATION_PHRASES: frozenset[str] = frozenset({
    "y", "yes", "yep", "yeah", "yup", "ok", "okay", "k", "sure",
    "continue", "go", "go ahead", "proceed", "do it", "looks good",
    "lgtm", "ship it", "approved", "approve", "thanks", "thank you",
    "done", "next", "stop", "cancel", "no", "nope", "quit", "exit",
})

_LOG_OR_CODE_LINE_RE = re.compile(
    r"^(\s*(?:Traceback|File\s+\"|at\s+\S+\s*\(|ERROR[:\s]|WARN(?:ING)?[:\s]|INFO[:\s]|DEBUG[:\s]|"
    r"\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}|diff\s+--git|@@\s+-\d+|"
    r"def\s+\w+|class\s+\w+|function\s+\w+|const\s+\w+|let\s+\w+|import\s+\w+|from\s+\S+\s+import|"
    r"[{}[\];]+$))"
)

_CLEAR_ONE_LINE_ASK_RE = re.compile(
    r"(?i)\b(fix|explain|why\s+is|what\s+causes|resolve|patch|update|refactor)\b"
)


@dataclass
class PolicyConfig:
    """Configuration controlling Prompt Compass behavior per project or environment."""

    mode: str = "suggest"  # "suggest" | "rewrite" | "off"
    max_added_tokens: int = 400
    top_k_routes: int = 5
    min_route_score: float = 1.2
    hook_timeout_ms: int = 1500
    llm_mode: bool = False
    recommend_enabled: bool = True
    disabled_capabilities: list[str] = field(default_factory=list)

    @classmethod
    def load(
        cls,
        project_dir: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> "PolicyConfig":
        environ = env if env is not None else dict(os.environ)
        cfg = cls()

        if project_dir is not None:
            for candidate in (
                project_dir / ".promptcompass" / "config.json",
                project_dir / ".promptcompass.json",
            ):
                if candidate.is_file():
                    try:
                        raw = json.loads(candidate.read_text(encoding="utf-8"))
                        if isinstance(raw, dict):
                            if raw.get("mode") in ("suggest", "rewrite", "off"):
                                cfg.mode = str(raw["mode"])
                            if isinstance(raw.get("max_added_tokens"), int):
                                cfg.max_added_tokens = max(50, min(400, int(raw["max_added_tokens"])))
                            if isinstance(raw.get("top_k_routes"), int):
                                cfg.top_k_routes = max(1, min(5, int(raw["top_k_routes"])))
                            if isinstance(raw.get("min_route_score"), (int, float)):
                                cfg.min_route_score = float(raw["min_route_score"])
                            if isinstance(raw.get("hook_timeout_ms"), int):
                                cfg.hook_timeout_ms = max(100, int(raw["hook_timeout_ms"]))
                            if isinstance(raw.get("recommend_enabled"), bool):
                                cfg.recommend_enabled = raw["recommend_enabled"]
                            if isinstance(raw.get("disabled_capabilities"), list):
                                cfg.disabled_capabilities = [str(x) for x in raw["disabled_capabilities"]]
                    except Exception:
                        pass
                    break

        disable_val = environ.get("PCOMPASS_DISABLE", "").strip().lower()
        if disable_val in ("1", "true", "yes", "on"):
            cfg.mode = "off"

        mode_override = environ.get("PCOMPASS_MODE", "").strip().lower()
        if mode_override in ("suggest", "rewrite", "off"):
            cfg.mode = mode_override

        llm_val = environ.get("PCOMPASS_LLM", "").strip().lower()
        if llm_val in ("on", "1", "true", "yes"):
            cfg.llm_mode = True

        return cfg


@dataclass(frozen=True)
class SkipDecision:
    """Result of evaluating whether a prompt should be skipped untouched."""

    should_skip: bool
    reason: str = ""
    stripped_prompt: str = ""


def evaluate_skip(prompt: str, config: PolicyConfig | None = None) -> SkipDecision:
    """Evaluate precision skip rules so clear/trivial prompts pass through with 0 tokens."""
    cfg = config or PolicyConfig()

    if cfg.mode == "off":
        return SkipDecision(True, "mode_off", prompt)

    if not prompt or not prompt.strip():
        return SkipDecision(True, "empty_prompt", prompt)

    stripped = prompt.strip()

    if stripped.startswith("/"):
        first_token = stripped.split()[0]
        if len(first_token) > 1 and not first_token.startswith("//") and "/" not in first_token[1:]:
            return SkipDecision(True, "slash_command", prompt)

    if stripped.startswith("*"):
        clean = stripped[1:].lstrip()
        return SkipDecision(True, "bypass_prefix_star", clean or prompt)

    if stripped.startswith("#") and not stripped.startswith("##"):
        first_line = stripped.splitlines()[0]
        if len( stripped.splitlines() ) == 1 and len(first_line) < 160:
            return SkipDecision(True, "bypass_prefix_hash", stripped[1:].lstrip() or prompt)

    normalized = re.sub(r"[.!?,;:]+$", "", stripped.lower()).strip()
    if normalized in CONFIRMATION_PHRASES:
        return SkipDecision(True, "short_confirmation", prompt)

    words = stripped.split()
    if len(words) <= 3 and normalized in {
        "yes please", "go for it", "sounds good", "looks good",
        "keep going", "try again", "run it", "commit it",
    }:
        return SkipDecision(True, "short_confirmation", prompt)

    lines = [ln for ln in stripped.splitlines() if ln.strip()]
    if len(lines) >= 5:
        fence_count = sum(1 for ln in lines if ln.strip().startswith("```"))
        code_or_log_lines = sum(1 for ln in lines if _LOG_OR_CODE_LINE_RE.search(ln))
        in_fence = False
        fenced_lines = 0
        non_fenced_lines: list[str] = []
        for ln in lines:
            if ln.strip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                fenced_lines += 1
            else:
                non_fenced_lines.append(ln)

        total_content = max(1, len(lines) - fence_count)
        code_ratio = (code_or_log_lines + fenced_lines) / total_content
        non_log_lines = [ln for ln in non_fenced_lines if not _LOG_OR_CODE_LINE_RE.search(ln)]
        ask_text = " ".join(non_log_lines).strip()
        if code_ratio >= 0.65 and ask_text and len(ask_text) <= 180 and _CLEAR_ONE_LINE_ASK_RE.search(ask_text):
            return SkipDecision(True, "pasted_logs_or_code_with_clear_ask", prompt)

    if len(lines) == 1 and len(words) <= 20 and re.match(r"(?i)^rename\s+`[^`]+`\s+to\s+`[^`]+`\s+in\s+`[^`]+`", stripped):
        return SkipDecision(True, "surgical_rename", prompt)

    return SkipDecision(False, "", prompt)
