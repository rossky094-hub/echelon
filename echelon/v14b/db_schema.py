"""
V14-B 数据库 Schema 定义

包含:
  - Pydantic 模型(数据验证)
  - SQL DDL 语句
  - DB 初始化工具函数
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Pydantic 模型
# ---------------------------------------------------------------------------

class MainPathEdge(BaseModel):
    """main_path_edges 表 - SPC 主干道边"""
    citing_id: str
    cited_id: str
    source_paper_id: Optional[str] = None
    target_paper_id: Optional[str] = None
    edge_direction: Optional[str] = "time_forward_cited_to_citing"
    spc: float = Field(ge=0.0)
    v13_weight: float = Field(ge=0.0)
    main_path_weight: float = Field(ge=0.0)
    is_main_path: bool = False

    @field_validator("citing_id", "cited_id", "source_paper_id", "target_paper_id", mode="before")
    @classmethod
    def _coerce_paper_id(cls, value):
        return None if value is None else str(value)


class SubgraphNode(BaseModel):
    """subgraph_nodes 表 - 子图节点(含所有分析结果)"""
    paper_id: str
    keystone_score_v14: Optional[float] = Field(None, ge=0.0, le=1.0)
    lifecycle_v14: Optional[str] = None          # fresh/growing/mature
    is_keystone: Optional[bool] = None
    is_fresh_top: Optional[bool] = None
    is_neighbor: Optional[bool] = None
    primary_field_id: Optional[str] = None
    mutation_red: bool = False
    mutation_orange: bool = False
    mutation_purple: bool = False
    umap_x: Optional[float] = None
    umap_y: Optional[float] = None
    z_year: Optional[float] = None
    node_size: Optional[float] = None
    color_hex: Optional[str] = None


class SubgraphEdge(BaseModel):
    """subgraph_edges 表 - 子图边(含引用功能分类)"""
    citing_id: str
    cited_id: str
    citation_function: Optional[str] = None
    citation_function_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    citation_function_method: Optional[str] = None
    citation_function_evidence_level: Optional[str] = None
    citation_context_available: bool = False
    citation_function_weight: Optional[float] = Field(None, ge=0.0, le=1.0)
    main_path_weight: Optional[float] = Field(None, ge=0.0)


class LimitationAtom(BaseModel):
    """limitation_atoms 表 - 原子化局限性"""
    atom_id: Optional[int] = None           # AUTOINCREMENT
    paper_id: str
    description: str
    keyword: Optional[str] = None
    severity: Optional[str] = None          # high/medium/low
    extracted_at: Optional[datetime] = None


class LimitationResolution(BaseModel):
    """limitation_resolutions 表 - 局限性解决记录"""
    atom_id: int
    resolver_paper_id: str
    resolution_year: Optional[int] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    evidence_text: Optional[str] = None


class PredictedFutureEdge(BaseModel):
    """predicted_future_edges 表 - VGAE 预测的未来引用边"""
    src_paper_id: str
    dst_paper_id: str
    predicted_prob: float = Field(ge=0.0, le=1.0)
    raw_predicted_prob: Optional[float] = Field(None, ge=0.0, le=1.0)
    calibrated_prob: Optional[float] = Field(None, ge=0.0, le=1.0)
    calibration_method: Optional[str] = None
    calibration_support: Optional[int] = None
    prediction_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    calibration_label: Optional[str] = None
    src_year: Optional[int] = None
    dst_year: Optional[int] = None
    is_cross_field: bool = False


class FutureDirection(BaseModel):
    """future_directions 表 - 三路融合输出的未来方向"""
    direction_id: Optional[int] = None      # AUTOINCREMENT
    direction_name: str
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    expected_period: Optional[str] = None   # e.g. "2026-2028"
    main_path_evidence: Optional[str] = None
    vgae_evidence: Optional[str] = None
    limitation_evidence: Optional[str] = None
    paper_ids_json: Optional[str] = None    # JSON array of paper_ids
    evidence_paths: Optional[int] = None
    evidence_tier: Optional[str] = None
    claim_scope: Optional[str] = None
    calibration_label: Optional[str] = None
    evidence_json: Optional[str] = None


# ---------------------------------------------------------------------------
# SQL DDL
# ---------------------------------------------------------------------------

DDL_STATEMENTS = """
-- ================================================================
-- V14-B Pilot 数据库 Schema
-- 创建时间: 自动生成
-- 注意: 此文件描述新表 (V14-B 专用),不修改 V14-A 原表
-- ================================================================

