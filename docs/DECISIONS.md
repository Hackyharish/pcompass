# Architecture Decision Records (`DECISIONS.md`)

Running log of architectural and product decisions for Prompt Compass (`pcompass`).

## ADR-0001: Package and CLI Naming (`pcompass` / `prompt-compass`)
- **Date:** 2026-10-20
- **Status:** Accepted
- **Context:** Checked PyPI, npm, and GitHub on 2026-10-20. `pcompass` has zero collisions on PyPI, npm, and GitHub. `PromptCompass` is used on GitHub by `ErikBorra/PromptCompass` (an academic digital research tool).
- **Decision:** Keep **"Prompt Compass"** as the display name and **`pcompass`** as the PyPI package name, CLI command (`pcompass`), and MCP server executable (`pcompass-mcp`).

## ADR-0002: Honest Three-Tier Delivery Architecture Across the 6 Target Agents
- **Date:** 2026-10-20
- **Status:** Accepted
- **Context:** Official documentation verified on 2026-10-20 shows that Claude Code (`UserPromptSubmit`), OpenAI Codex CLI (`UserPromptSubmit`), Gemini CLI (`BeforeAgent`), and GitHub Copilot CLI/SDK (`userPromptTransformed`) can inject context on every prompt turn, whereas Cursor (`beforeSubmitPrompt`), GitHub Copilot VS Code Local Harness (`UserPromptSubmit`), and Windsurf/Devin (`pre_user_prompt`) do not support per-prompt context injection from their prompt-submit hook.
- **Decision:** Use **Tier 1 (Prompt-Submit Hook)** for Claude Code, Codex CLI, Gemini CLI, and Copilot CLI/SDK, and fall back transparently to **Tier 2 (Universal `SKILL.md`)** + **Tier 3 (`pcompass-mcp` stdio server)** (plus `sessionStart` warmup on Cursor) for agents whose prompt-submit hooks cannot inject context.

## ADR-0003: Standard Library Only for Core (`Python 3.10+`)
- **Date:** 2026-10-20
- **Status:** Accepted
- **Decision:** Implement `pcompass/core/`, `pcompass/adapters/`, `pcompass/recommend/`, and `pcompass/mcp_server/` using Python 3.10+ standard library only so hook cold start stays well below the 300 ms p95 target (measured at ~5 ms p95 on standard workspaces and ~50 ms p95 on 500 skills).

## ADR-0004: Untrusted Description Sanitization and Data Framing
- **Date:** 2026-10-20
- **Status:** Accepted
- **Decision:** Never paste third-party skill or MCP descriptions verbatim into `<prompt-compass>`. Generate deterministic routing reasons from matched task terms and workspace signals, and pass all quoted strings through `pcompass/core/sanitize.py`.

## ADR-0005: Phase 1 Capability Index, Parse-Time Secret Stripping, and BM25 Routing
- **Date:** 2026-10-20
- **Status:** Accepted
- **Decision:** Read only the first 8 KiB YAML frontmatter of `SKILL.md` files, strip MCP `env`/`headers`/`oauth` secrets at parse time before hashing or writing `.promptcompass/cache/index.json`, and rank capabilities using Robertson-Sparck Jones BM25 (`k1=1.5, b=0.75`) with field weights (`name` 3x, `tools` 2x, `description` 1x) and workspace signal boosts.

## ADR-0006: Phase 2 Deterministic Restructurer, Precision Skip Rules, and <=400 Token Cap
- **Date:** 2026-10-20
- **Status:** Accepted
- **Decision:** Evaluate precision skip rules (`*`, `/`, `#`, confirmations, pasted stacktraces/code with clear one-line asks, surgical single-symbol renames) before routing so clear/trivial prompts add 0 tokens. Enforce a progressive compression cascade in `render.py` so `<prompt-compass>` never exceeds 400 added tokens.

## ADR-0007: Phase 3 & 4 Idempotent Adapter Setup with Atomic `.bak` Backups
- **Date:** 2026-10-20
- **Status:** Accepted
- **Decision:** Every adapter's `setup()` and `uninstall()` uses `backup_and_write_text()`, creating a `<file>.bak` copy before modifying any existing JSON/TOML configuration, merging entries rather than overwriting, and supporting `--dry-run`.

## ADR-0008: Phase 5 Security-Gated Recommender and SHA-256 Lockfile (`lock.json`)
- **Date:** 2026-10-20
- **Status:** Accepted
- **Decision:** Registry searches use `extract_search_keywords()` (never raw user prompts). Every candidate is evaluated by `trust.py` (`0-100`) and `scan.py` (7 static security rules). Any Critical or High finding blocks installation even when `--yes` is passed. Installed items are recorded with per-file SHA-256 hashes in `.promptcompass/lock.json` and verified via `pcompass audit`.
