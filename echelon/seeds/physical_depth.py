"""
V11.4-N2: Physical depth gate with refined Path 2 (2a/2b/2c/2d) + new Path 4 (theory).

V11.3 background:
  Path 1 (Physical constants): numeric + physical unit count >= 3
  Path 2 (CS quantitative):    SOTA% / dataset name / ablation count >= 3
  Path 3 (Experimental):       comparison keywords + numeric count >= 3

V11.4 changes (N2-A):
  Path 2 is split into 4 sub-paths to reduce false positives / false negatives:
    2a: Performance numbers PAIRED with dataset name in ±50 char window
        (prevents "achieves 87%" without a named benchmark from passing)
    2b: Ablation completeness — ablation appears >= 3 times OR
        "ablation table" / "ablation study" appears
    2c: Complexity proof — Big-O notation, time/space complexity, FLOPS, etc.
    2d: Dataset scale — M/B+ samples/parameters/images/tokens count >= 1

  Path 4 (Theoretical depth): math-proof language keywords >= 2 distinct hits

Pass condition: any single path (1, 2a, 2b, 2c, 2d, 3, 4) meets its threshold.

Backward compatibility:
  check_physical_depth() and has_physical_depth() are preserved (V11.3 API).
  evaluate_physical_depth_v4() is the new V11.4 API.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple


# ---------------------------------------------------------------------------
# Path 1: Physical unit patterns (V11.3 unchanged)
# ---------------------------------------------------------------------------

_NUMERIC_PATTERN = r'[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?'

_PHYSICAL_UNITS = frozenset([
    "nm", "µm", "um", "mm", "cm",
    "db", "dbi",
    "thz", "ghz", "mhz", "khz", "hz",
    "w", "mw", "µw", "uw", "kw",
    "fs", "ps", "ns", "µs", "us",
    "ev", "mev", "kev", "gev",
    "k", "mk",
    "pa", "kpa", "mpa",
    "t", "mt", "µt",
    "cm-1", "cm⁻¹",
    "sr", "rad",
    "db/cm", "db/km",
    "%",
])


# Pre-compile the physical unit pattern (cannot inline join in rf-string on Python 3.12)
_UNITS_ALTERNATION = "|".join(re.escape(u) for u in _PHYSICAL_UNITS)
_PHYS_UNIT_RE = re.compile(
    rf'({_NUMERIC_PATTERN})\s*({_UNITS_ALTERNATION})\b',
    re.IGNORECASE,
)


def _count_physical_unit_mentions(text: str) -> int:
    """Count (numeric_value + physical_unit) pairs in text."""
    text_lower = text.lower()
    return len(_PHYS_UNIT_RE.findall(text_lower))


# ---------------------------------------------------------------------------
# Path 2a: Performance number PAIRED with dataset name (±50 char window)
# ---------------------------------------------------------------------------

# Performance metric patterns (captured group is the full match including value)
_PERF_PATTERN = re.compile(
    r'(\d+(?:\.\d+)?\s*%'
    r'|\d+\.\d+\s*F1'
    r'|\d+\.\d+\s*BLEU'
    r'|\d+\.\d+\s*ROUGE'
    r'|\d+\.\d+\s*AUC'
    r'|\d+\.\d+\s*mAP'
    r'|\d+\.\d+\s*accuracy'
    r'|\d+\.\d+\s*AP\b)',
    re.IGNORECASE,
)

# Extended dataset list for path 2a pairing check
_DATASET_NAMES_2A = [
    "coco", "imagenet", "cifar", "glue", "squad", "mmlu", "humaneval",
    "ms-marco", "wmt", "mnist",
    "vqa", "vqav2", "nocaps", "vizwiz", "okvqa", "textvqa", "gqa",
    "refcoco", "conceptual captions", "laion", "yfcc", "flickr30k",
    "msvd", "msrvtt", "superglue", "mnli", "sst", "cityscapes", "ade20k",
    "pascal voc", "lvis", "kinetics", "hmdb", "ucf101", "something-something",
    "clevr", "scanqa", "sqa", "scienceqa", "winogrande", "hellaswag",
    "arc", "truthfulqa", "gsm8k", "math", "mbpp",
    "mujoco", "atari", "dm control", "dmc", "metaworld", "openai gym",
    "d4rl", "robosuite", "maniskill",
]


def _count_perf_dataset_pairs(text: str) -> int:
    """
    Count performance-metric / dataset co-occurrence pairs within ±50 char window.

    For each performance number match, check if any dataset name appears
    within 50 characters before or after the match start/end.
    """
    text_lower = text.lower()
    count = 0
    for m in _PERF_PATTERN.finditer(text_lower):
        start, end = m.start(), m.end()
        window_start = max(0, start - 50)
        window_end = min(len(text_lower), end + 50)
        window = text_lower[window_start:window_end]
        for ds in _DATASET_NAMES_2A:
            if ds in window:
                count += 1
                break  # count this match once even if multiple datasets nearby
    return count


# ---------------------------------------------------------------------------
# Path 2b: Ablation completeness
# ---------------------------------------------------------------------------

_ABLATION_COMPOUND_RE = re.compile(
    r'ablation\s+(?:table|study|experiment|analysis|result)',
    re.IGNORECASE,
)

_ABLATION_SINGLE_RE = re.compile(r'ablat\w*', re.IGNORECASE)


def _count_ablation_hits(text: str) -> int:
    """
    Count ablation completeness signal.

    Returns:
        Number of ablation hits (each "ablation table/study" counts as 3
        to immediately trigger the threshold; each bare "ablation" counts as 1).
    """
    # ablation table / ablation study each count as 3 (immediately trigger threshold)
    compound_hits = len(_ABLATION_COMPOUND_RE.findall(text))
    if compound_hits > 0:
        return compound_hits * 3  # one compound phrase is enough

    # bare ablation occurrences
    return len(_ABLATION_SINGLE_RE.findall(text))


# ---------------------------------------------------------------------------
# Path 2c: Complexity proof
# ---------------------------------------------------------------------------

_COMPLEXITY_RE = re.compile(
    r'O\([^)]+\)'
    r'|time\s+complexity'
    r'|space\s+complexity'
    r'|polynomial\s+time'
    r'|convergence\s+rate'
    r'|(?:FLOPS|GFLOPs|FLOPs)\b',
    re.IGNORECASE,
)


def _count_complexity_hits(text: str) -> int:
    """Count complexity proof indicators."""
    return len(_COMPLEXITY_RE.findall(text))


# ---------------------------------------------------------------------------
# Path 2d: Dataset scale
# ---------------------------------------------------------------------------

_SCALE_RE = re.compile(
    r'\d+(?:\.\d+)?\s*(?:[Mm]illion|[Bb]illion|[KkMmGgTt])\s*'
    r'(?:samples|parameters|examples|images|tokens|trajectories)',
    re.IGNORECASE,
)


def _count_scale_hits(text: str) -> int:
    """Count dataset/model scale mentions."""
    return len(_SCALE_RE.findall(text))


# ---------------------------------------------------------------------------
# Path 3: Experimental comparison (V11.3 unchanged)
# ---------------------------------------------------------------------------

_COMPARISON_KEYWORDS = frozenset([
    "compare", "compared", "comparison",
    "baseline", "baselines",
    "outperform", "outperforms", "outperformed",
    "versus", " vs ", " vs.", "against",
    "surpass", "surpasses", "surpassed",
    "improve", "improves", "improvement",
    "gain", "gains",
    "better than", "superior to",
    "state-of-the-art", "sota",
])

_NUMERIC_RE = re.compile(r'\d+(?:\.\d+)?')


def _count_comparison_mentions(text: str) -> int:
    """Count experimental comparison indicators."""
    text_lower = text.lower()
    comparison_count = sum(1 for kw in _COMPARISON_KEYWORDS if kw in text_lower)
    if comparison_count == 0:
        return 0
    numeric_count = len(_NUMERIC_RE.findall(text_lower))
    return comparison_count + numeric_count


# ---------------------------------------------------------------------------
# Path 4: Theoretical depth (V11.4 new)
# ---------------------------------------------------------------------------

# Each keyword group: matching any word in the group counts as 1 hit
# We count distinct keyword matches, threshold = 2
_THEORY_KEYWORDS = [
    re.compile(r'\btheorem\b', re.IGNORECASE),
    re.compile(r'\blemma\b', re.IGNORECASE),
    re.compile(r'\bproof\b|\bprove\b|\bproven\b|\bproved\b', re.IGNORECASE),
    re.compile(r'\bproposition\b', re.IGNORECASE),
    re.compile(r'\bcorollary\b', re.IGNORECASE),
    re.compile(r'\bwe\s+prove\b', re.IGNORECASE),
    re.compile(r'\bit\s+can\s+be\s+shown\s+that\b', re.IGNORECASE),
    re.compile(r'\bunder\s+the\s+assumption\b', re.IGNORECASE),
    re.compile(r'\bbound\s+is\s+tight\b', re.IGNORECASE),
    re.compile(r'\bguarantees?\s+that\b', re.IGNORECASE),
    re.compile(r'\bsufficient\s+condition\b', re.IGNORECASE),
    re.compile(r'\bnecessary\s+condition\b', re.IGNORECASE),
]


def _count_theory_hits(text: str) -> int:
    """
    Count distinct theoretical-depth keyword matches.
    Each pattern class counts at most once (prevents single word spam).
    """
    count = 0
    for pat in _THEORY_KEYWORDS:
        if pat.search(text):
            count += 1
    return count


# ---------------------------------------------------------------------------
# V11.4 main API
# ---------------------------------------------------------------------------

def evaluate_physical_depth_v4(text: str) -> dict:
    """
    [V11.4-N2] Evaluate physical depth using refined multi-path logic.

    Paths:
        1   Physical unit mentions (numeric + unit pairs) >= 3
        2a  Performance metric paired with dataset name (±50 char window) >= 1
        2b  Ablation completeness hits >= 3
        2c  Complexity proof hits >= 3
        2d  Dataset/model scale mentions >= 1
        3   Comparison keywords + numeric >= 3
        4   Theory keywords (distinct classes) >= 2

    Returns:
        {
            "passed": bool,
            "passed_paths": list[str],      # e.g. ["path_2a", "path_4"]
            "path_1_count": int,
            "path_2a_pairs": int,
            "path_2b_ablation_count": int,
            "path_2c_complexity_hits": int,
            "path_2d_scale_hits": int,
            "path_3_compare_hits": int,
            "path_4_theory_hits": int,
        }
    """
    if not text or not text.strip():
        return {
            "passed": False,
            "passed_paths": [],
            "path_1_count": 0,
            "path_2a_pairs": 0,
            "path_2b_ablation_count": 0,
            "path_2c_complexity_hits": 0,
            "path_2d_scale_hits": 0,
            "path_3_compare_hits": 0,
            "path_4_theory_hits": 0,
        }

    p1 = _count_physical_unit_mentions(text)
    p2a = _count_perf_dataset_pairs(text)
    p2b = _count_ablation_hits(text)
    p2c = _count_complexity_hits(text)
    p2d = _count_scale_hits(text)
    p3 = _count_comparison_mentions(text)
    p4 = _count_theory_hits(text)

    passed_paths = []
    if p1 >= 3:
        passed_paths.append("path_1")
    if p2a >= 1:
        passed_paths.append("path_2a")
    if p2b >= 3:
        passed_paths.append("path_2b")
    if p2c >= 3:
        passed_paths.append("path_2c")
    if p2d >= 1:
        passed_paths.append("path_2d")
    if p3 >= 3:
        passed_paths.append("path_3")
    if p4 >= 2:
        passed_paths.append("path_4")

    return {
        "passed": len(passed_paths) > 0,
        "passed_paths": passed_paths,
        "path_1_count": p1,
        "path_2a_pairs": p2a,
        "path_2b_ablation_count": p2b,
        "path_2c_complexity_hits": p2c,
        "path_2d_scale_hits": p2d,
        "path_3_compare_hits": p3,
        "path_4_theory_hits": p4,
    }


# ---------------------------------------------------------------------------
# V11.3 backward-compat API (preserved, do not remove)
# ---------------------------------------------------------------------------

@dataclass
class PhysicalDepthResult:
    """Result of the physical depth gate check (V11.3 API)."""
    passed: bool
    path1_count: int
    path2_count: int
    path3_count: int
    path1_passed: bool
    path2_passed: bool
    path3_passed: bool
    threshold: int = 3


# Dataset names for V11.3 path 2 (kept for backward compat)
_DATASET_NAMES = frozenset([
    "coco", "imagenet", "vqa", "vqav2", "nocaps", "vizwiz",
    "okvqa", "textvqa", "gqa", "refcoco", "conceptual captions",
    "laion", "yfcc", "flickr30k", "msvd", "msrvtt",
    "squad", "glue", "superglue", "mnli", "sst",
    "cityscapes", "ade20k", "pascal voc", "lvis",
    "kinetics", "hmdb", "ucf101", "something-something",
    "clevr", "scanqa", "sqa", "scienceqa",
    "winogrande", "hellaswag", "arc", "mmlu", "truthfulqa",
    "gsm8k", "math", "humaneval", "mbpp",
    "mujoco", "atari", "dm control", "dmc", "metaworld",
    "openai gym", "d4rl", "robosuite", "maniskill",
])

_SOTA_PATTERN = re.compile(
    rf'({_NUMERIC_PATTERN})\s*(%|percent|accuracy|ap|map|miou|bleu|rouge|cider|spice|f1)',
    re.IGNORECASE,
)

_ABLATION_KEYWORDS = frozenset([
    "ablation", "ablate",
    "w/o", "without", "removing",
    "component analysis", "contribution",
])


def _count_cs_quantitative_mentions(text: str) -> int:
    """V11.3 Path 2 counter (preserved for backward compat)."""
    text_lower = text.lower()
    count = 0
    count += len(_SOTA_PATTERN.findall(text_lower))
    for dataset in _DATASET_NAMES:
        if dataset in text_lower:
            count += 1
    for kw in _ABLATION_KEYWORDS:
        if kw in text_lower:
            count += 1
    return count


def check_physical_depth(
    abstract: str,
    threshold: int = 3,
) -> PhysicalDepthResult:
    """
    [V11.3-R5] OR-logic physical depth gate (backward compat, preserved).

    For V11.4 callers use evaluate_physical_depth_v4() instead.
    """
    if not abstract or not abstract.strip():
        return PhysicalDepthResult(
            passed=False,
            path1_count=0, path2_count=0, path3_count=0,
            path1_passed=False, path2_passed=False, path3_passed=False,
            threshold=threshold,
        )

    p1 = _count_physical_unit_mentions(abstract)
    p2 = _count_cs_quantitative_mentions(abstract)
    p3 = _count_comparison_mentions(abstract)

    p1_passed = p1 >= threshold
    p2_passed = p2 >= threshold
    p3_passed = p3 >= threshold

    return PhysicalDepthResult(
        passed=p1_passed or p2_passed or p3_passed,
        path1_count=p1,
        path2_count=p2,
        path3_count=p3,
        path1_passed=p1_passed,
        path2_passed=p2_passed,
        path3_passed=p3_passed,
        threshold=threshold,
    )


def has_physical_depth(abstract: str, threshold: int = 3) -> bool:
    """Convenience function: return True if abstract passes any depth path (V11.3 API)."""
    return check_physical_depth(abstract, threshold).passed
