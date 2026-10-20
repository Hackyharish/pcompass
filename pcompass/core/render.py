"""Render structured Brief + Routing + Recommendations within the <=400 token budget."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from pcompass.core.restructure import PromptBrief
from pcompass.core.router import RoutedCapability
from pcompass.core.sanitize import sanitize_text


@dataclass(frozen=True)
class CandidateRecommendation:
    """A security-scanned external capability candidate (never auto-installed)."""

    id: str
    kind: str
    name: str
    source: str
    reason: str
    trust_score: int
    risk_flags: list[str] = field(default_factory=list)
    install_cmd: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RenderedOutput:
    """Rendered output ready for an agent adapter or CLI."""

    skipped: bool
    skip_reason: str
    mode: str
    original_prompt: str
    context_block: str
    banner: str
    added_tokens_estimate: int
    brief: PromptBrief | None = None
    routed: list[RoutedCapability] = field(default_factory=list)
    recommendations: list[CandidateRecommendation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "mode": self.mode,
            "original_prompt": self.original_prompt,
            "context_block": self.context_block,
            "banner": self.banner,
            "added_tokens_estimate": self.added_tokens_estimate,
            "brief": self.brief.to_dict() if self.brief else None,
            "routed": [r.to_dict() for r in self.routed],
            "recommendations": [rec.to_dict() for rec in self.recommendations],
        }


def estimate_tokens(text: str) -> int:
    """Conservative token estimator (~3.8 chars per token + word boundary count)."""
    if not text:
        return 0
    char_est = (len(text) + 3) // 4
    word_est = int(len(text.split()) * 1.35)
    return max(char_est, word_est)


def render_prompt_compass_block(
    brief: PromptBrief,
    routed: list[RoutedCapability],
    recommendations: list[CandidateRecommendation] | None = None,
    mode: str = "suggest",
    max_added_tokens: int = 400,
) -> RenderedOutput:
    """Format `<prompt-compass>` block while strictly enforcing the <=400 added token budget."""
    recs = recommendations or []

    if brief.is_clear_and_specific and not routed and not recs and not brief.open_questions:
        return RenderedOutput(
            skipped=True,
            skip_reason="clear_and_no_special_routes",
            mode=mode,
            original_prompt=brief.original_prompt,
            context_block="",
            banner="",
            added_tokens_estimate=0,
            brief=brief,
            routed=[],
            recommendations=[],
        )

    orig_display = brief.original_prompt.strip().replace("</prompt-compass>", "")
    if len(orig_display) > 280:
        orig_display = orig_display[:277] + "..."

    def _assemble(
        include_brief_details: bool,
        route_limit: int,
        rec_limit: int,
        include_questions: bool,
    ) -> tuple[str, int]:
        body_lines: list[str] = []
        if include_brief_details:
            body_lines.append("Brief:")
            body_lines.append(f"- Goal: {sanitize_text(brief.goal, max_len=140)}")
            if brief.context_found:
                body_lines.append(f"- Context found: {sanitize_text('; '.join(brief.context_found), max_len=130)}")
            if brief.constraints:
                body_lines.append(f"- Constraints: {sanitize_text('; '.join(brief.constraints), max_len=130)}")
            body_lines.append(f"- Done when: {sanitize_text(brief.done_when, max_len=120)}")

        active_routes = routed[:route_limit]
        if active_routes:
            body_lines.append("Use (installed):")
            for r in active_routes:
                safe_name = sanitize_text(r.name, max_len=40)
                safe_reason = sanitize_text(r.reason, max_len=110)
                body_lines.append(f"- {r.kind} `{safe_name}`: {safe_reason}")

        active_recs = recs[:rec_limit]
        if active_recs:
            body_lines.append("Consider (NOT installed; ask the user before doing anything):")
            for c in active_recs:
                safe_cname = sanitize_text(c.name, max_len=45)
                safe_creason = sanitize_text(c.reason, max_len=90)
                flags_str = ", ".join(c.risk_flags) if c.risk_flags else "none"
                body_lines.append(
                    f"- `{safe_cname}`: {safe_creason}; trust: {c.trust_score}/100; risks: {flags_str}"
                )

        if include_questions and brief.open_questions:
            q_joined = " | ".join(sanitize_text(q, max_len=120) for q in brief.open_questions[:2])
            body_lines.append(f"Open questions (only if blocking): {q_joined}")

        full_lines = [
            "<prompt-compass>",
            f"Original request (verbatim): {orig_display}",
            *body_lines,
            "</prompt-compass>",
        ]
        full_block = "\n".join(full_lines)
        added_only_text = "<prompt-compass>\n" + "\n".join(body_lines) + "\n</prompt-compass>"
        return full_block, estimate_tokens(added_only_text)

    configs_to_try = [
        (True, min(5, len(routed)), min(2, len(recs)), True),
        (True, min(3, len(routed)), min(1, len(recs)), True),
        (True, min(2, len(routed)), 0, True),
        (False, min(2, len(routed)), 0, True),
        (False, min(1, len(routed)), 0, False),
    ]

    chosen_block = ""
    chosen_tokens = 0
    for inc_brief, r_lim, c_lim, inc_q in configs_to_try:
        blk, tok = _assemble(inc_brief, r_lim, c_lim, inc_q)
        chosen_block = blk
        chosen_tokens = tok
        if tok <= max_added_tokens:
            break

    banner_parts: list[str] = [f"intent={brief.intent}"]
    if routed:
        top_names = ", ".join(f"{r.kind}:{r.name}" for r in routed[:3])
        banner_parts.append(f"routed=[{top_names}]")
    if brief.open_questions:
        banner_parts.append(f"questions={len(brief.open_questions)}")
    banner = f"[pcompass] Added brief ({', '.join(banner_parts)}, +{chosen_tokens} tokens)"

    return RenderedOutput(
        skipped=False,
        skip_reason="",
        mode=mode,
        original_prompt=brief.original_prompt,
        context_block=chosen_block,
        banner=banner,
        added_tokens_estimate=chosen_tokens,
        brief=brief,
        routed=routed,
        recommendations=recs,
    )
