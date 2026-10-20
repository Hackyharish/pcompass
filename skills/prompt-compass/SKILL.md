---
name: prompt-compass
description: Analyze the user's request before starting work and produce a structured brief plus a routing plan naming which installed skills, MCP servers and CLI tools to use. Use at the start of any non-trivial task (building features, debugging, refactoring, research, data work, documents, deployment), especially when the request is short, ambiguous, or spans multiple steps. Skip for single-line factual questions or "yes / continue" replies.
---

# Prompt Compass

Run this step before planning or editing on any non-trivial request.

## Workflow

1. If the `pcompass` CLI or the `pcompass-mcp` server is available, call it first:
   - CLI: `pcompass brief --json "$USER_PROMPT"` (or `pcompass route --json "$USER_PROMPT"`)
   - MCP: `analyze_prompt(prompt=...)`
2. If neither is installed, follow the manual procedure below:
   - Scan the workspace for `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.cursor/rules`, `.github/copilot-instructions.md`, `.agents/skills/`, `.claude/skills/`, and MCP configs (`.mcp.json`, `.cursor/mcp.json`, `.vscode/mcp.json`).
   - Restructure the user's request into **Goal**, **Context**, **Constraints**, and **Done-when** without altering the user's intent.
   - Select up to 5 installed skills, MCP servers, rules, or CLI tools that match the task and state a one-line reason for each.
3. Show the user the compact `<prompt-compass>` brief (at most 12 lines).
4. If `Open questions` is non-empty, ask those questions (at most 2) and wait before editing files.
5. Otherwise, proceed with the task and actually invoke the routed skills and MCP tools.
6. If a missing capability is listed under `Consider`, ask the user before running any install command (`pcompass install <id>`). Never install anything automatically.

## Progressive Disclosure References

- Output & JSON contracts: see `references/output_schema.md`
- Security gate, trust scoring, and lockfile auditing: see `references/security_gate.md`
- Standalone routing helper script: `python3 scripts/run_route.py "<prompt>"`
