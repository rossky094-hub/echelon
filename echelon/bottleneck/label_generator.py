"""
Cluster Label Generator — AUDIT-017 fix.

V11.1 bug: Labels were generated from paper TITLES, producing achievement-framing
"表扬信" (praise letters) like "High-efficiency metasurface for broadband control".

V11.2 fix:
- Step 1: convergence happens FIRST (converged_bottlenecks must be non-empty)
- Step 2: label is generated FROM the converged_bottleneck_text, not titles
- Format: "[系统X]: [未解卡点Y]" — no praise words allowed
- Forbidden words list enforced by post-validation
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Praise / achievement words — FORBIDDEN in cluster labels  [AUDIT-017]
# ---------------------------------------------------------------------------

PRAISE_WORDS = frozenset([
    # English
    "breakthrough", "revolutionary", "state-of-the-art", "sota",
    "achieved", "demonstrated", "enabled", "overcame", "solved",
    "outperforms", "surpasses", "exceeds", "excellent", "superior",
    "remarkable", "unprecedented", "record", "best-in-class",
    # Chinese (in case LLM outputs Chinese)
    "突破", "革命性", "最先进", "克服", "解决", "实现了", "优于",
    "超越", "超过", "卓越", "卓众", "前所未有", "创纪录",
])

# Limitation/bottleneck words — REQUIRED in cluster labels
BOTTLENECK_INDICATORS = frozenset([
    "limited", "constrained", "barrier", "challenge", "bottleneck",
    "unsolved", "unresolved", "fundamental", "difficulty", "constraint",
    "未解", "限制", "瓶颈", "挑战", "障碍", "约束",
])

# ---------------------------------------------------------------------------
# Prompt template  [AUDIT-017]
# ---------------------------------------------------------------------------

CLUSTER_LABEL_PROMPT_V2 = """\
You are labeling a research cluster by its CORE UNSOLVED BOTTLENECK.

This cluster has {n} papers. Their TOP CONVERGED BOTTLENECK CLAIMS are:

{bottleneck_claims_formatted}

SAMPLE PAPER TITLES (context only — do NOT use titles as the label source):
{titles_sample}

Generate a cluster label that:
1. FOCUSES ON THE UNSOLVED CONSTRAINT, not on what the papers achieved
2. Format: "[Physical system or regime]: [Core unsolved challenge limiting progress]"
3. Length: 8-20 words
4. DO NOT use achievement/positive language: "achieved", "demonstrated", "enabled",
   "breakthrough", "revolutionary", "state-of-the-art", "solved", "overcame"
5. USE limitation language: "limited by", "constrained by", "challenge of",
   "barrier to", "unsolved", "fundamental limit"

BAD EXAMPLE (achievement framing — WRONG):
  "High-efficiency metasurface design for broadband polarization control"

GOOD EXAMPLE (bottleneck framing — CORRECT):
  "Metasurface design: bandwidth fundamentally constrained by resonance Q-factor vs efficiency tradeoff"

ANOTHER GOOD EXAMPLE:
  "On-chip photonic integration: crosstalk barrier limiting scalability beyond 100 channels"

