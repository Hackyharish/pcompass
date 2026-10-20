# Configuration Reference (`docs/CONFIGURATION.md`)

Prompt Compass works out of the box with zero configuration. You can customize behavior per repository via `.promptcompass/config.json` (or `.promptcompass.json`) and environment variables.

## `.promptcompass/config.json` Schema

```json
{
  "mode": "suggest",
  "max_added_tokens": 400,
  "top_k_routes": 5,
  "min_route_score": 1.2,
  "hook_timeout_ms": 1500,
  "recommend_enabled": true,
  "disabled_capabilities": [
    "mcp:gemini-cli:project:experimental"
  ]
}
```

### Fields

| Field | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `mode` | `"suggest" \| "rewrite" \| "off"` | `"suggest"` | `"suggest"` injects `<prompt-compass>` context and displays a one-line banner; `"off"` disables Prompt Compass for the project. |
| `max_added_tokens` | `int` (`50..400`) | `400` | Strict ceiling on tokens added by `<prompt-compass>`. |
| `top_k_routes` | `int` (`1..5`) | `5` | Maximum number of installed capabilities to route per prompt. |
| `min_route_score` | `float` | `1.2` | Minimum BM25 + project-signal score required to include a capability. |
| `hook_timeout_ms` | `int` | `1500` | Hook execution timeout budget in milliseconds (fail-open). |
| `recommend_enabled` | `bool` | `true` | Whether `pcompass brief` includes vetted registry candidates when fewer than 2 local capabilities match. |
| `disabled_capabilities` | `string[]` | `[]` | List of capability IDs to exclude from routing. |

## Environment Variables

| Variable | Values | Effect |
| :--- | :--- | :--- |
| `PCOMPASS_DISABLE` | `1`, `true`, `yes`, `on` | Immediately bypasses Prompt Compass (0 tokens added, exit `0`). |
| `PCOMPASS_MODE` | `suggest`, `rewrite`, `off` | Overrides `mode` from `.promptcompass/config.json`. |
| `PCOMPASS_LLM` | `on`, `off` (default `off`) | Optional opt-in LLM tie-breaker mode (disabled by default for privacy and latency). |

## Per-Prompt Bypass Prefixes

- `* <prompt>`: Strips the leading `*` and bypasses Prompt Compass for that turn.
- `/<command>`: Treated as an agent slash command and skipped untouched.
- `# <note>`: Single-line memory note skipped untouched.
