"""
echelon.core.topic_mapper
=========================
Pilot Topic ID → 元数据 映射模块。

[修订自 AUDIT-024] 原代码中 primary_topic_id 字段缺失,DDL 与查询均未使用
结构化 topic 元数据。本模块内置 4 个 Pilot topic 的完整映射,供 ingest/graph
层使用。

参考: V11.2 白皮书 §2.1 数据采集范围;CONFIG.md §4 个 OpenAlex Topic
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar


@dataclass(frozen=True)
class TopicMeta:
    """单个 OpenAlex Topic 的元数据。

    Attributes
    ----------
    topic_id:
        OpenAlex Topic ID(如 ``T10245``).
    name:
        Topic 全名.
    subfield:
        所属二级学科.
    field:
        所属一级学科.
    pilot_quota:
        Pilot 抽取论文数量上限.
    """

    topic_id: str
    name: str
    subfield: str
    field: str
    pilot_quota: int = 250


# ---------------------------------------------------------------------------
# 内置 4 个 Pilot topics(与 CONFIG.md 完全对应)
# ---------------------------------------------------------------------------

PILOT_TOPICS: dict[str, TopicMeta] = {
    "T10245": TopicMeta(
        topic_id="T10245",
        name="Metamaterials and Metasurfaces Applications",
        subfield="Electronic, Optical and Magnetic Materials",
        field="Materials Science",
        pilot_quota=250,
    ),
    "T10653": TopicMeta(
        topic_id="T10653",
        name="Robot Manipulation and Learning",
        subfield="Control and Systems Engineering",
        field="Engineering",
        pilot_quota=250,
    ),
    "T11714": TopicMeta(
        topic_id="T11714",
        name="Multimodal Machine Learning Applications",
        subfield="Computer Vision and Pattern Recognition",
        field="Computer Science",
        pilot_quota=250,
    ),
    "T10462": TopicMeta(
        topic_id="T10462",
        name="Reinforcement Learning in Robotics",
        subfield="Artificial Intelligence",
        field="Computer Science",
        pilot_quota=250,
    ),
}

# 全部 Pilot topic ID 列表(有序)
PILOT_TOPIC_IDS: list[str] = list(PILOT_TOPICS.keys())


def get_topic(topic_id: str) -> TopicMeta:
    """根据 topic_id 查询 Pilot topic 元数据。

    Parameters
    ----------
    topic_id:
        OpenAlex Topic ID,如 ``T10245``。

    Returns
    -------
    TopicMeta
        对应的 topic 元数据。

    Raises
    ------
    KeyError
        若 topic_id 不在 Pilot 列表中。

    Examples
    --------
    >>> meta = get_topic("T10245")
    >>> meta.field
    'Materials Science'
    """
    try:
        return PILOT_TOPICS[topic_id]
    except KeyError:
        valid = ", ".join(PILOT_TOPIC_IDS)
        raise KeyError(
            f"Unknown topic_id {topic_id!r}. Valid Pilot topics: {valid}"
        ) from None


def list_topics() -> list[TopicMeta]:
    """返回所有 Pilot topic 元数据列表。

    Returns
    -------
    list[TopicMeta]
        4 个 Pilot topic 的元数据列表。
    """
    return list(PILOT_TOPICS.values())


def topic_id_for_name(name: str) -> str:
    """通过 topic 名称反查 topic_id(精确匹配)。

    Parameters
    ----------
    name:
        Topic 名称字符串。

    Returns
    -------
    str
        对应的 topic_id。

    Raises
    ------
    KeyError
        若名称不在 Pilot 列表中。
    """
    for meta in PILOT_TOPICS.values():
        if meta.name == name:
            return meta.topic_id
    raise KeyError(f"No topic found with name {name!r}")
