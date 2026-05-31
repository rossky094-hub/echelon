"""Step 13: 第一性原理 + 卡点历史脉络报告.

目标:
1. 把 limitation/resolution/future-growth/branch-lineage 证据汇总成可追溯结论。
2. 避免“泛泛而谈”结论: 每条结论都绑定原子证据、年份、分支和未来边。
3. 产出结构化表 + Markdown/JSON 报告,供 API/可视化继续消费。

该 step 默认不调用外部 LLM,完全基于已入库证据可重跑、可审计。
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from echelon.v14b.corpus_registry import create_temp_corpus_table, ensure_corpus_schema
from echelon.v14b.config import DB_MAIN, DB_V14, REPORT_DIR
from echelon.v14b.db_schema import get_v14b_conn, upsert_step_meta
from echelon.v14b.evidence_contracts import (
    MODERATE_SECTION_STRATEGIES,
    SECTION_PARSER_CONTRACT_VERSION,
    STRONG_SECTION_STRATEGIES,
)
from echelon.v14b.evidence_grade import grade_from_qualities
from echelon.v14b.utils import add_common_args, setup_logging

logger = logging.getLogger("echelon.v14b.step13_first_principles_history")


SEVERITY_WEIGHT = {
    "high": 1.00,
    "medium": 0.65,
    "low": 0.35,
}


@dataclass(frozen=True)
class PrincipleDef:
    principle_id: str
    name: str
    root_cause: str
    patterns: tuple[str, ...]
    cross_domain_duals: tuple[str, ...]

    def match_count(self, text: str) -> int:
        total = 0
        for p in self.patterns:
            total += len(re.findall(p, text, flags=re.I))
        return total


PRINCIPLES: tuple[PrincipleDef, ...] = (
    PrincipleDef(
        principle_id="FP_OPT_GEOM",
        name="优化几何与可训练性约束",
        root_cause="非凸地形/梯度稳定性/收敛路径受限",
        patterns=(
            r"\bnon[- ]?convex\b",
            r"\bgradient\b",
            r"\bconvergen",
            r"\bunstable\b",
            r"\btraining\b",
            r"\blocal minima\b",
            r"\boptimization\b",
        ),
        cross_domain_duals=(
            "逆向设计中的非凸搜索",
            "强化学习中的信用分配与训练震荡",
            "多模态大模型中的对齐优化不稳定",
        ),
    ),
    PrincipleDef(
        principle_id="FP_INFO_CAPACITY",
        name="信息容量与噪声约束",
        root_cause="信道容量/互信息可分辨性/噪声累积上界",
        patterns=(
            r"\bnoise\b",
            r"\bsnr\b",
            r"\bbandwidth\b",
            r"\bcapacity\b",
            r"\binformation\b",
            r"\bcompression\b",
            r"\bresolution\b",
            r"\bsignal\b",
        ),
        cross_domain_duals=(
            "光学测量中的信噪比瓶颈",
            "通信系统中的容量与误码权衡",
            "视觉表示中的压缩与判别力权衡",
        ),
    ),
    PrincipleDef(
        principle_id="FP_PHYSICAL_CONSTRAINT",
        name="物理实现与制造约束",
        root_cause="材料/热/损耗/工艺容差等硬约束",
        patterns=(
            r"\bfabricat",
            r"\bmanufactur",
            r"\bthermal\b",
            r"\bloss\b",
            r"\bcoupling\b",
            r"\bdispersion\b",
            r"\bdiffraction\b",
            r"\befficien",
        ),
        cross_domain_duals=(
            "光子器件制造容差",
            "硬件系统热设计与功耗边界",
            "实验物理中的器件稳定性",
        ),
    ),
    PrincipleDef(
        principle_id="FP_GENERALIZATION_SHIFT",
        name="泛化与分布漂移约束",
        root_cause="训练分布与部署分布不一致导致失配",
        patterns=(
            r"\bgeneralization\b",
            r"\bdomain shift\b",
            r"\bood\b",
            r"\bout[- ]of[- ]distribution\b",
            r"\bsim[- ]to[- ]real\b",
            r"\brobust",
            r"\bbias\b",
            r"\bhallucinat",
        ),
        cross_domain_duals=(
            "机器人 sim2real 泛化",
            "多模态模型跨域迁移",
            "实验环境到真实场景的稳健性落差",
        ),
    ),
    PrincipleDef(
        principle_id="FP_SCALING_INTEGRATION",
        name="规模化与系统集成约束",
        root_cause="计算/时延/内存/系统耦合成本上升",
        patterns=(
            r"\bscalab",
            r"\blatency\b",
            r"\bmemory\b",
            r"\bcomput",
            r"\bthroughput\b",
            r"\bintegration\b",
            r"\bdeployment\b",
            r"\breal[- ]time\b",
        ),
        cross_domain_duals=(
            "片上光学系统集成与吞吐瓶颈",
            "大模型推理时延与资源约束",
            "跨模块系统工程复杂度爆炸",
        ),
    ),
)

FALLBACK_PRINCIPLE = PrincipleDef(
    principle_id="FP_OTHER",
    name="其他未归类基础约束",
    root_cause="证据文本不足或跨类混合",
    patterns=(),
    cross_domain_duals=(
        "需要更多 section-level 证据后再细分",
    ),
)

PRINCIPLE_TO_ROOT_CONSTRAINT = {
    "FP_PHYSICAL_CONSTRAINT": "physical",
    "FP_SCALING_INTEGRATION": "engineering",
    "FP_OPT_GEOM": "engineering",
    "FP_INFO_CAPACITY": "data",
    "FP_GENERALIZATION_SHIFT": "data",
    "FP_OTHER": "cost",
}

COST_TERMS = re.compile(
    r"\b(cost|expensive|budget|resource|compute|latency|throughput|"
    r"memory|time-consuming|slow|infrastructure)\b",
    re.I,
)

HEURISTIC_RESOLUTION_EVIDENCE_TEXT = (
    "Algorithmic lexical match between limitation keyword and resolver claim."
)

def jdumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def ensure_schema(conn_v14: sqlite3.Connection) -> None:
    conn_v14.executescript(
        """
        CREATE TABLE IF NOT EXISTS first_principles_principles (
            principle_id TEXT PRIMARY KEY,
            principle_name TEXT NOT NULL,
            root_cause TEXT,
            bottleneck_score REAL NOT NULL DEFAULT 0,
            unresolved_atoms INTEGER NOT NULL DEFAULT 0,
            resolved_atoms INTEGER NOT NULL DEFAULT 0,
            emergence_year INTEGER,
            peak_backlog_year INTEGER,
            current_backlog REAL,
            evidence_quality_json TEXT,
            top_keywords_json TEXT,
            top_branches_json TEXT,
            top_papers_json TEXT,
            future_alignment_json TEXT,
            direction_tier_json TEXT,
            risk_label TEXT,
            notes_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS first_principles_history_events (
            principle_id TEXT NOT NULL,
            event_year INTEGER NOT NULL,
            opened_atoms INTEGER NOT NULL DEFAULT 0,
            resolved_atoms INTEGER NOT NULL DEFAULT 0,
            opened_score REAL NOT NULL DEFAULT 0,
            resolved_score REAL NOT NULL DEFAULT 0,
            backlog_score REAL NOT NULL DEFAULT 0,
            top_keywords_json TEXT,
            PRIMARY KEY (principle_id, event_year)
        );

        CREATE INDEX IF NOT EXISTS idx_fp_history_year
            ON first_principles_history_events(event_year);

        CREATE TABLE IF NOT EXISTS bottleneck_lineage_triples (
            triple_id TEXT PRIMARY KEY,
            principle_id TEXT NOT NULL,
            direction_id INTEGER,
            atom_id INTEGER,
            edge_order INTEGER NOT NULL,
            source_stage TEXT NOT NULL,
            target_stage TEXT NOT NULL,
            source_text TEXT,
            target_text TEXT,
            relation_type TEXT,
            paper_id TEXT,
            resolver_paper_id TEXT,
            event_year INTEGER,
            evidence_section TEXT,
            evidence_page INTEGER,
            evidence_quality TEXT,
            evidence_weight REAL,
            metadata_json TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_lineage_principle
            ON bottleneck_lineage_triples(principle_id, event_year DESC);
        CREATE INDEX IF NOT EXISTS idx_lineage_direction
            ON bottleneck_lineage_triples(direction_id, event_year DESC);

        CREATE TABLE IF NOT EXISTS direction_claim_cards (
            claim_card_id TEXT PRIMARY KEY,
            direction_id INTEGER NOT NULL,
            direction_name TEXT NOT NULL,
            root_constraint_json TEXT NOT NULL,
            attempts_last_10y_json TEXT NOT NULL,
            enabling_conditions_json TEXT NOT NULL,
            unresolved_bottleneck_json TEXT NOT NULL,
            minimal_validation_experiment_json TEXT NOT NULL,
            evidence_strength_level TEXT NOT NULL,
            evidence_grade TEXT NOT NULL DEFAULT 'incomplete_claim_card',
            claim_scope TEXT NOT NULL,
            uncertainty_reasons_json TEXT NOT NULL DEFAULT '[]',
            evidence_objects_json TEXT NOT NULL DEFAULT '[]',
            five_question_complete INTEGER NOT NULL DEFAULT 0,
            high_confidence_eligible INTEGER NOT NULL DEFAULT 0,
            quality_gate_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_claim_cards_direction
            ON direction_claim_cards(direction_id);
        """
    )
    cols = {
        row[1] for row in conn_v14.execute("PRAGMA table_info(future_directions)").fetchall()
    }
    if "claim_card_id" not in cols:
        conn_v14.execute("ALTER TABLE future_directions ADD COLUMN claim_card_id TEXT")
    if "claim_card_complete" not in cols:
        conn_v14.execute("ALTER TABLE future_directions ADD COLUMN claim_card_complete INTEGER DEFAULT 0")
    if "high_confidence_eligible" not in cols:
        conn_v14.execute("ALTER TABLE future_directions ADD COLUMN high_confidence_eligible INTEGER DEFAULT 0")
    if "quality_gate_json" not in cols:
        conn_v14.execute("ALTER TABLE future_directions ADD COLUMN quality_gate_json TEXT")
    claim_cols = {
        row[1] for row in conn_v14.execute("PRAGMA table_info(direction_claim_cards)").fetchall()
    }
    for col, ddl in {
        "evidence_grade": "ALTER TABLE direction_claim_cards ADD COLUMN evidence_grade TEXT NOT NULL DEFAULT 'incomplete_claim_card'",
        "uncertainty_reasons_json": "ALTER TABLE direction_claim_cards ADD COLUMN uncertainty_reasons_json TEXT NOT NULL DEFAULT '[]'",
        "evidence_objects_json": "ALTER TABLE direction_claim_cards ADD COLUMN evidence_objects_json TEXT NOT NULL DEFAULT '[]'",
    }.items():
        if col not in claim_cols:
            conn_v14.execute(ddl)
    conn_v14.commit()


def classify_principle(text: str) -> PrincipleDef:
    norm = (text or "").lower()
    best: Optional[PrincipleDef] = None
    best_hits = 0
    for p in PRINCIPLES:
        hits = p.match_count(norm)
        if hits > best_hits:
            best_hits = hits
            best = p
    return best if best and best_hits > 0 else FALLBACK_PRINCIPLE


def _json_obj(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(str(value))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _strategy_strength(strategies: set[str]) -> str:
    if strategies & STRONG_SECTION_STRATEGIES:
        return "strong"
    if strategies & MODERATE_SECTION_STRATEGIES:
        return "moderate"
    return "weak"


def load_section_provenance_index(
    conn_main: sqlite3.Connection,
    paper_ids: list[str],
    *,
    corpus_id: str | None = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    table_names = {
        row[0] for row in conn_main.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "paper_sections" not in table_names or not paper_ids:
        return {}
    cols = {
        row[1] for row in conn_main.execute("PRAGMA table_info(paper_sections)").fetchall()
    }
    meta_expr = "COALESCE(section_meta_json, '{}')" if "section_meta_json" in cols else "'{}'"
    placeholders = ",".join("?" * len(paper_ids))
    scope_sql = (
        "AND paper_id IN (SELECT paper_id FROM temp.v14b_corpus_papers)"
        if corpus_id
        else ""
    )
    rows = conn_main.execute(
        f"""
        SELECT paper_id, section_name, {meta_expr} AS section_meta_json
        FROM paper_sections
        WHERE paper_id IN ({placeholders})
          {scope_sql}
        """,
        paper_ids,
    ).fetchall()
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        meta = _json_obj(row["section_meta_json"])
        raw_strategies = meta.get("extraction_strategies") or []
        strategies = {
            str(item).strip()
            for item in raw_strategies
            if str(item).strip()
        }
        if not strategies:
            strategies = {"legacy_unknown_strategy"}
        strength = _strategy_strength(strategies)
        contract_version = str(meta.get("parser_contract_version") or "legacy_unknown_contract")
        out[(str(row["paper_id"]), _normalize_section_name(str(row["section_name"] or "")))] = {
            "section_provenance_strength": strength,
            "section_extraction_strategies": sorted(strategies),
            "section_parser_contract_version": contract_version,
            "section_decision_grade": (
                contract_version == SECTION_PARSER_CONTRACT_VERSION
                and strength in {"strong", "moderate"}
            ),
            "section_meta": meta,
        }
    return out


def load_atoms(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    *,
    corpus_id: str | None = None,
) -> list[dict]:
    if not table_exists(conn_v14, "limitation_atoms"):
        return []

    have_visual = table_exists(conn_v14, "visual_nodes")
    visual_join = (
        "LEFT JOIN visual_nodes vn ON vn.paper_id = a.paper_id"
        if have_visual
        else ""
    )
    visual_cols = (
        "vn.branch_id AS branch_id, vn.cluster_id AS cluster_id,"
        if have_visual
        else "NULL AS branch_id, NULL AS cluster_id,"
    )

    rows = conn_v14.execute(
        f"""
        SELECT
            a.atom_id,
            a.paper_id,
            a.description,
            COALESCE(a.keyword, '') AS keyword,
            COALESCE(a.severity, 'medium') AS severity,
            COALESCE(a.evidence_source, 'unknown') AS evidence_source,
            COALESCE(a.evidence_quality, 'unknown') AS evidence_quality,
            COALESCE(a.evidence_weight, 0.35) AS evidence_weight,
            COALESCE(a.source_section_name, '') AS source_section_name,
            COALESCE(a.extractor_method, '') AS extractor_method,
            {visual_cols}
            COALESCE(a.extracted_at, '') AS extracted_at
        FROM limitation_atoms a
        {visual_join}
        """
    ).fetchall()
    if not rows:
        return []

    paper_ids = sorted({str(r["paper_id"]) for r in rows if r["paper_id"]})
    paper_meta: dict[str, dict] = {}
    if paper_ids:
        placeholders = ",".join("?" * len(paper_ids))
        scope_sql = (
            "AND id IN (SELECT paper_id FROM temp.v14b_corpus_papers)"
            if corpus_id
            else ""
        )
        p_rows = conn_main.execute(
            f"""
            SELECT id, title, publication_year, COALESCE(primary_field_id, '') AS primary_field_id
            FROM papers
            WHERE id IN ({placeholders})
              {scope_sql}
            """,
            paper_ids,
        ).fetchall()
        paper_meta = {str(r["id"]): dict(r) for r in p_rows}
    section_provenance = load_section_provenance_index(
        conn_main,
        paper_ids,
        corpus_id=corpus_id,
    )

    resolved_map: dict[int, tuple[int, int]] = {}
    if table_exists(conn_v14, "limitation_resolutions"):
        rr = conn_v14.execute(
            """
            SELECT atom_id, MIN(COALESCE(resolution_year, 9999)) AS first_year, COUNT(*) AS n
            FROM limitation_resolutions
            WHERE COALESCE(confidence, 0) >= 0.75
              AND (
                    evidence_text IS NULL
                    OR evidence_text != ?
              )
            GROUP BY atom_id
            """,
            (HEURISTIC_RESOLUTION_EVIDENCE_TEXT,),
        ).fetchall()
        resolved_map = {
            int(r[0]): (0 if r[1] == 9999 else int(r[1]), int(r[2]))
            for r in rr
        }

    atoms: list[dict] = []
    for row in rows:
        atom = dict(row)
        meta = paper_meta.get(str(atom.get("paper_id") or ""), {})
        if corpus_id and not meta:
            continue
        atom["paper_title"] = meta.get("title") or ""
        atom["publication_year"] = meta.get("publication_year")
        atom["primary_field_id"] = meta.get("primary_field_id") or ""
        section_key = (
            str(atom.get("paper_id") or ""),
            _normalize_section_name(str(atom.get("source_section_name") or "")),
        )
        provenance = section_provenance.get(section_key, {})
        atom["section_provenance_strength"] = provenance.get("section_provenance_strength") or (
            "weak" if atom.get("evidence_quality") == "section_level" else "none"
        )
        atom["section_extraction_strategies"] = provenance.get("section_extraction_strategies") or []
        atom["section_parser_contract_version"] = provenance.get("section_parser_contract_version") or (
            "legacy_unknown_contract" if atom["section_provenance_strength"] != "none" else "none"
        )
        atom["section_decision_grade"] = bool(provenance.get("section_decision_grade"))
        atom_id = int(atom.get("atom_id") or 0)
        resolved = resolved_map.get(atom_id)
        if resolved:
            atom["is_resolved"] = 1
            atom["resolved_year"] = int(resolved[0]) if resolved[0] else None
            atom["n_resolutions"] = int(resolved[1])
        else:
            atom["is_resolved"] = 0
            atom["resolved_year"] = None
            atom["n_resolutions"] = 0
        year = atom.get("publication_year")
        atom["publication_year"] = int(year) if year else 2000
        atoms.append(atom)
    return atoms


def load_future_edges(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    *,
    corpus_id: str | None = None,
) -> list[dict]:
    if not table_exists(conn_v14, "predicted_future_edges"):
        return []
    have_visual = table_exists(conn_v14, "visual_nodes")
    visual_join = (
        "LEFT JOIN visual_nodes vn ON vn.paper_id = pfe.dst_paper_id"
        if have_visual
        else ""
    )
    visual_col = "vn.branch_id AS dst_branch_id," if have_visual else "NULL AS dst_branch_id,"
    rows = conn_v14.execute(
        f"""
        SELECT
            pfe.src_paper_id,
            pfe.dst_paper_id,
            COALESCE(pfe.prediction_confidence, pfe.calibrated_prob, pfe.predicted_prob, 0) AS confidence,
            COALESCE(pfe.predicted_prob, 0) AS predicted_prob,
            COALESCE(pfe.is_cross_field, 0) AS is_cross_field,
            COALESCE(pfe.calibration_label, 'unknown') AS calibration_label,
            {visual_col}
            COALESCE(pfe.src_year, 0) AS src_year_raw,
            COALESCE(pfe.dst_year, 0) AS dst_year_raw
        FROM predicted_future_edges pfe
        {visual_join}
        """
    ).fetchall()
    if not rows:
        return []

    ids = sorted(
        {
            str(r["src_paper_id"])
            for r in rows
            if r["src_paper_id"]
        }
        | {
            str(r["dst_paper_id"])
            for r in rows
            if r["dst_paper_id"]
        }
    )
    meta: dict[str, dict] = {}
    if ids:
        placeholders = ",".join("?" * len(ids))
        scope_sql = (
            "AND id IN (SELECT paper_id FROM temp.v14b_corpus_papers)"
            if corpus_id
            else ""
        )
        p_rows = conn_main.execute(
            f"""
            SELECT
                id,
                COALESCE(publication_year, 0) AS publication_year,
                COALESCE(title, '') AS title,
                COALESCE(abstract, '') AS abstract,
                COALESCE(primary_field_id, '') AS primary_field_id
            FROM papers
            WHERE id IN ({placeholders})
              {scope_sql}
            """,
            ids,
        ).fetchall()
        meta = {str(r["id"]): dict(r) for r in p_rows}

    enriched = []
    for row in rows:
        rec = dict(row)
        if corpus_id and (
            str(rec.get("src_paper_id") or "") not in meta
            or str(rec.get("dst_paper_id") or "") not in meta
        ):
            continue
        src = meta.get(str(rec.get("src_paper_id") or ""), {})
        dst = meta.get(str(rec.get("dst_paper_id") or ""), {})
        rec["src_year"] = int(src.get("publication_year") or rec.get("src_year_raw") or 0)
        rec["dst_year"] = int(dst.get("publication_year") or rec.get("dst_year_raw") or 0)
        rec["dst_title"] = dst.get("title") or ""
        rec["dst_abstract"] = dst.get("abstract") or ""
        rec["dst_field"] = dst.get("primary_field_id") or ""
        enriched.append(rec)
    return enriched


def load_future_directions(conn_v14: sqlite3.Connection) -> list[dict]:
    if not table_exists(conn_v14, "future_directions"):
        return []
    rows = conn_v14.execute(
        """
        SELECT
            direction_id,
            direction_name,
            COALESCE(confidence, 0) AS confidence,
            COALESCE(evidence_tier, 'unknown') AS evidence_tier,
            COALESCE(claim_scope, 'unknown') AS claim_scope,
            COALESCE(main_path_evidence, '') AS main_path_evidence,
            COALESCE(vgae_evidence, '') AS vgae_evidence,
            COALESCE(limitation_evidence, '') AS limitation_evidence,
            COALESCE(paper_ids_json, '[]') AS paper_ids_json,
            COALESCE(evidence_json, '{}') AS evidence_json,
            COALESCE(calibration_label, '') AS calibration_label
        FROM future_directions
        """
    ).fetchall()
    return [dict(r) for r in rows]


def load_section_page_index(
    conn_main: sqlite3.Connection,
    *,
    corpus_id: str | None = None,
) -> dict[tuple[str, str], list[int]]:
    table_names = {
        row[0] for row in conn_main.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    table = "paper_sections" if "paper_sections" in table_names else None
    if not table:
        return {}

    cols = {
        row[1] for row in conn_main.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }
    if "section_pages_json" not in cols:
        return {}

    scope_sql = (
        "WHERE paper_id IN (SELECT paper_id FROM temp.v14b_corpus_papers)"
        if corpus_id else ""
    )
    rows = conn_main.execute(
        f"""
        SELECT paper_id, section_name, COALESCE(section_pages_json, '[]') AS pages_json
        FROM {table}
        {scope_sql}
        """
    ).fetchall()
    out: dict[tuple[str, str], list[int]] = {}
    for row in rows:
        key = (str(row["paper_id"]), str(row["section_name"] or "").strip().lower())
        pages = _safe_json_loads(row["pages_json"], [])
        if not isinstance(pages, list):
            pages = []
        out[key] = sorted(
            {
                int(p)
                for p in pages
                if isinstance(p, (int, float, str)) and str(p).isdigit() and int(p) > 0
            }
        )
    return out


def load_resolution_rows(conn_v14: sqlite3.Connection) -> list[dict]:
    if not table_exists(conn_v14, "limitation_resolutions"):
        return []
    rows = conn_v14.execute(
        """
        SELECT atom_id, resolver_paper_id, resolution_year, confidence, evidence_text
        FROM limitation_resolutions
        """
    ).fetchall()
    return [dict(r) for r in rows]


def load_section_atom_chains(
    conn_main: sqlite3.Connection,
    *,
    corpus_id: str | None = None,
) -> list[dict]:
    if not table_exists(conn_main, "section_atom_chains"):
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
            COALESCE(p.publication_year, 0) AS publication_year,
            COALESCE(p.primary_field_id, '') AS primary_field_id
        FROM section_atom_chains c
        LEFT JOIN papers p ON p.id = c.paper_id
        {scope_sql}
        ORDER BY c.paper_id, c.section_key, c.chain_index
        """
    ).fetchall()
    out: list[dict] = []
    for row in rows:
        chain = dict(row)
        chain["relation_edges"] = _safe_json_loads(chain.get("relation_edges_json") or "[]", [])
        chain["missing_stages"] = _safe_json_loads(chain.get("missing_stages_json") or "[]", [])
        chain["uncertainty_reasons"] = _safe_json_loads(chain.get("uncertainty_reasons_json") or "[]", [])
        chain["evidence_objects"] = _safe_json_loads(chain.get("evidence_objects_json") or "[]", [])
        out.append(chain)
    return out


def load_vgae_calibration_audit(conn_v14: sqlite3.Connection) -> dict:
    if not table_exists(conn_v14, "vgae_calibration_audit"):
        return {}
    row = conn_v14.execute(
        """
        SELECT method, label, support, base_rate, avg_raw_auc, avg_calibrated_auc,
               summary_json, rolling_backtest_json, curve_json
        FROM vgae_calibration_audit
        ORDER BY created_at DESC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return {}
    payload = dict(row)
    payload["summary"] = _safe_json_loads(payload.pop("summary_json", "{}"), {})
    payload["rolling_backtest"] = _safe_json_loads(payload.pop("rolling_backtest_json", "{}"), {})
    payload["curve"] = _safe_json_loads(payload.pop("curve_json", "[]"), [])
    return payload


def infer_root_constraint_type(principle_id: str, text: str) -> str:
    if COST_TERMS.search(text or ""):
        return "cost"
    return PRINCIPLE_TO_ROOT_CONSTRAINT.get(principle_id, "engineering")


def evidence_strength_level_from_atoms(atoms: list[dict]) -> str:
    if not atoms:
        return "weak"
    grade = grade_from_qualities(a.get("evidence_quality") for a in atoms)
    provenance = section_provenance_summary_from_atoms(atoms)
    strong_or_moderate = int(provenance.get("strong", 0)) + int(provenance.get("moderate", 0))
    strong = int(provenance.get("strong", 0))
    provenance_ratio = strong_or_moderate / max(1, len(atoms))
    strong_ratio = strong / max(1, len(atoms))
    if grade == "strong_section" and strong_ratio >= 0.70:
        return "strong"
    if grade in {"strong_section", "moderate_section"} and provenance_ratio >= 0.35:
        return "moderate"
    qualities = Counter((a.get("evidence_quality") or "unknown") for a in atoms)
    section = int(qualities.get("section_level", 0) + qualities.get("structured_sections", 0))
    weak = int(qualities.get("weak_abstract", 0))
    ratio = section / max(1, len(atoms))
    if ratio >= 0.70 and strong_ratio >= 0.70:
        return "strong"
    if ratio >= 0.35 and provenance_ratio >= 0.35 and weak < len(atoms):
        return "moderate"
    return "weak"


def section_provenance_summary_from_atoms(atoms: list[dict]) -> dict[str, Any]:
    strengths = Counter()
    strategies = Counter()
    contract_versions = Counter()
    current_contract = 0
    decision_grade = 0
    for atom in atoms:
        strength = str(atom.get("section_provenance_strength") or "").strip()
        if not strength:
            strength = "none" if atom.get("evidence_quality") != "section_level" else "weak"
        strengths[strength] += 1
        contract_version = str(atom.get("section_parser_contract_version") or "legacy_unknown_contract")
        if strength != "none":
            contract_versions[contract_version] += 1
            if contract_version == SECTION_PARSER_CONTRACT_VERSION:
                current_contract += 1
        atom_decision_grade = bool(atom.get("section_decision_grade")) or (
            contract_version == SECTION_PARSER_CONTRACT_VERSION
            and strength in {"strong", "moderate"}
        )
        if atom_decision_grade:
            decision_grade += 1
        for strategy in atom.get("section_extraction_strategies") or []:
            strategies[str(strategy)] += 1
    return {
        "strong": int(strengths.get("strong", 0)),
        "moderate": int(strengths.get("moderate", 0)),
        "weak": int(strengths.get("weak", 0)),
        "none": int(strengths.get("none", 0)),
        "current_contract": current_contract,
        "decision_grade": decision_grade,
        "contract_versions": dict(sorted(contract_versions.items())),
        "strategies": dict(sorted(strategies.items())),
    }


def minimal_experiment_template(
    *,
    root_type: str,
    keyword: str,
) -> dict:
    kw = keyword or "target bottleneck"
    if root_type == "physical":
        return {
            "experiment": f"Build A/B prototype isolating `{kw}` and measure physical constraint margins.",
            "cost_level": "medium",
            "cycle_weeks": 6,
            "success_criteria": [
                "Measured constraint margin improves >=20% vs baseline",
                "Performance gain remains stable across 3 repeated runs",
            ],
            "falsification_conditions": [
                "Improvement is below 10% vs baseline",
                "Repeated runs show unstable or reversed gains",
            ],
        }
    if root_type == "data":
        return {
            "experiment": f"Run held-out-distribution validation focused on `{kw}` with explicit failure slicing.",
            "cost_level": "low",
            "cycle_weeks": 3,
            "success_criteria": [
                "Out-of-distribution failure rate drops >=15%",
                "No significant regression on in-distribution benchmark",
            ],
            "falsification_conditions": [
                "Out-of-distribution failure rate drops <5%",
                "In-distribution benchmark regresses by more than 5%",
            ],
        }
    if root_type == "cost":
        return {
            "experiment": f"Run cost-per-result benchmark for `{kw}` under fixed throughput target.",
            "cost_level": "low",
            "cycle_weeks": 2,
            "success_criteria": [
                "Cost/latency improves >=20%",
                "Quality metrics stay within 5% of baseline",
            ],
            "falsification_conditions": [
                "Cost/latency improvement is below 10%",
                "Quality metrics degrade by more than 5%",
            ],
        }
    return {
        "experiment": f"Implement minimal system refactor targeting `{kw}` and benchmark integration overhead.",
        "cost_level": "medium",
        "cycle_weeks": 4,
        "success_criteria": [
            "Integration complexity (time or lines touched) reduced >=20%",
            "Core task performance no worse than baseline",
        ],
        "falsification_conditions": [
            "Integration complexity is not measurably reduced",
            "Core task performance drops below baseline",
        ],
    }


def _claim_gate_labels(gates: dict[str, bool]) -> list[str]:
    labels = {
        "root_constraint": "root constraint",
        "past_attempts_10y": "historical attempts and failure evidence",
        "new_enablers": "new enabling condition",
        "unresolved_bottleneck": "unresolved bottleneck evidence",
        "minimal_validation_experiment": "minimal validation experiment with success and falsification criteria",
    }
    return [labels.get(k, k) for k, ok in gates.items() if not ok]


def _high_confidence_gate_labels(gates: dict[str, bool]) -> list[str]:
    labels = {
        "five_question_complete": "complete five-question Claim Card",
        "section_evidence_strong": "strong section-level evidence",
        "section_provenance_ready": "strong or moderate section parser provenance",
        "section_decision_grade_ready": "current parser-contract decision-grade section evidence",
        "calibration_ready": "future-growth calibration available",
        "rolling_auc_ready": "rolling held-out-year AUC >= 0.65",
        "candidate_score_ready": "future candidate score >= 0.70",
        "fusion_tier_ready": "triangulated Step6 fusion evidence",
    }
    return [labels.get(k, k) for k, ok in gates.items() if not ok]


def _claim_card_evidence_grade(*, five_complete: bool, high_confidence_eligible: bool) -> str:
    if high_confidence_eligible:
        return "decision_grade_claim_card"
    if five_complete:
        return "complete_claim_card_pending_high_confidence_evidence"
    return "incomplete_claim_card"


def _claim_card_uncertainty_reasons(
    *,
    five_complete: bool,
    high_confidence_eligible: bool,
    missing_gates: list[str],
    missing_high_confidence_gates: list[str],
) -> list[str]:
    reasons = [
        *[f"missing five-question gate: {gate}" for gate in missing_gates],
        *[f"missing high-confidence gate: {gate}" for gate in missing_high_confidence_gates],
    ]
    if not five_complete:
        reasons.append("Claim Card is incomplete; direction remains candidate_pool_only")
    elif not high_confidence_eligible:
        reasons.append("complete Claim Card remains exploratory until high-confidence evidence gates pass")
    return sorted(set(reasons))


def _claim_card_evidence_objects(
    *,
    card_id: str,
    direction_id: int,
    direction_name: str,
    claim_scope: str,
    evidence_grade: str,
    root_constraint: dict[str, Any],
    attempts: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
    minimal_experiment: dict[str, Any],
    quality_gate: dict[str, Any],
) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = [
        {
            "type": "claim_card",
            "role": "five_question_contract",
            "source": "Step13 Claim Card",
            "id": card_id,
            "direction_id": direction_id,
            "label": direction_name,
            "claim_scope": claim_scope,
            "evidence_grade": evidence_grade,
            "five_question_complete": bool(quality_gate.get("five_question_complete")),
            "high_confidence_eligible": bool(quality_gate.get("high_confidence_eligible")),
        }
    ]
    if minimal_experiment:
        objects.append(
            {
                "type": "minimal_validation_experiment",
                "role": "falsifiable_validation",
                "source": "Step13 Claim Card",
                "id": card_id,
                "direction_id": direction_id,
                "label": minimal_experiment.get("experiment") or "minimal validation experiment",
                "claim_scope": claim_scope,
                "evidence_grade": evidence_grade,
                "success_criteria": minimal_experiment.get("success_criteria") or [],
                "falsification_conditions": minimal_experiment.get("falsification_conditions") or [],
            }
        )
    if root_constraint:
        objects.append(
            {
                "type": "claim_card_root_constraint",
                "role": "root_constraint",
                "source": "Step13 Claim Card",
                "id": root_constraint.get("principle_id") or card_id,
                "direction_id": direction_id,
                "label": root_constraint.get("type") or "root constraint",
                "description": root_constraint.get("constraint"),
                "claim_scope": claim_scope,
                "evidence_grade": evidence_grade,
            }
        )
    for attempt in attempts[:4]:
        objects.append(
            {
                "type": "claim_card_attempt",
                "role": "past_attempt_failure",
                "source": "Step13 Claim Card",
                "id": attempt.get("paper_id") or card_id,
                "direction_id": direction_id,
                "paper_id": attempt.get("paper_id"),
                "label": attempt.get("attempt_path") or attempt.get("keyword") or "past attempt",
                "description": attempt.get("why_failed"),
                "event_year": attempt.get("year"),
                "claim_scope": claim_scope,
                "evidence_grade": evidence_grade,
                "evidence_quality": attempt.get("evidence_quality"),
                "section_provenance_strength": attempt.get("section_provenance_strength"),
                "click_target": {"kind": "paper", "id": attempt.get("paper_id")} if attempt.get("paper_id") else None,
            }
        )
    for bottleneck in unresolved[:4]:
        objects.append(
            {
                "type": "claim_card_unresolved_bottleneck",
                "role": "open_bottleneck",
                "source": "Step13 Claim Card",
                "id": bottleneck.get("paper_id") or card_id,
                "direction_id": direction_id,
                "paper_id": bottleneck.get("paper_id"),
                "label": bottleneck.get("keyword") or "unresolved bottleneck",
                "description": bottleneck.get("description"),
                "claim_scope": claim_scope,
                "evidence_grade": evidence_grade,
                "evidence_quality": bottleneck.get("evidence_quality"),
                "section_provenance_strength": bottleneck.get("section_provenance_strength"),
                "click_target": {"kind": "paper", "id": bottleneck.get("paper_id")} if bottleneck.get("paper_id") else None,
            }
        )
    return [obj for obj in objects if obj]


def score_atom(atom: dict) -> float:
    severity = str(atom.get("severity") or "medium").lower()
    severity_w = SEVERITY_WEIGHT.get(severity, 0.55)
    evidence_w = float(atom.get("evidence_weight") or 0.35)
    evidence_w = min(1.0, max(0.05, evidence_w))
    return severity_w * evidence_w


def _safe_json_loads(value: str, default: Any) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return default


def _top_counter(counter: Counter, n: int = 8) -> list[dict]:
    out = []
    for key, value in counter.most_common(n):
        out.append({"key": key, "value": value})
    return out


def _risk_label(*, unresolved: int, resolved: int, section_ratio: float, future_matches: int) -> str:
    if unresolved >= max(6, resolved * 2) and future_matches < 3:
        return "high_unresolved_pressure"
    if section_ratio < 0.40:
        return "evidence_weak_section_coverage"
    if unresolved > resolved:
        return "moderate_with_uncertainty"
    return "managed_or_resolving"


def build_principle_summary(
    atoms: list[dict],
    future_edges: list[dict],
    future_directions: list[dict],
) -> tuple[list[dict], list[dict], dict]:
    by_principle: dict[str, dict] = {}
    year_min = 9999
    year_max = 0
    total_section_level = 0

    for atom in atoms:
        text = " ".join(
            [
                str(atom.get("keyword") or ""),
                str(atom.get("description") or ""),
                str(atom.get("source_section_name") or ""),
                str(atom.get("paper_title") or ""),
            ]
        )
        p = classify_principle(text)
        pid = p.principle_id
        score = score_atom(atom)
        year = int(atom.get("publication_year") or 2000)
        year_min = min(year_min, year)
        year_max = max(year_max, year)

        entry = by_principle.setdefault(
            pid,
            {
                "principle": p,
                "score_total": 0.0,
                "resolved_atoms": 0,
                "unresolved_atoms": 0,
                "open_score_by_year": defaultdict(float),
                "resolved_score_by_year": defaultdict(float),
                "open_atoms_by_year": defaultdict(int),
                "resolved_atoms_by_year": defaultdict(int),
                "keywords": Counter(),
                "branches": Counter(),
                "qualities": Counter(),
                "fields": Counter(),
                "top_atoms": [],
                "section_level_atoms": 0,
            },
        )

        entry["score_total"] += score
        entry["open_score_by_year"][year] += score
        entry["open_atoms_by_year"][year] += 1

        kw = (atom.get("keyword") or "").strip().lower()
        if kw:
            entry["keywords"][kw] += 1

        branch_id = (atom.get("branch_id") or "").strip()
        if branch_id:
            entry["branches"][branch_id] += score

        quality = (atom.get("evidence_quality") or "unknown").strip()
        entry["qualities"][quality] += 1
        field = (atom.get("primary_field_id") or "").strip()
        if field:
            entry["fields"][field] += 1

        if quality == "section_level" or atom.get("evidence_source") == "structured_sections":
            entry["section_level_atoms"] += 1
            total_section_level += 1

        if int(atom.get("is_resolved") or 0) == 1:
            entry["resolved_atoms"] += 1
            ryear = atom.get("resolved_year")
            if ryear:
                ryear_i = int(ryear)
                entry["resolved_score_by_year"][ryear_i] += score
                entry["resolved_atoms_by_year"][ryear_i] += 1
                year_max = max(year_max, ryear_i)
        else:
            entry["unresolved_atoms"] += 1

        entry["top_atoms"].append(
            {
                "atom_id": int(atom.get("atom_id") or 0),
                "paper_id": atom.get("paper_id"),
                "paper_title": atom.get("paper_title") or "",
                "year": year,
                "score": score,
                "severity": atom.get("severity"),
                "keyword": atom.get("keyword") or "",
                "description": atom.get("description") or "",
                "branch_id": atom.get("branch_id"),
                "evidence_quality": quality,
                "section_provenance_strength": atom.get("section_provenance_strength"),
                "section_extraction_strategies": atom.get("section_extraction_strategies") or [],
                "is_resolved": int(atom.get("is_resolved") or 0),
            }
        )

    if year_min == 9999:
        year_min = datetime.now().year
        year_max = year_min
    year_max = max(year_max, datetime.now().year)

    # future edge / direction 归因
    future_by_principle: dict[str, list[dict]] = defaultdict(list)
    for edge in future_edges:
        text = " ".join([edge.get("dst_title") or "", edge.get("dst_abstract") or ""])
        p = classify_principle(text)
        future_by_principle[p.principle_id].append(edge)

    dir_by_principle: dict[str, Counter] = defaultdict(Counter)
    for d in future_directions:
        text = " ".join(
            [
                d.get("direction_name") or "",
                d.get("limitation_evidence") or "",
                d.get("main_path_evidence") or "",
                d.get("vgae_evidence") or "",
            ]
        )
        p = classify_principle(text)
        tier = d.get("evidence_tier") or "unknown"
        dir_by_principle[p.principle_id][tier] += 1

    principle_rows: list[dict] = []
    history_rows: list[dict] = []
    for pid, payload in sorted(by_principle.items(), key=lambda kv: kv[1]["score_total"], reverse=True):
        p = payload["principle"]
        backlog = 0.0
        peak_backlog = 0.0
        peak_year = None
        emergence_year = None
        history_keywords = _top_counter(payload["keywords"], n=5)
        for y in range(year_min, year_max + 1):
            opened_score = float(payload["open_score_by_year"].get(y, 0.0))
            resolved_score = float(payload["resolved_score_by_year"].get(y, 0.0))
            opened_atoms = int(payload["open_atoms_by_year"].get(y, 0))
            resolved_atoms = int(payload["resolved_atoms_by_year"].get(y, 0))
            backlog = max(0.0, backlog + opened_score - resolved_score)
            if opened_atoms > 0 and emergence_year is None:
                emergence_year = y
            if backlog >= peak_backlog:
                peak_backlog = backlog
                peak_year = y
            if opened_atoms == 0 and resolved_atoms == 0:
                continue
            history_rows.append(
                {
                    "principle_id": pid,
                    "event_year": y,
                    "opened_atoms": opened_atoms,
                    "resolved_atoms": resolved_atoms,
                    "opened_score": round(opened_score, 6),
                    "resolved_score": round(resolved_score, 6),
                    "backlog_score": round(backlog, 6),
                    "top_keywords_json": jdumps(history_keywords),
                }
            )

        top_atoms = sorted(
            payload["top_atoms"],
            key=lambda x: (1 - int(x["is_resolved"]), x["score"]),
            reverse=True,
        )[:8]
        future_matches = sorted(
            future_by_principle.get(pid, []),
            key=lambda x: float(x.get("confidence") or 0.0),
            reverse=True,
        )[:8]
        cross_field = sum(1 for x in future_by_principle.get(pid, []) if int(x.get("is_cross_field") or 0) == 1)
        section_ratio = payload["section_level_atoms"] / max(
            1,
            payload["resolved_atoms"] + payload["unresolved_atoms"],
        )
        risk_label = _risk_label(
            unresolved=payload["unresolved_atoms"],
            resolved=payload["resolved_atoms"],
            section_ratio=section_ratio,
            future_matches=len(future_matches),
        )
        principle_rows.append(
            {
                "principle_id": pid,
                "principle_name": p.name,
                "root_cause": p.root_cause,
                "bottleneck_score": round(float(payload["score_total"]), 6),
                "unresolved_atoms": int(payload["unresolved_atoms"]),
                "resolved_atoms": int(payload["resolved_atoms"]),
                "emergence_year": int(emergence_year) if emergence_year else None,
                "peak_backlog_year": int(peak_year) if peak_year else None,
                "current_backlog": round(float(backlog), 6),
                "evidence_quality_json": jdumps(dict(payload["qualities"])),
                "top_keywords_json": jdumps(_top_counter(payload["keywords"], n=10)),
                "top_branches_json": jdumps(_top_counter(payload["branches"], n=8)),
                "top_papers_json": jdumps(top_atoms),
                "future_alignment_json": jdumps(
                    {
                        "future_edge_matches": len(future_matches),
                        "cross_field_matches": int(cross_field),
                        "top_future_edges": [
                            {
                                "src_paper_id": e.get("src_paper_id"),
                                "dst_paper_id": e.get("dst_paper_id"),
                                "confidence": float(e.get("confidence") or 0.0),
                                "calibration_label": e.get("calibration_label"),
                                "dst_branch_id": e.get("dst_branch_id"),
                            }
                            for e in future_matches
                        ],
                        "cross_domain_duals": list(p.cross_domain_duals),
                    }
                ),
                "direction_tier_json": jdumps(dict(dir_by_principle.get(pid, Counter()))),
                "risk_label": risk_label,
                "notes_json": jdumps(
                    {
                        "section_level_ratio": round(section_ratio, 4),
                        "top_fields": _top_counter(payload["fields"], n=5),
                    }
                ),
            }
        )

    totals = {
        "atoms_total": len(atoms),
        "principles_total": len(principle_rows),
        "section_level_total": int(total_section_level),
        "future_edges_total": len(future_edges),
        "future_directions_total": len(future_directions),
        "year_min": year_min,
        "year_max": year_max,
    }
    return principle_rows, history_rows, totals


def _normalize_section_name(raw: str) -> str:
    name = (raw or "").strip().lower()
    if not name:
        return ""
    return name


def _resolution_row_is_validated(row: dict) -> bool:
    evidence = str(row.get("evidence_text") or "").strip()
    confidence = float(row.get("confidence") or 0.0)
    return confidence >= 0.75 and evidence != HEURISTIC_RESOLUTION_EVIDENCE_TEXT


def build_bottleneck_lineage_triples(
    *,
    atoms: list[dict],
    resolution_rows: list[dict],
    section_pages: dict[tuple[str, str], list[int]],
    future_directions: list[dict],
    section_atom_chains: list[dict] | None = None,
) -> list[dict]:
    direction_by_paper: dict[str, list[dict]] = defaultdict(list)
    direction_tokens: dict[int, set[str]] = {}
    for d in future_directions:
        did = int(d.get("direction_id") or 0)
        if did <= 0:
            continue
        pids = _safe_json_loads(d.get("paper_ids_json") or "[]", [])
        if isinstance(pids, list):
            for pid in pids:
                if pid:
                    direction_by_paper[str(pid)].append(d)
        direction_tokens[did] = {
            t for t in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{2,}", (d.get("direction_name") or "").lower())
        }

    triples: list[dict] = []
    if section_atom_chains:
        triples.extend(
            build_section_atom_chain_lineage_triples(
                section_atom_chains=section_atom_chains,
                direction_by_paper=direction_by_paper,
                direction_tokens=direction_tokens,
            )
        )

    resolution_by_atom: dict[int, list[dict]] = defaultdict(list)
    for r in resolution_rows:
        resolution_by_atom[int(r.get("atom_id") or 0)].append(r)

    keyword_future_atoms: dict[str, list[dict]] = defaultdict(list)
    for atom in atoms:
        kw = (atom.get("keyword") or "").strip().lower()
        if kw:
            keyword_future_atoms[kw].append(atom)
    for kw in keyword_future_atoms:
        keyword_future_atoms[kw].sort(key=lambda x: int(x.get("publication_year") or 0))

    for atom in atoms:
        atom_id = int(atom.get("atom_id") or 0)
        desc = str(atom.get("description") or "").strip()
        kw = (atom.get("keyword") or "").strip().lower() or "unknown_constraint"
        year = int(atom.get("publication_year") or 0)
        paper_id = str(atom.get("paper_id") or "")
        section_name = _normalize_section_name(str(atom.get("source_section_name") or ""))
        pages = section_pages.get((paper_id, section_name), [])
        principle = classify_principle(
            " ".join(
                [
                    str(atom.get("keyword") or ""),
                    desc,
                    str(atom.get("paper_title") or ""),
                ]
            )
        )
        root_type = infer_root_constraint_type(principle.principle_id, desc)

        direction_id = None
        if direction_by_paper.get(paper_id):
            direction_id = int(direction_by_paper[paper_id][0].get("direction_id") or 0) or None
        if direction_id is None:
            for did, toks in direction_tokens.items():
                if kw and kw.replace(" ", "") and any(kw_part in toks for kw_part in kw.split()):
                    direction_id = did
                    break

        constraint_text = f"{root_type}:{kw}"
        failure_text = desc[:280]
        attempt_text = "missing evidence: no linked attempted path"
        local_fix_text = "missing evidence: no validated local fix"
        next_constraint_text = "missing evidence: no follow-on constraint"
        rel_rows = resolution_by_atom.get(atom_id, [])
        validated_rel_rows = [row for row in rel_rows if _resolution_row_is_validated(row)]
        if rel_rows:
            best = max(rel_rows, key=lambda r: float(r.get("confidence") or 0.0))
            attempt_text = f"candidate_resolver:{best.get('resolver_paper_id')}"
        if validated_rel_rows:
            best = max(validated_rel_rows, key=lambda r: float(r.get("confidence") or 0.0))
            attempt_text = f"validated_resolver:{best.get('resolver_paper_id')}"
            local_fix_text = str(best.get("evidence_text") or "reported mitigation")[:280]
        siblings = keyword_future_atoms.get(kw, [])
        newer = [a for a in siblings if int(a.get("publication_year") or 0) > year]
        if newer:
            next_constraint_text = str(newer[0].get("description") or "")[:280]

        placeholder_stages = []
        stage_evidence = {
            "constraint": "principle_keyword_classification",
            "failure_mechanism": "limitation_atom_description",
            "attempt_path": "candidate_resolution_record" if rel_rows else "missing_resolution_evidence",
            "local_fix": (
                "validated_resolution_evidence_text"
                if validated_rel_rows else
                "missing_validated_local_fix_evidence"
            ),
            "new_constraint": "later_same_keyword_atom" if newer else "missing_follow_on_constraint",
        }
        if not rel_rows:
            placeholder_stages.append("attempt_path")
        if not validated_rel_rows:
            placeholder_stages.append("local_fix")
        if not newer:
            placeholder_stages.append("new_constraint")
        typed_chain_complete = not placeholder_stages
        if typed_chain_complete:
            typed_chain_completeness = "full"
        elif validated_rel_rows:
            typed_chain_completeness = "validated_resolution_partial"
        elif rel_rows:
            typed_chain_completeness = "resolution_candidate_partial"
        else:
            typed_chain_completeness = "constraint_failure_only"
        lineage_missing_reasons = [
            {
                "stage": stage,
                "reason": stage_evidence.get(stage),
            }
            for stage in placeholder_stages
        ]

        def add_edge(
            edge_order: int,
            src_stage: str,
            dst_stage: str,
            src_text: str,
            dst_text: str,
            relation_type: str,
            resolver_paper_id: str | None = None,
            event_year: int | None = None,
        ) -> None:
            triple_id = f"{atom_id}:{edge_order}:{direction_id or 'na'}"
            triples.append(
                {
                    "triple_id": triple_id,
                    "principle_id": principle.principle_id,
                    "direction_id": direction_id,
                    "atom_id": atom_id,
                    "edge_order": edge_order,
                    "source_stage": src_stage,
                    "target_stage": dst_stage,
                    "source_text": src_text[:280],
                    "target_text": dst_text[:280],
                    "relation_type": relation_type,
                    "paper_id": paper_id,
                    "resolver_paper_id": resolver_paper_id,
                    "event_year": int(event_year or year or 0),
                    "evidence_section": section_name or None,
                    "evidence_page": int(pages[0]) if pages else None,
                    "evidence_quality": atom.get("evidence_quality") or "unknown",
                    "evidence_weight": float(atom.get("evidence_weight") or 0.35),
                    "metadata_json": jdumps(
                        {
                            "root_constraint_type": root_type,
                            "severity": atom.get("severity"),
                            "n_resolutions": len(rel_rows),
                            "n_validated_resolutions": len(validated_rel_rows),
                            "page_candidates": pages,
                            "lineage_schema": [
                                "constraint",
                                "failure_mechanism",
                                "attempt_path",
                                "local_fix",
                                "new_constraint",
                            ],
                            "evidence_grade": grade_from_qualities([atom.get("evidence_quality")]),
                            "section_provenance_strength": atom.get("section_provenance_strength"),
                            "section_extraction_strategies": atom.get("section_extraction_strategies") or [],
                            "stage_evidence": stage_evidence,
                            "typed_chain_complete": typed_chain_complete,
                            "typed_chain_completeness": typed_chain_completeness,
                            "placeholder_stages": placeholder_stages,
                            "lineage_missing_reasons": lineage_missing_reasons,
                            "source_stage_evidence": stage_evidence.get(src_stage),
                            "target_stage_evidence": stage_evidence.get(dst_stage),
                            "target_stage_is_placeholder": dst_stage in placeholder_stages,
                            "lineage_contract": (
                                "complete_typed_chain"
                                if typed_chain_complete
                                else "partial_typed_chain_with_explicit_missing_stages"
                            ),
                            "claim_policy": "lineage evidence only; not a standalone prediction",
                        }
                    ),
                }
            )

        add_edge(
            1,
            "constraint",
            "failure_mechanism",
            constraint_text,
            failure_text,
            "constraint_causes_failure",
        )
        add_edge(
            2,
            "failure_mechanism",
            "attempt_path",
            failure_text,
            attempt_text,
            "failure_triggers_attempt",
        )
        add_edge(
            3,
            "attempt_path",
            "local_fix",
            attempt_text,
            local_fix_text,
            "attempt_produces_local_fix",
            resolver_paper_id=(rel_rows[0].get("resolver_paper_id") if rel_rows else None),
            event_year=(
                int(rel_rows[0].get("resolution_year") or year)
                if rel_rows else year
            ),
        )
        add_edge(
            4,
            "local_fix",
            "new_constraint",
            local_fix_text,
            next_constraint_text,
            "local_fix_reveals_new_constraint",
        )
    return triples


def build_section_atom_chain_lineage_triples(
    *,
    section_atom_chains: list[dict],
    direction_by_paper: dict[str, list[dict]],
    direction_tokens: dict[int, set[str]],
) -> list[dict]:
    triples: list[dict] = []
    for chain in section_atom_chains:
        chain_id = str(chain.get("chain_id") or "")
        if not chain_id:
            continue
        paper_id = str(chain.get("paper_id") or "")
        section_name = _normalize_section_name(str(chain.get("section_name") or chain.get("section_key") or ""))
        stage_texts = {
            "constraint": str(chain.get("constraint_text") or ""),
            "failure_mechanism": str(chain.get("failure_mechanism_text") or ""),
            "attempt_path": str(chain.get("attempted_path_text") or ""),
            "local_fix": str(chain.get("local_fix_text") or ""),
            "new_constraint": str(chain.get("new_constraint_text") or ""),
        }
        stage_atom_ids = {
            "constraint": chain.get("constraint_atom_id"),
            "failure_mechanism": chain.get("failure_mechanism_atom_id"),
            "attempt_path": chain.get("attempted_path_atom_id"),
            "local_fix": chain.get("local_fix_atom_id"),
            "new_constraint": chain.get("new_constraint_atom_id"),
        }
        present_stages = {stage for stage, atom_id in stage_atom_ids.items() if atom_id}
        missing_stages = [
            _normalize_chain_stage(stage)
            for stage in (chain.get("missing_stages") or _safe_json_loads(chain.get("missing_stages_json") or "[]", []))
        ]
        typed_chain_complete = bool(int(chain.get("typed_chain_complete") or 0))
        typed_chain_completeness = str(chain.get("typed_chain_completeness") or "partial")
        evidence_grade = str(chain.get("evidence_grade") or "partial_typed_section_lineage")
        claim_scope = str(chain.get("claim_scope") or "exploratory_bottleneck_lineage")
        evidence_objects = chain.get("evidence_objects") or _safe_json_loads(chain.get("evidence_objects_json") or "[]", [])
        uncertainty_reasons = chain.get("uncertainty_reasons") or _safe_json_loads(
            chain.get("uncertainty_reasons_json") or "[]",
            [],
        )
        page_candidates = _chain_page_candidates(evidence_objects)
        combined_text = " ".join(
            [
                str(chain.get("paper_title") or ""),
                *(text for text in stage_texts.values() if text),
            ]
        )
        principle = classify_principle(combined_text)
        root_type = infer_root_constraint_type(principle.principle_id, combined_text)
        direction_id = _direction_id_for_lineage(
            paper_id=paper_id,
            text=combined_text,
            direction_by_paper=direction_by_paper,
            direction_tokens=direction_tokens,
        )
        event_year = int(chain.get("publication_year") or 0)
        evidence_weight = _chain_evidence_weight(evidence_grade, typed_chain_complete=typed_chain_complete)
        stage_evidence = {
            stage: (
                f"section_atom:{stage_atom_ids[stage]}"
                if stage_atom_ids.get(stage)
                else "missing_in_section_atom_chain"
            )
            for stage in ("constraint", "failure_mechanism", "attempt_path", "local_fix", "new_constraint")
        }
        lineage_missing_reasons = [
            {"stage": stage, "reason": "missing_in_section_atom_chain"}
            for stage in missing_stages
        ]
        relation_specs = [
            ("constraint", "failure_mechanism", "constraint_causes_failure"),
            ("failure_mechanism", "attempt_path", "failure_triggers_attempt"),
            ("attempt_path", "local_fix", "attempt_produces_local_fix"),
            ("local_fix", "new_constraint", "local_fix_reveals_new_constraint"),
        ]
        for edge_order, (src_stage, dst_stage, relation_type) in enumerate(relation_specs, start=1):
            src_text = stage_texts.get(src_stage) or f"missing evidence: no {src_stage}"
            dst_text = stage_texts.get(dst_stage) or f"missing evidence: no {dst_stage}"
            triples.append(
                {
                    "triple_id": f"chain:{chain_id}:{edge_order}:{direction_id or 'na'}",
                    "principle_id": principle.principle_id,
                    "direction_id": direction_id,
                    "atom_id": None,
                    "edge_order": edge_order,
                    "source_stage": src_stage,
                    "target_stage": dst_stage,
                    "source_text": src_text[:280],
                    "target_text": dst_text[:280],
                    "relation_type": relation_type,
                    "paper_id": paper_id,
                    "resolver_paper_id": None,
                    "event_year": event_year,
                    "evidence_section": section_name or None,
                    "evidence_page": int(page_candidates[0]) if page_candidates else None,
                    "evidence_quality": "section_level",
                    "evidence_weight": evidence_weight,
                    "metadata_json": jdumps(
                        {
                            "source": "section_atom_chain",
                            "section_atom_chain_id": chain_id,
                            "root_constraint_type": root_type,
                            "page_candidates": page_candidates,
                            "lineage_schema": [
                                "constraint",
                                "failure_mechanism",
                                "attempt_path",
                                "local_fix",
                                "new_constraint",
                            ],
                            "evidence_grade": evidence_grade,
                            "claim_scope": claim_scope,
                            "evidence_objects": evidence_objects,
                            "section_atom_ids": stage_atom_ids,
                            "stage_evidence": stage_evidence,
                            "typed_chain_complete": typed_chain_complete,
                            "typed_chain_completeness": typed_chain_completeness,
                            "placeholder_stages": missing_stages,
                            "lineage_missing_reasons": lineage_missing_reasons,
                            "chain_uncertainty_reasons": uncertainty_reasons,
                            "source_stage_evidence": stage_evidence.get(src_stage),
                            "target_stage_evidence": stage_evidence.get(dst_stage),
                            "source_stage_is_placeholder": src_stage not in present_stages,
                            "target_stage_is_placeholder": dst_stage not in present_stages,
                            "lineage_contract": (
                                "complete_typed_chain"
                                if typed_chain_complete
                                else "partial_typed_chain_with_explicit_missing_stages"
                            ),
                            "claim_policy": "lineage evidence only; Step13 Claim Card gates decide promotion",
                        }
                    ),
                }
            )
    return triples


def _normalize_chain_stage(stage: Any) -> str:
    raw = str(stage or "")
    return "attempt_path" if raw == "attempted_path" else raw


def _chain_page_candidates(evidence_objects: Any) -> list[int]:
    pages: set[int] = set()
    if not isinstance(evidence_objects, list):
        return []
    for obj in evidence_objects:
        if not isinstance(obj, dict):
            continue
        for key in ("page_start", "page_end"):
            value = obj.get(key)
            if isinstance(value, (int, float)) and int(value) > 0:
                pages.add(int(value))
    return sorted(pages)


def _chain_evidence_weight(evidence_grade: str, *, typed_chain_complete: bool) -> float:
    if evidence_grade == "typed_section_lineage":
        return 0.92
    if evidence_grade == "typed_section_lineage_traced":
        return 0.85
    if typed_chain_complete:
        return 0.70
    if evidence_grade == "partial_typed_section_lineage":
        return 0.68
    return 0.45


def _direction_id_for_lineage(
    *,
    paper_id: str,
    text: str,
    direction_by_paper: dict[str, list[dict]],
    direction_tokens: dict[int, set[str]],
) -> int | None:
    if direction_by_paper.get(paper_id):
        return int(direction_by_paper[paper_id][0].get("direction_id") or 0) or None
    text_tokens = {
        t for t in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{2,}", (text or "").lower())
    }
    best_direction = None
    best_overlap = 0
    for did, toks in direction_tokens.items():
        overlap = len(text_tokens & toks)
        if overlap > best_overlap:
            best_direction = did
            best_overlap = overlap
    return best_direction if best_overlap >= 2 else None


def build_direction_claim_cards(
    *,
    atoms: list[dict],
    future_directions: list[dict],
    principle_rows: list[dict],
    calibration_audit: dict,
) -> tuple[list[dict], list[dict]]:
    principles_by_id = {p["principle_id"]: p for p in principle_rows}
    now_year = datetime.utcnow().year
    atom_by_paper: dict[str, list[dict]] = defaultdict(list)
    for atom in atoms:
        atom_by_paper[str(atom.get("paper_id") or "")].append(atom)

    cards: list[dict] = []
    updates: list[dict] = []
    for d in future_directions:
        direction_id = int(d.get("direction_id") or 0)
        if direction_id <= 0:
            continue
        direction_name = str(d.get("direction_name") or "").strip() or f"direction_{direction_id}"
        pids = _safe_json_loads(d.get("paper_ids_json") or "[]", [])
        if not isinstance(pids, list):
            pids = []
        direction_atoms = [
            atom
            for pid in pids
            for atom in atom_by_paper.get(str(pid), [])
        ]
        if not direction_atoms:
            direction_atoms = [
                atom for atom in atoms
                if (atom.get("keyword") or "").lower() in direction_name.lower()
            ][:8]

        weighted_principles: Counter[str] = Counter()
        for atom in direction_atoms:
            pid = classify_principle(
                " ".join(
                    [
                        str(atom.get("keyword") or ""),
                        str(atom.get("description") or ""),
                        str(atom.get("paper_title") or ""),
                    ]
                )
            ).principle_id
            weighted_principles[pid] += float(score_atom(atom))
        top_principle_id = weighted_principles.most_common(1)[0][0] if weighted_principles else "FP_OTHER"
        top_principle = principles_by_id.get(top_principle_id, {})

        top_atom = sorted(
            direction_atoms,
            key=lambda a: float(score_atom(a)),
            reverse=True,
        )[0] if direction_atoms else {}
        root_text = (
            str(top_principle.get("root_cause") or "")
            or str(top_atom.get("description") or "")
            or "insufficient evidence"
        )
        root_type = infer_root_constraint_type(
            top_principle_id,
            " ".join(
                [root_text, str(top_atom.get("keyword") or ""), direction_name]
            ),
        )
        root_constraint = {
            "type": root_type,
            "constraint": root_text[:320],
            "principle_id": top_principle_id,
            "principle_name": top_principle.get("principle_name"),
        }

        attempts = []
        for atom in sorted(
            direction_atoms,
            key=lambda a: int(a.get("publication_year") or 0),
            reverse=True,
        ):
            year = int(atom.get("publication_year") or 0)
            if year and year < now_year - 10:
                continue
            attempts.append(
                {
                    "paper_id": atom.get("paper_id"),
                    "year": year,
                    "attempt_path": str(atom.get("paper_title") or "")[:180],
                    "why_failed": str(atom.get("description") or "")[:220],
                    "keyword": atom.get("keyword"),
                    "severity": atom.get("severity"),
                    "evidence_quality": atom.get("evidence_quality"),
                    "section_provenance_strength": atom.get("section_provenance_strength"),
                    "section_extraction_strategies": atom.get("section_extraction_strategies") or [],
                    "section_parser_contract_version": atom.get("section_parser_contract_version"),
                    "section_decision_grade": bool(atom.get("section_decision_grade")),
                }
            )
            if len(attempts) >= 8:
                break

        calibration_ready = bool(calibration_audit.get("method"))
        rolling_avg_auc = float(calibration_audit.get("avg_calibrated_auc") or 0.0)
        section_strength = evidence_strength_level_from_atoms(direction_atoms)
        section_provenance = section_provenance_summary_from_atoms(direction_atoms)
        strong_or_moderate_provenance = int(section_provenance.get("strong", 0)) + int(
            section_provenance.get("moderate", 0)
        )
        section_provenance_ready = strong_or_moderate_provenance >= max(
            1,
            int(0.35 * max(1, len(direction_atoms))),
        )
        decision_grade_sections = int(section_provenance.get("decision_grade") or 0)
        section_decision_grade_ready = decision_grade_sections >= max(
            1,
            int(0.35 * max(1, len(direction_atoms))),
        )
        new_enablers = []
        missing_enablers = []
        if calibration_ready and rolling_avg_auc >= 0.65:
            new_enablers.append("rolling held-out-year calibration supports the future-growth candidate")
        else:
            missing_enablers.append("rolling held-out-year calibration is missing or below threshold")
        if section_strength in {"moderate", "strong"}:
            new_enablers.append(
                f"{section_strength} section-level bottleneck evidence with parser provenance is available"
            )
        else:
            missing_enablers.append("section-level bottleneck evidence is weak or parser provenance is weak")
        if section_decision_grade_ready:
            new_enablers.append("current parser-contract decision-grade section evidence is available")
        else:
            missing_enablers.append(
                "current parser-contract decision-grade section evidence is missing or below threshold"
            )
        candidate_score = float(d.get("candidate_score") or d.get("confidence") or 0.0)
        if candidate_score >= 0.70:
            new_enablers.append("future candidate score is above the candidate threshold")
        else:
            missing_enablers.append("future candidate score is below candidate threshold")
        if (d.get("evidence_tier") or "").strip() and "weak" not in str(d.get("evidence_tier") or "").lower():
            new_enablers.append(f"Step6 fusion tier={d.get('evidence_tier')}")
        else:
            missing_enablers.append("Step6 fusion is weak or missing")
        enabling_conditions = {
            "new_enablers": new_enablers,
            "missing_enablers": missing_enablers,
            "candidate_score": candidate_score,
            "calibration_label": d.get("calibration_label"),
            "rolling_avg_calibrated_auc": rolling_avg_auc,
            "evidence_tier": d.get("evidence_tier"),
            "section_provenance": section_provenance,
        }

        unresolved = [
            {
                "paper_id": atom.get("paper_id"),
                "description": str(atom.get("description") or "")[:220],
                "keyword": atom.get("keyword"),
                "severity": atom.get("severity"),
                "evidence_quality": atom.get("evidence_quality"),
                "section_provenance_strength": atom.get("section_provenance_strength"),
                "section_extraction_strategies": atom.get("section_extraction_strategies") or [],
                "section_parser_contract_version": atom.get("section_parser_contract_version"),
                "section_decision_grade": bool(atom.get("section_decision_grade")),
                "evidence_weight": float(atom.get("evidence_weight") or 0.35),
            }
            for atom in sorted(
                [a for a in direction_atoms if int(a.get("is_resolved") or 0) == 0],
                key=lambda a: float(score_atom(a)),
                reverse=True,
            )[:6]
        ]
        top_kw = str((top_atom.get("keyword") or "technical bottleneck")).strip()
        minimal_experiment = minimal_experiment_template(
            root_type=root_type,
            keyword=top_kw,
        )

        q1 = bool(root_constraint.get("constraint")) and root_constraint.get("constraint") != "insufficient evidence"
        q2 = bool(attempts)
        q3 = bool(enabling_conditions.get("new_enablers"))
        q4 = bool(unresolved)
        q5 = bool(
            minimal_experiment.get("experiment")
            and minimal_experiment.get("cost_level")
            and minimal_experiment.get("cycle_weeks")
            and minimal_experiment.get("success_criteria")
            and minimal_experiment.get("falsification_conditions")
        )
        five_question_gates = {
            "root_constraint": q1,
            "past_attempts_10y": q2,
            "new_enablers": q3,
            "unresolved_bottleneck": q4,
            "minimal_validation_experiment": q5,
        }
        five_complete = int(all(five_question_gates.values()))

        evidence_tier = str(d.get("evidence_tier") or "")
        fusion_tier_ready = evidence_tier == "triangulated_strong"
        high_confidence_gates = {
            "five_question_complete": bool(five_complete),
            "section_evidence_strong": section_strength == "strong",
            "section_provenance_ready": section_provenance_ready,
            "section_decision_grade_ready": section_decision_grade_ready,
            "calibration_ready": calibration_ready,
            "rolling_auc_ready": rolling_avg_auc >= 0.65,
            "candidate_score_ready": candidate_score >= 0.70,
            "fusion_tier_ready": fusion_tier_ready,
        }
        high_confidence_eligible = int(all(high_confidence_gates.values()))
        claim_scope = (
            "validated_candidate"
            if high_confidence_eligible
            else ("exploratory_with_claim_card" if five_complete else "exploratory_incomplete_card")
        )
        missing_gates = _claim_gate_labels(five_question_gates)
        missing_high_confidence_gates = _high_confidence_gate_labels(high_confidence_gates)

        quality_gate = {
            "five_questions": five_question_gates,
            "five_question_complete": bool(five_complete),
            "missing_gates": missing_gates,
            "section_evidence_strength": section_strength,
            "section_provenance": section_provenance,
            "calibration_ready": calibration_ready,
            "rolling_avg_calibrated_auc": rolling_avg_auc,
            "candidate_score": candidate_score,
            "high_confidence_gates": high_confidence_gates,
            "missing_high_confidence_gates": missing_high_confidence_gates,
            "high_confidence_eligible": bool(high_confidence_eligible),
            "radar_policy": (
                "promote_to_radar_high_confidence"
                if high_confidence_eligible
                else (
                    "show_in_radar_as_exploratory_claim_card"
                    if five_complete
                    else "candidate_pool_only"
                )
            ),
        }

        card_id = f"claim:{direction_id}"
        evidence_grade = _claim_card_evidence_grade(
            five_complete=bool(five_complete),
            high_confidence_eligible=bool(high_confidence_eligible),
        )
        uncertainty_reasons = _claim_card_uncertainty_reasons(
            five_complete=bool(five_complete),
            high_confidence_eligible=bool(high_confidence_eligible),
            missing_gates=missing_gates,
            missing_high_confidence_gates=missing_high_confidence_gates,
        )
        evidence_objects = _claim_card_evidence_objects(
            card_id=card_id,
            direction_id=direction_id,
            direction_name=direction_name,
            claim_scope=claim_scope,
            evidence_grade=evidence_grade,
            root_constraint=root_constraint,
            attempts=attempts,
            unresolved=unresolved,
            minimal_experiment=minimal_experiment,
            quality_gate=quality_gate,
        )
        cards.append(
            {
                "claim_card_id": card_id,
                "direction_id": direction_id,
                "direction_name": direction_name,
                "root_constraint_json": jdumps(root_constraint),
                "attempts_last_10y_json": jdumps(attempts),
                "enabling_conditions_json": jdumps(enabling_conditions),
                "unresolved_bottleneck_json": jdumps(
                    {
                        "items": unresolved,
                        "evidence_strength_level": section_strength,
                        "section_provenance": section_provenance,
                    }
                ),
                "minimal_validation_experiment_json": jdumps(minimal_experiment),
                "evidence_strength_level": section_strength,
                "evidence_grade": evidence_grade,
                "claim_scope": claim_scope,
                "uncertainty_reasons_json": jdumps(uncertainty_reasons),
                "evidence_objects_json": jdumps(evidence_objects),
                "five_question_complete": five_complete,
                "high_confidence_eligible": high_confidence_eligible,
                "quality_gate_json": jdumps(quality_gate),
            }
        )
        updates.append(
            {
                "direction_id": direction_id,
                "claim_card_id": card_id,
                "claim_card_complete": five_complete,
                "high_confidence_eligible": high_confidence_eligible,
                "claim_scope": claim_scope,
                "quality_gate_json": jdumps(quality_gate),
            }
        )
    return cards, updates


def write_lineage_and_claim_cards(
    conn_v14: sqlite3.Connection,
    *,
    triples: list[dict],
    cards: list[dict],
    direction_updates: list[dict],
) -> None:
    conn_v14.execute("DELETE FROM bottleneck_lineage_triples")
    conn_v14.execute("DELETE FROM direction_claim_cards")
    if triples:
        conn_v14.executemany(
            """
            INSERT INTO bottleneck_lineage_triples (
                triple_id, principle_id, direction_id, atom_id, edge_order,
                source_stage, target_stage, source_text, target_text, relation_type,
                paper_id, resolver_paper_id, event_year, evidence_section, evidence_page,
                evidence_quality, evidence_weight, metadata_json
            ) VALUES (
                :triple_id, :principle_id, :direction_id, :atom_id, :edge_order,
                :source_stage, :target_stage, :source_text, :target_text, :relation_type,
                :paper_id, :resolver_paper_id, :event_year, :evidence_section, :evidence_page,
                :evidence_quality, :evidence_weight, :metadata_json
            )
            """,
            triples,
        )
    if cards:
        conn_v14.executemany(
            """
            INSERT INTO direction_claim_cards (
                claim_card_id, direction_id, direction_name, root_constraint_json,
                attempts_last_10y_json, enabling_conditions_json, unresolved_bottleneck_json,
                minimal_validation_experiment_json, evidence_strength_level, evidence_grade,
                claim_scope, uncertainty_reasons_json, evidence_objects_json,
                five_question_complete, high_confidence_eligible, quality_gate_json
            ) VALUES (
                :claim_card_id, :direction_id, :direction_name, :root_constraint_json,
                :attempts_last_10y_json, :enabling_conditions_json, :unresolved_bottleneck_json,
                :minimal_validation_experiment_json, :evidence_strength_level, :evidence_grade,
                :claim_scope, :uncertainty_reasons_json, :evidence_objects_json,
                :five_question_complete, :high_confidence_eligible, :quality_gate_json
            )
            """,
            cards,
        )
    if direction_updates:
        conn_v14.executemany(
            """
            UPDATE future_directions
            SET claim_card_id = :claim_card_id,
                claim_card_complete = :claim_card_complete,
                high_confidence_eligible = :high_confidence_eligible,
                claim_scope = :claim_scope,
                quality_gate_json = :quality_gate_json
            WHERE direction_id = :direction_id
            """,
            direction_updates,
        )
    conn_v14.commit()


def write_db(
    conn_v14: sqlite3.Connection,
    principle_rows: list[dict],
    history_rows: list[dict],
) -> None:
    conn_v14.execute("DELETE FROM first_principles_principles")
    conn_v14.execute("DELETE FROM first_principles_history_events")
    if principle_rows:
        conn_v14.executemany(
            """
            INSERT INTO first_principles_principles (
                principle_id, principle_name, root_cause, bottleneck_score,
                unresolved_atoms, resolved_atoms, emergence_year, peak_backlog_year,
                current_backlog, evidence_quality_json, top_keywords_json,
                top_branches_json, top_papers_json, future_alignment_json,
                direction_tier_json, risk_label, notes_json
            ) VALUES (
                :principle_id, :principle_name, :root_cause, :bottleneck_score,
                :unresolved_atoms, :resolved_atoms, :emergence_year, :peak_backlog_year,
                :current_backlog, :evidence_quality_json, :top_keywords_json,
                :top_branches_json, :top_papers_json, :future_alignment_json,
                :direction_tier_json, :risk_label, :notes_json
            )
            """,
            principle_rows,
        )
    if history_rows:
        conn_v14.executemany(
            """
            INSERT INTO first_principles_history_events (
                principle_id, event_year, opened_atoms, resolved_atoms,
                opened_score, resolved_score, backlog_score, top_keywords_json
            ) VALUES (
                :principle_id, :event_year, :opened_atoms, :resolved_atoms,
                :opened_score, :resolved_score, :backlog_score, :top_keywords_json
            )
            """,
            history_rows,
        )
    conn_v14.commit()


def _format_keyword_list(raw: str, top_n: int = 4) -> str:
    items = _safe_json_loads(raw, [])
    if not isinstance(items, list):
        return "N/A"
    keys = []
    for it in items[:top_n]:
        if isinstance(it, dict):
            k = str(it.get("key") or "").strip()
            if k:
                keys.append(k)
    return ", ".join(keys) if keys else "N/A"


def build_markdown(principle_rows: list[dict], totals: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# 第一性原理 + 卡点历史脉络报告（V14B）",
        "",
        f"生成时间: {now}",
        "",
        "## 结论摘要",
        "",
        f"- limitation atoms: {int(totals.get('atoms_total') or 0):,}",
        f"- principle buckets: {int(totals.get('principles_total') or 0):,}",
        f"- section-level atoms: {int(totals.get('section_level_total') or 0):,}",
        f"- future edges considered: {int(totals.get('future_edges_total') or 0):,}",
        f"- future directions considered: {int(totals.get('future_directions_total') or 0):,}",
        f"- bottleneck lineage triples: {int(totals.get('lineage_triples_total') or 0):,}",
        f"- direction claim cards: {int(totals.get('claim_cards_total') or 0):,}",
        f"- high-confidence eligible directions: {int(totals.get('high_confidence_eligible_directions') or 0):,}",
        f"- calibration method: {totals.get('calibration_method') or 'missing'}",
        f"- timeline window: {totals.get('year_min')} - {totals.get('year_max')}",
        "",
        "该报告只基于当前入库证据生成，不对缺失证据区域做强推断。",
        "",
        "## 总览表",
        "",
        "| principle | score | unresolved | resolved | peak backlog year | risk | keywords |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for row in principle_rows:
        lines.append(
            "| {name} | {score:.2f} | {unresolved} | {resolved} | {peak} | {risk} | {kw} |".format(
                name=row.get("principle_name"),
                score=float(row.get("bottleneck_score") or 0.0),
                unresolved=int(row.get("unresolved_atoms") or 0),
                resolved=int(row.get("resolved_atoms") or 0),
                peak=row.get("peak_backlog_year") or "N/A",
                risk=row.get("risk_label") or "unknown",
                kw=_format_keyword_list(str(row.get("top_keywords_json") or "[]")),
            )
        )

    lines += [
        "",
        "## 分项脉络（证据化）",
        "",
    ]

    for row in principle_rows:
        future = _safe_json_loads(row.get("future_alignment_json") or "{}", {})
        top_papers = _safe_json_loads(row.get("top_papers_json") or "[]", [])
        branches = _safe_json_loads(row.get("top_branches_json") or "[]", [])
        tiers = _safe_json_loads(row.get("direction_tier_json") or "{}", {})
        notes = _safe_json_loads(row.get("notes_json") or "{}", {})

        lines += [
            f"### {row.get('principle_name')} ({row.get('principle_id')})",
            "",
            f"- 第一性原理根因: {row.get('root_cause')}",
            f"- 历史脉络: emergence={row.get('emergence_year') or 'N/A'}, peak_backlog={row.get('peak_backlog_year') or 'N/A'}, current_backlog={float(row.get('current_backlog') or 0):.2f}",
            f"- 未解/已解: {int(row.get('unresolved_atoms') or 0)}/{int(row.get('resolved_atoms') or 0)}",
            f"- 证据质量: `{row.get('evidence_quality_json')}`",
            f"- 分支集中度: `{row.get('top_branches_json')}`",
            f"- Future 对齐: matches={future.get('future_edge_matches', 0)}, cross_field={future.get('cross_field_matches', 0)}, tiers={tiers}",
            f"- 当前风险: {row.get('risk_label')}",
            f"- 横向对偶: {', '.join(future.get('cross_domain_duals') or []) or 'N/A'}",
            f"- section-level ratio: {notes.get('section_level_ratio', 'N/A')}",
            "",
            "证据样本（top atoms）:",
        ]
        if isinstance(top_papers, list) and top_papers:
            for atom in top_papers[:5]:
                lines.append(
                    "- paper_id={pid} year={year} score={score:.2f} kw={kw} resolved={resolved} | {desc}".format(
                        pid=atom.get("paper_id") or "N/A",
                        year=atom.get("year") or "N/A",
                        score=float(atom.get("score") or 0.0),
                        kw=(atom.get("keyword") or "N/A"),
                        resolved=int(atom.get("is_resolved") or 0),
                        desc=(atom.get("description") or "").strip()[:220],
                    )
                )
        else:
            lines.append("- 无可用 atom 证据")
        if isinstance(branches, list) and branches:
            lines.append("")
            lines.append(
                "主导分支: " + ", ".join(
                    f"{b.get('key')}({float(b.get('value') or 0):.2f})"
                    for b in branches[:4]
                    if isinstance(b, dict)
                )
            )
        lines.append("")

    lines += [
        "## 使用边界",
        "",
        "1. 本报告是 evidence-aware 诊断层,不把 exploratory 信号伪装为高置信结论。",
        "2. 每条未来方向的高置信资格由 claim card 五问质量门决定；五问不全不得进入高置信。",
        "3. bottleneck lineage triples 来自 limitation/resolution/section 证据链，并保留 section/page 线索。",
        "4. 若 calibration/backtest 缺失，future growth 只能作为探索线索。",
        "5. 若 section-level 证据比例低,卡点解释应标注为弱证据区。",
        "6. 若未来边匹配稀疏,应优先增强候选生成/校准/分支验证,而不是降低阈值。",
        "",
    ]
    return "\n".join(lines) + "\n"


def run_first_principles_history(
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    out_dir: Path = REPORT_DIR,
    corpus_id: str | None = None,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    conn_main = sqlite3.connect(str(db_main))
    conn_main.row_factory = sqlite3.Row
    ensure_corpus_schema(conn_main)
    scoped_count = create_temp_corpus_table(conn_main, corpus_id)
    conn_v14 = get_v14b_conn(db_v14)

    ensure_schema(conn_v14)
    atoms = load_atoms(conn_main, conn_v14, corpus_id=corpus_id)
    section_pages = load_section_page_index(conn_main, corpus_id=corpus_id)
    resolution_rows = load_resolution_rows(conn_v14)
    section_atom_chains = load_section_atom_chains(conn_main, corpus_id=corpus_id)
    future_edges = load_future_edges(conn_main, conn_v14, corpus_id=corpus_id)
    future_directions = load_future_directions(conn_v14)
    calibration_audit = load_vgae_calibration_audit(conn_v14)
    principle_rows, history_rows, totals = build_principle_summary(
        atoms=atoms,
        future_edges=future_edges,
        future_directions=future_directions,
    )
    lineage_triples = build_bottleneck_lineage_triples(
        atoms=atoms,
        resolution_rows=resolution_rows,
        section_pages=section_pages,
        future_directions=future_directions,
        section_atom_chains=section_atom_chains,
    )
    claim_cards, direction_updates = build_direction_claim_cards(
        atoms=atoms,
        future_directions=future_directions,
        principle_rows=principle_rows,
        calibration_audit=calibration_audit,
    )
    write_db(conn_v14, principle_rows, history_rows)
    write_lineage_and_claim_cards(
        conn_v14,
        triples=lineage_triples,
        cards=claim_cards,
        direction_updates=direction_updates,
    )

    totals["lineage_triples_total"] = len(lineage_triples)
    totals["section_atom_chains_total"] = len(section_atom_chains)
    totals["section_atom_chain_lineage_triples"] = sum(
        1
        for triple in lineage_triples
        if (_safe_json_loads(triple.get("metadata_json") or "{}", {}) or {}).get("source") == "section_atom_chain"
    )
    totals["claim_cards_total"] = len(claim_cards)
    totals["high_confidence_eligible_directions"] = sum(
        int(c.get("high_confidence_eligible") or 0) for c in claim_cards
    )
    totals["calibration_method"] = calibration_audit.get("method")

    md_text = build_markdown(principle_rows, totals)
    suffix = f"_{corpus_id}" if corpus_id else ""
    report_md = out_dir / f"第一性原理_卡点历史脉络报告{suffix}.md"
    report_json = out_dir / f"first_principles_bottleneck_history{suffix}.json"
    report_md.write_text(md_text, encoding="utf-8")
    report_json.write_text(
        json.dumps(
            {
                "generated_at": datetime.utcnow().isoformat(),
                "totals": totals,
                "principles": principle_rows,
                "history_events": history_rows,
                "lineage_triples": lineage_triples,
                "direction_claim_cards": claim_cards,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = {
        "report_md": str(report_md),
        "report_json": str(report_json),
        "corpus_id": corpus_id,
        "scoped_papers": scoped_count if corpus_id else None,
        "principles": len(principle_rows),
        "atoms_total": int(totals.get("atoms_total") or 0),
        "history_events": len(history_rows),
        "lineage_triples": len(lineage_triples),
        "claim_cards": len(claim_cards),
        "high_confidence_eligible_directions": int(totals.get("high_confidence_eligible_directions") or 0),
    }
    upsert_step_meta(
        conn_v14,
        "step13_first_principles_history",
        "done",
        records_n=len(principle_rows),
        notes=jdumps(summary),
    )
    conn_main.close()
    conn_v14.close()
    return summary


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.step13_first_principles_history",
        description="Step 13: 第一性原理 + 卡点历史脉络报告",
    )
    add_common_args(parser)
    parser.add_argument("--out-dir", default=str(REPORT_DIR))
    args = parser.parse_args(argv)

    setup_logging("step13_first_principles_history", level=getattr(logging, args.log_level))
    db_main = Path(args.db) if args.db else DB_MAIN
    db_v14 = Path(args.db_v14) if args.db_v14 else DB_V14
    result = run_first_principles_history(
        db_main=db_main,
        db_v14=db_v14,
        out_dir=Path(args.out_dir),
        corpus_id=args.corpus_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
