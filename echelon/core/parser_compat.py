"""
echelon.core.parser_compat
============================
Parser 兼容性哈希(幂等键)。

[修订自 AUDIT-032]
V11.1 问题:幂等键使用 parser_version(语义版本号字符串),存在两个缺陷:
  1. 语义版本号更新不一定意味着解析结果改变(patch 修复不影响输出格式)
  2. schema_version 变化时幂等键不更新 → 旧缓存污染新 schema

V11.2 修复:
  - 幂等键改为 ``parser_compat_hash``:
      SHA-256(parser_name + "|" + parser_version + "|" + schema_version)[:16]
  - 内置 5 个 parser 的兼容性注册表
  - 提供 ``compute_parser_compat_hash(parser_name, parser_version, schema_version)``

参考: V11.2 白皮书 §3.2.2;AUDIT-032
"""

from __future__ import annotations

import hashlib
import logging
from typing import NamedTuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 注册表条目
# ---------------------------------------------------------------------------


class ParserCompatEntry(NamedTuple):
    """Parser 兼容性注册表条目。

    Attributes
    ----------
    parser_name:
        Parser 名称(唯一标识)。
    parser_version:
        Parser 版本号字符串。
    schema_version:
        关联 Schema 版本号字符串(影响输出字段结构)。
    description:
        简要描述。
    """

    parser_name: str
    parser_version: str
    schema_version: str
    description: str


# ---------------------------------------------------------------------------
# 内置 5 个 Parser 兼容性注册表 [AUDIT-032]
# ---------------------------------------------------------------------------

PARSER_REGISTRY: dict[str, ParserCompatEntry] = {
    "pdfplumber": ParserCompatEntry(
        parser_name="pdfplumber",
        parser_version="0.10.3",
        schema_version="2.1.0",
        description="pdfplumber PDF 文本提取;V11.2 schema 新增 page_no 字段",
    ),
    "grobid": ParserCompatEntry(
        parser_name="grobid",
        parser_version="0.8.0",
        schema_version="2.1.0",
        description="GROBID 学术文献结构解析(标题/作者/摘要/参考文献)",
    ),
    "sentence_split": ParserCompatEntry(
        parser_name="sentence_split",
        parser_version="1.2.0",
        schema_version="2.0.0",
        description="句子分割器(spacy sentencizer);V11.2 改用 ±1 上下文窗口",
    ),
    "regex_evidence": ParserCompatEntry(
        parser_name="regex_evidence",
        parser_version="2.3.1",
        schema_version="2.1.0",
        description="正则表达式证据抽取;V11.2 新增 SELF_PRAISE_PATTERNS",
    ),
    "spacy": ParserCompatEntry(
        parser_name="spacy",
        parser_version="3.7.2",
        schema_version="2.0.0",
        description="spaCy NLP pipeline(NER/代词消解/实体链接)",
    ),
}


# ---------------------------------------------------------------------------
# 核心函数
# ---------------------------------------------------------------------------


def compute_parser_compat_hash(
    parser_name: str,
    parser_version: str,
    schema_version: str,
) -> str:
    """计算 parser 兼容性哈希(幂等键)。

    [修订自 AUDIT-032]

    算法:
        raw = "{parser_name}|{parser_version}|{schema_version}"
        hash = SHA-256(raw.encode("utf-8"))[:16]  # 前 16 hex chars = 64 bit

    保证:
    - 任意一个维度(parser_name/parser_version/schema_version)变化 → hash 变化
    - 相同三元组 → hash 恒定(幂等)

    Parameters
    ----------
    parser_name:
        Parser 名称,如 ``"pdfplumber"``。
    parser_version:
        Parser 版本号,如 ``"0.10.3"``。
    schema_version:
        关联 Schema 版本号,如 ``"2.1.0"``。

    Returns
    -------
    str
        16 字符十六进制哈希(前 64 bits of SHA-256)。

    Examples
    --------
    ::

        h = compute_parser_compat_hash("pdfplumber", "0.10.3", "2.1.0")
        # "a3f1b2c9d4e5f607"  (示例,实际值由 SHA-256 决定)
    """
    if not parser_name:
        raise ValueError("[AUDIT-032] parser_name must not be empty")
    if not parser_version:
        raise ValueError("[AUDIT-032] parser_version must not be empty")
    if not schema_version:
        raise ValueError("[AUDIT-032] schema_version must not be empty")

    raw = f"{parser_name}|{parser_version}|{schema_version}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    result = digest[:16]  # 16 hex chars = 64 bits — 足以防碰撞

    logger.debug(
        "[AUDIT-032] parser_compat_hash: raw=%r -> hash=%r",
        raw,
        result,
    )
    return result


def get_registered_hash(parser_name: str) -> str:
    """从内置注册表获取指定 parser 的兼容性哈希。

    [修订自 AUDIT-032]

    Parameters
    ----------
    parser_name:
        注册表中的 parser 名称(见 ``PARSER_REGISTRY``)。

    Returns
    -------
    str
        对应的 ``parser_compat_hash``。

    Raises
    ------
    KeyError
        若 parser_name 不在注册表中。
    """
    if parser_name not in PARSER_REGISTRY:
        available = list(PARSER_REGISTRY.keys())
        raise KeyError(
            f"[AUDIT-032] parser {parser_name!r} not in registry; "
            f"available: {available}"
        )
    entry = PARSER_REGISTRY[parser_name]
    return compute_parser_compat_hash(
        entry.parser_name,
        entry.parser_version,
        entry.schema_version,
    )


def list_all_hashes() -> dict[str, str]:
    """返回所有注册 parser 的名称 → hash 映射。

    [修订自 AUDIT-032]

    Returns
    -------
    dict[str, str]
        ``{parser_name: parser_compat_hash}``。
    """
    return {name: get_registered_hash(name) for name in PARSER_REGISTRY}


def register_parser(
    parser_name: str,
    parser_version: str,
    schema_version: str,
    description: str = "",
) -> str:
    """动态注册新 parser 并返回其兼容性哈希。

    [修订自 AUDIT-032]

    Parameters
    ----------
    parser_name:
        Parser 名称(若已存在则覆盖)。
    parser_version:
        Parser 版本号。
    schema_version:
        Schema 版本号。
    description:
        描述文字。

    Returns
    -------
    str
        计算得到的 ``parser_compat_hash``。
    """
    entry = ParserCompatEntry(
        parser_name=parser_name,
        parser_version=parser_version,
        schema_version=schema_version,
        description=description,
    )
    PARSER_REGISTRY[parser_name] = entry
    h = compute_parser_compat_hash(parser_name, parser_version, schema_version)
    logger.info(
        "[AUDIT-032] registered parser: name=%r version=%r schema=%r hash=%r",
        parser_name,
        parser_version,
        schema_version,
        h,
    )
    return h
