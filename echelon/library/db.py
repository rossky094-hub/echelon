"""
echelon.library.db
==================
V14 统一论文库数据库访问层。

SQLite Pilot 实施(db/echelon_library.sqlite3)。
提供 get_session() context manager + 表初始化。

Postgres 切换:修改 DATABASE_URL 环境变量即可,SQLAlchemy 层透明。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

# SQLite Pilot 默认路径
_DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "db" / "echelon_library.sqlite3"

# 生产环境通过环境变量覆盖
LIBRARY_DB_PATH: str = os.environ.get("ECHELON_LIBRARY_DB", str(_DEFAULT_DB_PATH))


# ---------------------------------------------------------------------------
# 原生 SQLite 连接管理(Pilot 实施)
# ---------------------------------------------------------------------------

def _get_connection(db_path: str = LIBRARY_DB_PATH) -> sqlite3.Connection:
    """创建 SQLite 连接(WAL 模式,row_factory)"""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_session(db_path: str = LIBRARY_DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager: 获取数据库连接,自动 commit/rollback。

    用法::

        with get_session() as db:
            db.execute("INSERT INTO papers ...")

    Postgres 切换: 替换此函数返回 asyncpg / psycopg2 连接即可。
    """
    conn = _get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 初始化数据库(执行 DDL 脚本)
# ---------------------------------------------------------------------------

def init_db(db_path: str = LIBRARY_DB_PATH) -> None:
    """
    初始化数据库:创建所有表和索引。

    调用 001_initial.sql DDL 脚本。
    幂等操作:已存在的表/索引不会重建(CREATE IF NOT EXISTS)。
    """
    migrations_dir = Path(__file__).parent / "migrations"
    ddl_file = migrations_dir / "001_initial.sql"

    if not ddl_file.exists():
        raise FileNotFoundError(f"DDL 文件不存在: {ddl_file}")

    ddl = ddl_file.read_text(encoding="utf-8")

    # SQLite executescript 需要先 commit 所有待处理事务
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(ddl)
        conn.commit()
        logger.info(f"[V14] 数据库初始化完成: {db_path}")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CRUD 辅助函数
# ---------------------------------------------------------------------------

