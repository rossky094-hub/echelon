"""
AUDIT-061 P1: SimulationRunnable 维度闸门

问题: 部分仿真工具 (如 SPINS-B) 仅支持 2D 仿真, 若系统尝试对其运行 3D
      仿真则静默失败或产生错误结果 (第 8 项闸门缺失).

修复:
  - TOOL_DIMENSION_SUPPORT: 工具 → 支持维度列表 映射表
  - check_simulation_dimension(target_dim, tool) → bool
  - auto_downgrade_3d_to_2d(simulation_spec) → 降级建议

设计说明:
  闸门位于 VRL (Validation Runnable Layer) 第 8 项:
    若 target_dim not in TOOL_DIMENSION_SUPPORT[tool] → 拒绝运行
    若 target_dim == "3D" 且 tool 仅支持 "2D" → 建议自动降级
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# 工具维度支持映射表
# ---------------------------------------------------------------------------

#: tool_name → 支持的维度列表
TOOL_DIMENSION_SUPPORT: dict[str, list[str]] = {
    # 仅 2D
    "SPINS-B":    ["2D"],
    "FDFD-2D":    ["2D"],

    # 2D + 3D
    "Meep":       ["2D", "3D"],
    "Lumerical":  ["2D", "3D"],
    "COMSOL":     ["2D", "3D"],
    "CST":        ["2D", "3D"],
    "FDTD-3D":    ["3D"],       # 仅 3D

    # 通用占位
    "Generic":    ["2D", "3D"],
}

_DEFAULT_TOOL = "Generic"


# ---------------------------------------------------------------------------
# 核心接口
# ---------------------------------------------------------------------------

def check_simulation_dimension(
    target_dim: str,
    tool: str,
) -> bool:
    """
    [AUDIT-061] 第 8 项闸门: 检查仿真工具是否支持目标维度.

    Args:
        target_dim: 目标维度 — "2D" 或 "3D".
        tool:       仿真工具名称 (查 TOOL_DIMENSION_SUPPORT).

    Returns:
        True = 支持 (可运行); False = 不支持 (拒绝).

    Examples:
        >>> check_simulation_dimension("2D", "SPINS-B")
        True
        >>> check_simulation_dimension("3D", "SPINS-B")
        False
        >>> check_simulation_dimension("3D", "Meep")
        True
    """
    supported = TOOL_DIMENSION_SUPPORT.get(tool, TOOL_DIMENSION_SUPPORT[_DEFAULT_TOOL])
    return target_dim in supported


@dataclass
class SimulationSpec:
    """仿真规格."""
    tool: str
    target_dim: str   # "2D" | "3D"
    domain_size: Optional[tuple] = None
    extra: dict = field(default_factory=dict)


@dataclass
class DowngradeResult:
    """降级建议结果."""
    original_spec: SimulationSpec
    downgraded: bool
    new_dim: str
    reason: str
    warnings: list[str] = field(default_factory=list)


def auto_downgrade_3d_to_2d(simulation_spec: SimulationSpec) -> DowngradeResult:
    """
    [AUDIT-061] 若工具不支持 3D, 自动建议降级到 2D.

    逻辑:
      1. tool 支持 3D → 不降级
      2. tool 仅支持 2D 且 target_dim == 3D → 降级到 2D + 警告
      3. target_dim 本已是 2D → 不变

    Args:
        simulation_spec: 原始仿真规格.

    Returns:
        DowngradeResult: 含降级决策和警告.

    Examples:
        >>> spec = SimulationSpec(tool="SPINS-B", target_dim="3D")
        >>> r = auto_downgrade_3d_to_2d(spec)
        >>> r.downgraded, r.new_dim
        (True, '2D')
    """
    tool = simulation_spec.tool
    original_dim = simulation_spec.target_dim

    # 工具未知 → 按 Generic 处理 (支持 2D + 3D, 不降级)
    supported = TOOL_DIMENSION_SUPPORT.get(tool, TOOL_DIMENSION_SUPPORT[_DEFAULT_TOOL])

    if original_dim == "3D" and "3D" not in supported and "2D" in supported:
        return DowngradeResult(
            original_spec=simulation_spec,
            downgraded=True,
            new_dim="2D",
            reason=(
                f"Tool '{tool}' does not support 3D simulation "
                f"(supported: {supported}). Auto-downgrading to 2D."
            ),
            warnings=[
                "3D→2D downgrade may reduce physical accuracy.",
                "Verify that 2D approximation is valid for this geometry.",
                f"Consider switching to a 3D-capable tool: Meep, Lumerical, COMSOL.",
            ],
        )

    # 不需要降级
    return DowngradeResult(
        original_spec=simulation_spec,
        downgraded=False,
        new_dim=original_dim,
        reason="No downgrade needed.",
    )


def gate_simulation(simulation_spec: SimulationSpec) -> dict:
    """
    [AUDIT-061] 完整第 8 项闸门: 检查 + 自动降级建议.

    Returns:
        dict with keys: allowed (bool), dimension (str), downgrade (DowngradeResult|None)
    """
    allowed = check_simulation_dimension(simulation_spec.target_dim, simulation_spec.tool)

    if allowed:
        return {
            "allowed": True,
            "dimension": simulation_spec.target_dim,
            "downgrade": None,
        }

    # 不允许 → 尝试降级
    downgrade = auto_downgrade_3d_to_2d(simulation_spec)

    if downgrade.downgraded:
        # 降级后允许
        return {
            "allowed": True,
            "dimension": downgrade.new_dim,
            "downgrade": downgrade,
        }

    # 完全不支持 (例如 FDTD-3D 接到 2D 请求)
    return {
        "allowed": False,
        "dimension": simulation_spec.target_dim,
        "downgrade": None,
        "error": (
            f"Tool '{simulation_spec.tool}' does not support "
            f"'{simulation_spec.target_dim}' and no fallback available."
        ),
    }
