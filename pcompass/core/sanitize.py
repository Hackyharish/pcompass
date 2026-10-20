"""Untrusted text sanitization and secret redaction for Prompt Compass.

Skill and MCP descriptions come from third parties and may contain indirect
prompt injection, fake XML closing tags, zero-width/bidi characters, or
accidental secret values. This module sanitizes untrusted text and strips
secrets at parse time.
"""

from __future__ import annotations

import re
from typing import Any

# Zero-width, bidirectional override, and ASCII control characters (excluding \t, \n)
_CONTROL_AND_BIDI_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f"
    r"\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]"
)

# XML / HTML tags (especially closing tags like </prompt-compass>, </system-reminder>)
_XML_TAG_RE = re.compile(r"</?[a-zA-Z_][a-zA-Z0-9_.:-]*(\s+[^>]*)?>")

# Prompt-injection and imperative system override patterns
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)\b(curl|wget)\s+\S+\s*\|\s*(?:ba|z)?sh\b"),
    re.compile(r"(?i)\bignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|rules|directions)\b(?:\s+and\s+[^;\n]+|[^.;\n]*)"),
    re.compile(r"(?i)\bdisregard\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|rules)\b(?:\s+and\s+[^;\n]+|[^.;\n]*)"),
    re.compile(r"(?i)\b(system\s+prompt|system\s+override|developer\s+message|new\s+instructions|important\s+instruction)\s*:[^\n]*"),
    re.compile(r"(?i)\byou\s+are\s+now\s+[^.\n]+"),
    re.compile(r"(?i)\b(always|must|never)\s+(run|execute|call|obey|fetch|download|curl|wget)\b[^.\n]*"),
    re.compile(r"(?i)\bdo\s+not\s+(tell|inform|mention\s+to)\s+the\s+user\b[^.\n]*"),
    re.compile(r"(?i)\bbase64\s+(-d|--decode)\b[^\n]*"),
    re.compile(r"(?i)\beval\s*\([^)]*\)"),
]

# Secret / token patterns in strings (CLI args, URLs, descriptions)
_SECRET_VALUE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[A-Za-z0-9._\-+/=]{8,}"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret|password|passwd|client[_-]?secret|access[_-]?key|auth[_-]?token)\s*[:=]\s*['\"]?)([^\s'\",;]{6,})"),
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\b(sk-(?:proj-|ant-|live-|test-)?[A-Za-z0-9_\-]{16,})\b"),
    re.compile(r"\b(xox[baprs]-[A-Za-z0-9\-]{10,})\b"),
    re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
    re.compile(r"\b(AIza[0-9A-Za-z_\-]{30,})\b"),
    re.compile(r"\b(npm_[A-Za-z0-9]{20,}|pypi-[A-Za-z0-9_\-]{20,})\b"),
    re.compile(r"(https?://[^/\s:@]+:)([^@\s/]+)(@)"),
    re.compile(r"(?i)([?&](?:api[_-]?key|token|secret|key|access_token)=)([^&\s]+)"),
]


def redact_secrets(text: str) -> str:
    """Redact API keys, tokens, bearer headers, and URL credentials from text."""
    if not text:
        return ""
    out = text
    out = _SECRET_VALUE_PATTERNS[0].sub(r"\1<REDACTED>", out)

    def _replace_kv(match: re.Match[str]) -> str:
        prefix, val = match.group(1), match.group(2)
        if val.startswith("$") or val.startswith("${") or val == "<REDACTED>":
            return match.group(0)
        return f"{prefix}<REDACTED>"

    out = _SECRET_VALUE_PATTERNS[1].sub(_replace_kv, out)
    for pat in _SECRET_VALUE_PATTERNS[2:8]:
        out = pat.sub("<REDACTED>", out)
    out = _SECRET_VALUE_PATTERNS[8].sub(r"\1<REDACTED>\3", out)
    out = _SECRET_VALUE_PATTERNS[9].sub(r"\1<REDACTED>", out)
    return out


def sanitize_cli_args(args: list[str]) -> list[str]:
    """Sanitize a command-line argument list, stripping inline --env/--header secrets."""
    cleaned: list[str] = []
    skip_next_value = False
    for arg in args:
        s_arg = str(arg)
        if skip_next_value:
            if "=" in s_arg:
                k, _ = s_arg.split("=", 1)
                cleaned.append(f"{k}=<REDACTED>")
            elif ":" in s_arg:
                k, _ = s_arg.split(":", 1)
                cleaned.append(f"{k}: <REDACTED>")
            else:
                cleaned.append("<REDACTED>")
            skip_next_value = False
            continue

        lower = s_arg.lower()
        if lower in ("--header", "-h", "--env", "-e", "--api-key", "--token", "--secret"):
            cleaned.append(s_arg)
            skip_next_value = True
            continue

        if any(lower.startswith(prefix) for prefix in ("--header=", "--env=", "--api-key=", "--token=", "--secret=")):
            flag, val = s_arg.split("=", 1)
            if "=" in val:
                env_k, _ = val.split("=", 1)
                cleaned.append(f"{flag}={env_k}=<REDACTED>")
            else:
                cleaned.append(f"{flag}=<REDACTED>")
            continue

        cleaned.append(redact_secrets(s_arg))
    return cleaned


def sanitize_text(text: str, max_len: int = 200) -> str:
    """Sanitize untrusted description text against prompt injection and tag spoofing."""
    if not text:
        return ""
    cleaned = _CONTROL_AND_BIDI_RE.sub("", str(text))
    cleaned = _XML_TAG_RE.sub(" ", cleaned)
    cleaned = re.sub(r"!\s*`[^`]*`", " ", cleaned)
    cleaned = re.sub(r"`([^`]{1,60})`", r"\1", cleaned)
    cleaned = cleaned.replace("`", "")
    for pat in _INJECTION_PATTERNS:
        cleaned = pat.sub(" ", cleaned)
    cleaned = redact_secrets(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if max_len > 0 and len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 3].rstrip() + "..."
    return cleaned


def contains_secret_value(text: str) -> bool:
    """Return True if the string appears to contain an unredacted secret value."""
    if not text:
        return False
    return redact_secrets(text) != text


def extract_env_var_names(env_mapping: Any) -> list[str]:
    """Extract only the environment variable names (never values!) from an MCP config."""
    if isinstance(env_mapping, dict):
        return sorted(str(k) for k in env_mapping.keys() if k)
    if isinstance(env_mapping, list):
        names: list[str] = []
        for item in env_mapping:
            if isinstance(item, str):
                names.append(item.split("=", 1)[0])
            elif isinstance(item, dict) and "name" in item:
                names.append(str(item["name"]))
        return sorted(set(names))
    return []