def _json_dumps(obj: Any) -> Optional[str]:
    """安全序列化为 JSON 字符串"""
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj
    return json.dumps(obj, ensure_ascii=False, default=str)


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_paper(
    paper_dict: dict,
    db_path: str = LIBRARY_DB_PATH,
    refresh: bool = False,
) -> bool:
    """
    插入或更新一篇论文。

    Returns:
        True 表示新插入, False 表示已存在(跳过/更新)
    """
    # 序列化 JSON 字段
    raw_jsonb = _json_dumps(paper_dict.get("raw_jsonb"))
    open_access = _json_dumps(paper_dict.get("open_access"))

    pub_date = paper_dict.get("publication_date")
    if isinstance(pub_date, date):
        pub_date = pub_date.isoformat()

    with get_session(db_path) as conn:
        arxiv_id_val = paper_dict.get("arxiv_id")
        if arxiv_id_val:
            row = conn.execute(
                "SELECT id FROM papers WHERE arxiv_id = ?",
                (arxiv_id_val,),
            ).fetchone()
            if row:
                paper_dict["id"] = row[0]

        cursor = conn.execute(
            """
            INSERT INTO papers (
                id, openalex_id, doi, arxiv_id, pmid,
                title, abstract, publication_date, n_authors, cited_by_count,
                primary_topic_id, primary_subfield_id, primary_field_id, primary_domain_id,
                venue_id, is_retracted, is_paratext, language,
                open_access, raw_jsonb,
                first_ingested_at, last_refreshed_at,
                source_provider, ingestion_job_id
            ) VALUES (
                :id, :openalex_id, :doi, :arxiv_id, :pmid,
                :title, :abstract, :publication_date, :n_authors, :cited_by_count,
                :primary_topic_id, :primary_subfield_id, :primary_field_id, :primary_domain_id,
                :venue_id, :is_retracted, :is_paratext, :language,
                :open_access, :raw_jsonb,
                :first_ingested_at, :last_refreshed_at,
                :source_provider, :ingestion_job_id
            )
            ON CONFLICT(id) DO UPDATE SET
                last_refreshed_at = excluded.last_refreshed_at,
                cited_by_count    = COALESCE(excluded.cited_by_count, papers.cited_by_count),
                raw_jsonb         = excluded.raw_jsonb,
                title             = CASE WHEN :refresh THEN excluded.title ELSE papers.title END,
                abstract          = CASE WHEN :refresh THEN COALESCE(excluded.abstract, papers.abstract) ELSE papers.abstract END,
                publication_date  = CASE WHEN :refresh THEN excluded.publication_date ELSE papers.publication_date END,
                doi               = CASE WHEN :refresh THEN COALESCE(excluded.doi, papers.doi) ELSE papers.doi END,
                arxiv_id          = CASE WHEN :refresh THEN COALESCE(excluded.arxiv_id, papers.arxiv_id) ELSE papers.arxiv_id END,
                n_authors         = CASE WHEN :refresh THEN COALESCE(excluded.n_authors, papers.n_authors) ELSE papers.n_authors END,
                primary_topic_id  = CASE WHEN :refresh THEN COALESCE(excluded.primary_topic_id, papers.primary_topic_id) ELSE papers.primary_topic_id END,
                open_access       = CASE WHEN :refresh THEN excluded.open_access ELSE papers.open_access END,
                source_provider   = CASE WHEN :refresh THEN excluded.source_provider ELSE papers.source_provider END
            """,
            {
                "id": paper_dict.get("id"),
                "openalex_id": paper_dict.get("openalex_id"),
                "doi": paper_dict.get("doi"),
                "arxiv_id": paper_dict.get("arxiv_id"),
                "pmid": paper_dict.get("pmid"),
                "title": paper_dict.get("title", ""),
                "abstract": paper_dict.get("abstract"),
                "publication_date": pub_date,
                "n_authors": paper_dict.get("n_authors"),
                "cited_by_count": paper_dict.get("cited_by_count"),
                "primary_topic_id": paper_dict.get("primary_topic_id"),
                "primary_subfield_id": paper_dict.get("primary_subfield_id"),
                "primary_field_id": paper_dict.get("primary_field_id"),
                "primary_domain_id": paper_dict.get("primary_domain_id"),
                "venue_id": paper_dict.get("venue_id"),
                "is_retracted": int(paper_dict.get("is_retracted", False)),
                "is_paratext": int(paper_dict.get("is_paratext", False)),
                "language": paper_dict.get("language"),
                "open_access": open_access,
                "raw_jsonb": raw_jsonb,
                "first_ingested_at": paper_dict.get("first_ingested_at") or _now_utc(),
                "last_refreshed_at": _now_utc(),
                "source_provider": paper_dict.get("source_provider"),
                "ingestion_job_id": paper_dict.get("ingestion_job_id"),
                "refresh": 1 if refresh else 0,
            }
        )
        return cursor.rowcount > 0


def upsert_paper_references(citing_id: str, references: list[str],
                             db_path: str = LIBRARY_DB_PATH) -> int:
    """
    批量插入引用关系。

    Args:
        citing_id: 引用方论文的内部 ULID
        references: 被引文献的外部 ID 列表(W ID 等)

    Returns:
        插入行数
    """
    if not references:
        return 0

    rows = [(citing_id, ref_id) for ref_id in references]
    with get_session(db_path) as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO paper_references
                (citing_paper_id, cited_paper_id_external)
            VALUES (?, ?)
            """,
            rows
        )
    return len(rows)


def upsert_author(author_dict: dict, db_path: str = LIBRARY_DB_PATH) -> bool:
    """插入或更新作者"""
    with get_session(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO authors (id, openalex_id, orcid, display_name, h_index, works_count)
            VALUES (:id, :openalex_id, :orcid, :display_name, :h_index, :works_count)
            ON CONFLICT(id) DO UPDATE SET
                display_name = excluded.display_name,
                h_index      = COALESCE(excluded.h_index, authors.h_index),
                works_count  = COALESCE(excluded.works_count, authors.works_count)
            """,
            {
                "id": author_dict.get("id"),
                "openalex_id": author_dict.get("openalex_id"),
                "orcid": author_dict.get("orcid"),
                "display_name": author_dict.get("display_name", ""),
                "h_index": author_dict.get("h_index"),
                "works_count": author_dict.get("works_count"),
            }
        )
        return cursor.rowcount > 0


