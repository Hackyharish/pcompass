"""Content-hashed + mtime disk cache for CapabilityIndex."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from pcompass.core.inventory import CapabilityRecord, scan_inventory
from pcompass.core.sanitize import contains_secret_value, redact_secrets


@dataclass
class ProjectSignals:
    """Signals detected from the workspace root to boost relevant capabilities."""

    languages: list[str] = field(default_factory=list)
    manifests: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    git_host: str = ""
    has_docker: bool = False
    has_k8s: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "languages": self.languages,
            "manifests": self.manifests,
            "frameworks": self.frameworks,
            "git_host": self.git_host,
            "has_docker": self.has_docker,
            "has_k8s": self.has_k8s,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectSignals":
        return cls(
            languages=list(data.get("languages", [])),
            manifests=list(data.get("manifests", [])),
            frameworks=list(data.get("frameworks", [])),
            git_host=str(data.get("git_host", "")),
            has_docker=bool(data.get("has_docker", False)),
            has_k8s=bool(data.get("has_k8s", False)),
        )


def detect_project_signals(project_dir: Path) -> ProjectSignals:
    """Inspect workspace manifests and git config to extract routing signals."""
    signals = ProjectSignals()
    if not project_dir.is_dir():
        return signals

    languages: set[str] = set()
    manifests: list[str] = []
    frameworks: set[str] = set()

    manifest_checks = [
        ("pyproject.toml", "python"),
        ("requirements.txt", "python"),
        ("setup.py", "python"),
        ("package.json", "javascript"),
        ("tsconfig.json", "typescript"),
        ("Cargo.toml", "rust"),
        ("go.mod", "go"),
        ("Gemfile", "ruby"),
        ("pom.xml", "java"),
        ("Dockerfile", "docker"),
        ("docker-compose.yml", "docker"),
        ("docker-compose.yaml", "docker"),
    ]
    for fname, lang in manifest_checks:
        fpath = project_dir / fname
        if fpath.is_file():
            manifests.append(fname)
            if lang == "docker":
                signals.has_docker = True
            else:
                languages.add(lang)

    pkg_json = project_dir / "package.json"
    if pkg_json.is_file():
        try:
            pkg_data = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace")[:16384])
            deps: dict[str, Any] = {}
            if isinstance(pkg_data, dict):
                for k in ("dependencies", "devDependencies", "peerDependencies"):
                    if isinstance(pkg_data.get(k), dict):
                        deps.update(pkg_data[k])
            for dep_name in deps:
                dl = dep_name.lower()
                if "react" in dl or "next" in dl:
                    frameworks.add("react")
                if "playwright" in dl:
                    frameworks.add("playwright")
                if "tailwind" in dl:
                    frameworks.add("tailwind")
                if "typescript" in dl:
                    languages.add("typescript")
                if "prisma" in dl or "drizzle" in dl or "pg" == dl:
                    frameworks.add("database")
        except Exception:
            pass

    pyproject = project_dir / "pyproject.toml"
    if pyproject.is_file():
        try:
            py_text = pyproject.read_text(encoding="utf-8", errors="replace")[:16384].lower()
            for fw in ("pytest", "fastapi", "django", "flask", "sqlalchemy", "ruff", "mypy", "pydantic"):
                if fw in py_text:
                    frameworks.add(fw)
        except OSError:
            pass

    if (project_dir / ".github" / "workflows").is_dir():
        manifests.append(".github/workflows")
        signals.git_host = "github"

    git_cfg = project_dir / ".git" / "config"
    if git_cfg.is_file():
        try:
            g_text = git_cfg.read_text(encoding="utf-8", errors="replace")[:8192].lower()
            if "github.com" in g_text:
                signals.git_host = "github"
            elif "gitlab.com" in g_text:
                signals.git_host = "gitlab"
            elif "bitbucket.org" in g_text:
                signals.git_host = "bitbucket"
        except OSError:
            pass

    if (project_dir / "k8s").is_dir() or (project_dir / "helm").is_dir() or (project_dir / "Chart.yaml").is_file():
        signals.has_k8s = True
        frameworks.add("kubernetes")

    signals.languages = sorted(languages)
    signals.manifests = sorted(set(manifests))
    signals.frameworks = sorted(frameworks)
    return signals


def _compute_sources_fingerprint(project_dir: Path, home_dir: Path) -> str:
    """Compute a fast fingerprint of config/skill/rule file mtimes and sizes."""
    watched_dirs = [
        project_dir / ".agents",
        project_dir / ".claude",
        project_dir / ".codex",
        project_dir / ".gemini",
        project_dir / ".cursor",
        project_dir / ".github",
        project_dir / ".vscode",
        project_dir / ".devin",
        project_dir / ".windsurf",
        home_dir / ".agents",
        home_dir / ".claude",
        home_dir / ".codex",
        home_dir / ".gemini",
        home_dir / ".cursor",
        home_dir / ".copilot",
        home_dir / ".codeium",
        home_dir / ".config" / "devin",
        home_dir / ".config" / "Code" / "User",
    ]
    watched_files = [
        project_dir / "AGENTS.md",
        project_dir / "AGENTS.override.md",
        project_dir / "CLAUDE.md",
        project_dir / "CLAUDE.local.md",
        project_dir / "GEMINI.md",
        project_dir / ".mcp.json",
        project_dir / ".cursorrules",
        project_dir / ".windsurfrules",
        project_dir / "package.json",
        project_dir / "pyproject.toml",
        project_dir / "Cargo.toml",
        project_dir / "Dockerfile",
        home_dir / ".claude.json",
    ]

    entries: list[str] = []
    for fpath in watched_files:
        try:
            st = fpath.stat()
            entries.append(f"F:{fpath}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            pass

    for dpath in watched_dirs:
        if not dpath.is_dir():
            continue
        try:
            for root, dirs, files in os.walk(dpath):
                dirs[:] = [d for d in sorted(dirs) if d not in ("node_modules", ".git", "__pycache__", "cache")]
                for fname in sorted(files):
                    if fname.endswith((".md", ".mdc", ".json", ".toml", ".yaml")):
                        full = Path(root) / fname
                        try:
                            st = full.stat()
                            entries.append(f"F:{full}:{st.st_mtime_ns}:{st.st_size}")
                        except OSError:
                            pass
        except OSError:
            pass

    digest = hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()[:24]
    return f"fp:{digest}"


@dataclass
class CapabilityIndex:
    """In-memory and disk-cached index of capabilities and project signals."""

    capabilities: list[CapabilityRecord]
    signals: ProjectSignals
    fingerprint: str = ""
    project_dir: str = ""
    home_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "fingerprint": self.fingerprint,
            "project_dir": self.project_dir,
            "home_dir": self.home_dir,
            "signals": self.signals.to_dict(),
            "capabilities": [c.to_dict() for c in self.capabilities],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CapabilityIndex":
        return cls(
            capabilities=[CapabilityRecord.from_dict(x) for x in data.get("capabilities", [])],
            signals=ProjectSignals.from_dict(data.get("signals", {})),
            fingerprint=str(data.get("fingerprint", "")),
            project_dir=str(data.get("project_dir", "")),
            home_dir=str(data.get("home_dir", "")),
        )

    def filter_by_agent(self, agent: str | None) -> list[CapabilityRecord]:
        if not agent:
            return self.capabilities
        allowed = {agent, "universal", "system"}
        if agent in ("antigravity", "gemini-cli", "agy"):
            allowed.update({"antigravity", "gemini-cli"})
        if agent == "opencode":
            allowed.add("claude-code")  # OpenCode natively loads .claude/skills and CLAUDE.md
        return [c for c in self.capabilities if c.agent in allowed]


def _assert_no_secrets_in_records(records: list[CapabilityRecord]) -> list[CapabilityRecord]:
    """Enforce the zero-secret invariant on every CapabilityRecord before caching/returning."""
    sanitized: list[CapabilityRecord] = []
    for rec in records:
        desc = redact_secrets(rec.description) if contains_secret_value(rec.description) else rec.description
        tools = [redact_secrets(t) for t in rec.tools]
        requires = [redact_secrets(r) for r in rec.requires]
        sanitized.append(
            CapabilityRecord(
                id=rec.id,
                kind=rec.kind,
                name=rec.name,
                description=desc,
                agent=rec.agent,
                scope=rec.scope,
                source_path=rec.source_path,
                content_hash=rec.content_hash,
                tools=tools,
                requires=requires,
            )
        )
    return sanitized


def build_or_load_index(
    project_dir: Path | None = None,
    home_dir: Path | None = None,
    bin_dirs: list[Path] | None = None,
    cache_path: Path | None = None,
    use_cache: bool = True,
) -> CapabilityIndex:
    """Load CapabilityIndex from disk cache if fingerprint matches, else rescan and save."""
    proj = (project_dir or Path.cwd()).resolve()
    home = (home_dir or Path.home()).resolve()
    resolved_cache = cache_path or (proj / ".promptcompass" / "cache" / "index.json")

    fingerprint = _compute_sources_fingerprint(proj, home)

    if use_cache and resolved_cache.is_file():
        try:
            cached_data = json.loads(resolved_cache.read_text(encoding="utf-8"))
            if (
                isinstance(cached_data, dict)
                and cached_data.get("fingerprint") == fingerprint
                and cached_data.get("project_dir") == str(proj)
                and cached_data.get("home_dir") == str(home)
            ):
                return CapabilityIndex.from_dict(cached_data)
        except Exception:
            pass

    records = scan_inventory(project_dir=proj, home_dir=home, bin_dirs=bin_dirs)
    safe_records = _assert_no_secrets_in_records(records)
    signals = detect_project_signals(proj)

    idx = CapabilityIndex(
        capabilities=safe_records,
        signals=signals,
        fingerprint=fingerprint,
        project_dir=str(proj),
        home_dir=str(home),
    )

    if use_cache:
        try:
            resolved_cache.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = resolved_cache.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(idx.to_dict(), indent=2), encoding="utf-8")
            tmp_path.replace(resolved_cache)
        except OSError:
            pass

    return idx