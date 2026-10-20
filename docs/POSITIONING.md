# Positioning Statement: Prompt Compass (`pcompass`)

## The Problem: Capability Blindness, Prompt Drift, and Supply-Chain Risk in Coding Agents

Developers in 2026 routinely work across two or three AI coding agents—Claude Code or OpenAI Codex CLI in the terminal, Cursor, GitHub Copilot, or Windsurf in the IDE, and MCP-enabled desktop clients. Across those environments, three structural failures waste turns and expose machines to risk:

1. **Capability Fragmentation & Context Bloat:** A developer's actual toolkit is scattered across `.claude/skills/`, `.agents/skills/`, `.cursor/rules/*.mdc`, `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.mcp.json`, `~/.codex/config.toml`, `.vscode/mcp.json`, and CLI binaries on `PATH`. Agents either miss tools that are already installed (because descriptions are truncated or live in another agent's folder) or burn 15,000–25,000 tokens loading every skill and MCP schema upfront on every session.
2. **Underspecified Prompts Cost Full Correction Loops:** When a user types `"fix the auth timeout"` or `"add a migration for billing"`, the agent guesses the target files, ignores project rules, and skips installed specialized skills or MCP servers—forcing a costly multi-turn correction loop. Existing prompt improvers either rewrite the user's words opaquely, make slow network/LLM calls inside a hook, or work in only one agent.
3. **Unvetted Third-Party Skills and MCP Servers Are a Supply-Chain Vector:** Public audits of agent skill and MCP marketplaces have uncovered hundreds of payloads combining classic shell malware (`curl | sh`, base64 payloads, unpinned `npx -y` typosquats, credential exfiltration) with indirect prompt injection hidden inside tool/skill descriptions. Auto-installing skills or pasting third-party descriptions verbatim into an agent's context turns discovery into an exploit path.

## The Gap Prompt Compass Fills

Existing open-source tools solve isolated slices of this problem for a single agent: `severity1/claude-code-prompt-improver` nudges vague prompts in Claude Code; `hussi9/skill-router` routes across Claude Code skills; `vercel-labs/skills` (`npx skills`) installs `SKILL.md` folders from GitHub; `keshrath/agent-discover` discovers MCP servers mid-session.

**Prompt Compass (`pcompass`) is the missing cross-agent intake layer that unifies all four stages—Inventory, Restructure, Route, and Security-Gated Recommend—in a single deterministic, local-first core:**

| Pillar | What Prompt Compass Does Differently |
| :--- | :--- |
| **1. Cross-Agent Core, Thin Adapters + 3 Delivery Tiers** | One stdlib-only Python 3.10+ core (`pcompass/core/`) backs ~100-line adapters for **Claude Code, OpenAI Codex CLI, Gemini CLI, Cursor, GitHub Copilot, and Windsurf**, plus a universal `SKILL.md` (Tier 2) and `pcompass-mcp` stdio server (Tier 3) so agents without prompt-injection hooks still get first-class routing without faked support. |
| **2. Unified, Secret-Safe Capability Inventory** | Scans **skills (`SKILL.md` frontmatter), MCP servers (JSON & TOML configs), rules files (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.cursor/rules`, `copilot-instructions.md`, `.devin/rules`), and CLI tools on `PATH`** into a single content-hashed `CapabilityIndex`. Strips `env`, `headers`, tokens, and secrets at parse time—never storing credentials on disk. |
| **3. Transparent, Zero-Network Brief + BM25 Router** | Preserves the user's original prompt **verbatim**. Uses fast, deterministic rule-based slot extraction and BM25 + project-signal boosting (`pyproject.toml`, `package.json`, `Cargo.toml`, `Dockerfile`, git remote) to add at most **400 tokens** on complex/vague prompts and **0 tokens** on clear or trivial ones—in **<300 ms p95** with zero LLM calls and zero network traffic. |
| **4. Sanitized Context & Security-Gated Recommender** | Never pastes untrusted third-party descriptions verbatim into the prompt (preventing indirect prompt injection). When a missing skill or MCP server would clearly help, searches the Official MCP Registry and Agent Skills ecosystem using **extracted keywords only**, scores publisher trust, runs a **static security scan** (`curl | sh`, base64 blobs, unpinned `npx -y`, env harvesting, prompt injection), requires **explicit user confirmation** via `pcompass install <id>`, pins the commit SHA/version in `.promptcompass/lock.json`, and verifies integrity via `pcompass audit`. |

## Target Audience & Non-Goals

- **For:** Individual engineers and platform teams who use one or more AI coding agents and want higher first-turn accuracy, automatic discovery of their own installed skills/MCPs/rules, and supply-chain verification before installing third-party agent extensions.
- **What It Is Not:** Not a new coding agent, not a hosted cloud service or telemetry collector, not a new marketplace, and never an auto-installer inside a hook.
