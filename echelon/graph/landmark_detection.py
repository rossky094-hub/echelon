"""
echelon/graph/landmark_detection.py
V13 里程碑自动识别 + LLM 中文短标签生成

里程碑 = 高 novelty × 高 betweenness × 跨 topic 广度的论文
LLM 标签 = 2-4 个中文字,捕捉颠覆性核心 (如 "双螺旋","超表面","神经辐射场")
"""

import json
import math
import re
import subprocess
from typing import Optional

# ── LLM 提示词 ────────────────────────────────────────────────────────────────

LANDMARK_LABEL_PROMPT = """Read the paper title and abstract. Output a 2-4 Chinese character label
that captures the disruptive core (like "双螺旋", "臭氧空洞", "超表面", "神经辐射场").
NOT a topic word like "机器学习". Must be specific to method/phenomenon.

Title: {title}
Abstract: {abstract}

Output JSON: {{"label": "<2-4 Chinese chars>", "reasoning": "..."}}"""

# ── 里程碑检测 ─────────────────────────────────────────────────────────────────


def _safe_float(v, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def detect_landmarks(
    papers: list[dict],
    novelty_scores: dict[str, float],
    weighted_betweenness: Optional[dict[str, float]] = None,
    top_n: int = 10,
) -> list[dict]:
    """
    Top N 颠覆性里程碑

    综合分 = novelty × betweenness × topic_spread_factor

    Parameters
    ----------
    papers            : 论文列表 (含 openalex_id/paper_id, primary_topic_id, cited_by_count)
    novelty_scores    : {paper_id: float ∈ [0,1]}
    weighted_betweenness : {paper_id: float} 归一化 betweenness centrality
                          若 None, 则用 log(cited_by_count) 代替
    top_n             : 返回 Top N 里程碑

    Returns
    -------
    list of dicts:
        {paper_id, title, abstract, novelty, betweenness,
         topic_spread, composite_score, short_label_zh}
    """
    if not papers:
        return []

    if weighted_betweenness is None:
        weighted_betweenness = {}

    # 计算每篇论文的 topic_spread (跨 topic 广度)
    # = paper 引用的不同 topic 数 / 总可能 topic 数
    # 此处用 referenced_works 数作为 proxy (数量越多, spread 越可能高)
    # (全信号版本需要 fused_edges)
    paper_map: dict[str, dict] = {}
    for p in papers:
        pid = p.get("openalex_id") or p.get("paper_id") or p.get("id", "")
        paper_map[pid] = p

    # 归一化 betweenness
    max_bc = max(weighted_betweenness.values(), default=1.0)
    if max_bc <= 0:
        max_bc = 1.0

    # 归一化 referenced_works 数 (用于 topic_spread proxy)
    ref_counts = []
    for p in papers:
        refs = p.get("referenced_works", []) or []
        ref_counts.append(len(refs))
    max_refs = max(ref_counts, default=1)
    if max_refs <= 0:
        max_refs = 1

    scored: list[dict] = []
    for p in papers:
        pid = p.get("openalex_id") or p.get("paper_id") or p.get("id", "")
        novelty = novelty_scores.get(pid, 0.5)

        # betweenness: 从 weighted_betweenness 取或用 cited_by 代理
        bc_raw = weighted_betweenness.get(pid)
        if bc_raw is not None:
            bc = float(bc_raw) / max_bc
        else:
            cited = _safe_float(p.get("cited_by_count", 0))
            bc = min(math.log(1 + cited) / 8.0, 1.0)

        # topic_spread proxy
        refs = p.get("referenced_works", []) or []
        spread = len(refs) / max_refs

        # 综合颠覆性里程碑分
        composite = novelty * 0.50 + bc * 0.30 + spread * 0.20

        scored.append({
            "paper_id":        pid,
            "title":           p.get("title", ""),
            "abstract":        (p.get("abstract", "") or "")[:500],
            "novelty":         round(novelty, 4),
            "betweenness":     round(bc, 4),
            "topic_spread":    round(spread, 4),
            "composite_score": round(composite, 4),
            "short_label_zh":  "",   # 由 generate_landmark_labels 填充
            "field_name":      p.get("field_name", ""),
            "subfield_name":   p.get("subfield_name", ""),
            "primary_topic_id":   p.get("primary_topic_id", ""),
            "primary_topic_name": p.get("primary_topic_name", ""),
            "cited_by_count":  _safe_float(p.get("cited_by_count", 0)),
        })

    # 按综合分降序取 Top N
    scored.sort(key=lambda x: x["composite_score"], reverse=True)
    return scored[:top_n]


# ── LLM 标签生成 ───────────────────────────────────────────────────────────────

def _call_pplx_llm(prompt: str) -> Optional[str]:
    """
    调用 pplx-tool llm_extract 生成中文标签。
    失败时返回 None。
    """
    try:
        payload = json.dumps({"prompt": prompt, "max_tokens": 128})
        result = subprocess.run(
            ["pplx-tool", "llm_extract"],
            input=payload,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _extract_label_from_response(response_text: str) -> str:
    """
    从 LLM 响应中提取 JSON label 字段。
    失败时返回空字符串。
    """
    if not response_text:
        return ""
    # 尝试解析 JSON
    for candidate in [response_text, response_text.split("```json")[-1].split("```")[0]]:
        try:
            data = json.loads(candidate.strip())
            label = data.get("label", "")
            if label and 2 <= len(label) <= 4:
                return label
        except Exception:
            pass
    # 正则兜底: 找 2-4 中文字
    matches = re.findall(r'[\u4e00-\u9fff]{2,4}', response_text)
    return matches[0] if matches else ""


def _generate_fallback_label(landmark: dict) -> str:
    """
    无法调用 LLM 时的回退标签(基于 topic + 关键词)。
    """
    topic_map = {
        "T10245": "超表面",
        "T11714": "多模态",
        "T10462": "强化学习",
        "T10653": "机器人",
    }
    tid = landmark.get("primary_topic_id", "")
    if tid in topic_map:
        return topic_map[tid]

    title = landmark.get("title", "")
    # 简单启发式: 取标题首个有意义名词
    keywords = ["metasurface", "transformer", "diffusion", "robot", "neural", "quantum"]
    title_lower = title.lower()
    fallback_map = {
        "metasurface": "超表面",
        "transformer":  "注意力",
        "diffusion":    "扩散模型",
        "robot":        "机器人",
        "neural":       "神经网络",
        "quantum":      "量子计算",
    }
    for kw in keywords:
        if kw in title_lower:
            return fallback_map[kw]
    return "前沿研究"


def generate_landmark_labels(landmarks: list[dict]) -> list[dict]:
    """
    为每个里程碑生成 2-4 字中文短标签。
    优先使用 pplx-tool LLM,若不可用则使用规则回退。

    Parameters
    ----------
    landmarks : detect_landmarks() 的输出列表

    Returns
    -------
    landmarks with `short_label_zh` 字段填充
    """
    result = []
    for lm in landmarks:
        prompt = LANDMARK_LABEL_PROMPT.format(
            title=lm.get("title", ""),
            abstract=lm.get("abstract", "")[:300],
        )

        label = ""
        response = _call_pplx_llm(prompt)
        if response:
            label = _extract_label_from_response(response)

        if not label:
            label = _generate_fallback_label(lm)

        result.append({**lm, "short_label_zh": label})

    return result
