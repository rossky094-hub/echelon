"""
echelon.crawler.worker
========================
V14 摄入 Worker — 单进程 worker loop。

命令行入口:
    python -m echelon.crawler.worker --provider arxiv --set physics:physics.optics \\
        --from 2024-01-01 --to 2024-01-31 --max 500

支持参数:
    --provider   数据源: arxiv (默认)
    --set        arXiv set spec (默认 physics:physics.optics)
    --from       起始日期 (YYYY-MM-DD)
    --to         截止日期 (YYYY-MM-DD)
    --max        最大拉取数量 (0=不限)
    --db         数据库路径 (默认 db/echelon_library.sqlite3)
    --delay      请求间隔秒数 (默认 3.0)
    --no-enrich  不调 OpenAlex 补元数据
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from echelon.library.db import (
    LIBRARY_DB_PATH,
    get_session,
    get_db_stats,
    get_hwm_v14,
    init_db,
    set_hwm_v14,
    upsert_author,
    upsert_ingestion_job,
    upsert_paper,
    upsert_paper_references,
    link_paper_author,
)
from echelon.library.schema import IngestionJob, JobStatusEnum
from echelon.core.ulid_utils import ulid_new
from echelon.crawler.dedup import find_duplicate
from echelon.v14b.corpus_registry import ensure_corpus_schema, normalize_corpus_id

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 核心摄入逻辑
# ---------------------------------------------------------------------------

async def run_ingestion(
    provider: str,
    query_params: dict,
    job_id: str,
    db_path: str = LIBRARY_DB_PATH,
) -> dict:
    """
    执行一次完整的摄入任务。

    Args:
        provider: 'arxiv' | 'openalex' | 'crossref'
        query_params: {set_spec, from_date, to_date, max_results, delay, enrich}
        job_id: 关联的 ingestion_job ULID
        db_path: 数据库路径

    Returns:
        摘要字典: {papers_ingested, papers_skipped_duplicate, papers_failed, elapsed_seconds}
    """
    from echelon.crawler.arxiv_harvester import (
        ArxivHarvester,
        category_from_set_spec,
    )
    from echelon.crawler.openalex_harvester import OpenAlexHarvester

    start_time = time.time()
    papers_ingested = 0
    papers_refreshed = 0
    papers_skipped = 0
    papers_failed = 0

    # 解析参数
    set_spec = query_params.get("set_spec", "physics:physics:optics")
    from_date_str = query_params.get("from_date")
    to_date_str = query_params.get("to_date")
    max_results = query_params.get("max_results") or None
    request_delay = float(query_params.get("delay", 3.0))
    do_enrich = query_params.get("enrich", False)
    do_refresh = query_params.get("refresh", False)
    harvest_mode = (query_params.get("harvest_mode") or "search").lower()
    corpus_id = query_params.get("corpus_id")

    full_harvest = bool(query_params.get("full_harvest", False))
    backfill_harvest = bool(query_params.get("backfill_harvest", False))
    from_date = date.fromisoformat(from_date_str) if from_date_str else None
    to_date = date.fromisoformat(to_date_str) if to_date_str else None

    if full_harvest:
        from_date = None
        to_date = None
        if harvest_mode == "search":
            logger.info("[worker] 全量模式: cat 搜索 1991→今 (含交叉分类, ~5.6万篇)")
        else:
            logger.info("[worker] 全量模式: 按 OAI set 分页, 无日期过滤")
    elif not from_date:
        hwm = get_hwm_v14(provider, set_spec, db_path)
        from_date = date.fromisoformat(hwm) if hwm else date(2020, 1, 1)
        to_date = to_date or date.today()
        logger.info(f"[worker] 使用 HWM 起始日期: {from_date}")
    else:
        to_date = to_date or date.today()

    logger.info(
        f"[worker] 开始摄入: provider={provider} set={set_spec} mode={harvest_mode} "
        f"from={from_date or 'ALL'} to={to_date or 'ALL'} max={max_results} delay={request_delay}s"
    )

    # 实例化 Harvester
    if provider == "arxiv":
        harvester = ArxivHarvester(request_delay=request_delay)
    elif provider == "openalex":
        harvester = OpenAlexHarvester()
    else:
        raise ValueError(f"未支持的 provider: {provider}")

    # 可选的 OpenAlex enrichment
    oa_harvester = OpenAlexHarvester() if do_enrich else None

    # 摄入循环
    try:
        if provider == "arxiv" and harvest_mode == "search":
            cat = category_from_set_spec(set_spec)
            if backfill_harvest:
                logger.info("[worker] backfill 模式: cat 搜索无日期过滤")
                paper_iter = harvester.fetch_by_category_backfill(
                    category=cat,
                    max_results=max_results,
                )
            else:
                search_from = from_date or date(1991, 1, 1)
                search_to = to_date or date.today()
                paper_iter = harvester.fetch_by_category_search(
                    category=cat,
                    from_date=search_from,
                    to_date=search_to,
                    max_results=max_results,
                )
        else:
            paper_iter = harvester.fetch_by_topic(
                topic_id=set_spec,
                from_date=from_date,
                to_date=to_date,
                max_results=max_results,
            )
        async for paper in paper_iter:
            try:
                # 去重检查
                existing = find_duplicate(paper, db_path)
                if existing:
                    if not do_refresh:
                        papers_skipped += 1
                        continue
                    paper.id = existing["id"]

                # 可选:OpenAlex 补充元数据
                if oa_harvester and (paper.arxiv_id or paper.doi):
                    try:
                        paper = await oa_harvester.enrich_paper(paper)
                    except Exception as e:
                        logger.debug(f"[worker] enrich 失败: {e}")

                # 设置 job_id
                paper.ingestion_job_id = job_id

                # 写入 papers 表
                paper_dict = paper.model_dump(exclude={"authors", "references_external"})
                # 序列化 open_access
                if paper.open_access:
                    paper_dict["open_access"] = paper.open_access.model_dump()
                is_refresh = bool(existing and do_refresh)
                upsert_paper(paper_dict, db_path=db_path, refresh=is_refresh)

                # 写入 authors 表 + paper_authors 关联
                for idx, author in enumerate(paper.authors):
                    author_dict = author.model_dump()
                    upsert_author(author_dict, db_path=db_path)
                    link_paper_author(
                        paper.id, author.id, idx,
                        db_path=db_path
                    )

                # 写入 paper_references 表
                if paper.references_external:
                    upsert_paper_references(
                        paper.id,
                        paper.references_external,
                        db_path=db_path,
                    )

                if is_refresh:
                    papers_refreshed += 1
                else:
                    papers_ingested += 1

                total_done = papers_ingested + papers_refreshed
                # 每 100 篇打印进度
                if total_done % 100 == 0:
                    elapsed = time.time() - start_time
                    rate = total_done / elapsed if elapsed > 0 else 0
                    logger.info(
                        f"[worker] 进度: new={papers_ingested} refreshed={papers_refreshed} "
                        f"skipped={papers_skipped} failed={papers_failed} "
                        f"elapsed={elapsed:.0f}s rate={rate:.1f}/s"
                    )

            except Exception as e:
                papers_failed += 1
                logger.warning(f"[worker] 单篇处理失败: {e}")
                continue

    except Exception as e:
        logger.error(f"[worker] Harvester 异常: {e}", exc_info=True)
        raise

    # 更新 HWM
    set_hwm_v14(
        provider=provider,
        topic_id=set_spec,
        last_date=to_date.isoformat(),
        db_path=db_path,
    )

    elapsed = time.time() - start_time
    if corpus_id:
        cid = normalize_corpus_id(str(corpus_id))
        with get_session(db_path) as db:
            ensure_corpus_schema(db)
            db.execute(
                """
                INSERT OR IGNORE INTO paper_corpora
                    (paper_id, corpus_id, assigned_at, assignment_source, score)
                SELECT id, ?, CURRENT_TIMESTAMP, 'crawler_ingest_job', NULL
                FROM papers
                WHERE ingestion_job_id = ?
                """,
                (cid, job_id),
            )
            db.execute(
                """
                UPDATE papers
                SET corpus_id = COALESCE(corpus_id, ?)
                WHERE ingestion_job_id = ?
                """,
                (cid, job_id),
            )

    result = {
        "papers_ingested": papers_ingested,
        "papers_refreshed": papers_refreshed,
        "papers_skipped_duplicate": papers_skipped,
        "papers_failed": papers_failed,
        "elapsed_seconds": round(elapsed, 1),
        "provider": provider,
        "set_spec": set_spec,
        "from_date": str(from_date),
        "to_date": str(to_date),
        "corpus_id": corpus_id,
    }
    logger.info(f"[worker] 摄入完成: {result}")
    return result


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------

def main():
    """命令行 Worker 入口"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )

    parser = argparse.ArgumentParser(
        description="Echelon V14 摄入 Worker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # Step A: 验证 2024-01 单月
  python -m echelon.crawler.worker --provider arxiv --set physics:physics.optics \\
      --from 2024-01-01 --to 2024-01-31 --max 500

  # Step B: 近 6 个月
  python -m echelon.crawler.worker --provider arxiv --set physics:physics.optics \\
      --from 2025-11-01 --to 2026-05-12

  # Step C: 近 2 年全量
  python -m echelon.crawler.worker --provider arxiv --set physics:physics.optics \\
      --from 2024-01-01 --to 2026-05-12

  # Step D (全史,后台 nohup):
  nohup python -m echelon.crawler.worker --provider arxiv \\
      --set physics:physics.optics --from 1991-01-01 > logs/arxiv-full.log 2>&1 &
        """
    )
    parser.add_argument("--provider", default="arxiv",
                        choices=["arxiv", "openalex", "crossref"],
                        help="数据源提供方 (默认: arxiv)")
    parser.add_argument("--set", dest="set_spec", default="physics:physics:optics",
                        help="arXiv OAI setSpec (默认: physics:physics:optics)")
    parser.add_argument("--refresh", action="store_true", default=False,
                        help="已存在论文也按 arXiv 元数据更新(全量重抓时用)")
    parser.add_argument("--full", action="store_true", default=False,
                        help="全史拉取: search=1991至今, oai=无日期过滤")
    parser.add_argument("--backfill", action="store_true", default=False,
                        help="search 模式: cat: 无日期过滤补缺 (日期 crawl 完成后)")
    parser.add_argument("--mode", dest="harvest_mode", default="search",
                        choices=["search", "oai"],
                        help="arxiv 抓取模式: search=cat:physics.optics ~5.6万; oai=set ~1.3万")
    parser.add_argument("--from", dest="from_date", default=None,
                        help="起始日期 YYYY-MM-DD (默认: 从 HWM 读取)")
    parser.add_argument("--to", dest="to_date", default=None,
                        help="截止日期 YYYY-MM-DD (默认: 今天)")
    parser.add_argument("--max", dest="max_results", type=int, default=0,
                        help="最大拉取数量 (0=不限, 默认: 0)")
    parser.add_argument("--db", dest="db_path", default=LIBRARY_DB_PATH,
                        help=f"数据库路径 (默认: {LIBRARY_DB_PATH})")
    parser.add_argument("--delay", dest="delay", type=float, default=3.0,
                        help="请求间隔秒数 (默认: 3.0)")
    parser.add_argument("--enrich", action="store_true", default=False,
                        help="调 OpenAlex 补充元数据")
    parser.add_argument("--stats", action="store_true", default=False,
                        help="完成后打印数据库统计")
    parser.add_argument("--corpus-id", default=None,
                        help="写入 paper_corpora 的 corpus_id (如 optics/cs/materials)")

    args = parser.parse_args()

    # 初始化数据库
    logger.info(f"[worker] 初始化数据库: {args.db_path}")
    init_db(args.db_path)

    # 构建查询参数
    query_params = {
        "set_spec": args.set_spec,
        "from_date": args.from_date,
        "to_date": None if args.full else (args.to_date or date.today().isoformat()),
        "max_results": args.max_results if args.max_results > 0 else None,
        "delay": args.delay,
        "enrich": args.enrich,
        "refresh": args.refresh,
        "full_harvest": args.full,
        "backfill_harvest": args.backfill,
        "harvest_mode": args.harvest_mode,
        "corpus_id": args.corpus_id,
    }

    # 创建任务记录
    job_id = ulid_new()
    upsert_ingestion_job(
        {
            "job_id": job_id,
            "provider": args.provider,
            "query_params": query_params,
            "status": JobStatusEnum.RUNNING,
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
        db_path=args.db_path,
    )

    print(f"\n=== Echelon V14 摄入 Worker ===")
    print(f"provider  : {args.provider}")
    print(f"set spec  : {args.set_spec}")
    print(f"mode      : {query_params['harvest_mode']}")
    print(f"full      : {query_params['full_harvest']}")
    print(f"from      : {query_params['from_date'] or ('(ALL)' if query_params['full_harvest'] else '(HWM)')}")
    print(f"to        : {query_params['to_date'] or '(ALL)'}")
    print(f"max       : {query_params['max_results'] or '无限'}")
    print(f"delay     : {args.delay}s/请求")
    print(f"refresh   : {args.refresh}")
    print(f"db        : {args.db_path}")
    print(f"corpus_id : {args.corpus_id or '(none)'}")
    print(f"job_id    : {job_id}")
    print(f"启动时间  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 40 + "\n")

    # 运行摄入
    try:
        result = asyncio.run(
            run_ingestion(args.provider, query_params, job_id, args.db_path)
        )

        # 更新任务为完成
        upsert_ingestion_job(
            {
                "job_id": job_id,
                "provider": args.provider,
                "query_params": query_params,
                "status": JobStatusEnum.DONE,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "papers_ingested": result["papers_ingested"],
                "papers_skipped_duplicate": result["papers_skipped_duplicate"],
            },
            db_path=args.db_path,
        )

        print(f"\n=== 摄入完成 ===")
        print(f"摄入论文数   : {result['papers_ingested']}")
        print(f"更新已有     : {result.get('papers_refreshed', 0)}")
        print(f"跳过重复     : {result['papers_skipped_duplicate']}")
        print(f"失败         : {result['papers_failed']}")
        print(f"耗时         : {result['elapsed_seconds']}s")
        print(f"速率         : {result['papers_ingested'] / max(result['elapsed_seconds'], 1):.1f} 篇/s")

        if args.stats:
            stats = get_db_stats(args.db_path)
            print(f"\n=== 数据库统计 ===")
            for k, v in stats.items():
                print(f"  {k:30s}: {v}")

    except KeyboardInterrupt:
        print("\n[worker] 用户中断,任务中止")
        upsert_ingestion_job(
            {
                "job_id": job_id,
                "provider": args.provider,
                "query_params": query_params,
                "status": JobStatusEnum.FAILED,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error_log": "KeyboardInterrupt",
            },
            db_path=args.db_path,
        )
        sys.exit(1)
    except Exception as e:
        logger.error(f"[worker] 摄入异常: {e}", exc_info=True)
        upsert_ingestion_job(
            {
                "job_id": job_id,
                "provider": args.provider,
                "query_params": query_params,
                "status": JobStatusEnum.FAILED,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error_log": str(e)[:2000],
            },
            db_path=args.db_path,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
