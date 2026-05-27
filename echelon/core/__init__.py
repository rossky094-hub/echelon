"""
echelon.core
============
Echelon MVP0a 核心基础设施模块。

导出所有 P0 基础设施组件的主要公开符号。
"""

from echelon.core.async_task import (
    AsyncTaskManager,
    TaskRecord,
    TaskStatus,
    get_default_manager,
)
from echelon.core.date_utils import (
    coerce_pub_date,
    date_to_iso,
    is_in_range,
    parse_pub_date,
)
from echelon.core.openalex_client import (
    build_filter_string,
    iter_works_by_topic,
)
from echelon.core.outbox import (
    OutboxEvent,
    OutboxStore,
)
from echelon.core.topic_mapper import (
    PILOT_TOPIC_IDS,
    PILOT_TOPICS,
    TopicMeta,
    get_topic,
    list_topics,
    topic_id_for_name,
)
from echelon.core.ulid_utils import (
    ULIDStr,
    ulid_monotonic_check,
    ulid_new,
)
from echelon.core.unit_normalizer import (
    DB_PER_CM_VARIANTS,
    is_parseable,
    llm_unit_fallback,
    normalize_quantity,
    parse_unit,
)
from echelon.core.rbac import (
    AuthError,
    PILOT_MODE,
    ROLE_HIERARCHY,
    VALID_ROLES,
    check_role,
    get_token_from_request,
    require_role,
    resolve_role_from_token,
)

__all__ = [
    # ulid_utils (AUDIT-026)
    "ulid_new",
    "ULIDStr",
    "ulid_monotonic_check",
    # openalex_client (AUDIT-067)
    "iter_works_by_topic",
    "build_filter_string",
    # topic_mapper (AUDIT-024)
    "PILOT_TOPICS",
    "PILOT_TOPIC_IDS",
    "TopicMeta",
    "get_topic",
    "list_topics",
    "topic_id_for_name",
    # outbox (AUDIT-025)
    "OutboxStore",
    "OutboxEvent",
    # unit_normalizer (AUDIT-064)
    "parse_unit",
    "normalize_quantity",
    "is_parseable",
    "llm_unit_fallback",
    "DB_PER_CM_VARIANTS",
    # async_task (AUDIT-070)
    "AsyncTaskManager",
    "TaskRecord",
    "TaskStatus",
    "get_default_manager",
    # date_utils (AUDIT-074)
    "parse_pub_date",
    "coerce_pub_date",
    "date_to_iso",
    "is_in_range",
    # rbac (AUDIT-056)
    "require_role",
    "check_role",
    "AuthError",
    "resolve_role_from_token",
    "get_token_from_request",
    "ROLE_HIERARCHY",
    "VALID_ROLES",
    "PILOT_MODE",
]
