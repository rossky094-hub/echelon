"""
Step 6: 三路融合 + 交集报告

三路输入:
  1. VGAE+MPA 主干道: main_path_edges (is_main_path=1) 末端节点
  2. Future candidate generator (GNN/VGAE): predicted_future_edges (top 200)
  3. Limitation Tracking: 未解决 limitation_atoms (top 50)

融合逻辑:
  - 主干道方向延伸 → 主干道末端 2024+ 节点 → 其 GNN/VGAE candidate edges
  - 限制驱动方向 → 未解决 atom keyword → 匹配 GNN/VGAE candidate edges
  - 三路交集 = 候选方向排序信号，仍需 Step13 Claim Card / calibration gates

输出: future_directions 表 + markdown 报告

CLI:
    python -m echelon.v14b.step6_fusion --help
    python -m echelon.v14b.step6_fusion
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, List, Dict, Set

from echelon.v14b.corpus_registry import create_temp_corpus_table, ensure_corpus_schema
from echelon.v14b.config import (
    DB_MAIN, DB_V14,
    FUSION_TOP_DIRECTIONS, FUSION_MIN_EVIDENCE_PATHS, VGAE_PREDICT_THRESHOLD,
    FUSION_USE_LLM_NAMING,
    LIMIT,
)
from echelon.v14b.db_schema import get_v14b_conn, upsert_step_meta
from echelon.v14b.evidence_contracts import (
    SECTION_PARSER_CONTRACT_VERSION,
    is_decision_section,
    normalize_section_key,
    section_strategy_quality,
)
from echelon.v14b.llm_client import LLMClient
from echelon.v14b.utils import setup_logging, Checkpoint, add_common_args, table_columns

logger = logging.getLogger("echelon.v14b.step6_fusion")

FUSION_VGAE_TOP_N = int(os.environ.get("V14B_FUSION_VGAE_TOP_N", "500"))
FUSION_MIN_VGAE_CONFIDENCE = float(os.environ.get("V14B_FUSION_MIN_VGAE_CONFIDENCE", "0.55"))

# Prompt: 命名 future direction
DIRECTION_NAMING_PROMPT = """\
Based on the following evidence about potential future research directions in physics/optics,
generate a concise, specific direction name and key insights.

Main path terminal papers (2024+):
{main_path_papers}

GNN/VGAE future candidate edges:
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
    corpus_id: str | None = None,
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
    scope_sql = "AND id IN (SELECT paper_id FROM temp.v14b_corpus_papers)" if corpus_id else ""
    rows = conn_main.execute(f"""
        SELECT id AS paper_id, title, publication_year, primary_field_id
        FROM papers
        WHERE id IN ({placeholders})
          {scope_sql}
          AND (publication_year IS NULL OR publication_year >= ?)
        ORDER BY publication_year DESC
        LIMIT 50
    """, terminal_ids + [year_threshold]).fetchall()
    return [dict(r) for r in rows]


def load_vgae_predictions(conn_v14: sqlite3.Connection) -> List[dict]:
    """加载 VGAE 预测的未来边"""
    cols = table_columns(conn_v14, "predicted_future_edges")
    optional_cols = []
    for col in (
        "raw_predicted_prob",
        "calibrated_prob",
        "calibration_method",
        "calibration_support",
        "prediction_confidence",
        "calibration_label",
    ):
        if col in cols:
            optional_cols.append(col)
    optional_sql = ", " + ", ".join(optional_cols) if optional_cols else ""
    order_expr = (
        "COALESCE(prediction_confidence, predicted_prob) DESC, "
        "COALESCE(raw_predicted_prob, predicted_prob) DESC"
        if "prediction_confidence" in cols
        else "predicted_prob DESC"
    )
    rows = conn_v14.execute(f"""
        SELECT src_paper_id, dst_paper_id, predicted_prob, src_year, dst_year, is_cross_field
               {optional_sql}
        FROM predicted_future_edges
        ORDER BY {order_expr}
        LIMIT ?
    """, (FUSION_VGAE_TOP_N,)).fetchall()
    return [dict(r) for r in rows]


def load_vgae_calibration_context(conn_v14: sqlite3.Connection) -> dict:
    """Load the run-level calibration audit that makes edge probabilities decision-usable."""
    try:
        cols = table_columns(conn_v14, "vgae_calibration_audit")
        count = int(conn_v14.execute("SELECT COUNT(*) FROM vgae_calibration_audit").fetchone()[0])
    except sqlite3.Error:
        return {"has_run_audit": False, "method": None, "avg_calibrated_auc": 0.0}
    if count <= 0:
        return {"has_run_audit": False, "method": None, "avg_calibrated_auc": 0.0}
    method_expr = "method" if "method" in cols else "NULL AS method"
    auc_expr = "avg_calibrated_auc" if "avg_calibrated_auc" in cols else "NULL AS avg_calibrated_auc"
    label_expr = "label" if "label" in cols else "NULL AS label"
    order_expr = "created_at DESC" if "created_at" in cols else "rowid DESC"
    try:
        row = conn_v14.execute(
            f"""
            SELECT {method_expr}, {auc_expr}, {label_expr}
            FROM vgae_calibration_audit
            ORDER BY {order_expr}
            LIMIT 1
            """
        ).fetchone()
    except sqlite3.Error:
        row = None
    if row is None:
        return {"has_run_audit": False, "method": None, "avg_calibrated_auc": 0.0}
    return {
        "has_run_audit": True,
        "method": row[0],
        "avg_calibrated_auc": float(row[1] or 0.0),
        "label": row[2],
    }


