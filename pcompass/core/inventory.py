"""Capability inventory scanner for Prompt Compass.

Scans installed skills (SKILL.md frontmatter only), MCP servers (JSON and TOML
configs with parse-time secret stripping), rules/instructions files, and
developer CLI tools on PATH across:
- Claude Code (claude-code)
- OpenAI Codex CLI (codex)
- Gemini CLI (gemini-cli)
- Cursor (cursor)
- GitHub Copilot (copilot)
- Windsurf / Devin Desktop (windsurf)
- Universal Agent Skills (.agents/skills/)
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any

from pcompass.core.sanitize import (
    extract_env_var_names,
    redact_secrets,
    sanitize_cli_args,
    sanitize_text,
)

if sys.version_info >= (3, 11):
    import tomllib
else:
    tomllib = None


@dataclass(frozen=True)
class CapabilityRecord:
    """Canonical capability record stored in CapabilityIndex."""

    id: str
    kind: str  # "skill" | "mcp" | "rule" | "cli"
    name: str
    description: str
    agent: str
    scope: str  # "project" | "user"
    source_path: str
    content_hash: str
    tools: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CapabilityRecord":
        return cls(
            id=str(data["id"]),
            kind=str(data["kind"]),
            name=str(data["name"]),
            description=str(data.get("description", "")),
            agent=str(data.get("agent", "universal")),
            scope=str(data.get("scope", "project")),
            source_path=str(data.get("source_path", "")),
            content_hash=str(data.get("content_hash", "")),
            tools=list(data.get("tools", [])),
            requires=list(data.get("requires", [])),
        )


CURATED_CLI_TOOLS: dict[str, str] = {
    "agy": "Google Antigravity CLI for agent sessions, plugins, skills, and MCP management",
    "opencode": "OpenCode CLI and TUI coding agent",
    "git": "Version control operations, branching, diffs, blame, and commit history",
    "gh": "GitHub CLI for pull requests, issues, workflow runs, releases, and repo queries",
    "rg": "Ripgrep fast regex code search across files and directories",
    "fd": "Fast filesystem entry and filename finder",
    "jq": "Command-line JSON processor, filter, and transformer",
    "pytest": "Python unit and integration test runner",
    "ruff": "Fast Python linter and code formatter",
    "mypy": "Static type checker for Python",
    "uv": "Fast Python package installer, resolver, and tool runner",
    "docker": "Container builds, compose services, and image inspection",
    "kubectl": "Kubernetes cluster manifest inspection and deployment CLI",
    "helm": "Kubernetes package manager and chart template renderer",
    "terraform": "Infrastructure-as-code plan, validate, and state CLI",
    "npm": "Node.js package manager and script runner",
    "pnpm": "Fast disk-efficient Node.js package manager",
    "bun": "Fast JavaScript/TypeScript runtime, bundler, and test runner",
    "cargo": "Rust package manager, compiler, and test runner",
    "go": "Go toolchain for building, testing, and module management",
    "sqlite3": "Local SQLite database query and schema inspection CLI",
    "psql": "PostgreSQL interactive query and schema inspection client",
    "make": "Build automation tool for Makefile targets",
}


def compute_bytes_hash(data: bytes) -> str:
    """Return a hex SHA-256 digest prefixed with sha256:."""
    return "sha256:" + hashlib.sha256(data).hexdigest()[:16]


def parse_yaml_frontmatter(text: str) -> dict[str, Any]:
    """Parse YAML frontmatter between leading --- markers using stdlib only."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    fm_lines: list[str] = []
    found_end = False
    for line in lines[1:120]:
        if line.strip() in ("---", "..."):
            found_end = True
            break
        fm_lines.append(line)

    if not found_end:
        return {}

    result: dict[str, Any] = {}
    current_key: str | None = None
    current_list: list[str] | None = None
    multiline_mode: str | None = None
    multiline_buf: list[str] = []

    def _flush_pending() -> None:
        nonlocal current_key, current_list, multiline_mode, multiline_buf
        if current_key is not None:
            if current_list is not None:
                result[current_key] = current_list
            elif multiline_mode is not None:
                result[current_key] = " ".join(multiline_buf).strip()
        current_key = None
        current_list = None
        multiline_mode = None
        multiline_buf = []

    for raw_line in fm_lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if raw_line.startswith((" ", "\t")) and current_key is not None:
            if stripped.startswith("- "):
                if current_list is None:
                    current_list = []
                item_val = stripped[2:].strip().strip("'\"")
                if item_val:
                    current_list.append(item_val)
                continue
            elif multiline_mode is not None:
                multiline_buf.append(stripped)
                continue

        if ":" in stripped and not stripped.startswith("-"):
            _flush_pending()
            key, val = stripped.split(":", 1)
            key = key.strip()
            val = val.strip()
            if not val:
                current_key = key
                current_list = []
            elif val in ("|", ">", "|-", ">-"):
                current_key = key
                multiline_mode = val[0]
                multiline_buf = []
            elif val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                items = [
                    x.strip().strip("'\"")
                    for x in inner.split(",")
                    if x.strip().strip("'\"")
                ]
                result[key] = items
            else:
                unquoted = val.strip("'\"")
                if unquoted.lower() in ("true", "false"):
                    result[key] = unquoted.lower() == "true"
                else:
                    result[key] = unquoted

    _flush_pending()
    return result


