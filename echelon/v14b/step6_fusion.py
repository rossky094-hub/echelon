"""
Step 6: 三路融合 + 交集报告

三路输入:
  1. VGAE+MPA 主干道: main_path_edges (is_main_path=1) 末端节点
  2. VGAE Link Prediction: predicted_future_edges (top 200)
  3. Limitation Tracking: 未解决 limitation_atoms (top 50)

融合逻辑:
  - 主干道方向延伸 → 主干道末端 2024+ 节点 → 其 VGAE 预测边
  - 限制驱动方向 → 未解决 atom keyword → 匹配 VGAE 预测边
  - 三路交集 = 最高可信度未来方向

输出: future_directions 表 + markdown 报告

CLI:
    python -m echelon.v14b.step6_fusion --help
    python -m echelon.v14b.step6_fusion
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Set

from echelon.v14b.config import (
    DB_MAIN, DB_V14,
    FUSION_TOP_DIRECTIONS, FUSION_MIN_EVIDENCE_PATHS, VGAE_PREDICT_THRESHOLD,
    FUSION_USE_LLM_NAMING,
    LIMIT,
)
from echelon.v14b.db_schema import get_v14b_conn, upsert_step_meta
from echelon.v14b.llm_client import LLMClient
from echelon.v14b.utils import setup_logging, Checkpoint, add_common_args, table_columns

logger = logging.getLogger("echelon.v14b.step6_fusion")

# Prompt: 命名 future direction
DIRECTION_NAMING_PROMPT = """\
Based on the following evidence about potential future research directions in physics/optics,
generate a concise, specific direction name and key insights.

Main path terminal papers (2024+):
{main_path_papers}

VGAE predicted future connections:
{vgae_predictions}

Unresolved limitations pointing to this direction:
{limitations}

