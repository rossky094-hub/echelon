"""
Debate Critic — AUDIT-016 fix.

V11.1 bug: The Debate Critic prompt lacked a prior_art_pool, causing the LLM to
invent UUIDs for papers that don't exist.

V11.2 fix:
- prior_art_pool is ALWAYS injected into the prompt
- LLM is explicitly forbidden from inventing UUIDs
- validate_critic_result() checks that every returned UUID is in the pool
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt template  [AUDIT-016]
# ---------------------------------------------------------------------------

DEBATE_CRITIC_PROMPT = """\
You are a debate critic evaluating a bottleneck claim from a research cluster.

PRIOR ART POOL — the ONLY papers you may reference:
{prior_art_pool_formatted}

BOTTLENECK CLAIM:
  Text: "{claim_text}"
  Severity: {severity}
  Physical depth: {physical_depth_score:.2f}
  Supporting papers: {supporting_count}

Your task: identify which prior arts MOST DIRECTLY refute or contradict this claim.

CRITICAL RULES:
1. You MUST select pool_ids ONLY from the PRIOR ART POOL listed above.
2. DO NOT invent pool_ids. DO NOT fabricate UUIDs or paper IDs.
3. If no prior art in the pool refutes this claim, return an empty list.
4. Do NOT reference papers not in the pool above.

Reply JSON only:
{{
  "critique_targets": ["<pool_id from pool>", ...],
  "critique_reasoning": "<≤200 chars explaining the contradiction>",
  "verdict": "refuted|partially_refuted|confirmed|uncertain"
}}
"""


def format_prior_art_pool(pool: list[dict]) -> str:
    """Format prior_art_pool for injection into the critic prompt."""
    lines = []
    for entry in pool:
        pool_id = entry.get("pool_id", "unknown")
        title = entry.get("title", "untitled")[:120]
        year = entry.get("publication_year") or "?"
        snippet = entry.get("abstract_snippet", "")[:200]
        lines.append(
            f"  [pool_id: {pool_id}] \"{title}\" (year: {year})\n"
            f"    {snippet}"
        )
    return "\n\n".join(lines) if lines else "  (empty pool)"


# ---------------------------------------------------------------------------
# Response schema  [AUDIT-016]
# ---------------------------------------------------------------------------

class CriticResult(BaseModel):
    """
    Structured output from the Debate Critic.

    [AUDIT-016] critique_targets must be a SUBSET of prior_art_pool UUIDs/IDs.
    Validated by validate_critic_result().
    """

    critique_targets: list[str] = Field(
        default_factory=list,
        description="[AUDIT-016] Pool IDs from prior_art_pool ONLY",
    )
    critique_reasoning: str = Field(default="", max_length=500)
    verdict: str = Field(
        default="uncertain",
        description="refuted|partially_refuted|confirmed|uncertain",
    )


def validate_critic_result(
    result: CriticResult,
    prior_art_pool: list[dict],
) -> tuple[CriticResult, list[str]]:
    """
    [AUDIT-016] Validate that critique_targets are a subset of the pool.

    Any IDs not found in the pool are hallucinated UUIDs — they are stripped.

    Args:
        result:         CriticResult from LLM output.
        prior_art_pool: List of pool entries with "pool_id" keys.

    Returns:
        (sanitized_result, hallucinated_ids)
        hallucinated_ids: IDs that were stripped because they weren't in pool.
    """
    valid_pool_ids = {str(entry.get("pool_id", "")) for entry in prior_art_pool}

    hallucinated: list[str] = []
    valid_targets: list[str] = []

    for target_id in result.critique_targets:
        if str(target_id) in valid_pool_ids:
            valid_targets.append(target_id)
        else:
            hallucinated.append(target_id)
            logger.warning(
                f"[AUDIT-016] Critic hallucinated pool_id {target_id!r} — "
                f"not in prior_art_pool. Stripped."
            )

    # Return sanitized result
    sanitized = CriticResult(
        critique_targets=valid_targets,
        critique_reasoning=result.critique_reasoning,
        verdict=result.verdict,
    )
    return sanitized, hallucinated


def build_critic_prompt(
    claim_text: str,
    severity: str,
    physical_depth_score: float,
    supporting_count: int,
    prior_art_pool: list[dict],
) -> str:
    """
    Build the Debate Critic prompt with the mandatory prior_art_pool.

    [AUDIT-016] The pool is ALWAYS injected — never empty.
    """
    if not prior_art_pool:
        logger.warning(
            "[AUDIT-016] prior_art_pool is empty — Critic will have no reference papers. "
            "This increases hallucination risk."
        )

    pool_text = format_prior_art_pool(prior_art_pool)

    return DEBATE_CRITIC_PROMPT.format(
        prior_art_pool_formatted=pool_text,
        claim_text=claim_text[:300],
        severity=severity,
        physical_depth_score=physical_depth_score,
        supporting_count=supporting_count,
    )


def parse_critic_response(llm_response: str) -> Optional[CriticResult]:
    """Parse LLM JSON response into CriticResult."""
    try:
        # Strip markdown fences if present
        cleaned = re.sub(r"```(?:json)?|```", "", llm_response).strip()
        data = json.loads(cleaned)
        return CriticResult(**data)
    except Exception as exc:
        logger.error(f"Failed to parse critic response: {exc}\nResponse: {llm_response[:200]!r}")
        return None


def run_debate_critic(
    claim_text: str,
    severity: str,
    physical_depth_score: float,
    supporting_count: int,
    prior_art_pool: list[dict],
    llm_callable: Any,  # callable(prompt: str) -> str
) -> tuple[Optional[CriticResult], list[str]]:
    """
    Run a single Debate Critic pass with pool injection and UUID validation.

    [AUDIT-016] Complete workflow:
    1. Build prompt with prior_art_pool
    2. Call LLM
    3. Parse response
    4. Validate critique_targets ⊆ pool IDs
    5. Return (sanitized_result, hallucinated_ids)

    Args:
        llm_callable: Any callable that takes a prompt string and returns
                      a response string. Can be a mock in tests.

    Returns:
        (CriticResult | None, hallucinated_ids)
    """
    prompt = build_critic_prompt(
        claim_text=claim_text,
        severity=severity,
        physical_depth_score=physical_depth_score,
        supporting_count=supporting_count,
        prior_art_pool=prior_art_pool,
    )

    try:
        raw_response = llm_callable(prompt)
    except Exception as exc:
        logger.error(f"LLM call failed in debate_critic: {exc}")
        return None, []

    result = parse_critic_response(raw_response)
    if result is None:
        return None, []

    sanitized, hallucinated = validate_critic_result(result, prior_art_pool)
    return sanitized, hallucinated
