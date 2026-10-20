# Changelog

All notable changes to Prompt Compass (`pcompass`) are documented in this file.

## [0.1.0] - 2026-10-20

### Added
- **Step 0 Research & Verification:** Verified hook schemas, config paths, and capabilities across Claude Code, OpenAI Codex CLI, Gemini CLI, Cursor, GitHub Copilot, and Windsurf/Devin Desktop (`docs/COMPATIBILITY.md`, `docs/PRIOR_ART.md`, `docs/POSITIONING.md`).
- **Phase 1 Inventory & Router:** Built `sanitize.py`, `inventory.py`, `index.py`, and BM25 + project-signal `router.py` with zero-secret cache persistence and `<60ms` p95 latency on 500 skills.
- **Phase 2 Restructurer, Policy & Golden Evals:** Built `policy.py`, `restructure.py`, `render.py` (`<=400` token cap), and 65-prompt golden evaluation suite (`evals/prompts.jsonl`, `evals/runner.py`) achieving 100% top-3 routing recall and 0% false-rewrite rate.
- **Phase 3 CLI Adapters:** Implemented `ClaudeCodeAdapter`, `CodexAdapter`, and `GeminiCliAdapter` with idempotent `setup` (`.bak` backups, JSON merge, `--dry-run`) and `uninstall`.
- **Phase 4 IDE Adapters, MCP Server & Universal Skill:** Implemented `CursorAdapter`, `CopilotAdapter`, `WindsurfAdapter`, `pcompass-mcp` stdio JSON-RPC 2.0 server, and `skills/prompt-compass/SKILL.md`.
- **Phase 5 Security-Gated Recommender:** Added keyword-only `registries.py`, `trust.py` (`0-100` scoring), 7-rule static security scanner `scan.py`, and SHA-256 lockfile `installer.py` (`pcompass install`, `pcompass audit`, `pcompass uninstall`).
- **Phase 6 Open-Source Hygiene & Docs:** Added `ADAPTERS.md`, `SECURITY_MODEL.md`, `CONFIGURATION.md`, `DECISIONS.md`, GitHub Actions CI matrix, and examples.