Generate a direction name and description:
Reply with JSON only:
{{
  "direction_name": "<specific technical direction, 5-10 words>",
  "expected_period": "YYYY-YYYY",
  "confidence": <0.0-1.0>,
  "summary": "<2-3 sentence description of this future direction>"
}}"""


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------

def load_main_path_terminals(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    year_threshold: int = 2022,
) -> List[dict]:
    """
    加载主干道末端节点(在 main_path 上且是新论文)。
    """
    cols = table_columns(conn_v14, "main_path_edges")
    src_expr = "source_paper_id" if "source_paper_id" in cols else "citing_id"
    dst_expr = "target_paper_id" if "target_paper_id" in cols else "cited_id"
    rows = conn_v14.execute(f"""
        SELECT DISTINCT {dst_expr} AS paper_id
        FROM main_path_edges
        WHERE is_main_path = 1
        -- 末端: time-forward target, not used again as a source.
        AND {dst_expr} NOT IN (
            SELECT {src_expr} FROM main_path_edges WHERE is_main_path = 1
        )
    """).fetchall()
    terminal_ids = [row[0] for row in rows]

    if not terminal_ids:
        # 降级: 取所有主干道上的 2022+ 节点
        rows = conn_v14.execute(f"""
            SELECT DISTINCT {dst_expr} AS paper_id
            FROM main_path_edges WHERE is_main_path = 1
        """).fetchall()
        terminal_ids = [row[0] for row in rows]

    if not terminal_ids:
        return []

    placeholders = ",".join("?" * len(terminal_ids))
    rows = conn_main.execute(f"""
        SELECT id AS paper_id, title, publication_year, primary_field_id
        FROM papers
        WHERE id IN ({placeholders})
          AND (publication_year IS NULL OR publication_year >= ?)
        ORDER BY publication_year DESC
        LIMIT 50
    """, terminal_ids + [year_threshold]).fetchall()
    return [dict(r) for r in rows]


def load_vgae_predictions(conn_v14: sqlite3.Connection) -> List[dict]:
    """加载 VGAE 预测的未来边"""
    rows = conn_v14.execute("""
        SELECT src_paper_id, dst_paper_id, predicted_prob, src_year, dst_year, is_cross_field
        FROM predicted_future_edges
        ORDER BY predicted_prob DESC
        LIMIT 200
    """).fetchall()
    return [dict(r) for r in rows]


def load_unresolved_limitations(conn_v14: sqlite3.Connection) -> List[dict]:
    """加载未解决的 limitation atoms"""
    rows = conn_v14.execute("""
        SELECT
            a.atom_id, a.paper_id, a.description, a.keyword, a.severity,
            a.evidence_source, a.evidence_quality, a.evidence_weight,
            COUNT(r.atom_id) AS n_resolutions
        FROM limitation_atoms a
        LEFT JOIN limitation_resolutions r
            ON a.atom_id = r.atom_id AND r.confidence > 0.6
        GROUP BY a.atom_id
        HAVING n_resolutions = 0
        ORDER BY CASE a.severity WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC
        LIMIT 50
    """).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 融合逻辑
# ---------------------------------------------------------------------------

def compute_direction_clusters(
    terminals: List[dict],
    vgae_preds: List[dict],
    unresolved: List[dict],
    conn_main: sqlite3.Connection,
) -> List[dict]:
    """
    三路融合:将不同信号聚合为 future direction clusters。

    聚类逻辑:
      1. 以 VGAE 预测边的 dst_paper_id 为候选 direction 锚点
      2. 检查每个候选是否同时被:
         (a) 主干道末端指向
         (b) 未解决 limitation keyword 相关
      3. 合并同 field 的相邻方向
    """
    # 主干道末端 paper_ids
    terminal_ids: Set[str] = {t["paper_id"] for t in terminals}

    # 未解决 limitation keywords
    limit_keywords: List[str] = list(dict.fromkeys(
        a["keyword"].lower() for a in unresolved if a.get("keyword")
    ))
    limitations_by_keyword: dict[str, list[dict]] = {}
    for atom in unresolved:
        kw = (atom.get("keyword") or "").lower()
        if kw:
            limitations_by_keyword.setdefault(kw, []).append(atom)

    # 读取 VGAE 预测涉及的 dst 论文标题
    dst_ids = list({p["dst_paper_id"] for p in vgae_preds})
    if not dst_ids:
        return []

    placeholders = ",".join("?" * len(dst_ids))
    rows = conn_main.execute(f"""
        SELECT id, title, abstract, publication_year, primary_field_id
        FROM papers WHERE id IN ({placeholders})
    """, dst_ids).fetchall()
    dst_meta = {row[0]: dict(row) for row in rows}

    # 对每个 VGAE 预测边,计算三路证据分数
    direction_candidates = []
    for pred in vgae_preds:
        dst_id = pred["dst_paper_id"]
        src_id = pred["src_paper_id"]
        dst_paper = dst_meta.get(dst_id, {})
        dst_title = dst_paper.get("title", "")
        dst_abstract = dst_paper.get("abstract", "") or ""

        evidence_paths = 0
        main_path_evidence = ""
        vgae_evidence = f"VGAE pred: prob={pred['predicted_prob']:.3f}"
        limitation_evidence = ""

        # 路径 1: 主干道支持.  With corrected Step5b semantics, src is the
        # older/current anchor and dst is the newer potential growth node.
        if src_id in terminal_ids:
            evidence_paths += 1
            main_path_evidence = f"主干道末端 paper_id={src_id}"

        # 路径 2: VGAE only counts when above the calibrated product threshold.
        # Low-confidence edges stay available to Step10 as visual uncertainty,
        # but should not manufacture a future direction by themselves.
        if float(pred["predicted_prob"] or 0.0) >= VGAE_PREDICT_THRESHOLD:
            evidence_paths += 1

        # 路径 3: Limitation 关联
        text_to_search = (dst_title + " " + dst_abstract).lower()
        matched_keywords = [kw for kw in limit_keywords if kw and kw in text_to_search]
        if matched_keywords:
            evidence_paths += 1
            matched_atoms = [
                atom
                for kw in matched_keywords
                for atom in limitations_by_keyword.get(kw, [])
            ]
            weights = [
                float(atom.get("evidence_weight") or 0.35)
                for atom in matched_atoms
            ]
            qualities = sorted({
                atom.get("evidence_quality") or "unknown"
                for atom in matched_atoms
            })
            limitation_weight = sum(weights) / max(1, len(weights))
            limitation_evidence = (
                f"关联未解决限制: {', '.join(matched_keywords[:3])}; "
                f"evidence_quality={','.join(qualities[:3]) or 'unknown'}"
            )
        else:
            limitation_weight = 0.0
            qualities = []

        if evidence_paths >= FUSION_MIN_EVIDENCE_PATHS:
            direction_candidates.append({
                "anchor_paper_id": dst_id,
                "anchor_title": dst_title,
                "evidence_paths": evidence_paths,
                "predicted_prob": pred["predicted_prob"],
                "is_cross_field": pred["is_cross_field"],
                "main_path_evidence": main_path_evidence,
                "vgae_evidence": vgae_evidence,
                "limitation_evidence": limitation_evidence,
                "limitation_evidence_weight": limitation_weight,
                "limitation_evidence_quality": qualities,
                "field_id": dst_paper.get("primary_field_id"),
                "src_ids": [src_id],
            })

    # 合并同 field 的候选(简单去重).  Missing field is not a real cluster, so do
    # not collapse all unknown-field candidates into one bucket.
    seen_fields: Dict[str, dict] = {}
    merged_candidates = []
    for cand in sorted(direction_candidates, key=lambda x: -x["evidence_paths"]):
        field_key = cand["field_id"] or f"anchor:{cand['anchor_paper_id']}"
        if field_key not in seen_fields:
            seen_fields[field_key] = cand
            merged_candidates.append(cand)
        else:
            # 合并到已有方向
            existing = seen_fields[field_key]
            existing["evidence_paths"] = max(existing["evidence_paths"], cand["evidence_paths"])
            existing["limitation_evidence_weight"] = max(
                existing.get("limitation_evidence_weight") or 0.0,
                cand.get("limitation_evidence_weight") or 0.0,
            )
            for src_id in cand["src_ids"]:
                if src_id not in existing["src_ids"]:
                    existing["src_ids"].append(src_id)

    return merged_candidates[:FUSION_TOP_DIRECTIONS]


def name_directions(
    candidates: List[dict],
    conn_main: sqlite3.Connection,
    llm_client=None,
) -> List[dict]:
    """
    为每个 direction cluster 生成名称。

    The product chain defaults to deterministic names because external LLM
    latency/failures should not block graph construction.  Optional LLM naming
    can still be enabled for semantic polish.
    """
    def stable_unique(ids: List[str]) -> List[str]:
        seen = set()
        out = []
        for paper_id in ids:
            if paper_id and paper_id not in seen:
                seen.add(paper_id)
                out.append(paper_id)
        return out

    named = []
    for cand in candidates:
        anchor_id = cand["anchor_paper_id"]
        anchor_title = cand["anchor_title"]

        # 构建上下文
        src_ids = cand["src_ids"][:3]
        if src_ids:
            placeholders = ",".join("?" * len(src_ids))
            src_rows = conn_main.execute(
                f"SELECT title FROM papers WHERE id IN ({placeholders})",
                src_ids
            ).fetchall()
            main_papers_text = "\n".join(f"- {r[0]}" for r in src_rows if r[0])
        else:
            main_papers_text = f"- {anchor_title}"

        direction_name = anchor_title[:80]
        expected_period = "2026-2030"
        limitation_weight = float(cand.get("limitation_evidence_weight") or 0.0)
        limitation_factor = 0.85 + 0.15 * limitation_weight if cand.get("limitation_evidence") else 1.0
        confidence = min(1.0, (0.45 + 0.15 * cand["evidence_paths"]) * limitation_factor)

        if llm_client is not None:
            prompt = DIRECTION_NAMING_PROMPT.format(
                main_path_papers=main_papers_text[:500],
                vgae_predictions=cand["vgae_evidence"],
                limitations=cand["limitation_evidence"] or "N/A",
            )

            try:
                result = llm_client.extract_json(prompt, max_tokens=300)
                direction_name = result.get("direction_name", direction_name)
                expected_period = result.get("expected_period", expected_period)
                confidence = float(result.get("confidence", confidence))
                confidence = min(1.0, confidence)
            except Exception as exc:
                logger.warning("LLM 命名失败,使用算法命名 fallback: %s", exc)

        named.append({
            "direction_name": direction_name,
            "confidence": confidence,
            "expected_period": expected_period,
            "main_path_evidence": cand["main_path_evidence"],
            "vgae_evidence": cand["vgae_evidence"],
            "limitation_evidence": cand["limitation_evidence"],
            "paper_ids_json": json.dumps(stable_unique(cand["src_ids"] + [cand["anchor_paper_id"]])),
        })

    return named


# ---------------------------------------------------------------------------
# DB 写入
# ---------------------------------------------------------------------------

def write_future_directions(
    conn_v14: sqlite3.Connection,
    directions: List[dict],
) -> int:
    """写入 future_directions 表"""
    conn_v14.execute("DELETE FROM future_directions")
    conn_v14.executemany("""
        INSERT INTO future_directions
            (direction_name, confidence, expected_period,
             main_path_evidence, vgae_evidence, limitation_evidence, paper_ids_json)
        VALUES
            (:direction_name, :confidence, :expected_period,
             :main_path_evidence, :vgae_evidence, :limitation_evidence, :paper_ids_json)
    """, directions)
    conn_v14.commit()
    return len(directions)


def write_fusion_evidence_audit(
    conn_v14: sqlite3.Connection,
    *,
    terminals: list[dict],
    vgae_preds: list[dict],
    unresolved: list[dict],
    candidates: list[dict],
    n_directions: int,
) -> dict:
    total_predicted = conn_v14.execute("SELECT COUNT(*) FROM predicted_future_edges").fetchone()[0]
    cross_field_total = conn_v14.execute(
        "SELECT COUNT(*) FROM predicted_future_edges WHERE is_cross_field = 1"
    ).fetchone()[0]
    quality_counts = Counter(
        atom.get("evidence_quality") or "unknown"
        for atom in unresolved
    )
    path_counts = Counter(int(c.get("evidence_paths") or 0) for c in candidates)
    if n_directions == 0:
        adequacy = "no_user_facing_claim"
    elif n_directions < 5:
        adequacy = "sparse_evidence"
    elif n_directions < 10:
        adequacy = "limited_but_usable_with_uncertainty"
    else:
        adequacy = "adequate_candidate_set"

    remaining_risk = (
        "If Step5b/Step5c evidence remains sparse, Step6 should output few or zero "
        "directions. Do not lower thresholds blindly; improve branch-lineage, "
        "candidate generation, limitation section evidence, and calibration first."
    )
    audit = {
        "run_id": datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"),
        "n_terminals": len(terminals),
        "n_vgae_preds_top": len(vgae_preds),
        "n_vgae_preds_total": int(total_predicted),
        "n_cross_field_total": int(cross_field_total),
        "n_unresolved": len(unresolved),
        "n_candidates": len(candidates),
        "n_directions": int(n_directions),
        "limitation_quality_json": json.dumps(dict(quality_counts), ensure_ascii=False),
        "evidence_path_json": json.dumps(dict(path_counts), ensure_ascii=False),
        "adequacy_label": adequacy,
        "remaining_risk": remaining_risk,
    }
    conn_v14.execute("DELETE FROM fusion_evidence_audit")
    conn_v14.execute("""
        INSERT OR REPLACE INTO fusion_evidence_audit
            (run_id, n_terminals, n_vgae_preds_top, n_vgae_preds_total,
             n_cross_field_total, n_unresolved, n_candidates, n_directions,
             limitation_quality_json, evidence_path_json, adequacy_label, remaining_risk)
        VALUES
            (:run_id, :n_terminals, :n_vgae_preds_top, :n_vgae_preds_total,
             :n_cross_field_total, :n_unresolved, :n_candidates, :n_directions,
             :limitation_quality_json, :evidence_path_json, :adequacy_label, :remaining_risk)
    """, audit)
    conn_v14.commit()
    return audit


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def run_fusion(
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    limit: Optional[int] = None,
    resume: bool = True,
) -> dict:
    """执行 Step 6: 三路融合"""
    step_name = "step6_fusion"
    ck = Checkpoint(step_name)

    if resume and ck.done():
        data = ck.load()
        logger.info("Step6 已完成 (%d directions),跳过", data.get("records_n", 0))
        return data

    conn_main = sqlite3.connect(str(db_main))
    conn_main.row_factory = sqlite3.Row

    conn_v14 = get_v14b_conn(db_v14)
    upsert_step_meta(conn_v14, step_name, "running")

    # 加载三路输入
    terminals = load_main_path_terminals(conn_main, conn_v14)
    logger.info("主干道末端节点: %d", len(terminals))

    vgae_preds = load_vgae_predictions(conn_v14)
    logger.info("VGAE 预测边: %d", len(vgae_preds))

    unresolved = load_unresolved_limitations(conn_v14)
    logger.info("未解决 limitations: %d", len(unresolved))

    # 三路融合
    candidates = compute_direction_clusters(terminals, vgae_preds, unresolved, conn_main)
    logger.info("融合候选方向: %d", len(candidates))

    # Direction naming.  LLM naming is opt-in; deterministic naming keeps the
    # graph product chain reproducible and independent from API availability.
    if candidates:
        llm_client = LLMClient.from_env() if FUSION_USE_LLM_NAMING else None
        directions = name_directions(candidates, conn_main, llm_client)
    else:
        # No placeholder directions: an empty table is an honest failed/weak
        # signal, while a TBD row pollutes downstream reports and visual graph.
        directions = []

    n_written = write_future_directions(conn_v14, directions)
    audit = write_fusion_evidence_audit(
        conn_v14,
        terminals=terminals,
        vgae_preds=vgae_preds,
        unresolved=unresolved,
        candidates=candidates,
        n_directions=n_written,
    )

    upsert_step_meta(
        conn_v14,
        step_name,
        "done",
        records_n=n_written,
        notes=json.dumps(audit, ensure_ascii=False),
    )
    conn_main.close()
    conn_v14.close()

    stats = {
        "n_directions": n_written,
        "n_terminals": len(terminals),
        "n_vgae_preds": len(vgae_preds),
        "n_unresolved": len(unresolved),
        "fusion_audit": audit,
        "records_n": n_written,
    }
    ck.mark_done(records_n=n_written, meta=stats)
    logger.info("Step6 完成: %d future directions", n_written)
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.step6_fusion",
        description="Step 6: 三路融合",
    )
    add_common_args(parser)
    args = parser.parse_args(argv)

    log_level = getattr(logging, args.log_level)
    setup_logging("step6_fusion", level=log_level)

    db_main = Path(args.db) if args.db else DB_MAIN
    db_v14 = Path(args.db_v14) if args.db_v14 else DB_V14
    limit = args.limit or LIMIT

    run_fusion(db_main=db_main, db_v14=db_v14, limit=limit, resume=args.resume)


if __name__ == "__main__":
    main()
