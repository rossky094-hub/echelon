"""Step 12: goal-alignment audit for the V14B optics product chain.

This report compares Step1-Step6 evidence against the product goal:
an explainable optics evolution graph that can show why branches formed and
where they may grow next.  It is intentionally conservative: weak evidence is
reported as weak instead of being promoted into user-facing claims.
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from echelon.v14b.config import DB_MAIN, DB_V14, REPORT_DIR
from echelon.v14b.db_schema import get_v14b_conn, upsert_step_meta
from echelon.v14b.utils import add_common_args, setup_logging, table_columns


def scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Any:
    try:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.Error:
        return []


def load_checkpoint(name: str) -> dict:
    path = REPORT_DIR / "checkpoints" / f"{name}.done.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def pct(n: float, d: float) -> str:
    return f"{(n / max(d, 1) * 100):.1f}%"


def quality_label(value: float, *, good: float, warn: float) -> str:
    if value >= good:
        return "pass"
    if value >= warn:
        return "warning"
    return "risk"


def build_audit(db_main: Path, db_v14: Path) -> tuple[str, dict]:
    conn_main = sqlite3.connect(str(db_main))
    conn_main.row_factory = sqlite3.Row
    conn_v14 = get_v14b_conn(db_v14)

    paper_cols = table_columns(conn_main, "papers")
    total_papers = int(scalar(conn_main, "SELECT COUNT(*) FROM papers") or 0)
    abstracts = int(scalar(conn_main, "SELECT COUNT(*) FROM papers WHERE abstract IS NOT NULL AND LENGTH(abstract)>100") or 0)
    total_refs = int(scalar(conn_main, "SELECT COUNT(*) FROM paper_references") or 0)
    linked_refs = int(scalar(conn_main, "SELECT COUNT(*) FROM paper_references WHERE cited_paper_id_internal IS NOT NULL") or 0)
    field_cov = int(scalar(conn_main, "SELECT COUNT(*) FROM papers WHERE primary_field_id IS NOT NULL") or 0) if "primary_field_id" in paper_cols else 0
    embeddings = int(scalar(conn_main, "SELECT COUNT(*) FROM paper_embeddings") or 0)

    main_edges = int(scalar(conn_v14, "SELECT COUNT(*) FROM main_path_edges") or 0)
    main_core = int(scalar(conn_v14, "SELECT COUNT(*) FROM main_path_edges WHERE is_main_path=1") or 0)
    cycle_components = int(scalar(conn_v14, "SELECT COUNT(*) FROM main_path_cycle_audit") or 0)
    cyclic_nodes = int(scalar(conn_v14, "SELECT COALESCE(SUM(component_size),0) FROM main_path_cycle_audit") or 0)
    intra_cycle_edges = int(scalar(conn_v14, "SELECT COALESCE(SUM(intra_edges),0) FROM main_path_cycle_audit") or 0)

    step3_meta = rows(conn_v14, "SELECT notes FROM v14b_run_meta WHERE step_name='step3_keystone_v14'")
    step3_notes = json.loads(step3_meta[0]["notes"]) if step3_meta and step3_meta[0].get("notes") else {}

    subgraph_audit = rows(conn_v14, "SELECT * FROM subgraph_scope_audit ORDER BY created_at DESC LIMIT 1")
    subgraph = subgraph_audit[0] if subgraph_audit else {}
    citation_evidence = rows(conn_v14, """
        SELECT COALESCE(citation_function_evidence_level, 'unknown') AS level,
               COUNT(*) AS n,
               AVG(COALESCE(citation_function_weight,0)) AS avg_weight
        FROM subgraph_edges
        WHERE citation_function IS NOT NULL
        GROUP BY level
        ORDER BY n DESC
    """)

    step5b = load_checkpoint("step5b_vgae")
    rolling_backtest = step5b.get("rolling_backtest") or {}
    predicted_total = int(scalar(conn_v14, "SELECT COUNT(*) FROM predicted_future_edges") or 0)
    predicted_cross = int(scalar(conn_v14, "SELECT COUNT(*) FROM predicted_future_edges WHERE is_cross_field=1") or 0)
    pred_min = float(scalar(conn_v14, "SELECT COALESCE(MIN(predicted_prob),0) FROM predicted_future_edges") or 0.0)
    pred_avg = float(scalar(conn_v14, "SELECT COALESCE(AVG(predicted_prob),0) FROM predicted_future_edges") or 0.0)
    pred_max = float(scalar(conn_v14, "SELECT COALESCE(MAX(predicted_prob),0) FROM predicted_future_edges") or 0.0)
    pred_cols = table_columns(conn_v14, "predicted_future_edges")
    raw_min = raw_avg = raw_max = None
    conf_avg = None
    calibration_labels = []
    if "raw_predicted_prob" in pred_cols:
        raw_min = float(scalar(conn_v14, "SELECT COALESCE(MIN(raw_predicted_prob),0) FROM predicted_future_edges") or 0.0)
        raw_avg = float(scalar(conn_v14, "SELECT COALESCE(AVG(raw_predicted_prob),0) FROM predicted_future_edges") or 0.0)
        raw_max = float(scalar(conn_v14, "SELECT COALESCE(MAX(raw_predicted_prob),0) FROM predicted_future_edges") or 0.0)
    if "prediction_confidence" in pred_cols:
        conf_avg = float(scalar(conn_v14, "SELECT COALESCE(AVG(prediction_confidence),0) FROM predicted_future_edges") or 0.0)
    if "calibration_label" in pred_cols:
        calibration_labels = rows(conn_v14, """
            SELECT COALESCE(calibration_label, 'unknown') AS label, COUNT(*) AS n
            FROM predicted_future_edges
            GROUP BY label
            ORDER BY n DESC
        """)

    limitation_quality = rows(conn_v14, """
        SELECT COALESCE(evidence_quality, 'unknown') AS quality,
               COALESCE(evidence_source, 'unknown') AS source,
               COUNT(*) AS n,
               AVG(COALESCE(evidence_weight,0)) AS avg_weight
        FROM limitation_atoms
        GROUP BY quality, source
        ORDER BY n DESC
    """)
    limitation_atoms = int(scalar(conn_v14, "SELECT COUNT(*) FROM limitation_atoms") or 0)
    limitation_resolutions = int(scalar(conn_v14, "SELECT COUNT(*) FROM limitation_resolutions") or 0)
    section_table_exists = int(
        scalar(
            conn_main,
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('paper_sections','scibot_sections','paper_fulltext_sections')",
        ) or 0
    ) > 0
    section_primary_papers = 0
    section_rows_total = 0
    if section_table_exists:
        table_name = rows(
            conn_main,
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('paper_sections','scibot_sections','paper_fulltext_sections') ORDER BY CASE name WHEN 'paper_sections' THEN 1 WHEN 'scibot_sections' THEN 2 ELSE 3 END LIMIT 1",
        )
        sec_table = table_name[0]["name"] if table_name else "paper_sections"
        section_rows_total = int(
            scalar(conn_main, f"SELECT COUNT(*) FROM {sec_table}") or 0
        )
        section_primary_papers = int(
            scalar(
                conn_main,
                f"""
                SELECT COUNT(DISTINCT paper_id) FROM {sec_table}
                WHERE lower(section_name) IN ('limitations','limitation','discussion','conclusion','conclusions','future work')
                """,
            ) or 0
        )

    fusion_audit_rows = rows(conn_v14, "SELECT * FROM fusion_evidence_audit ORDER BY created_at DESC LIMIT 1")
    fusion_audit = fusion_audit_rows[0] if fusion_audit_rows else {}
    future_dirs = int(scalar(conn_v14, "SELECT COUNT(*) FROM future_directions") or 0)
    direction_tiers = rows(conn_v14, """
        SELECT COALESCE(evidence_tier, 'unknown') AS tier,
               COUNT(*) AS n,
               AVG(COALESCE(confidence,0)) AS avg_confidence
        FROM future_directions
        GROUP BY tier
        ORDER BY n DESC
    """)

    visual_nodes = int(scalar(conn_v14, "SELECT COUNT(*) FROM visual_nodes") or 0)
    visual_edges = int(scalar(conn_v14, "SELECT COUNT(*) FROM visual_edges") or 0)
    clusters = int(scalar(conn_v14, "SELECT COUNT(*) FROM visual_clusters") or 0)
    lineages = int(scalar(conn_v14, "SELECT COUNT(*) FROM branch_lineages") or 0)

    linked_ratio = linked_refs / max(total_refs, 1)
    field_ratio = field_cov / max(total_papers, 1)
    embed_ratio = embeddings / max(total_papers, 1)
    direction_ratio = future_dirs / max(1, int(fusion_audit.get("n_vgae_preds_top") or 200))

    summary = {
        "total_papers": total_papers,
        "linked_ref_ratio": linked_ratio,
        "field_coverage": field_ratio,
        "embedding_coverage": embed_ratio,
        "step5b_test_auc": step5b.get("test_auc"),
        "future_directions": future_dirs,
        "fusion_adequacy": fusion_audit.get("adequacy_label"),
        "visual_nodes": visual_nodes,
        "visual_edges": visual_edges,
    }

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# V14B Optics Goal Alignment Audit",
        "",
        f"Generated: {now}",
        "",
        "## Project Goal",
        "",
        "Build an explainable optics evolution graph that can show why the field grew into its current branch structure and where it may grow next, while exposing evidence quality for user-facing claims.",
        "",
        "## Executive Verdict",
        "",
        f"- Product graph layer exists: {visual_nodes:,} visual nodes, {visual_edges:,} visual edges, {clusters:,} clusters, {lineages:,} branch lineages.",
        f"- Step5b future-growth signal is numerically strong as a ranker: test AUC={float(step5b.get('test_auc') or 0):.4f}, predicted_edges={predicted_total:,}, cross_field={predicted_cross:,}; product confidence is calibrated separately from raw model score.",
        f"- Step5c limitation evidence is currently mostly abstract/algorithmic unless section tables are ingested: atoms={limitation_atoms:,}, resolutions={limitation_resolutions:,}.",
        f"- Section evidence inventory: table_present={section_table_exists}, rows={section_rows_total:,}, primary-section papers={section_primary_papers:,}.",
        f"- Step6 fusion output is limited: directions={future_dirs:,}, adequacy={fusion_audit.get('adequacy_label', 'unknown')}. This is acceptable as an honest signal, but not yet enough for strong user-facing future claims.",
        "",
        "## Step1-Step6 Evidence Chain",
        "",
        "| step | key output | quality status | interpretation |",
        "|---|---:|---|---|",
        f"| Step1 library/enrich | papers={total_papers:,}, abstracts={pct(abstracts,total_papers)}, linked_refs={linked_refs:,}/{total_refs:,} ({pct(linked_refs,total_refs)}) | {quality_label(linked_ratio, good=0.20, warn=0.10)} | citation graph is usable but still coverage-limited against all raw references |",
        f"| Step1 field/topic | primary_field_id={field_cov:,}/{total_papers:,} ({pct(field_cov,total_papers)}) | {quality_label(field_ratio, good=0.70, warn=0.45)} | cross-field interpretation remains partial |",
        f"| Step0 embeddings | embeddings={embeddings:,}/{total_papers:,} ({pct(embeddings,total_papers)}) | {quality_label(embed_ratio, good=0.95, warn=0.80)} | semantic layer/search/layout is well supported |",
        f"| Step2 main path | edges={main_edges:,}, main={main_core:,}, cycles={cycle_components}, cyclic_nodes={cyclic_nodes}, intra_cycle_edges={intra_cycle_edges} | pass | SCC condensation preserves ambiguous cycles instead of arbitrary deletion |",
        f"| Step3 keystone | avg_signal_reliability={float(step3_notes.get('avg_signal_reliability') or 0):.3f}, critical_default_papers={step3_notes.get('critical_default_papers', 'n/a')} | pass | score is discriminative only while graph feature columns remain populated |",
        f"| Step4 subgraph | nodes={int(subgraph.get('selected_nodes') or 0):,}, edges={int(subgraph.get('selected_edges') or 0):,}, scope={subgraph.get('conclusion_scope', 'unknown')} | {subgraph.get('adequacy_label', 'unknown')} | pilot/evidence subgraph, not complete optics graph |",
        f"| Step5a citation function | classified={sum(int(r.get('n') or 0) for r in citation_evidence):,} | weak evidence | no full citation context, therefore use only as fusion/visual weighting |",
        f"| Step5b future growth | predicted={predicted_total:,}, cross_field={predicted_cross:,}, calibrated_min/avg/max={pred_min:.3f}/{pred_avg:.3f}/{pred_max:.3f} | warning | ranking works; calibrated confidence is product evidence, not scientific certainty |",
        f"| Step5c limitations | atoms={limitation_atoms:,}, resolutions={limitation_resolutions:,} | weak-to-moderate | limitation quality must be visible in graph |",
        f"| Step6 fusion | directions={future_dirs:,}, candidates={fusion_audit.get('n_candidates', 'n/a')} | {fusion_audit.get('adequacy_label', 'unknown')} | few directions means evidence intersection is sparse, not a reason to lower thresholds |",
        "",
        "## Limitation Evidence Quality",
        "",
        "| quality | source | atoms | avg_weight |",
        "|---|---|---:|---:|",
    ]
    for r in limitation_quality:
        lines.append(f"| {r.get('quality')} | {r.get('source')} | {int(r.get('n') or 0):,} | {float(r.get('avg_weight') or 0):.3f} |")

    lines += [
        "",
        "## Fusion Evidence Adequacy",
        "",
        f"- top_vgae_used: {fusion_audit.get('n_vgae_preds_top', 'n/a')}",
        f"- total_vgae_predictions: {fusion_audit.get('n_vgae_preds_total', predicted_total)}",
        f"- cross_field_predictions: {fusion_audit.get('n_cross_field_total', predicted_cross)}",
        f"- unresolved_limitations_used: {fusion_audit.get('n_unresolved', 'n/a')}",
        f"- evidence_path_distribution: `{fusion_audit.get('evidence_path_json', '{}')}`",
        f"- candidate_tier_distribution: `{fusion_audit.get('candidate_tier_json', '{}')}`",
        f"- calibration_distribution: `{fusion_audit.get('calibration_json', '{}')}`",
        f"- limitation_quality_distribution: `{fusion_audit.get('limitation_quality_json', '{}')}`",
        "",
        "## Step5b Calibration",
        "",
        f"- calibrated_predicted_prob_min_avg_max: {pred_min:.3f}/{pred_avg:.3f}/{pred_max:.3f}",
        f"- raw_predicted_prob_min_avg_max: {raw_min:.3f}/{raw_avg:.3f}/{raw_max:.3f}" if raw_min is not None else "- raw_predicted_prob_min_avg_max: n/a",
        f"- prediction_confidence_avg: {conf_avg:.3f}" if conf_avg is not None else "- prediction_confidence_avg: n/a",
        f"- calibration_labels: `{json.dumps(calibration_labels, ensure_ascii=False)}`",
        f"- rolling_backtest_avg_raw_auc: {float(rolling_backtest.get('avg_raw_auc') or 0):.4f}",
        f"- rolling_backtest_avg_calibrated_auc: {float(rolling_backtest.get('avg_calibrated_auc') or 0):.4f}",
        f"- rolling_backtest_years: `{json.dumps(rolling_backtest.get('years') or [], ensure_ascii=False)}`",
        "",
        "## Future Direction Evidence Tiers",
        "",
        "| tier | directions | avg_confidence |",
        "|---|---:|---:|",
    ]
    for r in direction_tiers:
        lines.append(f"| {r.get('tier')} | {int(r.get('n') or 0):,} | {float(r.get('avg_confidence') or 0):.3f} |")

    lines += [
        "",
        "## What Was Improved",
        "",
        "- Step2 now exposes canonical `source_paper_id` / `target_paper_id` for time-forward main-path semantics while retaining legacy columns for compatibility.",
        "- Step3 now records signal reliability and dampens KeystoneScore toward neutral if critical features regress to defaults.",
        "- Step4 now records `subgraph_scope_audit`, explicitly labeling the 5,000-node subgraph as pilot/evidence and evaluating whether the cap is adequate.",
        "- Step5a now writes method/evidence-level/weight, so title/abstract-only citation-function labels cannot masquerade as ground truth.",
        "- Step5c now writes limitation evidence source, quality, weight, section name, and extractor method.",
        "- Step5b now separates raw VGAE scores from calibrated product confidence using chronological validation evidence.",
        "- Step6 now writes evidence tiers and claim scopes, making sparse/exploratory evidence an explicit product signal.",
        "- Step10 propagates limitation and calibrated future-edge evidence into visual node/edge flags and detail JSON.",
        "",
        "## Remaining Risk",
        "",
        "1. Linked-reference coverage is still the largest graph-bone risk. The internal citation DAG is large enough to run, but linked_refs/raw_refs is still coverage-limited.",
        "2. OpenAlex Field/Topic coverage is partial. Cross-field color, bridge, and future direction claims should expose uncertainty until field coverage improves.",
        "3. Step5b now includes calibration + rolling held-out-year checks, but user-facing confidence still needs external LLM/human stratified audit calibration.",
        "4. Step5c is weak when based on abstracts. Section-level `paper_sections` / Sci-Bot sections are needed before limitation-driven bottleneck claims become strong.",
        "5. Step6 evidence tiers improve transparency, but exploratory directions remain hypotheses. The next improvement should strengthen branch lineage and candidate generation with stronger external validation, not just lower thresholds.",
        "6. Branch lineage now exposes support ratios and alternative parents, but parent-child branch causality still needs stronger validation against citation/community history and LLM/human audit samples.",
        "7. LLM/Doubao audit is planned but not executed. The visual graph should present unaudited future/main/branch edges with uncertainty until the stratified audit is run.",
        "",
        "## Recommendation",
        "",
        "The current output is suitable as an evidence-aware pilot visual graph and search/recommendation substrate. It is not yet strong enough to present future directions as high-confidence scientific forecasts. The next engineering priority is section-level evidence ingestion plus calibrated future-growth/branch-lineage validation.",
    ]

    conn_main.close()
    conn_v14.close()
    return "\n".join(lines) + "\n", summary


def run_goal_alignment_audit(
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    out_dir: Path = REPORT_DIR,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    report, summary = build_audit(db_main, db_v14)
    path = out_dir / "goal_alignment_audit_step1_step6.md"
    path.write_text(report, encoding="utf-8")

    conn_v14 = get_v14b_conn(db_v14)
    upsert_step_meta(
        conn_v14,
        "step12_goal_alignment_audit",
        "done",
        records_n=1,
        notes=json.dumps({"report_path": str(path), **summary}, ensure_ascii=False),
    )
    conn_v14.close()
    return {"report_path": str(path), **summary}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.step12_goal_alignment_audit",
        description="Step 12: audit Step1-Step6 alignment with V14B product goals",
    )
    add_common_args(parser)
    parser.add_argument("--out-dir", default=str(REPORT_DIR))
    args = parser.parse_args(argv)

    log_level = getattr(logging, args.log_level)
    setup_logging("step12_goal_alignment_audit", level=log_level)
    db_main = Path(args.db) if args.db else DB_MAIN
    db_v14 = Path(args.db_v14) if args.db_v14 else DB_V14
    result = run_goal_alignment_audit(db_main=db_main, db_v14=db_v14, out_dir=Path(args.out_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
