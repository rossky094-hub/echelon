"""
AUDIT-062: VRL 无人区修复

原问题: V11.1 要求 has_counterevidence=True 才能出 VRL0+
        极其超前的颠覆性论文 (无人区) 没有反证文献 → 被系统判定 VRL0 枪毙
        越前无古人, 越被系统惩罚

修复:
- 移除 has_counterevidence 必填约束
- 改为软信号: 有反证 → counter_bonus=0.5 (加分)
- 无反证 + 跨 ≥2 子领域 (真无人区标志) → counter_bonus=0.3 (可入 VRL1+)
- 无反证 + 单子领域 → counter_bonus=0.0 (不加分但也不枪毙)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# VRL 等级定义
VRL_LEVELS = ["VRL0", "VRL1", "VRL2", "VRL3", "VRL4"]

# [AUDIT-062] counter_bonus 配置
COUNTER_BONUS_WITH_EVIDENCE = 0.5       # 有反证: +0.5 (反映方向"不天真")
COUNTER_BONUS_UNMANNED_ZONE = 0.3       # 无人区: +0.3 (跨 ≥2 子领域, 无反证)
COUNTER_BONUS_NONE = 0.0                # 无反证 + 单领域: +0.0


@dataclass
class VRLInput:
    """
    [AUDIT-062] VRL 评估输入

    重要修改: has_counterevidence 不再是必填约束,
              而是可选软信号 (None 表示未知)
    """
    # 基础要求
    has_evidence_chain: bool            # 是否有证据链 (必须)
    geometry_complete: bool             # 几何参数是否完整
    materials_complete: bool            # 材料参数是否完整

    # [AUDIT-062] 软信号 (不再是硬门)
    has_counterevidence: Optional[bool] = None  # 是否有反证文献 (Optional!)

    # 无人区检测
    cross_subfield_origin: bool = False         # 是否跨子领域起源
    member_subfields: List[str] = field(default_factory=list)  # 所属子领域列表

    # 附加信号
    has_simulation_plan: bool = False           # 是否有仿真计划
    has_fabrication_plan: bool = False          # 是否有制造计划
    validation_score: float = 0.0              # 来自 falsifiability 的验证得分 [0, 1]

    # 元数据
    paper_id: Optional[str] = None
    topic_id: Optional[str] = None


@dataclass
class VRLResult:
    """VRL 评估结果"""
    vrl_level: str                              # VRL0 ~ VRL4
    vrl_numeric: int                            # 0 ~ 4
    counter_bonus: float                        # 反证/无人区奖励
    is_unmanned_zone: bool                      # 是否判定为真无人区
    reason: str                                 # 判定理由
    details: dict = field(default_factory=dict)


def _detect_unmanned_zone(inp: VRLInput) -> tuple[bool, float, str]:
    """
    [AUDIT-062] 检测是否为真无人区

    真无人区条件:
    - cross_subfield_origin = True (跨子领域起源)
    - len(member_subfields) >= 2 (跨 ≥2 子领域)
    - has_counterevidence is None or False (无反证文献)

    Returns:
        (is_unmanned_zone, counter_bonus, reason)
    """
    if inp.has_counterevidence:
        return False, COUNTER_BONUS_WITH_EVIDENCE, "有反证文献 (+0.5 bonus)"

    # has_counterevidence is None or False
    if inp.cross_subfield_origin and len(inp.member_subfields) >= 2:
        # 真无人区: 跨域 + 无反证 (因为没人做过)
        return True, COUNTER_BONUS_UNMANNED_ZONE, (
            f"无人区判定: 跨 {len(inp.member_subfields)} 子领域 "
            f"({', '.join(inp.member_subfields[:3])}) + 无反证 "
            f"(因为没人涉足过此领域, +0.3 bonus)"
        )

    return False, COUNTER_BONUS_NONE, "无反证 + 单子领域 (counter_bonus=0.0)"


def assign_vrl(inp: VRLInput) -> VRLResult:
    """
    [AUDIT-062] VRL 评估: 移除 has_counterevidence 必填

    V11.1 设计 (已废弃):
        if not (a.has_evidence_chain and a.has_counterevidence):
            return "VRL0"    ← 无反证就枪毙

    V11.2 修订:
        - has_counterevidence 改为软信号
        - 无反证 + 跨域 → 无人区 → counter_bonus=0.3 → 可入 VRL1+
        - 无反证 + 单域 → counter_bonus=0.0 → 按其他指标正常评估

    完整逻辑:
        VRL0: 无证据链 (硬门)
        VRL1: 有证据链, 但 geometry/materials 不完整
        VRL2: geometry + materials 完整 (+ counter_bonus)
        VRL3: VRL2 + simulation_plan (+ counter_bonus)
        VRL4: VRL3 + fabrication_plan + high validation_score

    Args:
        inp: VRLInput

    Returns:
        VRLResult with vrl_level, counter_bonus, is_unmanned_zone
    """
    # ===== 硬门: 证据链 =====
    if not inp.has_evidence_chain:
        return VRLResult(
            vrl_level="VRL0",
            vrl_numeric=0,
            counter_bonus=0.0,
            is_unmanned_zone=False,
            reason="无证据链 (has_evidence_chain=False)",
        )

    # ===== [AUDIT-062] 软信号: 反证/无人区检测 =====
    is_unmanned_zone, counter_bonus, counter_reason = _detect_unmanned_zone(inp)

    # ===== 几何 + 材料完整性检查 =====
    if not (inp.geometry_complete and inp.materials_complete):
        # VRL1: 基础验证阶段 (但无人区也给 VRL1)
        vrl = "VRL1"
        reason = (
            f"几何或材料参数不完整 → VRL1。{counter_reason}"
        )
        return VRLResult(
            vrl_level=vrl,
            vrl_numeric=1,
            counter_bonus=counter_bonus,
            is_unmanned_zone=is_unmanned_zone,
            reason=reason,
            details={
                "geometry_complete": inp.geometry_complete,
                "materials_complete": inp.materials_complete,
            },
        )

    # ===== VRL2+: geometry + materials 完整 =====
    base_score = 2.0 + counter_bonus

    if inp.has_simulation_plan:
        base_score += 1.0

    if inp.has_fabrication_plan and inp.validation_score >= 0.6:
        base_score += 1.0

    vrl_numeric = min(4, int(base_score))
    vrl_level = f"VRL{vrl_numeric}"

    reason = (
        f"geometry+materials 完整。{counter_reason}. "
        f"base_score={base_score:.2f} → {vrl_level}"
    )

    return VRLResult(
        vrl_level=vrl_level,
        vrl_numeric=vrl_numeric,
        counter_bonus=counter_bonus,
        is_unmanned_zone=is_unmanned_zone,
        reason=reason,
        details={
            "has_evidence_chain": inp.has_evidence_chain,
            "has_counterevidence": inp.has_counterevidence,
            "cross_subfield_origin": inp.cross_subfield_origin,
            "member_subfields": inp.member_subfields,
            "geometry_complete": inp.geometry_complete,
            "materials_complete": inp.materials_complete,
            "has_simulation_plan": inp.has_simulation_plan,
            "has_fabrication_plan": inp.has_fabrication_plan,
            "validation_score": inp.validation_score,
            "counter_bonus": counter_bonus,
        },
    )
