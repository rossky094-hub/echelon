"""
Step 1: 多源 Enrich 13606 篇

默认数据源 (V14B_ENRICH_PROVIDERS): Semantic Scholar → Crossref → (可选) OpenAlex

补充:
  - cited_by_count / external work id
  - paper_references (引用列表)
  - topics_hierarchy (S2/OpenAlex 有时为空)

CLI:
    python -m echelon.v14b.step1_enrich --help
    python -m echelon.v14b.step1_enrich --db db/echelon_library.sqlite3 --concurrency 10
    python -m echelon.v14b.step1_enrich --limit 100  # 调试

支持 --resume (已 enrich 的自动跳过)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

from tqdm import tqdm

from echelon.v14b.utils import (
    setup_logging, Checkpoint, add_common_args, make_progress,
    ensure_library_schema_compat,
)
from echelon.v14b.config import (
    DB_MAIN, CONCURRENCY, LIMIT, USE_OPENALEX, SEMANTIC_SCHOLAR_API_KEY,
)
from echelon.v14b.enrich_providers import (
    effective_enrich_providers,
    _clean_doi,
)
from echelon.v14b.id_normalization import (
    classify_external_id,
    normalize_arxiv_id,
    normalize_doi,
    normalize_openalex_work_id,
    normalize_s2_paper_id,
)

logger = logging.getLogger("echelon.v14b.step1_enrich")

# ---------------------------------------------------------------------------
# DB 工具
# ---------------------------------------------------------------------------

def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _oa_id_tail(raw: Optional[str]) -> Optional[str]:
    """OpenAlex URL/ID → 尾段 (如 T10245, W4392199370, S3107)."""
    if not raw:
        return None
    tail = raw.split("/")[-1]
    return tail or None


def ensure_enrich_tables(conn: sqlite3.Connection) -> None:
    """确保 enrich 所需列/表存在 (兼容 V14-A library schema)."""
    for col_def in [
        ("openalex_id", "TEXT"),
        ("s2_paper_id", "TEXT"),
        ("cited_by_count", "INTEGER DEFAULT 0"),
        ("primary_topic_id", "TEXT"),
        ("primary_subfield_id", "TEXT"),
        ("primary_field_id", "TEXT"),
        ("primary_domain_id", "TEXT"),
        ("openalex_enriched", "INTEGER DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE papers ADD COLUMN {col_def[0]} {col_def[1]}")
        except Exception:
            pass

    if not _table_columns(conn, "paper_references"):
        conn.executescript("""
            CREATE TABLE paper_references (
                citing_paper_id         TEXT NOT NULL,
                cited_paper_id_external TEXT NOT NULL,
                cited_paper_id_provider TEXT,
                cited_paper_id_norm     TEXT,
                cited_paper_id_internal TEXT,
                PRIMARY KEY (citing_paper_id, cited_paper_id_external)
            );
            CREATE INDEX idx_paper_refs_citing ON paper_references(citing_paper_id);
            CREATE INDEX idx_paper_refs_cited_ext ON paper_references(cited_paper_id_external);
            CREATE INDEX idx_paper_refs_provider_norm ON paper_references(cited_paper_id_provider, cited_paper_id_norm);
        """)
    else:
        ref_cols = _table_columns(conn, "paper_references")
        for col_def in [
            ("cited_paper_id_provider", "TEXT"),
            ("cited_paper_id_norm", "TEXT"),
        ]:
            if col_def[0] not in ref_cols:
                try:
                    conn.execute(f"ALTER TABLE paper_references ADD COLUMN {col_def[0]} {col_def[1]}")
                except Exception:
                    pass
        try:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_paper_refs_provider_norm "
                "ON paper_references(cited_paper_id_provider, cited_paper_id_norm)"
            )
        except Exception:
            pass

    if not _table_columns(conn, "topics_hierarchy"):
        conn.executescript("""
            CREATE TABLE topics_hierarchy (
                topic_id      TEXT PRIMARY KEY,
                topic_name    TEXT,
                subfield_id   TEXT,
                subfield_name TEXT,
                field_id      TEXT,
                field_name    TEXT,
                domain_id     TEXT,
                domain_name   TEXT
            );
        """)

    # Migrate historical provider IDs that were stored in openalex_id.
    try:
        conn.execute("""
            UPDATE papers
            SET openalex_id = NULL
            WHERE openalex_id IS NOT NULL
              AND length(trim(openalex_id)) = 0
        """)
        rows = conn.execute("""
            SELECT id, openalex_id, source_provider
            FROM papers
            WHERE openalex_id IS NOT NULL
              AND length(trim(openalex_id)) > 0
        """).fetchall()
        for paper_id, raw_id, source_provider in rows:
            openalex_id = normalize_openalex_work_id(raw_id)
            if openalex_id:
                if openalex_id != str(raw_id).strip():
                    conn.execute(
                        "UPDATE papers SET openalex_id = ? WHERE id = ?",
                        (openalex_id, paper_id),
                    )
                continue
            provider, norm = classify_external_id(raw_id)
            if provider == "doi" and norm:
                clean_doi = normalize_doi(norm)
                existing = conn.execute(
                    "SELECT id FROM papers WHERE lower(doi) = lower(?) AND id != ? LIMIT 1",
                    (clean_doi, paper_id),
                ).fetchone() if clean_doi else None
                if existing:
                    conn.execute("UPDATE papers SET openalex_id = NULL WHERE id = ?", (paper_id,))
                else:
                    conn.execute("""
                        UPDATE papers
                        SET doi = COALESCE(NULLIF(doi, ''), ?),
                            openalex_id = NULL
                        WHERE id = ?
                    """, (clean_doi, paper_id))
            elif provider == "arxiv" and norm:
                clean_arxiv = normalize_arxiv_id(norm)
                existing = conn.execute(
                    "SELECT id FROM papers WHERE arxiv_id = ? AND id != ? LIMIT 1",
                    (clean_arxiv, paper_id),
                ).fetchone() if clean_arxiv else None
                if existing:
                    conn.execute("UPDATE papers SET openalex_id = NULL WHERE id = ?", (paper_id,))
                else:
                    conn.execute("""
                        UPDATE papers
                        SET arxiv_id = COALESCE(NULLIF(arxiv_id, ''), ?),
                            openalex_id = NULL
                        WHERE id = ?
                    """, (clean_arxiv, paper_id))
            elif (provider == "s2" or source_provider == "semantic_scholar") and norm:
                conn.execute("""
                    UPDATE papers
                    SET s2_paper_id = COALESCE(NULLIF(s2_paper_id, ''), ?),
                        openalex_id = NULL
                    WHERE id = ?
                """, (normalize_s2_paper_id(norm), paper_id))
    except Exception:
        pass

    try:
        rows = conn.execute("""
            SELECT citing_paper_id, cited_paper_id_external
            FROM paper_references
            WHERE cited_paper_id_external IS NOT NULL
              AND (cited_paper_id_provider IS NULL OR cited_paper_id_norm IS NULL)
        """).fetchall()
        updates = []
        for row in rows:
            provider, norm = classify_external_id(row[1])
            updates.append((provider, norm, row[0], row[1]))
        if updates:
            conn.executemany("""
                UPDATE paper_references
                SET cited_paper_id_provider = ?,
                    cited_paper_id_norm = ?
                WHERE citing_paper_id = ?
                  AND cited_paper_id_external = ?
            """, updates)
    except Exception:
        pass

    conn.commit()


def link_paper_reference_internals(conn: sqlite3.Connection) -> int:
    """Map external reference IDs to library ULIDs using provider-aware IDs."""
    def doi_to_arxiv(doi_value: Optional[str]) -> Optional[str]:
        doi_norm = normalize_doi(doi_value)
        if not doi_norm:
            return None
        m = re.match(r"^10\.48550/arxiv\.(.+)$", doi_norm, flags=re.I)
        if not m:
            return None
        return normalize_arxiv_id(m.group(1))

    before = conn.execute(
        "SELECT COUNT(*) FROM paper_references WHERE cited_paper_id_internal IS NOT NULL"
    ).fetchone()[0]

    paper_cols = _table_columns(conn, "papers")
    has_s2_col = "s2_paper_id" in paper_cols
    paper_rows = conn.execute(
        "SELECT id, openalex_id, doi, arxiv_id"
        + (", s2_paper_id" if has_s2_col else "")
        + " FROM papers"
    ).fetchall()

    id_maps: dict[str, dict[str, str]] = {
        "openalex": {},
        "s2": {},
        "doi": {},
        "arxiv": {},
    }
    for row in paper_rows:
        pid = row[0]
        openalex_id = normalize_openalex_work_id(row[1])
        doi = normalize_doi(row[2])
        arxiv_id = row[3]
        s2_id = normalize_s2_paper_id(row[4]) if has_s2_col else None
        if openalex_id:
            id_maps["openalex"].setdefault(openalex_id, pid)
        if s2_id:
            id_maps["s2"].setdefault(s2_id, pid)
        # legacy compatibility: historical S2 IDs may still be in openalex_id.
        legacy_s2 = normalize_s2_paper_id(row[1])
        if legacy_s2 and not openalex_id:
            id_maps["s2"].setdefault(legacy_s2, pid)
        if doi:
            id_maps["doi"].setdefault(doi, pid)
            # arXiv DOIs appear in reference lists frequently. Keep this alias
            # so DOI-form references can relink to arXiv-only papers.
            arxiv_alias = doi_to_arxiv(doi)
            if arxiv_alias:
                id_maps["arxiv"].setdefault(arxiv_alias, pid)
        if arxiv_id:
            id_maps["arxiv"].setdefault(str(arxiv_id).strip(), pid)

    ref_cols = _table_columns(conn, "paper_references")
    has_ref_norm = {
        "cited_paper_id_provider",
        "cited_paper_id_norm",
    }.issubset(ref_cols)
    if has_ref_norm:
        rows = conn.execute("""
            SELECT citing_paper_id, cited_paper_id_external,
                   cited_paper_id_provider, cited_paper_id_norm
            FROM paper_references
            WHERE cited_paper_id_internal IS NULL
              AND cited_paper_id_external IS NOT NULL
        """).fetchall()
    else:
        rows = conn.execute("""
            SELECT citing_paper_id, cited_paper_id_external
            FROM paper_references
            WHERE cited_paper_id_internal IS NULL
              AND cited_paper_id_external IS NOT NULL
        """).fetchall()

    internal_updates = []
    norm_updates = []
    for row in rows:
        citing_id = row[0]
        external = row[1]
        if has_ref_norm:
            provider = row[2]
            norm = row[3]
            if not provider or not norm:
                provider, norm = classify_external_id(external)
                norm_updates.append((provider, norm, citing_id, external))
        else:
            provider, norm = classify_external_id(external)
        target_id = id_maps.get(provider or "", {}).get(norm or "")
        if not target_id and provider == "doi":
            arxiv_alias = doi_to_arxiv(norm)
            if arxiv_alias:
                target_id = id_maps["arxiv"].get(arxiv_alias)
        if not target_id and (provider in (None, "other") or not norm):
            p2, n2 = classify_external_id(external)
            if p2 and n2:
                if has_ref_norm and (provider != p2 or norm != n2):
                    norm_updates.append((p2, n2, citing_id, external))
                target_id = id_maps.get(p2, {}).get(n2)
        if target_id:
            internal_updates.append((target_id, citing_id, external))

    if has_ref_norm and norm_updates:
        conn.executemany("""
            UPDATE paper_references
            SET cited_paper_id_provider = ?,
                cited_paper_id_norm = ?
            WHERE citing_paper_id = ?
              AND cited_paper_id_external = ?
        """, norm_updates)
    if internal_updates:
        conn.executemany("""
            UPDATE paper_references
            SET cited_paper_id_internal = ?
            WHERE citing_paper_id = ?
              AND cited_paper_id_external = ?
        """, internal_updates)
    conn.commit()
    after = conn.execute(
        "SELECT COUNT(*) FROM paper_references WHERE cited_paper_id_internal IS NOT NULL"
    ).fetchone()[0]
    linked = after - before
    logger.info("引用边内部 ID 链接: +%d (合计 %d)", linked, after)
    return linked


def get_unenriched_papers(conn: sqlite3.Connection, limit: Optional[int] = None) -> list[dict]:
    """获取尚未 enrich 的论文列表 (含纯 arXiv, 当 S2/OpenAlex 可用时)."""
    q = """
        SELECT id, arxiv_id, doi, title
        FROM papers
        WHERE (openalex_enriched IS NULL OR openalex_enriched = 0)
    """
    # 无 OpenAlex 且无 S2 Key 时仅能 enrich 有 DOI 的篇目
    if not USE_OPENALEX and not SEMANTIC_SCHOLAR_API_KEY:
        q += " AND doi IS NOT NULL AND doi != ''"
    q += " ORDER BY id"
    if limit:
        q += f" LIMIT {limit}"
    rows = conn.execute(q).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 多源抓取 (S2 / Crossref / OpenAlex)
# ---------------------------------------------------------------------------

async def fetch_one(
    session,
    paper: dict,
    semaphore: asyncio.Semaphore,
) -> Optional[dict]:
    """
    按 V14B_ENRICH_PROVIDERS 优先级抓取 enrich 数据。

    Returns:
        enrich result dict (供 write_enrich_result) 或 None
    """
    from echelon.v14b.enrich_providers import fetch_enrich_payload

    async with semaphore:
        result, provider = await fetch_enrich_payload(paper)
        if result and provider:
            logger.debug("enrich ok paper=%s via %s", paper.get("id"), provider)
        return result


def parse_openalex_work(paper_id: str, work: dict) -> dict:
    """
    从 OpenAlex work dict 提取关键字段。

    Returns:
        Dict with keys: updates, references, topics, affiliations
    """
    # 主题层级 (V14-A: T10245 / S3107 / F22 / D3 字符串 ID)
    primary_topic = (work.get("primary_topic") or {})
    subfield = primary_topic.get("subfield") or {}
    field = primary_topic.get("field") or {}
    domain = primary_topic.get("domain") or {}

    topic_id = _oa_id_tail(primary_topic.get("id")) if primary_topic else None
    subfield_id = _oa_id_tail(subfield.get("id")) if subfield else None
    field_id = _oa_id_tail(field.get("id")) if field else None
    domain_id = _oa_id_tail(domain.get("id")) if domain else None

    updates = {
        "paper_id": paper_id,
        "openalex_id": normalize_openalex_work_id(work.get("id")),
        "s2_paper_id": None,
        "cited_by_count": work.get("cited_by_count", 0) or 0,
        "primary_topic_id": topic_id,
        "primary_subfield_id": subfield_id,
        "primary_field_id": field_id,
        "primary_domain_id": domain_id,
    }

    # 引用列表
    references = []
    for ref in (work.get("referenced_works") or []):
        oa_id = ref.split("/")[-1] if isinstance(ref, str) else None
        if oa_id:
            references.append({
                "citing_paper_id": paper_id,
                "cited_paper_id_external": oa_id,
                "cited_paper_id_provider": "openalex",
                "cited_paper_id_norm": oa_id,
            })

    # topics_hierarchy
    topics = []
    for topic_obj in (work.get("topics") or []):
        t_id = _oa_id_tail(topic_obj.get("id"))
        if not t_id:
            continue
        sf = topic_obj.get("subfield") or {}
        fi = topic_obj.get("field") or {}
        do = topic_obj.get("domain") or {}
        topics.append({
            "topic_id": t_id,
            "topic_name": topic_obj.get("display_name"),
            "subfield_id": _oa_id_tail(sf.get("id")) if sf else None,
            "field_id": _oa_id_tail(fi.get("id")) if fi else None,
            "domain_id": _oa_id_tail(do.get("id")) if do else None,
            "subfield_name": sf.get("display_name"),
            "field_name": fi.get("display_name"),
            "domain_name": do.get("display_name"),
        })

    # affiliations
    affiliations = []
    for authorship in (work.get("authorships") or []):
        for inst in (authorship.get("institutions") or []):
            inst_id = inst.get("id", "").split("/")[-1]
            affiliations.append({
                "paper_id": paper_id,
                "institution_id": inst_id,
                "institution_name": inst.get("display_name"),
                "country_code": inst.get("country_code"),
            })

    return {
        "updates": updates,
        "references": references,
        "topics": topics,
        "affiliations": affiliations,
    }


def write_enrich_result(conn: sqlite3.Connection, result: dict) -> None:
    """将 enrich 结果写入 DB"""
    u = result["updates"]

    oid = normalize_openalex_work_id(u.get("openalex_id"))
    s2_id = normalize_s2_paper_id(u.get("s2_paper_id"))
    paper_id = u["paper_id"]
    conn.execute("""
        UPDATE papers SET
            cited_by_count = ?,
            primary_topic_id = COALESCE(?, primary_topic_id),
            primary_subfield_id = COALESCE(?, primary_subfield_id),
            primary_field_id = COALESCE(?, primary_field_id),
            primary_domain_id = COALESCE(?, primary_domain_id),
            openalex_enriched = 1
        WHERE id = ?
    """, (
        u["cited_by_count"],
        u["primary_topic_id"], u["primary_subfield_id"],
        u["primary_field_id"], u["primary_domain_id"],
        paper_id,
    ))

    paper_cols = _table_columns(conn, "papers")
    if oid:
        existing = conn.execute(
            "SELECT id FROM papers WHERE openalex_id = ? AND id != ? LIMIT 1",
            (oid, paper_id),
        ).fetchone()
        if existing is None:
            conn.execute(
                "UPDATE papers SET openalex_id = COALESCE(openalex_id, ?) WHERE id = ?",
                (oid, paper_id),
            )
        else:
            logger.warning(
                "OpenAlex ID collision skipped paper_id=%s openalex_id=%s existing=%s",
                paper_id, oid, existing[0],
            )
    if s2_id and "s2_paper_id" in paper_cols:
        existing = conn.execute(
            "SELECT id FROM papers WHERE s2_paper_id = ? AND id != ? LIMIT 1",
            (s2_id, paper_id),
        ).fetchone()
        if existing is None:
            conn.execute(
                "UPDATE papers SET s2_paper_id = COALESCE(s2_paper_id, ?) WHERE id = ?",
                (s2_id, paper_id),
            )
        else:
            logger.warning(
                "S2 ID collision skipped paper_id=%s s2_paper_id=%s existing=%s",
                paper_id, s2_id, existing[0],
            )

    if result["references"]:
        ref_cols = _table_columns(conn, "paper_references")
        if "cited_paper_id_external" in ref_cols:
            rows = []
            for ref in result["references"]:
                external = ref["cited_paper_id_external"]
                provider = ref.get("cited_paper_id_provider")
                norm = ref.get("cited_paper_id_norm")
                if not provider or not norm:
                    provider, norm = classify_external_id(external)
                rows.append({
                    "citing_paper_id": ref["citing_paper_id"],
                    "cited_paper_id_external": external,
                    "cited_paper_id_provider": provider,
                    "cited_paper_id_norm": norm,
                })
            if {"cited_paper_id_provider", "cited_paper_id_norm"}.issubset(ref_cols):
                conn.executemany("""
                    INSERT OR IGNORE INTO paper_references
                        (citing_paper_id, cited_paper_id_external,
                         cited_paper_id_provider, cited_paper_id_norm)
                    VALUES (:citing_paper_id, :cited_paper_id_external,
                            :cited_paper_id_provider, :cited_paper_id_norm)
                """, rows)
            else:
                conn.executemany("""
                    INSERT OR IGNORE INTO paper_references
                        (citing_paper_id, cited_paper_id_external)
                    VALUES (:citing_paper_id, :cited_paper_id_external)
                """, rows)
        elif "cited_openalex_id" in ref_cols:
            legacy = [
                {
                    "citing_paper_id": r["citing_paper_id"],
                    "cited_openalex_id": r["cited_paper_id_external"],
                }
                for r in result["references"]
            ]
            conn.executemany("""
                INSERT OR IGNORE INTO paper_references
                    (citing_paper_id, cited_openalex_id)
                VALUES (:citing_paper_id, :cited_openalex_id)
            """, legacy)

    if result["topics"]:
        conn.executemany("""
            INSERT OR REPLACE INTO topics_hierarchy
                (topic_id, topic_name, subfield_id, field_id, domain_id,
                 subfield_name, field_name, domain_name)
            VALUES (:topic_id, :topic_name, :subfield_id, :field_id, :domain_id,
                    :subfield_name, :field_name, :domain_name)
        """, result["topics"])

    # V14-A affiliations 为机构主数据表,无 paper_id 列 — 跳过逐篇机构写入
    aff_cols = _table_columns(conn, "affiliations")
    if result["affiliations"] and "paper_id" in aff_cols:
        conn.executemany("""
            INSERT OR IGNORE INTO affiliations
                (paper_id, institution_id, institution_name, country_code)
            VALUES (:paper_id, :institution_id, :institution_name, :country_code)
        """, result["affiliations"])


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

async def run_enrich(
    db_path: Path,
    concurrency: int = CONCURRENCY,
    limit: Optional[int] = None,
    resume: bool = True,
) -> dict:
    """
    执行 Step 1: OpenAlex Enrich。

    Returns:
        统计字典: {total, success, failed, skipped}
    """
    step_name = "step1_enrich"
    ck = Checkpoint(step_name)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    ensure_enrich_tables(conn)
    ensure_library_schema_compat(conn)

    papers = get_unenriched_papers(conn, limit=limit)

    if resume and ck.done() and not papers:
        data = ck.load()
        conn.close()
        logger.info("Step1 已完成 (%d records), 无待处理篇目, 跳过", data.get("records_n", 0))
        return data
    if resume and ck.done() and papers:
        logger.info(
            "Step1 已有 checkpoint, 仍有 %d 篇待 enrich (增量续跑, 如纯 arXiv+S2)",
            len(papers),
        )

    prov = effective_enrich_providers(has_doi=True)
    mode = ",".join(prov) if prov else "none"
    logger.info(
        "待 enrich 论文: %d 篇 | providers=%s | openalex=%s | s2_key=%s",
        len(papers), mode, USE_OPENALEX, bool(SEMANTIC_SCHOLAR_API_KEY),
    )

    semaphore = asyncio.Semaphore(concurrency)
    success = 0
    failed = 0
    batch_size = 50

    with make_progress(range(0, len(papers), batch_size), desc="Enrich batches") as pbar:
        for i in pbar:
            batch = papers[i: i + batch_size]
            tasks = [
                fetch_one(None, p, semaphore)
                for p in batch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for paper, result in zip(batch, results):
                if isinstance(result, Exception) or result is None:
                    has_doi = bool(_clean_doi(paper.get("doi")))
                    if not effective_enrich_providers(has_doi=has_doi):
                        # 无可用数据源, 保持 openalex_enriched=0 待后续配置
                        continue
                    failed += 1
                    # 有 S2/Crossref 仍失败时保持 0, 便于重试; 勿标 -1
                    continue

                try:
                    # fetch_enrich_payload 已返回 {updates, references, topics} 结构
                    if isinstance(result, dict) and "updates" in result:
                        write_enrich_result(conn, result)
                    else:
                        write_enrich_result(
                            conn, parse_openalex_work(paper["id"], result)
                        )
                    success += 1
                except Exception as exc:
                    logger.warning("写入失败 paper_id=%s: %s", paper["id"], exc)
                    failed += 1

            conn.commit()
            link_paper_reference_internals(conn)
            pbar.set_postfix(ok=success, fail=failed)

    link_paper_reference_internals(conn)
    conn.close()

    stats = {
        "total": len(papers),
        "success": success,
        "failed": failed,
        "records_n": success,
    }
    if success > 0:
        ck.mark_done(records_n=success, meta=stats)
    else:
        logger.warning("Step1 无成功记录,不写入 checkpoint (可重跑)")
    logger.info(
        "Step1 完成: total=%d success=%d failed=%d (%.1f%%)",
        len(papers), success, failed,
        100 * success / max(1, len(papers)),
    )
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.step1_enrich",
        description="Step 1: OpenAlex Enrich 13606 篇",
    )
    add_common_args(parser)
    args = parser.parse_args(argv)

    log_level = getattr(logging, args.log_level)
    setup_logging("step1_enrich", level=log_level)

    db_path = Path(args.db) if args.db else DB_MAIN
    limit = args.limit or LIMIT

    asyncio.run(run_enrich(
        db_path=db_path,
        concurrency=args.concurrency or CONCURRENCY,
        limit=limit,
        resume=args.resume,
    ))


if __name__ == "__main__":
    main()
