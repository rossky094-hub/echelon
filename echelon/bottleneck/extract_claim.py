"""
AUDIT-048 P1: LLM 评分 1-5 离散整数 + Pydantic Field validator
AUDIT-060 P1: Breakthrough Score 完整 abstract + few-shot + 1-5

V11.5 P1-B 变更:
- AUDIT-048: 评分改为 1-5 离散整数, 替代原 0-3 连续浮点
  - discretize_score_1_to_5() 函数 (见 score_keystone.py)
  - Pydantic BreakthroughScore 模型含 Field validator
- AUDIT-060: BREAKTHROUGH_SCORE_PROMPT 重写
  - 读完整 abstract (不截断)
  - 5 条 few-shot 示例 (high/mid/low impact 各级别)
  - 明确 1-5 离散整数输出格式
"""
from __future__ import annotations

from typing import Optional

try:
    from pydantic import BaseModel, Field, field_validator, model_validator
    PYDANTIC_V2 = True
except ImportError:
    try:
        from pydantic import BaseModel, Field, validator as field_validator
        PYDANTIC_V2 = False
    except ImportError:
        raise ImportError("请安装 pydantic: pip install pydantic>=1.10")


# ---------------------------------------------------------------------------
# AUDIT-060 P1: Breakthrough Score Prompt (完整 abstract + few-shot + 1-5)
# ---------------------------------------------------------------------------

BREAKTHROUGH_SCORE_PROMPT = """You are an expert scientific reviewer evaluating the breakthrough potential of a research paper.

TASK: Rate the paper's breakthrough/impact level on a scale of 1-5 (discrete integer only).

SCALE DEFINITION:
  5 = Paradigm shift / foundational breakthrough: completely overturns existing understanding or enables an entirely new class of applications
  4 = Major advance: solves a long-standing bottleneck or opens a significant new direction
  3 = Solid contribution: notable improvement with clear practical or theoretical significance
  2 = Incremental improvement: extends prior work with modest gains
  1 = Descriptive / confirmatory: no novel claim of advancement, primarily characterization or replication

FEW-SHOT EXAMPLES (use these to calibrate your scoring):

Example 1 — Score 5 (Paradigm shift):
Title: "Attention Is All You Need"
Abstract excerpt: "We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely... The Transformer generalizes well to other tasks..."
→ score=5 [Reasoning: Transformer architecture replaced dominant RNN paradigm; foundational for the entire modern LLM era]

Example 2 — Score 4 (Major advance):
Title: "AlphaFold: Improved protein structure prediction using potentials from deep learning"
Abstract excerpt: "We introduce a novel neural network-based model... achieving unprecedented accuracy on the CASP13 benchmark, surpassing all existing methods by a large margin..."
→ score=4 [Reasoning: Solves decades-old protein folding problem; major breakthrough but built on existing ML framework]

Example 3 — Score 3 (Solid contribution):
Title: "Efficient Large-Scale Language Model Training on GPU Clusters"
Abstract excerpt: "We present techniques for training large language models on thousands of GPUs including pipeline parallelism and tensor model parallelism... achieving 52% compute utilization..."
→ score=3 [Reasoning: Significant engineering contribution enabling larger models, but does not change fundamental approach]

Example 4 — Score 2 (Incremental improvement):
Title: "Improved Metasurface Design for 95% Efficiency at 1550nm Wavelength"
Abstract excerpt: "We propose an optimized metasurface geometry achieving 95% transmission efficiency at telecom wavelength, improving on the prior 87% record through geometric parameter sweeping..."
→ score=2 [Reasoning: Numerical improvement within existing paradigm; extends prior work with modest gain]

Example 5 — Score 1 (Descriptive/confirmatory):
Title: "Characterization of Loss Mechanisms in Thin-Film Lithium Niobate Waveguides"
Abstract excerpt: "We systematically measure and characterize propagation loss in TFLN waveguides as a function of etching conditions... Our measurements confirm the dominant contribution of sidewall roughness..."
→ score=1 [Reasoning: Characterization study; no claim of new capability or breakthrough; primarily descriptive]

---

Now evaluate the following paper:

Title: {title}

Abstract (full text):
{abstract}

INSTRUCTIONS:
- Output ONLY a JSON object with exactly one field: {{"score": <integer 1-5>}}
- Do NOT output any explanation, reasoning, or extra text
- The score must be an integer: 1, 2, 3, 4, or 5
- If abstract is missing or uninformative, output {{"score": 1}}

Output:"""


# ---------------------------------------------------------------------------
# AUDIT-048 P1: Pydantic BreakthroughScore model with validator
# ---------------------------------------------------------------------------

