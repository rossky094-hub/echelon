"""
echelon.schema.node_metric_history
===================================
节点度量历史纵表 Schema 及 DDL。

[修订自 AUDIT-027]
V11.1 将 metric_history 存储为 JSONB 列(宽表),每次更新整行都产生 MVCC 新版本
→ Tuple bloat 严重(PostgreSQL TOAST 频繁触发),查询也需要全行读取。

V11.2 修复:
  1. 拆出独立纵表 ``node_metric_history``(每行 = 一个指标在一个快照时间点的值)
  2. 按 ``snapshot_year`` 分区(PostgreSQL RANGE 分区),历史年份分区可整体 detach/archive
  3. Pydantic v2 Schema 严格类型定义

参考文献:
  - PostgreSQL TOAST: https://www.postgresql.org/docs/current/storage-toast.html
  - PostgreSQL 声明式分区: https://www.postgresql.org/docs/current/ddl-partitioning.html
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# 支持的指标名称枚举(可扩展)
# ---------------------------------------------------------------------------

MetricName = Literal[
    # 图中心性指标
    "bridging_centrality",
    "betweenness_centrality",
    "degree_centrality",
    "pagerank",
    # 评分指标
    "convergence_score",
    "breakthrough_score",
    "keystone_score",
    "c_recency",
    "c_team_disrupt",
    # 引用指标
    "cited_by_count",
    "semantic_bridge_count",
    # 其他
    "custom",
]


# ---------------------------------------------------------------------------
# Pydantic 纵表行 Schema
# ---------------------------------------------------------------------------


class NodeMetricHistoryRow(BaseModel):
    """``node_metric_history`` 纵表的单行记录。

    [修订自 AUDIT-027] 从 JSONB 宽表拆出,每行代表一个节点在特定快照
    时间的一个指标值,支持 snapshot_year 分区。

    Attributes
    ----------
    id:
        行 ULID(主键,由 generate_ulid() 自动生成)。
    node_id:
        论文/节点 ULID,关联 ``paper.id``。
    metric_name:
        指标名称。
    metric_value:
        指标数值(Decimal 保证精度,避免 IEEE 754 浮点问题)。
    snapshot_date:
        快照日期(分区依据 snapshot_year 由此派生)。
    snapshot_year:
        快照年份(分区键,由 snapshot_date 自动派生)。
    run_id:
        产生本次快照的 pipeline run ID(便于回溯)。
    extra:
        额外元数据。
    created_at:
        记录写入时间(UTC)。
    """

    id: str = Field(description="行 ULID 主键")
    node_id: str = Field(min_length=1, description="关联节点 ULID")
    metric_name: str = Field(min_length=1, description="指标名称")
    metric_value: Decimal = Field(description="指标数值(Decimal 精度)")
    snapshot_date: date = Field(description="快照日期")
    snapshot_year: int = Field(description="快照年份(分区键,由 snapshot_date 派生)")
    run_id: str | None = Field(default=None, description="Pipeline Run ID")
    extra: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @field_validator("snapshot_date", mode="before")
    @classmethod
    def coerce_snapshot_date(cls, v: Any) -> date:
        """支持字符串 YYYY-MM-DD 或 datetime.date。"""
        if isinstance(v, str):
            return date.fromisoformat(v)
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        raise ValueError(f"Cannot coerce snapshot_date from {type(v)}: {v!r}")

    @field_validator("metric_value", mode="before")
    @classmethod
    def coerce_metric_value(cls, v: Any) -> Decimal:
        """将 float/int/str 统一转为 Decimal。"""
        if isinstance(v, Decimal):
            return v
        try:
            return Decimal(str(v))
        except Exception as exc:
            raise ValueError(f"Cannot coerce metric_value: {v!r}") from exc

    @model_validator(mode="after")
    def derive_snapshot_year(self) -> "NodeMetricHistoryRow":
        """确保 snapshot_year 与 snapshot_date 一致。

        [AUDIT-027] 分区键必须与分区范围对齐;允许手动传入 snapshot_year
        但会校验与 snapshot_date.year 一致。
        """
        expected_year = self.snapshot_date.year
        if self.snapshot_year != expected_year:
            raise ValueError(
                f"snapshot_year={self.snapshot_year} != "
                f"snapshot_date.year={expected_year}"
            )
        return self

    model_config = ConfigDict(populate_by_name=True)


def make_row(
    node_id: str,
    metric_name: str,
    metric_value: float | int | Decimal,
    snapshot_date: date | str,
    run_id: str | None = None,
    extra: dict[str, Any] | None = None,
    row_id: str | None = None,
) -> NodeMetricHistoryRow:
    """便捷工厂函数:创建 NodeMetricHistoryRow。

    [修订自 AUDIT-027]

    Parameters
    ----------
    node_id:
        关联节点 ULID。
    metric_name:
        指标名称。
    metric_value:
        指标数值。
    snapshot_date:
        快照日期(date 或 ISO 字符串)。
    run_id:
        Pipeline Run ID(可选)。
    extra:
        附加元数据(可选)。
    row_id:
        行 ULID;若 None,自动生成。

    Returns
    -------
    NodeMetricHistoryRow
    """
    from echelon.core.ulid_utils import ulid_new

    if isinstance(snapshot_date, str):
        sd = date.fromisoformat(snapshot_date)
    else:
        sd = snapshot_date

    return NodeMetricHistoryRow(
        id=row_id or ulid_new(),
        node_id=node_id,
        metric_name=metric_name,
        metric_value=Decimal(str(metric_value)),
        snapshot_date=sd,
        snapshot_year=sd.year,
        run_id=run_id,
        extra=extra or {},
    )


# ---------------------------------------------------------------------------
# SQL DDL(PostgreSQL 生产 + SQLite 兼容注释)
# ---------------------------------------------------------------------------

NODE_METRIC_HISTORY_DDL_PG = """
-- [AUDIT-027] node_metric_history 纵表 DDL (PostgreSQL)
-- 使用 RANGE PARTITION BY snapshot_year 以支持历史年份归档
CREATE TABLE IF NOT EXISTS node_metric_history (
    id              TEXT        NOT NULL,           -- ULID 主键
    node_id         TEXT        NOT NULL,           -- 关联 paper.id
    metric_name     TEXT        NOT NULL,
    metric_value    NUMERIC(20, 10) NOT NULL,       -- Decimal 精度
    snapshot_date   DATE        NOT NULL,
    snapshot_year   INTEGER     NOT NULL,           -- 分区键
    run_id          TEXT,
    extra           JSONB       NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, snapshot_year)
) PARTITION BY RANGE (snapshot_year);

