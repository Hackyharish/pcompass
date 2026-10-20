"""Unit and evaluation tests for Phase 2 (policy, restructure, render, evals)."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.runner import run_eval_suite
from pcompass.core.index import build_or_load_index
from pcompass.core.policy import PolicyConfig, evaluate_skip
from pcompass.core.render import CandidateRecommendation, render_prompt_compass_block
from pcompass.core.restructure import detect_intent, extract_slots, restructure_prompt
from pcompass.core.router import route_prompt

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class TestPolicyAndSkipRules(unittest.TestCase):
    def test_bypass_prefixes_and_confirmations(self) -> None:
        cfg = PolicyConfig()
        for p in ("yes", "continue", "go ahead", "LGTM", "* skip this", "/compact", "# note for memory"):
            dec = evaluate_skip(p, cfg)
            self.assertTrue(dec.should_skip, f"Expected skip for {p!r}")

    def test_env_disable_and_mode_off(self) -> None:
        cfg = PolicyConfig.load(env={"PCOMPASS_DISABLE": "1"})
        self.assertEqual(cfg.mode, "off")
        self.assertTrue(evaluate_skip("Build a complex microservice", cfg).should_skip)

    def test_pasted_logs_with_clear_ask_skips(self) -> None:
        log_prompt = (
            "Fix this crash in worker.py:\n"
            "Traceback (most recent call last):\n"
            "  File \"worker.py\", line 19, in run\n"
            "  File \"db.py\", line 88, in connect\n"
            "ERROR: ConnectionRefusedError: [Errno 111] Connection refused\n"
            "2026-10-20 10:00:00 ERROR retrying"
        )
        self.assertTrue(evaluate_skip(log_prompt).should_skip)


class TestRestructureAndRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = build_or_load_index(
            project_dir=FIXTURES_DIR / "project_dir",
            home_dir=FIXTURES_DIR / "home_dir",
            bin_dirs=[FIXTURES_DIR / "bin_dir"],
            use_cache=False,
        )

    def test_slot_extraction_and_intent(self) -> None:
        prompt = (
            "Fix `ValueError: invalid token` in `src/auth/jwt_handler.py` when calling "
            "`verify_signature()` on Python 3.12 (see https://example.com/issue/42). "
            "Do not modify the public function signature."
        )
        intent, _ = detect_intent(prompt)
        self.assertEqual(intent, "fix")
        slots = extract_slots(prompt)
        self.assertIn("src/auth/jwt_handler.py", slots.files)
        self.assertTrue(any("verify_signature" in s for s in slots.symbols))
        self.assertTrue(any("ValueError" in e for e in slots.errors))
        self.assertIn("https://example.com/issue/42", slots.urls)

    def test_ambiguous_prompt_produces_at_most_2_questions(self) -> None:
        brief = restructure_prompt("fix it", signals=self.index.signals)
        self.assertGreaterEqual(brief.ambiguity_score, 0.6)
        self.assertGreaterEqual(len(brief.open_questions), 1)
        self.assertLessEqual(len(brief.open_questions), 2)

    def test_token_budget_strictly_enforced_under_400(self) -> None:
        long_prompt = (
            "Build a full end-to-end Playwright test suite and PostgreSQL migration "
            "and Kubernetes Helm audit and GitHub Actions workflow debugger and Sentry check "
            "with strict backwards compatibility and zero downtime."
        )
        brief = restructure_prompt(long_prompt, signals=self.index.signals)
        routed = route_prompt(long_prompt, self.index, top_k=5)
        recs = [
            CandidateRecommendation(
                id="mcp:registry:redis",
                kind="mcp",
                name="redis-mcp",
                source="registry.modelcontextprotocol.io",
                reason="Caching layer inspection for session tokens",
                trust_score=88,
                risk_flags=[],
                install_cmd="pcompass install mcp:registry:redis",
            )
        ]
        rendered = render_prompt_compass_block(brief, routed, recs, max_added_tokens=400)
        self.assertFalse(rendered.skipped)
        self.assertLessEqual(rendered.added_tokens_estimate, 400)
        self.assertIn("<prompt-compass>", rendered.context_block)
        self.assertIn("Original request (verbatim):", rendered.context_block)
        self.assertIn("Use (installed):", rendered.context_block)

    def test_golden_eval_suite_meets_all_targets(self) -> None:
        summary = run_eval_suite(verbose=False)
        self.assertGreaterEqual(summary["total_prompts"], 60)
        self.assertGreaterEqual(summary["routing_recall_top3_pct"], 80.0)
        self.assertLess(summary["false_rewrite_rate_pct"], 5.0)
        self.assertLessEqual(summary["max_added_tokens"], 400)
        self.assertLess(summary["latency_p95_ms"], 300.0)
        self.assertEqual(summary["failures"], [])


if __name__ == "__main__":
    unittest.main()
