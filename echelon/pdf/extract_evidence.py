"""
Evidence extraction from PDF — AUDIT-015 + AUDIT-058 fix.
V11.3-R2: abstract sentence-split evidence extraction.

The LLM prompt explicitly includes [Page N] markers derived from
pdfplumber.pages so the LLM can copy the correct page number.

The Prompt EXPLICITLY instructs the LLM:
  "evidence_page MUST match the [Page N] label — DO NOT invent page numbers."

V11.3-R2 addition:
  extract_evidence_from_abstract(paper_id, abstract) — splits abstract into
  sentences via pysbd and returns EvidenceAtom list. Resolves the Pilot 1k
  bug where all 10 bottleneck claims had evidence_count = 0.

AUDIT-058: NEGATION_PATTERNS were falsely flagging self-praise as bottlenecks.
  Fix: SELF_PRAISE_PATTERNS check runs BEFORE NEGATION scoring.
  If a window matches SELF_PRAISE_PATTERNS, it is skipped (not a bottleneck).
  9 self-praise patterns from V11.2 are integrated here.
"""
from __future__ import annotations

import json
import logging
from typing import Optional
from uuid import UUID, uuid4

import re

from .parser import PageBlock, build_page_pool, format_with_page_markers, post_validate_evidence_page

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AUDIT-058: Self-praise pattern detection
# Runs BEFORE NEGATION scoring — windows matching these are NOT bottlenecks
# ---------------------------------------------------------------------------

# 9 self-praise pattern types (V11.2 comprehensive set)
SELF_PRAISE_PATTERNS: list[str] = [
    # Pattern 1: achievement comparison — "outperforms X by Y%" or "outperforms all prior"
    r"outperforms?\s+.{0,30}\s+by\s+[\d.]+%?",
    # Pattern 2: SOTA/state-of-the-art claims
    r"(?:achieves?|reaches?|attains?)\s+(?:state-of-the-art|sota|new\s+record)",
    # Pattern 3: "works perfectly without [tuning / adjustment / calibration]"
    r"works?\s+\w*\s*without\s+(?:tuning|adjustment|calibration|modification)",
    # Pattern 4: "never degrades / fails / breaks"
    r"never\s+(?:degrades?|fails?|breaks?|saturates?|diverges?)",
    # Pattern 5: "is not limited by traditional / conventional / previous bounds"
    r"is\s+not\s+limited\s+by\s+(?:traditional|conventional|previous|prior)",
    # Pattern 6: "completely eliminates / fully resolves / entirely removes"
    r"(?:completely|fully|entirely|totally)\s+(?:eliminates?|resolves?|removes?|overcomes?)",
    # Pattern 7: "surpasses all prior / existing / previous methods/baselines"
    r"surpasses?\s+.{0,40}(?:methods?|approaches?|baselines?|benchmarks?|results?)",
    # Pattern 8: "without any compromise / degradation / loss"
    r"without\s+any\s+(?:compromise|degradation|loss|trade-?off|penalty)",
    # Pattern 9: "significantly outperforms / exceeds / beats baseline"
    r"(?:significantly|substantially|dramatically)\s+(?:outperforms?|exceeds?|beats?|improves?\s+over)",
    # Pattern 10 (extra coverage): "outperforms all prior|existing|previous"
    r"outperforms?\s+(?:all\s+)?(?:prior|existing|previous|traditional)",
]


def is_self_praise(window_text: str) -> bool:
    """
    [AUDIT-058] Detect whether a text window is self-praise (NOT a bottleneck).

    Self-praise patterns use negation words ("not limited", "never fails",
    "without") but in a positive/boasting context rather than expressing
    a genuine constraint. NEGATION_PATTERNS would falsely flag these as
    bottleneck evidence, reducing precision.

    This check must run BEFORE any NEGATION scoring. If it fires, the window
    should be skipped (not added to bottleneck evidence).

    Args:
        window_text: The text window being evaluated.

    Returns:
        True if the window matches any SELF_PRAISE_PATTERNS, False otherwise.

    Examples:
        >>> is_self_praise("Our method outperforms SOTA by 5%")
        True
        >>> is_self_praise("Bandwidth is fundamentally limited by the Q-factor")
        False
        >>> is_self_praise("The method works perfectly without tuning")
        True
    """
    text_lower = window_text.lower()
    for pattern in SELF_PRAISE_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True
    return False


