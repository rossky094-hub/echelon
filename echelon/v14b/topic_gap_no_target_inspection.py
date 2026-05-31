"""Inspect current-parser no-target topic-gap PDFs without promoting evidence.

This is a deliberately read-only audit.  When Step5s records
``no_target_sections`` under the current parser contract, the right response is
not to loosen extraction until tests pass.  First classify whether the PDF has
auditable target-heading signals at all, or whether it is a short/letter-style
paper with only abstract/body/references text.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from echelon.v14b.config import DB_MAIN, REPORT_DIR, SECTION_INGEST_TIMEOUT_SEC
from echelon.v14b.step5s_section_ingest import (
    SECTION_INGEST_MIN_CHARS,
    SECTION_PARSER_CONTRACT_VERSION,
    _embedded_heading_sections,
    _heading_to_section,
    _inline_heading_to_section,
    parse_pdf_pages_with_timeout,
)
from echelon.v14b.topic_gap_section_evidence_audit import (
    load_topic_gap_section_triage_state,
)
from echelon.v14b.utils import add_common_args, setup_logging

logger = logging.getLogger("echelon.v14b.topic_gap_no_target_inspection")

NON_TARGET_HEADING_RE = re.compile(
    r"^\s*(abstract|introduction|background|theory|model|references|bibliography|"
    r"acknowledg(e)?ments?|appendix|supplementary|supporting information)\s*[:.\-–—]*\s*$",
    re.I,
)
HEADINGISH_RE = re.compile(
    r"^\s*(?:section\s+)?(?:\d+(?:\.\d+)*|[ivx]+|[a-z])?[\).:\s-]*"
    r"[A-Z][A-Za-z0-9,&()/+' -]{2,90}\s*[:.\-–—]?\s*$"
)


@dataclass
class HeadingProbe:
    page_no: int
    text: str
    kind: str
    section: str = ""
    strategy: str = ""
    body_chars: int = 0


def _clean_line(raw: str) -> str:
    return " ".join(str(raw or "").replace("\x00", " ").split())


def inspect_no_target_blocks(blocks: list[Any]) -> dict[str, Any]:
    """Classify parser no-target failures from parsed PDF blocks."""
    probes: list[HeadingProbe] = []
    pages_with_text: set[int] = set()
    total_chars = 0
    for block in blocks:
        text = str(getattr(block, "text", "") or "").replace("\x00", " ").strip()
        if not text:
            continue
        page_no = int(getattr(block, "page_no", 0) or 0)
        if page_no:
            pages_with_text.add(page_no)
        total_chars += len(text)
        for line in text.splitlines():
            clean = _clean_line(line)
            if not clean:
                continue
            heading = _heading_to_section(clean)
            if heading:
                probes.append(HeadingProbe(page_no, clean[:220], "target_explicit", heading, "explicit_heading"))
                continue
            inline_heading, inline_rest, inline_strategy = _inline_heading_to_section(clean)
            if inline_heading:
                probes.append(
                    HeadingProbe(
                        page_no,
                        clean[:220],
                        "target_inline",
                        inline_heading,
                        inline_strategy or "inline_heading",
                        len(inline_rest),
                    )
                )
                continue
            if NON_TARGET_HEADING_RE.match(clean):
                probes.append(HeadingProbe(page_no, clean[:220], "non_target_heading"))
            elif HEADINGISH_RE.match(clean) and len(clean) <= 120:
                probes.append(HeadingProbe(page_no, clean[:220], "heading_like"))
        for section_name, body in _embedded_heading_sections(text):
            probes.append(
                HeadingProbe(
                    page_no,
                    _clean_line(body[:220]),
                    "target_embedded",
                    section_name,
                    "embedded_heading",
                    len(body),
                )
            )

    target = [p for p in probes if p.kind.startswith("target_")]
    target_long = [
        p for p in target
        if p.kind == "target_explicit" or p.body_chars >= SECTION_INGEST_MIN_CHARS
    ]
    non_target = [p for p in probes if p.kind == "non_target_heading"]
    heading_like = [p for p in probes if p.kind == "heading_like"]
    if not blocks or total_chars == 0:
        classification = "parse_no_text"
    elif target_long:
        classification = "target_heading_signal_present"
    elif target:
        classification = "target_heading_signal_subthreshold"
    elif non_target and not target:
        classification = "sectionless_or_non_target_heading_format"
    elif heading_like:
        classification = "heading_like_but_not_target_section"
    else:
        classification = "no_heading_signal_detected"

    return {
        "classification": classification,
        "pages_with_text": len(pages_with_text),
        "text_blocks": len(blocks),
        "total_chars": total_chars,
        "target_heading_candidates": [
            {
                "page_no": p.page_no,
                "text": p.text,
                "section": p.section,
                "strategy": p.strategy,
                "body_chars": p.body_chars,
            }
            for p in target[:10]
        ],
        "non_target_heading_examples": [
            {"page_no": p.page_no, "text": p.text}
            for p in non_target[:10]
        ],
        "heading_like_examples": [
            {"page_no": p.page_no, "text": p.text}
            for p in heading_like[:10]
        ],
    }


def _load_triage_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = loaded.get("rows") if isinstance(loaded, dict) else []
    return [r for r in rows if isinstance(r, dict)]


def _latest_attempts(conn: sqlite3.Connection, paper_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not paper_ids:
        return {}
    ph = ",".join("?" for _ in paper_ids)
    rows = conn.execute(
        f"""
        SELECT * FROM (
            SELECT paper_id, attempt_ts, outcome, source_url, parser_name,
                   parser_contract_version,
                   ROW_NUMBER() OVER (
                       PARTITION BY paper_id
                       ORDER BY attempt_ts DESC, attempt_id DESC
                   ) AS rn
            FROM section_ingest_attempts
            WHERE paper_id IN ({ph})
        )
        WHERE rn = 1
        """,
        paper_ids,
    ).fetchall()
    return {str(row["paper_id"]): dict(row) for row in rows}


def run_no_target_inspection(
    *,
    db_main: Path = DB_MAIN,
    triage_json: Path = REPORT_DIR / "topic_gap_section_evidence_audit.json",
    out_dir: Path = REPORT_DIR,
    limit: int | None = None,
) -> dict[str, Any]:
    triage_state = load_topic_gap_section_triage_state(triage_json)
    triage_rows = _load_triage_rows(triage_json)
    targets = [
        row for row in triage_rows
        if row.get("failure_mode") == "no_target_sections_after_current_parser"
    ]
    if limit:
        targets = targets[: int(limit)]
    paper_ids = [str(row.get("paper_id")) for row in targets if row.get("paper_id")]

    conn = sqlite3.connect(str(db_main))
    conn.row_factory = sqlite3.Row
    try:
        attempts = _latest_attempts(conn, paper_ids)
    finally:
        conn.close()

    audit_ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    rows: list[dict[str, Any]] = []
    with httpx.Client(follow_redirects=True, timeout=SECTION_INGEST_TIMEOUT_SEC) as client:
        for row in targets:
            pid = str(row.get("paper_id") or "")
            source_url = str(row.get("source_url") or (attempts.get(pid) or {}).get("source_url") or "")
            payload = {
                "paper_id": pid,
                "title": row.get("title") or "",
                "topics": row.get("topics") or [],
                "source_url": source_url,
                "latest_attempt_outcome": (attempts.get(pid) or {}).get("outcome") or "",
                "latest_attempt_contract": (attempts.get(pid) or {}).get("parser_contract_version") or "",
            }
            if not source_url:
                rows.append({**payload, "classification": "missing_source_url", "error": "no source_url"})
                continue
            try:
                response = client.get(source_url)
                if response.status_code != 200 or not response.content:
                    rows.append(
                        {
                            **payload,
                            "classification": "download_failed",
                            "error": f"status={response.status_code}",
                        }
                    )
                    continue
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(response.content)
                    tmp_path = tmp.name
                try:
                    blocks = parse_pdf_pages_with_timeout(tmp_path)
                    inspected = inspect_no_target_blocks(blocks)
                finally:
                    Path(tmp_path).unlink(missing_ok=True)
                rows.append({**payload, **inspected, "download_bytes": len(response.content)})
            except Exception as exc:
                logger.warning("no-target inspection failed paper=%s url=%s: %s", pid, source_url, exc)
                rows.append(
                    {
                        **payload,
                        "classification": "inspection_failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    classification_counts = Counter(str(row.get("classification") or "unknown") for row in rows)
    parser_signal = int(classification_counts.get("target_heading_signal_present") or 0)
    subthreshold_signal = int(classification_counts.get("target_heading_signal_subthreshold") or 0)
    sectionless = int(classification_counts.get("sectionless_or_non_target_heading_format") or 0)
    summary = {
        "status": "warn" if parser_signal else "pass",
        "inspected_papers": len(rows),
        "source_triage_available": bool(triage_state.get("available")),
        "source_triage_status": triage_state.get("status") or "",
        "classification_counts": dict(classification_counts),
        "parser_target_signal_papers": parser_signal,
        "subthreshold_target_signal_papers": subthreshold_signal,
        "sectionless_or_non_target_heading_papers": sectionless,
        "policy": (
            "Current-parser no-target papers are not decision-grade section evidence. "
            "Only rows with target_heading_signal_present should be treated as parser repair candidates; "
            "subthreshold target signals and sectionless/non-target-heading papers remain weak full-text or metadata evidence."
        ),
    }
    result = {
        "audit_ts": audit_ts,
        "db_main": str(db_main),
        "triage_json": str(triage_json),
        "section_parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
        "summary": summary,
        "rows": rows,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "topic_gap_no_target_inspection.json"
    md_path = out_dir / "topic_gap_no_target_inspection.md"
    result["outputs"] = {"json": str(json_path), "markdown": str(md_path)}
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_render_markdown(result), encoding="utf-8")
    return result


def _md_cell(raw: Any) -> str:
    if isinstance(raw, list):
        raw = ", ".join(str(item) for item in raw)
    return " ".join(str(raw or "").replace("|", ";").split())


def _render_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# Topic-Gap No-Target PDF Inspection",
        "",
        f"- audit_ts: `{result['audit_ts']}`",
        f"- triage_json: `{result['triage_json']}`",
        f"- parser_contract: `{result['section_parser_contract_version']}`",
        f"- status: `{summary['status']}`",
        f"- inspected papers: `{summary['inspected_papers']}`",
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
            "## Papers",
            "",
            "| paper_id | topics | classification | target signals | non-target examples | title |",
            "|---|---|---|---:|---|---|",
        ]
    )
    for row in result.get("rows") or []:
        target_count = len(row.get("target_heading_candidates") or [])
        non_target = "; ".join(
            _md_cell(item.get("text")) for item in (row.get("non_target_heading_examples") or [])[:3]
        )
        lines.append(
            f"| `{_md_cell(row.get('paper_id'))}` | {_md_cell(row.get('topics'))} | "
            f"`{_md_cell(row.get('classification'))}` | {target_count} | "
            f"{_md_cell(non_target)} | {_md_cell(row.get('title'))} |"
        )
    lines.extend(["", "## Policy", "", summary["policy"]])
    return "\n".join(lines) + "\n"


def load_topic_gap_no_target_inspection_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"available": False, "reason": "unreadable", "path": str(path)}
    summary = loaded.get("summary") if isinstance(loaded, dict) else {}
    if not isinstance(summary, dict):
        return {"available": False, "reason": "missing_summary", "path": str(path)}
    counts = summary.get("classification_counts") or {}
    parser_signal = int(summary.get("parser_target_signal_papers") or 0)
    if parser_signal:
        next_action = (
            "Review target-heading signal rows as parser repair candidates before changing section gates."
        )
    else:
        next_action = (
            "Do not loosen the current parser for the no-target bucket; keep those papers as weak full-text "
            "or metadata evidence and focus repair effort on stale-contract reparse and unattempted PDFs."
        )
    return {
        "available": True,
        "path": str(path),
        "status": str(summary.get("status") or "unknown"),
        "inspected_papers": int(summary.get("inspected_papers") or 0),
        "classification_counts": counts,
        "parser_target_signal_papers": parser_signal,
        "subthreshold_target_signal_papers": int(summary.get("subthreshold_target_signal_papers") or 0),
        "sectionless_or_non_target_heading_papers": int(
            summary.get("sectionless_or_non_target_heading_papers") or 0
        ),
        "next_action": next_action,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Inspect no-target topic-gap PDFs for target section-heading signals."
    )
    add_common_args(parser)
    parser.add_argument(
        "--triage-json",
        type=Path,
        default=REPORT_DIR / "topic_gap_section_evidence_audit.json",
    )
    parser.add_argument("--out-dir", type=Path, default=REPORT_DIR)
    args = parser.parse_args(argv)
    setup_logging(
        "topic_gap_no_target_inspection",
        level=getattr(logging, args.log_level),
    )
    result = run_no_target_inspection(
        db_main=Path(args.db) if args.db else DB_MAIN,
        triage_json=args.triage_json,
        out_dir=args.out_dir,
        limit=args.limit,
    )
    print(json.dumps({"summary": result["summary"], "outputs": result["outputs"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