Reply JSON only (no markdown):
{{"label": "...", "core_bottleneck_phrase": "...(≤80 chars)", "key_concepts": ["...", "..."]}}
"""


# ---------------------------------------------------------------------------
# Response schema  [AUDIT-017]
# ---------------------------------------------------------------------------

class ClusterLabel(BaseModel):
    """
    Cluster label output.

    [AUDIT-017] label must describe the UNSOLVED BOTTLENECK, not the achievements.
    Validated by check_no_praise_words().
    """

    label: str = Field(..., min_length=15, max_length=150)
    core_bottleneck_phrase: str = Field(..., max_length=80)
    key_concepts: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def validate_label_tone(self) -> "ClusterLabel":
        """
        [AUDIT-017] Reject labels containing praise/achievement words.
        """
        issues = check_no_praise_words(self.label)
        if issues:
            raise ValueError(
                f"Cluster label contains forbidden achievement words {issues}. "
                "Label must describe the UNSOLVED BOTTLENECK, not achievements."
            )
        return self


def check_no_praise_words(label: str) -> list[str]:
    """
    Return list of praise words found in the label.

    An empty list means the label is acceptable (no praise words).
    """
    label_lower = label.lower()
    found = []
    for word in PRAISE_WORDS:
        # Use word boundary check for multi-word phrases
        pattern = re.escape(word.lower())
        if re.search(pattern, label_lower):
            found.append(word)
    return found


def has_bottleneck_language(label: str) -> bool:
    """Check that the label contains at least one bottleneck indicator word."""
    label_lower = label.lower()
    for word in BOTTLENECK_INDICATORS:
        if word.lower() in label_lower:
            return True
    return False


# ---------------------------------------------------------------------------
# Step 1: convergence text formatting
# ---------------------------------------------------------------------------

def format_bottleneck_claims(converged_bottlenecks: list[dict]) -> str:
    """
    Format converged bottleneck claims for injection into the label prompt.

    [AUDIT-017] This is the DRIVER of the label — not the paper titles.
    """
    lines = []
    for i, cb in enumerate(converged_bottlenecks[:3]):
        claim_text = cb.get("claim_text", "")
        conv_score = cb.get("convergence_score", 0.0)
        sup_count = cb.get("supporting_count", 0)
        severity = cb.get("severity_lexical", "unknown")
        consistency = cb.get("cross_paper_consistency", 0.0)
        lines.append(
            f"  [{i+1}] (convergence={conv_score:.2f}, "
            f"supported_by={sup_count}_papers)\n"
            f"       \"{claim_text}\"\n"
            f"       severity={severity}, consistency={consistency:.2f}"
        )
    return "\n".join(lines) if lines else "  (no converged bottlenecks)"


# ---------------------------------------------------------------------------
# Step 2: label generation
# ---------------------------------------------------------------------------

def build_label_prompt(
    cluster: dict,
    converged_bottlenecks: list[dict],
) -> str:
    """
    Build the cluster label prompt.

    [AUDIT-017] REQUIRES converged_bottlenecks to be non-empty.
    The label is driven by the convergent_bottleneck_text, not paper titles.
    """
    if not converged_bottlenecks:
        raise ValueError(
            f"Cluster {cluster.get('cluster_id', '?')} has no converged bottlenecks. "
            "Label generation MUST occur AFTER Step 4 bottleneck convergence. "
            "[AUDIT-017]"
        )

    n = len(cluster.get("members", []))
    bottleneck_claims_formatted = format_bottleneck_claims(converged_bottlenecks)
    titles_sample = "\n".join(
        f"  - {p.get('title', 'untitled')}"
        for p in cluster.get("members", [])[:5]
    )

    return CLUSTER_LABEL_PROMPT_V2.format(
        n=n,
        bottleneck_claims_formatted=bottleneck_claims_formatted,
        titles_sample=titles_sample,
    )


def parse_label_response(llm_response: str) -> Optional[ClusterLabel]:
    """Parse and validate LLM label response."""
    try:
        cleaned = re.sub(r"```(?:json)?|```", "", llm_response).strip()
        data = json.loads(cleaned)
        return ClusterLabel(**data)
    except Exception as exc:
        logger.error(f"Failed to parse label response: {exc}\n{llm_response[:200]!r}")
        return None


def generate_cluster_label(
    cluster: dict,
    converged_bottlenecks: list[dict],
    llm_callable: Any,  # callable(prompt: str) -> str
    max_retries: int = 2,
) -> Optional[ClusterLabel]:
    """
    Two-step cluster label generation: convergence first, then label.

    [AUDIT-017]
    Step 1: converged_bottlenecks must already be computed (passed in)
    Step 2: label is generated FROM the converged bottleneck text

    The label format is "[系统X]: [未解卡点Y]" — must not contain praise words.

    Args:
        cluster:               Cluster dict with "members" list.
        converged_bottlenecks: List of converged bottleneck dicts (from Step 4).
        llm_callable:          Callable(prompt: str) -> str.
        max_retries:           How many times to retry if label contains praise words.

    Returns:
        ClusterLabel or None on failure.
    """
    # [AUDIT-017] Enforce: convergence must precede label generation
    if not converged_bottlenecks:
        logger.error(
            "[AUDIT-017] Cannot generate cluster label: no converged bottlenecks. "
            "Run Step 4 bottleneck convergence first."
        )
        return None

    prompt = build_label_prompt(cluster, converged_bottlenecks)

    for attempt in range(max_retries + 1):
        try:
            raw_response = llm_callable(prompt)
        except Exception as exc:
            logger.error(f"LLM call failed (attempt {attempt}): {exc}")
            continue

        label = parse_label_response(raw_response)
        if label is None:
            continue

        # Validation is built into ClusterLabel model_validator
        # If it passed, the label is praise-free
        praise_found = check_no_praise_words(label.label)
        if praise_found:
            # Should not happen since model_validator already checked,
            # but guard here for safety
            logger.warning(
                f"[AUDIT-017] Label attempt {attempt} still has praise words "
                f"{praise_found}: {label.label!r}"
            )
            continue

        return label

    logger.error(
        f"[AUDIT-017] Failed to generate a praise-free label after {max_retries+1} attempts."
    )
    return None


# ---------------------------------------------------------------------------
# V11.3-R3: Cross-topic detection and label prefix generation
# ---------------------------------------------------------------------------

def compute_top_topic_ratio(
    members: list,
    topic_id_field: str = "primary_topic_id",
) -> tuple:
    """
    [V11.3-R3] Compute top_topic_ratio and sorted topic names for a cluster.

    top_topic_ratio = max(topic_count) / cluster_size

    Args:
        members:        List of paper dicts in the cluster.
        topic_id_field: Field name for the paper's topic identifier.

    Returns:
        (top_topic_ratio, sorted_topic_names)
        where sorted_topic_names is ordered by frequency descending.
    """
    from collections import Counter
    if not members:
        return 1.0, []

    topic_counts: Counter = Counter()
    for m in members:
        tid = m.get(topic_id_field) or m.get("topic_id") or "unknown"
        # Also try display_name / topic_name as label
        topic_label = (
            m.get("primary_topic_display_name")
            or m.get("topic_name")
            or str(tid)
        )
        topic_counts[topic_label] += 1

    cluster_size = len(members)
    top_count = topic_counts.most_common(1)[0][1]
    top_topic_ratio = top_count / cluster_size
    sorted_topics = [t for t, _ in topic_counts.most_common()]

    return top_topic_ratio, sorted_topics


def build_topic_prefix(
    members: list,
    topic_id_field: str = "primary_topic_id",
    cross_topic_threshold: float = 0.6,
) -> str:
    """
    [V11.3-R3] Build the topic prefix for a cluster label.

    - top_topic_ratio >= cross_topic_threshold: "在 topic1 中"
    - top_topic_ratio < cross_topic_threshold:  "在 topic1 / topic2 跨界中"

    Args:
        members:                List of paper dicts.
        topic_id_field:         Field name for topic identifier.
        cross_topic_threshold:  Ratio threshold below which cluster is cross-topic.

    Returns:
        Topic prefix string, e.g. "在 metasurface design / multimodal ML 跨界中"
    """
    ratio, sorted_topics = compute_top_topic_ratio(members, topic_id_field)

    if not sorted_topics:
        return ""

    if ratio >= cross_topic_threshold:
        # Single dominant topic
        return f"在 {sorted_topics[0]} 中"
    else:
        # Cross-topic cluster: use top-2 topics with "/"
        top2 = sorted_topics[:2]
        joined = " / ".join(top2)
        return f"在 {joined} 跨界中"


def is_cross_topic_cluster(
    members: list,
    topic_id_field: str = "primary_topic_id",
    cross_topic_threshold: float = 0.6,
) -> bool:
    """
    [V11.3-R3] Return True if cluster's top_topic_ratio < cross_topic_threshold.

    Args:
        members:               List of paper dicts.
        topic_id_field:        Field name for topic identifier.
        cross_topic_threshold: Ratio threshold (default 0.6).

    Returns:
        True if cluster spans multiple topics (no single dominant topic >= 60%).
    """
    ratio, _ = compute_top_topic_ratio(members, topic_id_field)
    return ratio < cross_topic_threshold
