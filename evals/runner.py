"""Evaluation harness for Prompt Compass against evals/prompts.jsonl."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pcompass.core.index import build_or_load_index
from pcompass.core.policy import PolicyConfig, evaluate_skip
from pcompass.core.render import render_prompt_compass_block
from pcompass.core.restructure import restructure_prompt
from pcompass.core.router import route_prompt

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
PROMPTS_FILE = REPO_ROOT / "evals" / "prompts.jsonl"


def run_eval_suite(verbose: bool = True) -> dict[str, Any]:
    index = build_or_load_index(
        project_dir=FIXTURES_DIR / "project_dir",
        home_dir=FIXTURES_DIR / "home_dir",
        bin_dirs=[FIXTURES_DIR / "bin_dir"],
        use_cache=False,
    )
    policy = PolicyConfig()

    cases: list[dict[str, Any]] = []
    with PROMPTS_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                cases.append(json.loads(line))

    skip_total = 0
    false_rewrites = 0

    route_total = 0
    route_top3_hits = 0

    ambig_total = 0
    ambig_question_hits = 0

    max_tokens_observed = 0
    latencies_ms: list[float] = []
    failures: list[str] = []

    for case in cases:
        cid = case["id"]
        prompt = case["prompt"]
        expect_skip = bool(case["expect_skip"])
        expected_routes = list(case.get("expected_routes", []))
        expect_questions = bool(case.get("expect_questions", False))

        t0 = time.perf_counter()
        skip_dec = evaluate_skip(prompt, policy)
        if skip_dec.should_skip:
            rendered = None
            routed_ids: list[str] = []
            added_tokens = 0
            actually_skipped = True
            open_q_count = 0
        else:
            brief = restructure_prompt(prompt, signals=index.signals)
            routed = route_prompt(prompt, index, top_k=5, min_score=policy.min_route_score)
            rendered = render_prompt_compass_block(
                brief=brief,
                routed=routed,
                recommendations=[],
                mode=policy.mode,
                max_added_tokens=policy.max_added_tokens,
            )
            actually_skipped = rendered.skipped
            routed_ids = [r.id for r in rendered.routed]
            added_tokens = rendered.added_tokens_estimate
            open_q_count = len(brief.open_questions)

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(elapsed_ms)
        max_tokens_observed = max(max_tokens_observed, added_tokens)

        if added_tokens > 400:
            failures.append(f"{cid}: exceeded 400 token budget ({added_tokens} tokens)")

        if expect_skip:
            skip_total += 1
            if not actually_skipped or added_tokens > 0:
                false_rewrites += 1
                failures.append(f"{cid}: false rewrite on skip/clear prompt (added_tokens={added_tokens})")

        if expected_routes:
            route_total += 1
            top3 = set(routed_ids[:3])
            if any(exp in top3 for exp in expected_routes):
                route_top3_hits += 1
            else:
                failures.append(f"{cid}: expected one of {expected_routes} in top-3, got {routed_ids[:3]}")

        if expect_questions:
            ambig_total += 1
            if 1 <= open_q_count <= 2:
                ambig_question_hits += 1
            else:
                failures.append(f"{cid}: expected 1-2 open questions on ambiguous prompt, got {open_q_count}")

    latencies_ms.sort()
    p50_ms = latencies_ms[len(latencies_ms) // 2] if latencies_ms else 0.0
    p95_ms = latencies_ms[int(len(latencies_ms) * 0.95) - 1] if latencies_ms else 0.0

    recall_top3 = (route_top3_hits / max(1, route_total)) * 100.0
    false_rewrite_rate = (false_rewrites / max(1, skip_total)) * 100.0
    ambig_accuracy = (ambig_question_hits / max(1, ambig_total)) * 100.0

    summary = {
        "total_prompts": len(cases),
        "route_cases": route_total,
        "route_top3_hits": route_top3_hits,
        "routing_recall_top3_pct": round(recall_top3, 2),
        "skip_cases": skip_total,
        "false_rewrites": false_rewrites,
        "false_rewrite_rate_pct": round(false_rewrite_rate, 2),
        "ambiguous_cases": ambig_total,
        "ambiguous_question_hits": ambig_question_hits,
        "ambiguous_question_accuracy_pct": round(ambig_accuracy, 2),
        "max_added_tokens": max_tokens_observed,
        "latency_p50_ms": round(p50_ms, 2),
        "latency_p95_ms": round(p95_ms, 2),
        "failures": failures,
    }

    if verbose:
        print("=== Prompt Compass Golden Evaluation Suite ===")
        print(f"Total golden prompts evaluated : {summary['total_prompts']}")
        print(f"Top-3 Routing Recall           : {summary['routing_recall_top3_pct']:.1f}% ({route_top3_hits}/{route_total}) [Target >= 80.0%]")
        print(f"False-Rewrite Rate (Clear/Skip): {summary['false_rewrite_rate_pct']:.1f}% ({false_rewrites}/{skip_total}) [Target < 5.0%]")
        print(f"Ambiguity Question Precision   : {summary['ambiguous_question_accuracy_pct']:.1f}% ({ambig_question_hits}/{ambig_total})")
        print(f"Max Added Tokens Observed      : {summary['max_added_tokens']} tokens [Budget <= 400]")
        print(f"End-to-End Latency             : p50={summary['latency_p50_ms']:.2f} ms, p95={summary['latency_p95_ms']:.2f} ms [Target < 300 ms]")
        if failures:
            print("Failures:")
            for fail in failures:
                print(f"  - {fail}")
    return summary


if __name__ == "__main__":
    res = run_eval_suite(verbose=True)
    if res["routing_recall_top3_pct"] < 80.0 or res["false_rewrite_rate_pct"] >= 5.0 or res["max_added_tokens"] > 400:
        sys.exit(1)