-- 为当前年份自动建分区(可用脚本批量创建历史分区)
-- CREATE TABLE node_metric_history_2024
--     PARTITION OF node_metric_history
--     FOR VALUES FROM (2024) TO (2025);

-- 索引:按节点 + 指标名 + 快照日期查询
CREATE INDEX IF NOT EXISTS idx_nmh_node_metric_date
    ON node_metric_history (node_id, metric_name, snapshot_date);

-- 索引:按 run_id 查询(便于 pipeline 回溯)
CREATE INDEX IF NOT EXISTS idx_nmh_run_id
    ON node_metric_history (run_id)
    WHERE run_id IS NOT NULL;
""".strip()


NODE_METRIC_HISTORY_DDL_SQLITE = """
-- [AUDIT-027] node_metric_history 纵表 DDL (SQLite Pilot)
-- SQLite 不支持声明式分区,但接口语义不变
CREATE TABLE IF NOT EXISTS node_metric_history (
    id              TEXT        NOT NULL PRIMARY KEY,
    node_id         TEXT        NOT NULL,
    metric_name     TEXT        NOT NULL,
    metric_value    REAL        NOT NULL,
    snapshot_date   TEXT        NOT NULL,   -- ISO 8601
    snapshot_year   INTEGER     NOT NULL,
    run_id          TEXT,
    extra           TEXT        NOT NULL DEFAULT '{}',
    created_at      TEXT        NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_nmh_node_metric_date
    ON node_metric_history (node_id, metric_name, snapshot_date);

CREATE INDEX IF NOT EXISTS idx_nmh_run_id
    ON node_metric_history (run_id);
""".strip()


# ---------------------------------------------------------------------------
# SQLite Pilot 帮助函数
# ---------------------------------------------------------------------------

def ensure_table_sqlite(db_path: str) -> None:
    """在 SQLite 数据库中建表(Pilot)。

    [修订自 AUDIT-027]
    """
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.executescript(NODE_METRIC_HISTORY_DDL_SQLITE)
    conn.commit()
    conn.close()


def insert_row_sqlite(row: NodeMetricHistoryRow, db_path: str) -> None:
    """插入单行到 SQLite(Pilot)。

    [修订自 AUDIT-027]
    """
    import json
    import sqlite3
    ensure_table_sqlite(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT OR REPLACE INTO node_metric_history
            (id, node_id, metric_name, metric_value, snapshot_date,
             snapshot_year, run_id, extra, created_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            row.id,
            row.node_id,
            row.metric_name,
            float(row.metric_value),
            row.snapshot_date.isoformat(),
            row.snapshot_year,
            row.run_id,
            json.dumps(row.extra),
            row.created_at.isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def query_node_metrics_sqlite(
    node_id: str,
    metric_name: str | None,
    db_path: str,
) -> list[dict]:
    """查询节点指标历史(SQLite Pilot)。

    [修订自 AUDIT-027]
    """
    import sqlite3
    ensure_table_sqlite(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if metric_name:
        rows = conn.execute(
            "SELECT * FROM node_metric_history WHERE node_id=? AND metric_name=? ORDER BY snapshot_date",
            (node_id, metric_name),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM node_metric_history WHERE node_id=? ORDER BY snapshot_date",
            (node_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
