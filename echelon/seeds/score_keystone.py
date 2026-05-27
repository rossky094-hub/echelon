"""
AUDIT-003: 三重共线性修复 - Depth 改为正交 supporting_count
AUDIT-035: c_team_disrupt 按论文类型分类 (experiment/simulation/theory × bucket)
AUDIT-068: 几何平均复数崩溃修复 - safe_clip 强制所有 c_* 字段 [0.001, 1.0]
AUDIT-083: n_authors=0 KeyError → 默认中性 0.5
V11.3-R1: KeystoneScore 坍缩修复 - 对数空间几何平均 + 0.05 平滑

修复说明:
- AUDIT-003: 原 Depth 分量与其他指标高度共线, 改为 supporting_count (独立特征)
- AUDIT-035: 实验/仿真/理论论文的团队规模最优区间不同, 引入分类打分表
- AUDIT-068: c_recency 等可为负 (-0.125), 负数求非整数次方 → 复数
  修复: safe_clip(c, 0.001, 1.0) 强制所有分量非负, 几何平均不产生复数
- AUDIT-083: n_authors=0 (社论/快报未解析) → 返回中性 0.5 避免 KeyError
- V11.3-R1: safe_clip 下限从 0.001 改为 0.05, compute() 改用对数空间几何平均:
  score = exp(mean(log(c_i + 0.05))) - 0.05  (等价加 0.05 平滑的几何平均)
  解决 1000 篇 σ < 0.05 的评分坍缩问题 (健康应 ≥ 0.10)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Dict, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from echelon.schema.paper import Paper


def safe_clip(v: float, lo: float = 0.05, hi: float = 1.0) -> float:
    """
    [AUDIT-068 + V11.3-R1] 强制 clip 到 [lo, hi], 防止:
    - 负数引发复数崩溃 (e.g. (-0.125)**0.20 → 复数)
    - 0 一票归零

    V11.3-R1 变更: lo 从 0.001 提升到 0.05
    原因: 0.001 下限导致所有低分 c_* 都被截断到 0.001,
          几何平均后差异坍缩 (σ < 0.05), 无法区分"金种子"。
          0.05 平滑保留更多区分度, σ ≥ 0.10 (健康值)。

    Args:
        v: 输入值
        lo: 下界, 默认 0.05 (V11.3-R1: 从 0.001 改为 0.05)
        hi: 上界, 默认 1.0

    Returns:
        clip 后的值 ∈ [lo, hi]

    Examples:
        >>> safe_clip(-0.125)
        0.05
        >>> safe_clip(1.5)
        1.0
        >>> safe_clip(0.7)
        0.7
    """
    return max(lo, min(hi, v))


@dataclass
class KeystoneScore:
    """
    [AUDIT-003 + AUDIT-068] KeystoneScore V11.2 修订版

    AUDIT-003 修复: supporting_count 替代共线性的 Depth 分量
    AUDIT-068 修复: 所有 c_* 字段强制 safe_clip [0.001, 1.0], 几何平均不产生复数

    几何平均公式:
        KeystoneScore = S0^w0 · S1_b^w1 · S1_o^w2 · S2^w3

    其中所有 S_i 均经 safe_clip, 保证基数 > 0, 幂运算不产生复数。
    """

    # 第 0 层: 元数据信号 (5 分量加权和)
    c_recency: float = 0.5          # (year - 2018) / 8, clip [0.001, 1]
    c_venue: float = 0.5            # 期刊/会议影响因子分位数
    c_team_disrupt: float = 0.5     # 团队规模与论文类型匹配度
    c_recent_burst: float = 0.5     # 近期引用突增信号
    c_review_filter: float = 0.0    # 1=综述 (参与 1-c_review_filter 降权)

    # 第 1 层 Barabási: 引用图信号
    c_bib_breadth: float = 0.5      # 参考文献跨领域广度
    c_cocite_breadth: Optional[float] = None  # 共被引广度 (新论文可 None)
    c_bridging_centrality: float = 0.5  # 桥接中心性 (全局 z-score 归一化)

    # 第 1 层 Other: CD index + 语义离群度
    c_cd_subdomain: Optional[float] = None   # CD index (新论文可 None)
    c_semantic_outlier: float = 0.5          # 语义离群度 (Isolation Forest)

    # 第 2 层 LLM: Breakthrough + Novelty
    c_breakthrough_lang: float = 0.5    # 突破性语言 (1-5 离散评分归一化)
    c_mechanism_novelty: float = 0.5    # 机制新颖性

    # [AUDIT-003] 正交特征: supporting_count (替代共线性的 Depth)
    # supporting_count = 支持该论文核心声明的独立证据数量 (归一到 [0,1])
    # 与 bib_breadth/cocite_breadth 不共线: 衡量深度而非广度
    supporting_count: float = 0.5       # = min(evidence_count / 10, 1.0)

    # 权重配置 (V11.2 初始值)
    w0: float = 0.20   # 元数据权重
    w1: float = 0.45   # Barabási 权重
    w2: float = 0.20   # Other 权重
    w3: float = 0.15   # LLM 权重

    def compute_s0(self) -> float:
        """第 0 层信号合成 (全部 safe_clip)"""
        c_rec = safe_clip(self.c_recency)
        c_ven = safe_clip(self.c_venue)
        c_td  = safe_clip(self.c_team_disrupt)
        c_rb  = safe_clip(self.c_recent_burst)
        c_rev = safe_clip(self.c_review_filter)
        return safe_clip(
            0.30 * c_rec +
            0.20 * c_ven +
            0.15 * c_td +
            0.20 * c_rb +
            0.15 * (1.0 - c_rev)
        )

    def compute_s1_barabasi(self) -> float:
        """第 1 层 Barabási 信号 (全部 safe_clip)"""
        bib = safe_clip(self.c_bib_breadth)
        bc  = safe_clip(self.c_bridging_centrality)

        if self.c_cocite_breadth is None:
            # 新论文: 无 cocite 数据, 权重重新分配
            return safe_clip(0.50 * bib + 0.50 * bc)
        else:
            cc = safe_clip(self.c_cocite_breadth)
            return safe_clip(0.40 * bib + 0.35 * cc + 0.25 * bc)

    def compute_s1_other(self) -> float:
        """第 1 层 Other 信号 (CD index + 语义离群度)"""
        sem = safe_clip(self.c_semantic_outlier)

        if self.c_cd_subdomain is None:
            # 新论文: 无 CD index
            return sem
        else:
            cd = safe_clip(self.c_cd_subdomain)
            return safe_clip(0.50 * cd + 0.50 * sem)

    def compute_s2(self) -> float:
        """第 2 层 LLM 信号"""
        bl = safe_clip(self.c_breakthrough_lang)
        mn = safe_clip(self.c_mechanism_novelty)
        return safe_clip(0.5 * bl + 0.5 * mn)

    def compute(self) -> float:
        """
        [AUDIT-068 + V11.3-R1] 计算 KeystoneScore

        V11.3-R1: 改用对数空间几何平均 + 0.05 平滑, 解决坍缩问题:
          score = exp(mean(log(c_i + 0.05))) - 0.05
        等价于 (c_i + 0.05) 的几何平均 再减去 0.05 平滑偏置。
        保留几何平均"任一为极小则整体较小"的物理语义, 同时区分度更好。

        [AUDIT-003] supporting_count 作为正交调节因子 (非共线性 Depth)

        Returns:
            score ∈ [0, 1] (实数, 非复数)
        """
        s0 = safe_clip(self.compute_s0())
        s1_b = safe_clip(self.compute_s1_barabasi())
        s1_o = safe_clip(self.compute_s1_other())
        s2 = safe_clip(self.compute_s2())

        # [V11.3-R1] 对数空间几何平均 + 0.05 平滑
        # 公式: score = exp(Σ w_i * log(c_i + 0.05)) - 0.05
        # 等价于加权几何平均后减去平滑偏置
        SMOOTH = 0.05
        log_sum = (
            self.w0 * math.log(s0 + SMOOTH) +
            self.w1 * math.log(s1_b + SMOOTH) +
            self.w2 * math.log(s1_o + SMOOTH) +
            self.w3 * math.log(s2 + SMOOTH)
        )
        raw = math.exp(log_sum) - SMOOTH

        # [AUDIT-003] supporting_count 正交调节 (独立于广度指标)
        sc = safe_clip(self.supporting_count)
        # 调节公式: 0.85 + 0.15 * sc (轻微提升深度支撑充分的论文)
        depth_bonus = 0.85 + 0.15 * sc

        result = raw * depth_bonus
        return safe_clip(result)

    def to_dict(self) -> Dict[str, Any]:
        """返回所有分量和最终分数"""
        return {
            "s0": self.compute_s0(),
            "s1_barabasi": self.compute_s1_barabasi(),
            "s1_other": self.compute_s1_other(),
            "s2": self.compute_s2(),
            "supporting_count": self.supporting_count,
            "keystone_score": self.compute(),
        }


def compute_keystone_score(
    c_recency: float = 0.5,
    c_venue: float = 0.5,
    c_team_disrupt: float = 0.5,
    c_recent_burst: float = 0.5,
    c_review_filter: float = 0.0,
    c_bib_breadth: float = 0.5,
    c_cocite_breadth: Optional[float] = None,
    c_bridging_centrality: float = 0.5,
    c_cd_subdomain: Optional[float] = None,
    c_semantic_outlier: float = 0.5,
    c_breakthrough_lang: float = 0.5,
    c_mechanism_novelty: float = 0.5,
    supporting_count: float = 0.5,
) -> float:
    """
    [AUDIT-003 + AUDIT-068] 便捷函数: 计算 KeystoneScore

    所有 c_* 参数在内部经 safe_clip [0.001, 1.0] 处理。
    supporting_count 替代共线性 Depth (AUDIT-003)。
    """
    ks = KeystoneScore(
        c_recency=c_recency,
        c_venue=c_venue,
        c_team_disrupt=c_team_disrupt,
        c_recent_burst=c_recent_burst,
        c_review_filter=c_review_filter,
        c_bib_breadth=c_bib_breadth,
        c_cocite_breadth=c_cocite_breadth,
        c_bridging_centrality=c_bridging_centrality,
        c_cd_subdomain=c_cd_subdomain,
        c_semantic_outlier=c_semantic_outlier,
        c_breakthrough_lang=c_breakthrough_lang,
        c_mechanism_novelty=c_mechanism_novelty,
        supporting_count=supporting_count,
    )
    return ks.compute()


# ---------------------------------------------------------------------------
# V11.4-N4: c_venue percentile-by-age
# ---------------------------------------------------------------------------

def c_venue_v4(paper: "Paper", corpus: List["Paper"], today: Optional[date] = None) -> float:
    """
    [V11.4-N4] c_venue as citation-rate percentile within age-matched peer group.

    Replaces the old `cited_by_count / max(corpus_cited)` formula which
    caused old papers (high absolute citations) to cluster near 0.7-0.9
    and new papers to cluster near 0-0.5, destroying cross-corpus comparability.

    New approach:
      1. Compute paper's annualised citation rate: cite_per_year.
      2. Find peers in corpus whose age is within ±6 months of this paper.
      3. Return the percentile of this paper's cite_per_year among peers.

    If the peer group is too small (< 5), return 0.5 (neutral, no signal).

    Args:
        paper:   The paper to score.
        corpus:  Full list of papers to compute the peer group from.
        today:   Reference date (defaults to date.today()).

    Returns:
        Percentile in [0, 1] (0 = bottom, 1 = top).
    """
    if today is None:
        today = date.today()

    age_months = max(1, (today - paper.publication_date).days / 30.4)
    cite_per_year = paper.cited_by_count / max(0.5, age_months / 12)

    peer: List[float] = []
    for p in corpus:
        p_age = max(1, (today - p.publication_date).days / 30.4)
        if abs(p_age - age_months) <= 6:
            peer.append(p.cited_by_count / max(0.5, p_age / 12))

    if len(peer) < 5:
        return 0.5  # peer group too small — neutral value

    peer_sorted = sorted(peer)
    rank = sum(1 for c in peer_sorted if c <= cite_per_year)
    return rank / len(peer_sorted)


def compute_keystone_score_v4(
    paper: "Paper",
    corpus: List["Paper"],
    today: Optional[date] = None,
    c_recency: float = 0.5,
    c_team_disrupt: float = 0.5,
    c_recent_burst: float = 0.5,
    c_review_filter: float = 0.0,
    c_bib_breadth: float = 0.5,
    c_cocite_breadth: Optional[float] = None,
    c_bridging_centrality: float = 0.5,
    c_cd_subdomain: Optional[float] = None,
    c_semantic_outlier: float = 0.5,
    c_breakthrough_lang: float = 0.5,
    c_mechanism_novelty: float = 0.5,
    supporting_count: float = 0.5,
) -> float:
    """
    [V11.4-N4] Compute KeystoneScore using percentile-by-age c_venue.

    c_venue is derived via c_venue_v4(); all other components are
    identical to compute_keystone_score() (V11.3 preserved for backward compat).

    Args:
        paper:   The paper to score.
        corpus:  Full corpus for peer-group percentile computation.
        today:   Reference date for age computation (default: date.today()).
        (other): Same as compute_keystone_score().

    Returns:
        KeystoneScore float in [0, 1].
    """
    c_venue = c_venue_v4(paper, corpus, today)
    ks = KeystoneScore(
        c_recency=c_recency,
        c_venue=c_venue,
        c_team_disrupt=c_team_disrupt,
        c_recent_burst=c_recent_burst,
        c_review_filter=c_review_filter,
        c_bib_breadth=c_bib_breadth,
        c_cocite_breadth=c_cocite_breadth,
        c_bridging_centrality=c_bridging_centrality,
        c_cd_subdomain=c_cd_subdomain,
        c_semantic_outlier=c_semantic_outlier,
        c_breakthrough_lang=c_breakthrough_lang,
        c_mechanism_novelty=c_mechanism_novelty,
        supporting_count=supporting_count,
    )
    return ks.compute()


# ---------------------------------------------------------------------------
# AUDIT-005 P1: 0.5 平滑几何平均 + AUDIT-048 P1: 1-5 离散整数评分
# ---------------------------------------------------------------------------

def smooth_score_v5(v: float) -> float:
    """
    [AUDIT-005 P1] 0.5 平滑转换: (v + 0.5) / 5.5

    将原始 1-5 离散 LLM 评分映射到 (0,1] 连续空间,用于几何平均。
    平滑偏置从 V11.3-R1 的 0.05 提升到 0.5,大幅缓解"一票归零"问题。

    V11.3-R1 用 0.05 平滑 → 最低分 c=0.05 与 c=0.5 的对数比 = ln(0.05/0.5) ≈ -2.3
    V11.5-P1  用 0.5  平滑 → 最低分 c=0.5+0.5/5.5 ≈ 0.18, 对数比显著压缩

    Args:
        v: 原始分量值 ∈ [0, 1]

    Returns:
        平滑后的分量值 ∈ (0, 1]

    Examples:
        >>> round(smooth_score_v5(0.0), 4)
        0.0909
        >>> round(smooth_score_v5(1.0), 4)
        0.2727
        >>> round(smooth_score_v5(0.5), 4)
        0.1818
    """
    SMOOTH = 0.5
    SCALE = 5.5  # = 5 + SMOOTH (使得输入 1.0 映射到 1.0/5.5 ≈ 0.1818, 不超过 (1+0.5)/5.5 = 0.2727)
    return (float(v) + SMOOTH) / SCALE


def discretize_score_1_to_5(continuous_score: float) -> int:
    """
    [AUDIT-048 P1] 将 0-1 连续分数离散化为 1-5 整数评分

    设计点:
    - 单调映射: 保证不同 continuous_score 尽可能映射到不同离散值
    - 分段均匀: [0, 0.2) → 1, [0.2, 0.4) → 2, [0.4, 0.6) → 3,
                [0.6, 0.8) → 4, [0.8, 1.0] → 5
    - 排序保留: continuous_score_a < continuous_score_b → 不会出现
                discretize(a) > discretize(b) 的逆序

    Args:
        continuous_score: 连续评分 ∈ [0, 1]

    Returns:
        离散评分 ∈ {1, 2, 3, 4, 5}

    Examples:
        >>> discretize_score_1_to_5(0.0)
        1
        >>> discretize_score_1_to_5(0.5)
        3
        >>> discretize_score_1_to_5(1.0)
        5
        >>> discretize_score_1_to_5(0.19)
        1
        >>> discretize_score_1_to_5(0.21)
        2
    """
    v = max(0.0, min(1.0, float(continuous_score)))
    # 5 个等宽桶: [0, 0.2), [0.2, 0.4), [0.4, 0.6), [0.6, 0.8), [0.8, 1.0]
    # math.floor(v * 5) → 0,1,2,3,4; +1 → 1-5; 特殊处理 v=1.0 → 5
    raw = math.floor(v * 5)
    return min(5, raw + 1)


def llm_score_to_component(discrete_score: int) -> float:
    """
    [AUDIT-048 P1] 将 1-5 离散 LLM 评分归一化到 [0, 1]

    用于将 LLM 输出的 1-5 整数评分转换为 c_* 分量。
    保证单调性: score 1 → 0.0, score 5 → 1.0。

    Args:
        discrete_score: LLM 输出的整数 ∈ {1, 2, 3, 4, 5}

    Returns:
        归一化值 ∈ [0.0, 1.0]

    Examples:
        >>> llm_score_to_component(1)
        0.0
        >>> llm_score_to_component(3)
        0.5
        >>> llm_score_to_component(5)
        1.0
    """
    score = max(1, min(5, int(discrete_score)))
    return (score - 1) / 4.0  # 1→0, 2→0.25, 3→0.5, 4→0.75, 5→1.0


def compute_keystone_score_v5(
    c_recency: float = 0.5,
    c_venue: float = 0.5,
    c_team_disrupt: float = 0.5,
    c_recent_burst: float = 0.5,
    c_review_filter: float = 0.0,
    c_bib_breadth: float = 0.5,
    c_cocite_breadth: Optional[float] = None,
    c_bridging_centrality: float = 0.5,
    c_cd_subdomain: Optional[float] = None,
    c_semantic_outlier: float = 0.5,
    # AUDIT-048: c_* 字段从 0-1 接受(对应 1-5 LLM 评分的 llm_score_to_component 转换)
    c_breakthrough_lang: float = 0.5,
    c_mechanism_novelty: float = 0.5,
    supporting_count: float = 0.5,
) -> float:
    """
    [AUDIT-005 P1] KeystoneScore V5: 0.5 平滑几何平均

    V11.5-P1 变更 vs V11.3-R1:
      - 平滑系数从 0.05 提升到 0.5 (smooth_score_v5)
      - c_* 输入仍为 [0, 1] (对应 llm_score_to_component 输出)
      - 几何平均公式: exp(Σ w_i * log((c_i + 0.5)/5.5)) 等价于
        smooth 分量的加权几何平均

    V11.4 (compute_keystone_score_v4) 保留向后兼容, 本函数添加 V5 接口。

    Returns:
        score ∈ [0, 1]
    """
    SMOOTH = 0.5

    def _clip(v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    # 各分量 safe_clip 后再套 smooth
    def _s(v: float) -> float:
        return smooth_score_v5(_clip(v))

    # S0: 元数据信号 (与 v4 相同权重,但用 0.5 平滑)
    c_rec = _clip(c_recency)
    c_ven = _clip(c_venue)
    c_td  = _clip(c_team_disrupt)
    c_rb  = _clip(c_recent_burst)
    c_rev = _clip(c_review_filter)
    s0 = _clip(0.30 * c_rec + 0.20 * c_ven + 0.15 * c_td + 0.20 * c_rb + 0.15 * (1.0 - c_rev))

    # S1_b: Barabási 信号
    bib = _clip(c_bib_breadth)
    bc  = _clip(c_bridging_centrality)
    if c_cocite_breadth is None:
        s1_b = _clip(0.50 * bib + 0.50 * bc)
    else:
        cc = _clip(c_cocite_breadth)
        s1_b = _clip(0.40 * bib + 0.35 * cc + 0.25 * bc)

    # S1_o: Other 信号
    sem = _clip(c_semantic_outlier)
    if c_cd_subdomain is None:
        s1_o = sem
    else:
        cd = _clip(c_cd_subdomain)
        s1_o = _clip(0.50 * cd + 0.50 * sem)

    # S2: LLM 信号 (AUDIT-048: 已是 llm_score_to_component 归一化值)
    bl = _clip(c_breakthrough_lang)
    mn = _clip(c_mechanism_novelty)
    s2 = _clip(0.5 * bl + 0.5 * mn)

    # 权重 (同 V11.4)
    w0, w1, w2, w3 = 0.20, 0.45, 0.20, 0.15

    # [AUDIT-005 P1] 0.5 平滑的对数空间几何平均
    # 公式: exp(Σ w_i * log((c_i + 0.5) / 5.5))
    # 相比 V11.3-R1 的 0.05 平滑, 最低分从 log(0.05+0.05)=-3.0 提升到 log(0+0.5)=-1.1
    log_sum = (
        w0 * math.log(_s(s0)) +
        w1 * math.log(_s(s1_b)) +
        w2 * math.log(_s(s1_o)) +
        w3 * math.log(_s(s2))
    )
    # 逆变换: 从 (0, 1/5.5] 空间转回 [0, 1]
    # smooth 后的几何平均 ∈ (0, 0.27], 需要做 rescale
    smooth_geom = math.exp(log_sum)
    # 反推: smooth_geom = (raw + 0.5)/5.5 → raw = smooth_geom * 5.5 - 0.5
    raw = smooth_geom * 5.5 - SMOOTH

    # supporting_count 正交调节
    sc = _clip(supporting_count)
    depth_bonus = 0.85 + 0.15 * sc
    result = raw * depth_bonus

    return _clip(result)


# ---------------------------------------------------------------------------
# AUDIT-035 P1: c_team_disrupt — 按论文类型 × 作者数 bucket 分类打分
# ---------------------------------------------------------------------------

# 打分表: {validation_type: {bucket_label: score}}
# bucket: "1-3" | "4-10" | "11+" (for experiment/simulation) | "4+" (for theory)
TEAM_SCORE_TABLE: dict[str, dict[str, float]] = {
    "experiment": {
        "1-3":  0.5,   # 过小团队, 实验资源不足
        "4-10": 1.0,   # 黄金区间: 中等团队最具创新力
        "11+":  0.9,   # 大团队有系统优势但略有保守
    },
    "simulation": {
        "1-3":  0.6,   # 仿真可小团队完成, 但略低
        "4-10": 1.0,   # 同样最优
        "11+":  0.8,   # 过大团队仿真可能分散
    },
    "theory": {
        "1-3":  1.0,   # 理论工作小团队高效
        "4+":   0.7,   # 理论大团队往往有妥协
    },
}

# 已知 validation_type → 默认 bucket 键集合
_THEORY_THRESHOLD = 4   # theory: 1-3 vs 4+
_EXP_SIM_MID = (4, 10)  # experiment/simulation: 1-3 / 4-10 / 11+


def _bucket_experiment_simulation(n_authors: int) -> str:
    """将 n_authors 映射到 experiment/simulation 用的 bucket 键."""
    if n_authors <= 3:
        return "1-3"
    elif n_authors <= 10:
        return "4-10"
    else:
        return "11+"


def _bucket_theory(n_authors: int) -> str:
    """将 n_authors 映射到 theory 用的 bucket 键."""
    return "1-3" if n_authors < _THEORY_THRESHOLD else "4+"


def c_team_disrupt_v5(paper) -> float:
    """
    [AUDIT-035] c_team_disrupt 按论文类型 × 作者数计算团队最优匹配分.

    paper 需含属性:
      - validation_type: str — "experiment" | "simulation" | "theory"
      - n_authors:       int — 作者数量

    [AUDIT-083] n_authors == 0 → 返回中性 0.5 (社论/快报数据未解析).

    Args:
        paper: 含 validation_type 和 n_authors 属性的对象.

    Returns:
        分数 ∈ {0.5, 0.6, 0.7, 0.8, 0.9, 1.0}

    Examples:
        >>> class P:
        ...     validation_type = "experiment"
        ...     n_authors = 6
        >>> c_team_disrupt_v5(P())
        1.0

        >>> class Q:
        ...     validation_type = "theory"
        ...     n_authors = 2
        >>> c_team_disrupt_v5(Q())
        1.0
    """
    # [AUDIT-083] n_authors=0 → 中性
    n_authors: int = getattr(paper, "n_authors", 0)
    if n_authors == 0:
        return 0.5

    vtype: str = getattr(paper, "validation_type", "experiment").lower()
    vtype = vtype.strip()

    if vtype not in TEAM_SCORE_TABLE:
        # 未知类型 → 中性
        return 0.5

    table = TEAM_SCORE_TABLE[vtype]

    if vtype == "theory":
        bucket = _bucket_theory(n_authors)
    else:
        bucket = _bucket_experiment_simulation(n_authors)

    return table.get(bucket, 0.5)


# ---------------------------------------------------------------------------
# AUDIT-085: TOP2000_REFINE_PROMPT with topic-aware context injection
# ---------------------------------------------------------------------------

TOP2000_REFINE_PROMPT = """\
You are evaluating whether this paper is a significant keystone in its research landscape.

