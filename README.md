# Prompt Compass (`pcompass`)

**Cross-agent prompt router, unified capability inventory, and security-gated recommender for AI coding agents.**

Prompt Compass sits in front of your AI coding agent (CLI or IDE) and performs four deterministic operations in **<300 ms p95** with **zero LLM calls** and **zero network calls** on the default path:

1. **Inventory:** Scans installed skills (`SKILL.md` frontmatter only), MCP servers (JSON and TOML configs with parse-time secret stripping), rules files (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.cursor/rules/*.mdc`, `copilot-instructions.md`, `.devin/rules/*.md`), and developer CLI tools on `PATH`.
2. **Restructure:** Turns underspecified prompts into a structured brief (`Goal`, `Context found`, `Constraints`, `Done when`, plus at most 2 blocking `Open questions`) while preserving your original words verbatim.
3. **Route:** Ranks installed skills, MCP servers, rules, and CLI tools using BM25 + workspace signal boosting (`pyproject.toml`, `package.json`, `Cargo.toml`, `Dockerfile`, git remote) and explains why each matched.
4. **Recommend (Security-Gated):** When a missing capability would clearly help, searches registries using **extracted keywords only**, scores publisher trust (`0-100`), runs a static security scanner (`curl | sh`, base64 payloads, unpinned `npx -y`, prompt injection, credential harvesting, exfiltration), requires explicit user confirmation (`pcompass install --yes <id>`), and writes a SHA-256 lockfile (`.promptcompass/lock.json`) verified via `pcompass audit`.

## Architecture Diagram

```text
User Prompt ──► [Skip Policy Check (*, /, #, yes/lgtm, pasted logs)]
                        │
                        ├──► (Skip) ──► Pass through untouched (0 added tokens)
                        │
                        ▼
         ┌──────────────────────────────┐
         │    pcompass/core/ (stdlib)   │
         │  ┌────────────────────────┐  │
         │  │ CapabilityIndex (JSON) │◄─┼── Scan Skills + MCP + Rules + CLI
         │  │ (Zero Secrets Stored)  │  │   (Strip env/headers/tokens at parse)
         │  └───────────┬────────────┘  │
         │              ▼               │
         │  ┌────────────────────────┐  │
         │  │ Restructurer + Router  │  │
         │  │ (Slots + BM25 + Boost) │  │
         │  └───────────┬────────────┘  │
         │              ▼               │
         │  ┌────────────────────────┐  │
         │  │ Sanitizer + Renderer   │  │
         │  │ (<= 400 Added Tokens)  │  │
         │  └───────────┬────────────┘  │
         └──────────────┼───────────────┘
                        ▼
     ┌──────────────────┼──────────────────┐
     ▼                  ▼                  ▼
  [Tier 1]           [Tier 2]           [Tier 3]
Prompt-Submit     Universal Skill     pcompass-mcp
    Hook            (SKILL.md)       (stdio JSON-RPC)
- Claude Code     - Cursor           - All 6 Agents
- Codex CLI       - Copilot VS Code  - Claude Desktop
- Gemini CLI      - Windsurf/Devin   - Cline / Continue
- Copilot CLI     - 75+ Skill Hosts  - Plain Terminal
```

## 60-Second Quickstart

```bash
# Install from source or PyPI
pip install -e .

# 1. Inspect detected agents, inventory, and lockfile health
pcompass doctor

# 2. Configure hooks / skills / MCP for your workspace (preview first with --dry-run)
pcompass setup --dry-run
pcompass setup

# 3. Scan all installed capabilities across agents
pcompass scan

# 4. Generate a structured brief + capability routing for a prompt
pcompass brief "Extract the revenue table from quarterly.pdf and create a PostgreSQL migration"
```

### Per-Agent Setup Commands

- **Claude Code** ([Hooks Docs](https://code.claude.com/docs/en/hooks)): `pcompass setup --agent claude-code` (wires `UserPromptSubmit` in `.claude/settings.json`).
- **OpenAI Codex CLI** ([Hooks Docs](https://learn.chatgpt.com/docs/hooks)): `pcompass setup --agent codex` (wires `UserPromptSubmit` in `.codex/hooks.json`; approve once via `/hooks` in Codex).
- **Google Antigravity CLI (`agy`) / App / IDE** ([Antigravity Hooks Docs](https://antigravity.google/docs/hooks/)): `pcompass setup --agent antigravity` (wires `PreInvocation` & `SessionStart` in `.agents/hooks.json`, `pcompass-mcp` in `.agents/mcp_config.json`, and `.agents/skills/prompt-compass/SKILL.md` which auto-exposes `/prompt-compass` in `agy`; legacy `gemini-cli` alias also supported).
- **OpenCode (`opencode`)** ([OpenCode Docs](https://opencode.ai/docs/skills/)): `pcompass setup --agent opencode` (wires `pcompass-mcp` under `"mcp"` in `opencode.json` and installs `.opencode/skills/prompt-compass/SKILL.md` with `opencode/slash: "true"`).
- **Cursor** ([Hooks Docs](https://cursor.com/docs/hooks)): `pcompass setup --agent cursor` (installs `.cursor/skills/prompt-compass/SKILL.md`, registers `pcompass-mcp` in `.cursor/mcp.json`, and wires `sessionStart`).
- **GitHub Copilot** ([Hooks Reference](https://docs.github.com/en/copilot/reference/hooks-reference)): `pcompass setup --agent copilot` (wires `userPromptTransformed` in `.github/hooks/pcompass.json`, `.vscode/mcp.json`, and `.github/skills/prompt-compass/SKILL.md`).
- **Windsurf / Devin Desktop** ([Cascade Hooks](https://docs.windsurf.com/windsurf/cascade/hooks)): `pcompass setup --agent windsurf` (installs `SKILL.md` in `.devin/skills/` or `.windsurf/skills/` and registers `pcompass-mcp`).

## Before / After Examples

### Example 1: Domain Task Routing (`+185 tokens`)

**Input prompt:**
```text
Create a reversible PostgreSQL migration for the users table and write a Playwright login test
```

**Injected `<prompt-compass>` context:**
```xml
<prompt-compass>
Original request (verbatim): Create a reversible PostgreSQL migration for the users table and write a Playwright login test
Brief:
- Goal: [ADD] Create a reversible PostgreSQL migration for the users table and write a Playwright login test
- Context found: workspace=javascript/python/typescript + fastapi/playwright/pytest + github
- Constraints: Preserve existing behavior outside the requested scope; follow workspace rules.
- Done when: Feature is implemented cleanly, wired into existing entrypoints, and covered by unit/integration tests.
Use (installed):
- skill `db-migration`: skill `db-migration` (project): matches task terms [migration, postgresql, table]; boosted by project language [python]
- skill `webapp-testing`: skill `webapp-testing` (user): matches task terms [playwright, test]; boosted by project language [javascript], workspace signal [playwright]
- mcp `playwright`: mcp `playwright` (user): matches task terms [playwright, test]; boosted by project language [javascript]
- mcp `postgres`: mcp `postgres` (user): matches task terms [postgres, postgresql]; exposes tools [query]
</prompt-compass>
```

### Example 2: Clear / Confirmation / Bypass Prompt (`+0 tokens`)

Prompts like `yes`, `continue`, `LGTM`, `/compact`, `* explain Python generators`, or pasted stacktraces with a clear one-line ask are **skipped automatically**, adding **0 tokens**.

## Compatibility Matrix Summary

See [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md) for the full field-level reference verified against official documentation.

| Agent | Hook Event | Inject Context? | Rewrite Prompt? | Primary Delivery Tier |
| :--- | :--- | :--- | :--- | :--- |
| **Claude Code** | `UserPromptSubmit` | Yes (`additionalContext`) | No | **Tier 1** (Hook) + Tier 2/3 |
| **OpenAI Codex CLI** | `UserPromptSubmit` | Yes (`additionalContext`) | No | **Tier 1** (Hook, `/hooks` trust) + Tier 2/3 |
| **Google Antigravity (`agy` / App / IDE)** | `PreInvocation` & `SessionStart` | Yes (`injectSteps` `ephemeralMessage`) | No | **Tier 1** (Hook) + **Tier 2** (`/prompt-compass`) + **Tier 3** (`mcp_config.json`) |
| **OpenCode (`opencode`)** | TS/JS Plugin (`chat.message`) | Via Plugin / Skill | No | **Tier 2** (`.opencode/skills/` + `/prompt-compass`) + **Tier 3** (`opencode.json` `mcp`) |
| **Gemini CLI (Legacy)** | `BeforeAgent` | Yes (`additionalContext`) | No | **Tier 1** (Hook) + Tier 2/3 |
| **Cursor** | `beforeSubmitPrompt` | No (`sessionStart` only) | No | **Tier 2** (`SKILL.md`) + **Tier 3** (`pcompass-mcp`) |
| **GitHub Copilot CLI/SDK** | `userPromptTransformed` | Yes (`modifiedTransformedPrompt`) | Yes | **Tier 1** (Hook) + Tier 2/3 |
| **GitHub Copilot VS Code** | `UserPromptSubmit` | No (`SessionStart` only) | No | **Tier 2** (`SKILL.md`) + **Tier 3** (`pcompass-mcp`) |
| **Windsurf / Devin** | `pre_user_prompt` | No | No | **Tier 2** (`SKILL.md`) + **Tier 3** (`pcompass-mcp`) |

## FAQ

- **Does Prompt Compass ever make LLM or network calls inside a hook?**  
  No. The default path is 100% deterministic local Python 3.10+ stdlib code (`<300 ms` p95).
- **Are my API keys or MCP `env` variables stored in `.promptcompass/cache/index.json`?**  
  Never. All `env` values, HTTP `headers`, OAuth secrets, and CLI `--header`/`--token` arguments are stripped at parse time before hashing or caching.
- **How do I bypass Prompt Compass on a single prompt?**  
  Prefix your prompt with `*` (e.g., `* what is 2+2`), or set `PCOMPASS_DISABLE=1`.
