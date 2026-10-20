"""Static security scanner for third-party skill and MCP server candidates.

Detects and blocks:
1. `curl | sh` / `wget | bash` remote script execution
2. `base64 -d` / `eval(...)` / obfuscated payload execution
3. Unpinned `npx -y <pkg>` without explicit version or trusted scope
4. Remote prompt-injection fetch-and-obey instructions or tag spoofing
5. Credential & environment harvesting (`~/.ssh`, `~/.aws`, `.env`, keychain)
6. Broad destructive filesystem access (`rm -rf /`, `/etc/passwd`)
7. Network exfiltration (`curl -X POST`, webhook.site, requestbin, pastebin)
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
import re
from typing import Any


@dataclass(frozen=True)
class ScanFinding:
    """A single static security finding in a candidate skill or MCP config."""

    rule_id: str
    severity: str  # "critical" | "high" | "medium" | "low"
    description: str
    location: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SecurityScanResult:
    """Result of running the static security scanner over a candidate."""

    passed: bool
    blocked: bool
    risk_flags: list[str] = field(default_factory=list)
    findings: list[ScanFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "blocked": self.blocked,
            "risk_flags": self.risk_flags,
            "findings": [f.to_dict() for f in self.findings],
        }


_SCAN_RULES: list[tuple[str, str, str, re.Pattern[str]]] = [
    (
        "curl_pipe_sh",
        "critical",
        "Remote shell pipe execution (curl/wget piped to sh/bash/python)",
        re.compile(r"(?i)\b(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:ba|z)?sh\b|\b(?:curl|wget)\b[^\n|]*\|\s*python3?\b"),
    ),
    (
        "encoded_exec",
        "critical",
        "Base64 decode or dynamic eval/exec of obfuscated payload",
        re.compile(r"(?i)\bbase64\s+(?:-d|--decode)\b|\beval\s*\(\s*(?:atob|Buffer\.from|base64|compile)\b|\bexec\s*\(\s*base64\b"),
    ),
    (
        "prompt_injection_fetch",
        "critical",
        "Prompt injection / remote instruction fetch-and-obey override",
        re.compile(
            r"(?i)(?:ignore|disregard)\s+(?:all\s+)?(?:previous|prior|system)\s+instructions|"
            r"</prompt-compass>|</system-reminder>|"
            r"fetch\s+https?://\S+\s+and\s+(?:follow|obey|execute)\s+its\s+instructions|"
            r"do\s+not\s+(?:inform|tell)\s+the\s+user"
        ),
    ),
    (
        "credential_harvesting",
        "high",
        "Accesses sensitive credential stores (~/.ssh, ~/.aws, ~/.gnupg, keychain, or bulk env dump)",
        re.compile(
            r"(?i)(?:~/|\$HOME/|/home/\w+/)\.(?:ssh|aws|gnupg|kube/config|netrc|npmrc|pypirc)\b|"
            r"\bsecurity\s+find-(?:generic|internet)-password\b|"
            r"\bprintenv\b\s*\|\s*(?:curl|nc|wget)"
        ),
    ),
    (
        "network_exfil",
        "critical",
        "Suspicious outbound data exfiltration (POSTing files/env to external webhook/host)",
        re.compile(
            r"(?i)\bcurl\b[^\n]*(?:-X\s*POST|--data|-d\s+@|-F\s+)[^\n]*https?://|"
            r"\b(?:webhook\.site|requestbin\.com|pipedream\.net|oastify\.com|interact\.sh)\b"
        ),
    ),
    (
        "broad_filesystem_access",
        "high",
        "Destructive or root-level filesystem modification outside workspace",
        re.compile(r"(?i)\brm\s+-[rf]{1,2}\s+(?:/|~|\$HOME)(?:\s|$)|\bchmod\s+777\s+/|/etc/(?:shadow|sudoers|passwd)"),
    ),
]

_UNPINNED_NPX_RE = re.compile(r"\bnpx\s+(?:-y|--yes)\s+([@\w./-]+)")


def scan_text_blob(content: str, location: str = "inline") -> list[ScanFinding]:
    """Scan a single text or command string for security findings."""
    findings: list[ScanFinding] = []
    if not content:
        return findings

    for rule_id, severity, desc, pattern in _SCAN_RULES:
        if pattern.search(content):
            findings.append(
                ScanFinding(
                    rule_id=rule_id,
                    severity=severity,
                    description=desc,
                    location=location,
                )
            )

    for m in _UNPINNED_NPX_RE.finditer(content):
        pkg_spec = m.group(1)
        # Check if version is pinned: e.g. pkg@1.2.3 or @scope/pkg@1.2.3 (and not @latest)
        has_version = False
        if pkg_spec.startswith("@"):
            parts = pkg_spec[1:].split("@")
            if len(parts) >= 2 and parts[1] and parts[1] != "latest":
                has_version = True
        else:
            parts = pkg_spec.split("@")
            if len(parts) >= 2 and parts[1] and parts[1] != "latest":
                has_version = True

        if not has_version:
            findings.append(
                ScanFinding(
                    rule_id="unpinned_npx",
                    severity="medium",
                    description=f"Unpinned npx package execution ({pkg_spec}) without immutable version",
                    location=location,
                )
            )

    return findings


def scan_candidate(
    files: dict[str, str] | None = None,
    command: str = "",
    args: list[str] | None = None,
    description: str = "",
) -> SecurityScanResult:
    """Run static security checks across all files and commands of a candidate."""
    all_findings: list[ScanFinding] = []

    if description:
        all_findings.extend(scan_text_blob(description, location="metadata.description"))

    if command or args:
        cmd_line = f"{command} {' '.join(args or [])}".strip()
        all_findings.extend(scan_text_blob(cmd_line, location="mcp.command"))

    for rel_path, text in sorted((files or {}).items()):
        all_findings.extend(scan_text_blob(text, location=rel_path))

    risk_flags = sorted(set(f.rule_id for f in all_findings))
    blocked = any(f.severity in ("critical", "high") for f in all_findings)
    passed = len(all_findings) == 0

    return SecurityScanResult(
        passed=passed,
        blocked=blocked,
        risk_flags=risk_flags,
        findings=all_findings,
    )


def scan_directory(root_dir: Path) -> SecurityScanResult:
    """Scan all text/script/markdown files in a local skill directory."""
    files_map: dict[str, str] = {}
    if root_dir.is_file():
        files_map[root_dir.name] = root_dir.read_text(encoding="utf-8", errors="replace")
    elif root_dir.is_dir():
        for p in sorted(root_dir.rglob("*")):
            if p.is_file() and p.suffix.lower() in (".md", ".py", ".sh", ".js", ".ts", ".json", ".toml", ".yaml", ".yml"):
                rel = str(p.relative_to(root_dir))
                files_map[rel] = p.read_text(encoding="utf-8", errors="replace")[:65536]
    return scan_candidate(files=files_map)
