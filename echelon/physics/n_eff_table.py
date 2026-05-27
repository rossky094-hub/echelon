"""
AUDIT-033: 真空光速硬编码修复 - 内置有效折射率表 N_EFF_TABLE

原问题: V11.1 在微纳光学计算中使用真空光速 c = 3e8 m/s 硬编码,
        忽略了介质中的有效折射率。在硅光子 (n_eff ≈ 3.476) 中,
        等效波长 = λ₀ / n_eff, 误差达 3.5 倍。

修复:
- 内置 N_EFF_TABLE: 7 种常用介质的有效折射率 (波长 1550nm 附近)
- 提供 effective_wavelength_nm(medium, wavelength_nm) 函数
- 支持多介质 key 别名 (si, silicon, Si 等)

参考数据:
- Silicon (Si): n_eff ≈ 3.476 @ 1550nm (来自 [Palik, Handbook of Optical Constants])
- SiN: n_eff ≈ 2.0 @ 1550nm (来自 [Luke et al., Opt. Lett. 2015])
- LiNbO3 (LN): n_eff ≈ 2.21 @ 1550nm (ordinary ray)
- SiO2 (glass/oxide): n_eff ≈ 1.444 @ 1550nm
- Air: n_eff ≈ 1.0003 @ 1550nm
- Vacuum: n_eff = 1.0 (精确)
- GaAs: n_eff ≈ 3.37 @ 1550nm
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple


# [AUDIT-033] 内置有效折射率表
# 格式: {medium_key: (n_eff @ 1550nm, description)}
# 覆盖微纳光学 7 种主要介质
N_EFF_TABLE: Dict[str, Tuple[float, str]] = {
    # Silicon (Si) - 硅光子学最重要介质
    "si":      (3.476, "Silicon @ 1550nm, bulk refractive index"),
    "silicon": (3.476, "Silicon @ 1550nm, bulk refractive index"),

    # Silicon Nitride (SiN) - 低损耗波导
    "sin":     (2.0,   "Silicon Nitride @ 1550nm"),
    "silicon_nitride": (2.0, "Silicon Nitride @ 1550nm"),

    # Lithium Niobate (LiNbO3) - 电光调制
    "ln":      (2.21,  "Lithium Niobate (LN) @ 1550nm, ordinary ray"),
    "linbo3":  (2.21,  "Lithium Niobate @ 1550nm, ordinary ray"),
    "liNbO3":  (2.21,  "Lithium Niobate @ 1550nm, ordinary ray"),

    # Glass / SiO2 - 光纤、包层
    "glass":   (1.444, "Fused Silica (SiO2) @ 1550nm"),
    "sio2":    (1.444, "Fused Silica (SiO2) @ 1550nm"),
    "fused_silica": (1.444, "Fused Silica (SiO2) @ 1550nm"),

    # GaAs - III-V 半导体激光
    "gaas":    (3.37,  "Gallium Arsenide (GaAs) @ 1550nm"),

    # Air
    "air":     (1.0003, "Air @ standard conditions"),

    # Vacuum (精确值)
    "vacuum":  (1.0,   "Vacuum (exact)"),
    "unknown": (1.0,   "Unknown medium, assume vacuum"),
}

# 归一化 key 映射 (大小写不敏感别名)
_ALIAS_MAP: Dict[str, str] = {
    "si": "si",
    "silicon": "si",
    "sin": "sin",
    "si3n4": "sin",
    "silicon_nitride": "sin",
    "siliconnitride": "sin",
    "ln": "ln",
    "linbo3": "ln",
    "lithiumniobate": "ln",
    "liNbO3": "ln",
    "glass": "glass",
    "sio2": "glass",
    "silica": "glass",
    "fused_silica": "glass",
    "fusedsilica": "glass",
    "gaas": "gaas",
    "galliumarsenide": "gaas",
    "air": "air",
    "vacuum": "vacuum",
    "unknown": "vacuum",
}


def _normalize_medium(medium: str) -> str:
    """归一化介质名称 (小写 + 去空格)"""
    key = medium.lower().replace(" ", "_").replace("-", "_")
    return _ALIAS_MAP.get(key, key)


def get_n_eff(medium: str, wavelength_nm: float = 1550.0) -> float:
    """
    [AUDIT-033] 获取介质的有效折射率

    Args:
        medium: 介质名称 (大小写不敏感, 支持 si/silicon/sin/ln/glass/gaas/air/vacuum)
        wavelength_nm: 波长 (nm), 当前版本使用 1550nm 数据

    Returns:
        n_eff: 有效折射率

    Examples:
        >>> get_n_eff("si", 1550)
        3.476
        >>> get_n_eff("vacuum")
        1.0
        >>> get_n_eff("Air")
        1.0003
    """
    key = _normalize_medium(medium)

    if key not in N_EFF_TABLE:
        # 未知介质: 发出警告并使用真空值
        import warnings
        warnings.warn(
            f"[AUDIT-033] 未知介质 '{medium}', 使用真空折射率 n_eff=1.0。"
            f"已知介质: {list(N_EFF_TABLE.keys())}",
            UserWarning,
            stacklevel=2,
        )
        return 1.0

    n_eff, _ = N_EFF_TABLE[key]
    return n_eff


def effective_wavelength_nm(medium: str, wavelength_nm: float) -> float:
    """
    [AUDIT-033] 计算介质中的等效波长

    公式: λ_eff = λ₀ / n_eff

    Args:
        medium: 介质名称 (如 "si", "sin", "vacuum" 等)
        wavelength_nm: 真空波长 (nm)

    Returns:
        等效波长 (nm)

    Examples:
        >>> effective_wavelength_nm("si", 1550)
        # 1550 / 3.476 ≈ 445.9 nm
        446.0  # 约 446 nm

        >>> effective_wavelength_nm("vacuum", 1550)
        1550.0  # 真空中等效波长 = 自身

    Notes:
        这是 AUDIT-033 的核心修复:
        微纳光学计算必须使用介质折射率, 而非真空光速。
        硅波导中 1550nm 光的等效波长约 446nm (非 1550nm)。
    """
    if wavelength_nm <= 0:
        raise ValueError(f"wavelength_nm 必须 > 0, 收到 {wavelength_nm}")

    n_eff = get_n_eff(medium, wavelength_nm)
    return wavelength_nm / n_eff


def effective_speed_m_per_s(medium: str, wavelength_nm: float = 1550.0) -> float:
    """
    [AUDIT-033] 计算介质中的光速

    公式: v = c₀ / n_eff

    Args:
        medium: 介质名称
        wavelength_nm: 波长 (nm), 用于查表

    Returns:
        介质中的光速 (m/s)
    """
    C0 = 2.998e8  # 真空光速 (m/s)
    n_eff = get_n_eff(medium, wavelength_nm)
    return C0 / n_eff