class BreakthroughScore(BaseModel):
    """
    [AUDIT-048 P1] Breakthrough Score 1-5 离散整数评分

    Pydantic 模型含 field validator:
    - score 必须为整数 ∈ {1, 2, 3, 4, 5}
    - 允许 float 输入但会 round + clip (宽容解析)
    - 保证排序语义: 不同 score 值不会因 validator 被合并

    Examples:
        >>> bs = BreakthroughScore(score=3)
        >>> bs.score
        3
        >>> bs = BreakthroughScore(score=3.7)  # round → 4
        >>> bs.score
        4
        >>> BreakthroughScore(score=6)  # → clip to 5
        BreakthroughScore(score=5)
        >>> BreakthroughScore(score=0)  # → clip to 1
        BreakthroughScore(score=1)
    """

    score: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Breakthrough score, discrete integer 1-5 (AUDIT-048)",
    )

    if PYDANTIC_V2:
        @field_validator("score", mode="before")
        @classmethod
        def validate_score(cls, v: object) -> int:
            """接受 int/float, round 后 clip 到 [1, 5]"""
            try:
                v_float = float(v)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                raise ValueError(f"score 必须是数值, 收到: {v!r}")
            v_int = int(round(v_float))
            return max(1, min(5, v_int))

    else:
        # Pydantic V1 兼容
        @field_validator("score", pre=True, always=True)
        @classmethod
        def validate_score(cls, v: object) -> int:  # type: ignore[misc]
            try:
                v_float = float(v)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                raise ValueError(f"score 必须是数值, 收到: {v!r}")
            v_int = int(round(v_float))
            return max(1, min(5, v_int))

    def to_component(self) -> float:
        """
        将 1-5 整数评分转换为 [0,1] 分量值 (用于 KeystoneScore)
        1→0.0, 2→0.25, 3→0.5, 4→0.75, 5→1.0
        排序保留: 任意 score_a < score_b → component(a) < component(b)
        """
        return (self.score - 1) / 4.0

    def to_smooth_component(self) -> float:
        """
        [AUDIT-005 P1] 0.5 平滑转换: (component + 0.5) / 5.5
        用于 compute_keystone_score_v5 的几何平均
        """
        raw = self.to_component()
        return (raw + 0.5) / 5.5


class MechanismNoveltyScore(BaseModel):
    """
    [AUDIT-048 P1] 机制新颖性 1-5 离散整数评分

    与 BreakthroughScore 相同的 validator 逻辑, 独立 Pydantic 模型。
    """

    score: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Mechanism novelty score, discrete integer 1-5 (AUDIT-048)",
    )

    if PYDANTIC_V2:
        @field_validator("score", mode="before")
        @classmethod
        def validate_score(cls, v: object) -> int:
            try:
                v_float = float(v)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                raise ValueError(f"score 必须是数值, 收到: {v!r}")
            v_int = int(round(v_float))
            return max(1, min(5, v_int))

    else:
        @field_validator("score", pre=True, always=True)
        @classmethod
        def validate_score(cls, v: object) -> int:  # type: ignore[misc]
            try:
                v_float = float(v)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                raise ValueError(f"score 必须是数值, 收到: {v!r}")
            v_int = int(round(v_float))
            return max(1, min(5, v_int))

    def to_component(self) -> float:
        return (self.score - 1) / 4.0


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def format_breakthrough_prompt(title: str, abstract: str) -> str:
    """
    [AUDIT-060 P1] 格式化 Breakthrough Score Prompt

    使用完整 abstract (不截断), 注入 few-shot 示例。

    Args:
        title:    论文标题
        abstract: 完整摘要文本 (不截断到 100 词)

    Returns:
        格式化后的 prompt 字符串
    """
    # 若 abstract 为空, 用占位符
    if not abstract or not abstract.strip():
        abstract = "[Abstract not available]"

    return BREAKTHROUGH_SCORE_PROMPT.format(
        title=title.strip() if title else "[Title not available]",
        abstract=abstract.strip(),
    )


def parse_breakthrough_response(llm_response: str) -> BreakthroughScore:
    """
    [AUDIT-048 P1] 解析 LLM 输出的 breakthrough score

    解析 JSON {"score": N} 格式, 并通过 Pydantic validator 验证。

    Args:
        llm_response: LLM 输出字符串

    Returns:
        BreakthroughScore (score ∈ {1,2,3,4,5})

    Notes:
        若解析失败, 返回 BreakthroughScore(score=1) (保守默认)
    """
    import json
    import re

    # 尝试提取 JSON
    json_match = re.search(r'\{[^{}]*"score"\s*:\s*(\d+(?:\.\d+)?)[^{}]*\}', llm_response)
    if json_match:
        try:
            data = json.loads(json_match.group(0))
            score_raw = data.get("score", 1)
            return BreakthroughScore(score=score_raw)
        except Exception:
            pass

    # 纯数字 fallback (提取第一个 1-5 整数)
    num_match = re.search(r'\b([1-5])\b', llm_response)
    if num_match:
        return BreakthroughScore(score=int(num_match.group(1)))

    # 解析失败 → 保守默认
    return BreakthroughScore(score=1)


