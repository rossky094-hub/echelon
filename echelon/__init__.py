"""
echelon
=======
Echelon MVP0a — AI4Science 跨界知识图谱系统。

顶层导出包含核心基础设施与 Schema 的主要符号。

版本: 0.1.0a (Pilot)
"""

__version__ = "0.1.0a"

# 核心基础设施
from echelon.core import (
    AsyncTaskManager,
    DB_PER_CM_VARIANTS,
    PILOT_TOPIC_IDS,
    PILOT_TOPICS,
    OutboxEvent,
    OutboxStore,
    TaskRecord,
    TaskStatus,
    TopicMeta,
    ULIDStr,
    build_filter_string,
    coerce_pub_date,
    date_to_iso,
    get_default_manager,
    get_topic,
    is_in_range,
    is_parseable,
    iter_works_by_topic,
    list_topics,
    llm_unit_fallback,
    normalize_quantity,
    parse_pub_date,
    parse_unit,
    topic_id_for_name,
    ulid_monotonic_check,
    ulid_new,
)

# Schema
from echelon.schema import (
    AuthorInfo,
    EditType,
    GraphEditBatch,
    GraphEditOperation,
    Paper,
    PaperSummary,
)

__all__ = [
    "__version__",
    # core
    "ulid_new",
    "ULIDStr",
    "ulid_monotonic_check",
    "iter_works_by_topic",
    "build_filter_string",
    "PILOT_TOPICS",
    "PILOT_TOPIC_IDS",
    "TopicMeta",
    "get_topic",
    "list_topics",
    "topic_id_for_name",
    "OutboxStore",
    "OutboxEvent",
    "parse_unit",
    "normalize_quantity",
    "is_parseable",
    "llm_unit_fallback",
    "DB_PER_CM_VARIANTS",
    "AsyncTaskManager",
    "TaskRecord",
    "TaskStatus",
    "get_default_manager",
    "parse_pub_date",
    "coerce_pub_date",
    "date_to_iso",
    "is_in_range",
    # schema
    "Paper",
    "PaperSummary",
    "AuthorInfo",
    "GraphEditOperation",
    "GraphEditBatch",
    "EditType",
]