def parse_skill_file(skill_md_path: Path, agent: str, scope: str) -> CapabilityRecord | None:
    """Parse ONLY the frontmatter of a SKILL.md (or command .md) file."""
    try:
        raw_bytes = skill_md_path.read_bytes()
    except OSError:
        return None

    head_text = raw_bytes[:8192].decode("utf-8", errors="replace")
    fm = parse_yaml_frontmatter(head_text)

    if skill_md_path.name == "SKILL.md":
        default_name = skill_md_path.parent.name
    else:
        default_name = skill_md_path.stem

    if default_name.lower() == "synced" or default_name.lower().startswith("anthropic-skills"):
        return None

    raw_name = str(fm.get("name") or default_name).strip()
    name = re.sub(r"[^a-zA-Z0-9._-]+", "-", raw_name).strip("-").lower() or default_name.lower()

    raw_desc = str(fm.get("description") or "").strip()
    description = sanitize_text(raw_desc or f"Skill {name}", max_len=200)

    tools: list[str] = []
    for tool_key in ("tools", "allowed-tools", "allowedTools"):
        val = fm.get(tool_key)
        if isinstance(val, list):
            tools.extend(str(x) for x in val if x)
        elif isinstance(val, str) and val:
            tools.extend(x.strip() for x in re.split(r"[,|]", val) if x.strip())

    requires: list[str] = []
    req_val = fm.get("requires")
    if isinstance(req_val, list):
        requires.extend(str(x) for x in req_val if x)
    elif isinstance(req_val, str) and req_val:
        requires.extend(x.strip() for x in req_val.split(",") if x.strip())

    openai_yaml = skill_md_path.parent / "agents" / "openai.yaml"
    if openai_yaml.is_file():
        try:
            yaml_text = openai_yaml.read_text(encoding="utf-8", errors="replace")[:4096]
            for match in re.finditer(r'value:\s*["\']?([a-zA-Z0-9_-]+)["\']?', yaml_text):
                dep_name = match.group(1)
                if dep_name not in requires:
                    requires.append(f"mcp:{dep_name}")
        except OSError:
            pass

    # Hash frontmatter only so changes or secrets in body are never read/hashed if desired, or hash file bytes
    content_hash = compute_bytes_hash(raw_bytes)
    cap_id = f"skill:{agent}:{scope}:{name}"
    return CapabilityRecord(
        id=cap_id,
        kind="skill",
        name=name,
        description=description,
        agent=agent,
        scope=scope,
        source_path=str(skill_md_path),
        content_hash=content_hash,
        tools=sorted(set(tools)),
        requires=sorted(set(requires)),
    )


def _strip_json_comments(text: str) -> str:
    """Strip // line comments and /* */ block comments from JSONC files."""
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    escape = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
        else:
            if ch == '"':
                in_string = True
                out.append(ch)
                i += 1
            elif ch == "/" and i + 1 < n and text[i + 1] == "/":
                i += 2
                while i < n and text[i] not in ("\n", "\r"):
                    i += 1
            elif ch == "/" and i + 1 < n and text[i + 1] == "*":
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i += 2
            else:
                out.append(ch)
                i += 1
    return "".join(out)