def filter_self_praise_from_evidence(
    candidate_spans: list[str],
) -> tuple[list[str], list[str]]:
    """
    [AUDIT-058] Filter self-praise spans from candidate evidence list.

    Applies is_self_praise() to each span and partitions into:
    - kept: genuine bottleneck evidence
    - discarded: self-praise windows (not bottlenecks)

    Args:
        candidate_spans: Raw candidate evidence span strings.

    Returns:
        (kept_spans, discarded_spans)
    """
    kept: list[str] = []
    discarded: list[str] = []
    for span in candidate_spans:
        if is_self_praise(span):
            logger.debug(f"[AUDIT-058] Discarding self-praise span: {span[:80]!r}")
            discarded.append(span)
        else:
            kept.append(span)
    return kept, discarded

# ---------------------------------------------------------------------------
# Prompt template — [AUDIT-015] explicit [Page N] instructions
# ---------------------------------------------------------------------------

EVIDENCE_EXTRACTION_PROMPT = """\
You are extracting bottleneck evidence from a physics paper.

STRICT RULES:
1. evidence_page MUST exactly match the [Page N] label shown above each text block.
   DO NOT invent page numbers. DO NOT guess. Copy the number from [Page N].
2. evidence_span must be an EXACT QUOTE from the text (minimum 10 characters).
3. Include ±1 sentence of context around the target sentence.
4. If no clear bottleneck evidence exists, return an empty list.

Paper ID: {paper_id}
Paper title: {title}

TEXT WITH PAGE MARKERS:
{page_marked_text}

Extract evidence in this JSON format (list of objects):
[
  {{
    "page_no": <integer — COPY from [Page N] label ONLY>,
    "span_text": "<exact quote from text, min 10 chars>",
    "section_type": "limitations|discussion|conclusion|future_work|abstract|body"
  }}
]

Reply with valid JSON only. No markdown fences.
"""


# ---------------------------------------------------------------------------
# Evidence atom dataclass (pure Python, no Pydantic dependency here)
# ---------------------------------------------------------------------------

class RawEvidenceAtom:
    """
    Raw evidence extracted by LLM, before validation.
    Use validate_and_create_atoms() to convert to EvidenceAtom instances.
    """

    __slots__ = ("paper_id", "page_no", "span_text", "section_type")

    def __init__(
        self,
        paper_id: str,
        page_no: Optional[int],
        span_text: str,
        section_type: str = "body",
    ) -> None:
        self.paper_id = paper_id
        self.page_no = page_no
        self.span_text = span_text
        self.section_type = section_type


def build_extraction_prompt(
    paper_id: str,
    title: str,
    blocks: list[PageBlock],
    section_filter: Optional[set[str]] = None,
) -> str:
    """
    Build the evidence extraction prompt with [Page N] markers.

    Args:
        paper_id:       Paper identifier.
        title:          Paper title.
        blocks:         List of PageBlock objects (from parse_pdf_pages).
        section_filter: If given, only include blocks whose section_hint is in this set.

    Returns:
        Formatted prompt string with explicit page markers.
    """
    if section_filter:
        filtered_blocks = [b for b in blocks if b.section_hint in section_filter]
    else:
        filtered_blocks = blocks

    if not filtered_blocks:
        filtered_blocks = blocks  # fallback: include all

    page_marked_text = format_with_page_markers(filtered_blocks)

    return EVIDENCE_EXTRACTION_PROMPT.format(
        paper_id=paper_id,
        title=title,
        page_marked_text=page_marked_text,
    )