def _candidate_calibration_status(pred: dict, calibration_context: dict | None) -> str:
    context = calibration_context or {}
    edge_has_calibration_marker = (
        pred.get("calibration_label") is not None
        or pred.get("calibration_method") is not None
        or pred.get("calibrated_prob") is not None
    )
    if context.get("has_run_audit") and edge_has_calibration_marker:
        return "calibrated_with_run_audit"
    if context.get("has_run_audit"):
        return "run_audit_available_candidate_unlabeled"
    if edge_has_calibration_marker:
        return "edge_has_calibration_label_but_run_audit_missing"
    return "not_calibrated"


def _json_obj(raw) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(str(raw))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def load_decision_grade_section_index(
    conn_main: sqlite3.Connection,
    paper_ids: list[str],
) -> dict[tuple[str, str], dict]:
    """Index current-contract traced section evidence for limitation atoms."""
    if not paper_ids:
        return {}
    try:
        cols = table_columns(conn_main, "paper_sections")
    except sqlite3.Error:
        return {}
    if "section_meta_json" not in cols:
        return {}
    out: dict[tuple[str, str], dict] = {}
    for start in range(0, len(paper_ids), 800):
        chunk = [str(pid) for pid in paper_ids[start : start + 800]]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn_main.execute(
            f"""
            SELECT paper_id, section_name, section_meta_json
            FROM paper_sections
            WHERE paper_id IN ({placeholders})
              AND length(trim(section_text)) >= 80
            """,
            chunk,
        ).fetchall()
        for row in rows:
            section_name = row["section_name"] if isinstance(row, sqlite3.Row) else row[1]
            if not is_decision_section(section_name):
                continue
            raw_meta = row["section_meta_json"] if isinstance(row, sqlite3.Row) else row[2]
            meta = _json_obj(raw_meta)
            strategies = {
                str(item).strip()
                for item in (meta.get("extraction_strategies") or [])
                if str(item).strip()
            }
            if not strategies:
                strategies = {"legacy_unknown_strategy"}
            contract_version = str(meta.get("parser_contract_version") or "legacy_unknown_contract")
            quality = section_strategy_quality(strategies)
            decision_grade = contract_version == SECTION_PARSER_CONTRACT_VERSION and quality in {"strong", "moderate"}
            paper_id = row["paper_id"] if isinstance(row, sqlite3.Row) else row[0]
            out[(str(paper_id), normalize_section_key(section_name))] = {
                "section_parser_contract_version": contract_version,
                "section_provenance_strength": quality,
                "section_decision_grade": decision_grade,
                "section_extraction_strategies": sorted(strategies),
            }
    return out


def attach_limitation_section_contracts(
    limitations: list[dict],
    conn_main: sqlite3.Connection,
) -> list[dict]:
    paper_ids = sorted({str(atom.get("paper_id") or "") for atom in limitations if atom.get("paper_id")})
    index = load_decision_grade_section_index(conn_main, paper_ids)
    enriched: list[dict] = []
    for atom in limitations:
        item = dict(atom)
        key = (
            str(item.get("paper_id") or ""),
            normalize_section_key(item.get("source_section_name") or ""),
        )
        section = index.get(key, {})
        item["section_parser_contract_version"] = section.get("section_parser_contract_version") or (
            item.get("section_parser_contract_version")
            or (
                "legacy_unknown_contract"
                if item.get("evidence_quality") in {"section_level", "structured_sections"}
                else "none"
            )
        )
        item["section_provenance_strength"] = section.get("section_provenance_strength") or (
            item.get("section_provenance_strength")
            or (
                "weak"
                if item.get("evidence_quality") in {"section_level", "structured_sections"}
                else "none"
            )
        )
        item["section_extraction_strategies"] = (
            section.get("section_extraction_strategies") or item.get("section_extraction_strategies") or []
        )
        item["section_decision_grade"] = bool(section.get("section_decision_grade")) or bool(item.get("section_decision_grade"))
        source_atom_grade = str(item.get("source_section_atom_evidence_grade") or "")
        if item.get("source_section_atom_id"):
            item["section_parser_contract_version"] = (
                item.get("source_parser_contract_version")
                or item.get("section_parser_contract_version")
            )
            item["section_provenance_strength"] = {
                "section_atom_decision_grade": "strong",
                "section_atom_traced": "moderate",
                "section_atom_weak": "weak",
            }.get(source_atom_grade, item.get("section_provenance_strength"))
            item["section_decision_grade"] = item["section_decision_grade"] or (
                source_atom_grade == "section_atom_decision_grade"
            )
            strategies = list(item.get("section_extraction_strategies") or [])
            if "section_atom_bridge" not in strategies:
                strategies.append("section_atom_bridge")
            item["section_extraction_strategies"] = strategies
        enriched.append(item)
    return enriched


