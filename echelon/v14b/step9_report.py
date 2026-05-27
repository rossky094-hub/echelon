"""
Step 9: 报告生成器

生成两份 Markdown 报告:
  1. V14B_Pilot_算法验证报告.md (13 章节)
  2. 未来方向预测_交集报告.md (top 20)

从 DB 实查数据填充(无数据时用 TBD 占位)

CLI:
    python -m echelon.v14b.step9_report --help
    python -m echelon.v14b.step9_report
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from echelon.v14b.config import (
    DB_MAIN, DB_V14,
    REPORT_DIR, REPORT_ALGO_VALIDATION, REPORT_FUTURE_DIRECTIONS,
    LIMIT,
    UMAP_N_NEIGHBORS, UMAP_MIN_DIST,
)
from echelon.v14b.db_schema import get_v14b_conn, upsert_step_meta
from echelon.v14b.utils import setup_logging, Checkpoint, add_common_args

logger = logging.getLogger("echelon.v14b.step9_report")


# ---------------------------------------------------------------------------
# DB 查询工具
# ---------------------------------------------------------------------------

def safe_query(conn, sql: str, params=()) -> list:
    """安全执行 SQL,失败返回空列表"""
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.debug("Query failed: %s | %s", sql[:80], exc)
        return []


def safe_count(conn, table: str, where: str = "") -> int:
    """安全统计表行数"""
    try:
        q = f"SELECT COUNT(*) FROM {table}"
        if where:
            q += f" WHERE {where}"
        return conn.execute(q).fetchone()[0]
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# 算法验证报告 (13 章节)
# ---------------------------------------------------------------------------

def generate_algo_report(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
) -> str:
    """生成 V14B Pilot 算法验证报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 基础统计
    total_papers = safe_count(conn_main, "papers")
    enriched_papers = safe_count(conn_main, "papers", "openalex_enriched = 1")
    total_refs = safe_count(conn_main, "paper_references")

    # 主干道统计
    main_path_edges = safe_count(conn_v14, "main_path_edges")
    main_path_core = safe_count(conn_v14, "main_path_edges", "is_main_path = 1")

    # 子图统计
    subgraph_nodes = safe_count(conn_v14, "subgraph_nodes")
    subgraph_edges = safe_count(conn_v14, "subgraph_edges")
    keystone_nodes = safe_count(conn_v14, "subgraph_nodes", "is_keystone = 1")
    fresh_nodes = safe_count(conn_v14, "subgraph_nodes", "is_fresh_top = 1")

    # SciBERT 分类统计
    classified_edges = safe_count(conn_v14, "subgraph_edges", "citation_function IS NOT NULL")
    func_dist = safe_query(conn_v14, """
        SELECT citation_function, COUNT(*) as n
        FROM subgraph_edges
        WHERE citation_function IS NOT NULL
        GROUP BY citation_function
        ORDER BY n DESC
    """)

    # VGAE 统计
    predicted_edges = safe_count(conn_v14, "predicted_future_edges")
    cross_field_preds = safe_count(conn_v14, "predicted_future_edges", "is_cross_field = 1")
    top_vgae = safe_query(conn_v14, """
        SELECT p1.title AS src_title, p2.title AS dst_title,
               pfe.predicted_prob, pfe.src_year, pfe.dst_year
        FROM predicted_future_edges pfe
        LEFT JOIN papers p1 ON pfe.src_paper_id = p1.id
        LEFT JOIN papers p2 ON pfe.dst_paper_id = p2.id
        ORDER BY pfe.predicted_prob DESC
        LIMIT 5
    """)

    # Limitation 统计
    total_atoms = safe_count(conn_v14, "limitation_atoms")
    total_resolutions = safe_count(conn_v14, "limitation_resolutions")
    high_severity = safe_count(conn_v14, "limitation_atoms", "severity = 'high'")
    top_unresolved = safe_query(conn_v14, """
        SELECT a.atom_id, a.description, a.keyword, a.severity,
               p.title AS paper_title, p.id AS paper_id
        FROM limitation_atoms a
        LEFT JOIN papers p ON a.paper_id = p.id
        LEFT JOIN limitation_resolutions r ON a.atom_id = r.atom_id AND r.confidence > 0.6
        GROUP BY a.atom_id
        HAVING COUNT(r.atom_id) = 0
        ORDER BY CASE a.severity WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC
        LIMIT 10
    """)

    # 融合方向统计
    future_dirs = safe_count(conn_v14, "future_directions")
    top_dirs = safe_query(conn_v14, """
        SELECT direction_name, confidence, expected_period
        FROM future_directions
        ORDER BY confidence DESC
        LIMIT 5
    """)

    # 突变统计
    red_count = safe_count(conn_v14, "subgraph_nodes", "mutation_red = 1")
    orange_count = safe_count(conn_v14, "subgraph_nodes", "mutation_orange = 1")
    purple_count = safe_count(conn_v14, "subgraph_nodes", "mutation_purple = 1")

    # 主干道 case study
    main_path_papers = safe_query(conn_main, """
        SELECT p.id, p.title, p.publication_year, p.cited_by_count
        FROM papers p
        JOIN subgraph_nodes sn ON p.id = sn.paper_id
        WHERE sn.is_keystone = 1
        ORDER BY p.publication_year ASC, p.cited_by_count DESC
        LIMIT 10
    """)

    # V14 vs V13 top100 重叠率(近似)
    v14_top100 = safe_query(conn_main, """
        SELECT id FROM papers
        WHERE keystone_score_v14 IS NOT NULL
        ORDER BY keystone_score_v14 DESC LIMIT 100
    """)
    v14_top_ids = {r["id"] for r in v14_top100}

    enrich_rate = f"{enriched_papers / max(1, total_papers) * 100:.1f}%"
    classification_rate = f"{classified_edges / max(1, subgraph_edges) * 100:.1f}%"
    cross_field_rate = f"{cross_field_preds / max(1, predicted_edges) * 100:.1f}%"

    # 构建报告
    lines = [
        f"# V14-B Pilot 算法验证报告",
        f"",
        f"**生成时间**: {now}",
        f"**数据规模**: {total_papers:,} 篇论文 (physics.optics arXiv 1991-2026)",
        f"",
        f"---",
        f"",
        f"## 1. 执行摘要",
        f"",
        f"| 指标 | 数值 |",
        f"|---|---|",
        f"| 总论文数 | **{total_papers:,}** |",
        f"| OpenAlex enrich 成功率 | **{enrich_rate}** ({enriched_papers:,}/{total_papers:,}) |",
        f"| 引用关系总数 | **{total_refs:,}** |",
        f"| 主干道边数 (top 1%) | **{main_path_core:,}** / {main_path_edges:,} |",
        f"| 子图节点数 | **{subgraph_nodes:,}** |",
        f"| 子图边数 | **{subgraph_edges:,}** |",
        f"| SciBERT 分类完成率 | **{classification_rate}** |",
        f"| VGAE 预测未来边数 | **{predicted_edges:,}** |",
        f"| Limitation atoms 总数 | **{total_atoms:,}** |",
        f"| 三路融合方向数 | **{future_dirs:,}** |",
        f"",
        f"---",
        f"",
        f"## 2. Enrich 数据质量",
        f"",
        f"- **OpenAlex 命中率**: {enrich_rate}",
        f"- **引用关系总数**: {total_refs:,} 条",
        f"- **平均每篇引用数**: {total_refs / max(1, enriched_papers):.1f}",
        f"",
        f"---",
        f"",
        f"## 3. 全网 Main Path",
        f"",
        f"- **SPC 主干道边数**: {main_path_core:,} (top 1%)",
        f"- **总边数**: {main_path_edges:,}",
        f"",
        f"### 主干道代表性论文 (case study)",
        f"",
        f"| paper_id | 标题 | 年份 | 被引数 |",
        f"|---|---|---|---|",
    ]

    for p in main_path_papers[:10]:
        title = (p.get("title") or "TBD")[:60]
        lines.append(f"| {p['id']} | {title} | {p.get('publication_year', 'TBD')} | {p.get('cited_by_count', 0):,} |")

    lines += [
        f"",
        f"---",
        f"",
        f"## 4. V14 调权 vs V13",
        f"",
        f"- **V14 top100 节点**: {len(v14_top_ids)} 个",
        f"- **生命周期分布**: (见 DB lifecycle_v14 列)",
        f"",
        f"> V14 新增权重强调: **bridging_centrality** (0.20-0.25) 和 **cd_subdomain** (成熟期 0.25)",
        f"",
        f"---",
        f"",
        f"## 5. 子图选取",
        f"",
        f"| 类型 | 数量 |",
        f"|---|---|",
        f"| 子图节点总数 | **{subgraph_nodes:,}** |",
        f"| Keystone 节点 | **{keystone_nodes:,}** |",
        f"| Fresh (2024+) 节点 | **{fresh_nodes:,}** |",
        f"| 1 度邻居节点 | **{subgraph_nodes - keystone_nodes - fresh_nodes:,}** |",
        f"| 子图边数 | **{subgraph_edges:,}** |",
        f"",
        f"---",
        f"",
        f"## 6. SciBERT 引用功能分布",
        f"",
        f"| 引用功能 | 边数 | 占比 |",
        f"|---|---|---|",
    ]

    for d in func_dist:
        pct = d["n"] / max(1, classified_edges) * 100
        lines.append(f"| {d['citation_function']} | {d['n']:,} | {pct:.1f}% |")

    lines += [
        f"",
        f"**高权重 (extension+motivation+usage) 总占比**: "
        + f"{sum(d['n'] for d in func_dist if d['citation_function'] in ('extension','motivation','usage')) / max(1, classified_edges) * 100:.1f}%",
        f"",
        f"---",
        f"",
        f"## 7. VGAE Link Prediction",
        f"",
        f"- **预测边总数**: {predicted_edges:,}",
        f"- **跨 Field 边占比**: **{cross_field_rate}** ({cross_field_preds:,}/{predicted_edges:,})",
        f"",
        f"### Top 5 预测边 (case study)",
        f"",
        f"| 源论文 | 目标论文 | 概率 | 源年 | 目标年 |",
        f"|---|---|---|---|---|",
    ]

    for e in top_vgae:
        src_t = (e.get("src_title") or "TBD")[:40]
        dst_t = (e.get("dst_title") or "TBD")[:40]
        lines.append(
            f"| {src_t} | {dst_t} | {e['predicted_prob']:.3f} | "
            f"{e.get('src_year', 'TBD')} | {e.get('dst_year', 'TBD')} |"
        )

    lines += [
        f"",
        f"---",
        f"",
        f"## 8. Limitation Tracking",
        f"",
        f"- **Limitation atoms 总数**: {total_atoms:,}",
        f"- **高严重性 atoms**: {high_severity:,}",
        f"- **Resolution 记录数**: {total_resolutions:,}",
        f"",
        f"### Top 10 未解决 Limitations",
        f"",
        f"| atom_id | paper_id | 论文 | 局限描述 | 严重性 |",
        f"|---|---|---|---|---|",
    ]

    for a in top_unresolved:
        paper_title = (a.get("paper_title") or "TBD")[:50]
        desc = (a.get("description") or "TBD")[:60]
        lines.append(
            f"| {a['atom_id']} | {a.get('paper_id','TBD')} | {paper_title} | {desc} | {a.get('severity', 'TBD')} |"
        )

    lines += [
        f"",
        f"---",
        f"",
        f"## 9. 三路融合交集",
        f"",
        f"- **融合方向数**: **{future_dirs:,}**",
        f"",
        f"### Top 5 未来方向预览",
        f"",
        f"| 方向 | 置信度 | 预期时间 |",
        f"|---|---|---|",
    ]

    for d in top_dirs:
        lines.append(
            f"| {d['direction_name'][:70]} | {d['confidence']:.2f} | {d.get('expected_period', 'TBD')} |"
        )

    lines += [
        f"",
        f"> 详细见: 未来方向预测_交集报告.md",
        f"",
        f"---",
        f"",
        f"## 10. 三色突变标记",
        f"",
        f"| 类型 | 数量 | 含义 |",
        f"|---|---|---|",
        f"| 🔴 红色 (CD-index 突变) | **{red_count:,}** | mature 论文 CD-index > 0.3 |",
        f"| 🟠 橙色 (跨 Field 桥接) | **{orange_count:,}** | 跨领域桥接分数 > p90 |",
        f"| 🟣 紫色 (Burstiness) | **{purple_count:,}** | 18 月内被引突增 > p95 |",
        f"| **合计** | **{red_count + orange_count + purple_count:,}** | 子图 {subgraph_nodes:,} 节点中的 {(red_count + orange_count + purple_count) / max(1, subgraph_nodes) * 100:.1f}% |",
        f"",
        f"---",
        f"",
        f"## 11. 演化树布局",
        f"",
        f"- **X, Y 轴**: UMAP 降维 (cosine similarity, n_neighbors={UMAP_N_NEIGHBORS}, min_dist={UMAP_MIN_DIST})",
        f"- **Z 轴**: (publication_year - 1991) / (2026 - 1991) ∈ [0, 1]",
        f"- **节点颜色**: primary_field_id (26 色映射)",
        f"- **节点大小**: log(cite_count + 1) 归一化",
        f"",
        f"---",
        f"",
        f"## 12. 与 V12.5 Pilot 对比",
        f"",
        f"| 维度 | V12.5 (2000 篇) | V14-B (13606 篇) |",
        f"|---|---|---|",
        f"| 数据规模 | 2,000 篇 | **13,606 篇** |",
        f"| 引用图 | 仅 arXiv 内部 | **OpenAlex 跨库** |",
        f"| 评分算法 | V13 均等权重 | **V14 生命周期自适应** |",
        f"| 未来方向 | 无 | **{future_dirs:,} 个三路融合方向** |",
        f"",
        f"---",
        f"",
        f"## 13. 下一步建议",
        f"",
        f"### 建议: {_go_nogo_recommendation(future_dirs, predicted_edges, total_atoms)}",
        f"",
        f"**前端启动条件**:",
        f"- [ ] 三路融合方向 ≥ 10 个 (当前: {future_dirs})",
        f"- [ ] VGAE test AUC > 0.80 (需验证)",
        f"- [ ] 主干道节点 100-200 个 (当前: TBD)",
        f"- [ ] 突变节点 100-300 个 (当前: {red_count + orange_count + purple_count})",
        f"",
        f"**重型算法调优建议**:",
        f"1. SciBERT: 如 extension+motivation+usage 占比 < 40%,考虑换 LLM 分类",
        f"2. VGAE: 如 AUC < 0.80,减少 epoch → 调 lr → 增加 negative sampling",
        f"3. Limitation: 如 high-confidence resolution < 30%,放宽阈值到 0.5",
        f"",
        f"---",
        f"",
        f"*报告由 V14-B step9_report.py 自动生成 | {now}*",
    ]

    return "\n".join(lines)