def validate_and_create_atoms(
    llm_output: str,
    paper_id: str,
    page_pool: dict[int, str],
) -> tuple[list, list[dict]]:
    """
    Parse LLM JSON output and validate page_no against the real page pool.

    [AUDIT-015] The guard: any evidence whose page_no is not in page_pool
    is rejected — it means the LLM hallucinated a page number.

    Args:
        llm_output: Raw JSON string from the LLM.
        paper_id:   Paper identifier.
        page_pool:  {page_no → text} from build_page_pool().

    Returns:
        (valid_atoms, rejected_items)
        valid_atoms: list of EvidenceAtom instances
        rejected_items: list of raw dicts that failed validation
    """
    # Import here to avoid circular imports
    from echelon.schema.evidence import EvidenceAtom

    try:
        raw_list = json.loads(llm_output)
    except json.JSONDecodeError as exc:
        logger.error(f"LLM output is not valid JSON: {exc}")
        return [], []

    if not isinstance(raw_list, list):
        logger.error(f"LLM output is not a list: {type(raw_list)}")
        return [], []

    valid_atoms: list[EvidenceAtom] = []
    rejected_items: list[dict] = []

    for item in raw_list:
        if not isinstance(item, dict):
            rejected_items.append({"error": "not a dict", "item": item})
            continue

        page_no = item.get("page_no")
        span_text = item.get("span_text", "").strip()
        section_type = item.get("section_type", "body")

        # [AUDIT-015] Validate page_no is in the real parsed pool
        if not post_validate_evidence_page(page_no, page_pool):
            logger.warning(
                f"Rejected evidence with page_no={page_no} (not in pool); "
                f"span={span_text[:50]!r}"
            )
            rejected_items.append({
                "error": f"page_no={page_no} not in parsed pool",
                "item": item,
            })
            continue

        if len(span_text) < 10:
            rejected_items.append({"error": "span_text too short", "item": item})
            continue

        try:
            atom = EvidenceAtom(
                paper_id=paper_id,
                page_no=page_no,       # REAL page from pdfplumber (validated above)
                span_text=span_text,
                section_type=section_type,
            )
            valid_atoms.append(atom)
        except Exception as exc:
            logger.warning(f"EvidenceAtom creation failed: {exc}")
            rejected_items.append({"error": str(exc), "item": item})

    return valid_atoms, rejected_items


# ---------------------------------------------------------------------------
# V11.3-R2: Abstract-based evidence extraction (no PDF required)
# ---------------------------------------------------------------------------

def extract_evidence_from_abstract(
    paper_id: str,
    abstract: str,
    bottleneck_keywords: Optional[list] = None,
    max_atoms: int = 15,
) -> list:
    """
    [V11.3-R2] Extract EvidenceAtom instances from an abstract string.

    Uses pysbd sentence splitting (96%+ accuracy on English academic text).
    Each sentence becomes one EvidenceAtom:
      - page_no = 1  (abstract occupies conceptual page 1)
      - section_type = "abstract"
      - parser = "pysbd_abstract"

    Bottleneck-relevant sentences (containing limitation/challenge/however
    keywords) are prioritised. Fallback: all sentences are used.

    Args:
        paper_id:            Paper identifier.
        abstract:            Raw abstract text.
        bottleneck_keywords: Additional keyword list for relevance matching.
        max_atoms:           Maximum atoms to return (default 15).

    Returns:
        List of EvidenceAtom instances. Empty list if abstract is None/empty.
    """
    from echelon.schema.evidence import EvidenceAtom
    from echelon.pdf.sentence_split import extract_abstract_evidence_atoms

    raw_dicts = extract_abstract_evidence_atoms(
        paper_id=paper_id,
        abstract=abstract or "",
        bottleneck_keywords=bottleneck_keywords,
        max_atoms=max_atoms,
    )

    atoms = []
    for d in raw_dicts:
        try:
            atom = EvidenceAtom(**d)
            atoms.append(atom)
        except Exception as exc:
            logger.warning(f"EvidenceAtom creation failed for {paper_id}: {exc}")

    return atoms


# ---------------------------------------------------------------------------
# AUDIT-046 P1: 双轨召回 — 规则轨 + 语义轨 (bge-m3 / sentence-transformers)
# ---------------------------------------------------------------------------

#: Bottleneck 代理模板列表 (15 条)
BOTTLENECK_TEMPLATES: list[str] = [
    "X remains an open challenge",
    "the limitation of Y",
    "however, this approach suffers from",
    "a key bottleneck is",
    "the fundamental challenge is",
    "current methods fail to",
    "this is hindered by",
    "it is difficult to achieve",
    "one major obstacle is",
    "the scalability of X is limited",
    "existing solutions cannot handle",
    "performance degrades significantly when",
    "there is no efficient method for",
    "future work is needed to address",
    "remains unsolved due to",
]