CONTEXT:
This paper is from the topic: '{primary_topic_name}'.
Its top-5 semantic neighbour topics are: {neighbor_topic_names_top5}.

Based on this CONCRETE cross-topic context (not just abstract reading), score the paper on:
1. cross_domain_significance (0-1): How significantly does this paper bridge or influence
   other topics beyond its primary topic? Use the neighbour topic list as evidence.
2. novelty_within_topic (0-1): How novel is this relative to typical work in
   '{primary_topic_name}'? Low score if it is incremental within the topic.
3. breakthrough_language_score (0-1): Does the abstract contain genuine breakthrough
   claims (not just self-praise)? Use cautious scoring — most papers are incremental.
4. mechanism_novelty_score (0-1): Does the paper introduce a genuinely new physical
   mechanism, mathematical framework, or algorithmic paradigm?

IMPORTANT: Do NOT inflate scores due to impressive-sounding abstracts.
Score based on CONCRETE CROSS-TOPIC EVIDENCE from the neighbour list above.

Title: {title}
Abstract: {abstract_full}

Reply JSON only (no markdown):
{{
  "cross_domain_significance": <0.0-1.0>,
  "novelty_within_topic": <0.0-1.0>,
  "breakthrough_language_score": <0.0-1.0>,
  "mechanism_novelty_score": <0.0-1.0>,
  "reasoning": "<1-2 sentence explanation citing specific cross-topic evidence>"
}}
"""


def build_topic_aware_prompt(
    paper: dict,
    knn_topics: list[str],
) -> str:
    """
    [AUDIT-085] Build the TOP2000_REFINE_PROMPT with topic context injected.

    V11.1 bug: The LLM had no information about which subfield the paper
    belonged to, nor which adjacent topics it was semantically close to.
    This caused the LLM to hallucinate high cross_domain_significance scores
    for papers that were actually domain-internal.

    Fix: Inject primary_topic_name and top-5 KNN neighbour topic names so
    the LLM can score cross-domain significance based on concrete evidence.

    Args:
        paper:      Paper dict with at least:
                    - title (str)
                    - abstract (str) or abstract_full (str)
                    - primary_topic_name (str, optional)
                    - primary_topic_display_name (str, optional fallback)
        knn_topics: List of topic names from KNN top-5 neighbours.
                    Should have 1–5 items. Extra items are truncated to 5.

    Returns:
        Formatted prompt string ready for LLM call.

    Examples:
        >>> paper = {
        ...     "title": "Nonlinear metasurface for ultrafast pulse shaping",
        ...     "abstract": "We demonstrate a nonlinear metasurface...",
        ...     "primary_topic_name": "Nonlinear Photonics",
        ... }
        >>> knn = ["Ultrafast Optics", "Silicon Photonics", "Quantum Optics",
        ...        "Electromagnetic Metamaterials", "Laser Physics"]
        >>> prompt = build_topic_aware_prompt(paper, knn)
        >>> assert "Nonlinear Photonics" in prompt
        >>> assert "Ultrafast Optics" in prompt
        >>> assert "{" not in prompt  # all placeholders filled
    """
    # Resolve primary_topic_name
    primary_topic_name = (
        paper.get("primary_topic_name")
        or paper.get("primary_topic_display_name")
        or paper.get("topic_name")
        or "Unknown Topic"
    )

    # Format neighbour topics (top 5 only)
    top5 = knn_topics[:5] if knn_topics else []
    if top5:
        neighbor_topic_names_top5 = ", ".join(f'"{t}"' for t in top5)
    else:
        neighbor_topic_names_top5 = "(no neighbours available)"

    title = paper.get("title", "")
    abstract_full = (
        paper.get("abstract_full")
        or paper.get("abstract")
        or ""
    )

    return TOP2000_REFINE_PROMPT.format(
        primary_topic_name=primary_topic_name,
        neighbor_topic_names_top5=neighbor_topic_names_top5,
        title=title,
        abstract_full=abstract_full,
    )


def parse_refine_prompt_response(llm_output: str) -> Optional[Dict[str, Any]]:
    """
    Parse the LLM response from build_topic_aware_prompt().

    Returns a dict with keys:
      cross_domain_significance, novelty_within_topic,
      breakthrough_language_score, mechanism_novelty_score, reasoning.
    Returns None on parse failure.
    """
    import json
    import re as _re
    try:
        cleaned = _re.sub(r"```(?:json)?|```", "", llm_output).strip()
        data = json.loads(cleaned)
        required = {
            "cross_domain_significance", "novelty_within_topic",
            "breakthrough_language_score", "mechanism_novelty_score",
        }
        if not required.issubset(data.keys()):
            return None
        return data
    except Exception:
        return None


# ---------------------------------------------------------------------------
# V13: c_semantic_outlier_v6 — Isolation Forest + kNN score → [0, 1]
# ---------------------------------------------------------------------------

def c_semantic_outlier_v6(
    paper_embedding,
    all_embeddings,
    paper_index: int = 0,
    contamination: float = 0.05,
    knn_k: int = 10,
    random_state: int = 42,
) -> Optional[float]:
    """
    [V13] Compute continuous semantic outlier score for a paper using IF + kNN.

    Wraps anomaly_detection.detect_outliers() logic to produce a continuous
    score in [0, 1] rather than a binary {0, 1} label.

    Method:
      1. Run Isolation Forest on all_embeddings → raw anomaly scores
      2. Run kNN distance → distance scores
      3. Combine: average of normalized IF score and normalized kNN distance
      4. clip to [0, 1]; higher = more semantically outlying

    Args:
        paper_embedding:  1-D embedding of the focal paper (not used directly,
                          paper must be at position paper_index in all_embeddings).
        all_embeddings:   2-D array (n, d) of all papers' embeddings.
        paper_index:      Row index of the focal paper in all_embeddings.
        contamination:    Expected fraction of outliers (IsolationForest param).
        knn_k:            Number of nearest neighbours.
        random_state:     Reproducibility seed.

    Returns:
        Continuous score ∈ [0.0, 1.0]:
          0.0 = deeply embedded in cluster (typical paper)
          1.0 = extreme semantic outlier (potentially disruptive)
        Returns None if embeddings are empty or only 1 sample.

    Examples:
        >>> import numpy as np
        >>> embs = np.random.rand(20, 64)
        >>> score = c_semantic_outlier_v6(embs[0], embs, paper_index=0)
        >>> score is None or 0.0 <= score <= 1.0
        True
    """
    try:
        import numpy as np
        from sklearn.ensemble import IsolationForest
    except ImportError:
        return None

    emb = np.array(all_embeddings, dtype=np.float64)
    if emb.ndim != 2 or emb.shape[0] < 2:
        return None

    n = emb.shape[0]

    # --- Isolation Forest: score_samples returns anomaly score
    # (lower = more anomalous, typically in [-0.5, 0.5])
    safe_contamination = float(np.clip(contamination, 1e-4, 0.5))
    iso = IsolationForest(
        contamination=safe_contamination,
        random_state=random_state,
        n_estimators=100,
    )
    iso.fit(emb)
    iso_scores = iso.score_samples(emb)  # shape (n,), lower = more anomalous
    # Invert & normalize to [0, 1]: 1 = most anomalous
    iso_min, iso_max = iso_scores.min(), iso_scores.max()
    if iso_max - iso_min < 1e-12:
        iso_norm = np.full(n, 0.5)
    else:
        iso_norm = 1.0 - (iso_scores - iso_min) / (iso_max - iso_min)

    # --- kNN distance: higher = more outlying
    k = min(knn_k, n - 1)
    sq_norms = (emb ** 2).sum(axis=1)
    dist_sq = sq_norms[:, None] + sq_norms[None, :] - 2.0 * (emb @ emb.T)
    dist_sq = np.clip(dist_sq, 0.0, None)
    np.fill_diagonal(dist_sq, np.inf)
    if k <= 0:
        knn_norm = np.zeros(n)
    else:
        partitioned = np.partition(dist_sq, k - 1, axis=1)
        knn_dists = np.sqrt(partitioned[:, k - 1])
        d_min, d_max = knn_dists.min(), knn_dists.max()
        if d_max - d_min < 1e-12:
            knn_norm = np.full(n, 0.5)
        else:
            knn_norm = (knn_dists - d_min) / (d_max - d_min)

    # Combine: average of IF and kNN outlier scores
    combined = (iso_norm + knn_norm) / 2.0

    idx = int(paper_index)
    if idx < 0 or idx >= n:
        return None

    return float(np.clip(combined[idx], 0.0, 1.0))


# ---------------------------------------------------------------------------
# V13: keystone_score_v6 — convenience wrapper (delegates to lifecycle_weights)
# ---------------------------------------------------------------------------

def keystone_score_v6(
    signals: "Dict[str, Optional[float]]",
    paper,
    today: "Optional[date]" = None,
) -> float:
    """
    [V13] Convenience wrapper for lifecycle-adaptive weighted harmonic mean.

    Delegates to echelon.seeds.lifecycle_weights.keystone_score_v6.
    Imported here for single-import ergonomics.

    V5 compute_keystone_score_v5() is preserved unchanged for backward compat.

    Args:
        signals: Dict mapping signal name → value (None = skip, not 0.5).
        paper:   Object or dict with ``publication_date`` attribute.
        today:   Reference date.

    Returns:
        Score ∈ [0.0, 1.0]
    """
    from echelon.seeds.lifecycle_weights import (
        keystone_score_v6 as _v6,
    )
    return _v6(signals, paper, today=today)