def _parse_mcp_server_entry(
    server_name: str,
    entry: dict[str, Any],
    agent: str,
    scope: str,
    source_path: Path,
) -> CapabilityRecord | None:
    """Convert a single MCP server config dict into a secret-free CapabilityRecord."""
    if not isinstance(entry, dict):
        return None
    if entry.get("enabled") is False or entry.get("disabled") is True:
        return None

    clean_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(server_name)).strip("-")
    if not clean_name:
        return None

    raw_cmd = entry.get("command")
    if isinstance(raw_cmd, list) and raw_cmd:
        command = str(raw_cmd[0]).strip()
        raw_args = [str(a) for a in raw_cmd[1:]]
    else:
        command = str(raw_cmd or "").strip()
        raw_args = entry.get("args") if isinstance(entry.get("args"), list) else []
    safe_args = sanitize_cli_args([str(a) for a in raw_args])

    raw_url = str(entry.get("url") or entry.get("httpUrl") or entry.get("serverUrl") or "").strip()
    safe_url = ""
    if raw_url:
        no_query = raw_url.split("?", 1)[0].split("#", 1)[0]
        safe_url = redact_secrets(no_query)

    transport = str(entry.get("type") or ("http" if safe_url else "stdio")).lower()

    pkg_hint = ""
    for tok in safe_args:
        if not tok.startswith("-") and tok not in ("run", "-y", "exec", "dlx", "<REDACTED>"):
            pkg_hint = tok
            break
    if command and pkg_hint:
        desc_base = f"MCP server {clean_name} ({transport}: {Path(command).name} {pkg_hint})"
    elif command:
        desc_base = f"MCP server {clean_name} ({transport}: {Path(command).name})"
    elif safe_url:
        desc_base = f"MCP server {clean_name} ({transport}: {safe_url})"
    else:
        desc_base = f"MCP server {clean_name} ({transport})"

    if isinstance(entry.get("description"), str) and entry["description"].strip():
        desc_base = f"{desc_base} - {sanitize_text(entry['description'], max_len=120)}"

    tools: list[str] = []
    for tool_field in ("includeTools", "enabled_tools", "tools"):
        t_val = entry.get(tool_field)
        if isinstance(t_val, list):
            tools.extend(str(t) for t in t_val if isinstance(t, str))
        elif isinstance(t_val, dict):
            tools.extend(str(k) for k in t_val.keys())

    disabled = set()
    for dis_field in ("excludeTools", "disabledTools", "disabled_tools"):
        d_val = entry.get(dis_field)
        if isinstance(d_val, list):
            disabled.update(str(t) for t in d_val if isinstance(t, str))
    tools = [t for t in tools if t not in disabled]

    requires: list[str] = []
    if "env" in entry:
        requires.extend(extract_env_var_names(entry["env"]))
    if "environment" in entry:
        requires.extend(extract_env_var_names(entry["environment"]))
    if "env_vars" in entry:
        requires.extend(extract_env_var_names(entry["env_vars"]))
    if isinstance(entry.get("bearer_token_env_var"), str) and entry["bearer_token_env_var"]:
        requires.append(entry["bearer_token_env_var"])
    if isinstance(entry.get("env_http_headers"), dict):
        requires.extend(str(v) for v in entry["env_http_headers"].values() if isinstance(v, str))

    canonical_payload = json.dumps(
        {
            "name": clean_name,
            "transport": transport,
            "command": command,
            "args": safe_args,
            "url": safe_url,
            "tools": sorted(set(tools)),
            "requires": sorted(set(requires)),
        },
        sort_keys=True,
    ).encode("utf-8")

    return CapabilityRecord(
        id=f"mcp:{agent}:{scope}:{clean_name}",
        kind="mcp",
        name=clean_name,
        description=sanitize_text(desc_base, max_len=200),
        agent=agent,
        scope=scope,
        source_path=str(source_path),
        content_hash=compute_bytes_hash(canonical_payload),
        tools=sorted(set(tools)),
        requires=sorted(set(requires)),
    )