-- 主干道边 (Step 2 输出)
-- Historical citing_id/cited_id columns are retained for compatibility.
-- Their values are time-forward SPC endpoints, equivalent to
-- source_paper_id -> target_paper_id (cited/older -> citing/newer).
-- New API/product code should prefer source_paper_id/target_paper_id.
CREATE TABLE IF NOT EXISTS main_path_edges (
    citing_id             TEXT NOT NULL,
    cited_id              TEXT NOT NULL,
    source_paper_id       TEXT,
    target_paper_id       TEXT,
    edge_direction        TEXT NOT NULL DEFAULT 'time_forward_cited_to_citing',
    spc                   REAL    NOT NULL DEFAULT 0,
    v13_weight            REAL    NOT NULL DEFAULT 0,
    main_path_weight      REAL    NOT NULL DEFAULT 0,
    is_main_path          BOOLEAN DEFAULT 0,
    PRIMARY KEY (citing_id, cited_id)
);

CREATE INDEX IF NOT EXISTS idx_main_path_edges_is_main
    ON main_path_edges (is_main_path);
CREATE INDEX IF NOT EXISTS idx_main_path_edges_weight
    ON main_path_edges (main_path_weight DESC);

-- Step 2 SCC condensation audit.
-- Cycles in citation DAG are not deleted arbitrarily. They are collapsed into
-- ambiguous temporal components before SPC and tracked here.
CREATE TABLE IF NOT EXISTS main_path_cycle_audit (
    run_id              TEXT    NOT NULL,
    component_id        TEXT    NOT NULL,
    component_size      INTEGER NOT NULL,
    year_min            INTEGER,
    year_max            INTEGER,
    intra_edges         INTEGER NOT NULL DEFAULT 0,
    member_ids_json     TEXT    NOT NULL,
    sample_edges_json   TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, component_id)
);

CREATE INDEX IF NOT EXISTS idx_main_path_cycle_size
    ON main_path_cycle_audit (component_size DESC);

CREATE TABLE IF NOT EXISTS main_path_edge_audit (
    citing_id              TEXT NOT NULL,
    cited_id               TEXT NOT NULL,
    source_component_id    TEXT NOT NULL,
    target_component_id    TEXT NOT NULL,
    component_edge_size    INTEGER NOT NULL DEFAULT 1,
    spc_scope              TEXT NOT NULL DEFAULT 'paper_dag',
    temporal_status        TEXT,
    PRIMARY KEY (citing_id, cited_id)
);

CREATE INDEX IF NOT EXISTS idx_main_path_edge_audit_scope
    ON main_path_edge_audit (spc_scope);
CREATE INDEX IF NOT EXISTS idx_main_path_edge_audit_components
    ON main_path_edge_audit (source_component_id, target_component_id);

-- 子图节点 (Step 4 构建, 后续 step 写入分析结果)
CREATE TABLE IF NOT EXISTS subgraph_nodes (
    paper_id              TEXT PRIMARY KEY,
    keystone_score_v14    REAL,
    lifecycle_v14         TEXT,
    is_keystone           BOOLEAN,
    is_fresh_top          BOOLEAN,
    is_neighbor           BOOLEAN,
    primary_field_id      TEXT,
    mutation_red          BOOLEAN DEFAULT 0,
    mutation_orange       BOOLEAN DEFAULT 0,
    mutation_purple       BOOLEAN DEFAULT 0,
    umap_x                REAL,
    umap_y                REAL,
    z_year                REAL,
    node_size             REAL,
    color_hex             TEXT
);

CREATE INDEX IF NOT EXISTS idx_subgraph_nodes_keystone
    ON subgraph_nodes (keystone_score_v14 DESC);