def link_paper_author(paper_id: str, author_id: str, position: int = 0,
                       affiliation_id: Optional[str] = None,
                       db_path: str = LIBRARY_DB_PATH) -> None:
    """关联论文和作者"""
    with get_session(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO paper_authors
                (paper_id, author_id, author_position, affiliation_id)
            VALUES (?, ?, ?, ?)
            """,
            (paper_id, author_id, position, affiliation_id)
        )


def upsert_ingestion_job(job_dict: dict, db_path: str = LIBRARY_DB_PATH) -> None:
    """插入或更新摄入任务"""
    query_params_json = _json_dumps(job_dict.get("query_params"))
    with get_session(db_path) as conn:
        conn.execute(
            """
            INSERT INTO ingestion_jobs
                (job_id, provider, query_params, status,
                 started_at, finished_at,
                 papers_ingested, papers_skipped_duplicate,
                 error_log, parent_job_id)
            VALUES (:job_id, :provider, :query_params, :status,
                    :started_at, :finished_at,
                    :papers_ingested, :papers_skipped_duplicate,
                    :error_log, :parent_job_id)
            ON CONFLICT(job_id) DO UPDATE SET
                status                   = excluded.status,
                started_at               = COALESCE(excluded.started_at, ingestion_jobs.started_at),
                finished_at              = excluded.finished_at,
                papers_ingested          = excluded.papers_ingested,
                papers_skipped_duplicate = excluded.papers_skipped_duplicate,
                error_log                = excluded.error_log
            """,
            {
                "job_id": job_dict.get("job_id"),
                "provider": job_dict.get("provider"),
                "query_params": query_params_json,
                "status": job_dict.get("status", "pending"),
                "started_at": job_dict.get("started_at"),
                "finished_at": job_dict.get("finished_at"),
                "papers_ingested": job_dict.get("papers_ingested", 0),
                "papers_skipped_duplicate": job_dict.get("papers_skipped_duplicate", 0),
                "error_log": job_dict.get("error_log"),
                "parent_job_id": job_dict.get("parent_job_id"),
            }
        )


def get_hwm_v14(provider: str, topic_id: str = "",
                db_path: str = LIBRARY_DB_PATH) -> Optional[str]:
    """读取 V14 摄入高水位日期"""
    with get_session(db_path) as conn:
        row = conn.execute(
            "SELECT last_processed_date FROM ingestion_hwm WHERE provider=? AND topic_id=?",
            (provider, topic_id)
        ).fetchone()
    return row["last_processed_date"] if row else None


def get_cursor_v14(provider: str, topic_id: str = "",
                   db_path: str = LIBRARY_DB_PATH) -> Optional[str]:
    """读取 V14 上次 cursor(OAI-PMH resumptionToken 等)"""
    with get_session(db_path) as conn:
        row = conn.execute(
            "SELECT last_cursor FROM ingestion_hwm WHERE provider=? AND topic_id=?",
            (provider, topic_id)
        ).fetchone()
    return row["last_cursor"] if row else None


def set_hwm_v14(provider: str, topic_id: str = "",
                last_date: Optional[str] = None,
                last_cursor: Optional[str] = None,
                db_path: str = LIBRARY_DB_PATH) -> None:
    """更新 V14 摄入高水位"""
    with get_session(db_path) as conn:
        conn.execute(
            """
            INSERT INTO ingestion_hwm (provider, topic_id, last_processed_date, last_cursor, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(provider, topic_id) DO UPDATE SET
                last_processed_date = COALESCE(excluded.last_processed_date, ingestion_hwm.last_processed_date),
                last_cursor         = excluded.last_cursor,
                updated_at          = excluded.updated_at
            """,
            (provider, topic_id, last_date, last_cursor, _now_utc())
        )


def get_db_stats(db_path: str = LIBRARY_DB_PATH) -> dict:
    """获取数据库统计信息"""
    stats = {}
    tables = ["papers", "paper_references", "authors", "paper_authors",
              "affiliations", "topics_hierarchy", "pdfs", "retractions",
              "ingestion_jobs", "ingestion_hwm"]
    try:
        with get_session(db_path) as conn:
            for table in tables:
                try:
                    row = conn.execute(f"SELECT COUNT(*) as n FROM {table}").fetchone()
                    stats[table] = row["n"] if row else 0
                except Exception:
                    stats[table] = -1  # 表不存在

        # 数据库文件大小
        db_file = Path(db_path)
        if db_file.exists():
            stats["db_size_bytes"] = db_file.stat().st_size
            stats["db_size_mb"] = round(db_file.stat().st_size / 1024 / 1024, 2)
        else:
            stats["db_size_bytes"] = 0
            stats["db_size_mb"] = 0.0
    except Exception as e:
        stats["error"] = str(e)
    return stats