def parse_mcp_json_file(config_path: Path, agent: str, scope: str) -> list[CapabilityRecord]:
    """Parse an MCP JSON/JSONC configuration file (mcpServers or servers)."""
    try:
        raw_text = config_path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(_strip_json_comments(raw_text))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(data, dict):
        return []

    records: list[CapabilityRecord] = []
    servers_obj: dict[str, Any] = {}
    if isinstance(data.get("mcpServers"), dict):
        servers_obj.update(data["mcpServers"])
    if isinstance(data.get("servers"), dict):
        servers_obj.update(data["servers"])
    if isinstance(data.get("mcp"), dict):
        for k, v in data["mcp"].items():
            if k not in ("allowed", "excluded") and isinstance(v, dict):
                servers_obj[k] = v

    allowed_set: set[str] | None = None
    excluded_set: set[str] = set()
    if isinstance(data.get("mcp"), dict):
        if isinstance(data["mcp"].get("allowed"), list) and data["mcp"]["allowed"]:
            allowed_set = {str(x) for x in data["mcp"]["allowed"]}
        if isinstance(data["mcp"].get("excluded"), list):
            excluded_set = {str(x) for x in data["mcp"]["excluded"]}
    if isinstance(data.get("disabledMcpServers"), list):
        excluded_set.update(str(x) for x in data["disabledMcpServers"])
    if isinstance(data.get("disabledMcpjsonServers"), list):
        excluded_set.update(str(x) for x in data["disabledMcpjsonServers"])

    for s_name, s_entry in sorted(servers_obj.items()):
        if s_name in excluded_set:
            continue
        if allowed_set is not None and s_name not in allowed_set:
            continue
        rec = _parse_mcp_server_entry(s_name, s_entry, agent, scope, config_path)
        if rec is not None:
            records.append(rec)

    return records


