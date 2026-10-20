# Security Policy

## Security Invariants

Prompt Compass sits in the prompt intake path of coding agents and treats all third-party skill files, MCP server configs, and registry metadata as **untrusted input**:

1. **No Secret Persistence:** MCP `env` values, HTTP `headers`, OAuth secrets, and CLI `--token`/`--header` flags are stripped at parse time and never written to `.promptcompass/cache/index.json`.
2. **No Verbatim Third-Party Descriptions in Context:** Routing reasons are synthesized deterministically by Prompt Compass and passed through `pcompass/core/sanitize.py` to strip XML closing tags (`</prompt-compass>`), zero-width/bidi characters, and prompt-injection imperatives.
3. **Never Auto-Install:** Hooks never install packages or make network calls. `pcompass install` requires explicit user confirmation and blocks any candidate flagged by `pcompass/recommend/scan.py`.

## Reporting a Vulnerability

Please report security vulnerabilities (such as sanitizer bypasses, secret-redaction misses, or static scanner evasions) privately via GitHub Security Advisories rather than public issues. We aim to acknowledge reports within 48 hours and ship a regression test and patch within 7 days.
