"""
echelon.core.date_utils
========================
日期类型安全工具模块。

[修订自 AUDIT-074] 原实现将 publication_date 存储为 str,与 date 对象混用,
导致比较/排序时抛出 ``TypeError: '<' not supported between instances of
'str' and 'datetime.date'``。本模块提供统一的 parse/coerce 函数,确保
ingestion 层所有日期操作使用 ``datetime.date`` 类型。

参考: V11.2 白皮书 §2.4 日期字段规范;AUDIT-074
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Union


# ---------------------------------------------------------------------------
# 支持的日期格式(按优先级)
# ---------------------------------------------------------------------------

_DATE_FORMATS = [
    "%Y-%m-%d",   # ISO-8601 日期:2024-01-15
    "%Y/%m/%d",   # 斜线分隔:2024/01/15
    "%d-%m-%Y",   # 欧式:15-01-2024
    "%Y-%m",      # 年月:2024-01(视为当月 1 日)
    "%Y",         # 仅年份:2024(视为 1 月 1 日)
]

# 仅年月格式,需特殊处理 day=1
_YEAR_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_YEAR_ONLY_RE = re.compile(r"^\d{4}$")


def parse_pub_date(v: Union[str, date, datetime, None]) -> date:
    """将各种格式的发表日期解析为 ``datetime.date`` 对象。

    统一 ingestion 层的日期处理,消除 str 与 date 混用导致的 TypeError。

    Parameters
    ----------
    v:
        输入日期值,支持:
        - ``datetime.date``:直接返回
        - ``datetime.datetime``:返回 ``.date()``
        - ``str``:尝试多种格式解析(见 ``_DATE_FORMATS``)
        - ``None``:返回 ``date(1970, 1, 1)``(占位符,并记录警告)

    Returns
    -------
    datetime.date
        解析后的日期对象。

    Raises
    ------
    ValueError
        若字符串格式无法识别。
    TypeError
        若输入类型不受支持。

    Examples
    --------
    >>> parse_pub_date("2024-03-15")
    datetime.date(2024, 3, 15)
    >>> parse_pub_date("2024-03")
    datetime.date(2024, 3, 1)
    >>> parse_pub_date("2024")
    datetime.date(2024, 1, 1)
    >>> from datetime import date
    >>> parse_pub_date(date(2024, 3, 15))
    datetime.date(2024, 3, 15)
    """
    if v is None:
        import warnings
        warnings.warn(
            "parse_pub_date received None; defaulting to 1970-01-01. "
            "Check upstream data quality.",
            stacklevel=2,
        )
        return date(1970, 1, 1)

    if isinstance(v, datetime):
        return v.date()

    if isinstance(v, date):
        return v

    if isinstance(v, str):
        s = v.strip()

        # 仅年月(2024-03)→ 当月 1 日
        if _YEAR_MONTH_RE.match(s):
            return datetime.strptime(s + "-01", "%Y-%m-%d").date()

        # 仅年份(2024)→ 1 月 1 日
        if _YEAR_ONLY_RE.match(s):
            return date(int(s), 1, 1)

        # 逐格式尝试
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue

        raise ValueError(
            f"Cannot parse publication date {s!r}. "
            f"Supported formats: {_DATE_FORMATS}"
        )

    raise TypeError(
        f"parse_pub_date expects str, date, datetime, or None; "
        f"got {type(v).__name__!r}"
    )


def coerce_pub_date(v: Union[str, date, datetime, None]) -> date | None:
    """宽松版本:解析失败时返回 None 而非抛出异常。

    Parameters
    ----------
    v:
        输入日期值。

    Returns
    -------
    datetime.date or None
        解析成功返回 date 对象,失败返回 None。
    """
    try:
        return parse_pub_date(v)
    except (ValueError, TypeError):
        return None


def date_to_iso(d: date) -> str:
    """将 ``datetime.date`` 转为 ISO-8601 字符串。

    Parameters
    ----------
    d:
        日期对象。

    Returns
    -------
    str
        如 ``"2024-03-15"``。
    """
    return d.isoformat()


def is_in_range(d: date, since: date, until: date) -> bool:
    """检查日期是否在 [since, until] 范围内(含边界)。

    Parameters
    ----------
    d:
        待检查日期。
    since:
        起始日期(含)。
    until:
        截止日期(含)。

    Returns
    -------
    bool
    """
    return since <= d <= until
