"""Evidence-bone audit for Echelon V14B.

This audit turns the vague statement "linked refs and section evidence are too
thin" into actionable failure taxonomies.  It is intentionally read-only for
the library and pilot databases, so it can run while section/OpenAlex frontfill
continues.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echelon.v14b.config import DB_MAIN, DB_V14
from echelon.v14b.direction_readiness_audit import PRIMARY_SECTION_NAMES, scalar, table_exists


REFERENCE_KIND_SQL = """
CASE
  WHEN COALESCE(cited_paper_id_provider, '') IN ('doi', 'DOI') OR lower(COALESCE(cited_paper_id_external, '')) LIKE '10.%'
    THEN 'doi_unlinked'
  WHEN COALESCE(cited_paper_id_provider, '') IN ('openalex', 'OpenAlex') OR COALESCE(cited_paper_id_norm, '') LIKE 'W%'
       OR lower(COALESCE(cited_paper_id_external, '')) LIKE '%openalex.org/w%'
    THEN 'openalex_unlinked'
  WHEN COALESCE(cited_paper_id_provider, '') IN ('arxiv', 'arXiv') OR COALESCE(cited_paper_id_norm, '') GLOB '[0-9][0-9][0-9][0-9].*'
       OR lower(COALESCE(cited_paper_id_external, '')) LIKE '%arxiv%'
    THEN 'arxiv_unlinked'
  WHEN lower(COALESCE(cited_paper_id_provider, '')) IN ('s2', 'semantic_scholar', 'semanticscholar')
    THEN 's2_unlinked'
  WHEN COALESCE(cited_paper_id_norm, '') = ''
    THEN 'missing_normalized_id'
  WHEN length(COALESCE(cited_paper_id_external, '')) < 12
    THEN 'weak_reference_string'
  ELSE 'other_unlinked'
END
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def pct(n: int | float, d: int | float) -> float:
    return 0.0 if not d else float(n) / float(d)


def pct_str(value: float) -> str:
    return f"{value * 100:.1f}%"


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=20000")
    return conn


def _rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def reference_taxonomy(conn: sqlite3.Connection, *, sample_limit: int = 8) -> dict[str, Any]:
    if not table_exists(conn, "paper_references"):
        return {"available": False, "reason": "paper_references table missing"}
    total = int(scalar(conn, "SELECT COUNT(*) FROM paper_references") or 0)
    linked = int(
        scalar(
            conn,
            "SELECT COUNT(*) FROM paper_references WHERE COALESCE(cited_paper_id_internal, '') <> ''",
        )
        or 0
    )
    grouped = _rows(
        conn,
        f"""
        SELECT {REFERENCE_KIND_SQL} AS kind, COUNT(*) AS n
        FROM paper_references
        WHERE COALESCE(cited_paper_id_internal, '') = ''
        GROUP BY kind
        ORDER BY n DESC
        """,
    )
    samples: dict[str, list[dict[str, Any]]] = {}
    for row in grouped:
        kind = str(row["kind"])
        samples[kind] = _rows(
            conn,
            f"""
            SELECT citing_paper_id, cited_paper_id_external, cited_paper_id_provider, cited_paper_id_norm
            FROM paper_references
            WHERE COALESCE(cited_paper_id_internal, '') = ''
              AND {REFERENCE_KIND_SQL} = ?
            LIMIT ?
            """,
            (kind, sample_limit),
        )
    return {
        "available": True,
        "refs_total": total,
        "linked_refs": linked,
        "unlinked_refs": total - linked,
        "linked_ref_rate": pct(linked, total),
        "taxonomy": grouped,
        "samples": samples,
        "next_actions": _reference_next_actions(grouped),
    }


def _reference_next_actions(grouped: list[dict[str, Any]]) -> list[str]:
    counts = {str(r["kind"]): int(r["n"] or 0) for r in grouped}
    actions: list[str] = []
    if counts.get("doi_unlinked", 0):
        actions.append("Run DOI-normalized relinking before adding more crawlers; DOI refs should be exact local joins.")
    if counts.get("openalex_unlinked", 0):
        actions.append("Continue OpenAlex W backfill and relink W IDs after each successful batch.")
    if counts.get("arxiv_unlinked", 0):
        actions.append("Normalize arXiv version/category variants, then relink against arxiv_id.")
    if counts.get("missing_normalized_id", 0) or counts.get("weak_reference_string", 0):
        actions.append("Add title/year reference parsing only for high-value unresolved refs; do not fuzzy-link all refs blindly.")
    if counts.get("s2_unlinked", 0):
        actions.append("Keep S2 IDs separate from OpenAlex IDs and relink through s2_paper_id.")
    return actions