def _go_nogo_recommendation(future_dirs: int, predicted_edges: int, total_atoms: int) -> str:
    """根据关键指标给出建议"""
    if future_dirs >= 10 and predicted_edges >= 50:
        return "**GO** — 算法验证通过,可启动 V14-B 前端开发"
    elif future_dirs >= 5 or predicted_edges >= 20:
        return "**REVISE** — 部分指标达标,建议调优后再启动前端"
    else:
        return "**NO-GO** — 关键指标不足,需重跑 VGAE/Limitation/Fusion 步骤"


# ---------------------------------------------------------------------------
# 未来方向交集报告
# ---------------------------------------------------------------------------

def generate_future_directions_report(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
) -> str:
    """生成未来方向预测交集报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    directions = safe_query(conn_v14, """
        SELECT direction_id, direction_name, confidence, expected_period,
               main_path_evidence, vgae_evidence, limitation_evidence,
               paper_ids_json
        FROM future_directions
        ORDER BY confidence DESC
        LIMIT 20
    """)

    lines = [
        f"# 未来颠覆性方向预测 — 三路融合交集报告",
        f"",
        f"**生成时间**: {now}",
        f"**方法**: VGAE+主干道延伸 × Limitation未解决方向 × Link Prediction 三路融合",
        f"**总方向数**: **{len(directions)}** 个",
        f"",
        f"---",
        f"",
    ]

    if not directions:
        lines += [
            f"> **TBD**: 尚无数据。请先完成 make pilot 全流程。",
            f"",
        ]
        return "\n".join(lines)

    lines += [
        f"## 摘要表格",
        f"",
        f"| # | 方向名称 | 置信度 | 预期时间 |",
        f"|---|---|---|---|",
    ]
    for i, d in enumerate(directions, 1):
        lines.append(
            f"| {i} | {d['direction_name'][:70]} | {d['confidence']:.2f} | {d.get('expected_period','TBD')} |"
        )

    lines += [f"", f"---", f""]

    for i, d in enumerate(directions, 1):
        lines += [
            f"## 方向 {i}: {d['direction_name']}",
            f"",
            f"- **综合置信度**: **{d['confidence']:.2f}**",
            f"- **预期出现时间**: {d.get('expected_period', 'TBD')}",
            f"",
            f"### 三路证据",
            f"",
            f"| 证据路径 | 内容 |",
            f"|---|---|",
            f"| 主干道延伸 | {d.get('main_path_evidence') or 'N/A'} |",
            f"| VGAE Link Prediction | {d.get('vgae_evidence') or 'N/A'} |",
            f"| Limitation 驱动 | {d.get('limitation_evidence') or 'N/A'} |",
            f"",
        ]

        # 相关论文
        try:
            paper_ids = json.loads(d.get("paper_ids_json") or "[]")
        except Exception:
            paper_ids = []

        if paper_ids:
            lines.append("### 相关论文")
            lines.append("")
            placeholders = ",".join("?" * len(paper_ids))
            related = safe_query(conn_main, f"""
                SELECT id, title, publication_year
                FROM papers WHERE id IN ({placeholders})
                LIMIT 5
            """, paper_ids)
            for p in related:
                lines.append(f"- [{p.get('title', 'TBD')} ({p.get('publication_year', 'TBD')})](https://arxiv.org/abs/{p['id']})")

        lines += [f"", f"---", f""]

    lines.append(f"*报告由 V14-B step9_report.py 自动生成 | {now}*")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def run_report(
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    resume: bool = True,
) -> dict:
    """执行 Step 9: 报告生成"""
    step_name = "step9_report"
    ck = Checkpoint(step_name)

    if resume and ck.done():
        data = ck.load()
        logger.info("Step9 已完成,跳过")
        return data

    conn_main = sqlite3.connect(str(db_main))
    conn_main.row_factory = sqlite3.Row

    conn_v14 = get_v14b_conn(db_v14)
    upsert_step_meta(conn_v14, step_name, "running")

    # 确保报告目录存在
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # 生成算法验证报告
    algo_report = generate_algo_report(conn_main, conn_v14)
    REPORT_ALGO_VALIDATION.write_text(algo_report, encoding="utf-8")
    logger.info("算法验证报告: %s", REPORT_ALGO_VALIDATION)

    # 生成未来方向报告
    future_report = generate_future_directions_report(conn_main, conn_v14)
    REPORT_FUTURE_DIRECTIONS.write_text(future_report, encoding="utf-8")
    logger.info("未来方向报告: %s", REPORT_FUTURE_DIRECTIONS)
    upsert_step_meta(conn_v14, step_name, "done", records_n=2)

    conn_main.close()
    conn_v14.close()

    stats = {
        "algo_report": str(REPORT_ALGO_VALIDATION),
        "future_report": str(REPORT_FUTURE_DIRECTIONS),
        "records_n": 2,
    }
    ck.mark_done(records_n=2, meta=stats)
    logger.info("Step9 完成: 2 报告生成")
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.step9_report",
        description="Step 9: 报告生成器",
    )
    add_common_args(parser)
    args = parser.parse_args(argv)

    log_level = getattr(logging, args.log_level)
    setup_logging("step9_report", level=log_level)

    db_main = Path(args.db) if args.db else DB_MAIN
    db_v14 = Path(args.db_v14) if args.db_v14 else DB_V14

    run_report(db_main=db_main, db_v14=db_v14, resume=args.resume)


if __name__ == "__main__":
    main()