def load_unresolved_limitations(conn_v14: sqlite3.Connection) -> List[dict]:
    """加载未解决的 limitation atoms"""
    cols = table_columns(conn_v14, "limitation_atoms")
    source_section_expr = (
        "COALESCE(a.source_section_name, '') AS source_section_name"
        if "source_section_name" in cols
        else "'' AS source_section_name"
    )
    optional_cols = []
    for name in (
        "source_section_atom_id",
        "source_section_atom_type",
        "source_section_atom_evidence_grade",
        "source_parser_contract_version",
        "source_storage_uri",
    ):
        optional_cols.append(
            f"COALESCE(a.{name}, '') AS {name}" if name in cols else f"'' AS {name}"
        )
    optional_cols.append(
        "a.source_page_start AS source_page_start" if "source_page_start" in cols else "NULL AS source_page_start"
    )
    optional_cols.append(
        "a.source_page_end AS source_page_end" if "source_page_end" in cols else "NULL AS source_page_end"
    )
    optional_sql = ",\n            " + ",\n            ".join(optional_cols) if optional_cols else ""
    rows = conn_v14.execute(f"""
        SELECT
            a.atom_id, a.paper_id, a.description, a.keyword, a.severity,
            a.evidence_source, a.evidence_quality, a.evidence_weight,
            {source_section_expr}{optional_sql},
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


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'virtual table') AND name = ?",
        (table,),
    ).fetchone() is not None


def _safe_json_loads(raw: Any, default: Any) -> Any:
    try:
        return json.loads(str(raw))
    except Exception:
        return default


def load_section_atom_chains(
    conn_main: sqlite3.Connection,
    *,
    corpus_id: str | None = None,
) -> list[dict]:
    """Load typed section chains as Step6 section-lineage evidence context."""
    if not _table_exists(conn_main, "section_atom_chains"):
        return []
    scope_sql = (
        "WHERE c.paper_id IN (SELECT paper_id FROM temp.v14b_corpus_papers)"
        if corpus_id
        else ""
    )
    rows = conn_main.execute(
        f"""
        SELECT
            c.*,
            COALESCE(p.title, '') AS paper_title,
            COALESCE(p.publication_year, 0) AS publication_year
        FROM section_atom_chains c
        LEFT JOIN papers p ON p.id = c.paper_id
        {scope_sql}
        """
    ).fetchall()
    chains: list[dict] = []
    for row in rows:
        chain = dict(row)
        chain["missing_stages"] = _safe_json_loads(chain.get("missing_stages_json") or "[]", [])
        chain["evidence_objects"] = _safe_json_loads(chain.get("evidence_objects_json") or "[]", [])
        chains.append(chain)
    return chains


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{2,}", (text or "").lower())
    }


def _chain_text(chain: dict[str, Any]) -> str:
    return " ".join(
        str(chain.get(key) or "")
        for key in (
            "paper_title",
            "section_name",
            "constraint_text",
            "failure_mechanism_text",
            "attempted_path_text",
            "local_fix_text",
            "new_constraint_text",
        )
        if str(chain.get(key) or "").strip()
    )


def _chain_evidence_weight(chain: dict[str, Any]) -> float:
    evidence_grade = str(chain.get("evidence_grade") or "")
    typed_chain_complete = bool(int(chain.get("typed_chain_complete") or 0))
    if evidence_grade == "typed_section_lineage":
        return 0.92
    if evidence_grade == "typed_section_lineage_traced":
        return 0.85
    if typed_chain_complete:
        return 0.70
    if evidence_grade == "partial_typed_section_lineage":
        return 0.68
    return 0.45


def _section_chain_support_summary(chains: list[dict]) -> dict[str, Any]:
    by_grade = Counter(str(chain.get("evidence_grade") or "unknown") for chain in chains)
    by_completeness = Counter(str(chain.get("typed_chain_completeness") or "unknown") for chain in chains)
    full_decision_grade = sum(
        1
        for chain in chains
        if int(chain.get("typed_chain_complete") or 0) == 1
        and str(chain.get("evidence_grade") or "") == "typed_section_lineage"
    )
    full_traced = sum(
        1
        for chain in chains
        if int(chain.get("typed_chain_complete") or 0) == 1
        and str(chain.get("evidence_grade") or "") in {"typed_section_lineage", "typed_section_lineage_traced"}
    )
    return {
        "total": len(chains),
        "full": int(by_completeness.get("full", 0)),
        "full_decision_grade": full_decision_grade,
        "full_traced_or_decision_grade": full_traced,
        "partial": sum(1 for chain in chains if int(chain.get("typed_chain_complete") or 0) == 0),
        "by_evidence_grade": dict(sorted(by_grade.items())),
        "by_completeness": dict(sorted(by_completeness.items())),
    }


def _matching_section_atom_chains(
    *,
    chains: list[dict],
    src_id: str,
    dst_id: str,
    target_text: str,
) -> list[dict]:
    target_tokens = _tokens(target_text)
    matches: list[tuple[int, float, dict]] = []
    for chain in chains:
        paper_match = str(chain.get("paper_id") or "") in {src_id, dst_id}
        token_overlap = len(_tokens(_chain_text(chain)) & target_tokens)
        if not paper_match and token_overlap < 2:
            continue
        score = (
            3 * int(paper_match)
            + 2 * int(int(chain.get("typed_chain_complete") or 0) == 1)
            + _chain_evidence_weight(chain)
            + min(token_overlap, 6) / 10.0
        )
        matches.append((int(paper_match), score, chain))
    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in matches[:12]]


# ---------------------------------------------------------------------------
# 融合逻辑
# ---------------------------------------------------------------------------

def compute_direction_clusters(
    terminals: List[dict],
    vgae_preds: List[dict],
    unresolved: List[dict],
    conn_main: sqlite3.Connection,
    calibration_context: dict | None = None,
    section_atom_chains: list[dict] | None = None,
) -> List[dict]:
    """
    三路融合:将不同信号聚合为 future direction clusters。

    聚类逻辑:
      1. 以 GNN/VGAE candidate edge 的 dst_paper_id 为候选 direction 锚点
      2. 检查每个候选是否同时被:
         (a) 主干道末端指向
         (b) 未解决 limitation keyword 相关
      3. 合并同 field 的相邻方向
    """
    # 主干道末端 paper_ids
    terminal_ids: Set[str] = {str(t["paper_id"]) for t in terminals}
    section_atom_chains = section_atom_chains or []

    # 未解决 limitation keywords
    unresolved = attach_limitation_section_contracts(unresolved, conn_main)
    limit_keywords: List[str] = list(dict.fromkeys(
        a["keyword"].lower() for a in unresolved if a.get("keyword")
    ))
    limitations_by_keyword: dict[str, list[dict]] = {}
    for atom in unresolved:
        kw = (atom.get("keyword") or "").lower()
        if kw:
            limitations_by_keyword.setdefault(kw, []).append(atom)

    # 读取 GNN/VGAE candidate edges 涉及的 dst 论文标题
    dst_ids = list({p["dst_paper_id"] for p in vgae_preds})
    if not dst_ids:
        return []

    placeholders = ",".join("?" * len(dst_ids))
    rows = conn_main.execute(f"""
        SELECT id, title, abstract, publication_year, primary_field_id
        FROM papers WHERE id IN ({placeholders})
    """, dst_ids).fetchall()
    dst_meta = {str(row[0]): dict(row) for row in rows}

    # 对每个 GNN/VGAE candidate edge 计算证据分层。Step6 now keeps exploratory
    # candidates when evidence is useful, but labels them explicitly instead of
    # promoting them into strong claims.
    direction_candidates = []
    for pred in vgae_preds:
        dst_id = str(pred["dst_paper_id"])
        src_id = str(pred["src_paper_id"])
        dst_paper = dst_meta.get(dst_id, {})
        dst_title = dst_paper.get("title", "")
        dst_abstract = dst_paper.get("abstract", "") or ""

        evidence_paths = 0
        main_path_evidence = ""
        raw_prob = float(pred.get("raw_predicted_prob") or pred.get("predicted_prob") or 0.0)
        calibrated_prob = float(pred.get("calibrated_prob") or pred.get("predicted_prob") or 0.0)
        prediction_confidence = float(
            pred.get("prediction_confidence")
            if pred.get("prediction_confidence") is not None
            else calibrated_prob
        )
        calibration_status = _candidate_calibration_status(pred, calibration_context)
        calibrated_for_fusion = calibration_status == "calibrated_with_run_audit"
        calibration_label = (
            pred.get("calibration_label")
            or pred.get("calibration_method")
            or (
                "run_audit_unlabeled"
                if calibration_status == "run_audit_available_candidate_unlabeled"
                else "uncalibrated_no_run_audit"
            )
        )
        vgae_evidence = (
            f"GNN/VGAE candidate edge: calibrated={calibrated_prob:.3f}, "
            f"raw={raw_prob:.3f}, confidence={prediction_confidence:.3f}, "
            f"calibration={calibration_label}, status={calibration_status}"
        )
        limitation_evidence = ""

        # 路径 1: 主干道支持.  With corrected Step5b semantics, src is the
        # older/current anchor and dst is the newer potential growth node.
        if src_id in terminal_ids:
            evidence_paths += 1
            main_path_evidence = f"主干道末端 paper_id={src_id}"

        # 路径 2: VGAE only counts when above the calibrated product threshold.
        # Low-confidence edges stay available to Step10 as visual uncertainty,
        # but should not manufacture a future direction by themselves.
        vgae_supported = (
            calibrated_for_fusion
            and prediction_confidence >= FUSION_MIN_VGAE_CONFIDENCE
            and calibrated_prob >= min(VGAE_PREDICT_THRESHOLD, FUSION_MIN_VGAE_CONFIDENCE)
        )
        if vgae_supported:
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
            decision_grade_section_count = sum(1 for atom in matched_atoms if atom.get("section_decision_grade"))
            limitation_contract_versions = sorted(
                {
                    str(atom.get("section_parser_contract_version") or "unknown")
                    for atom in matched_atoms
                }
            )
            limitation_weight = sum(weights) / max(1, len(weights))
            limitation_evidence = (
                f"关联未解决限制: {', '.join(matched_keywords[:3])}; "
                f"evidence_quality={','.join(qualities[:3]) or 'unknown'}; "
                f"decision_grade_sections={decision_grade_section_count}"
            )
        else:
            limitation_weight = 0.0
            qualities = []
            decision_grade_section_count = 0
            limitation_contract_versions = []

        matched_chains = _matching_section_atom_chains(
            chains=section_atom_chains,
            src_id=src_id,
            dst_id=dst_id,
            target_text=f"{dst_title} {dst_abstract}",
        )
        chain_support = _section_chain_support_summary(matched_chains)
        chain_lineage_counts_as_path = int(chain_support.get("full_traced_or_decision_grade") or 0) > 0
        chain_decision_grade_count = int(chain_support.get("full_decision_grade") or 0)
        if chain_lineage_counts_as_path:
            evidence_paths += 1
        chain_weight = max([_chain_evidence_weight(chain) for chain in matched_chains] or [0.0])
        if matched_chains:
            chain_evidence = (
                "typed section atom chains: "
                f"total={chain_support['total']}, full={chain_support['full']}, "
                f"full_decision_grade={chain_support['full_decision_grade']}, "
                f"partial={chain_support['partial']}"
            )
            limitation_evidence = (
                f"{limitation_evidence}; {chain_evidence}"
                if limitation_evidence
                else chain_evidence
            )
            limitation_weight = max(limitation_weight, chain_weight)

        if evidence_paths >= FUSION_MIN_EVIDENCE_PATHS:
            section_qualities = list(qualities)
            if chain_lineage_counts_as_path:
                section_qualities.append("section_level")
            evidence_tier = direction_evidence_tier(
                evidence_paths=evidence_paths,
                limitation_quality=section_qualities,
                prediction_confidence=prediction_confidence,
                has_main_path=bool(main_path_evidence),
                calibrated_for_fusion=calibrated_for_fusion,
                has_decision_grade_section_evidence=(
                    decision_grade_section_count > 0 or chain_decision_grade_count > 0
                ),
            )
            missing_gates = (
                []
                if calibrated_for_fusion
                else ["rolling held-out-year calibration audit"]
            )
            if "section_level" in set(qualities) and decision_grade_section_count <= 0:
                missing_gates.append("current parser-contract decision-grade limitation section evidence")
            if int(chain_support.get("total") or 0) > 0 and chain_decision_grade_count <= 0:
                missing_gates.append("current parser-contract decision-grade typed-chain section evidence")
            direction_candidates.append({
                "anchor_paper_id": dst_id,
                "anchor_title": dst_title,
                "future_edge_pairs": [[src_id, dst_id]],
                "evidence_paths": evidence_paths,
                "evidence_tier": evidence_tier,
                "claim_scope": claim_scope_for_tier(evidence_tier),
                "predicted_prob": pred["predicted_prob"],
                "raw_predicted_prob": raw_prob,
                "calibrated_prob": calibrated_prob,
                "prediction_confidence": prediction_confidence,
                "calibration_label": calibration_label,
                "calibration_status": calibration_status,
                "calibrated_for_fusion": calibrated_for_fusion,
                "missing_gates": missing_gates,
                "uncertainty_reasons": (
                    []
                    if calibrated_for_fusion
                    else [calibration_status.replace("_", " ")]
                ),
                "is_cross_field": pred["is_cross_field"],
                "main_path_evidence": main_path_evidence,
                "vgae_evidence": vgae_evidence,
                "limitation_evidence": limitation_evidence,
                "limitation_evidence_weight": limitation_weight,
                "limitation_evidence_quality": section_qualities,
                "limitation_decision_grade_section_count": decision_grade_section_count,
                "section_atom_chain_support": chain_support,
                "section_atom_chain_ids": [
                    str(chain.get("chain_id") or "")
                    for chain in matched_chains
                    if str(chain.get("chain_id") or "")
                ],
                "section_atom_chain_decision_grade_count": chain_decision_grade_count,
                "section_atom_chain_evidence_weight": chain_weight,
                "limitation_section_contract_versions": limitation_contract_versions,
                "field_id": dst_paper.get("primary_field_id"),
                "src_ids": [src_id],
            })

    # 合并同 field 的候选(简单去重).  Missing field is not a real cluster, so do
    # not collapse all unknown-field candidates into one bucket.
    seen_fields: Dict[str, dict] = {}
    merged_candidates = []
    for cand in sorted(
        direction_candidates,
        key=lambda x: (
            -int(x["evidence_paths"]),
            -(x.get("prediction_confidence") or 0.0),
            -(x.get("limitation_evidence_weight") or 0.0),
        ),
    ):
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
            existing_pairs = existing.setdefault("future_edge_pairs", [])
            for pair in cand.get("future_edge_pairs") or []:
                if pair not in existing_pairs:
                    existing_pairs.append(pair)
            existing["prediction_confidence"] = max(
                existing.get("prediction_confidence") or 0.0,
                cand.get("prediction_confidence") or 0.0,
            )
            existing["evidence_tier"] = max_evidence_tier(existing["evidence_tier"], cand["evidence_tier"])
            existing["claim_scope"] = claim_scope_for_tier(existing["evidence_tier"])
            if cand.get("calibrated_for_fusion") and not existing.get("calibrated_for_fusion"):
                existing["calibrated_for_fusion"] = True
                existing["calibration_status"] = cand.get("calibration_status")
                existing["calibration_label"] = cand.get("calibration_label")
                existing["missing_gates"] = cand.get("missing_gates") or []
                existing["uncertainty_reasons"] = cand.get("uncertainty_reasons") or []
            existing["limitation_decision_grade_section_count"] = max(
                int(existing.get("limitation_decision_grade_section_count") or 0),
                int(cand.get("limitation_decision_grade_section_count") or 0),
            )
            existing["section_atom_chain_decision_grade_count"] = max(
                int(existing.get("section_atom_chain_decision_grade_count") or 0),
                int(cand.get("section_atom_chain_decision_grade_count") or 0),
            )
            existing["section_atom_chain_evidence_weight"] = max(
                float(existing.get("section_atom_chain_evidence_weight") or 0.0),
                float(cand.get("section_atom_chain_evidence_weight") or 0.0),
            )
            if int((cand.get("section_atom_chain_support") or {}).get("total") or 0) > int(
                (existing.get("section_atom_chain_support") or {}).get("total") or 0
            ):
                existing["section_atom_chain_support"] = cand.get("section_atom_chain_support") or {}
            existing_chain_ids = list(existing.get("section_atom_chain_ids") or [])
            for chain_id in cand.get("section_atom_chain_ids") or []:
                if chain_id not in existing_chain_ids:
                    existing_chain_ids.append(chain_id)
            existing["section_atom_chain_ids"] = existing_chain_ids[:24]
            contracts = set(existing.get("limitation_section_contract_versions") or [])
            contracts.update(cand.get("limitation_section_contract_versions") or [])
            existing["limitation_section_contract_versions"] = sorted(contracts)

    return merged_candidates[:FUSION_TOP_DIRECTIONS]


def direction_evidence_tier(
    *,
    evidence_paths: int,
    limitation_quality: list[str],
    prediction_confidence: float,
    has_main_path: bool,
    calibrated_for_fusion: bool = True,
    has_decision_grade_section_evidence: bool = False,
) -> str:
    qualities = set(limitation_quality or [])
    has_section = bool(qualities & {"section_level", "structured_sections"})
    has_weak_limitation = "weak_abstract" in qualities or not qualities
    if not calibrated_for_fusion:
        return "exploratory_uncalibrated_candidate" if evidence_paths >= 2 else "insufficient"
    if (
        evidence_paths >= 3
        and prediction_confidence >= 0.70
        and has_section
        and has_decision_grade_section_evidence
        and has_main_path
    ):
        return "triangulated_strong"
    if evidence_paths >= 3 and prediction_confidence >= 0.60:
        return "triangulated_limited"
    if evidence_paths >= 2 and has_weak_limitation:
        return "exploratory_weak_limitation"
    if evidence_paths >= 2:
        return "exploratory"
    return "insufficient"


def max_evidence_tier(left: str, right: str) -> str:
    rank = {
        "insufficient": 0,
        "exploratory_uncalibrated_candidate": 1,
        "exploratory_weak_limitation": 1,
        "exploratory": 2,
        "triangulated_limited": 3,
        "triangulated_strong": 4,
    }
    return left if rank.get(left, 0) >= rank.get(right, 0) else right


def claim_scope_for_tier(tier: str) -> str:
    if tier == "exploratory_uncalibrated_candidate":
        return "candidate_pool_only"
    if tier == "triangulated_strong":
        return "candidate_direction"
    if tier == "triangulated_limited":
        return "candidate_direction_with_uncertainty"
    if tier.startswith("exploratory"):
        return "exploratory_hypothesis"
    return "not_for_user_claim"


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
        prediction_confidence = float(cand.get("prediction_confidence") or cand.get("predicted_prob") or 0.0)
        confidence = (
            0.20
            + 0.10 * int(cand["evidence_paths"])
            + 0.35 * prediction_confidence
            + 0.20 * limitation_weight
        ) * limitation_factor
        if cand.get("evidence_tier") == "exploratory_weak_limitation":
            confidence = min(confidence, 0.62)
        elif cand.get("evidence_tier") == "exploratory_uncalibrated_candidate":
            confidence = min(confidence, 0.52)
        elif cand.get("evidence_tier") == "triangulated_limited":
            confidence = min(confidence, 0.74)
        else:
            confidence = min(confidence, 0.88)

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
            "evidence_paths": int(cand.get("evidence_paths") or 0),
            "evidence_tier": cand.get("evidence_tier") or "insufficient",
            "claim_scope": cand.get("claim_scope") or "not_for_user_claim",
            "calibration_label": cand.get("calibration_label"),
            "evidence_json": json.dumps(
                {
                    "anchor_paper_id": cand["anchor_paper_id"],
                    "src_ids": stable_unique(cand["src_ids"]),
                    "future_edge_pairs": cand.get("future_edge_pairs") or [],
                    "predicted_prob": cand.get("predicted_prob"),
                    "raw_predicted_prob": cand.get("raw_predicted_prob"),
                    "calibrated_prob": cand.get("calibrated_prob"),
                    "prediction_confidence": cand.get("prediction_confidence"),
                    "calibration_status": cand.get("calibration_status"),
                    "calibrated_for_fusion": bool(cand.get("calibrated_for_fusion")),
                    "missing_gates": cand.get("missing_gates") or [],
                    "uncertainty_reasons": cand.get("uncertainty_reasons") or [],
                    "limitation_evidence_quality": cand.get("limitation_evidence_quality"),
                    "limitation_evidence_weight": cand.get("limitation_evidence_weight"),
                    "limitation_decision_grade_section_count": cand.get("limitation_decision_grade_section_count"),
                    "section_atom_chain_support": cand.get("section_atom_chain_support") or {},
                    "section_atom_chain_ids": cand.get("section_atom_chain_ids") or [],
                    "section_atom_chain_decision_grade_count": cand.get("section_atom_chain_decision_grade_count") or 0,
                    "section_atom_chain_evidence_weight": cand.get("section_atom_chain_evidence_weight") or 0.0,
                    "limitation_section_contract_versions": cand.get("limitation_section_contract_versions") or [],
                    "claim_scope": cand.get("claim_scope"),
                },
                ensure_ascii=False,
            ),
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
    for direction in directions:
        direction.setdefault("evidence_paths", None)
        direction.setdefault("evidence_tier", None)
        direction.setdefault("claim_scope", None)
        direction.setdefault("calibration_label", None)
        direction.setdefault("evidence_json", None)
    conn_v14.execute("DELETE FROM future_directions")
    conn_v14.executemany("""
        INSERT INTO future_directions
            (direction_name, confidence, expected_period,
             main_path_evidence, vgae_evidence, limitation_evidence, paper_ids_json,
             evidence_paths, evidence_tier, claim_scope, calibration_label, evidence_json)
        VALUES
            (:direction_name, :confidence, :expected_period,
             :main_path_evidence, :vgae_evidence, :limitation_evidence, :paper_ids_json,
             :evidence_paths, :evidence_tier, :claim_scope, :calibration_label, :evidence_json)
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
    decision_grade_limitations = sum(1 for atom in unresolved if atom.get("section_decision_grade"))
    chain_supported_candidates = sum(
        1
        for candidate in candidates
        if int((candidate.get("section_atom_chain_support") or {}).get("total") or 0) > 0
    )
    decision_grade_chain_candidates = sum(
        1
        for candidate in candidates
        if int((candidate.get("section_atom_chain_support") or {}).get("full_decision_grade") or 0) > 0
    )
    path_counts = Counter(int(c.get("evidence_paths") or 0) for c in candidates)
    tier_counts = Counter(c.get("evidence_tier") or "unknown" for c in candidates)
    calibration_counts = Counter(c.get("calibration_label") or "legacy_raw" for c in candidates)
    calibration_status_counts = Counter(c.get("calibration_status") or "unknown" for c in candidates)
    confidence_values = [
        float(c.get("prediction_confidence") or 0.0)
        for c in candidates
    ]
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
        "candidate_tier_json": json.dumps(dict(tier_counts), ensure_ascii=False),
        "calibration_json": json.dumps(
            {
                "labels": dict(calibration_counts),
                "status": dict(calibration_status_counts),
                "prediction_confidence_avg": (
                    sum(confidence_values) / max(1, len(confidence_values))
                ),
                "min_vgae_confidence": FUSION_MIN_VGAE_CONFIDENCE,
                "vgae_top_n": FUSION_VGAE_TOP_N,
                "decision_grade_limitation_sections": decision_grade_limitations,
                "chain_supported_candidates": chain_supported_candidates,
                "decision_grade_section_atom_chain_candidates": decision_grade_chain_candidates,
            },
            ensure_ascii=False,
        ),
        "adequacy_label": adequacy,
        "remaining_risk": remaining_risk,
    }
    conn_v14.execute("DELETE FROM fusion_evidence_audit")
    conn_v14.execute("""
        INSERT OR REPLACE INTO fusion_evidence_audit
            (run_id, n_terminals, n_vgae_preds_top, n_vgae_preds_total,
             n_cross_field_total, n_unresolved, n_candidates, n_directions,
             limitation_quality_json, evidence_path_json, candidate_tier_json,
             calibration_json, adequacy_label, remaining_risk)
        VALUES
            (:run_id, :n_terminals, :n_vgae_preds_top, :n_vgae_preds_total,
             :n_cross_field_total, :n_unresolved, :n_candidates, :n_directions,
             :limitation_quality_json, :evidence_path_json, :candidate_tier_json,
             :calibration_json, :adequacy_label, :remaining_risk)
    """, audit)
    conn_v14.commit()
    return audit


