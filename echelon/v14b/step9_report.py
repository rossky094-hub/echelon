"""
Step 9: 报告生成器

生成两份 Markdown 报告:
  1. V14B_Pilot_算法验证报告.md (legacy filename; current Evidence Decision report)
  2. 未来候选方向_证据合同报告.md (top 20)

从 DB 实查数据填充(无数据时用 TBD 占位)

CLI:
    python -m echelon.v14b.step9_report --help
    python -m echelon.v14b.step9_report
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from echelon.v14b.corpus_registry import create_temp_corpus_table, ensure_corpus_schema
from echelon.v14b.config import (
    DB_MAIN, DB_V14,
    REPORT_DIR, REPORT_ALGO_VALIDATION, REPORT_FUTURE_DIRECTIONS,
    LIMIT,
    UMAP_N_NEIGHBORS, UMAP_MIN_DIST,
)
from echelon.v14b.db_schema import get_v14b_conn, upsert_step_meta
from echelon.v14b.utils import setup_logging, Checkpoint, add_common_args

logger = logging.getLogger("echelon.v14b.step9_report")


ARXIV_ID_RE = re.compile(r"^\d{4}\.\d{4,5}(?:v\d+)?$", re.IGNORECASE)


def _normalise_arxiv_id(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    raw = str(value).strip()
    raw = raw.removeprefix("arXiv:").removeprefix("arxiv:")
    raw = raw.removeprefix("https://arxiv.org/abs/")
    raw = raw.removeprefix("http://arxiv.org/abs/")
    raw = raw.removeprefix("https://arxiv.org/pdf/")
    raw = raw.removeprefix("http://arxiv.org/pdf/")
    raw = raw.removesuffix(".pdf")
    return raw if ARXIV_ID_RE.match(raw) else None


def _paper_reference_markdown(paper: dict) -> str:
    title = paper.get("title") or paper.get("id") or "TBD"
    year = paper.get("publication_year") or "TBD"
    label = f"{title} ({year})"
    arxiv_id = _normalise_arxiv_id(paper.get("arxiv_id"))
    doi = (paper.get("doi") or "").strip()
    if arxiv_id:
        return f"[{label}](https://arxiv.org/abs/{arxiv_id})"
    if doi:
        return f"[{label}](https://doi.org/{doi})"
    return f"{label} — local_id: `{paper.get('id', 'TBD')}`"


def _loads_json(value, default):
    if value is None:
        return default
    try:
        return json.loads(str(value))
    except Exception:
        return default


def _future_candidate_evidence_text(value: object) -> str:
    text = str(value or "N/A")
    return text.replace("VGAE pred:", "GNN/VGAE candidate edge:")


def _direction_contract(direction: dict) -> dict:
    evidence = _loads_json(direction.get("evidence_json"), {})
    quality_gate = _loads_json(direction.get("quality_gate_json"), {})
    five_questions = quality_gate.get("five_questions") if isinstance(quality_gate, dict) else {}
    missing_gates = list(quality_gate.get("missing_gates") or []) if isinstance(quality_gate, dict) else []
    missing_high_conf = (
        list(quality_gate.get("missing_high_confidence_gates") or [])
        if isinstance(quality_gate, dict)
        else []
    )
    claim_card_complete = bool(direction.get("claim_card_complete"))
    high_confidence = bool(direction.get("high_confidence_eligible"))
    claim_scope = (
        direction.get("claim_scope")
        or (evidence.get("claim_scope") if isinstance(evidence, dict) else None)
        or ("exploratory_with_claim_card" if claim_card_complete else "candidate_pool_only")
    )
    evidence_grade = (
        direction.get("evidence_tier")
        or (quality_gate.get("section_evidence_strength") if isinstance(quality_gate, dict) else None)
        or "metadata_or_algorithmic_candidate"
    )
    uncertainty_reasons: list[str] = []
    if not claim_card_complete:
        uncertainty_reasons.append("Claim Card five-question contract incomplete")
    if missing_gates:
        uncertainty_reasons.extend(f"missing {gate}" for gate in missing_gates[:3])
    if not high_confidence:
        uncertainty_reasons.append("not high-confidence eligible")
    if missing_high_conf:
        uncertainty_reasons.extend(f"missing high-confidence gate: {gate}" for gate in missing_high_conf[:4])
    if direction.get("calibration_label") != "calibrated_temporal_holdout":
        uncertainty_reasons.append("future candidate lacks run-level temporal calibration label")
    if claim_scope in {"candidate_pool_only", "exploratory_incomplete_card", "not_for_user_claim"}:
        uncertainty_reasons.append("candidate pool only; not Radar main-view evidence")
    if not uncertainty_reasons:
        uncertainty_reasons.append("requires human validation and quarterly snapshot comparison")
    promotion_status = (
        "exploratory_claim_card"
        if claim_card_complete and str(claim_scope).startswith("exploratory")
        else "candidate_pool_only"
    )
    return {
        "claim_scope": claim_scope,
        "evidence_grade": evidence_grade,
        "uncertainty_reasons": uncertainty_reasons,
        "promotion_status": promotion_status,
        "claim_card_complete": claim_card_complete,
        "high_confidence_eligible": high_confidence,
        "five_questions": five_questions if isinstance(five_questions, dict) else {},
    }


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


def safe_scalar(conn, sql: str, params=()) -> int:
    try:
        row = conn.execute(sql, params).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


def table_columns(conn, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# 算法验证报告 (13 章节)
# ---------------------------------------------------------------------------

def generate_algo_report(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    *,
    corpus_id: str | None = None,
) -> str:
    """生成 V14B Pilot 算法验证报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    scope = "id IN (SELECT paper_id FROM temp.v14b_corpus_papers)" if corpus_id else "1=1"
    corpus_label = corpus_id or "all"

    # 基础统计
    total_papers = safe_count(conn_main, "papers", scope)
    enriched_papers = safe_count(conn_main, "papers", f"{scope} AND openalex_enriched = 1")
    openalex_w = safe_count(
        conn_main,
        "papers",
        f"{scope} AND (openalex_id LIKE 'W%' OR openalex_id LIKE 'https://openalex.org/W%')",
    )
    field_papers = safe_count(
        conn_main,
        "papers",
        f"{scope} AND primary_field_id IS NOT NULL AND trim(primary_field_id) <> ''",
    )
    total_refs = safe_scalar(
        conn_main,
        f"""
        SELECT COUNT(*)
        FROM paper_references
        WHERE citing_paper_id IN (
            SELECT id FROM papers WHERE {scope}
        )
        """,
    )

    # 主干道统计
    main_path_edges = safe_count(conn_v14, "main_path_edges")
    main_path_core = safe_count(conn_v14, "main_path_edges", "is_main_path = 1")

    # 子图统计
    subgraph_nodes = safe_count(conn_v14, "subgraph_nodes")
    subgraph_edges = safe_count(conn_v14, "subgraph_edges")
    keystone_nodes = safe_count(conn_v14, "subgraph_nodes", "is_keystone = 1")
    fresh_nodes = safe_count(conn_v14, "subgraph_nodes", "is_fresh_top = 1")

    # Citation-function evidence statistics.  The default classifier is a
    # deterministic weak-evidence layer; do not present it as a SciBERT model
    # conclusion.
    classified_edges = safe_count(conn_v14, "subgraph_edges", "citation_function IS NOT NULL")
    func_dist = safe_query(conn_v14, """
        SELECT citation_function, COUNT(*) as n
        FROM subgraph_edges
        WHERE citation_function IS NOT NULL
        GROUP BY citation_function
        ORDER BY n DESC
    """)
    citation_evidence = safe_query(conn_v14, """
        SELECT citation_function_evidence_level AS level,
               COUNT(*) AS n,
               AVG(COALESCE(citation_function_weight, 0)) AS avg_weight
        FROM subgraph_edges
        WHERE citation_function IS NOT NULL
        GROUP BY citation_function_evidence_level
        ORDER BY n DESC
    """)
    subgraph_scope = safe_query(conn_v14, """
        SELECT *
        FROM subgraph_scope_audit
        ORDER BY created_at DESC
        LIMIT 1
    """)
    subgraph_scope_row = subgraph_scope[0] if subgraph_scope else {}

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
    direction_cols = table_columns(conn_v14, "future_directions")
    direction_preview_cols = [
        "direction_name",
        "confidence",
        "expected_period",
        "evidence_tier",
        "claim_scope",
        "calibration_label",
        "evidence_json",
        "claim_card_complete",
        "high_confidence_eligible",
        "quality_gate_json",
    ]
    top_dir_select = [
        col if col in direction_cols else f"NULL AS {col}"
        for col in direction_preview_cols
    ]
    top_dirs = safe_query(conn_v14, f"""
        SELECT {', '.join(top_dir_select)}
        FROM future_directions
        ORDER BY confidence DESC
        LIMIT 5
    """) if direction_cols else []

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
    v14_top100 = safe_query(conn_main, f"""
        SELECT id FROM papers
        WHERE {scope}
          AND keystone_score_v14 IS NOT NULL
        ORDER BY keystone_score_v14 DESC LIMIT 100
    """)
    v14_top_ids = {r["id"] for r in v14_top100}

    openalex_enrich_rate = f"{enriched_papers / max(1, total_papers) * 100:.1f}%"
    openalex_w_rate = f"{openalex_w / max(1, total_papers) * 100:.1f}%"
    field_rate = f"{field_papers / max(1, total_papers) * 100:.1f}%"
    classification_rate = f"{classified_edges / max(1, subgraph_edges) * 100:.1f}%"
    cross_field_rate = f"{cross_field_preds / max(1, predicted_edges) * 100:.1f}%"

    # 构建报告
    lines = [
        f"# V14-B Evidence Decision 算法验证报告",
        f"",
        f"**生成时间**: {now}",
        f"**数据规模**: {total_papers:,} 篇论文 (corpus={corpus_label})",
        f"",
        f"---",
        f"",
        f"## 1. 执行摘要",
        f"",
        f"| 指标 | 数值 |",
        f"|---|---|",
        f"| 总论文数 | **{total_papers:,}** |",
        f"| OpenAlex W 覆盖率 | **{openalex_w_rate}** ({openalex_w:,}/{total_papers:,}) |",
        f"| Field/Topic 覆盖率 | **{field_rate}** ({field_papers:,}/{total_papers:,}) |",
        f"| 引用关系总数 | **{total_refs:,}** |",
        f"| 主干道边数 (top 1%) | **{main_path_core:,}** / {main_path_edges:,} |",
        f"| 子图节点数 | **{subgraph_nodes:,}** |",
        f"| 子图边数 | **{subgraph_edges:,}** |",
        f"| 子图结论范围 | **{subgraph_scope_row.get('conclusion_scope', 'pilot/evidence')}** |",
        f"| Citation-function evidence 覆盖率 | **{classification_rate}** |",
        f"| Future candidate generator 候选边数 | **{predicted_edges:,}** |",
        f"| Limitation atoms 总数 | **{total_atoms:,}** |",
        f"| 三路融合方向数 | **{future_dirs:,}** |",
        f"",
        f"---",
        f"",
        f"## 2. OpenAlex / Field 覆盖质量",
        f"",
        f"- **OpenAlex W 覆盖率**: {openalex_w_rate} ({openalex_w:,}/{total_papers:,})",
        f"- **Field/Topic 覆盖率**: {field_rate} ({field_papers:,}/{total_papers:,})",
        f"- **openalex_enriched 标记覆盖**: {openalex_enrich_rate}；这是历史元数据标记，不等同于 OpenAlex W 或 field/topic 决策覆盖。",
        f"- **结论边界**: OpenAlex/field coverage is not a success claim; cross-field, bridge, and topic-color conclusions must carry uncertainty until coverage gates pass.",
        f"- **引用关系总数**: {total_refs:,} 条",
        f"- **平均每篇引用数**: {total_refs / max(1, total_papers):.1f}",
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
        f"**结论边界**: Step4 是 `{subgraph_scope_row.get('conclusion_scope', 'pilot_evidence_subgraph')}`；"
        f"任何只来自该子图的结论必须标为 pilot/evidence，完整 {corpus_label} 图谱以 Step10 visual graph 为准。",
        f"",
        f"- 节点覆盖率: {float(subgraph_scope_row.get('node_coverage') or 0) * 100:.1f}%",
        f"- 边覆盖率: {float(subgraph_scope_row.get('edge_coverage') or 0) * 100:.1f}%",
        f"- 适配性: `{subgraph_scope_row.get('adequacy_label', 'unknown')}`",
        f"- 推荐子图上限: {int(subgraph_scope_row.get('recommended_max_size') or 0):,}",
        f"",
        f"---",
        f"",
        f"## 6. Citation Function Evidence",
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
        f"**证据解释**: citation function 在没有全文 citation context 时是弱证据层，"
        f"只应用作 fusion / visual evidence 的权重修正，不能当作真实引用意图的 ground truth。",
        f"",
        f"| 证据等级 | 边数 | 平均权重 |",
        f"|---|---:|---:|",
    ]

    for d in citation_evidence:
        level = d.get("level") or "unknown"
        lines.append(f"| {level} | {d.get('n', 0):,} | {float(d.get('avg_weight') or 0):.3f} |")

    lines += [
        f"",
        f"---",
        f"",
        f"## 7. Future Candidate Generator",
        f"",
        f"- **候选边总数**: {predicted_edges:,}",
        f"- **跨 Field 候选边占比**: **{cross_field_rate}** ({cross_field_preds:,}/{predicted_edges:,})",
        f"",
        f"**证据边界**: GNN/VGAE 只生成 future candidate edges；`predicted_prob`/`calibrated_prob` "
        f"是候选排序信号，不是方向结论。进入 Radar/Topic Dossier 需要 Step6 fusion + "
        f"Step13 complete Claim Card + calibration audit。",
        f"",
        f"### Top 5 候选边 (case study)",
        f"",
        f"| 源论文 | 目标论文 | 候选概率 | 源年 | 目标年 |",
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
        f"### Top 5 未来候选证据合同预览",
        f"",
        f"| 候选方向 | 排序分数 | claim_scope | evidence_grade | Radar 状态 | uncertainty_reasons |",
        f"|---|---:|---|---|---|---:|",
    ]

    for d in top_dirs:
        contract = _direction_contract(d)
        lines.append(
            f"| {d['direction_name'][:70]} | {float(d.get('confidence') or 0.0):.2f} | "
            f"{contract['claim_scope']} | {contract['evidence_grade']} | "
            f"{contract['promotion_status']} | {len(contract['uncertainty_reasons'])} |"
        )

    lines += [
        f"",
        f"> 详细见: 未来候选方向_证据合同报告.md",
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
        f"| 引用图 | 仅 arXiv 内部 | **DOI/arXiv/OpenAlex/S2 exact relinking；linked-ref 低覆盖时仍需 uncertainty** |",
        f"| 评分算法 | V13 均等权重 | **V14 生命周期自适应** |",
        f"| 未来方向 | 无 | **{future_dirs:,} 个三路融合方向** |",
        f"",
        f"---",
        f"",
        f"## 13. 下一步建议",
        f"",
        f"### 决策状态: {_decision_readiness_recommendation(future_dirs, predicted_edges, total_atoms)}",
        f"",
        f"**证据决策放行条件**:",
        f"- [ ] Topic Dossier multi-topic regression 通过四个基准 topic,不是只让 Metalens 好看",
        f"- [ ] linked refs >= 30%；低于门槛时 Main/Cite 演化只能标为 uncertainty",
        f"- [ ] section evidence 覆盖 main/future/branch/keystone 关键论文和 topic-gap 队列",
        f"- [ ] future candidates 有 rolling held-out-year calibration audit；否则只能进 candidate_pool",
        f"- [ ] Radar 主视图只允许完整 Step13 Claim Card,裸 GNN/VGAE 边只能作为证据补齐目标",
        f"",
        f"**下一步证据工作**:",
        f"1. Citation function: 如 extension+motivation+usage 占比 < 40%,先补 citation context 或运行 capped LLM edge audit 抽检；LLM 结果只能作为弱标签,不能直接升级结论",
        f"2. VGAE / future candidates: 若 calibration audit 未通过,保持 candidate_pool_only；优先补 rolling held-out-year 校准和反例分析,不是追求裸边数量",
        f"3. Limitation/resolution: 如 high-confidence resolution < 30%,保持 exploratory / candidate_pool, 优先补 limitation/discussion/resolution section evidence 与 linked resolution evidence；阈值不得下调来晋升高置信",
        f"",
        f"---",
        f"",
        f"*报告由 V14-B step9_report.py 自动生成 | {now}*",
    ]

    return "\n".join(lines)


