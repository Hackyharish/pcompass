# Cross-Agent Compatibility Matrix (`COMPATIBILITY.md`)

**Research Date:** 2026-10-20

**Scope:** Step 0 Mandatory Verification across 6 Target Coding Agents + Generic MCP Clients

**Policy:** Every field name, file path, and hook behavior below is verified against official documentation fetched on 2026-10-20. Anything not explicitly confirmed in official documentation is marked `UNVERIFIED`. No field names or capabilities are guessed or faked.

## Executive Summary & Delivery Tier Matrix

Prompt Compass (`pcompass`) uses three delivery tiers so it works reliably across every agent without faking hook capabilities where a host does not support them:

* **Tier 1 (Automatic Prompt-Submit Hook):** Runs `pcompass hook <agent>` automatically when the user submits a prompt and injects `<prompt-compass>` context (and/or rewrites the model-facing prompt).

* **Tier 2 (Universal Agent Skill):** Installs `SKILL.md` into the agent's native skills directory (`.agents/skills/prompt-compass/SKILL.md` or agent-specific path) so the model invokes `pcompass route --json` at the start of non-trivial tasks.

* **Tier 3 (MCP Server + CLI):** Exposes `pcompass-mcp` over `stdio` (`analyze_prompt`, `list_capabilities`, `recommend`, `install_plan`) plus the `pcompass` CLI.