def section_coverage(conn_main: sqlite3.Connection, conn_v14: sqlite3.Connection) -> dict[str, Any]:
    if not table_exists(conn_main, "paper_sections"):
        return {"available": False, "reason": "paper_sections table missing"}
    ph = ",".join("?" for _ in PRIMARY_SECTION_NAMES)
    rows = int(scalar(conn_main, "SELECT COUNT(*) FROM paper_sections") or 0)
    papers = int(scalar(conn_main, "SELECT COUNT(DISTINCT paper_id) FROM paper_sections") or 0)
    primary = int(
        scalar(
            conn_main,
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
    section_name_rows = _rows(
        conn_main,
        """
        SELECT lower(section_name) AS section_name, COUNT(*) AS rows, COUNT(DISTINCT paper_id) AS papers
        FROM paper_sections
        GROUP BY lower(section_name)
        ORDER BY rows DESC
        LIMIT 20
        """,
    )
    priority_summary = []
    priority_totals = {}
    if table_exists(conn_v14, "section_priority_summary"):
        latest = scalar(conn_v14, "SELECT MAX(audit_ts) FROM section_priority_summary")
        if latest:
            priority_summary = _rows(
                conn_v14,
                """
                SELECT category, total, in_top_n, any_section, primary_section, eligible_pdf, coverage_json
                FROM section_priority_summary
                WHERE audit_ts = ?
                ORDER BY total DESC, category
                """,
                (latest,),
            )
    if table_exists(conn_v14, "section_priority_papers"):
        priority_totals = {
            "high_value_papers": int(scalar(conn_v14, "SELECT COUNT(*) FROM section_priority_papers") or 0),
            "missing_primary_with_pdf": int(
                scalar(
                    conn_v14,
                    "SELECT COUNT(*) FROM section_priority_papers WHERE has_primary_section=0 AND eligible_pdf=1",
                )
                or 0
            ),
            "missing_primary_in_top_n": int(
                scalar(
                    conn_v14,
                    "SELECT COUNT(*) FROM section_priority_papers WHERE has_primary_section=0 AND eligible_pdf=1 AND in_top_n=1",
                )
                or 0
            ),
        }
    return {
        "available": True,
        "section_rows": rows,
        "section_papers": papers,
        "primary_section_papers": primary,
        "section_name_distribution": section_name_rows,
        "priority_totals": priority_totals,
        "priority_summary": priority_summary,
        "next_actions": _section_next_actions(priority_summary, priority_totals),
    }


def _section_next_actions(summary: list[dict[str, Any]], totals: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    if totals.get("missing_primary_with_pdf", 0):
        actions.append("After top12000 completes, run delta queue for high-value papers missing primary sections.")
    weak_categories = [
        str(row["category"])
        for row in summary
        if int(row.get("total") or 0) >= 10 and pct(int(row.get("primary_section") or 0), int(row.get("total") or 0)) < 0.20
    ]
    if weak_categories:
        actions.append("Prioritize section evidence for weak high-value classes: " + ", ".join(weak_categories[:8]))
    return actions


LOG_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pdf_graphics_warning", re.compile(r"Cannot set gray .* color", re.I)),
    ("timeout", re.compile(r"timeout|timed out", re.I)),
    ("download_failure", re.compile(r"download|http|connection|server disconnected|failed", re.I)),
    ("parser_exception", re.compile(r"traceback|exception|error", re.I)),
    ("low_yield_scan", re.compile(r"LOW_YIELD_SCAN", re.I)),
    ("hard_stall", re.compile(r"HARD_STALL", re.I)),
)


def section_log_taxonomy(log_paths: list[Path]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    samples: dict[str, list[str]] = {}
    progress = {"done": None, "total": None, "raw": ""}
    progress_re = re.compile(r"(?P<done>\d+)\s*/\s*(?P<total>\d+)")
    for path in log_paths:
        if not path.exists():
            continue
        for line in path.read_text(errors="ignore").splitlines():
            if "Step5s sections:" in line:
                m = progress_re.search(line)
                if m:
                    progress = {"done": int(m.group("done")), "total": int(m.group("total")), "raw": line[-260:]}
            for label, pattern in LOG_PATTERNS:
                if pattern.search(line):
                    counts[label] += 1
                    samples.setdefault(label, [])
                    if len(samples[label]) < 5:
                        samples[label].append(line[:300])
    return {
        "event_counts": dict(counts),
        "samples": samples,
        "progress": progress,
        "next_actions": _log_next_actions(counts),
    }


def _log_next_actions(counts: Counter[str]) -> list[str]:
    actions: list[str] = []
    if counts.get("pdf_graphics_warning", 0) > 100:
        actions.append("Suppress or downgrade noisy PDF graphics warnings so true parser failures remain visible.")
    if counts.get("low_yield_scan", 0):
        actions.append("Treat current low-yield section segment as evidence-budget issue; rely on delta queue handoff after topN.")
    if counts.get("timeout", 0) or counts.get("download_failure", 0):
        actions.append("Keep single-process section ingest and add retry classification before increasing concurrency.")
    return actions


def collect_audit(
    *,
    db_main: Path,
    db_v14: Path,
    section_log: Path,
    watchdog_log: Path,
    openalex_log: Path,
) -> dict[str, Any]:
    with connect(db_main) as conn_main, connect(db_v14) as conn_v14:
        refs = reference_taxonomy(conn_main)
        sections = section_coverage(conn_main, conn_v14)
    logs = section_log_taxonomy([section_log, watchdog_log, openalex_log])
    return {
        "generated_at": utc_now(),
        "reference_taxonomy": refs,
        "section_coverage": sections,
        "frontfill_log_taxonomy": logs,
        "product_interpretation": (
            "Evidence Bone remains the limiting factor if linked refs are below 30% "
            "or primary section evidence is below the high-value claim budget. "
            "The graph can guide inspection, but claims must remain scoped and uncertainty-labeled."
        ),
    }


def render_markdown(result: dict[str, Any]) -> str:
    refs = result["reference_taxonomy"]
    sections = result["section_coverage"]
    logs = result["frontfill_log_taxonomy"]
    lines = [
        "# V14B Evidence Bone Audit",
        "",
        f"- generated_at: `{result['generated_at']}`",
        "",
        "## Reference Linkage",
        "",
    ]
    if refs.get("available"):
        lines.extend(
            [
                f"- linked refs: {refs['linked_refs']:,} / {refs['refs_total']:,} ({pct_str(refs['linked_ref_rate'])})",
                f"- unlinked refs: {refs['unlinked_refs']:,}",
                "",
                "| unlinked kind | count |",
                "| --- | ---: |",
            ]
        )
        for row in refs["taxonomy"]:
            lines.append(f"| {row['kind']} | {int(row['n']):,} |")
    else:
        lines.append(f"- unavailable: {refs.get('reason')}")
    lines.extend(["", "## Section Evidence", ""])
    if sections.get("available"):
        lines.extend(
            [
                f"- section rows: {sections['section_rows']:,}",
                f"- section papers: {sections['section_papers']:,}",
                f"- primary section papers: {sections['primary_section_papers']:,}",
                "",
                "### High-Value Priority Coverage",
                "",
                "| category | total | in topN | any section | primary section | eligible PDF |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in sections.get("priority_summary") or []:
            lines.append(
                f"| {row['category']} | {int(row['total']):,} | {int(row['in_top_n']):,} | "
                f"{int(row['any_section']):,} | {int(row['primary_section']):,} | {int(row['eligible_pdf']):,} |"
            )
    else:
        lines.append(f"- unavailable: {sections.get('reason')}")
    lines.extend(["", "## Frontfill Log Signals", "", "| event | count |", "| --- | ---: |"])
    for key, value in sorted((logs.get("event_counts") or {}).items(), key=lambda kv: kv[1], reverse=True):
        lines.append(f"| {key} | {value:,} |")
    prog = logs.get("progress") or {}
    if prog.get("done"):
        lines.extend(["", f"- section progress: {prog.get('done')}/{prog.get('total')}"])
    lines.extend(["", "## Recommended Next Actions", ""])
    actions = []
    actions.extend(refs.get("next_actions") or [])
    actions.extend(sections.get("next_actions") or [])
    actions.extend(logs.get("next_actions") or [])
    if not actions:
        actions.append("No immediate evidence-bone action found; continue frontfill monitoring.")
    for action in actions:
        lines.append(f"- {action}")
    lines.extend(["", "## Product Interpretation", "", result["product_interpretation"]])
    return "\n".join(lines) + "\n"


def run_audit(
    *,
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    out_dir: Path = Path("reports/v14b_pilot"),
    section_log: Path = Path("logs/v14b/step5s_section_top12000.log"),
    watchdog_log: Path = Path("logs/v14b/section_top12000_watchdog.log"),
    openalex_log: Path = Path("logs/v14b/openalex_backfill_current.log"),
) -> dict[str, Any]:
    result = collect_audit(
        db_main=db_main,
        db_v14=db_v14,
        section_log=section_log,
        watchdog_log=watchdog_log,
        openalex_log=openalex_log,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "evidence_bone_audit.md"
    json_path = out_dir / "evidence_bone_audit.json"
    md_path.write_text(render_markdown(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"report": str(md_path), "json": str(json_path), "generated_at": result["generated_at"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit V14B evidence bone failure taxonomy.")
    parser.add_argument("--db", default=str(DB_MAIN))
    parser.add_argument("--db-v14", default=str(DB_V14))
    parser.add_argument("--out-dir", default="reports/v14b_pilot")
    parser.add_argument("--section-log", default="logs/v14b/step5s_section_top12000.log")
    parser.add_argument("--watchdog-log", default="logs/v14b/section_top12000_watchdog.log")
    parser.add_argument("--openalex-log", default="logs/v14b/openalex_backfill_current.log")
    args = parser.parse_args()
    result = run_audit(
        db_main=Path(args.db),
        db_v14=Path(args.db_v14),
        out_dir=Path(args.out_dir),
        section_log=Path(args.section_log),
        watchdog_log=Path(args.watchdog_log),
        openalex_log=Path(args.openalex_log),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
