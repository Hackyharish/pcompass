# Contributing to Prompt Compass

Thank you for contributing to Prompt Compass! We keep the core small, boring, deterministic, and well-tested.

## Core Engineering Rules

1. **Standard Library Only in `pcompass/core/`:** Do not add third-party runtime dependencies to the core package. Hook cold start must remain well under 300 ms p95.
2. **Verify Against Official Docs:** Never guess agent hook schemas or config paths. Cite the official documentation URL and date in `docs/COMPATIBILITY.md`.
3. **Zero Secrets on Disk:** Any parser touching MCP or agent config files must strip `env` values, `headers`, and tokens at parse time and add a corresponding secret-leak assertion in `tests/`.
4. **Run the Full Test & Eval Suite Before Submitting a PR:**
   ```bash
   python3 -m unittest discover -v -s tests
   python3 evals/runner.py
   ```