| Target Agent | Prompt Hook Event | Inject Context? | Rewrite Prompt? | Block Prompt? | Show User Message? | Primary Delivery Tier | Official Source (Verified 2026-10-20) | 
| ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | 
| **Claude Code** | `UserPromptSubmit` | **Yes** (`additionalContext` or stdout) | **No** (explicitly unsupported on `UserPromptSubmit`) | **Yes** (exit `2` or `decision: "block"`) | **Yes** (`systemMessage`) | **Tier 1** (`suggest` mode) + Tier 2/3 | [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks) | 
| **OpenAI Codex CLI** | `UserPromptSubmit` | **Yes** (`additionalContext` or stdout) | **No** (no prompt rewrite field) | **Yes** (exit `2` or `decision: "block"`) | **Yes** (`systemMessage`, `statusMessage`) | **Tier 1** (`suggest` mode; requires `/hooks` trust) + Tier 2/3 | [Codex Hooks Reference](https://learn.chatgpt.com/docs/hooks) | 
| **Gemini CLI** | `BeforeAgent` (and `BeforeModel`) | **Yes** (`hookSpecificOutput.additionalContext`) | **No** on `BeforeAgent` (`Yes` on `BeforeModel` via `llm_request`) | **Yes** (exit `2` or `decision: "deny"`) | **Yes** (`systemMessage`) | **Tier 1** (`suggest` mode on `BeforeAgent`) + Tier 2/3 | [Gemini CLI Hooks Reference](https://geminicli.com/docs/hooks/reference/) | 
| **Cursor (IDE & CLI)** | `beforeSubmitPrompt` | **No** (only `sessionStart` & `postToolUse` inject context) | **No** | **Yes** (`continue: false` or exit `2`) | **Only on block** (`user_message`) | **Tier 2 + Tier 3** (plus optional `sessionStart` index warmup) | [Cursor Hooks Docs](https://cursor.com/docs/hooks) | 
| **GitHub Copilot CLI & SDK Harness** | `userPromptSubmitted` & `userPromptTransformed` | **Yes** (via `userPromptTransformed` `modifiedTransformedPrompt`) | **Yes** (`modifiedTransformedPrompt` on `userPromptTransformed`; dropped on `userPromptSubmitted` command hooks) | **No** on prompt hooks (exit `2` is warning only) | **Yes** (stdout `{"type": "progress", ...}`) | **Tier 1** (via `userPromptTransformed`) + Tier 2/3 | [GitHub Copilot Hooks Reference](https://docs.github.com/en/copilot/reference/hooks-reference) | 
| **GitHub Copilot VS Code (Local Harness)** | `UserPromptSubmit` | **No** on `UserPromptSubmit` (`Yes` on `SessionStart` / `SubagentStart`) | **No** | **Yes** (exit `2` or `continue: false`) | **Yes** (`systemMessage`) | **Tier 2 + Tier 3** (plus `SessionStart` / `SubagentStart` hooks) | [VS Code Local Hooks Reference](https://code.visualstudio.com/docs/agents/reference/hooks-reference) | 
| **Windsurf / Devin Desktop (Cascade)** | `pre_user_prompt` | **No** (stdout ignored on `pre_user_prompt`) | **No** | **Yes** (exit `2` with `stderr`) | **Only on block** (`show_output` disabled on `pre_user_prompt`) | **Tier 2 + Tier 3** | [Windsurf Cascade Hooks Docs](https://docs.windsurf.com/windsurf/cascade/hooks) | 
| **Generic MCP Clients** | None (`UNVERIFIED` / no MCP spec hook) | **No** | **No** | **No** | **No** | **Tier 3** (`pcompass-mcp` + CLI) + **Tier 2** (if `SKILL.md` supported) | [Official MCP Registry](https://github.com/modelcontextprotocol/registry) | 

## Package & Binary Name Availability Check

Verified on 2026-10-20 via web search across PyPI, npm, and GitHub:

* **`pcompass`:** **Free** on PyPI (`pypi.org`), npm (`npmjs.com`), and GitHub (`github.com`). Zero package or repository collisions found.

* **`prompt-compass`:** Free on PyPI and npm, but `ErikBorra/PromptCompass` exists on GitHub ([ErikBorra/PromptCompass](https://github.com/ErikBorra/PromptCompass), an LLM digital research tool).

* **Decision:** Use `pcompass` as the canonical package name on PyPI/npm and CLI executable (`pcompass`, `pcompass-mcp`), and keep "Prompt Compass (`pcompass`)" as the human-readable project title.

## 1. Claude Code

**Primary Sources (Verified 2026-10-20):**

* [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks)

* [Automate Actions with Hooks](https://code.claude.com/docs/en/hooks-guide)

* [Extend Claude with Skills](https://code.claude.com/docs/en/skills)

* [Connect Claude Code to Tools via MCP](https://code.claude.com/docs/en/mcp)

* [How Claude Remembers Your Project (`CLAUDE.md` & `AGENTS.md`)](https://code.claude.com/docs/en/memory)

### Hook Event & Configuration

* **Prompt-Submit Event:** `UserPromptSubmit` fires when a user submits a prompt, before Claude processes it (also fires on turns Claude Code starts on its own). It does not support `matcher` filtering (any configured `matcher` is ignored). A secondary event, `UserPromptExpansion`, fires when a slash command or skill expands into a prompt.

* **Config File Locations:**

  * User scope: `~/.claude/settings.json`

  * Project scope (committed): `.claude/settings.json`

  * Project scope (local/gitignored): `.claude/settings.local.json`

  * Managed policy scope: `/Library/Application Support/ClaudeCode/managed-settings.json` (macOS), `/etc/claude-code/managed-settings.json` (Linux/WSL), `C:\Program Files\ClaudeCode\managed-settings.json` (Windows)

  * Plugin scope: `hooks/hooks.json` inside an enabled plugin

* **Config Schema:**

```
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "pcompass",
            "args": ["hook", "claude-code"],
            "timeout": 5
          }
        ]
      }
    ]
  }
}

```

* **Hook Input Fields (`stdin` JSON):**

  * `session_id` (`string`): Current session identifier.

  * `transcript_path` (`string`): Path to the `.jsonl` session transcript file.

  * `cwd` (`string`): Current working directory.

  * `permission_mode` (`string`): Active permission mode (e.g., `"default"`, `"plan"`, `"acceptEdits"`, `"bypassPermissions"`).

  * `hook_event_name` (`string`): `"UserPromptSubmit"`.

  * `prompt` (`string`): Submitted prompt text (pasted text arrives expanded).

  * `prompt_id` (`string`): UUID identifying the user prompt.

  * Environment variable: `CLAUDE_PROJECT_DIR` (project root directory where the session started).

* **Hook Output Contract (`stdout` JSON & Exit Codes):**

  * Exit code `0` with empty stdout: No-op; prompt proceeds unchanged.

  * Exit code `0` with plain text stdout: Plain text is added as context alongside the prompt.

  * Exit code `0` with a single JSON object on stdout:

```
{
  "systemMessage": "[pcompass] Added brief + 2 routed capabilities (skill:pdf, mcp:github)",
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "<prompt-compass>...</prompt-compass>"
  }
}

```

* Optional top-level fields: `continue` (`boolean`), `stopReason` (`string`), `decision` (`"block"`), `reason` (`string`), and `hookSpecificOutput.sessionTitle` (`string`).

* Exit code `2`: Blocks the prompt; `stderr` is shown as the rejection reason.

* Any other non-zero exit code: Non-blocking hook error; prompt proceeds (fail-open).

* Oversized output handling: `additionalContext` above 10,000 characters is saved to disk and replaced with a file path and 2,000-character preview ([cachly UserPromptSubmit Reference](https://cachly.dev/docs/claude-code-hooks/userpromptsubmit)).

* **Hook Capabilities:**

  * **(a) Inject context:** **Yes** (`hookSpecificOutput.additionalContext` or plain text stdout).

  * **(b) Replace prompt text:** **No** ([Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks) explicitly states: "`UserPromptSubmit`: can't replace the prompt; it only injects `additionalContext` alongside it").

  * **(c) Block:** **Yes** (exit code `2` or `"decision": "block"`).

  * **(d) Show message to user:** **Yes** (top-level `systemMessage`).

* **Timeouts & Trust/Approvals:**

  * Command hooks default to `600` seconds globally (`30` seconds noted on `UserPromptSubmit` in [cachly Docs](https://cachly.dev/docs/claude-code-hooks/userpromptsubmit)); `timeout` field is in seconds.

  * Project-scoped hooks require accepting the workspace trust dialog when launching `claude` in a repository. Administrators can enforce `allowManagedHooksOnly: true`.

### Skills, MCP, and Rules Inventory Paths

* **Skills (`SKILL.md` natively supported: Yes):**

  * Project: `.claude/skills/<name>/SKILL.md` and nested `<subdir>/.claude/skills/<name>/SKILL.md` (legacy `.claude/commands/*.md` also supported).

  * User: `~/.claude/skills/<name>/SKILL.md` (Note: `~/.claude/skills/synced/` and namespace `anthropic-skills` are reserved for `claude.ai` synced skills).

  * Enterprise: `.claude/skills/<name>/SKILL.md` in managed settings directory.

* **MCP Configs (JSON):**

  * User & local scope: `~/.claude.json` (top-level `"mcpServers"` or per-project entries).

  * Project scope: `<project>/.mcp.json` (top-level `"mcpServers"` object; requires interactive trust approval before connecting).

  * Server entry fields: `type` (`"stdio"` | `"http"` | `"streamable-http"` | `"sse"` | `"ws"`), `command`, `args`, `url`, `env`, `headers`, `headersHelper`.

  * Where secrets live: `env`, `headers`, `headersHelper` (must be stripped at parse time; supports `${VAR}` and `${VAR:-default}` syntax).

* **Rules & Instructions Files:**

  * Project: `./CLAUDE.md`, `./.claude/CLAUDE.md`, `./CLAUDE.local.md`, `./.claude/rules/**/*.md` (supports YAML frontmatter `paths` glob list), and `./AGENTS.md` (loaded automatically in v2.1.277+ when no `CLAUDE.md` exists in working directory or above, or via `@AGENTS.md` import).

  * User: `~/.claude/CLAUDE.md`, `~/.claude/rules/**/*.md`.

  * Managed: `/Library/Application Support/ClaudeCode/CLAUDE.md` (macOS), `/etc/claude-code/CLAUDE.md` (Linux/WSL), `C:\Program Files\ClaudeCode\CLAUDE.md` (Windows).

## 2. OpenAI Codex CLI

**Primary Sources (Verified 2026-10-20):**

* [Codex Hooks Reference](https://learn.chatgpt.com/docs/hooks)

* [Codex Configuration Reference (`config.toml`)](https://learn.chatgpt.com/docs/config-file/config-reference)

* [Codex Sample Configuration (`config.toml`)](https://learn.chatgpt.com/docs/config-file/config-sample)

* [Custom Instructions with `AGENTS.md`](https://learn.chatgpt.com/docs/agent-configuration/agents-md)

* [Build Skills for ChatGPT and Codex](https://learn.chatgpt.com/docs/build-skills)

### Hook Event & Configuration

* **Prompt-Submit Event:** `UserPromptSubmit` fires during a turn when a user prompt is about to be sent (`matcher` is not supported and ignored for this event).

* **Config File Locations:**

  * User scope: `~/.codex/hooks.json` or inline `[[hooks.UserPromptSubmit]]` in `~/.codex/config.toml` (respects `$CODEX_HOME`).

  * Project scope: `<repo>/.codex/hooks.json` or `<repo>/.codex/config.toml` (loaded only when the project `.codex/` layer is trusted).

  * Managed scope: `requirements.toml` (`[hooks]` with `allow_managed_hooks_only = true`).

  * Note: If a single config layer contains both `hooks.json` and inline `[hooks]` in `config.toml`, Codex merges them and logs a startup warning. `pcompass setup` checks whether `[hooks]` already exists in `config.toml` and otherwise writes to `hooks.json`.

* **Config Schema (`hooks.json` & `config.toml`):**

```
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "pcompass hook codex",
            "timeout": 5,
            "statusMessage": "Routing prompt with Prompt Compass",
            "additionalContextLimit": 2500
          }
        ]
      }
    ]
  }
}

```

Equivalent `config.toml`:

```
[[hooks.UserPromptSubmit]]
[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = "pcompass hook codex"
timeout = 5
statusMessage = "Routing prompt with Prompt Compass"
additionalContextLimit = 2500

```

* **Hook Input Fields (`stdin` JSON):**

  * `session_id` (`string`): Current Codex session ID.

  * `turn_id` (`string`): Active Codex turn ID.

  * `transcript_path` (`string | null`): Path to session transcript file.

  * `cwd` (`string`): Working directory for the session.

  * `hook_event_name` (`string`): `"UserPromptSubmit"`.

  * `model` (`string`): Active model slug.

  * `permission_mode` (`string`): `"default"` | `"acceptEdits"` | `"plan"` | `"dontAsk"` | `"bypassPermissions"`.

  * `prompt` (`string`): User prompt about to be sent.

* **Hook Output Contract (`stdout` JSON & Exit Codes):**

  * Exit `0` with no output: Treated as success; Codex continues.

  * Exit `0` with plain text on stdout: Added as extra developer context.

  * Exit `0` with JSON on stdout:

```
{
  "continue": true,
  "systemMessage": "[pcompass] Routed to skill:pdf, mcp:github",
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "<prompt-compass>...</prompt-compass>"
  }
}

```

* Blocking: Return `{"decision": "block", "reason": "..."}` on stdout or exit with code `2` and write reason to `stderr`.

* Spilling threshold: Default 2,500 tokens per handler (`additionalContextLimit`), above which Codex writes full text to `<temp_dir>/hook_outputs/<session_id>/<uuid>.txt` and passes a preview.

* **Hook Capabilities:**

  * **(a) Inject context:** **Yes** (`hookSpecificOutput.additionalContext` or plain text stdout, injected as developer context).

  * **(b) Replace prompt text:** **No** (no prompt replacement field on `UserPromptSubmit`).

  * **(c) Block:** **Yes** (`decision: "block"` or exit code `2`).

  * **(d) Show message to user:** **Yes** (`systemMessage` surfaces as a UI warning/banner; `statusMessage` displays while hook runs).

* **Timeouts & Trust/Approvals:**

  * Default timeout: `600` seconds (`timeout` field is in seconds).

  * **Mandatory Hook Trust:** Before any non-managed hook runs, Codex requires the user to review and trust the exact hook definition (hashed by content) via the `/hooks` command in the CLI (or pass `--dangerously-bypass-hook-trust`). If a hook definition changes, Codex skips it and prints a startup notice until re-trusted in `/hooks`.

### Skills, MCP, and Rules Inventory Paths

* **Skills (`SKILL.md` natively supported: Yes):**

  * Project: `$CWD/.agents/skills/<name>/SKILL.md` walking up to `$REPO_ROOT/.agents/skills/<name>/SKILL.md` (optional `agents/openai.yaml` metadata file).

  * User: `$HOME/.agents/skills/<name>/SKILL.md`.

  * Admin: `/etc/codex/skills/<name>/SKILL.md`.

  * Per-skill enable/disable: `[[skills.config]]` (`path`, `enabled`) in `config.toml`.

* **MCP Configs (TOML):**

  * User scope: `~/.codex/config.toml` (`$CODEX_HOME/config.toml`) under `[mcp_servers.<name>]`.

  * Project scope: `.codex/config.toml` under `[mcp_servers.<name>]` (when project is trusted).

  * Server entry fields: `command`, `args`, `cwd`, `env = { ... }`, `env_vars = [...]`, `url`, `bearer_token_env_var`, `http_headers = { ... }`, `env_http_headers = { ... }`, `http_headers_helper`, `enabled_tools`, `disabled_tools`, `startup_timeout_sec`, `tool_timeout_sec`, and `[mcp_servers.<name>.oauth]` (`client_id`, `client_secret`, `callback_url`, `callback_port`).

  * Where secrets live: `env` table values, `http_headers` table values, and `oauth.client_secret` (strip values at parse time; `bearer_token_env_var`, `env_vars`, and `env_http_headers` hold variable names only).

* **Rules & Instructions Files:**

  * User: `~/.codex/AGENTS.override.md` (if present and non-empty), else `~/.codex/AGENTS.md`.

  * Project: From git root down to `cwd`, checks `AGENTS.override.md`, then `AGENTS.md`, then any filenames in `project_doc_fallback_filenames` in `config.toml` (default combined limit `project_doc_max_bytes = 32768`).

## 3. Gemini CLI

**Primary Sources (Verified 2026-10-20):**

* [Gemini CLI Hooks Reference](https://geminicli.com/docs/hooks/reference/)

* [Gemini CLI Configuration Reference](https://geminicli.com/docs/reference/configuration/)

* [Gemini CLI Agent Skills](https://geminicli.com/docs/cli/skills/)

* [MCP Servers with Gemini CLI](https://geminicli.com/docs/tools/mcp-server/)

* [Provide Context with `GEMINI.md` Files](https://geminicli.com/docs/cli/gemini-md/)

### Hook Event & Configuration

* **Prompt-Submit Event:** `BeforeAgent` fires after a user submits a prompt, before the agent begins planning. (Additionally, `BeforeModel` fires before the LLM request and can modify `hookSpecificOutput.llm_request`, and `BeforeToolSelection` can filter tools via `hookSpecificOutput.toolConfig.allowedFunctionNames`).

* **Config File Locations:**

  * User scope: `~/.gemini/settings.json`

  * Project scope: `.gemini/settings.json`

  * System overrides: `/etc/gemini-cli/settings.json` (Linux), `/Library/Application Support/GeminiCli/settings.json` (macOS), `C:\ProgramData\gemini-cli\settings.json` (Windows)

  * System defaults: `/etc/gemini-cli/system-defaults.json` (Linux), `/Library/Application Support/GeminiCli/system-defaults.json` (macOS), `C:\ProgramData\gemini-cli\system-defaults.json` (Windows)

* **Config Schema (`settings.json`):**

```
{
  "hooks": {
    "BeforeAgent": [
      {
        "sequential": false,
        "hooks": [
          {
            "type": "command",
            "name": "pcompass",
            "command": "pcompass hook gemini-cli",
            "timeout": 1500,
            "description": "Prompt Compass capability router and brief generator"
          }
        ]
      }
    ]
  }
}

```

* **Critical difference:** `timeout` in Gemini CLI `settings.json` is in **milliseconds** (default: `60000`), unlike Claude Code and Codex which use seconds!

* **Silence is Mandatory:** Scripts must NOT print any plain text to `stdout` other than the final JSON object.

* **Hook Input Fields (`stdin` JSON):**

  * `session_id` (`string`): Unique ID for current session.

  * `transcript_path` (`string`): Absolute path to session transcript JSON.

  * `cwd` (`string`): Current working directory.

  * `hook_event_name` (`string`): `"BeforeAgent"`.

  * `timestamp` (`string`): ISO 8601 execution timestamp.

  * `prompt` (`string`): The original text submitted by the user.

* **Hook Output Contract (`stdout` JSON & Exit Codes):**

  * Exit `0` with strict JSON on stdout:

```
{
  "systemMessage": "[pcompass] Routed to skill:pdf, mcp:github",
  "suppressOutput": false,
  "continue": true,
  "decision": "allow",
  "hookSpecificOutput": {
    "additionalContext": "<prompt-compass>...</prompt-compass>"
  }
}

```

* Blocking: `"decision": "deny"` (or exit code `2` with `stderr` reason) aborts the turn and discards the user's message from history; `"continue": false` with `"reason"` blocks the turn while keeping the message in history.

* Other non-zero exit codes: Treated as a non-fatal warning; CLI continues (fail-open).

* **Hook Capabilities (`BeforeAgent`):**

  * **(a) Inject context:** **Yes** (`hookSpecificOutput.additionalContext` is appended to the prompt for this turn only).

  * **(b) Replace prompt text:** **No** on `BeforeAgent` (`BeforeModel` can override `hookSpecificOutput.llm_request.messages`, which we document as an optional advanced hook, keeping `BeforeAgent` as the primary safe path).

  * **(c) Block:** **Yes** (`decision: "deny"`, `continue: false`, or exit code `2`).

  * **(d) Show message to user:** **Yes** (`systemMessage` displayed immediately in the terminal).

* **Timeouts & Trust/Approvals:**

  * Default timeout: `60000` ms (`timeout` is specified in ms).

  * Folder trust: Controlled via `security.folderTrust.enabled` (`folderTrust`) in `settings.json`. Skill activation in interactive sessions prompts the user for consent showing the skill's directory path.

### Skills, MCP, and Rules Inventory Paths

* **Skills (`SKILL.md` natively supported: Yes):**

  * Workspace (Project): `.agents/skills/<name>/SKILL.md` (higher precedence alias) and `.gemini/skills/<name>/SKILL.md`.

  * User: `~/.agents/skills/<name>/SKILL.md` (higher precedence alias) and `~/.gemini/skills/<name>/SKILL.md`.

  * Extensions: Bundled inside installed Gemini CLI extensions.

* **MCP Configs (JSON):**

  * User & Project: `~/.gemini/settings.json` and `.gemini/settings.json` under top-level `"mcpServers"` object (and global `"mcp": {"allowed": [...], "excluded": [...]}`).

  * Server entry fields: `command`, `args`, `env`, `cwd`, `url` (SSE), `httpUrl` (Streamable HTTP), `headers`, `timeout`, `trust`, `includeTools`, `excludeTools`, `oauth`.

  * Where secrets live: `env`, `headers`, `oauth.clientSecret`, and `~/.gemini/mcp-oauth-tokens.json`.

* **Rules & Instructions Files:**

  * User: `~/.gemini/GEMINI.md`.

  * Project & JIT subdirectories: `GEMINI.md` in workspace root, parent directories, and accessed subdirectories (supports `@file.md` imports; configurable via `context.fileName` in `settings.json`, e.g., `["AGENTS.md", "CONTEXT.md", "GEMINI.md"]`).

## 4. Cursor (IDE and CLI)

**Primary Sources (Verified 2026-10-20):**

* [Cursor Hooks Documentation](https://cursor.com/docs/hooks)

* [Cursor Third-Party Hooks Compatibility](https://cursor.com/docs/reference/third-party-hooks)

* [Cursor Agent Skills Documentation](https://cursor.com/docs/skills)

* [Cursor Rules Documentation](https://cursor.com/docs/rules)

* [Cursor Model Context Protocol (MCP) Documentation](https://cursor.com/docs/mcp)

### Hook Event & Configuration

* **Prompt-Submit Event:** `beforeSubmitPrompt` fires right after the user hits send, before the backend request.

* **Config File Locations:**

  * User scope: `~/.cursor/hooks.json` (working directory for relative script paths is `~/.cursor/`).

  * Project scope: `<project-root>/.cursor/hooks.json` (working directory is `<project-root>`; runs in trusted workspaces and Cloud Agents).

  * Enterprise/MDM scope: `/Library/Application Support/Cursor/hooks.json` (macOS), `/etc/cursor/hooks.json` (Linux/WSL), `C:\ProgramData\Cursor\hooks.json` (Windows).

* **Config Schema (`hooks.json`):**

```
{
  "version": 1,
  "hooks": {
    "sessionStart": [
      {
        "command": "pcompass hook cursor --event sessionStart",
        "type": "command",
        "timeout": 5,
        "failClosed": false
      }
    ],
    "beforeSubmitPrompt": [
      {
        "command": "pcompass hook cursor --event beforeSubmitPrompt",
        "type": "command",
        "timeout": 5,
        "failClosed": false
      }
    ]
  }
}

```

* **Hook Input Fields (`stdin` JSON):**

  * Common fields: `conversation_id` (`string`), `generation_id` (`string`), `model` (`string`), `model_id` (`string`, optional), `model_params` (`array`, optional), `hook_event_name` (`"beforeSubmitPrompt"`), `cursor_version` (`string`), `workspace_roots` (`string[]`), `user_email` (`string | null`), `transcript_path` (`string | null`).

  * `beforeSubmitPrompt` specific fields: `prompt` (`string`), `attachments` (`Array<{type: "file" | "rule", file_path: string}>`).

  * Environment variables: `CURSOR_PROJECT_DIR`, `CURSOR_VERSION`, `CURSOR_USER_EMAIL`, `CURSOR_TRANSCRIPT_PATH`, `CURSOR_CODE_REMOTE`, `CLAUDE_PROJECT_DIR`.

* **Hook Output Contract (`stdout` JSON & Exit Codes):**

  * For `beforeSubmitPrompt`:

```
{
  "continue": true,
  "user_message": "Optional message shown to the user when the prompt is blocked"
}

```

* For `sessionStart`:

```
{
  "env": {},
  "additional_context": "Optional initial system context for the conversation"
}

```

* For `postToolUse` / `postToolUseFailure`: supports `{"additional_context": "..."}`.

* Exit code `0`: Uses JSON output. Exit code `2`: Blocks the action. Other non-zero exit codes: Fail-open by default unless `failClosed: true`.

* **Hook Capabilities (`beforeSubmitPrompt`) & Honest Limitation:**

  * **(a) Inject context:** **No on `beforeSubmitPrompt`**. Cursor's `beforeSubmitPrompt` output schema only accepts `continue` and `user_message`; `additional_context` is only supported on `sessionStart`, `postToolUse`, and `postToolUseFailure` ([Cursor Hooks Docs](https://cursor.com/docs/hooks); confirmed by open feature requests [#150707](https://forum.cursor.com/t/hooks-allow-beforesubmitprompt-hook-to-inject-additional-context/150707) and [#157231](https://forum.cursor.com/t/add-additional-context-to-beforesubmitprompt-hook-output/157231)).

  * **(b) Replace prompt text:** **No**.

  * **(c) Block:** **Yes** (`continue: false` or exit code `2`).

  * **(d) Show message to user:** **Only when blocked** (`user_message`).

  * **CLI caveat:** Community bug reports note that `cursor-agent` CLI has known regressions where `beforeSubmitPrompt` is skipped in certain CLI/enterprise configurations ([#169059](https://forum.cursor.com/t/cursor-cli-omits-beforesubmitprompt-afteragentresponse-and-stop-hooks-loses-token-usage-and-emits-inconsistent-generation-id-values/169059), [#173219](https://forum.cursor.com/t/cursor-cli-does-not-run-enterprise-or-team-beforesubmitprompt-hooks/173219)).

  * **Fallback Strategy:** We do **not** fake per-prompt injection on `beforeSubmitPrompt`. Instead, the Cursor adapter uses **Tier 2** (installing the universal `SKILL.md` into `.cursor/skills/prompt-compass/SKILL.md` or `.agents/skills/prompt-compass/SKILL.md`) + **Tier 3** (`pcompass-mcp` in `.cursor/mcp.json`), and optionally registers a `sessionStart` hook to inject a compact summary of the workspace capability index at conversation start.

* **Timeouts & Trust/Approvals:**

  * `timeout` is in seconds (platform default if omitted; exact numeric platform default is `UNVERIFIED` in Cursor docs, though a forum report notes a 1s cutoff on some `beforeSubmitPrompt` builds ([#174861](https://forum.cursor.com/t/beforesubmitprompt-does-not-wait-for-the-hook-a-block-returned-after-1-second-is-ignored-and-the-prompt-is-sent/174861))).

  * Project hooks require Workspace Trust to execute.

### Skills, MCP, and Rules Inventory Paths

* **Skills (`SKILL.md` natively supported: Yes):**

  * Project: `.agents/skills/` and `.cursor/skills/` (walks subdirectories recursively and also discovers nested monorepo `<pkg>/.cursor/skills/` and `<pkg>/.agents/skills/`). Also loads `.claude/skills/` and `.codex/skills/` for compatibility.

  * User: `~/.agents/skills/` and `~/.cursor/skills/` (plus `~/.claude/skills/` and `~/.codex/skills/`).

* **MCP Configs (JSON):**

  * Project: `.cursor/mcp.json` (top-level `"mcpServers"` object).

  * User: `~/.cursor/mcp.json` (top-level `"mcpServers"` object).

  * Server entry fields: `type` (`"stdio"`), `command`, `args`, `env`, `envFile`, `url`, `headers`, `auth` (`CLIENT_ID`, `CLIENT_SECRET`, `scopes`).

  * Where secrets live: `env`, `envFile`, `headers`, `auth.CLIENT_SECRET` (supports `${env:NAME}` interpolation).

* **Rules & Instructions Files:**

  * Project rules: `.cursor/rules/**/*.mdc` (YAML frontmatter: `description`, `globs`, `alwaysApply`; plain `.md` files in `.cursor/rules/` are ignored by Cursor).

  * Agent instructions: `AGENTS.md` in project root and nested subdirectories.

  * Legacy: `.cursorrules` in project root.

## 5. GitHub Copilot (VS Code and CLI)

**Primary Sources (Verified 2026-10-20):**

* [GitHub Copilot Hooks Reference (CLI & Cloud Agent)](https://docs.github.com/en/copilot/reference/hooks-reference)

* [Configure Agent Hooks in Visual Studio Code (Preview)](https://code.visualstudio.com/docs/agent-customization/hooks)

* [VS Code Local Hooks Reference](https://code.visualstudio.com/docs/agents/reference/hooks-reference)

* [Use Agent Skills in VS Code](https://code.visualstudio.com/docs/agent-customization/agent-skills)

* [Adding Agent Skills for GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills)

* [VS Code MCP Configuration Reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration)

* [Adding Custom Instructions for GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions)

### Runtime Split: Copilot CLI / Copilot SDK Harness vs. VS Code Local Harness

GitHub Copilot has two distinct hook runtimes documented in the official references:

1. **Copilot CLI & VS Code "Copilot" Session Target** (uses the shared Copilot SDK runtime).

2. **VS Code "Local" Session Target** (runs in the VS Code extension host).

### 5A. Copilot CLI & Copilot SDK Harness

* **Prompt-Submit Events:**

  * `userPromptSubmitted` (or PascalCase `UserPromptSubmit`): Fires when the user submits a prompt. **Critical limitation:** [GitHub Copilot Hooks Reference](https://docs.github.com/en/copilot/reference/hooks-reference) documents that `modifiedPrompt` is only honored by in-process SDK programmatic hooks; *command and HTTP config-file `userPromptSubmitted` hooks have their output dropped, including `modifiedPrompt`*.

  * `userPromptTransformed`: Fires immediately after the runtime transforms a submitted prompt into its model-facing content, before it is sent to the model. **Supports `modifiedTransformedPrompt` in command hooks**, which replaces the model-facing content while leaving the user's timeline display untouched!

* **Config File Locations:**

  * Repository: `.github/hooks/*.json`, inline `hooks` in `.github/copilot/settings.json` or `.github/copilot/settings.local.json` (also reads `.claude/settings.json`).

  * User: `~/.copilot/hooks/*.json` (or `$COPILOT_HOME/hooks/*.json`) and inline `hooks` in `~/.copilot/settings.json`.

  * Policy: `/etc/github-copilot/policy.d/*.json` (Linux/macOS), `C:\ProgramData\GitHub\Copilot\policy.d\*.json` (Windows).

* **Config Schema (`version: 1`):**

```
{
  "version": 1,
  "hooks": {
    "userPromptTransformed": [
      {
        "type": "command",
        "command": "pcompass hook copilot",
        "timeoutSec": 5
      }
    ]
  }
}

```

* Also supports `exec` + `args` (Copilot CLI only) and `bash` / `powershell` platform overrides.

* **Hook Input Fields (`stdin` JSON):**

  * `userPromptSubmitted` (camelCase): `{"sessionId": "string", "timestamp": 1700000000000, "cwd": "string", "prompt": "string"}`.

  * `userPromptTransformed`: `{"sessionId": "string", "timestamp": 1700000000000, "cwd": "string", "prompt": "string", "transformedPrompt": "string"}`.

* **Hook Output Contract (`stdout` JSON):**

  * Progress banner line (optional, single-line JSON before final object):
    `{"type": "progress", "message": "[pcompass] Added brief + routed capabilities", "temporary": true}`

  * Final JSON decision object on `userPromptTransformed`:

```
{
  "modifiedTransformedPrompt": "<original transformedPrompt>\n\n<prompt-compass>...</prompt-compass>"
}

```

* Note: Because `pcompass` appends `<prompt-compass>` to `transformedPrompt`, the original prompt is preserved verbatim and the user's visible chat timeline is untouched.

### 5B. VS Code "Local" Harness

* **Prompt-Submit Event:** `UserPromptSubmit` in `.github/hooks/*.json` or `~/.copilot/hooks/*.json` (PascalCase events without numeric `version`, or mapped from Copilot format).

* **Hook Input Fields (`stdin` JSON):**

  * `timestamp` (`string`, ISO 8601), `cwd` (`string`), `session_id` (`string`), `hook_event_name` (`"UserPromptSubmit"`), `transcript_path` (`string`), `prompt` (`string`).

* **Hook Output Contract & Limitation:**

  * Supports common output only: `{"continue": true, "stopReason": "...", "systemMessage": "..."}` or exit code `2` to block ([VS Code Local Hooks Reference](https://code.visualstudio.com/docs/agents/reference/hooks-reference)).

  * Does **not** support `additionalContext` on `UserPromptSubmit` (`additionalContext` is supported on `SessionStart`, `PreToolUse`, `PostToolUse`, and `SubagentStart`).

  * Therefore, on VS Code Local Harness, `pcompass` relies on **Tier 2 (`SKILL.md`) + Tier 3 (`pcompass-mcp`)** plus `SessionStart` / `SubagentStart` context injection.

* **Timeouts & Trust/Approvals:**

  * Default timeout: `30` seconds (`timeoutSec` in Copilot format, `timeout` in VS Code Local format). Timeouts are always fail-open.

  * Requires Workspace Trust and `chat.useHooks: true`.

### Skills, MCP, and Rules Inventory Paths

* **Skills (`SKILL.md` natively supported: Yes, in both VS Code and Copilot CLI):**

  * Project: `.github/skills/<name>/SKILL.md`, `.claude/skills/<name>/SKILL.md`, `.agents/skills/<name>/SKILL.md`.

  * User: `~/.copilot/skills/<name>/SKILL.md` (or `$COPILOT_HOME/skills`), `~/.claude/skills/<name>/SKILL.md` (VS Code), `~/.agents/skills/<name>/SKILL.md`.

* **MCP Configs (JSON):**

  * **VS Code Format:** `.vscode/mcp.json` (workspace) and User Profile `mcp.json` (`~/.config/Code/User/mcp.json` on Linux, `~/Library/Application Support/Code/User/mcp.json` on macOS, `%APPDATA%\Code\User\mcp.json` on Windows). Uses top-level `"servers"` object (plus `"inputs"` and `"sandbox"`).

  * **Portable Copilot CLI Format:** `.mcp.json` (workspace root) and `~/.copilot/mcp-config.json` (`$COPILOT_HOME/mcp-config.json`). Uses top-level `"mcpServers"` object.

  * Where secrets live: `env`, `envFile` (VS Code format), `headers`, `oauth`, `${input:...}` placeholders.

* **Rules & Instructions Files:**

  * Repository: `.github/copilot-instructions.md`, `.github/instructions/**/*.instructions.md` (YAML frontmatter `applyTo`, `excludeAgent`), `AGENTS.md`, `CLAUDE.md`, `.claude/CLAUDE.md`, `GEMINI.md`.

  * User: `~/.copilot/copilot-instructions.md`, `~/.copilot/instructions/**/*.instructions.md` (or under `$COPILOT_HOME`), plus directories in `COPILOT_CUSTOM_INSTRUCTIONS_DIRS`.

## 6. Windsurf / Devin Desktop (Cascade)

**Primary Sources (Verified 2026-10-20):**

* [Cascade Hooks Documentation](https://docs.windsurf.com/windsurf/cascade/hooks)

* [Cascade MCP Integration Documentation](https://docs.windsurf.com/windsurf/cascade/mcp)

* [Cascade Skills Documentation](https://docs.devin.ai/desktop/cascade/skills)

* [Cascade Memories & Rules Documentation](https://docs.windsurf.com/windsurf/cascade/memories)

*(Note: In 2026, Cognition unified Windsurf into Devin Desktop. The Cascade agent reads `.devin/` paths first and falls back to `.windsurf/` and `~/.codeium/windsurf/`. Prompt Compass scans and supports both path families.)*

### Hook Event & Configuration

* **Prompt-Submit Event:** `pre_user_prompt` fires before Cascade processes the text of a user's prompt.

* **Config File Locations:**

  * User scope: `~/.codeium/windsurf/hooks.json` (IDE) and `~/.codeium/hooks.json` (JetBrains plugin).

  * Workspace scope: `.devin/hooks.json` (preferred) or `.windsurf/hooks.json` (legacy fallback when `.devin/hooks.json` is absent).

  * System scope: `/Library/Application Support/Devin/hooks.json` or `/Library/Application Support/Windsurf/hooks.json` (macOS), `/etc/devin/hooks.json` or `/etc/windsurf/hooks.json` (Linux/WSL), `C:\ProgramData\Devin\hooks.json` or `C:\ProgramData\Windsurf\hooks.json` (Windows).

* **Config Schema (`hooks.json`):**

```
{
  "hooks": {
    "pre_user_prompt": [
      {
        "command": "python3 /absolute/path/to/hook.py",
        "powershell": "python3 C:\\absolute\\path\\to\\hook.py",
        "working_directory": "/absolute/path/to/workspace"
      }
    ]
  }
}

```

* Note: `~` home directory expansion is not supported in `hooks.json`.

* **Hook Input Fields (`stdin` JSON):**

  * `agent_action_name` (`string`): `"pre_user_prompt"`.

  * `trajectory_id` (`string`): Unique identifier for the Cascade conversation.

  * `execution_id` (`string`): Unique identifier for the single agent turn.

  * `timestamp` (`string`): ISO 8601 timestamp.

  * `model_name` (`string`): Human-readable model label in Cascade selector.

  * `tool_info` (`object`): `{"user_prompt": "string"}`.

* **Hook Output Contract & Honest Limitation:**

  * Exit code `0`: Action proceeds normally; `stdout` is NOT injected into Cascade's model prompt.

  * Exit code `2`: Blocks the prompt; `stderr` is shown to the user/agent as a blocking error.

  * Other exit codes: Action proceeds normally (fail-open).

  * [Cascade Hooks Docs](https://docs.windsurf.com/windsurf/cascade/hooks) explicitly state: *"The `show_output` configuration option does not apply to this hook \[`pre_user_prompt`\]."*

  * **Capabilities (`pre_user_prompt`):**

    * **(a) Inject context:** **No**.

    * **(b) Replace prompt text:** **No**.

    * **(c) Block:** **Yes** (exit code `2` + `stderr`).

    * **(d) Show message to user:** **Only when blocking** (`show_output` is disabled on `pre_user_prompt`).

  * **Fallback Strategy:** Because `pre_user_prompt` cannot inject context or rewrite prompts, Windsurf/Cascade defaults to **Tier 2 (`SKILL.md` in `.devin/skills/` or `.windsurf/skills/` or `.agents/skills/`) + Tier 3 (`pcompass-mcp` in `mcp_config.json`)**.

* **Timeouts & Trust/Approvals:**

  * Docs recommend sub-100ms execution times; exact hard kill timeout in seconds/ms is `UNVERIFIED` in official documentation.

  * Hooks do not load or run when a workspace is open in **Restricted Mode**.

### Skills, MCP, and Rules Inventory Paths

* **Skills (`SKILL.md` natively supported: Yes):**

  * Workspace: `.devin/skills/<name>/SKILL.md` (preferred), `.windsurf/skills/<name>/SKILL.md` (legacy), `.agents/skills/<name>/SKILL.md`, and `.claude/skills/<name>/SKILL.md` (when Claude config reading is enabled).

  * Global/User: `~/.codeium/windsurf/skills/<name>/SKILL.md`, `~/.config/devin/skills/<name>/SKILL.md`, `~/.agents/skills/<name>/SKILL.md`.

  * System: `/Library/Application Support/Devin/skills/` or `/Library/Application Support/Windsurf/skills/` (macOS), `/etc/devin/skills/` or `/etc/windsurf/skills/` (Linux/WSL), `C:\ProgramData\Devin\skills\` or `C:\ProgramData\Windsurf\skills\` (Windows).

* **MCP Configs (JSON):**

  * User/Global: `~/.codeium/windsurf/mcp_config.json` and `~/.config/devin/mcp_config.json` (`%APPDATA%\devin\mcp_config.json` on Windows).

  * Format: Top-level `"mcpServers"` object (`command`, `args`, `env`, `disabledTools`, `serverUrl` or `url`, `headers`). Note: Cascade enforces a 100-tool limit across active MCP servers.

  * Where secrets live: `env` and `headers` (supports `${env:VAR_NAME}` and `${file:/path/to/file}`).

* **Rules & Instructions Files:**

  * Global: `~/.codeium/windsurf/memories/global_rules.md` (always on, max 6,000 chars).

  * Workspace: `.devin/rules/*.md` (preferred), `.windsurf/rules/*.md` (fallback; YAML frontmatter `trigger: always_on | model_decision | glob | manual`, `globs`; max 12,000 chars/file), legacy `.windsurfrules` at workspace root, and `AGENTS.md` (root = always-on, subdirectory = auto-glob).

  * Workflows: `.devin/workflows/*.md` and `.windsurf/workflows/*.md` (invoked via `/[workflow-name]`).

## 7. Generic MCP Clients (Claude Desktop, Continue, Cline, Roo Code, OpenCode, Goose, Zed)

* **Hook Event:** `UNVERIFIED` / Not in the Model Context Protocol specification (individual hosts outside the 6 above do not share a standardized prompt-submit hook schema).

* **Skills (`SKILL.md`):** Clients adopting the [Agent Skills Open Standard](https://github.com/vercel-labs/skills) read `.agents/skills/<name>/SKILL.md` (project) and `~/.agents/skills/<name>/SKILL.md` (user).

* **MCP Configs:** Standard `"mcpServers"` JSON block (e.g., Claude Desktop at `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `~/.config/Claude/claude_desktop_config.json` on Linux, `%APPDATA%\Claude\claude_desktop_config.json` on Windows, verified via [VS Code MCP Discovery Docs](https://code.visualstudio.com/docs/agents/reference/mcp-configuration)).

* **Delivery Tier:** **Tier 3 (`pcompass-mcp` stdio server + `pcompass` CLI)** and **Tier 2 (`SKILL.md` in `.agents/skills/prompt-compass/`)**.

## Summary of Items Marked `UNVERIFIED`

1. **Cursor default hook timeout numeric value:** [Cursor Hooks Docs](https://cursor.com/docs/hooks) list the default for `timeout` as `"platform default"` without stating the exact number of seconds (community forum reports observe \~1s on `beforeSubmitPrompt` in some versions).

2. **Windsurf / Devin Desktop hard hook timeout numeric value:** [Cascade Hooks Docs](https://docs.windsurf.com/windsurf/cascade/hooks) advise aiming for `<100ms` execution time but do not publish the exact process kill timeout.

3. **Generic MCP client prompt hooks:** No MCP protocol-level prompt-submit hook exists; generic clients must use Tier 2 (`SKILL.md`) or Tier 3 (`pcompass-mcp`).