def _table_row_count(conn: sqlite3.Connection, table: str) -> int | None:
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except sqlite3.Error:
        return None


def _fusion_resume_state_valid(conn_v14: sqlite3.Connection, checkpoint_data: dict) -> tuple[bool, str]:
    """Protect Step6 from stale checkpoints and stale fusion audit rows."""
    expected = int(checkpoint_data.get("records_n") or 0)
    actual = _table_row_count(conn_v14, "future_directions")
    if actual is None:
        return False, "future_directions table is missing"
    if actual != expected:
        return False, f"future_directions rows={actual} != checkpoint records_n={expected}"

    try:
        row = conn_v14.execute(
            "SELECT n_directions FROM fusion_evidence_audit LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        row = None
    if row is None:
        return False, "fusion_evidence_audit is missing"
    audit_n = int(row[0] or 0)
    if audit_n != actual:
        return False, f"fusion_evidence_audit n_directions={audit_n} != future_directions rows={actual}"

    return True, "ok"


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def run_fusion(
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    limit: Optional[int] = None,
    resume: bool = True,
    corpus_id: str | None = None,
) -> dict:
    """执行 Step 6: 三路融合"""
    step_name = "step6_fusion"
    ck = Checkpoint(step_name)

    if resume and ck.done():
        data = ck.load()
        conn_v14_resume = get_v14b_conn(db_v14)
        valid, reason = _fusion_resume_state_valid(conn_v14_resume, data)
        conn_v14_resume.close()
        if valid:
            logger.info("Step6 已完成 (%d directions),跳过", data.get("records_n", 0))
            return data
        logger.warning("Step6 checkpoint stale; rerunning fusion: %s", reason)
        ck.clear()

    conn_main = sqlite3.connect(str(db_main))
    conn_main.row_factory = sqlite3.Row
    ensure_corpus_schema(conn_main)
    scoped_count = create_temp_corpus_table(conn_main, corpus_id)

    conn_v14 = get_v14b_conn(db_v14)
    upsert_step_meta(conn_v14, step_name, "running")

    # 加载三路输入
    terminals = load_main_path_terminals(conn_main, conn_v14, corpus_id=corpus_id)
    logger.info("主干道末端节点: %d", len(terminals))

    vgae_preds = load_vgae_predictions(conn_v14)
    logger.info("GNN/VGAE candidate edges: %d", len(vgae_preds))
    calibration_context = load_vgae_calibration_context(conn_v14)
    if not calibration_context.get("has_run_audit"):
        logger.warning("VGAE run-level calibration audit missing; Step6 will keep VGAE-only evidence as candidate-pool evidence")

    unresolved = load_unresolved_limitations(conn_v14)
    unresolved = attach_limitation_section_contracts(unresolved, conn_main)
    logger.info("未解决 limitations: %d", len(unresolved))
    section_atom_chains = load_section_atom_chains(conn_main, corpus_id=corpus_id)
    logger.info("typed section atom chains: %d", len(section_atom_chains))

    # 三路融合
    candidates = compute_direction_clusters(
        terminals,
        vgae_preds,
        unresolved,
        conn_main,
        calibration_context=calibration_context,
        section_atom_chains=section_atom_chains,
    )
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
        "n_section_atom_chains": len(section_atom_chains),
        "corpus_id": corpus_id,
        "scoped_papers": scoped_count if corpus_id else None,
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

    run_fusion(
        db_main=db_main,
        db_v14=db_v14,
        limit=limit,
        resume=args.resume,
        corpus_id=args.corpus_id,
    )


if __name__ == "__main__":
    main()
