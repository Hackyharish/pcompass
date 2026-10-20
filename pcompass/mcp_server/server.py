"""Stdio JSON-RPC 2.0 MCP Server (`pcompass-mcp`) exposing Prompt Compass tools.

Tools exposed:
- `analyze_prompt`: Restructure prompt + route to installed capabilities + render `<prompt-compass>`
- `list_capabilities`: List installed skills, MCP servers, rules, and CLI tools
- `recommend`: Discover missing skills/MCP servers via keyword-only search + security gate
- `install_plan`: Generate a human-reviewable, SHA-pinned install plan with trust & scan report
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from pcompass import __version__
from pcompass.core.index import build_or_load_index
from pcompass.core.policy import PolicyConfig, evaluate_skip
from pcompass.core.render import CandidateRecommendation, render_prompt_compass_block
from pcompass.core.restructure import restructure_prompt
from pcompass.core.router import route_prompt
from pcompass.recommend.installer import build_install_plan
from pcompass.recommend.registries import search_registries

MCP_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "name": "analyze_prompt",
        "description": (
            "Analyze a user prompt deterministically: extract intent and slots, "
            "route to installed skills/MCPs/rules/CLIs, and return a <prompt-compass> brief."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "The user prompt to analyze"},
                "agent": {"type": "string", "description": "Optional agent filter (e.g. claude-code, cursor)"},
                "project_dir": {"type": "string", "description": "Optional workspace root path"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "list_capabilities",
        "description": "List installed skills, MCP servers, rules files, and CLI tools in the workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent": {"type": "string", "description": "Optional agent filter"},
                "kind": {"type": "string", "description": "Optional kind filter (skill|mcp|rule|cli)"},
                "project_dir": {"type": "string", "description": "Optional workspace root path"},
            },
        },
    },
    {
        "name": "recommend",
        "description": (
            "Search registries using extracted keywords only and return security-scanned, "
            "trust-scored skill and MCP candidates (never auto-installs)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Task description or keywords"},
                "kind": {"type": "string", "description": "Optional kind filter (skill|mcp)"},
                "project_dir": {"type": "string", "description": "Optional workspace root path"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "install_plan",
        "description": (
            "Generate a human-reviewable, SHA-pinned installation plan with trust score "
            "and static security scan findings for a candidate ID."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string", "description": "Candidate ID (e.g. mcp:registry:redis)"},
                "agent": {"type": "string", "description": "Target agent (default: universal)"},
                "scope": {"type": "string", "description": "Target scope (project|user)"},
                "project_dir": {"type": "string", "description": "Optional workspace root path"},
            },
            "required": ["candidate_id"],
        },
    },
]


def call_mcp_tool(
    name: str,
    arguments: dict[str, Any],
    default_project_dir: Path | None = None,
    default_home_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute one of the 4 MCP tools and return an MCP tool result dict."""
    proj = Path(arguments["project_dir"]).resolve() if arguments.get("project_dir") else (default_project_dir or Path.cwd()).resolve()
    home = (default_home_dir or Path.home()).resolve()

    if name == "analyze_prompt":
        prompt = str(arguments.get("prompt") or "")
        agent = arguments.get("agent")
        index = build_or_load_index(project_dir=proj, home_dir=home)
        policy = PolicyConfig.load(project_dir=proj)
        skip_dec = evaluate_skip(prompt, policy)
        if skip_dec.should_skip:
            res_payload = {
                "skipped": True,
                "skip_reason": skip_dec.reason,
                "context_block": "",
            }
        else:
            brief = restructure_prompt(prompt, signals=index.signals)
            routed = route_prompt(prompt, index, agent=agent, top_k=policy.top_k_routes, min_score=policy.min_route_score)
            installed_names = {c.name for c in index.capabilities}
            vetted = search_registries(prompt, installed_names=installed_names) if not routed else []
            cand_recs = [
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
            rendered = render_prompt_compass_block(brief, routed, cand_recs, mode=policy.mode, max_added_tokens=policy.max_added_tokens)
            res_payload = rendered.to_dict()
        return {
            "content": [{"type": "text", "text": json.dumps(res_payload, indent=2)}],
            "isError": False,
        }

    if name == "list_capabilities":
        agent = arguments.get("agent")
        kind = arguments.get("kind")
        index = build_or_load_index(project_dir=proj, home_dir=home)
        caps = index.filter_by_agent(agent)
        if kind:
            caps = [c for c in caps if c.kind == kind]
        payload = {
            "project_dir": index.project_dir,
            "signals": index.signals.to_dict(),
            "count": len(caps),
            "capabilities": [c.to_dict() for c in caps],
        }
        return {
            "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
            "isError": False,
        }

    if name == "recommend":
        query = str(arguments.get("query") or "")
        kind = arguments.get("kind")
        index = build_or_load_index(project_dir=proj, home_dir=home)
        installed_names = {c.name for c in index.capabilities}
        vetted = search_registries(query, installed_names=installed_names, kind_filter=kind)
        payload = {
            "query": query,
            "recommendations": [v.to_dict() for v in vetted],
        }
        return {
            "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
            "isError": False,
        }

    if name == "install_plan":
        cid = str(arguments.get("candidate_id") or "")
        agent = str(arguments.get("agent") or "universal")
        scope = str(arguments.get("scope") or "project")
        plan = build_install_plan(cid, agent=agent, scope=scope, project_dir=proj, home_dir=home)
        return {
            "content": [{"type": "text", "text": json.dumps(plan.to_dict(), indent=2)}],
            "isError": plan.scan_blocked,
        }

    return {
        "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
        "isError": True,
    }


def handle_jsonrpc_request(
    request: dict[str, Any],
    default_project_dir: Path | None = None,
    default_home_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Handle a single JSON-RPC 2.0 request message."""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params") if isinstance(request.get("params"), dict) else {}

    if method == "notifications/initialized":
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "pcompass-mcp", "version": __version__},
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": MCP_TOOLS_SCHEMA},
        }

    if method == "tools/call":
        tool_name = str(params.get("name") or "")
        tool_args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        try:
            result = call_mcp_tool(
                tool_name,
                tool_args,
                default_project_dir=default_project_dir,
                default_home_dir=default_home_dir,
            )
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error calling {tool_name}: {exc}"}],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> int:
    """Run stdio JSON-RPC 2.0 loop for `pcompass-mcp`."""
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                continue
            resp = handle_jsonrpc_request(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
        except Exception:
            continue
    return 0


if __name__ == "__main__":
    sys.exit(main())