# AUDIT-018 + AUDIT-021: Bottleneck Claim Extraction
import json as _json
import logging as _logging
import re as _re
_logger = _logging.getLogger(__name__)

CLAIM_EXTRACTION_PROMPT_V2 = (
    "You are extracting bottleneck claims from a physics/AI paper.\n\n"
    "A 'bottleneck claim' is a SPECIFIC UNSOLVED CONSTRAINT.\n\n"
    "6 required properties:\n"
    "1. claim_text (10-500 chars)\n"
    "2. claim_type: limitation|failure|metric_boundary|unresolved\n"
    "3. severity: weak|limitation|failure|constraint|unresolved\n"
    "4. binds_metric, binds_mechanism, binds_condition, binds_threshold, binds_optimization_objective\n"
    "   evidence_id, evidence_span, evidence_page, evidence_section\n"
    "5. [AUDIT-018] attempted_circumvention: [] or list of workaround evidence (small positive signal)\n"
    "6. [AUDIT-018] claimed_resolution: [] or list of resolution claims (negative signal)\n\n"
    "IMPORTANT DISTINCTION (AUDIT-018):\n"
    "  - attempted_circumvention = 'we work around it' (partial, still a constraint)\n"
    "  - claimed_resolution = 'we SOLVE it' (if real, may not be a bottleneck)\n\n"
    "Paper ID: {paper_id}\nPaper title: {title}\n\nEVIDENCE TEXT:\n{evidence_text}\n"
)


def build_claim_extraction_prompt(paper_id: str, title: str, evidence_text: str) -> str:
    """[AUDIT-021] Build claim extraction prompt with all 6 properties."""
    return CLAIM_EXTRACTION_PROMPT_V2.format(
        paper_id=paper_id, title=title, evidence_text=evidence_text)


def parse_claim_extraction_response(llm_output: str, paper_id: str) -> tuple:
    """[AUDIT-021] Parse LLM output; defaults attempted_circumvention/claimed_resolution to []."""
    try:
        cleaned = _re.sub(r"```(?:json)?|```", "", llm_output).strip()
        raw_list = _json.loads(cleaned)
    except Exception:
        return [], []
    if not isinstance(raw_list, list):
        return [], []
    valid, rejected = [], []
    for item in raw_list:
        if not isinstance(item, dict):
            rejected.append({"error": "not a dict", "item": item})
            continue
        if len(item.get("claim_text", "").strip()) < 10:
            rejected.append({"error": "claim_text too short", "item": item})
            continue
        if "attempted_circumvention" not in item or item["attempted_circumvention"] is None:
            item["attempted_circumvention"] = []
        if "claimed_resolution" not in item or item["claimed_resolution"] is None:
            item["claimed_resolution"] = []
        valid.append(item)
    return valid, rejected


def extract_claims_from_evidence(paper_id, title, evidence_text, llm_callable) -> tuple:
    """[AUDIT-018+021] End-to-end claim extraction."""
    prompt = build_claim_extraction_prompt(paper_id, title, evidence_text)
    try:
        raw = llm_callable(prompt)
    except Exception:
        return [], []
    return parse_claim_extraction_response(raw, paper_id)




# ---------------------------------------------------------------------------
# AUDIT-018 + AUDIT-021: Bottleneck Claim Extraction Prompt & Parser
# (Restored from V11.4 — required by existing test_p1_schema_prompt.py)
# ---------------------------------------------------------------------------

import json as _json
import logging as _logging
import re as _re

_logger = _logging.getLogger(__name__)


