"""Deterministic BM25 + project-signal capability router for Prompt Compass."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import math
import re
from typing import Any

from pcompass.core.index import CapabilityIndex, ProjectSignals
from pcompass.core.inventory import CapabilityRecord
from pcompass.core.sanitize import sanitize_text

_WORD_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_+-]*")

STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "could",
    "do", "does", "for", "from", "get", "had", "has", "have", "help", "how",
    "i", "if", "in", "into", "is", "it", "its", "just", "let", "like", "make",
    "me", "my", "need", "no", "not", "of", "on", "or", "our", "out", "please",
    "should", "so", "some", "that", "the", "their", "them", "then", "there",
    "these", "they", "this", "to", "up", "us", "use", "using", "want", "was",
    "we", "what", "when", "where", "which", "who", "why", "will", "with",
    "would", "you", "your",
})

SYNONYM_MAP: dict[str, tuple[str, ...]] = {
    "k8s": ("kubernetes", "kubectl", "helm", "manifest"),
    "kubernetes": ("k8s", "kubectl", "helm"),
    "db": ("database", "sql", "postgres", "postgresql", "sqlite", "query", "migration"),
    "database": ("db", "sql", "postgres", "sqlite", "migration"),
    "postgres": ("postgresql", "database", "sql", "psql"),
    "postgresql": ("postgres", "database", "sql", "psql"),
    "sql": ("database", "postgres", "sqlite", "query"),
    "pr": ("pull", "request", "github", "gh", "review"),
    "github": ("gh", "pull", "request", "issue", "actions", "workflow"),
    "ci": ("workflow", "actions", "github", "pipeline", "build", "test"),
    "test": ("testing", "pytest", "unittest", "playwright", "spec", "coverage"),
    "tests": ("test", "testing", "pytest", "playwright"),
    "testing": ("test", "pytest", "playwright"),
    "e2e": ("playwright", "browser", "test", "webapp"),
    "browser": ("playwright", "webapp", "e2e", "frontend"),
    "ui": ("frontend", "react", "component", "css", "tailwind", "design"),
    "frontend": ("ui", "react", "component", "typescript", "css"),
    "lint": ("linter", "ruff", "format", "formatter", "style", "prettier"),
    "format": ("formatter", "lint", "ruff", "prettier", "style"),
    "container": ("docker", "dockerfile", "compose", "image"),
    "docker": ("container", "dockerfile", "compose"),
    "infra": ("terraform", "kubernetes", "cloud", "deploy"),
    "deploy": ("deployment", "release", "staging", "production", "ci"),
    "deployment": ("deploy", "release", "staging", "production"),
    "doc": ("docs", "documentation", "markdown", "readme", "pdf", "docx"),
    "docs": ("doc", "documentation", "markdown", "readme"),
    "pdf": ("document", "report", "extract", "form", "page"),
    "excel": ("xlsx", "spreadsheet", "workbook", "csv", "table"),
    "spreadsheet": ("excel", "xlsx", "csv", "workbook"),
    "slide": ("slides", "pptx", "powerpoint", "presentation", "deck"),
    "slides": ("slide", "pptx", "powerpoint", "presentation", "deck"),
    "deck": ("slides", "pptx", "powerpoint", "presentation"),
    "security": ("audit", "vulnerability", "scan", "secret", "auth", "owasp"),
    "auth": ("authentication", "oauth", "login", "jwt", "token", "session"),
    "search": ("grep", "ripgrep", "rg", "find", "fd"),
}


def _stem_token(tok: str) -> str:
    w = tok.lower().strip("_-+")
    if len(w) <= 3:
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("ing") and len(w) > 5:
        base = w[:-3]
        if len(base) >= 3 and base[-1] == base[-2]:
            base = base[:-1]
        return base
    if w.endswith("ed") and len(w) > 4:
        return w[:-2]
    if w.endswith("es") and len(w) > 4 and not w.endswith(("ses", "xes", "zes")):
        return w[:-1]
    if w.endswith("s") and not w.endswith(("ss", "us", "is", "k8s")):
        return w[:-1]
    return w


def tokenize(text: str, expand_synonyms: bool = False) -> list[str]:
    if not text:
        return []
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    raw_words = _WORD_RE.findall(spaced.lower())

    tokens: list[str] = []
    for raw in raw_words:
        parts = [p for p in re.split(r"[_+-]+", raw) if p]
        for p in parts:
            if p in STOPWORDS or len(p) < 2:
                continue
            stemmed = _stem_token(p)
            tokens.append(p)
            if stemmed != p and len(stemmed) >= 2:
                tokens.append(stemmed)
            if expand_synonyms and p in SYNONYM_MAP:
                for syn in SYNONYM_MAP[p]:
                    tokens.append(syn)
                    s_syn = _stem_token(syn)
                    if s_syn != syn:
                        tokens.append(s_syn)
    return tokens


@dataclass(frozen=True)
class RoutedCapability:
    """A capability selected by the router with its score and safe generated reason."""

    id: str
    kind: str
    name: str
    agent: str
    scope: str
    score: float
    reason: str
    matched_terms: list[str]
    source_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _build_safe_reason(
    cap: CapabilityRecord,
    matched_terms: list[str],
    boost_reasons: list[str],
) -> str:
    clean_name = sanitize_text(cap.name, max_len=40)
    unique_terms = sorted(set(matched_terms))[:4]
    parts: list[str] = []

    if unique_terms:
        parts.append(f"matches task terms [{', '.join(unique_terms)}]")
    if cap.tools:
        matched_tools = [t for t in cap.tools if any(mt in t.lower() for mt in unique_terms)]
        if matched_tools:
            parts.append(f"exposes tools [{', '.join(matched_tools[:2])}]")
    if boost_reasons:
        parts.append(f"boosted by {', '.join(boost_reasons[:2])}")

    if not parts:
        parts.append(f"relevant {cap.kind} capability for {clean_name}")

    return f"{cap.kind} `{clean_name}` ({cap.scope}): " + "; ".join(parts)


def _compute_project_signal_boost(
    cap: CapabilityRecord,
    cap_tokens: set[str],
    signals: ProjectSignals,
) -> tuple[float, list[str]]:
    boost = 0.0
    reasons: list[str] = []

    for lang in signals.languages:
        if lang in cap_tokens or (lang == "python" and {"py", "pytest", "ruff", "mypy", "uv"} & cap_tokens):
            boost += 0.45
            reasons.append(f"project language [{lang}]")
            break
        if lang in ("javascript", "typescript") and {"ts", "js", "react", "npm", "pnpm", "bun", "playwright"} & cap_tokens:
            boost += 0.45
            reasons.append(f"project language [{lang}]")
            break
        if lang == "rust" and {"rust", "cargo"} & cap_tokens:
            boost += 0.45
            reasons.append("project language [rust]")
            break
        if lang == "go" and "go" in cap_tokens:
            boost += 0.45
            reasons.append("project language [go]")
            break

    for fw in signals.frameworks:
        if fw in cap_tokens:
            boost += 0.55
            reasons.append(f"workspace signal [{fw}]")
            break

    if signals.git_host == "github" and ({"github", "gh", "pr", "actions"} & cap_tokens):
        boost += 0.4
        reasons.append("git remote [github.com]")
    elif signals.git_host == "gitlab" and "gitlab" in cap_tokens:
        boost += 0.4
        reasons.append("git remote [gitlab.com]")

    if signals.has_docker and ({"docker", "container", "compose"} & cap_tokens):
        boost += 0.35
        reasons.append("workspace [Dockerfile]")
    if signals.has_k8s and ({"kubernetes", "k8s", "kubectl", "helm"} & cap_tokens):
        boost += 0.35
        reasons.append("workspace [k8s]")

    return boost, reasons


def route_prompt(
    prompt: str,
    index: CapabilityIndex,
    agent: str | None = None,
    top_k: int = 5,
    min_score: float = 1.2,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[RoutedCapability]:
    """Rank installed capabilities against prompt using BM25 + project signal boosts."""
    max_results = min(max(1, top_k), 5)
    candidates = index.filter_by_agent(agent)
    if not candidates or not prompt or not prompt.strip():
        return []

    query_raw_tokens = tokenize(prompt, expand_synonyms=False)
    if not query_raw_tokens:
        return []
    query_expanded_tokens = tokenize(prompt, expand_synonyms=True)
    direct_set = set(query_raw_tokens)
    query_weights: dict[str, float] = {}
    for qt in query_expanded_tokens:
        query_weights[qt] = 1.0 if qt in direct_set else max(query_weights.get(qt, 0.0), 0.55)

    doc_token_lists: list[list[str]] = []
    doc_raw_token_sets: list[set[str]] = []
    df: dict[str, int] = {}

    for cap in candidates:
        name_tokens = tokenize(cap.name, expand_synonyms=False)
        tool_tokens = tokenize(" ".join(cap.tools), expand_synonyms=False)
        desc_tokens = tokenize(cap.description, expand_synonyms=False)
        weighted_doc = (name_tokens * 3) + (tool_tokens * 2) + desc_tokens
        doc_token_lists.append(weighted_doc)
        unique_doc_tokens = set(weighted_doc)
        doc_raw_token_sets.append(unique_doc_tokens)
        for tok in unique_doc_tokens:
            df[tok] = df.get(tok, 0) + 1

    num_docs = len(candidates)
    avgdl = sum(len(d) for d in doc_token_lists) / max(1, num_docs)

    scored: list[RoutedCapability] = []
    for idx_i, cap in enumerate(candidates):
        doc_tokens = doc_token_lists[idx_i]
        doc_set = doc_raw_token_sets[idx_i]
        if not doc_tokens:
            continue

        tf_map: dict[str, int] = {}
        for tok in doc_tokens:
            tf_map[tok] = tf_map.get(tok, 0) + 1

        dl = len(doc_tokens)
        bm25_score = 0.0
        matched_terms: list[str] = []

        for q_tok, q_weight in query_weights.items():
            tf = tf_map.get(q_tok, 0)
            if tf <= 0:
                continue
            doc_freq = df.get(q_tok, 0)
            idf = math.log(1.0 + (num_docs - doc_freq + 0.5) / (doc_freq + 0.5))
            idf = max(idf, 0.45)
            denom = tf + k1 * (1.0 - b + b * (dl / max(1.0, avgdl)))
            term_score = idf * ((tf * (k1 + 1.0)) / denom) * q_weight
            bm25_score += term_score
            matched_terms.append(q_tok)

        if not matched_terms:
            continue

        prompt_lower = prompt.lower()
        cap_name_lower = cap.name.lower()
        if len(cap_name_lower) >= 2 and re.search(r"\b" + re.escape(cap_name_lower) + r"\b", prompt_lower):
            bm25_score += 1.5

        if cap.kind in ("skill", "mcp"):
            bm25_score += 0.25

        proj_boost, boost_reasons = _compute_project_signal_boost(cap, doc_set, index.signals)
        total_score = round(bm25_score + proj_boost, 4)

        if total_score >= min_score:
            reason = _build_safe_reason(cap, matched_terms, boost_reasons)
            scored.append(
                RoutedCapability(
                    id=cap.id,
                    kind=cap.kind,
                    name=cap.name,
                    agent=cap.agent,
                    scope=cap.scope,
                    score=total_score,
                    reason=reason,
                    matched_terms=sorted(set(matched_terms)),
                    source_path=cap.source_path,
                )
            )

    scored.sort(key=lambda r: (-r.score, r.id))
    return scored[:max_results]