CREATE INDEX IF NOT EXISTS idx_subgraph_nodes_lifecycle
    ON subgraph_nodes (lifecycle_v14);
CREATE INDEX IF NOT EXISTS idx_subgraph_nodes_field
    ON subgraph_nodes (primary_field_id);

-- 子图边 (Step 4 构建, Step 5a 写入 citation_function)
CREATE TABLE IF NOT EXISTS subgraph_edges (
    citing_id                       TEXT NOT NULL,
    cited_id                        TEXT NOT NULL,
    citation_function               TEXT,
    citation_function_confidence    REAL,
    citation_function_method        TEXT,
    citation_function_evidence_level TEXT,
    citation_context_available      BOOLEAN DEFAULT 0,
    citation_function_weight        REAL,
    main_path_weight                REAL,
    PRIMARY KEY (citing_id, cited_id)
);

CREATE INDEX IF NOT EXISTS idx_subgraph_edges_function
    ON subgraph_edges (citation_function);

-- Step 4 subgraph scope audit. Step4 is a pilot/evidence subgraph for heavier
-- algorithms. Step10 visual graph is the full product graph.
CREATE TABLE IF NOT EXISTS subgraph_scope_audit (
    run_id                TEXT PRIMARY KEY,
    total_papers          INTEGER NOT NULL,
    total_linked_refs     INTEGER NOT NULL,
    configured_max_size   INTEGER NOT NULL,
    recommended_max_size  INTEGER NOT NULL,
    selected_nodes        INTEGER NOT NULL,
    selected_edges        INTEGER NOT NULL,
    node_coverage         REAL NOT NULL,
    edge_coverage         REAL NOT NULL,
    edge_density          REAL NOT NULL,
    conclusion_scope      TEXT NOT NULL,
    adequacy_label        TEXT NOT NULL,
    notes_json            TEXT,
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 原子化局限性 (Step 5c 输出)
CREATE TABLE IF NOT EXISTS limitation_atoms (
    atom_id       INTEGER  PRIMARY KEY AUTOINCREMENT,
    paper_id      TEXT     NOT NULL,
    description   TEXT     NOT NULL,
    keyword       TEXT,
    severity      TEXT,
    evidence_source TEXT,
    evidence_quality TEXT,
    evidence_weight REAL,
    source_section_name TEXT,
    extractor_method TEXT,
    extracted_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_limitation_atoms_paper
    ON limitation_atoms (paper_id);
CREATE INDEX IF NOT EXISTS idx_limitation_atoms_severity
    ON limitation_atoms (severity);

-- 局限性解决记录 (Step 5c 输出)
CREATE TABLE IF NOT EXISTS limitation_resolutions (
    atom_id            INTEGER NOT NULL,
    resolver_paper_id  TEXT    NOT NULL,
    resolution_year    INTEGER,
    confidence         REAL,
    evidence_text      TEXT,
    PRIMARY KEY (atom_id, resolver_paper_id)
);

CREATE INDEX IF NOT EXISTS idx_limit_res_atom
    ON limitation_resolutions (atom_id);
CREATE INDEX IF NOT EXISTS idx_limit_res_confidence
    ON limitation_resolutions (confidence DESC);

-- VGAE 预测的未来引用边 (Step 5b 输出)
CREATE TABLE IF NOT EXISTS predicted_future_edges (
    src_paper_id    TEXT NOT NULL,
    dst_paper_id    TEXT NOT NULL,
    predicted_prob  REAL    NOT NULL,
    raw_predicted_prob REAL,
    calibrated_prob REAL,
    calibration_method TEXT,
    calibration_support INTEGER,
    prediction_confidence REAL,
    calibration_label TEXT,
    src_year        INTEGER,
    dst_year        INTEGER,
    is_cross_field  BOOLEAN DEFAULT 0,
    PRIMARY KEY (src_paper_id, dst_paper_id)
);

CREATE INDEX IF NOT EXISTS idx_pred_edges_prob
    ON predicted_future_edges (predicted_prob DESC);
CREATE INDEX IF NOT EXISTS idx_pred_edges_cross_field
    ON predicted_future_edges (is_cross_field);

-- 三路融合输出的未来方向 (Step 6 输出)
CREATE TABLE IF NOT EXISTS future_directions (
    direction_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    direction_name       TEXT    NOT NULL,
    confidence           REAL,
    expected_period      TEXT,
    main_path_evidence   TEXT,
    vgae_evidence        TEXT,
    limitation_evidence  TEXT,
    paper_ids_json       TEXT,
    evidence_paths       INTEGER,
    evidence_tier        TEXT,
    claim_scope          TEXT,
    calibration_label    TEXT,
    evidence_json        TEXT
);

-- Step 6 evidence sparsity/adequacy audit.
CREATE TABLE IF NOT EXISTS fusion_evidence_audit (
    run_id                    TEXT PRIMARY KEY,
    n_terminals               INTEGER NOT NULL,
    n_vgae_preds_top          INTEGER NOT NULL,
    n_vgae_preds_total        INTEGER NOT NULL,
    n_cross_field_total       INTEGER NOT NULL,
    n_unresolved              INTEGER NOT NULL,
    n_candidates              INTEGER NOT NULL,
    n_directions              INTEGER NOT NULL,
    limitation_quality_json   TEXT,
    evidence_path_json        TEXT,
    candidate_tier_json       TEXT,
    calibration_json          TEXT,
    adequacy_label            TEXT NOT NULL,
    remaining_risk            TEXT,
    created_at                TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 运行元数据 (各 step 完成标记)
CREATE TABLE IF NOT EXISTS v14b_run_meta (
    step_name    TEXT    PRIMARY KEY,
    status       TEXT    NOT NULL DEFAULT 'pending',
    started_at   TIMESTAMP,
    finished_at  TIMESTAMP,
    records_n    INTEGER DEFAULT 0,
    notes        TEXT
);

-- 图谱可视化编辑记录 (V13 预埋, V14 实现)
CREATE TABLE IF NOT EXISTS graph_visual_edits (
    edit_id             TEXT     PRIMARY KEY,
    target_type         TEXT     NOT NULL,
    target_id           TEXT     NOT NULL,
    action              TEXT     NOT NULL,
    payload             TEXT,
    rationale           TEXT,
    expert_id           TEXT     NOT NULL,
    timestamp           TIMESTAMP NOT NULL,
    version             INTEGER  NOT NULL DEFAULT 1,
    status              TEXT     DEFAULT 'accepted',
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_graph_visual_edits_expert
    ON graph_visual_edits (expert_id);
CREATE INDEX IF NOT EXISTS idx_graph_visual_edits_target
    ON graph_visual_edits (target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_graph_visual_edits_timestamp
    ON graph_visual_edits (timestamp DESC);

-- 图谱搜索查询记录 (V13 预埋, V14 实现)
CREATE TABLE IF NOT EXISTS graph_visual_searches (
    query_id            TEXT     PRIMARY KEY,
    query_type          TEXT     NOT NULL,
    query_text          TEXT,
    filters             TEXT,
    top_k               INTEGER,
    expert_id           TEXT,
    timestamp           TIMESTAMP NOT NULL,
    total_matches       INTEGER  DEFAULT 0,
    elapsed_ms          INTEGER  DEFAULT 0,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_graph_visual_searches_expert
    ON graph_visual_searches (expert_id);
CREATE INDEX IF NOT EXISTS idx_graph_visual_searches_type
    ON graph_visual_searches (query_type);
CREATE INDEX IF NOT EXISTS idx_graph_visual_searches_timestamp
    ON graph_visual_searches (timestamp DESC);

-- 图谱搜索结果 (V13 预埋, V14 实现)
CREATE TABLE IF NOT EXISTS graph_visual_search_results (
    result_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id            TEXT     NOT NULL,
    hit_index           INTEGER  NOT NULL,
    hit_data            TEXT     NOT NULL,
    FOREIGN KEY (query_id) REFERENCES graph_visual_searches(query_id)
);

CREATE INDEX IF NOT EXISTS idx_search_results_query
    ON graph_visual_search_results (query_id);
"""


# ---------------------------------------------------------------------------
# Schema 迁移 (V14-A 库 papers.id 为 TEXT ULID)
# ---------------------------------------------------------------------------

def _column_sql_type(conn: sqlite3.Connection, table: str, column: str) -> Optional[str]:
    for row in conn.execute(f"PRAGMA table_info({table})"):
        if row[1] == column:
            return (row[2] or "").upper()
    return None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return _column_sql_type(conn, table, column) is not None


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    ddl_type: str,
    *,
    default_sql: str | None = None,
) -> bool:
    if _column_exists(conn, table, column):
        return False
    suffix = f" DEFAULT {default_sql}" if default_sql is not None else ""
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}{suffix}")
    return True


def _run_ddl_fragment(conn: sqlite3.Connection, ddl: str) -> None:
    for stmt in ddl.split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)


def ensure_v14b_text_paper_ids(conn: sqlite3.Connection) -> None:
    """
    将 V14-B 表中 paper_id / citing_id 等列从 INTEGER 迁移为 TEXT。
    旧库在 CREATE IF NOT EXISTS 下不会自动改列类型, 写入 ULID 会触发 datatype mismatch。
    """
    changed = False

    if _column_sql_type(conn, "subgraph_nodes", "paper_id") == "INTEGER":
        conn.execute("DROP TABLE IF EXISTS subgraph_nodes")
        _run_ddl_fragment(conn, """
        CREATE TABLE subgraph_nodes (
            paper_id              TEXT PRIMARY KEY,
            keystone_score_v14    REAL,
            lifecycle_v14         TEXT,
            is_keystone           BOOLEAN,
            is_fresh_top          BOOLEAN,
            is_neighbor           BOOLEAN,
            primary_field_id      TEXT,
            mutation_red          BOOLEAN DEFAULT 0,
            mutation_orange       BOOLEAN DEFAULT 0,
            mutation_purple       BOOLEAN DEFAULT 0,
            umap_x                REAL,
            umap_y                REAL,
            z_year                REAL,
            node_size             REAL,
            color_hex             TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_subgraph_nodes_keystone
            ON subgraph_nodes (keystone_score_v14 DESC);
        CREATE INDEX IF NOT EXISTS idx_subgraph_nodes_lifecycle
            ON subgraph_nodes (lifecycle_v14);
        CREATE INDEX IF NOT EXISTS idx_subgraph_nodes_field
            ON subgraph_nodes (primary_field_id)
        """)
        changed = True

    if _column_sql_type(conn, "subgraph_edges", "citing_id") == "INTEGER":
        conn.execute("DROP TABLE IF EXISTS subgraph_edges")
        _run_ddl_fragment(conn, """
        CREATE TABLE subgraph_edges (
            citing_id                       TEXT NOT NULL,
            cited_id                        TEXT NOT NULL,
            citation_function               TEXT,
            citation_function_confidence    REAL,
            citation_function_method        TEXT,
            citation_function_evidence_level TEXT,
            citation_context_available      BOOLEAN DEFAULT 0,
            citation_function_weight        REAL,
            main_path_weight                REAL,
            PRIMARY KEY (citing_id, cited_id)
        );
        CREATE INDEX IF NOT EXISTS idx_subgraph_edges_function
            ON subgraph_edges (citation_function)
        """)
        changed = True

    for table, col, ddl in (
        ("limitation_atoms", "paper_id", """
            DROP TABLE IF EXISTS limitation_atoms;
            CREATE TABLE limitation_atoms (
                atom_id       INTEGER  PRIMARY KEY AUTOINCREMENT,
                paper_id      TEXT     NOT NULL,
                description   TEXT     NOT NULL,
                keyword       TEXT,
                severity      TEXT,
                evidence_source TEXT,
                evidence_quality TEXT,
                evidence_weight REAL,
                source_section_name TEXT,
                extractor_method TEXT,
                extracted_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_limitation_atoms_paper
                ON limitation_atoms (paper_id);
            CREATE INDEX IF NOT EXISTS idx_limitation_atoms_severity
                ON limitation_atoms (severity)
        """),
        ("limitation_resolutions", "resolver_paper_id", """
            DROP TABLE IF EXISTS limitation_resolutions;
            CREATE TABLE limitation_resolutions (
                atom_id            INTEGER NOT NULL,
                resolver_paper_id  TEXT    NOT NULL,
                resolution_year    INTEGER,
                confidence         REAL,
                evidence_text      TEXT,
                PRIMARY KEY (atom_id, resolver_paper_id)
            );
            CREATE INDEX IF NOT EXISTS idx_limit_res_atom
                ON limitation_resolutions (atom_id);
            CREATE INDEX IF NOT EXISTS idx_limit_res_confidence
                ON limitation_resolutions (confidence DESC)
        """),
        ("predicted_future_edges", "src_paper_id", """
            DROP TABLE IF EXISTS predicted_future_edges;
            CREATE TABLE predicted_future_edges (
                src_paper_id    TEXT NOT NULL,
                dst_paper_id    TEXT NOT NULL,
                predicted_prob  REAL    NOT NULL,
                raw_predicted_prob REAL,
                calibrated_prob REAL,
                calibration_method TEXT,
                calibration_support INTEGER,
                prediction_confidence REAL,
                calibration_label TEXT,
                src_year        INTEGER,
                dst_year        INTEGER,
                is_cross_field  BOOLEAN DEFAULT 0,
                PRIMARY KEY (src_paper_id, dst_paper_id)
            );
            CREATE INDEX IF NOT EXISTS idx_pred_edges_prob
                ON predicted_future_edges (predicted_prob DESC);
            CREATE INDEX IF NOT EXISTS idx_pred_edges_cross_field
                ON predicted_future_edges (is_cross_field);
            CREATE INDEX IF NOT EXISTS idx_pred_edges_confidence
                ON predicted_future_edges (prediction_confidence DESC)
        """),
    ):
        if _column_sql_type(conn, table, col) == "INTEGER":
            _run_ddl_fragment(conn, ddl)
            changed = True

    if _column_sql_type(conn, "main_path_edges", "citing_id") == "INTEGER":
        _run_ddl_fragment(conn, """
        ALTER TABLE main_path_edges RENAME TO main_path_edges_old;
        CREATE TABLE main_path_edges (
            citing_id             TEXT NOT NULL,
            cited_id              TEXT NOT NULL,
            source_paper_id       TEXT,
            target_paper_id       TEXT,
            edge_direction        TEXT NOT NULL DEFAULT 'time_forward_cited_to_citing',
            spc                   REAL    NOT NULL DEFAULT 0,
            v13_weight            REAL    NOT NULL DEFAULT 0,
            main_path_weight      REAL    NOT NULL DEFAULT 0,
            is_main_path          BOOLEAN DEFAULT 0,
            PRIMARY KEY (citing_id, cited_id)
        );
        INSERT INTO main_path_edges
            SELECT citing_id, cited_id, citing_id, cited_id, 'time_forward_cited_to_citing',
                   spc, v13_weight, main_path_weight, is_main_path
            FROM main_path_edges_old;
        DROP TABLE main_path_edges_old;
        CREATE INDEX IF NOT EXISTS idx_main_path_edges_is_main
            ON main_path_edges (is_main_path);
        CREATE INDEX IF NOT EXISTS idx_main_path_edges_weight
            ON main_path_edges (main_path_weight DESC)
        """)
        changed = True

    for col, ddl_type, default_sql in (
        ("source_paper_id", "TEXT", None),
        ("target_paper_id", "TEXT", None),
        ("edge_direction", "TEXT NOT NULL", "'time_forward_cited_to_citing'"),
    ):
        if _add_column_if_missing(conn, "main_path_edges", col, ddl_type, default_sql=default_sql):
            changed = True
    conn.execute("""
        UPDATE main_path_edges
        SET source_paper_id = COALESCE(source_paper_id, citing_id),
            target_paper_id = COALESCE(target_paper_id, cited_id),
            edge_direction = COALESCE(edge_direction, 'time_forward_cited_to_citing')
    """)
    changed = True

    for col, ddl_type, default_sql in (
        ("citation_function_method", "TEXT", None),
        ("citation_function_evidence_level", "TEXT", None),
        ("citation_context_available", "BOOLEAN", "0"),
        ("citation_function_weight", "REAL", None),
    ):
        if _add_column_if_missing(conn, "subgraph_edges", col, ddl_type, default_sql=default_sql):
            changed = True

    for col, ddl_type, default_sql in (
        ("evidence_source", "TEXT", "'abstract'"),
        ("evidence_quality", "TEXT", "'weak_abstract'"),
        ("evidence_weight", "REAL", "0.35"),
        ("source_section_name", "TEXT", None),
        ("extractor_method", "TEXT", None),
    ):
        if _add_column_if_missing(conn, "limitation_atoms", col, ddl_type, default_sql=default_sql):
            changed = True

    for col, ddl_type in (
        ("raw_predicted_prob", "REAL"),
        ("calibrated_prob", "REAL"),
        ("calibration_method", "TEXT"),
        ("calibration_support", "INTEGER"),
        ("prediction_confidence", "REAL"),
        ("calibration_label", "TEXT"),
    ):
        if _add_column_if_missing(conn, "predicted_future_edges", col, ddl_type):
            changed = True
    _run_ddl_fragment(conn, """
        CREATE INDEX IF NOT EXISTS idx_pred_edges_confidence
            ON predicted_future_edges (prediction_confidence DESC)
    """)

    for col, ddl_type in (
        ("evidence_paths", "INTEGER"),
        ("evidence_tier", "TEXT"),
        ("claim_scope", "TEXT"),
        ("calibration_label", "TEXT"),
        ("evidence_json", "TEXT"),
    ):
        if _add_column_if_missing(conn, "future_directions", col, ddl_type):
            changed = True

    for col, ddl_type in (
        ("candidate_tier_json", "TEXT"),
        ("calibration_json", "TEXT"),
    ):
        if _add_column_if_missing(conn, "fusion_evidence_audit", col, ddl_type):
            changed = True

    if changed:
        conn.commit()


# ---------------------------------------------------------------------------
# DB 初始化工具
# ---------------------------------------------------------------------------

def init_v14b_db(db_path: Path | str) -> sqlite3.Connection:
    """
    初始化 V14-B 数据库,创建所有新表。

    Args:
        db_path: SQLite 数据库路径

    Returns:
        sqlite3.Connection (调用者负责关闭)
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")

    # 执行 DDL (每条 CREATE TABLE IF NOT EXISTS 独立执行)
    for stmt in DDL_STATEMENTS.split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    ensure_v14b_text_paper_ids(conn)
    conn.commit()

    return conn


def get_v14b_conn(db_path: Path | str | None = None) -> sqlite3.Connection:
    """
    获取 V14-B 数据库连接(如不存在则初始化)。

    Args:
        db_path: 数据库路径,默认用 config.DB_V14
    """
    if db_path is None:
        from echelon.v14b.config import DB_V14
        db_path = DB_V14
    return init_v14b_db(db_path)


def upsert_step_meta(
    conn: sqlite3.Connection,
    step_name: str,
    status: str,
    records_n: int = 0,
    notes: str = "",
) -> None:
    """记录 step 运行状态到 v14b_run_meta 表"""
    now = datetime.utcnow().isoformat()
    if status == "running":
        conn.execute(
            """INSERT OR REPLACE INTO v14b_run_meta
               (step_name, status, started_at, finished_at, records_n, notes)
               VALUES (?, ?, ?, NULL, 0, ?)""",
            (step_name, status, now, notes),
        )
    else:
        conn.execute(
            """INSERT OR REPLACE INTO v14b_run_meta
               (step_name, status, started_at, finished_at, records_n, notes)
               VALUES (?, ?, COALESCE(
                   (SELECT started_at FROM v14b_run_meta WHERE step_name=?), ?
               ), ?, ?, ?)""",
            (step_name, status, step_name, now, now, records_n, notes),
        )
    conn.commit()
