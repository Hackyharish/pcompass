## Summary
-

## Verification Checklist
- [ ] Verified any hook/config schema changes against official documentation and updated `docs/COMPATIBILITY.md`
- [ ] Confirmed zero third-party dependencies added to `pcompass/core/`
- [ ] `python3 -m unittest discover -v -s tests` passes
- [ ] `python3 evals/runner.py` meets all recall (>=80%), false-rewrite (<5%), token (<=400), and latency (<300ms) targets
