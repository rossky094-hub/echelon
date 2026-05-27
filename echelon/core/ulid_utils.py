"""
echelon.core.ulid_utils
=======================
ULID 主键工具模块。

[修订自 AUDIT-026] 原实现使用 UUID v4,导致主键无序、索引性能差。
本模块使用 ULID(Universally Unique Lexicographically Sortable Identifier)
替代 UUID,保证插入单调性与可读性。

参考: V11.2 白皮书 §2.3 主键策略
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema
from ulid import ULID


def ulid_new() -> str:
    """生成一个新的 ULID 字符串(26 字符,Crockford base32 编码)。

    Returns
    -------
    str
        当前时间戳对应的 ULID 字符串,如 ``01ARYZ6S41TPTWF1BGZM0PVHB0``。

    Examples
    --------
    >>> uid = ulid_new()
    >>> len(uid)
    26
    >>> uid.isupper() or uid.isalnum()
    True
    """
    return str(ULID())


class _ULIDStrPydanticAnnotation:
    """Pydantic v2 兼容的 ULID 字符串注解,用于 CoreSchema 注册。"""

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        """返回验证 ULID 字符串的 CoreSchema。"""
        return core_schema.no_info_plain_validator_function(
            cls._validate,
            serialization=core_schema.to_string_ser_schema(),
        )

    @classmethod
    def _validate(cls, value: Any) -> str:
        """验证并规范化 ULID 字符串。

        Parameters
        ----------
        value:
            待验证值,可为 str 或 ULID 实例。

        Raises
        ------
        ValueError
            若字符串格式不合法(长度不为 26 或包含非 Crockford base32 字符)。
        """
        if isinstance(value, ULID):
            return str(value)
        if isinstance(value, str):
            if len(value) != 26:
                raise ValueError(
                    f"ULID must be 26 characters, got {len(value)}: {value!r}"
                )
            # Crockford base32 字符集(不含 I/L/O/U)
            _VALID = frozenset("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
            upper = value.upper()
            invalid = set(upper) - _VALID
            if invalid:
                raise ValueError(
                    f"ULID contains invalid characters {invalid!r}: {value!r}"
                )
            return upper
        raise ValueError(f"Cannot convert {type(value).__name__!r} to ULIDStr")


# Public type alias for Pydantic v2 fields
ULIDStr = Annotated[str, _ULIDStrPydanticAnnotation]
"""Pydantic v2 field type:验证并存储 ULID 格式字符串。

Usage::

    class MyModel(BaseModel):
        id: ULIDStr = Field(default_factory=ulid_new)
"""


def ulid_monotonic_check(ulids: list[str]) -> bool:
    """检查 ULID 列表是否单调递增(字典序)。

    Parameters
    ----------
    ulids:
        ULID 字符串列表。

    Returns
    -------
    bool
        若列表中任意相邻两元素满足 ``ulids[i] <= ulids[i+1]``,则返回 True。
    """
    return all(ulids[i] <= ulids[i + 1] for i in range(len(ulids) - 1))
