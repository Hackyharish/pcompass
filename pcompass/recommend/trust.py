"""Publisher and repository trust scoring (0-100) for Prompt Compass candidates."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

OSI_LICENSES: frozenset[str] = frozenset({
    "mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "isc",
    "mpl-2.0", "lgpl-3.0", "gpl-3.0", "0bsd", "unlicense",
})

VERIFIED_PUBLISHERS: frozenset[str] = frozenset({
    "modelcontextprotocol", "anthropics", "openai", "google", "google-gemini",
    "microsoft", "github", "vercel-labs", "stripe", "cloudflare", "sentry",
    "linear", "playwright", "figma", "supabase", "postgres", "redis",
})


@dataclass(frozen=True)
class TrustReport:
    """Detailed breakdown of a candidate's 0-100 trust score."""

    score: int
    level: str  # "high" | "medium" | "low" | "untrusted"
    breakdown: dict[str, int]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_trust_score(metadata: dict[str, Any]) -> TrustReport:
    """Compute a deterministic 0-100 trust score from candidate metadata."""
    breakdown: dict[str, int] = {
        "publisher": 0,
        "license": 0,
        "recency": 0,
        "adoption": 0,
        "pinning": 0,
    }
    reasons: list[str] = []

    publisher = str(metadata.get("publisher") or "").strip().lower()
    verified_flag = bool(metadata.get("verified_publisher"))
    if verified_flag or publisher in VERIFIED_PUBLISHERS:
        breakdown["publisher"] = 30
        reasons.append(f"verified publisher ({publisher or 'official'})")
    elif publisher:
        breakdown["publisher"] = 10
        reasons.append(f"unverified publisher ({publisher})")
    else:
        reasons.append("unknown publisher")

    lic = str(metadata.get("license") or "").strip().lower()
    if lic in OSI_LICENSES:
        breakdown["license"] = 20
        reasons.append(f"OSI license ({lic.upper()})")
    elif lic:
        breakdown["license"] = 5
        reasons.append(f"non-standard license ({lic})")
    else:
        reasons.append("missing license")

    days_since_commit = metadata.get("days_since_last_commit")
    if isinstance(days_since_commit, (int, float)):
        if days_since_commit <= 180:
            breakdown["recency"] = 15
            reasons.append("updated <6 months ago")
        elif days_since_commit <= 365:
            breakdown["recency"] = 10
            reasons.append("updated <12 months ago")
        else:
            reasons.append("stale (>12 months since commit)")
    elif metadata.get("last_commit_iso"):
        try:
            dt = datetime.fromisoformat(str(metadata["last_commit_iso"]).replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - dt).days
            if age_days <= 365:
                breakdown["recency"] = 15
                reasons.append("updated <12 months ago")
        except Exception:
            pass

    stars = int(metadata.get("stars") or 0)
    installs = int(metadata.get("installs") or 0)
    if stars >= 500 or installs >= 5000:
        breakdown["adoption"] = 15
        reasons.append(f"strong adoption ({stars} stars)")
    elif stars >= 50 or installs >= 500:
        breakdown["adoption"] = 10
        reasons.append(f"moderate adoption ({stars} stars)")
    elif stars >= 10 or installs >= 100:
        breakdown["adoption"] = 5

    pinned_ref = str(metadata.get("pinned_ref") or "").strip()
    if len(pinned_ref) >= 7 and all(c in "0123456789abcdefABCDEF" for c in pinned_ref):
        breakdown["pinning"] = 20
        reasons.append(f"pinned commit SHA ({pinned_ref[:8]})")
    elif pinned_ref.startswith("v") or (pinned_ref and pinned_ref[0].isdigit()):
        breakdown["pinning"] = 15
        reasons.append(f"pinned version ({pinned_ref})")
    else:
        reasons.append("unpinned mutable ref")

    total = sum(breakdown.values())
    if total >= 80:
        level = "high"
    elif total >= 55:
        level = "medium"
    elif total >= 35:
        level = "low"
    else:
        level = "untrusted"

    return TrustReport(score=total, level=level, breakdown=breakdown, reasons=reasons)
