"""
AUDIT-036: alpha/power 强加 FDTD 仿真修复 - 按 validation_type 分支

原问题: V11.1 对所有论文 (包括仿真) 要求 alpha/power/MDE,
        这些统计指标仅适用于随机对照实验, 对 FDTD 仿真没有意义 (伪科学)

修复:
- 按 validation_type ∈ {experiment, simulation, theory} 分支处理
- 实验 (experiment): alpha/power/MDE
- 仿真 (simulation): convergence_criteria (网格收敛、步长收敛)
- 理论 (theory): 适用范围 (validity_domain)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List


class ValidationType(str, Enum):
    """[AUDIT-036] 验证类型分类"""
    EXPERIMENT = "experiment"   # 实验验证 (物理实验、测量)
    SIMULATION = "simulation"   # 仿真验证 (FDTD、FEM、MEEP 等)
    THEORY = "theory"           # 理论推导


# [AUDIT-036] 各验证类型的必要性指标
VALIDATION_REQUIREMENTS = {
    ValidationType.EXPERIMENT: {
        "required": ["alpha", "statistical_power", "sample_size"],
        "optional": ["mde", "confidence_interval", "p_value", "effect_size"],
        "description": "随机对照实验: 需要 α/power/样本量等统计功效指标",
    },
    ValidationType.SIMULATION: {
        "required": ["convergence_criterion"],
        "optional": ["mesh_refinement", "time_step", "pml_condition", "grid_points", "fdtd_tool"],
        "description": "数值仿真 (FDTD/FEM): 需要收敛准则, 不需要 alpha/power",
    },
    ValidationType.THEORY: {
        "required": ["validity_domain"],
        "optional": ["assumptions", "perturbation_order", "approximation_level", "regime"],
        "description": "理论推导: 需要适用范围描述",
    },
}


@dataclass
class ExperimentValidation:
    """[AUDIT-036] 实验验证指标 (随机对照实验)"""
    alpha: float                    # 显著性水平 (通常 0.05)
    statistical_power: float        # 统计功效 (通常 0.80)
    sample_size: int                # 样本量
    mde: Optional[float] = None     # 最小可检测效果 (MDE)
    confidence_interval: Optional[str] = None   # 置信区间描述
    p_value: Optional[float] = None
    effect_size: Optional[float] = None


@dataclass
class SimulationValidation:
    """[AUDIT-036] 仿真验证指标 (FDTD/FEM/MEEP)"""
    convergence_criterion: str      # 收敛准则描述 (如 "能量衰减到 -60dB")
    mesh_refinement: Optional[str] = None   # 网格细化方案
    time_step: Optional[float] = None       # 时间步长 (Courant 条件)
    pml_condition: Optional[str] = None     # PML 边界条件
    grid_points: Optional[int] = None       # 网格点数
    fdtd_tool: Optional[str] = None         # 仿真工具 (meep/lumerical/tidy3d)


@dataclass
class TheoryValidation:
    """[AUDIT-036] 理论验证指标"""
    validity_domain: str            # 适用范围 (如 "弱耦合极限, k·d << 1")
    assumptions: Optional[List[str]] = field(default_factory=list)
    perturbation_order: Optional[int] = None    # 微扰展开阶数
    approximation_level: Optional[str] = None  # 近似层级
    regime: Optional[str] = None               # 物理区间 (如 "近场/远场")


@dataclass
class FalsifiabilityResult:
    """
    [AUDIT-036] 可证伪性评估结果 (按 validation_type 分支)

    核心修复: 不再对仿真论文强加实验统计指标。
    """
    validation_type: ValidationType
    is_falsifiable: bool
    score: float                                    # 可证伪性得分 [0, 1]
    missing_requirements: List[str] = field(default_factory=list)
    notes: str = ""

    # 分支结果 (三选一, 按 validation_type)
    experiment: Optional[ExperimentValidation] = None
    simulation: Optional[SimulationValidation] = None
    theory: Optional[TheoryValidation] = None


def assess_falsifiability(
    claim: Dict[str, Any],
    validation_type: Optional[str] = None,
) -> FalsifiabilityResult:
    """
    [AUDIT-036] 按 validation_type 分支评估可证伪性

    修复核心: 不再对所有论文要求 alpha/power/MDE。
    仿真论文用收敛准则, 实验论文才用统计功效指标。

    Args:
        claim: 论文声明 dict, 含 validation_type 和相关字段
        validation_type: 验证类型 ('experiment'/'simulation'/'theory')
                         None 时从 claim 中推断

    Returns:
        FalsifiabilityResult with branch-specific validation

    Examples:
        # 仿真论文: 不需要 alpha/power
        claim = {
            "validation_type": "simulation",
            "convergence_criterion": "energy decays to -60dB",
            "fdtd_tool": "meep",
        }
        result = assess_falsifiability(claim)
        assert "alpha" not in result.missing_requirements
        assert result.simulation is not None
    """
    # 推断 validation_type
    vtype_str = validation_type or claim.get("validation_type", "")
    try:
        vtype = ValidationType(vtype_str.lower())
    except (ValueError, AttributeError):
        # 自动推断
        vtype = _infer_validation_type(claim)

    # 按分支处理
    if vtype == ValidationType.EXPERIMENT:
        return _assess_experiment(claim, vtype)
    elif vtype == ValidationType.SIMULATION:
        return _assess_simulation(claim, vtype)
    elif vtype == ValidationType.THEORY:
        return _assess_theory(claim, vtype)
    else:
        return FalsifiabilityResult(
            validation_type=ValidationType.EXPERIMENT,
            is_falsifiable=False,
            score=0.0,
            missing_requirements=["unknown_validation_type"],
            notes=f"无法识别 validation_type: {vtype_str}",
        )


def _infer_validation_type(claim: Dict[str, Any]) -> ValidationType:
    """从 claim 内容自动推断验证类型"""
    text = str(claim).lower()
    sim_keywords = ["fdtd", "meep", "lumerical", "tidy3d", "simulation", "simulated", "numerically", "fem"]
    exp_keywords = ["measured", "fabricated", "experiment", "sample", "device"]
    theory_keywords = ["analytical", "theoretically", "derivation", "perturbation"]

    sim_score = sum(1 for kw in sim_keywords if kw in text)
    exp_score = sum(1 for kw in exp_keywords if kw in text)
    thy_score = sum(1 for kw in theory_keywords if kw in text)

    if sim_score >= exp_score and sim_score >= thy_score and sim_score > 0:
        return ValidationType.SIMULATION
    if exp_score >= thy_score and exp_score > 0:
        return ValidationType.EXPERIMENT
    if thy_score > 0:
        return ValidationType.THEORY
    return ValidationType.EXPERIMENT  # 默认实验


def _assess_experiment(claim: Dict[str, Any], vtype: ValidationType) -> FalsifiabilityResult:
    """[AUDIT-036] 实验分支: 检查 alpha/power/sample_size"""
    missing = []

    alpha = claim.get("alpha")
    power = claim.get("statistical_power")
    n = claim.get("sample_size")

    if alpha is None:
        missing.append("alpha")
    if power is None:
        missing.append("statistical_power")
    if n is None:
        missing.append("sample_size")

    exp_val = ExperimentValidation(
        alpha=float(alpha) if alpha is not None else 0.05,
        statistical_power=float(power) if power is not None else 0.80,
        sample_size=int(n) if n is not None else 0,
        mde=claim.get("mde"),
        confidence_interval=claim.get("confidence_interval"),
        p_value=claim.get("p_value"),
        effect_size=claim.get("effect_size"),
    )

    score = 1.0 - (len(missing) / 3.0)

    return FalsifiabilityResult(
        validation_type=vtype,
        is_falsifiable=(len(missing) == 0),
        score=max(0.0, score),
        missing_requirements=missing,
        experiment=exp_val,
        notes="实验验证: 需要 α/统计功效/样本量",
    )


def _assess_simulation(claim: Dict[str, Any], vtype: ValidationType) -> FalsifiabilityResult:
    """[AUDIT-036] 仿真分支: 检查 convergence_criteria (不需要 alpha/power)"""
    missing = []

    convergence = claim.get("convergence_criterion") or claim.get("convergence_criteria")

    if not convergence:
        missing.append("convergence_criterion")

    sim_val = SimulationValidation(
        convergence_criterion=str(convergence) if convergence else "NOT_PROVIDED",
        mesh_refinement=claim.get("mesh_refinement"),
        time_step=claim.get("time_step"),
        pml_condition=claim.get("pml_condition"),
        grid_points=claim.get("grid_points"),
        fdtd_tool=claim.get("fdtd_tool"),
    )

    score = 1.0 if not missing else 0.5

    return FalsifiabilityResult(
        validation_type=vtype,
        is_falsifiable=(len(missing) == 0),
        score=score,
        missing_requirements=missing,
        simulation=sim_val,
        notes="仿真验证: 需要收敛准则 (不需要 alpha/power/MDE)",
    )


def _assess_theory(claim: Dict[str, Any], vtype: ValidationType) -> FalsifiabilityResult:
    """[AUDIT-036] 理论分支: 检查适用范围"""
    missing = []

    validity_domain = claim.get("validity_domain")

    if not validity_domain:
        missing.append("validity_domain")

    theory_val = TheoryValidation(
        validity_domain=str(validity_domain) if validity_domain else "NOT_PROVIDED",
        assumptions=claim.get("assumptions", []),
        perturbation_order=claim.get("perturbation_order"),
        approximation_level=claim.get("approximation_level"),
        regime=claim.get("regime"),
    )

    score = 1.0 if not missing else 0.4

    return FalsifiabilityResult(
        validation_type=vtype,
        is_falsifiable=(len(missing) == 0),
        score=score,
        missing_requirements=missing,
        theory=theory_val,
        notes="理论验证: 需要适用范围 (validity_domain)",
    )
