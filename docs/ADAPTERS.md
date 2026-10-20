# Writing a New Agent Adapter (`docs/ADAPTERS.md`)

Each coding agent adapter in `pcompass/adapters/` is a thin (~100–180 line) module implementing the `Adapter` protocol defined in `pcompass/adapters/base.py`. All inventory scanning, BM25 routing, prompt restructuring, and sanitization live in `pcompass/core/`.

## The `Adapter` Protocol

```python
class Adapter(Protocol):
    id: str
    def detect(self) -> bool: ...
    def paths(self) -> AgentPaths: ...
    def caps(self) -> AdapterCaps: ...
    def parse_hook_input(self, raw: dict[str, Any]) -> HookInput: ...
    def render_hook_output(self, out: RenderedOutput, hook_input: HookInput | None = None) -> str | dict[str, Any]: ...
    def setup(self, scope: str = "project", dry_run: bool = False) -> list[Change]: ...
    def uninstall(self, scope: str = "project", dry_run: bool = False) -> list[Change]: ...
```

## Checklist for Adding an Adapter

1. **Verify Official Documentation First:** Record the exact hook event name, config path, stdin JSON fields, and stdout contract in `docs/COMPATIBILITY.md` with source URLs and date. Never guess field names.
2. **Declare Honest Capabilities (`caps()`):** If the agent's prompt-submit hook cannot inject context or replace the prompt (such as Cursor's `beforeSubmitPrompt` or Windsurf's `pre_user_prompt`), set `can_inject=False`, `primary_tier=2`, and wire Tier 2 (`SKILL.md`) + Tier 3 (`pcompass-mcp`) in `setup()`.
3. **Idempotent `setup()` and `uninstall()`:** Use `backup_and_write_text` from `pcompass/adapters/base.py` so existing user settings are backed up to `.bak` and merged cleanly without clobbering unrelated keys.
4. **Register & Test:** Add your adapter class to `ADAPTER_CLASSES` in `pcompass/adapters/__init__.py` and add contract + idempotency tests in `tests/`.
