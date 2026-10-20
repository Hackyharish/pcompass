# Prompt Compass Output Schema Reference

## `<prompt-compass>` Injected Context Block

```xml
<prompt-compass>
Original request (verbatim): <user prompt preserved untouched>
Brief:
- Goal: [<INTENT>] <concise one-sentence summary>
- Context found: <extracted files, symbols, errors, versions, workspace signals>
- Constraints: <explicit negative constraints or workspace defaults>
- Done when: <testable completion criteria>
Use (installed):
- skill `<name>`: <deterministic routing reason>
- mcp `<name>`: <deterministic routing reason>
Consider (NOT installed; ask the user before doing anything):
- `<candidate>`: <reason>; trust: <score>/100; risks: <flags>
Open questions (only if blocking): <at most 2 clarifying questions>
</prompt-compass>
```

## Token Budget Invariant

- Complex / ambiguous prompts: `<= 400` added tokens.
- Clear / trivial / bypass (`*`, `/`, `#`) prompts: `0` added tokens (skipped).
