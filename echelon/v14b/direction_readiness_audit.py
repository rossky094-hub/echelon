"""Audit whether future-growth candidates are ready to become Claim Cards.

The product goal is not to maximize the number of future edges.  It is to
separate calibrated candidate generation from evidence-backed, actionable
research directions.  This audit reports which step is blocking that promotion.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from echelon.v14b.future_candidate_lifecycle import run_audit as run_lifecycle_audit


PRIMARY_SECTION_NAMES = (
    "limitation",
    "limitations",
    "discussion",
    "conclusion",
    "conclusions",
    "future_work",
    "future directions",
    "results",
    "error_analysis",
    "ablation",
    "method",
    "methods",
    "experiments",
)


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','virtual table') AND name=?",
        (name,),
    ).fetchone()
    return bool(row)


def scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    try:
        row = conn.execute(sql, params).fetchone()
    except sqlite3.Error:
        return 0
    return row[0] if row else 0


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


_WATCHDOG_TS_RE = re.compile(r"\[(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\]")
_WATCHDOG_COUNT_RE = re.compile(r"rows=(?P<rows>\d+)\s+papers=(?P<papers>\d+)")
_WATCHDOG_DONE_RE = re.compile(r"done=(?P<done>\d+)/(?P<total>\d+)")


def _ts_epoch(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _watchdog_no_evidence_elapsed(log_path: Path) -> dict[str, Any]:
    if not log_path.exists():
        return {}
    latest: dict[str, Any] | None = None
    last_growth: dict[str, Any] | None = None
    for line in log_path.read_text(errors="ignore").splitlines():
        ts = _WATCHDOG_TS_RE.search(line)
        counts = _WATCHDOG_COUNT_RE.search(line)
        if not ts or not counts:
            continue
        done = _WATCHDOG_DONE_RE.search(line)
        rec = {
            "ts": ts.group("ts"),
            "epoch": _ts_epoch(ts.group("ts")),
            "rows": int(counts.group("rows")),
            "papers": int(counts.group("papers")),
            "done": int(done.group("done")) if done else None,
            "total": int(done.group("total")) if done else None,
        }
        if latest is None or rec["rows"] != latest["rows"] or rec["papers"] != latest["papers"]:
            last_growth = rec
        latest = rec
    if not latest or not last_growth:
        return {}
    out = {
        "log_no_evidence_elapsed_s": int(max(0, latest["epoch"] - last_growth["epoch"])),
        "log_latest_done": latest.get("done"),
        "log_latest_total": latest.get("total"),
    }
    if latest.get("done") is not None and last_growth.get("done") is not None:
        out["log_no_evidence_done_delta"] = int(latest["done"]) - int(last_growth["done"])
    return out


def load_section_frontfill_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"available": False, "reason": "unreadable"}
    if not isinstance(state, dict):
        return {"available": False, "reason": "not_object"}
    no_evidence_delta = int(state.get("no_evidence_done_delta") or 0)
    no_evidence_elapsed_s = int(state.get("no_evidence_elapsed_s") or 0)
    low_yield_intervals = int(state.get("low_yield_intervals") or 0)
    log_state = _watchdog_no_evidence_elapsed(path.with_name("section_top12000_watchdog.log"))
    no_evidence_delta = max(no_evidence_delta, int(log_state.get("log_no_evidence_done_delta") or 0))
    no_evidence_elapsed_s = max(no_evidence_elapsed_s, int(log_state.get("log_no_evidence_elapsed_s") or 0))
    if low_yield_intervals >= 2 or no_evidence_elapsed_s >= 4 * 3600:
        status = "soft_stall"
    elif no_evidence_delta >= 200:
        status = "low_yield"
    else:
        status = "running_or_unknown"
    return {
        "available": True,
        "status": status,
        "done": state.get("done"),
        "total": state.get("total"),
        "log_latest_done": log_state.get("log_latest_done"),
        "log_latest_total": log_state.get("log_latest_total"),
        "rows": state.get("rows"),
        "papers": state.get("papers"),
        "primary_section_papers": state.get("primary_section_papers"),
        "no_evidence_done_delta": no_evidence_delta,
        "no_evidence_elapsed_s": no_evidence_elapsed_s,
        "low_yield_intervals": low_yield_intervals,
    }


def collect_metrics(db_main: Path, db_v14: Path) -> dict[str, Any]:
    main = sqlite3.connect(str(db_main))
    try:
        papers = int(scalar(main, "SELECT COUNT(*) FROM papers") or 0)
        refs = int(scalar(main, "SELECT COUNT(*) FROM paper_references") or 0)
        linked_refs = int(
            scalar(
                main,
                """
                SELECT COUNT(*) FROM paper_references
                WHERE COALESCE(cited_paper_id_internal, '') <> ''
                """,
            )
            or 0
        )
        openalex_w = int(
            scalar(
                main,
                """
                SELECT COUNT(*) FROM papers
                WHERE openalex_id LIKE 'W%' OR openalex_id LIKE 'https://openalex.org/W%'
                """,
            )
            or 0
        )
        section_rows = int(scalar(main, "SELECT COUNT(*) FROM paper_sections") or 0)
        section_papers = int(scalar(main, "SELECT COUNT(DISTINCT paper_id) FROM paper_sections") or 0)
        ph = ",".join("?" for _ in PRIMARY_SECTION_NAMES)
        primary_section_papers = int(
            scalar(
                main,
                f"""
                SELECT COUNT(DISTINCT paper_id)
                FROM paper_sections
                WHERE section_name IN ({ph})
                  AND length(trim(section_text)) >= 80
                """,
                tuple(PRIMARY_SECTION_NAMES),
            )
            or 0
        )
    finally:
        main.close()

    v14 = sqlite3.connect(str(db_v14))
    try:
        counts: dict[str, int] = {}
        for table in (
            "predicted_future_edges",
            "limitation_atoms",
            "limitation_resolutions",
            "fusion_evidence_audit",
            "future_directions",
            "direction_claim_cards",
            "visual_edges",
            "branch_lineages",
        ):
            counts[table] = int(scalar(v14, f"SELECT COUNT(*) FROM {table}") or 0) if table_exists(v14, table) else 0
        complete_cards = (
            int(scalar(v14, "SELECT COUNT(*) FROM direction_claim_cards WHERE five_question_complete=1") or 0)
            if table_exists(v14, "direction_claim_cards")
            else 0
        )
        high_conf_cards = (
            int(scalar(v14, "SELECT COUNT(*) FROM direction_claim_cards WHERE high_confidence_eligible=1") or 0)
            if table_exists(v14, "direction_claim_cards")
            else 0
        )
        future_visual_edges = (
            int(scalar(v14, "SELECT COUNT(*) FROM visual_edges WHERE layer='future'") or 0)
            if table_exists(v14, "visual_edges")
            else 0
        )
        latest_fusion = None
        if table_exists(v14, "fusion_evidence_audit") and counts["fusion_evidence_audit"]:
            cols = [r[1] for r in v14.execute("PRAGMA table_info(fusion_evidence_audit)").fetchall()]
            row = v14.execute("SELECT * FROM fusion_evidence_audit ORDER BY rowid DESC LIMIT 1").fetchone()
            latest_fusion = dict(zip(cols, row)) if row else None
    finally:
        v14.close()

    return {
        "papers": papers,
        "refs": refs,
        "linked_refs": linked_refs,
        "linked_ref_rate": linked_refs / max(1, refs),
        "openalex_w": openalex_w,
        "openalex_w_rate": openalex_w / max(1, papers),
        "section_rows": section_rows,
        "section_papers": section_papers,
        "primary_section_papers": primary_section_papers,
        "primary_section_rate": primary_section_papers / max(1, papers),
        **counts,
        "complete_claim_cards": complete_cards,
        "high_confidence_claim_cards": high_conf_cards,
        "future_visual_edges": future_visual_edges,
        "latest_fusion": latest_fusion,
    }


def classify_blockers(m: dict[str, Any]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    if m["linked_ref_rate"] < 0.30:
        blockers.append(
            {
                "gate": "citation_graph_bone",
                "severity": "high",
                "why": f"linked refs are {pct(m['linked_ref_rate'])}; branch/main-path claims need uncertainty labels.",
                "next_action": "Continue provider ID repair and reference relinking after OpenAlex/S2 identifiers stabilize.",
            }
        )
    if m["primary_section_papers"] < 8000:
        blockers.append(
            {
                "gate": "section_evidence",
                "severity": "high",
                "why": f"primary section evidence covers only {m['primary_section_papers']:,} papers.",
                "next_action": "Finish top12000 section ingest, then run delta section queue for main/future/branch/keystone papers.",
            }
        )
    frontfill = m.get("section_frontfill_state") or {}
    if frontfill.get("status") in {"low_yield", "soft_stall"}:
        delta = int(frontfill.get("no_evidence_done_delta") or 0)
        elapsed_h = float(frontfill.get("no_evidence_elapsed_s") or 0) / 3600.0
        delta_text = f"{delta:,} candidates" if delta else "candidate delta unknown"
        blockers.append(
            {
                "gate": "section_frontfill_efficiency",
                "severity": "high" if frontfill.get("status") == "soft_stall" else "medium",
                "why": (
                    f"section frontfill is {frontfill.get('status')}: "
                    f"{delta_text} and {elapsed_h:.1f}h since last evidence growth."
                ),
                "next_action": (
                    "Do not wait passively for topN. Run queue audit/delta handoff for high-value papers "
                    "and classify no-target-section/no-PDF/timeout failures before promoting bottleneck claims."
                ),
            }
        )
    if m["predicted_future_edges"] and not m["future_directions"]:
        blockers.append(
            {
                "gate": "fusion_materialization",
                "severity": "high",
                "why": "Step5b produced future candidates but live future_directions is empty.",
                "next_action": "After section evidence improves, rerun Step5c -> Step6 -> Step13; do not promote raw GNN edges.",
            }
        )
    if m["future_directions"] and not m["direction_claim_cards"]:
        blockers.append(
            {
                "gate": "claim_card_generation",
                "severity": "high",
                "why": "future_directions exist but Step13 Claim Cards are missing.",
                "next_action": "Run Step13 and enforce five-question gates.",
            }
        )
    if m["direction_claim_cards"] and not m["complete_claim_cards"]:
        blockers.append(
            {
                "gate": "radar_eligibility",
                "severity": "medium",
                "why": "Claim Cards exist but none answer all five hard questions.",
                "next_action": "Improve section-level bottleneck, enabler, and minimal validation experiment evidence.",
            }
        )
    if m["openalex_w_rate"] < 0.70:
        blockers.append(
            {
                "gate": "openalex_topic_coverage",
                "severity": "medium",
                "why": f"OpenAlex W coverage is {pct(m['openalex_w_rate'])}; cross-field claims need uncertainty.",
                "next_action": "Keep conservative OpenAlex backfill; use local field/topic fallback while labeling uncertainty.",
            }
        )
    return blockers


def readiness_level(m: dict[str, Any], blockers: list[dict[str, str]]) -> str:
    if m["high_confidence_claim_cards"] > 0:
        return "decision_grade_available"
    if m["complete_claim_cards"] > 0:
        return "actionable_but_not_high_confidence"
    if m["future_visual_edges"] > 0 or m["predicted_future_edges"] > 0:
        return "candidate_generator_only"
    return "not_ready"


def render_markdown(metrics: dict[str, Any], blockers: list[dict[str, str]], level: str) -> str:
    frontfill = metrics.get("section_frontfill_state") or {}
    frontfill_line = []
    if frontfill.get("available"):
        frontfill_line = [
            f"- section frontfill health: {frontfill.get('status')} "
            f"(done={frontfill.get('done')}/{frontfill.get('total')}, "
            f"no_evidence_delta={int(frontfill.get('no_evidence_done_delta') or 0):,}, "
            f"no_evidence_hours={float(frontfill.get('no_evidence_elapsed_s') or 0) / 3600.0:.1f})"
        ]
    lines = [
        "# Direction Readiness Audit",
        "",
        f"- generated_at: `{datetime.utcnow().isoformat(timespec='seconds')}Z`",
        f"- readiness_level: `{level}`",
        "",
        "## Metrics",
        "",
        f"- linked refs: {metrics['linked_refs']:,} / {metrics['refs']:,} ({pct(metrics['linked_ref_rate'])})",
        f"- OpenAlex W IDs: {metrics['openalex_w']:,} ({pct(metrics['openalex_w_rate'])})",
        f"- section evidence: {metrics['section_rows']:,} rows / {metrics['section_papers']:,} papers",
        f"- primary section evidence: {metrics['primary_section_papers']:,} papers ({pct(metrics['primary_section_rate'])})",
        *frontfill_line,
        f"- predicted future edges: {metrics['predicted_future_edges']:,}",
        f"- visual future edges: {metrics['future_visual_edges']:,}",
        f"- future directions: {metrics['future_directions']:,}",
        f"- Claim Cards: {metrics['direction_claim_cards']:,}; complete={metrics['complete_claim_cards']:,}; high_confidence={metrics['high_confidence_claim_cards']:,}",
        "",
        "## Blockers",
        "",
    ]
    if not blockers:
        lines.append("- No blocking gate detected. Run goal alignment audit before promoting claims.")
    for b in blockers:
        lines.append(f"- **{b['gate']}** ({b['severity']}): {b['why']} Next: {b['next_action']}")
    if metrics.get("latest_fusion"):
        lines.extend(["", "## Latest Fusion Audit", "", "```json", json.dumps(metrics["latest_fusion"], ensure_ascii=False, indent=2), "```"])
    if metrics.get("candidate_lifecycle_summary"):
        lifecycle = metrics["candidate_lifecycle_summary"]
        lines.extend(
            [
                "",
                "## Future Candidate Lifecycle",
                "",
                f"- total candidates: {int(lifecycle.get('total_candidates') or 0):,}",
                f"- radar eligible: {int(lifecycle.get('radar_eligible') or 0):,}",
                "",
                "| state | count |",
                "| --- | ---: |",
            ]
        )
        for state, count in sorted((lifecycle.get("state_counts") or {}).items()):
            lines.append(f"| {state} | {int(count):,} |")
        if lifecycle.get("missing_gate_counts"):
            lines.extend(["", "### Missing Claim Gates", "", "| gate | count |", "| --- | ---: |"])
            for gate, count in sorted(
                lifecycle["missing_gate_counts"].items(),
                key=lambda kv: (-kv[1], kv[0]),
            ):
                lines.append(f"| {gate} | {int(count):,} |")
    lines.extend(
        [
            "",
            "## Product Interpretation",
            "",
            "- `candidate_generator_only` means the graph can suggest where to inspect, but Radar must stay empty.",
            "- `actionable_but_not_high_confidence` means Claim Cards are complete but still exploratory.",
            "- `decision_grade_available` requires high-confidence Claim Cards with calibrated future evidence and strong section evidence.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_audit(db_main: Path, db_v14: Path, out_dir: Path) -> dict[str, Any]:
    lifecycle = run_lifecycle_audit(db_main, db_v14, out_dir, write_table=True)
    metrics = collect_metrics(db_main, db_v14)
    metrics["candidate_lifecycle_summary"] = lifecycle["summary"]
    metrics["section_frontfill_state"] = load_section_frontfill_state(
        Path("logs/v14b/section_top12000_watchdog_state.json")
    )
    blockers = classify_blockers(metrics)
    level = readiness_level(metrics, blockers)
    out_dir.mkdir(parents=True, exist_ok=True)
    md = render_markdown(metrics, blockers, level)
    md_path = out_dir / "direction_readiness_audit.md"
    json_path = out_dir / "direction_readiness_audit.json"
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(
        json.dumps({"metrics": metrics, "blockers": blockers, "readiness_level": level}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"readiness_level": level, "blockers": blockers, "report": str(md_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit future direction and Claim Card readiness.")
    parser.add_argument("--db", default="db/echelon_library.sqlite3")
    parser.add_argument("--db-v14", default="db/v14_pilot.sqlite3")
    parser.add_argument("--out-dir", default="reports/v14b_pilot")
    args = parser.parse_args()
    result = run_audit(Path(args.db), Path(args.db_v14), Path(args.out_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
