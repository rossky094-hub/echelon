"""
V13: c_mechanism_novelty — LLM-based mechanism novelty scorer.

Scores 0-3 based on whether a paper introduces a genuinely new physical
mechanism, material, architecture, or algorithmic paradigm.

Cost estimate: ~$0.0001/paper via pplx (max_tokens=200)
100 gold seeds = ~$0.01 — acceptable for production.

Score mapping (0-3 → 0-1):
  0 → 0.00  (no new mechanism)
  1 → 0.33  (mentioned but not original)
  2 → 0.67  (new but incremental)
  3 → 1.00  (fully novel mechanism)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

MECHANISM_NOVELTY_PROMPT = """\
Read ONLY this title and abstract:
Title: {title}
Abstract: {abstract}

Score 0-3:
0 = No new mechanism/material/architecture mentioned
1 = Mentions novel element but does not provide original design
2 = Provides new mechanism description, but incrementally related to known work
3 = Fully new mechanism (material/structure/principle) never seen in this field

Output JSON only (no markdown, no explanation outside JSON):
{{"score": <int 0-3>, "reasoning": "<one sentence>"}}"""


def _extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """
    Robustly extract JSON from LLM response text.
    Handles markdown code fences and surrounding prose.
    """
    # Try direct parse first
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Try extracting from ```json ... ``` block
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try extracting first {...} block
    brace_match = re.search(r"\{[^{}]+\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def score_mechanism_novelty(
    paper: Dict[str, Any],
    llm_client: Any = None,
    model: str = "llama-3.1-sonar-small-128k-online",
) -> int:
    """
    Score paper mechanism novelty using LLM (0-3 integer scale).

    Args:
        paper:      Dict with "title" and "abstract" keys.
        llm_client: Optional LLM client with .complete(prompt, max_tokens) method.
                    If None, returns 1 (neutral-conservative fallback).
        model:      LLM model name (default: pplx sonar-small for cost efficiency).

    Returns:
        Integer score ∈ {0, 1, 2, 3}.
        0 = no new mechanism
        3 = fully novel mechanism

    Examples:
        >>> paper = {"title": "Attention is All You Need", "abstract": "..."}
        >>> score = score_mechanism_novelty(paper, llm_client=None)
        >>> 0 <= score <= 3
        True
    """
    title = paper.get("title", "")
    abstract = paper.get("abstract", "") or paper.get("abstract_inverted_index", "")

    if not title and not abstract:
        logger.warning("score_mechanism_novelty: empty title and abstract, returning 1")
        return 1

    prompt = MECHANISM_NOVELTY_PROMPT.format(
        title=title[:500],  # truncate for cost efficiency
        abstract=str(abstract)[:1500],
    )

    if llm_client is None:
        # No client provided — return neutral-conservative fallback
        logger.debug("score_mechanism_novelty: no llm_client, returning fallback 1")
        return 1

    try:
        response_text = llm_client.complete(prompt, max_tokens=200, model=model)
        parsed = _extract_json_from_text(response_text)
        if parsed is None:
            logger.warning("score_mechanism_novelty: could not parse JSON, returning 1")
            return 1
        raw_score = int(parsed.get("score", 1))
        score = max(0, min(3, raw_score))
        logger.debug(
            "score_mechanism_novelty: score=%d, reasoning=%s",
            score,
            parsed.get("reasoning", ""),
        )
        return score
    except Exception as exc:  # noqa: BLE001
        logger.error("score_mechanism_novelty: LLM call failed: %s", exc)
        return 1


def mechanism_novelty_to_component(score: int) -> float:
    """
    Convert 0-3 integer score to [0, 1] component value for KeystoneScore.

    Mapping:
        0 → 0.00
        1 → 0.33
        2 → 0.67
        3 → 1.00

    Args:
        score: Integer ∈ {0, 1, 2, 3}

    Returns:
        Float ∈ [0.0, 1.0]

    Examples:
        >>> mechanism_novelty_to_component(0)
        0.0
        >>> round(mechanism_novelty_to_component(2), 4)
        0.6667
        >>> mechanism_novelty_to_component(3)
        1.0
    """
    score = max(0, min(3, int(score)))
    return score / 3.0
