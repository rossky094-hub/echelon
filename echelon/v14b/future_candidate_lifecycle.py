"""Audit lifecycle state from future edge candidates to Radar eligibility.

The product rule is strict: a VGAE/GNN edge is only a candidate.  It becomes a
user-facing Radar item only after Step6 fusion and Step13 Claim Card gates.
This derived table makes that path explicit for API/UI and audits.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from echelon.v14b.evidence_grade import uncertainty_reasons


PRIMARY_SECTION_RATE_TARGET = 0.12


def jdumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def jloads(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','virtual table') AND name=?",
        (name,),
    ).fetchone()
    return bool(row)


def columns(conn: sqlite3.Connection, name: str) -> set[str]:
    if not table_exists(conn, name):
        return set()
    return {row[1] for row in conn.execute(f"PRAGMA table_info({name})").fetchall()}


def scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    try:
        row = conn.execute(sql, params).fetchone()
    except sqlite3.Error:
        return 0
    return row[0] if row else 0


def ensure_lifecycle_table(conn_v14: sqlite3.Connection) -> None:
    conn_v14.executescript(
        """
        CREATE TABLE IF NOT EXISTS future_candidate_lifecycle (
            src_paper_id TEXT NOT NULL,
            dst_paper_id TEXT NOT NULL,
            lifecycle_state TEXT NOT NULL,
            direction_id INTEGER,
            claim_card_id TEXT,
            radar_eligible INTEGER NOT NULL DEFAULT 0,
            candidate_pool_reason TEXT,
            model_score REAL,
            calibrated_prob REAL,
            prediction_confidence REAL,
            calibration_label TEXT,
            calibration_status TEXT,
            evidence_tier TEXT,
            claim_scope TEXT,
            evidence_grade TEXT,
            missing_gates_json TEXT,
            missing_high_confidence_gates_json TEXT,
            uncertainty_reasons_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (src_paper_id, dst_paper_id)
        );

        CREATE INDEX IF NOT EXISTS idx_future_candidate_lifecycle_state
            ON future_candidate_lifecycle(lifecycle_state);
        CREATE INDEX IF NOT EXISTS idx_future_candidate_lifecycle_direction
            ON future_candidate_lifecycle(direction_id);
        """
    )
    conn_v14.commit()


def collect_global_evidence_context(conn_main: sqlite3.Connection, conn_v14: sqlite3.Connection) -> dict[str, Any]:
    papers = int(scalar(conn_main, "SELECT COUNT(*) FROM papers") or 0)
    refs = int(scalar(conn_main, "SELECT COUNT(*) FROM paper_references") or 0)
    linked_refs = int(
        scalar(
            conn_main,
            """
            SELECT COUNT(*) FROM paper_references
            WHERE COALESCE(cited_paper_id_internal, '') <> ''
            """,
        )
        or 0
    )
    openalex_w = int(
        scalar(
            conn_main,
            """
            SELECT COUNT(*) FROM papers
            WHERE openalex_id LIKE 'W%' OR openalex_id LIKE 'https://openalex.org/W%'
            """,
        )
        or 0
    )
    primary_section_papers = int(
        scalar(
            conn_main,
            """
            SELECT COUNT(DISTINCT paper_id)
            FROM paper_sections
            WHERE lower(section_name) IN (
                'limitation','limitations','discussion','conclusion','conclusions',
                'future_work','future directions','results','error_analysis',
                'ablation','method','methods','experiments'
            )
              AND length(trim(section_text)) >= 80
            """,
        )
        or 0
    )
    calibration_audits = (
        int(scalar(conn_v14, "SELECT COUNT(*) FROM vgae_calibration_audit") or 0)
        if table_exists(conn_v14, "vgae_calibration_audit")
        else 0
    )
    linked_rate = linked_refs / max(1, refs)
    section_rate = primary_section_papers / max(1, papers)
    openalex_rate = openalex_w / max(1, papers)
    return {
        "papers": papers,
        "refs": refs,
        "linked_refs": linked_refs,
        "linked_ref_rate": linked_rate,
        "openalex_w": openalex_w,
        "openalex_w_rate": openalex_rate,
        "primary_section_papers": primary_section_papers,
        "primary_section_rate": section_rate,
        "calibration_audits": calibration_audits,
        "global_uncertainty_reasons": uncertainty_reasons(
            linked_ref_rate=linked_rate,
            primary_section_rate=section_rate,
            openalex_rate=openalex_rate,
            has_calibration=calibration_audits > 0,
        ),
    }


def load_future_candidates(conn_v14: sqlite3.Connection) -> list[dict[str, Any]]:
    if not table_exists(conn_v14, "predicted_future_edges"):
        return []
    cols = columns(conn_v14, "predicted_future_edges")
    score_sql = "predicted_prob" if "predicted_prob" in cols else "1.0 AS predicted_prob"
    calibrated_sql = "calibrated_prob" if "calibrated_prob" in cols else "NULL AS calibrated_prob"
    confidence_sql = "prediction_confidence" if "prediction_confidence" in cols else "NULL AS prediction_confidence"
    label_sql = "calibration_label" if "calibration_label" in cols else "NULL AS calibration_label"
    method_sql = "calibration_method" if "calibration_method" in cols else "NULL AS calibration_method"
    order_sql = (
        "COALESCE(prediction_confidence, predicted_prob) DESC, predicted_prob DESC"
        if "predicted_prob" in cols and "prediction_confidence" in cols
        else ("predicted_prob DESC" if "predicted_prob" in cols else "src_paper_id, dst_paper_id")
    )
    rows = conn_v14.execute(
        f"""
        SELECT src_paper_id, dst_paper_id, {score_sql},
               {calibrated_sql}, {confidence_sql}, {label_sql}, {method_sql}
        FROM predicted_future_edges
        ORDER BY {order_sql}
        """
    ).fetchall()
    return [dict(row) for row in rows]


def load_directions(conn_v14: sqlite3.Connection) -> tuple[dict[int, dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    if not table_exists(conn_v14, "future_directions"):
        return {}, {}
    rows = conn_v14.execute("SELECT * FROM future_directions").fetchall()
    cols = [row[1] for row in conn_v14.execute("PRAGMA table_info(future_directions)").fetchall()]
    by_id: dict[int, dict[str, Any]] = {}
    by_edge: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        item = dict(zip(cols, row))
        did = int(item.get("direction_id") or 0)
        if did <= 0:
            continue
        pids = jloads(item.get("paper_ids_json"), [])
        if not isinstance(pids, list):
            pids = []
        item["_paper_ids"] = {str(pid) for pid in pids}
        by_id[did] = item
        if len(pids) >= 2:
            for i, src in enumerate(pids):
                for dst in pids[i + 1 :]:
                    by_edge[(str(src), str(dst))] = item
                    by_edge[(str(dst), str(src))] = item
    return by_id, by_edge


def load_claim_cards(conn_v14: sqlite3.Connection) -> dict[int, dict[str, Any]]:
    if not table_exists(conn_v14, "direction_claim_cards"):
        return {}
    rows = conn_v14.execute("SELECT * FROM direction_claim_cards").fetchall()
    cols = [row[1] for row in conn_v14.execute("PRAGMA table_info(direction_claim_cards)").fetchall()]
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        item = dict(zip(cols, row))
        did = int(item.get("direction_id") or 0)
        if did > 0:
            out[did] = item
    return out


def _calibration_status(candidate: dict[str, Any], context: dict[str, Any]) -> str:
    if context.get("calibration_audits", 0) <= 0:
        if candidate.get("calibration_label") or candidate.get("calibration_method"):
            return "edge_has_calibration_label_but_run_audit_missing"
        return "not_calibrated"
    if candidate.get("calibration_label") or candidate.get("calibration_method"):
        return "calibrated_with_run_audit"
    return "run_audit_available_candidate_unlabeled"


def _direction_for_candidate(
    candidate: dict[str, Any],
    directions_by_edge: dict[tuple[str, str], dict[str, Any]],
    directions_by_id: dict[int, dict[str, Any]],
) -> dict[str, Any] | None:
    src = str(candidate.get("src_paper_id") or "")
    dst = str(candidate.get("dst_paper_id") or "")
    if (src, dst) in directions_by_edge:
        return directions_by_edge[(src, dst)]
    matched = []
    for direction in directions_by_id.values():
        pids = direction.get("_paper_ids") or set()
        if src in pids or dst in pids:
            matched.append(direction)
    if not matched:
        return None
    return sorted(matched, key=lambda d: float(d.get("confidence") or 0.0), reverse=True)[0]


def build_lifecycle_rows(
    *,
    candidates: list[dict[str, Any]],
    directions_by_id: dict[int, dict[str, Any]],
    directions_by_edge: dict[tuple[str, str], dict[str, Any]],
    claim_cards: dict[int, dict[str, Any]],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    global_uncertainty = list(context.get("global_uncertainty_reasons") or [])
    for candidate in candidates:
        direction = _direction_for_candidate(candidate, directions_by_edge, directions_by_id)
        direction_id = int(direction.get("direction_id") or 0) if direction else None
        card = claim_cards.get(direction_id or -1) if direction_id else None
        missing_gates: list[str] = []
        missing_high: list[str] = []
        uncertainty = list(global_uncertainty)
        state = "future_candidate_unfused"
        radar_eligible = 0
        candidate_reason = "Step5b model candidate has not been fused by Step6"
        evidence_grade = "model_only"
        claim_scope = "candidate_pool_only"

        if direction and not card:
            state = "fused_direction_missing_claim_card"
            candidate_reason = "Step6 direction exists but Step13 Claim Card is missing"
            missing_gates.append("Step13 Claim Card")
            evidence_grade = str(direction.get("evidence_tier") or "metadata_only")
            claim_scope = str(direction.get("claim_scope") or "candidate_pool_only")
        elif direction and card:
            gate = jloads(card.get("quality_gate_json"), {})
            missing_gates = list(gate.get("missing_gates") or [])
            missing_high = list(gate.get("missing_high_confidence_gates") or [])
            complete = int(card.get("five_question_complete") or 0) == 1
            high = int(card.get("high_confidence_eligible") or 0) == 1
            evidence_grade = str(card.get("evidence_strength_level") or "metadata_only")
            claim_scope = str(card.get("claim_scope") or direction.get("claim_scope") or "candidate_pool_only")
            if high:
                state = "radar_high_confidence"
                radar_eligible = 1
                candidate_reason = "Step6 and Step13 gates passed"
            elif complete:
                state = "exploratory_claim_card"
                candidate_reason = "Claim Card complete but high-confidence gates remain open"
            else:
                state = "candidate_pool_incomplete_claim_card"
                candidate_reason = "Claim Card exists but one or more hard questions are missing"
        else:
            missing_gates.extend(["Step6 fusion direction", "Step13 Claim Card"])

        calibration_status = _calibration_status(candidate, context)
        if calibration_status != "calibrated_with_run_audit":
            uncertainty.append(calibration_status.replace("_", " "))

        rows.append(
            {
                "src_paper_id": candidate.get("src_paper_id"),
                "dst_paper_id": candidate.get("dst_paper_id"),
                "lifecycle_state": state,
                "direction_id": direction_id,
                "claim_card_id": card.get("claim_card_id") if card else None,
                "radar_eligible": radar_eligible,
                "candidate_pool_reason": candidate_reason,
                "model_score": float(candidate.get("predicted_prob") or 0.0),
                "calibrated_prob": (
                    float(candidate.get("calibrated_prob"))
                    if candidate.get("calibrated_prob") is not None
                    else None
                ),
                "prediction_confidence": (
                    float(candidate.get("prediction_confidence"))
                    if candidate.get("prediction_confidence") is not None
                    else None
                ),
                "calibration_label": candidate.get("calibration_label"),
                "calibration_status": calibration_status,
                "evidence_tier": direction.get("evidence_tier") if direction else None,
                "claim_scope": claim_scope,
                "evidence_grade": evidence_grade,
                "missing_gates_json": jdumps(sorted(set(missing_gates))),
                "missing_high_confidence_gates_json": jdumps(sorted(set(missing_high))),
                "uncertainty_reasons_json": jdumps(sorted(set(uncertainty))),
            }
        )
    return rows


def write_lifecycle_rows(conn_v14: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    ensure_lifecycle_table(conn_v14)
    conn_v14.execute("DELETE FROM future_candidate_lifecycle")
    if rows:
        conn_v14.executemany(
            """
            INSERT INTO future_candidate_lifecycle (
                src_paper_id, dst_paper_id, lifecycle_state, direction_id, claim_card_id,
                radar_eligible, candidate_pool_reason, model_score, calibrated_prob,
                prediction_confidence, calibration_label, calibration_status,
                evidence_tier, claim_scope, evidence_grade, missing_gates_json,
                missing_high_confidence_gates_json, uncertainty_reasons_json
            ) VALUES (
                :src_paper_id, :dst_paper_id, :lifecycle_state, :direction_id, :claim_card_id,
                :radar_eligible, :candidate_pool_reason, :model_score, :calibrated_prob,
                :prediction_confidence, :calibration_label, :calibration_status,
                :evidence_tier, :claim_scope, :evidence_grade, :missing_gates_json,
                :missing_high_confidence_gates_json, :uncertainty_reasons_json
            )
            """,
            rows,
        )
    conn_v14.commit()


def summarize(rows: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
    state_counts = Counter(row["lifecycle_state"] for row in rows)
    calibration_counts = Counter(row["calibration_status"] for row in rows)
    missing_gate_counts: Counter[str] = Counter()
    missing_high_counts: Counter[str] = Counter()
    for row in rows:
        missing_gate_counts.update(jloads(row.get("missing_gates_json"), []))
        missing_high_counts.update(jloads(row.get("missing_high_confidence_gates_json"), []))
    return {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "total_candidates": len(rows),
        "state_counts": dict(state_counts),
        "calibration_status_counts": dict(calibration_counts),
        "missing_gate_counts": dict(missing_gate_counts),
        "missing_high_confidence_gate_counts": dict(missing_high_counts),
        "radar_eligible": int(sum(int(row.get("radar_eligible") or 0) for row in rows)),
        "context": context,
    }


def render_markdown(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Future Candidate Lifecycle Audit",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- total candidates: {int(summary['total_candidates']):,}",
        f"- radar eligible: {int(summary['radar_eligible']):,}",
        "",
        "## Lifecycle States",
        "",
        "| state | count | product meaning |",
        "| --- | ---: | --- |",
    ]
    meanings = {
        "future_candidate_unfused": "GNN/VGAE candidate only; Step6 has not promoted it to a direction.",
        "fused_direction_missing_claim_card": "Step6 direction exists, but Step13 evidence card is missing.",
        "candidate_pool_incomplete_claim_card": "Claim Card exists, but at least one of the five hard questions is missing.",
        "exploratory_claim_card": "Five-question card is complete, but high-confidence gates are not all satisfied.",
        "radar_high_confidence": "Complete card plus high-confidence gates; may enter Radar.",
    }
    for state, count in sorted(summary["state_counts"].items()):
        lines.append(f"| {state} | {int(count):,} | {meanings.get(state, '')} |")

    lines.extend(["", "## Calibration Status", "", "| status | count |", "| --- | ---: |"])
    for status, count in sorted(summary["calibration_status_counts"].items()):
        lines.append(f"| {status} | {int(count):,} |")

    lines.extend(["", "## Missing Five-Question Gates", "", "| gate | count |", "| --- | ---: |"])
    if summary["missing_gate_counts"]:
        for gate, count in sorted(summary["missing_gate_counts"].items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"| {gate} | {int(count):,} |")
    else:
        lines.append("| none | 0 |")

    lines.extend(["", "## Top Candidate Pool Samples", ""])
    for row in rows[:12]:
        lines.append(
            "- {src} -> {dst}: state={state}, score={score:.3f}, reason={reason}".format(
                src=row.get("src_paper_id"),
                dst=row.get("dst_paper_id"),
                state=row.get("lifecycle_state"),
                score=float(row.get("prediction_confidence") or row.get("model_score") or 0.0),
                reason=row.get("candidate_pool_reason"),
            )
        )
    lines.extend(
        [
            "",
            "## Product Rule",
            "",
            "Future candidates are inspection targets until they pass Step6 fusion and Step13 Claim Card gates. "
            "Rows in `future_candidate_unfused`, `fused_direction_missing_claim_card`, or "
            "`candidate_pool_incomplete_claim_card` must not appear in the Radar main view.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_audit(
    db_main: Path,
    db_v14: Path,
    out_dir: Path,
    *,
    write_table: bool = True,
) -> dict[str, Any]:
    conn_main = sqlite3.connect(str(db_main))
    conn_main.row_factory = sqlite3.Row
    conn_v14 = sqlite3.connect(str(db_v14))
    conn_v14.row_factory = sqlite3.Row
    context = collect_global_evidence_context(conn_main, conn_v14)
    candidates = load_future_candidates(conn_v14)
    directions_by_id, directions_by_edge = load_directions(conn_v14)
    claim_cards = load_claim_cards(conn_v14)
    rows = build_lifecycle_rows(
        candidates=candidates,
        directions_by_id=directions_by_id,
        directions_by_edge=directions_by_edge,
        claim_cards=claim_cards,
        context=context,
    )
    if write_table:
        write_lifecycle_rows(conn_v14, rows)
    summary = summarize(rows, context)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "future_candidate_lifecycle_audit.json"
    md_path = out_dir / "future_candidate_lifecycle_audit.md"
    json_path.write_text(jdumps({"summary": summary, "rows": rows}) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(summary, rows), encoding="utf-8")
    conn_main.close()
    conn_v14.close()
    return {"summary": summary, "report": str(md_path), "json": str(json_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit future candidate lifecycle toward Claim Cards/Radar.")
    parser.add_argument("--db", default="db/echelon_library.sqlite3")
    parser.add_argument("--db-v14", default="db/v14_pilot.sqlite3")
    parser.add_argument("--out-dir", default="reports/v14b_pilot")
    parser.add_argument("--no-write-table", action="store_true")
    args = parser.parse_args()
    result = run_audit(
        Path(args.db),
        Path(args.db_v14),
        Path(args.out_dir),
        write_table=not args.no_write_table,
    )
    print(jdumps(result["summary"]))


if __name__ == "__main__":
    main()
