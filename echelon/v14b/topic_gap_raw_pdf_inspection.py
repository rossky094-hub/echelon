"""Inspect locally cached topic-gap PDFs without writing section evidence.

This audit turns the external raw PDF store into a parser-tuning work queue.
It answers a narrow question: among benchmark-topic evidence gaps that already
have a local raw PDF, can the current Step5s parser extract decision-grade
candidate sections, or is the blocker really parser/no-target/full-text shape?
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echelon.v14b.config import DB_MAIN, RAW_PDF_MANIFEST, RAW_PDF_STORE_ROOT, REPORT_DIR
from echelon.v14b.evidence_contracts import PRIMARY_SECTION_NAMES, SECTION_PARSER_CONTRACT_VERSION
from echelon.v14b.step5s_section_ingest import (
    SECTION_INGEST_MIN_CHARS,
    _local_raw_pdf_path,
    extract_sections_with_metadata,
    parse_pdf_pages_with_timeout,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_triage_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = loaded.get("rows") if isinstance(loaded, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def _load_papers(db_main: Path, paper_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not paper_ids:
        return {}
    uri = f"file:{db_main}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        out: dict[str, dict[str, Any]] = {}
        for start in range(0, len(paper_ids), 500):
            chunk = paper_ids[start : start + 500]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"""
                SELECT id, title, arxiv_id, doi, s2_paper_id
                FROM papers
                WHERE id IN ({placeholders})
                """,
                chunk,
            ).fetchall()
            for row in rows:
                out[str(row["id"])] = dict(row)
        return out
    finally:
        conn.close()


def inspect_parsed_blocks(blocks: list[Any]) -> dict[str, Any]:
    sections = extract_sections_with_metadata(blocks)
    primary_sections = sorted(sec for sec in sections if sec in PRIMARY_SECTION_NAMES)
    secondary_sections = sorted(sec for sec in sections if sec not in PRIMARY_SECTION_NAMES)
    if primary_sections:
        classification = "parser_success_primary"
    elif sections:
        classification = "parser_success_secondary_only"
    else:
        classification = "parser_no_target_sections"
    strategies: dict[str, list[str]] = {}
    section_chars: dict[str, int] = {}
    section_pages: dict[str, list[int]] = {}
    for name, payload in sections.items():
        strategies[name] = sorted(str(item) for item in (payload.get("extraction_strategies") or []))
        section_chars[name] = len(str(payload.get("text") or ""))
        section_pages[name] = [
            int(p)
            for p in (payload.get("pages") or [])
            if isinstance(p, (int, float)) and int(p) > 0
        ]
    return {
        "classification": classification,
        "text_blocks": len(blocks),
        "section_names": sorted(sections),
        "primary_sections": primary_sections,
        "secondary_sections": secondary_sections,
        "extraction_strategies": strategies,
        "section_chars": section_chars,
        "section_pages": section_pages,
        "min_section_chars": SECTION_INGEST_MIN_CHARS,
    }


def run_topic_gap_raw_pdf_inspection(
    *,
    db_main: Path = DB_MAIN,
    triage_json: Path = REPORT_DIR / "topic_gap_section_evidence_audit.json",
    store_root: Path | None = RAW_PDF_STORE_ROOT,
    manifest_path: Path | None = RAW_PDF_MANIFEST,
    out_dir: Path = REPORT_DIR,
    limit: int | None = None,
) -> dict[str, Any]:
    triage_rows = _load_triage_rows(triage_json)
    if limit is not None:
        triage_rows = triage_rows[: int(limit)]
    paper_ids = [str(row.get("paper_id") or "") for row in triage_rows if row.get("paper_id")]
    papers = _load_papers(db_main, paper_ids)
    rows: list[dict[str, Any]] = []
    skipped_no_local = 0

    for triage in triage_rows:
        paper_id = str(triage.get("paper_id") or "")
        paper = {**triage, **(papers.get(paper_id) or {})}
        paper["id"] = paper_id
        local_path = _local_raw_pdf_path(paper, store_root=store_root, manifest_path=manifest_path)
        if not local_path:
            skipped_no_local += 1
            continue
        payload = {
            "paper_id": paper_id,
            "title": paper.get("title") or triage.get("title") or "",
            "topics": triage.get("topics") or [],
            "failure_mode": triage.get("failure_mode") or "",
            "promotion_policy": triage.get("promotion_policy") or "",
            "local_pdf_path": str(local_path),
        }
        try:
            blocks = parse_pdf_pages_with_timeout(str(local_path))
            inspected = inspect_parsed_blocks(blocks)
            rows.append({**payload, **inspected})
        except Exception as exc:
            rows.append(
                {
                    **payload,
                    "classification": "parser_exception",
                    "error": f"{type(exc).__name__}: {exc}",
                    "section_names": [],
                    "primary_sections": [],
                    "secondary_sections": [],
                    "extraction_strategies": {},
                    "section_chars": {},
                    "section_pages": {},
                    "min_section_chars": SECTION_INGEST_MIN_CHARS,
                }
            )

    counts = Counter(str(row.get("classification") or "unknown") for row in rows)
    primary_ready = int(counts.get("parser_success_primary") or 0)
    primary_ready_repair_candidates = sum(
        1
        for row in rows
        if row.get("classification") == "parser_success_primary"
        and row.get("promotion_policy") != "covered"
        and row.get("failure_mode") != "decision_grade_current_contract"
    )
    primary_ready_already_covered = primary_ready - primary_ready_repair_candidates
    no_target = int(counts.get("parser_no_target_sections") or 0)
    parser_exceptions = int(counts.get("parser_exception") or 0)
    status = "pass" if primary_ready_repair_candidates else ("warn" if rows else "missing_local_pdf")
    summary = {
        "status": status,
        "triage_papers": len(triage_rows),
        "local_pdf_available_papers": len(rows),
        "skipped_no_local_pdf": skipped_no_local,
        "parser_primary_ready_papers": primary_ready,
        "parser_primary_ready_repair_candidates": primary_ready_repair_candidates,
        "parser_primary_ready_already_covered": primary_ready_already_covered,
        "parser_no_target_papers": no_target,
        "parser_exception_papers": parser_exceptions,
        "classification_counts": dict(counts),
        "policy": (
            "This is a read-only parser dry run. Rows with parser_success_primary and candidate_pool_only policy "
            "are local-cache candidates for the next safe Step5s ingest boundary; already-covered rows are useful "
            "parser controls but not counted as repair lift. No row is promoted until paper_sections, section_atoms, "
            "and typed chains are rebuilt with provenance."
        ),
    }
    result = {
        "audit_ts": utc_now(),
        "db_main": str(db_main),
        "triage_json": str(triage_json),
        "store_root": str(store_root or ""),
        "manifest_path": str(manifest_path or ""),
        "section_parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
        "summary": summary,
        "rows": rows,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "topic_gap_raw_pdf_inspection.json"
    md_path = out_dir / "topic_gap_raw_pdf_inspection.md"
    result["outputs"] = {"json": str(json_path), "markdown": str(md_path)}
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    md_path.write_text(_render_markdown(result), encoding="utf-8")
    return result


def load_topic_gap_raw_pdf_inspection_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"available": False, "reason": "unreadable", "path": str(path)}
    summary = loaded.get("summary") if isinstance(loaded, dict) else {}
    if not isinstance(summary, dict):
        return {"available": False, "reason": "missing_summary", "path": str(path)}
    return {
        "available": True,
        "path": str(path),
        "status": str(summary.get("status") or "unknown"),
        "triage_papers": int(summary.get("triage_papers") or 0),
        "local_pdf_available_papers": int(summary.get("local_pdf_available_papers") or 0),
        "parser_primary_ready_papers": int(summary.get("parser_primary_ready_papers") or 0),
        "parser_primary_ready_repair_candidates": int(
            summary.get("parser_primary_ready_repair_candidates") or 0
        ),
        "parser_primary_ready_already_covered": int(
            summary.get("parser_primary_ready_already_covered") or 0
        ),
        "parser_no_target_papers": int(summary.get("parser_no_target_papers") or 0),
        "parser_exception_papers": int(summary.get("parser_exception_papers") or 0),
        "classification_counts": summary.get("classification_counts") or {},
    }


def _md_cell(raw: Any) -> str:
    if isinstance(raw, list):
        raw = ", ".join(str(item) for item in raw)
    return " ".join(str(raw or "").replace("|", ";").split())


def _section_strategy_cell(row: dict[str, Any]) -> str:
    strategies = row.get("extraction_strategies") or {}
    if not isinstance(strategies, dict):
        return ""
    parts = []
    for section_name, values in sorted(strategies.items()):
        parts.append(f"{section_name}:{','.join(str(v) for v in values)}")
    return "; ".join(parts)


def _render_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# Topic-Gap Raw PDF Parser Inspection",
        "",
        f"- audit_ts: `{result['audit_ts']}`",
        f"- triage_json: `{result['triage_json']}`",
        f"- store_root: `{result['store_root']}`",
        f"- manifest: `{result['manifest_path']}`",
        f"- parser_contract: `{result['section_parser_contract_version']}`",
        f"- status: `{summary['status']}`",
        "",
        "## Summary",
        "",
        f"- triage papers: {summary['triage_papers']}",
        f"- local PDF available papers: {summary['local_pdf_available_papers']}",
        f"- skipped no local PDF: {summary['skipped_no_local_pdf']}",
        f"- parser primary-ready papers: {summary['parser_primary_ready_papers']}",
        f"- parser primary-ready repair candidates: {summary['parser_primary_ready_repair_candidates']}",
        f"- parser primary-ready already covered: {summary['parser_primary_ready_already_covered']}",
        f"- parser no-target papers: {summary['parser_no_target_papers']}",
        f"- parser exception papers: {summary['parser_exception_papers']}",
        "",
        "## Classification Counts",
        "",
        "| classification | papers |",
        "|---|---:|",
    ]
    for name, count in Counter(summary["classification_counts"]).most_common():
        lines.append(f"| {name} | {count:,} |")
    lines.extend(
        [
            "",
            "## Local PDF Rows",
            "",
            "| paper_id | topics | triage failure | parser classification | primary sections | section strategies | title |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for row in result.get("rows") or []:
        lines.append(
            f"| `{_md_cell(row.get('paper_id'))}` | {_md_cell(row.get('topics'))} | "
            f"`{_md_cell(row.get('failure_mode'))}` | `{_md_cell(row.get('classification'))}` | "
            f"{_md_cell(row.get('primary_sections'))} | {_md_cell(_section_strategy_cell(row))} | "
            f"{_md_cell(row.get('title'))} |"
        )
    lines.extend(["", "## Policy", "", summary["policy"], ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Inspect topic-gap PDFs already present in the raw PDF cache.")
    parser.add_argument("--db", default=str(DB_MAIN))
    parser.add_argument("--triage-json", default=str(REPORT_DIR / "topic_gap_section_evidence_audit.json"))
    parser.add_argument("--store-root", default=str(RAW_PDF_STORE_ROOT or ""))
    parser.add_argument("--manifest", default=str(RAW_PDF_MANIFEST or ""))
    parser.add_argument("--out-dir", default=str(REPORT_DIR))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    result = run_topic_gap_raw_pdf_inspection(
        db_main=Path(args.db),
        triage_json=Path(args.triage_json),
        store_root=Path(args.store_root).expanduser() if args.store_root else None,
        manifest_path=Path(args.manifest).expanduser() if args.manifest else None,
        out_dir=Path(args.out_dir),
        limit=args.limit,
    )
    print(json.dumps({"summary": result["summary"], "outputs": result["outputs"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