def _fallback_parse_codex_toml(text: str) -> dict[str, Any]:
    """Zero-dependency fallback parser for Codex config.toml when tomllib is unavailable (<3.11)."""
    data: dict[str, Any] = {"mcp_servers": {}}
    current_key: str | None = None
    sub_key: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        header_match = re.match(r"^\[mcp_servers\.([a-zA-Z0-9_-]+)(?:\.([a-zA-Z0-9_-]+))?\]", line)
        if header_match:
            current_key = header_match.group(1)
            sub_key = header_match.group(2)
            if current_key not in data["mcp_servers"]:
                data["mcp_servers"][current_key] = {}
            if sub_key and sub_key not in data["mcp_servers"][current_key]:
                data["mcp_servers"][current_key][sub_key] = {}
            continue

        if current_key is None or "=" not in line:
            continue

        k, v = [x.strip() for x in line.split("=", 1)]
        target_dict = data["mcp_servers"][current_key]
        if sub_key:
            target_dict = target_dict[sub_key]

        if v.startswith("[") and v.endswith("]"):
            inside = v[1:-1].strip()
            if not inside:
                target_dict[k] = []
            else:
                items: list[str] = []
                for token in re.findall(r'"([^"]*)"|\'([^\']*)\'', inside):
                    items.append(token[0] or token[1])
                target_dict[k] = items
        elif v.startswith("{") and v.endswith("}"):
            inside = v[1:-1].strip()
            nested: dict[str, str] = {}
            for pair in re.findall(r'["\']?([a-zA-Z0-9_-]+)["\']?\s*=\s*["\']?([^"\',}]+)["\']?', inside):
                nested[pair[0].strip()] = pair[1].strip()
            target_dict[k] = nested
        elif (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            target_dict[k] = v[1:-1]
        elif v.lower() == "true":
            target_dict[k] = True
        elif v.lower() == "false":
            target_dict[k] = False
        else:
            target_dict[k] = v

    return data


def parse_codex_toml_file(config_path: Path, scope: str) -> list[CapabilityRecord]:
    """Parse [mcp_servers] from OpenAI Codex CLI config.toml without storing secrets."""
    try:
        raw_bytes = config_path.read_bytes()
    except OSError:
        return []

    text = raw_bytes.decode("utf-8", errors="replace")
    data: dict[str, Any] = {}
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
        except Exception:
            data = {}
    else:
        data = _fallback_parse_codex_toml(text)

    mcp_servers = data.get("mcp_servers")
    if not isinstance(mcp_servers, dict):
        return []

    records: list[CapabilityRecord] = []
    for s_name, s_entry in sorted(mcp_servers.items()):
        if not isinstance(s_entry, dict):
            continue
        rec = _parse_mcp_server_entry(s_name, s_entry, "codex", scope, config_path)
        if rec is not None:
            records.append(rec)
    return records


def parse_rule_file(rule_path: Path, agent: str, scope: str, name_override: str | None = None) -> CapabilityRecord | None:
    """Parse a rules/instructions file (AGENTS.md, CLAUDE.md, GEMINI.md, .mdc, etc.)."""
    try:
        raw_bytes = rule_path.read_bytes()
    except OSError:
        return None

    if not raw_bytes.strip():
        return None

    head_text = raw_bytes[:8192].decode("utf-8", errors="replace")
    fm = parse_yaml_frontmatter(head_text)

    raw_name = name_override or str(fm.get("name") or rule_path.stem)
    if raw_name.endswith(".instructions"):
        raw_name = raw_name[: -len(".instructions")]
    name = re.sub(r"[^a-zA-Z0-9._-]+", "-", raw_name).strip("-").lower() or "rules"

    desc_parts: list[str] = []
    if isinstance(fm.get("description"), str) and fm["description"].strip():
        desc_parts.append(fm["description"].strip())

    for glob_key in ("paths", "globs", "applyTo", "trigger"):
        g_val = fm.get(glob_key)
        if isinstance(g_val, list) and g_val:
            desc_parts.append(f"applies to {', '.join(str(x) for x in g_val[:4])}")
        elif isinstance(g_val, str) and g_val:
            desc_parts.append(f"applies to {g_val}")

    lines = head_text.splitlines()
    in_fm = False
    extracted_topics: list[str] = []
    for idx, line in enumerate(lines):
        s = line.strip()
        if idx == 0 and s == "---":
            in_fm = True
            continue
        if in_fm:
            if s in ("---", "..."):
                in_fm = False
            continue
        if not s or s.startswith("<!--"):
            continue
        if s.startswith("#"):
            heading = s.lstrip("#").strip()
            if heading and len(extracted_topics) < 4:
                extracted_topics.append(heading)
        elif s.startswith(("- ", "* ")) and len(extracted_topics) < 4:
            bullet = s[2:].strip()
            if bullet:
                extracted_topics.append(bullet[:80])

    if extracted_topics:
        desc_parts.append("; ".join(extracted_topics))

    raw_desc = " — ".join(desc_parts) if desc_parts else f"Instruction rules from {rule_path.name}"
    description = sanitize_text(raw_desc, max_len=200)

    return CapabilityRecord(
        id=f"rule:{agent}:{scope}:{name}",
        kind="rule",
        name=name,
        description=description,
        agent=agent,
        scope=scope,
        source_path=str(rule_path),
        content_hash=compute_bytes_hash(raw_bytes),
        tools=[],
        requires=[],
    )


def _iter_skill_files(skills_root: Path) -> list[Path]:
    """Find all SKILL.md files under a skills root (up to 3 levels deep)."""
    if not skills_root.is_dir():
        return []
    found: list[Path] = []
    try:
        for path in sorted(skills_root.rglob("SKILL.md")):
            rel_parts = path.relative_to(skills_root).parts
            if len(rel_parts) > 4:
                continue
            if any(p.startswith(".") or p.lower() == "synced" for p in rel_parts[:-1]):
                continue
            if path.is_file():
                found.append(path)
    except OSError:
        pass
    return found


def scan_inventory(
    project_dir: Path | None = None,
    home_dir: Path | None = None,
    bin_dirs: list[Path] | None = None,
    agent_filter: str | None = None,
) -> list[CapabilityRecord]:
    """Scan skills, MCP servers, rules, and CLI tools across all supported agents."""
    proj = (project_dir or Path.cwd()).resolve()
    home = (home_dir or Path.home()).resolve()

    records_by_id: dict[str, CapabilityRecord] = {}

    def _add(rec: CapabilityRecord | None) -> None:
        if rec is None:
            return
        if agent_filter and rec.agent not in (agent_filter, "universal", "system"):
            return
        records_by_id[rec.id] = rec

    skill_targets: list[tuple[str, str, Path]] = [
        ("universal", "project", proj / ".agents" / "skills"),
        ("universal", "user", home / ".agents" / "skills"),
        ("claude-code", "project", proj / ".claude" / "skills"),
        ("claude-code", "user", home / ".claude" / "skills"),
        ("codex", "project", proj / ".codex" / "skills"),
        ("codex", "user", home / ".codex" / "skills"),
        ("antigravity", "project", proj / ".agent" / "skills"),
        ("antigravity", "user", home / ".gemini" / "config" / "skills"),
        ("antigravity", "user", home / ".gemini" / "antigravity-cli" / "skills"),
        ("antigravity", "user", home / ".gemini" / "antigravity" / "skills"),
        ("opencode", "project", proj / ".opencode" / "skills"),
        ("opencode", "user", home / ".config" / "opencode" / "skills"),
        ("gemini-cli", "project", proj / ".gemini" / "skills"),
        ("gemini-cli", "user", home / ".gemini" / "skills"),
        ("cursor", "project", proj / ".cursor" / "skills"),
        ("cursor", "user", home / ".cursor" / "skills"),
        ("copilot", "project", proj / ".github" / "skills"),
        ("copilot", "user", home / ".copilot" / "skills"),
        ("windsurf", "project", proj / ".devin" / "skills"),
        ("windsurf", "project", proj / ".windsurf" / "skills"),
        ("windsurf", "user", home / ".codeium" / "windsurf" / "skills"),
        ("windsurf", "user", home / ".config" / "devin" / "skills"),
    ]

    for agent_id, scope, s_dir in skill_targets:
        for skill_md in _iter_skill_files(s_dir):
            _add(parse_skill_file(skill_md, agent_id, scope))

    for scope, cmd_dir in [
        ("project", proj / ".claude" / "commands"),
        ("user", home / ".claude" / "commands"),
    ]:
        if cmd_dir.is_dir():
            for md_file in sorted(cmd_dir.glob("*.md")):
                if md_file.is_file():
                    _add(parse_skill_file(md_file, "claude-code", scope))

    mcp_json_targets: list[tuple[str, str, Path]] = [
        ("claude-code", "project", proj / ".mcp.json"),
        ("claude-code", "user", home / ".claude.json"),
        ("antigravity", "project", proj / ".agents" / "mcp_config.json"),
        ("antigravity", "user", home / ".gemini" / "config" / "mcp_config.json"),
        ("antigravity", "user", home / ".gemini" / "antigravity" / "mcp_config.json"),
        ("opencode", "project", proj / "opencode.json"),
        ("opencode", "project", proj / "opencode.jsonc"),
        ("opencode", "user", home / ".config" / "opencode" / "opencode.json"),
        ("gemini-cli", "project", proj / ".gemini" / "settings.json"),
        ("gemini-cli", "user", home / ".gemini" / "settings.json"),
        ("cursor", "project", proj / ".cursor" / "mcp.json"),
        ("cursor", "user", home / ".cursor" / "mcp.json"),
        ("copilot", "project", proj / ".vscode" / "mcp.json"),
        ("copilot", "user", home / ".copilot" / "mcp-config.json"),
        ("copilot", "user", home / ".config" / "Code" / "User" / "mcp.json"),
        ("windsurf", "user", home / ".codeium" / "windsurf" / "mcp_config.json"),
        ("windsurf", "user", home / ".config" / "devin" / "mcp_config.json"),
    ]
    for agent_id, scope, cfg_path in mcp_json_targets:
        if cfg_path.is_file():
            for rec in parse_mcp_json_file(cfg_path, agent_id, scope):
                _add(rec)

    for scope, toml_path in [
        ("project", proj / ".codex" / "config.toml"),
        ("user", home / ".codex" / "config.toml"),
    ]:
        if toml_path.is_file():
            for rec in parse_codex_toml_file(toml_path, scope):
                _add(rec)

    single_rule_targets: list[tuple[str, str, Path, str]] = [
        ("universal", "project", proj / "AGENTS.override.md", "agents-override"),
        ("universal", "project", proj / "AGENTS.md", "agents-md"),
        ("codex", "user", home / ".codex" / "AGENTS.override.md", "codex-agents-override"),
        ("codex", "user", home / ".codex" / "AGENTS.md", "codex-agents-md"),
        ("claude-code", "project", proj / "CLAUDE.md", "claude-md"),
        ("claude-code", "project", proj / ".claude" / "CLAUDE.md", "dot-claude-md"),
        ("claude-code", "project", proj / "CLAUDE.local.md", "claude-local-md"),
        ("claude-code", "user", home / ".claude" / "CLAUDE.md", "user-claude-md"),
        ("antigravity", "project", proj / ".agents" / "AGENTS.md", "antigravity-agents-md"),
        ("antigravity", "project", proj / ".agents" / "GEMINI.md", "antigravity-gemini-md"),
        ("antigravity", "user", home / ".gemini" / "AGENTS.md", "user-antigravity-agents-md"),
        ("antigravity", "user", home / ".gemini" / "config" / "AGENTS.md", "config-antigravity-agents-md"),
        ("antigravity", "user", home / ".gemini" / "config" / "GEMINI.md", "config-antigravity-gemini-md"),
        ("opencode", "user", home / ".config" / "opencode" / "AGENTS.md", "opencode-agents-md"),
        ("gemini-cli", "project", proj / "GEMINI.md", "gemini-md"),
        ("gemini-cli", "user", home / ".gemini" / "GEMINI.md", "user-gemini-md"),
        ("cursor", "project", proj / ".cursorrules", "cursorrules"),
        ("copilot", "project", proj / ".github" / "copilot-instructions.md", "copilot-instructions"),
        ("copilot", "user", home / ".copilot" / "copilot-instructions.md", "user-copilot-instructions"),
        ("windsurf", "project", proj / ".windsurfrules", "windsurfrules"),
        ("windsurf", "user", home / ".codeium" / "windsurf" / "memories" / "global_rules.md", "windsurf-global-rules"),
    ]
    for agent_id, scope, r_path, r_name in single_rule_targets:
        if r_path.is_file():
            _add(parse_rule_file(r_path, agent_id, scope, name_override=r_name))

    dir_rule_targets: list[tuple[str, str, Path, str]] = [
        ("claude-code", "project", proj / ".claude" / "rules", "*.md"),
        ("claude-code", "user", home / ".claude" / "rules", "*.md"),
        ("cursor", "project", proj / ".cursor" / "rules", "*.mdc"),
        ("copilot", "project", proj / ".github" / "instructions", "*.instructions.md"),
        ("copilot", "user", home / ".copilot" / "instructions", "*.instructions.md"),
        ("antigravity", "project", proj / ".agents" / "rules", "*.md"),
        ("antigravity", "project", proj / ".agent" / "rules", "*.md"),
        ("antigravity", "user", home / ".gemini" / "config" / "rules", "*.md"),
        ("antigravity", "user", home / ".gemini" / "antigravity-cli" / "rules", "*.md"),
        ("windsurf", "project", proj / ".devin" / "rules", "*.md"),
        ("windsurf", "project", proj / ".windsurf" / "rules", "*.md"),
    ]
    for agent_id, scope, r_dir, pattern in dir_rule_targets:
        if r_dir.is_dir():
            for r_file in sorted(r_dir.rglob(pattern)):
                if r_file.is_file():
                    _add(parse_rule_file(r_file, agent_id, scope))

    for cli_name, cli_desc in sorted(CURATED_CLI_TOOLS.items()):
        resolved_path: str | None = None
        if bin_dirs is not None:
            for b_dir in bin_dirs:
                candidate = b_dir / cli_name
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    resolved_path = str(candidate)
                    break
        else:
            resolved_path = shutil.which(cli_name)

        if resolved_path:
            _add(
                CapabilityRecord(
                    id=f"cli:system:user:{cli_name}",
                    kind="cli",
                    name=cli_name,
                    description=cli_desc,
                    agent="system",
                    scope="user",
                    source_path=resolved_path,
                    content_hash=compute_bytes_hash(f"{cli_name}:{resolved_path}".encode("utf-8")),
                    tools=[cli_name],
                    requires=[],
                )
            )

    return sorted(records_by_id.values(), key=lambda r: r.id)