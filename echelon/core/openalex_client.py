"""
echelon.core.openalex_client
=============================
OpenAlex API 异步客户端,实现 cursor 分页迭代。

[修订自 AUDIT-067] 原实现使用 ``page`` 参数,受 OpenAlex 单次最多返回
10 000 条的硬限制;改为 cursor 分页(``cursor="*"`` 起始,逐页追踪
``meta.next_cursor``)可突破此限制,理论可遍历全量结果。

参考: V11.2 白皮书 §6.2 L1 图谱构建;CONFIG.md §Pilot 抽取规则
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import AsyncIterator

import httpx

_BASE_URL = "https://api.openalex.org"
_DEFAULT_PER_PAGE = 200
_DEFAULT_TIMEOUT = 30.0
_USER_AGENT = "Echelon-MVP0a/1.0 (mailto:team@echelon.ai)"


async def iter_works_by_topic(
    topic_id: str,
    since: date | str,
    until: date | str,
    *,
    per_page: int = _DEFAULT_PER_PAGE,
    max_results: int | None = None,
    mailto: str | None = None,
    _http_client: httpx.AsyncClient | None = None,
) -> AsyncIterator[dict]:
    """游标分页迭代指定 topic 的 OpenAlex Works。

    本函数使用 ``cursor="*"`` 起始进行游标分页,每页最多 ``per_page`` 条,
    无 10 000 条上限;通过追踪响应中的 ``meta.next_cursor`` 逐页前进,
    直至 ``next_cursor`` 为 ``None``。

    Parameters
    ----------
    topic_id:
        OpenAlex Topic ID,如 ``T10245``。
    since:
        起始日期(含),如 ``date(2024, 1, 1)`` 或 ``"2024-01-01"``。
    until:
        截止日期(含),如 ``date(2026, 5, 9)`` 或 ``"2026-05-09"``。
    per_page:
        每页返回条数,最大 200。默认 200。
    max_results:
        最多返回条数(用于 Pilot 截断);``None`` 表示不限制。
    mailto:
        联系邮箱,传入后进入 OpenAlex polite pool,限速更宽松。
    _http_client:
        可注入的 ``httpx.AsyncClient``(供测试 mock 用)。

    Yields
    ------
    dict
        单篇 Work 的原始 JSON 字典。

    Examples
    --------
    以下示例仅演示 API 形态,实际运行需网络连接::

        async for work in iter_works_by_topic(
            "T10245",
            since="2024-01-01",
            until="2026-05-09",
            max_results=250,
        ):
            print(work["id"])

    Notes
    -----
    - 不使用 ``page`` 参数,彻底规避 10 000 条限制 (AUDIT-067)。
    - 若 ``_http_client`` 为 None,函数内部自建 AsyncClient;否则使用
      注入客户端(用于单元测试 mock/replay)。
    """
    since_str = since.isoformat() if isinstance(since, date) else str(since)
    until_str = until.isoformat() if isinstance(until, date) else str(until)

    headers = {"User-Agent": _USER_AGENT}
    params_base: dict[str, str | int] = {
        "filter": (
            f"primary_topic.id:{topic_id},"
            f"from_publication_date:{since_str},"
            f"to_publication_date:{until_str},"
            "is_retracted:false,"
            "has_abstract:true"
        ),
        "per_page": per_page,
        "select": ",".join(
            [
                "id",
                "doi",
                "title",
                "abstract_inverted_index",
                "publication_date",
                "primary_topic",
                "authorships",
                "referenced_works",
                "cited_by_count",
                "language",
            ]
        ),
    }
    if mailto:
        params_base["mailto"] = mailto

    yielded = 0
    cursor: str = "*"

    _own_client = _http_client is None
    client = _http_client or httpx.AsyncClient(
        base_url=_BASE_URL,
        headers=headers,
        timeout=_DEFAULT_TIMEOUT,
    )

    try:
        while True:
            params = {**params_base, "cursor": cursor}
            resp = await client.get("/works", params=params)
            resp.raise_for_status()
            payload = resp.json()

            results: list[dict] = payload.get("results", [])
            next_cursor: str | None = payload.get("meta", {}).get("next_cursor")

            for work in results:
                if max_results is not None and yielded >= max_results:
                    return
                yield work
                yielded += 1

            if not next_cursor:
                break
            cursor = next_cursor

    finally:
        if _own_client:
            await client.aclose()


def build_filter_string(
    topic_id: str,
    since: date | str,
    until: date | str,
    *,
    language: str = "en",
) -> str:
    """构建 OpenAlex filter 字符串(供调试/日志使用)。

    Parameters
    ----------
    topic_id:
        Topic ID。
    since:
        起始日期。
    until:
        截止日期。
    language:
        论文语言过滤,默认 ``"en"``。

    Returns
    -------
    str
        OpenAlex filter 字符串。
    """
    since_str = since.isoformat() if isinstance(since, date) else str(since)
    until_str = until.isoformat() if isinstance(until, date) else str(until)
    return (
        f"primary_topic.id:{topic_id},"
        f"from_publication_date:{since_str},"
        f"to_publication_date:{until_str},"
        f"language:{language},"
        "is_retracted:false,"
        "has_abstract:true"
    )
