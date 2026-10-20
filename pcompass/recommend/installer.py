"""Consent-gated, SHA-pinned installer, lockfile manager, and auditor for Prompt Compass."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from pcompass.recommend.registries import VettedCandidate, get_candidate_by_id
from pcompass.recommend.scan import scan_directory


@dataclass(frozen=True)
class InstallPlan:
    """Human-reviewable install plan produced before any file is written."""

    candidate_id: str
    kind: str
    name: str
    source_url: str
    pinned_ref: str
    target_agent: str
    target_scope: str
    target_path: str
    trust_score: int
    trust_level: str
    scan_passed: bool
    scan_blocked: bool
    risk_flags: list[str]
    findings: list[dict[str, Any]]
    requires_confirmation: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _compute_content_sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _resolve_install_target(
    kind: str,
    name: str,
    agent: str,
    scope: str,
    project_dir: Path,
    home_dir: Path,
) -> Path:
    base = home_dir if scope == "user" else project_dir
    if kind == "skill":
        agent_skill_map = {
            "universal": base / ".agents" / "skills" / name,
            "claude-code": base / ".claude" / "skills" / name,
            "codex": base / ".agents" / "skills" / name,
            "antigravity": (home_dir / ".gemini" / "config" / "skills" / name) if scope == "user" else (project_dir / ".agents" / "skills" / name),
            "opencode": (home_dir / ".config" / "opencode" / "skills" / name) if scope == "user" else (project_dir / ".opencode" / "skills" / name),
            "gemini-cli": base / ".agents" / "skills" / name,
            "cursor": base / ".cursor" / "skills" / name,
            "copilot": (base / ".copilot" / "skills" / name) if scope == "user" else (base / ".github" / "skills" / name),
            "windsurf": (home_dir / ".codeium" / "windsurf" / "skills" / name) if scope == "user" else (base / ".windsurf" / "skills" / name),
        }
        return agent_skill_map.get(agent, base / ".agents" / "skills" / name)
    else:
        mcp_map = {
            "claude-code": (home_dir / ".claude.json") if scope == "user" else (project_dir / ".mcp.json"),
            "antigravity": (home_dir / ".gemini" / "config" / "mcp_config.json") if scope == "user" else (project_dir / ".agents" / "mcp_config.json"),
            "opencode": (home_dir / ".config" / "opencode" / "opencode.json") if scope == "user" else (project_dir / "opencode.json"),
            "gemini-cli": base / ".gemini" / "settings.json",
            "cursor": base / ".cursor" / "mcp.json",
            "copilot": (home_dir / ".copilot" / "mcp-config.json") if scope == "user" else (project_dir / ".vscode" / "mcp.json"),
            "windsurf": home_dir / ".codeium" / "windsurf" / "mcp_config.json",
        }
        return mcp_map.get(agent, project_dir / ".mcp.json")


def build_install_plan(
    candidate_id: str,
    agent: str = "universal",
    scope: str = "project",
    project_dir: Path | None = None,
    home_dir: Path | None = None,
) -> InstallPlan:
    """Create a vetted install plan for a candidate ID."""
    proj = (project_dir or Path.cwd()).resolve()
    home = (home_dir or Path.home()).resolve()

    vetted: VettedCandidate | None = get_candidate_by_id(candidate_id)
    if vetted is None:
        raise ValueError(f"Unknown candidate ID {candidate_id!r}")

    cand = vetted.candidate
    target_path = _resolve_install_target(cand.kind, cand.name, agent, scope, proj, home)

    return InstallPlan(
        candidate_id=cand.id,
        kind=cand.kind,
        name=cand.name,
        source_url=cand.source_url,
        pinned_ref=cand.pinned_ref,
        target_agent=agent,
        target_scope=scope,
        target_path=str(target_path),
        trust_score=vetted.trust.score,
        trust_level=vetted.trust.level,
        scan_passed=vetted.scan.passed,
        scan_blocked=vetted.scan.blocked,
        risk_flags=vetted.scan.risk_flags,
        findings=[f.to_dict() for f in vetted.scan.findings],
        requires_confirmation=True,
    )


def _lockfile_path(project_dir: Path) -> Path:
    return project_dir / ".promptcompass" / "lock.json"


def load_lockfile(project_dir: Path) -> dict[str, Any]:
    lf = _lockfile_path(project_dir)
    if not lf.is_file():
        return {"version": 1, "entries": {}}
    try:
        data = json.loads(lf.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("entries"), dict):
            return data
    except Exception:
        pass
    return {"version": 1, "entries": {}}


def save_lockfile(project_dir: Path, data: dict[str, Any]) -> Path:
    lf = _lockfile_path(project_dir)
    lf.parent.mkdir(parents=True, exist_ok=True)
    tmp = lf.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(lf)
    return lf


def install_candidate(
    candidate_id: str,
    agent: str = "universal",
    scope: str = "project",
    project_dir: Path | None = None,
    home_dir: Path | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Install a candidate after enforcing the security gate and explicit confirmation."""
    proj = (project_dir or Path.cwd()).resolve()
    home = (home_dir or Path.home()).resolve()

    plan = build_install_plan(candidate_id, agent=agent, scope=scope, project_dir=proj, home_dir=home)
    if plan.scan_blocked:
        raise PermissionError(
            f"Security gate BLOCKED installation of {candidate_id!r} due to critical/high findings: "
            f"{', '.join(plan.risk_flags)}"
        )

    if not confirm:
        raise PermissionError(
            f"Explicit confirmation required to install {candidate_id!r}. Pass --yes / confirm=True after reviewing the plan."
        )

    vetted = get_candidate_by_id(candidate_id)
    assert vetted is not None
    cand = vetted.candidate
    target_path = Path(plan.target_path)

    file_hashes: dict[str, str] = {}
    if cand.kind == "skill":
        target_path.mkdir(parents=True, exist_ok=True)
        for rel_name, content in sorted(cand.files.items()):
            dest_file = target_path / rel_name
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            raw_bytes = content.encode("utf-8")
            dest_file.write_bytes(raw_bytes)
            file_hashes[rel_name] = _compute_content_sha256(raw_bytes)
    else:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        mcp_data: dict[str, Any] = {}
        if target_path.is_file():
            try:
                mcp_data = json.loads(target_path.read_text(encoding="utf-8"))
            except Exception:
                mcp_data = {}
        if target_path.name in ("opencode.json", "opencode.jsonc"):
            top_key = "mcp"
            entry_obj = {
                "type": "local",
                "command": [cand.command, *cand.args],
                "enabled": True,
            }
        elif target_path.name == "mcp.json" and ".vscode" in str(target_path):
            top_key = "servers"
            entry_obj = {"command": cand.command, "args": cand.args}
        else:
            top_key = "mcpServers"
            entry_obj = {"command": cand.command, "args": cand.args}
        servers = mcp_data.setdefault(top_key, {})
        servers[cand.name] = entry_obj
        target_path.write_text(json.dumps(mcp_data, indent=2) + "\n", encoding="utf-8")
        canonical = json.dumps(entry_obj, sort_keys=True).encode("utf-8")
        file_hashes[f"mcp:{cand.name}"] = _compute_content_sha256(canonical)

    lock_data = load_lockfile(proj)
    lock_entry = {
        "id": cand.id,
        "kind": cand.kind,
        "name": cand.name,
        "source_url": cand.source_url,
        "pinned_ref": cand.pinned_ref,
        "agent": agent,
        "scope": scope,
        "target_path": str(target_path),
        "trust_score": plan.trust_score,
        "scan_passed": plan.scan_passed,
        "file_hashes": file_hashes,
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    lock_data["entries"][cand.id] = lock_entry
    lock_path = save_lockfile(proj, lock_data)

    return {
        "status": "installed",
        "lockfile": str(lock_path),
        "entry": lock_entry,
    }


def audit_lockfile(project_dir: Path | None = None) -> dict[str, Any]:
    """Re-hash and security-scan all entries in `.promptcompass/lock.json`."""
    proj = (project_dir or Path.cwd()).resolve()
    lock_data = load_lockfile(proj)
    entries = lock_data.get("entries", {})

    results: list[dict[str, Any]] = []
    all_ok = True

    for cid, entry in sorted(entries.items()):
        target_path = Path(entry["target_path"])
        expected_hashes: dict[str, str] = entry.get("file_hashes", {})
        kind = entry.get("kind", "skill")
        name = entry.get("name", "")
        issues: list[str] = []

        if kind == "skill":
            if not target_path.is_dir():
                issues.append(f"Missing skill directory: {target_path}")
            else:
                for rel_name, exp_hash in sorted(expected_hashes.items()):
                    f_path = target_path / rel_name
                    if not f_path.is_file():
                        issues.append(f"Missing file {rel_name}")
                    else:
                        actual_hash = _compute_content_sha256(f_path.read_bytes())
                        if actual_hash != exp_hash:
                            issues.append(f"SHA-256 mismatch on {rel_name}: expected {exp_hash}, got {actual_hash}")
                scan_res = scan_directory(target_path)
                if scan_res.blocked or not scan_res.passed:
                    issues.append(f"Security scan flagged risks: {', '.join(scan_res.risk_flags)}")
        else:
            if not target_path.is_file():
                issues.append(f"Missing MCP config file: {target_path}")
            else:
                try:
                    mcp_data = json.loads(target_path.read_text(encoding="utf-8"))
                    if target_path.name in ("opencode.json", "opencode.jsonc"):
                        top_key = "mcp"
                    elif target_path.name == "mcp.json" and ".vscode" in str(target_path):
                        top_key = "servers"
                    else:
                        top_key = "mcpServers"
                    srv = mcp_data.get(top_key, {}).get(name)
                    if not isinstance(srv, dict):
                        issues.append(f"MCP server {name!r} missing from {target_path}")
                    else:
                        actual_hash = _compute_content_sha256(json.dumps(srv, sort_keys=True).encode("utf-8"))
                        exp_hash = expected_hashes.get(f"mcp:{name}", "")
                        if exp_hash and actual_hash != exp_hash:
                            issues.append(f"SHA-256 mismatch on MCP entry {name!r}: expected {exp_hash}, got {actual_hash}")
                except Exception as exc:
                    issues.append(f"Corrupt MCP config JSON: {exc}")

        status = "ok" if not issues else "tampered_or_drifted"
        if issues:
            all_ok = False
        results.append({
            "id": cid,
            "name": name,
            "target_path": str(target_path),
            "pinned_ref": entry.get("pinned_ref", ""),
            "status": status,
            "issues": issues,
        })

    return {
        "passed": all_ok,
        "checked_count": len(results),
        "results": results,
    }


def uninstall_candidate(
    candidate_id: str,
    project_dir: Path | None = None,
) -> dict[str, Any]:
    """Remove an installed capability tracked in `.promptcompass/lock.json`."""
    proj = (project_dir or Path.cwd()).resolve()
    lock_data = load_lockfile(proj)
    entries = lock_data.get("entries", {})

    matched_key = None
    for k, v in entries.items():
        if k == candidate_id or v.get("name") == candidate_id:
            matched_key = k
            break

    if not matched_key:
        return {"status": "not_found", "candidate_id": candidate_id}

    entry = entries.pop(matched_key)
    target_path = Path(entry["target_path"])
    kind = entry.get("kind", "skill")
    name = entry.get("name", "")

    if kind == "skill" and target_path.is_dir():
        import shutil
        shutil.rmtree(target_path)
    elif kind == "mcp" and target_path.is_file():
        try:
            mcp_data = json.loads(target_path.read_text(encoding="utf-8"))
            for tk in ("mcpServers", "servers", "mcp"):
                if isinstance(mcp_data.get(tk), dict) and name in mcp_data[tk]:
                    mcp_data[tk].pop(name, None)
            target_path.write_text(json.dumps(mcp_data, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass

    save_lockfile(proj, lock_data)
    return {"status": "uninstalled", "id": matched_key, "target_path": str(target_path)}
