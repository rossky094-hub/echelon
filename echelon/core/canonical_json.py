"""
echelon.core.canonical_json
==============================
Canonical JSON 序列化(幂等、确定性)。

[修订自 AUDIT-055]
V11.1 问题:直接调用 ``json.dumps`` 序列化浮点数时,Python 使用 IEEE 754
full precision repr(如 ``0.10000000000000001``),导致同一逻辑值的不同
浮点表示生成不同的哈希 → 幂等键雪崩(相同语义内容被认为不同)。

V11.2 修复:
  - 所有浮点数强制格式化为 ``.6g``(6 位有效数字),消除 IEEE 754 精度噪音
  - ``Decimal`` 类型先转 float 再 .6g 格式化(与浮点保持一致精度)
  - ``sort_keys=True`` 保证 dict key 顺序确定性
  - 分隔符无空格(``(",", ":")``),保证字节级一致
  - 递归处理嵌套结构(list/dict/set)

参考:
  - Python 浮点精度: https://docs.python.org/3/tutorial/floatingpoint.html
  - JSON Canonicalization: RFC 8785
  - AUDIT-055 V11.2 修订要点
"""

from __future__ import annotations

import json
import math
from decimal import Decimal
from typing import Any


# ---------------------------------------------------------------------------
# 核心:规范化浮点值
# ---------------------------------------------------------------------------


def _canonical_float(v: float) -> Any:
    """将浮点数规范化为 .6g 格式。

    [修订自 AUDIT-055]

    - NaN / Inf 不合法于 JSON,转为 None
    - 使用 ``%.6g`` 格式后解析回 float,消除精度尾巴
    """
    if math.isnan(v) or math.isinf(v):
        return None  # JSON 不支持 NaN/Inf
    # %.6g: 6 位有效数字,去除尾零
    return float(f"{v:.6g}")


def _normalize(obj: Any) -> Any:
    """递归规范化对象,用于 canonical_dumps。

    [修订自 AUDIT-055]

    支持类型:
    - float      → .6g 格式化后的 float
    - Decimal    → float → .6g 格式化后的 float
    - int        → 原样(JSON 整数无精度问题)
    - str        → 原样
    - bool       → 原样
    - None       → null
    - dict       → key/value 均递归规范化
    - list/tuple → 元素递归规范化
    - set        → 先排序(str 化 key),元素递归规范化
    """
    if isinstance(obj, bool):
        # bool 必须在 int 之前判断(bool 是 int 子类)
        return obj
    if isinstance(obj, float):
        return _canonical_float(obj)
    if isinstance(obj, Decimal):
        return _canonical_float(float(obj))
    if isinstance(obj, int):
        return obj
    if isinstance(obj, str):
        return obj
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {str(k): _normalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize(item) for item in obj]
    if isinstance(obj, set):
        # set 无序 → 先排序(用 str 化后排序保证确定性)
        return [_normalize(item) for item in sorted(obj, key=str)]
    # 其他类型(如自定义对象):尝试转 str
    return str(obj)


# ---------------------------------------------------------------------------
# 主接口
# ---------------------------------------------------------------------------


def canonical_dumps(data: Any) -> str:
    """生成确定性 canonical JSON 字符串。

    [修订自 AUDIT-055]

    特性:
    - 浮点强制 ``.6g`` 截断,消除 IEEE 754 哈希雪崩
    - Decimal 支持(转 float 后 .6g)
    - ``sort_keys=True`` — dict key 按字母序排列
    - 无空格分隔符 ``(",", ":")``
    - 递归处理嵌套 dict/list/set

    Parameters
    ----------
    data:
        任意 Python 对象(dict/list/float/int/str/Decimal/...)。

    Returns
    -------
    str
        规范化 JSON 字符串。

    Examples
    --------
    ::

        # 浮点雪崩消除
        a = canonical_dumps({"x": 0.1 + 0.2})      # {"x":0.3}
        b = canonical_dumps({"x": 0.30000000000000004})  # {"x":0.3}
        assert a == b

        # sort_keys
        c = canonical_dumps({"b": 1, "a": 2})  # '{"a":2,"b":1}'

        # Decimal 支持
        from decimal import Decimal
        d = canonical_dumps({"v": Decimal("1.234567890")})  # '{"v":1.23457}'
    """
    normalized = _normalize(data)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def canonical_hash(data: Any, algorithm: str = "sha256") -> str:
    """计算数据的 canonical JSON 哈希。

    [修订自 AUDIT-055]

    参数同 ``canonical_dumps``;算法支持 ``"sha256"``、``"md5"``、``"sha1"``。

    Returns
    -------
    str
        十六进制哈希字符串。
    """
    import hashlib

    canonical = canonical_dumps(data)
    h = hashlib.new(algorithm)
    h.update(canonical.encode("utf-8"))
    return h.hexdigest()