#: 语义召回相似度阈值
SEMANTIC_RECALL_THRESHOLD: float = 0.35


def _get_embedding_model():
    """
    懒加载 sentence-transformers 模型.
    优先 BAAI/bge-m3, fallback 到 all-MiniLM-L6-v2 (轻量).
    """
    try:
        from sentence_transformers import SentenceTransformer
        try:
            model = SentenceTransformer("BAAI/bge-m3")
            return model
        except Exception:
            model = SentenceTransformer("all-MiniLM-L6-v2")
            return model
    except ImportError:
        return None


def _cosine_similarity(a, b) -> float:
    """两个向量的余弦相似度."""
    import numpy as np
    a = np.array(a, dtype=float)
    b = np.array(b, dtype=float)
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-10:
        return 0.0
    return float(np.dot(a, b) / denom)


def semantic_recall_sentences(
    sentences: list[str],
    templates: list[str] | None = None,
    threshold: float = SEMANTIC_RECALL_THRESHOLD,
    model=None,
) -> list[tuple[str, float]]:
    """
    [AUDIT-046] 语义召回轨: 用 bge-m3 (fallback: all-MiniLM) 计算
    每句 vs 模板列表的最大 cosine 相似度, 超过 threshold 则召回.

    Args:
        sentences:  候选句子列表.
        templates:  模板列表 (默认 BOTTLENECK_TEMPLATES).
        threshold:  cosine 阈值 (默认 0.35).
        model:      可注入的 SentenceTransformer 模型 (供测试).

    Returns:
        召回的 (sentence, max_cosine_score) 列表, 按 score 降序.
    """
    if not sentences:
        return []

    if templates is None:
        templates = BOTTLENECK_TEMPLATES

    if model is None:
        model = _get_embedding_model()

    if model is None:
        # sentence-transformers 不可用 → 退化为空 (规则轨依然有效)
        logger.warning("AUDIT-046: sentence-transformers not available; semantic track disabled.")
        return []

    try:
        template_embs = model.encode(templates, normalize_embeddings=True)
        sent_embs = model.encode(sentences, normalize_embeddings=True)
    except Exception as exc:
        logger.warning(f"AUDIT-046: embedding failed: {exc}")
        return []

    results = []
    for sent, sent_emb in zip(sentences, sent_embs):
        max_score = max(
            _cosine_similarity(sent_emb, t_emb) for t_emb in template_embs
        )
        if max_score >= threshold:
            results.append((sent, float(max_score)))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def dual_track_recall(
    sentences: list[str],
    rule_keywords: list[str] | None = None,
    templates: list[str] | None = None,
    threshold: float = SEMANTIC_RECALL_THRESHOLD,
    model=None,
) -> list[str]:
    """
    [AUDIT-046] 双轨 OR 召回: 规则轨 + 语义轨, 合并去重.

    规则轨: 句子含 bottleneck 关键词 (不区分大小写).
    语义轨: cosine(sentence_emb, template_emb) ≥ threshold.

    OR 策略: 任一轨召回即纳入结果, 提升 recall.

    Args:
        sentences:     候选句子列表.
        rule_keywords: 规则轨关键词 (默认内置瓶颈词).
        templates:     语义轨模板 (默认 BOTTLENECK_TEMPLATES).
        threshold:     语义相似度阈值.
        model:         可注入模型.

    Returns:
        召回的句子列表 (去重, 保持原序).
    """
    if rule_keywords is None:
        rule_keywords = [
            "limitation", "challenge", "bottleneck", "drawback",
            "fail", "difficult", "hinder", "obstacle", "cannot",
            "unsolved", "open problem", "remain", "future work",
        ]

    # 规则轨
    rule_set: set[str] = set()
    for sent in sentences:
        sent_lower = sent.lower()
        if any(kw in sent_lower for kw in rule_keywords):
            rule_set.add(sent)

    # 语义轨
    semantic_hits = {s for s, _ in semantic_recall_sentences(
        sentences, templates=templates, threshold=threshold, model=model
    )}

    # OR 合并, 保持原序
    combined = rule_set | semantic_hits
    return [s for s in sentences if s in combined]
