"""Command-line interface for Prompt Compass (`pcompass`).

Commands:
  scan       Scan installed skills, MCP servers, rules, and CLI tools
  route      Rank installed capabilities for a prompt
  brief      Generate the full <prompt-compass> brief and routing output
  recommend  Discover and security-scan missing skills/MCP servers
  install    Show install plan and install a vetted capability into lockfile
  uninstall  Remove a lockfile-tracked capability
  audit      Re-hash and security-scan all capabilities in .promptcompass/lock.json
  doctor     Diagnose detected agents, hook configs, index health, and lockfile status
  hook       Run fail-open prompt-submit hook for a target agent
  setup      Configure (or --uninstall) Prompt Compass for one or all detected agents
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from pcompass import __version__
from pcompass.adapters import ADAPTER_CLASSES, get_adapter, get_all_adapters
from pcompass.core.index import build_or_load_index
from pcompass.core.policy import PolicyConfig, evaluate_skip
from pcompass.core.render import CandidateRecommendation, render_prompt_compass_block
from pcompass.core.restructure import restructure_prompt
from pcompass.core.router import route_prompt
from pcompass.recommend.installer import (
    audit_lockfile,
    build_install_plan,
    install_candidate,
    uninstall_candidate,
)
from pcompass.recommend.registries import search_registries


def _resolve_dirs(args: argparse.Namespace) -> tuple[Path, Path, Path | None, list[Path] | None]:
    proj = Path(args.project_dir).resolve() if getattr(args, "project_dir", None) else Path.cwd().resolve()
    home = Path(args.home_dir).resolve() if getattr(args, "home_dir", None) else Path.home().resolve()
    cache = Path(args.cache_path).resolve() if getattr(args, "cache_path", None) else None
    bins = [Path(p).resolve() for p in args.bin_dir] if getattr(args, "bin_dir", None) else None
    return proj, home, cache, bins


def _cmd_scan(args: argparse.Namespace) -> int:
    proj, home, cache, bins = _resolve_dirs(args)
    index = build_or_load_index(
        project_dir=proj,
        home_dir=home,
        bin_dirs=bins,
        cache_path=cache,
        use_cache=not args.no_cache,
    )
    caps = index.filter_by_agent(args.agent)
    if args.json:
        print(
            json.dumps(
                {
                    "project_dir": index.project_dir,
                    "fingerprint": index.fingerprint,
                    "signals": index.signals.to_dict(),
                    "count": len(caps),
                    "capabilities": [c.to_dict() for c in caps],
                },
                indent=2,
            )
        )
        return 0

    print(f"Prompt Compass Inventory ({len(caps)} capabilities, fingerprint {index.fingerprint})")
    sig = index.signals
    print(
        f"Project signals: languages={sig.languages}, manifests={sig.manifests}, "
        f"frameworks={sig.frameworks}, git_host={sig.git_host or 'none'}"
    )
    for cap in caps:
        print(f"  - [{cap.kind}] {cap.id}: {cap.description}")
    return 0


def _cmd_route(args: argparse.Namespace) -> int:
    proj, home, cache, bins = _resolve_dirs(args)
    index = build_or_load_index(
        project_dir=proj,
        home_dir=home,
        bin_dirs=bins,
        cache_path=cache,
        use_cache=not args.no_cache,
    )
    routed = route_prompt(
        prompt=args.prompt,
        index=index,
        agent=args.agent,
        top_k=args.top_k,
        min_score=args.min_score,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "prompt": args.prompt,
                    "agent": args.agent or "all",
                    "signals": index.signals.to_dict(),
                    "matches": [r.to_dict() for r in routed],
                },
                indent=2,
            )
        )
        return 0

    if not routed:
        print("No matching capabilities above threshold.")
        return 0

    print(f"Top {len(routed)} routed capabilities for: {args.prompt!r}")
    for item in routed:
        print(f"  - {item.id} (score={item.score:.2f}): {item.reason}")
    return 0


def _cmd_brief(args: argparse.Namespace) -> int:
    proj, home, cache, bins = _resolve_dirs(args)
    policy = PolicyConfig.load(project_dir=proj)
    skip_dec = evaluate_skip(args.prompt, policy)
    if skip_dec.should_skip:
        if args.json:
            print(json.dumps({"skipped": True, "skip_reason": skip_dec.reason, "context_block": ""}, indent=2))
        else:
            print(f"[pcompass] Skipped ({skip_dec.reason})")
        return 0

    index = build_or_load_index(
        project_dir=proj,
        home_dir=home,
        bin_dirs=bins,
        cache_path=cache,
        use_cache=not args.no_cache,
    )
    brief = restructure_prompt(args.prompt, signals=index.signals)
    routed = route_prompt(
        prompt=args.prompt,
        index=index,
        agent=args.agent,
        top_k=policy.top_k_routes,
        min_score=policy.min_route_score,
    )
    installed_names = {c.name for c in index.capabilities}
    vetted = search_registries(args.prompt, installed_names=installed_names) if (policy.recommend_enabled and len(routed) < 2) else []
    recs = [
        CandidateRecommendation(
            id=v.candidate.id,
            kind=v.candidate.kind,
            name=v.candidate.name,
            source=v.candidate.source_registry,
            reason=v.reason,
            trust_score=v.trust.score,
            risk_flags=v.scan.risk_flags,
            install_cmd=f"pcompass install {v.candidate.id}",
        )
        for v in vetted[:2]
    ]
    rendered = render_prompt_compass_block(
        brief=brief,
        routed=routed,
        recommendations=recs,
        mode=policy.mode,
        max_added_tokens=policy.max_added_tokens,
    )

    if args.json:
        print(json.dumps(rendered.to_dict(), indent=2))
        return 0

    if rendered.skipped:
        print(f"[pcompass] Skipped ({rendered.skip_reason})")
        return 0

    print(rendered.banner)
    print(rendered.context_block)
    return 0


def _cmd_recommend(args: argparse.Namespace) -> int:
    proj, home, cache, bins = _resolve_dirs(args)
    index = build_or_load_index(
        project_dir=proj,
        home_dir=home,
        bin_dirs=bins,
        cache_path=cache,
        use_cache=not args.no_cache,
    )
    installed_names = {c.name for c in index.capabilities}
    vetted = search_registries(
        args.query,
        installed_names=installed_names,
        kind_filter=args.kind,
        include_blocked=args.include_blocked,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "query": args.query,
                    "count": len(vetted),
                    "recommendations": [v.to_dict() for v in vetted],
                },
                indent=2,
            )
        )
        return 0

    if not vetted:
        print("No vetted external recommendations matched.")
        return 0

    print(f"Vetted recommendations for {args.query!r}:")
    for v in vetted:
        c = v.candidate
        flags = ", ".join(v.scan.risk_flags) if v.scan.risk_flags else "none"
        status = "BLOCKED" if v.scan.blocked else "PASSED"
        print(
            f"  - {c.id} [{status}] (trust={v.trust.score}/100, risks={flags}): {c.description}\n"
            f"    Install: pcompass install {c.id}"
        )
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    proj, home, _, _ = _resolve_dirs(args)
    plan = build_install_plan(
        args.candidate_id,
        agent=args.agent or "universal",
        scope=args.scope,
        project_dir=proj,
        home_dir=home,
    )
    if args.plan_only:
        if args.json:
            print(json.dumps(plan.to_dict(), indent=2))
        else:
            print(f"Install Plan for {plan.candidate_id}:")
            print(f"  Source     : {plan.source_url} @ {plan.pinned_ref}")
            print(f"  Target     : {plan.target_path} ({plan.target_agent}, {plan.target_scope})")
            print(f"  Trust Score: {plan.trust_score}/100 ({plan.trust_level})")
            print(f"  Scan Status: {'BLOCKED' if plan.scan_blocked else 'PASSED'} (risks: {plan.risk_flags or 'none'})")
        return 1 if plan.scan_blocked else 0

    try:
        res = install_candidate(
            args.candidate_id,
            agent=args.agent or "universal",
            scope=args.scope,
            project_dir=proj,
            home_dir=home,
            confirm=args.yes,
        )
    except PermissionError as exc:
        if args.json:
            print(json.dumps({"status": "blocked_or_unconfirmed", "error": str(exc), "plan": plan.to_dict()}, indent=2))
        else:
            print(f"[pcompass] {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"Installed {res['entry']['id']} -> {res['entry']['target_path']} (locked in {res['lockfile']})")
    return 0


def _cmd_uninstall(args: argparse.Namespace) -> int:
    proj, _, _, _ = _resolve_dirs(args)
    res = uninstall_candidate(args.candidate_id, project_dir=proj)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"Uninstall {args.candidate_id}: {res['status']}")
    return 0 if res["status"] == "uninstalled" else 1


def _cmd_audit(args: argparse.Namespace) -> int:
    proj, _, _, _ = _resolve_dirs(args)
    report = audit_lockfile(project_dir=proj)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        status_str = "PASSED" if report["passed"] else "FAILED (tampering or drift detected)"
        print(f"Prompt Compass Lockfile Audit: {status_str} ({report['checked_count']} entries checked)")
        for item in report["results"]:
            print(f"  - {item['id']} [{item['status']}] ({item['target_path']})")
            for iss in item["issues"]:
                print(f"      ! {iss}")
    return 0 if report["passed"] else 1


def _cmd_doctor(args: argparse.Namespace) -> int:
    proj, home, cache, bins = _resolve_dirs(args)
    index = build_or_load_index(
        project_dir=proj,
        home_dir=home,
        bin_dirs=bins,
        cache_path=cache,
        use_cache=not args.no_cache,
    )
    adapters = get_all_adapters(project_dir=proj, home_dir=home)
    adapter_status: list[dict[str, Any]] = []
    for ad in adapters:
        caps = ad.caps()
        adapter_status.append({
            "agent": ad.id,
            "detected": ad.detect(),
            "primary_tier": caps.primary_tier,
            "hook_event": caps.hook_event,
            "can_inject": caps.can_inject,
            "can_rewrite": caps.can_rewrite,
        })
    audit_rep = audit_lockfile(project_dir=proj)

    payload = {
        "version": __version__,
        "project_dir": str(proj),
        "capabilities_count": len(index.capabilities),
        "signals": index.signals.to_dict(),
        "adapters": adapter_status,
        "lockfile_audit_passed": audit_rep["passed"],
    }
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"Prompt Compass Doctor (v{__version__})")
    print(f"Workspace : {proj}")
    print(f"Inventory : {len(index.capabilities)} capabilities indexed")
    print(f"Lockfile  : {'OK' if audit_rep['passed'] else 'ISSUES FOUND'} ({audit_rep['checked_count']} locked entries)")
    print("Agents:")
    for st in adapter_status:
        det = "detected" if st["detected"] else "not detected"
        print(
            f"  - {st['agent']:12s}: {det:12s} | Tier {st['primary_tier']} | "
            f"hook={st['hook_event']} (inject={st['can_inject']}, rewrite={st['can_rewrite']})"
        )
    return 0


def _cmd_hook(args: argparse.Namespace) -> int:
    """Fail-open hook entrypoint. On ANY error, malformed input, or timeout, exits 0."""
    try:
        proj, home, cache, bins = _resolve_dirs(args)
        adapter = get_adapter(args.agent_name, project_dir=proj, home_dir=home)

        raw_stdin = sys.stdin.read() if not args.stdin_json else args.stdin_json
        if not raw_stdin or not raw_stdin.strip():
            raw_dict: dict[str, Any] = {}
        else:
            raw_dict = json.loads(raw_stdin)
            if not isinstance(raw_dict, dict):
                raw_dict = {}

        if args.event:
            raw_dict["hook_event_name"] = args.event

        hook_in = adapter.parse_hook_input(raw_dict)
        work_dir = Path(hook_in.cwd).resolve() if hook_in.cwd else proj
        policy = PolicyConfig.load(project_dir=work_dir)

        # For Cursor / Antigravity sessionStart or PreInvocation(0) warmup when prompt is empty
        if not hook_in.prompt.strip() and hook_in.event_name in ("sessionStart", "SessionStart", "PreInvocation"):
            index = build_or_load_index(project_dir=work_dir, home_dir=home, bin_dirs=bins, cache_path=cache)
            if adapter.id == "antigravity":
                inv_num = hook_in.raw.get("invocationNum", 0)
                if isinstance(inv_num, int) and inv_num > 0:
                    print(json.dumps({"injectSteps": []}))
                    return 0
                msg = (
                    f"<prompt-compass>Prompt Compass active ({len(index.capabilities)} capabilities indexed). "
                    f"For non-trivial tasks, call MCP tool `analyze_prompt` (or run `pcompass brief`) to route installed skills and MCP tools.</prompt-compass>"
                )
                print(json.dumps({"injectSteps": [{"ephemeralMessage": msg}]}))
                return 0
            out_dict = {
                "env": {},
                "additional_context": (
                    f"<prompt-compass>Workspace capability index ready: "
                    f"{len(index.capabilities)} capabilities available across skills, MCP, rules, and CLI.</prompt-compass>"
                ),
            }
            print(json.dumps(out_dict))
            return 0

        skip_dec = evaluate_skip(hook_in.prompt, policy)
        if skip_dec.should_skip:
            empty_render = render_prompt_compass_block(
                brief=restructure_prompt(hook_in.prompt),
                routed=[],
            )
            # Mark skipped explicitly
            from pcompass.core.render import RenderedOutput
            skipped_out = RenderedOutput(
                skipped=True,
                skip_reason=skip_dec.reason,
                mode=policy.mode,
                original_prompt=hook_in.prompt,
                context_block="",
                banner="",
                added_tokens_estimate=0,
            )
            formatted = adapter.render_hook_output(skipped_out, hook_in)
            if isinstance(formatted, dict) and formatted:
                print(json.dumps(formatted))
            elif isinstance(formatted, str) and formatted:
                print(formatted)
            return 0

        index = build_or_load_index(project_dir=work_dir, home_dir=home, bin_dirs=bins, cache_path=cache)
        brief = restructure_prompt(hook_in.prompt, signals=index.signals)
        routed = route_prompt(
            hook_in.prompt,
            index,
            agent=adapter.id,
            top_k=policy.top_k_routes,
            min_score=policy.min_route_score,
        )
        rendered = render_prompt_compass_block(
            brief=brief,
            routed=routed,
            recommendations=[],
            mode=policy.mode,
            max_added_tokens=policy.max_added_tokens,
        )
        formatted = adapter.render_hook_output(rendered, hook_in)
        if isinstance(formatted, dict):
            if formatted:
                print(json.dumps(formatted))
        elif isinstance(formatted, str) and formatted:
            print(formatted)
        return 0
    except Exception:
        # Strict fail-open guarantee: never block the user's prompt on an internal error
        if getattr(args, "agent_name", "") == "gemini-cli":
            print(json.dumps({"continue": True, "decision": "allow", "suppressOutput": True}))
        return 0


def _cmd_setup(args: argparse.Namespace) -> int:
    proj, home, _, _ = _resolve_dirs(args)
    if args.agent and args.agent != "all":
        target_adapters = [get_adapter(args.agent, project_dir=proj, home_dir=home)]
    else:
        detected = [a for a in get_all_adapters(project_dir=proj, home_dir=home) if a.detect()]
        target_adapters = detected or [get_adapter("claude-code", project_dir=proj, home_dir=home)]

    all_changes: list[dict[str, Any]] = []
    for ad in target_adapters:
        if args.uninstall:
            changes = ad.uninstall(scope=args.scope, dry_run=args.dry_run)
        else:
            changes = ad.setup(scope=args.scope, dry_run=args.dry_run)
        for ch in changes:
            item = ch.to_dict()
            item["agent"] = ad.id
            all_changes.append(item)

    if args.json:
        print(json.dumps({"dry_run": args.dry_run, "uninstall": args.uninstall, "changes": all_changes}, indent=2))
        return 0

    prefix = "[DRY-RUN] " if args.dry_run else ""
    for ch in all_changes:
        print(f"{prefix}[{ch['agent']}] {ch['action'].upper()}: {ch['path']} ({ch['description']})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pcompass",
        description="Prompt Compass: cross-agent prompt router, capability inventory, and security-gated recommender.",
    )
    parser.add_argument("--version", action="version", version=f"pcompass {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def _add_common_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument("--project-dir", help="Project workspace root directory")
        p.add_argument("--home-dir", help="User home directory override")
        p.add_argument("--bin-dir", action="append", help="Explicit PATH directory override for CLI scan")
        p.add_argument("--agent", help="Filter or target a specific agent")
        p.add_argument("--cache-path", help="Custom path for the index.json cache file")
        p.add_argument("--no-cache", action="store_true", help="Bypass reading/writing the on-disk index cache")
        p.add_argument("--json", action="store_true", help="Emit machine-readable JSON output")

    scan_p = sub.add_parser("scan", help="Scan installed skills, MCP servers, rules, and CLI tools")
    _add_common_flags(scan_p)
    scan_p.set_defaults(func=_cmd_scan)

    route_p = sub.add_parser("route", help="Route a user prompt to installed capabilities")
    _add_common_flags(route_p)
    route_p.add_argument("--top-k", type=int, default=5, help="Maximum capabilities to return (max 5)")
    route_p.add_argument("--min-score", type=float, default=1.2, help="Minimum score threshold")
    route_p.add_argument("prompt", help="User prompt text to route")
    route_p.set_defaults(func=_cmd_route)

    brief_p = sub.add_parser("brief", help="Generate structured brief and capability routing for a prompt")
    _add_common_flags(brief_p)
    brief_p.add_argument("prompt", help="User prompt text to structure and route")
    brief_p.set_defaults(func=_cmd_brief)

    rec_p = sub.add_parser("recommend", help="Search registries using keywords only and run security gate")
    _add_common_flags(rec_p)
    rec_p.add_argument("--kind", choices=["skill", "mcp"], help="Filter by capability kind")
    rec_p.add_argument("--include-blocked", action="store_true", help="Include blocked candidates for inspection")
    rec_p.add_argument("query", help="Task prompt or keywords to search")
    rec_p.set_defaults(func=_cmd_recommend)

    inst_p = sub.add_parser("install", help="Install a vetted capability and record SHA-256 in lockfile")
    _add_common_flags(inst_p)
    inst_p.add_argument("--scope", choices=["project", "user"], default="project", help="Install scope")
    inst_p.add_argument("--plan-only", action="store_true", help="Display install plan and security scan without installing")
    inst_p.add_argument("-y", "--yes", action="store_true", help="Confirm installation after reviewing plan")
    inst_p.add_argument("candidate_id", help="Candidate ID (e.g. mcp:registry:redis)")
    inst_p.set_defaults(func=_cmd_install)

    uninst_p = sub.add_parser("uninstall", help="Remove a capability tracked in .promptcompass/lock.json")
    _add_common_flags(uninst_p)
    uninst_p.add_argument("candidate_id", help="Candidate ID or name to remove")
    uninst_p.set_defaults(func=_cmd_uninstall)

    audit_p = sub.add_parser("audit", help="Verify SHA-256 hashes and security scan for all locked capabilities")
    _add_common_flags(audit_p)
    audit_p.set_defaults(func=_cmd_audit)

    doc_p = sub.add_parser("doctor", help="Diagnose detected agents, inventory, and lockfile status")
    _add_common_flags(doc_p)
    doc_p.set_defaults(func=_cmd_doctor)

    hook_p = sub.add_parser("hook", help="Fail-open prompt-submit hook entrypoint for an agent")
    _add_common_flags(hook_p)
    hook_p.add_argument("--event", help="Optional hook event name override")
    hook_p.add_argument("--stdin-json", help="Optional JSON string override for testing")
    hook_p.add_argument("agent_name", choices=sorted(ADAPTER_CLASSES.keys()), help="Target agent ID")
    hook_p.set_defaults(func=_cmd_hook)

    setup_p = sub.add_parser("setup", help="Configure hooks/skills/MCP for detected agents")
    _add_common_flags(setup_p)
    setup_p.add_argument("--scope", choices=["project", "user", "local"], default="project", help="Configuration scope")
    setup_p.add_argument("--dry-run", action="store_true", help="Show planned changes without modifying files")
    setup_p.add_argument("--uninstall", action="store_true", help="Remove Prompt Compass configuration")
    setup_p.set_defaults(func=_cmd_setup)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