def _decision_readiness_recommendation(future_dirs: int, predicted_edges: int, total_atoms: int) -> str:
    """Return an evidence-gated product state, not a frontend launch decision."""
    if future_dirs <= 0 or predicted_edges <= 0 or total_atoms <= 0:
        return "**INSUFFICIENT_EVIDENCE** — 证据链过薄,仅能显示 readiness gaps 和补证据队列"
    if future_dirs < 10 or total_atoms < 50:
        return "**EVIDENCE_GATED** — 候选方向可用于补证据,但 Topic Dossier / Claim Card / Radar 不得高置信放行"
    return "**CANDIDATE_POOL_READY** — 可进入候选池审阅；Radar 晋升仍需完整 Claim Card、校准和 section evidence"


# ---------------------------------------------------------------------------
# 未来方向交集报告
# ---------------------------------------------------------------------------

def generate_future_directions_report(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    *,
    corpus_id: str | None = None,
) -> str:
    """生成未来候选方向证据合同报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    direction_cols = table_columns(conn_v14, "future_directions")
    base_cols = [
        "direction_id",
        "direction_name",
        "confidence",
        "expected_period",
        "main_path_evidence",
        "vgae_evidence",
        "limitation_evidence",
        "paper_ids_json",
        "evidence_paths",
        "evidence_tier",
        "claim_scope",
        "calibration_label",
        "evidence_json",
        "claim_card_id",
        "claim_card_complete",
        "high_confidence_eligible",
        "quality_gate_json",
    ]
    select_cols = [
        col if col in direction_cols else f"NULL AS {col}"
        for col in base_cols
    ]
    directions = safe_query(conn_v14, f"""
        SELECT {', '.join(select_cols)}
        FROM future_directions
        ORDER BY confidence DESC
        LIMIT 20
    """) if direction_cols else []

    lines = [
        f"# 未来候选方向证据合同 — Claim Card / Radar 输入报告",
        f"",
        f"**生成时间**: {now}",
        f"**Corpus**: {corpus_id or 'all'}",
        f"**方法**: VGAE future candidate generator × limitation/resolution evidence × Step6 fusion × Step13 Claim Card gates",
        f"**候选方向数**: **{len(directions)}** 个",
        f"",
        f"> 本报告不把 GNN/VGAE 边或 Step6 排名分数当作结论。每一项必须携带 "
        f"`claim_scope`, `evidence_grade`, `uncertainty_reasons`; 未完整回答五问或未达高置信门槛时只能作为 candidate pool / exploratory Claim Card。",
        f"",
        f"---",
        f"",
    ]

    if not directions:
        lines += [
            f"> **TBD**: 尚无可晋升方向。请先完成当前证据约束链路 `make product-chain`, "
            f"或在 section/frontfill 完成后运行 `make post-frontfill-chain`；旧 `make pilot` 入口仅保留为 legacy compatibility。",
            f"",
        ]
        return "\n".join(lines)

    lines += [
        f"## 摘要表格",
        f"",
        f"| # | 候选方向 | 排序分数 | claim_scope | evidence_grade | Radar 状态 | uncertainty_reasons |",
        f"|---|---|---:|---|---|---|---:|",
    ]
    for i, d in enumerate(directions, 1):
        contract = _direction_contract(d)
        lines.append(
            f"| {i} | {d['direction_name'][:70]} | {float(d.get('confidence') or 0.0):.2f} | "
            f"{contract['claim_scope']} | {contract['evidence_grade']} | "
            f"{contract['promotion_status']} | {len(contract['uncertainty_reasons'])} |"
        )

    lines += [f"", f"---", f""]

    for i, d in enumerate(directions, 1):
        contract = _direction_contract(d)
        lines += [
            f"## 候选方向 {i}: {d['direction_name']}",
            f"",
            f"- **排序分数**: **{float(d.get('confidence') or 0.0):.2f}** (不是高置信结论)",
            f"- **预期出现时间**: {d.get('expected_period', 'TBD')}",
            f"- **claim_scope**: `{contract['claim_scope']}`",
            f"- **evidence_grade**: `{contract['evidence_grade']}`",
            f"- **Radar 状态**: `{contract['promotion_status']}`",
            f"- **Claim Card 五问完整**: `{contract['claim_card_complete']}`",
            f"- **高置信资格**: `{contract['high_confidence_eligible']}`",
            f"- **uncertainty_reasons**:",
        ]
        lines.extend(f"  - {reason}" for reason in contract["uncertainty_reasons"])
        lines += [
            f"",
            f"### 三路证据",
            f"",
            f"| 证据路径 | 内容 |",
            f"|---|---|",
            f"| 主干道延伸 | {d.get('main_path_evidence') or 'N/A'} |",
            f"| Future Candidate Generator (GNN/VGAE) | {_future_candidate_evidence_text(d.get('vgae_evidence'))} |",
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
                SELECT id, title, publication_year, arxiv_id, doi
                FROM papers WHERE id IN ({placeholders})
                LIMIT 5
            """, paper_ids)
            for p in related:
                lines.append(f"- {_paper_reference_markdown(dict(p))}")

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
    corpus_id: str | None = None,
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
    ensure_corpus_schema(conn_main)
    scoped_count = create_temp_corpus_table(conn_main, corpus_id)

    conn_v14 = get_v14b_conn(db_v14)
    upsert_step_meta(conn_v14, step_name, "running")

    # 确保报告目录存在
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # 生成算法验证报告
    algo_report = generate_algo_report(conn_main, conn_v14, corpus_id=corpus_id)
    REPORT_ALGO_VALIDATION.write_text(algo_report, encoding="utf-8")
    logger.info("算法验证报告: %s", REPORT_ALGO_VALIDATION)

    # 生成未来方向报告
    future_report = generate_future_directions_report(conn_main, conn_v14, corpus_id=corpus_id)
    REPORT_FUTURE_DIRECTIONS.write_text(future_report, encoding="utf-8")
    logger.info("未来方向报告: %s", REPORT_FUTURE_DIRECTIONS)
    upsert_step_meta(conn_v14, step_name, "done", records_n=2)

    conn_main.close()
    conn_v14.close()

    stats = {
        "algo_report": str(REPORT_ALGO_VALIDATION),
        "future_report": str(REPORT_FUTURE_DIRECTIONS),
        "corpus_id": corpus_id,
        "scoped_papers": scoped_count if corpus_id else None,
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

    run_report(
        db_main=db_main,
        db_v14=db_v14,
        resume=args.resume,
        corpus_id=args.corpus_id,
    )


if __name__ == "__main__":
    main()
