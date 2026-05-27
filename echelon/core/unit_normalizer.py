"""
echelon.core.unit_normalizer
=============================
物理量单位归一化模块,基于 Pint 库。

[修订自 AUDIT-064] 原实现未处理 Unicode 上标字符(如 dB·cm⁻¹),导致
单位解析失败,且无 LLM fallback 机制。本模块:
1. 预处理 Unicode 上标/点号 → ASCII 兼容格式
2. 使用 Pint 解析与换算
3. 无法识别时调用 LLM fallback stub(Pilot 阶段记录日志)

参考: V11.2 白皮书 §2.5 物理量归一化;AUDIT-064
"""

from __future__ import annotations

import logging
import re
from typing import Any

import pint

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pint UnitRegistry(全局单例,避免多次构建)
# ---------------------------------------------------------------------------

_ureg = pint.UnitRegistry()
_ureg.define("decibel = [] = dB")
# 光学常用非 SI 单位
_ureg.define("neper = [] = Np")

# ---------------------------------------------------------------------------
# Unicode 预处理映射
# ---------------------------------------------------------------------------

# 上标数字 → ASCII
_SUPERSCRIPT_MAP = str.maketrans(
    "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻",
    "0123456789+-",
)

# Unicode 点乘号、中文·等 → 空格(Pint 接受空格作乘法)
_DOT_PATTERN = re.compile(r"[·•⋅×✕]")

# 负号变体 → ASCII minus
_MINUS_PATTERN = re.compile(r"[−–—]")

# 带指数的常见写法:cm⁻¹ → cm**-1,m⁻² → m**-2
_SUPERSCRIPT_EXP_PATTERN = re.compile(r"([a-zA-Z]+)([⁻⁺]?)([⁰¹²³⁴⁵⁶⁷⁸⁹]+)")


def _normalize_unicode(unit_str: str) -> str:
    """将 Unicode 特殊字符预处理为 ASCII/Pint 可解析格式。

    处理内容:
    - 上标指数(``cm⁻¹`` → ``cm**-1``)
    - Unicode 点乘号(``·`` → 空格)
    - Unicode 负号变体

    Parameters
    ----------
    unit_str:
        原始单位字符串。

    Returns
    -------
    str
        预处理后的 ASCII 兼容单位字符串。

    Examples
    --------
    >>> _normalize_unicode("dB·cm⁻¹")
    'dB cm**-1'
    >>> _normalize_unicode("dB cm-1")
    'dB cm-1'
    """
    s = unit_str.strip()

    # Step 1: 处理形如 "cm⁻¹" 的上标指数写法
    def _replace_superscript_exp(m: re.Match) -> str:
        base = m.group(1)
        sign_char = m.group(2)
        digits = m.group(3).translate(_SUPERSCRIPT_MAP)
        sign = "-" if sign_char == "⁻" else ("+" if sign_char == "⁺" else "")
        return f"{base}**{sign}{digits}"

    s = _SUPERSCRIPT_EXP_PATTERN.sub(_replace_superscript_exp, s)

    # Step 2: 将剩余上标数字转为 ASCII
    s = s.translate(_SUPERSCRIPT_MAP)

    # Step 3: Unicode 点乘 → 空格(Pint 用空格表示乘法)
    s = _DOT_PATTERN.sub(" ", s)

    # Step 4: Unicode 减号变体 → ASCII -
    s = _MINUS_PATTERN.sub("-", s)

    return s


# ---------------------------------------------------------------------------
# 单位变体别名
# ---------------------------------------------------------------------------

# 常见 dB/cm 变体列表(用于测试断言)
DB_PER_CM_VARIANTS: list[str] = [
    "dB/cm",
    "dB cm-1",
    "dB·cm⁻¹",
    "dB cm⁻¹",
    "dB*cm**-1",
]


def parse_unit(unit_str: str) -> pint.Unit:
    """解析单位字符串,返回 Pint Unit 对象。

    先经 Unicode 预处理,再交由 Pint 解析。若 Pint 无法解析,调用
    ``llm_unit_fallback()`` stub。

    Parameters
    ----------
    unit_str:
        原始单位字符串(可含 Unicode)。

    Returns
    -------
    pint.Unit
        对应的 Pint 单位。

    Raises
    ------
    pint.errors.UndefinedUnitError
        若 Pint 解析失败且 LLM fallback 也无法处理。
    """
    normalized = _normalize_unicode(unit_str)
    try:
        return _ureg.parse_units(normalized)
    except pint.errors.UndefinedUnitError:
        logger.warning(
            "Pint cannot parse unit %r (normalized: %r), trying LLM fallback",
            unit_str,
            normalized,
        )
        return llm_unit_fallback(unit_str)


def normalize_quantity(
    value: float,
    unit_str: str,
    target_unit_str: str,
) -> float:
    """将物理量换算到目标单位。

    Parameters
    ----------
    value:
        数值。
    unit_str:
        原始单位字符串。
    target_unit_str:
        目标单位字符串。

    Returns
    -------
    float
        换算后的数值。

    Raises
    ------
    pint.DimensionalityError
        若原始单位与目标单位量纲不兼容。

    Examples
    --------
    >>> normalize_quantity(1000, "m", "km")
    1.0
    """
    src_unit = parse_unit(unit_str)
    tgt_unit = parse_unit(target_unit_str)
    qty = _ureg.Quantity(value, src_unit)
    return qty.to(tgt_unit).magnitude


def is_parseable(unit_str: str) -> bool:
    """检查单位字符串是否可被 Pint 解析(不含 LLM fallback)。

    Parameters
    ----------
    unit_str:
        原始单位字符串。

    Returns
    -------
    bool
        若 Pint 可解析返回 True,否则 False。
    """
    normalized = _normalize_unicode(unit_str)
    try:
        _ureg.parse_units(normalized)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# LLM Fallback Stub
# ---------------------------------------------------------------------------


def llm_unit_fallback(unit_str: str) -> pint.Unit:
    """LLM 辅助单位解析(Pilot stub,生产实现需接入 LLM API)。

    当 Pint 无法解析时调用。Pilot 阶段仅记录日志并返回无量纲单位,
    生产环境应替换为真实 LLM 调用(如 GPT-4 function calling)。

    Parameters
    ----------
    unit_str:
        Pint 无法解析的单位字符串。

    Returns
    -------
    pint.Unit
        解析结果;Pilot 返回 ``dimensionless``。

    Notes
    -----
    TODO(production): 替换为真实 LLM API 调用,将单位字符串送入
    ``convert_unit_string(unit_str)`` 工具函数,获取标准 SI 单位名称。
    """
    logger.error(
        "LLM unit fallback (stub) called for %r — returning dimensionless. "
        "Replace with real LLM call in production.",
        unit_str,
    )
    return _ureg.dimensionless
