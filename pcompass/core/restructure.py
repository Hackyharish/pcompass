"""Deterministic rule-based prompt restructurer for Prompt Compass."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
import re
from typing import Any

from pcompass.core.index import ProjectSignals

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "fix": ("fix", "bug", "error", "broken", "crash", "failing", "fail", "issue", "exception", "regression", "timeout", "500", "404", "debug", "resolve"),
    "add": ("add", "create", "implement", "build", "introduce", "support", "feature", "new", "scaffold", "wire"),
    "refactor": ("refactor", "clean", "cleanup", "restructure", "simplify", "modularize", "extract", "deduplicate", "rename", "optimize"),
    "explain": ("explain", "why", "how", "walkthrough", "understand", "clarify", "what", "describe", "trace"),
    "review": ("review", "audit", "check", "inspect", "security", "vulnerability", "lint", "critique", "pr"),
    "test": ("test", "tests", "testing", "pytest", "unittest", "playwright", "e2e", "coverage", "spec", "mock"),
    "deploy": ("deploy", "release", "publish", "ci", "cd", "pipeline", "docker", "kubernetes", "k8s", "helm", "terraform", "staging", "production"),
    "research": ("research", "compare", "survey", "investigate", "evaluate", "benchmark", "explore", "find", "discover"),
    "write": ("write", "document", "docs", "readme", "changelog", "adr", "report", "draft", "slide", "presentation", "pdf", "docx"),
    "data": ("data", "csv", "xlsx", "excel", "sql", "query", "migration", "schema", "database", "postgres", "sqlite", "table", "parse", "extract"),
}

_FILE_RE = re.compile(
    r"(?:[a-zA-Z0-9_.-]+/)+[a-zA-Z0-9_.-]+\.[a-zA-Z0-9]{1,8}\b"
    r"|\b[a-zA-Z0-9_-]+\.(?:py|ts|tsx|js|jsx|rs|go|rb|java|md|mdc|json|toml|ya?ml|sql|sh|css|html|pdf|xlsx|csv|docx|pptx|dockerfile)\b",
    re.IGNORECASE,
)

_SYMBOL_RE = re.compile(
    r"`([a-zA-Z_][a-zA-Z0-9_.:()-]{2,60})`"
    r"|\b([a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_.]*(?:\(\))?)"
    r"|\b([a-z]+(?:_[a-z0-9]+){1,4})\b"
    r"|\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b"
)

_ERROR_RE = re.compile(
    r"\b([A-Z][a-zA-Z0-9_]*(?:Error|Exception|Warning|Fault|Panic)(?::\s*[^\n.;]{1,80})?)\b"
    r"|\b(HTTP\s+[45]\d{2}|status\s+code\s+[45]\d{2}|[45]\d{2}\s+(?:Bad\s+Gateway|Internal\s+Server\s+Error|Not\s+Found|Unauthorized|Forbidden|Gateway\s+Timeout))\b"
    r"|\b(E[A-Z0-9]{3,12}|ENOENT|EACCES|ECONNREFUSED|ETIMEDOUT|Segfault|SIGSEGV|OOMKilled|CrashLoopBackOff)\b"
)

_URL_RE = re.compile(r"https?://[^\s)>\]\"']+")

_VERSION_RE = re.compile(
    r"\b(?:v?\d+\.\d+(?:\.\d+)?(?:-[a-zA-Z0-9.]+)?|python\s*3\.\d+|node\s*\d+|react\s*\d+)\b",
    re.IGNORECASE,
)

_CONSTRAINT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)\b(do\s+not|don't|must\s+not|never|without\s+\w+|avoid\s+\w+|keep\s+\w+|preserve\s+\w+|only\s+use|stdlib\s+only|no\s+external|backwards[- ]compatible)[^.;\n]{0,90}"),
    re.compile(r"(?i)\b(under\s+\d+\s*(?:ms|s|mb|kb|tokens|lines)|at\s+most\s+\d+[^.;\n]{0,50}|p95\s*<\s*\d+[^.;\n]{0,30})"),
]

_CONFLICT_PAIRS: list[tuple[re.Pattern[str], re.Pattern[str], str]] = [
    (
        re.compile(r"(?i)\b(no\s+new\s+dependencies|stdlib\s+only|zero\s+dependencies|without\s+external\s+packages)\b"),
        re.compile(r"(?i)\b(use\s+(?:pandas|sqlalchemy|pydantic|axios|lodash|fastapi|express)|install\s+\w+)\b"),
        "Request asks for zero external dependencies while also naming a third-party library—which should take precedence?",
    ),
    (
        re.compile(r"(?i)\b(do\s+not\s+modify|don't\s+touch|read[- ]only|without\s+changing)\s+(?:the\s+)?(database|schema|api|public\s+interface)\b"),
        re.compile(r"(?i)\b(add\s+a?\s*column|drop\s+column|rename\s+field|change\s+the\s+response\s+schema|migrate\s+the\s+table)\b"),
        "Request asks to preserve the existing schema/API unchanged while also requesting a schema or field change—should this be additive/versioned instead?",
    ),
    (
        re.compile(r"(?i)\b(delete|remove|drop)\s+all\s+legacy\b"),
        re.compile(r"(?i)\b(maintain\s+100%\s+backward|keep\s+legacy\s+clients\s+working|no\s+breaking\s+changes)\b"),
        "Request asks to remove legacy code while keeping legacy callers working without breaking changes—should we deprecate with a compatibility shim first?",
    ),
]

DEFAULT_DONE_WHEN: dict[str, str] = {
    "fix": "Root cause is resolved, reproduction case passes, and existing tests pass without regressions.",
    "add": "Feature is implemented cleanly, wired into existing entrypoints, and covered by unit/integration tests.",
    "refactor": "Code structure is simplified with identical external behavior and all existing tests passing.",
    "explain": "Clear explanation references concrete file paths, symbols, and control flow in the workspace.",
    "review": "Findings list concrete file/line issues ordered by severity with actionable remediation steps.",
    "test": "Automated tests cover happy path and edge cases and pass deterministically.",
    "deploy": "Deployment/CI manifests validate cleanly with health checks and rollback safety.",
    "research": "Comparison cites verified sources, trade-offs, and a concrete recommendation for this codebase.",
    "write": "Documentation or artifact is accurate, well-structured, and grounded in current repo state.",
    "data": "Data transformation or schema migration is validated, reversible, and preserves data integrity.",
}


@dataclass(frozen=True)
class ExtractedSlots:
    """Concrete entities extracted deterministically from the user prompt."""

    files: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    versions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def is_empty(self) -> bool:
        return not (self.files or self.symbols or self.errors or self.urls or self.versions)


@dataclass(frozen=True)
class PromptBrief:
    """Structured brief produced from a user prompt without changing intent."""

    original_prompt: str
    intent: str
    secondary_intents: list[str]
    goal: str
    context_found: list[str]
    constraints: list[str]
    done_when: str
    slots: ExtractedSlots
    ambiguity_score: float
    open_questions: list[str]
    is_clear_and_specific: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_prompt": self.original_prompt,
            "intent": self.intent,
            "secondary_intents": self.secondary_intents,
            "goal": self.goal,
            "context_found": self.context_found,
            "constraints": self.constraints,
            "done_when": self.done_when,
            "slots": self.slots.to_dict(),
            "ambiguity_score": self.ambiguity_score,
            "open_questions": self.open_questions,
            "is_clear_and_specific": self.is_clear_and_specific,
        }


def detect_intent(prompt: str) -> tuple[str, list[str]]:
    """Classify primary and secondary intents from the prompt."""
    words = re.findall(r"[a-zA-Z0-9_+-]+", prompt.lower())
    if not words:
        return "explain", []

    scores: dict[str, float] = {k: 0.0 for k in INTENT_KEYWORDS}
    for idx, w in enumerate(words):
        pos_weight = 1.5 if idx < 5 else 1.0
        for intent, kw_tuple in INTENT_KEYWORDS.items():
            if w in kw_tuple:
                scores[intent] += pos_weight

    ranked = sorted(
        ((intent, sc) for intent, sc in scores.items() if sc > 0),
        key=lambda x: (-x[1], x[0]),
    )
    if not ranked:
        return "add", []

    primary = ranked[0][0]
    secondaries = [intent for intent, sc in ranked[1:3] if sc >= 1.0]
    return primary, secondaries


def extract_slots(prompt: str) -> ExtractedSlots:
    """Extract files, symbols, errors, URLs, and versions from prompt text."""
    urls = sorted(set(_URL_RE.findall(prompt)))
    prompt_no_urls = _URL_RE.sub(" ", prompt)

    files = sorted(set(m.group(0) for m in _FILE_RE.finditer(prompt_no_urls)))
    file_set_lower = {f.lower() for f in files}

    errors: list[str] = []
    for m in _ERROR_RE.finditer(prompt_no_urls):
        val = next((g for g in m.groups() if g), "")
        if val and val not in errors:
            errors.append(val.strip())

    versions = sorted(set(m.group(0).strip() for m in _VERSION_RE.finditer(prompt_no_urls)))

    symbols: list[str] = []
    common_non_symbols = {"e.g", "i.e", "etc", "vs", "fig", "step_0", "user_request"}
    for m in _SYMBOL_RE.finditer(prompt_no_urls):
        cand = next((g for g in m.groups() if g), "").strip("`")
        if not cand or len(cand) < 3:
            continue
        if cand.lower() in file_set_lower or cand.lower() in common_non_symbols:
            continue
        if any(cand in f for f in files):
            continue
        if re.match(r"^v?\d+\.\d+", cand):
            continue
        if cand not in symbols:
            symbols.append(cand)

    return ExtractedSlots(
        files=files[:6],
        symbols=symbols[:6],
        errors=errors[:4],
        urls=urls[:4],
        versions=versions[:4],
    )


def _extract_constraints(prompt: str) -> list[str]:
    found: list[str] = []
    for pat in _CONSTRAINT_PATTERNS:
        for m in pat.finditer(prompt):
            snippet = re.sub(r"\s+", " ", m.group(0)).strip(" ,;.")
            if snippet and snippet not in found:
                found.append(snippet[:110])
    return found[:3]


def _detect_ambiguity(
    prompt: str,
    intent: str,
    slots: ExtractedSlots,
    constraints: list[str],
) -> tuple[float, list[str]]:
    """Calculate ambiguity score [0.0, 1.0] and produce at most 2 blocking questions."""
    words = prompt.strip().split()
    word_count = len(words)
    score = 0.0
    questions: list[str] = []

    for pat_a, pat_b, conflict_q in _CONFLICT_PAIRS:
        if pat_a.search(prompt) and pat_b.search(prompt):
            score += 0.65
            questions.append(conflict_q)
            break

    has_target = bool(slots.files or slots.symbols or slots.errors or slots.urls)
    domain_nouns = re.findall(
        r"\b(auth|login|database|db|migration|postgres|sqlite|redis|docker|k8s|kubernetes|helm|pdf|xlsx|csv|docx|pptx|react|button|modal|table|api|endpoint|webhook|sentry|linear|github|workflow|ci|test|pytest|playwright|ruff|cache|router|scanner|installer)\b",
        prompt.lower(),
    )

    if not has_target and not domain_nouns:
        score += 0.55
        if intent == "fix":
            questions.append("Which file, component, or error message is failing, and how can it be reproduced?")
        elif intent in ("refactor", "review", "test"):
            questions.append(f"Which module or file path should this {intent} focus on?")
        else:
            questions.append("Which component or file path in the workspace should be updated, and what is the expected behavior?")
    elif not has_target and word_count < 6:
        score += 0.45
        if intent == "fix":
            questions.append(f"What specific failure or error are you seeing in `{domain_nouns[0]}`?")
        else:
            questions.append(f"What concrete behavior or acceptance criteria should the `{domain_nouns[0]}` change satisfy?")

    if word_count <= 4 and not slots.files:
        score += 0.35

    vague_pronoun_re = re.compile(r"(?i)^(fix|update|change|refactor|check|test|improve|clean\s+up)\s+(it|this|that|everything|the\s+code|the\s+bug|the\s+issue|things)\b")
    if vague_pronoun_re.search(prompt.strip()):
        score += 0.5
        if not questions:
            questions.append("Which specific file, function, or failing behavior should be targeted?")

    if score >= 0.65 and len(questions) < 2 and not constraints and word_count < 9:
        if intent in ("add", "refactor", "data", "deploy"):
            questions.append("Are there any compatibility, schema, or performance constraints we must preserve?")

    clamped = min(1.0, round(score, 2))
    final_questions = questions[:2] if clamped >= 0.6 else []
    return clamped, final_questions


def restructure_prompt(
    prompt: str,
    signals: ProjectSignals | None = None,
) -> PromptBrief:
    """Turn a user prompt into a structured PromptBrief deterministically."""
    clean_prompt = prompt.strip()
    intent, secondary = detect_intent(clean_prompt)
    slots = extract_slots(clean_prompt)
    constraints = _extract_constraints(clean_prompt)

    first_sentence = re.split(r"(?<=[.!?])\s+|\n+", clean_prompt, maxsplit=1)[0].strip()
    if len(first_sentence) > 160:
        first_sentence = first_sentence[:157].rstrip() + "..."
    goal = f"[{intent.upper()}] {first_sentence}"

    context_items: list[str] = []
    if slots.files:
        context_items.append(f"files={', '.join(slots.files[:4])}")
    if slots.symbols:
        context_items.append(f"symbols={', '.join(slots.symbols[:4])}")
    if slots.errors:
        context_items.append(f"errors={', '.join(slots.errors[:2])}")
    if slots.versions:
        context_items.append(f"versions={', '.join(slots.versions[:2])}")
    if signals:
        sig_parts: list[str] = []
        if signals.languages:
            sig_parts.append("/".join(signals.languages[:3]))
        if signals.frameworks:
            sig_parts.append("/".join(signals.frameworks[:3]))
        if signals.git_host:
            sig_parts.append(signals.git_host)
        if sig_parts:
            context_items.append(f"workspace={' + '.join(sig_parts)}")

    if not constraints:
        constraints = ["Preserve existing behavior outside the requested scope; follow workspace rules."]

    done_when = DEFAULT_DONE_WHEN.get(intent, DEFAULT_DONE_WHEN["add"])
    ambiguity_score, open_questions = _detect_ambiguity(clean_prompt, intent, slots, constraints)

    word_count = len(clean_prompt.split())
    has_explicit_target = bool(slots.files or slots.symbols)
    is_clear_and_specific = (
        ambiguity_score < 0.25
        and has_explicit_target
        and 6 <= word_count <= 45
        and not secondary
    )

    return PromptBrief(
        original_prompt=prompt,
        intent=intent,
        secondary_intents=secondary,
        goal=goal,
        context_found=context_items,
        constraints=constraints,
        done_when=done_when,
        slots=slots,
        ambiguity_score=ambiguity_score,
        open_questions=open_questions,
        is_clear_and_specific=is_clear_and_specific,
    )