# AUDIT-021: Full 6-property claim extraction prompt
# AUDIT-018: Distinguishes attempted_circumvention (small positive) vs claimed_resolution (negative)
CLAIM_EXTRACTION_PROMPT_V2 = """\
You are extracting bottleneck claims from a physics/AI paper.

A "bottleneck claim" is a SPECIFIC UNSOLVED CONSTRAINT — NOT an achievement or solved problem.

STRICT RULES:
1. claim_text: 1 sentence, 10-500 chars, describes the UNSOLVED constraint.
2. claim_type: one of "limitation" | "failure" | "metric_boundary" | "unresolved"
3. severity: one of "weak" | "limitation" | "failure" | "constraint" | "unresolved"
4. Physical depth (5 binds_* booleans — answer each explicitly):
   - binds_metric: does the claim name a quantifiable physical metric?
   - binds_mechanism: does it name an explicit physical mechanism?
   - binds_condition: is it bound to specific experimental conditions?
   - binds_threshold: does it give a numerical threshold?
   - binds_optimization_objective: does it bind a formal optimization objective or NN architecture?
5. Evidence fields:
   - evidence_id: "{paper_id}_p{{page}}_{{3-letter-suffix}}"
   - evidence_span: verbatim quote from the paper (10-500 chars)
   - evidence_page: integer page number (or 0 if unknown)
   - evidence_section: one of "abstract" | "intro" | "method" | "result" | "discussion" | "conclusion" | "other"
6. [AUDIT-018] Anti-incremental signals (distinguish carefully):
   - attempted_circumvention: list of evidence_span snippets where the paper
     TRIED TO WORK AROUND this constraint (small positive signal — confirms constraint is real).
     NOT the same as solving it. Leave [] if no such attempt found.
   - claimed_resolution: list of evidence_span snippets where the paper
     CLAIMS TO FULLY RESOLVE this constraint (negative signal — may not be a bottleneck).
     Leave [] if no resolution is claimed.

IMPORTANT DISTINCTION (AUDIT-018):
  - attempted_circumvention = "we work around it" (partial, still a constraint)
  - claimed_resolution = "we SOLVE it" (if real, this claim may not be a bottleneck)

Output format: JSON array of claim objects.
Each object must have ALL fields: claim_text, claim_type, severity,
binds_metric, binds_mechanism, binds_condition, binds_threshold, binds_optimization_objective,
evidence_id, evidence_span, evidence_page, evidence_section,
attempted_circumvention (list), claimed_resolution (list).

Paper ID: {paper_id}
Abstract: {abstract}
Full text snippet: {text_snippet}
"""


def build_claim_extraction_prompt(
    paper_id: str,
    abstract: str,
    text_snippet: str = "",
) -> str:
    """
    [AUDIT-021] Build the full claim extraction prompt.

    Args:
        paper_id:     Paper identifier (used in evidence_id)
        abstract:     Paper abstract
        text_snippet: Additional text (optional)

    Returns:
        Formatted prompt string
    """
    return CLAIM_EXTRACTION_PROMPT_V2.format(
        paper_id=paper_id,
        abstract=abstract.strip() if abstract else "[Abstract not available]",
        text_snippet=text_snippet.strip() if text_snippet else "",
    )


def parse_claim_extraction_response(
    llm_response: str,
    paper_id: str,
) -> tuple:
    """
    [AUDIT-021] Parse LLM claim extraction response.

    Defaults attempted_circumvention and claimed_resolution to [] when omitted.

    Args:
        llm_response: Raw LLM output (JSON array expected)
        paper_id:     Paper identifier

    Returns:
        (valid_claims: list[dict], rejected: list[dict])
    """
    valid = []
    rejected = []

    # Extract JSON array from response
    json_match = _re.search(r'\[.*\]', llm_response, _re.DOTALL)
    if not json_match:
        _logger.warning(f"[AUDIT-021] No JSON array found in response for {paper_id}")
        return valid, rejected

    try:
        claims = _json.loads(json_match.group(0))
    except _json.JSONDecodeError as e:
        _logger.warning(f"[AUDIT-021] JSON parse error for {paper_id}: {e}")
        return valid, rejected

    if not isinstance(claims, list):
        return valid, rejected

    required_fields = {
        "claim_text", "claim_type", "severity",
        "binds_metric", "binds_mechanism", "binds_condition",
        "binds_threshold", "binds_optimization_objective",
        "evidence_id", "evidence_span",
    }

    for claim in claims:
        if not isinstance(claim, dict):
            rejected.append({"raw": claim, "reason": "not a dict"})
            continue

        missing = required_fields - claim.keys()
        if missing:
            rejected.append({"raw": claim, "reason": f"missing fields: {missing}"})
            continue

        # [AUDIT-021] Default anti-incremental fields to [] when omitted
        if "attempted_circumvention" not in claim or claim["attempted_circumvention"] is None:
            claim["attempted_circumvention"] = []
        if "claimed_resolution" not in claim or claim["claimed_resolution"] is None:
            claim["claimed_resolution"] = []

        # Default optional fields
        claim.setdefault("evidence_page", 0)
        claim.setdefault("evidence_section", "other")
        claim.setdefault("metric_value", None)
        claim.setdefault("metric_unit", None)

        valid.append(claim)

    return valid, rejected
