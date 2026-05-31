"""Read-only audit for the external raw PDF store.

The raw PDF crawler is useful only if downstream section ingest can reuse it.
This audit keeps that contract visible without writing to the main DB or the
external manifest.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echelon.v14b.config import DB_MAIN, RAW_PDF_MANIFEST, RAW_PDF_STORE_ROOT, REPORT_DIR
from echelon.v14b.step5s_section_ingest import _local_raw_pdf_path, read_candidate_file


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _connect_query_only(path: Path, *, timeout: float = 5.0) -> sqlite3.Connection:
    """Open SQLite for audit reads without taking writer ownership.

    Active WAL manifests on external disks can occasionally reject `mode=ro`.
    In that case we fall back to a normal connection with SQLite's query-only
    guard, which preserves the audit's no-write contract.
    """
    attempts: tuple[tuple[str, bool], ...] = (
        (f"file:{path}?mode=ro", True),
        (str(path), False),
    )
    last_error: sqlite3.Error | None = None
    for target, is_uri in attempts:
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(target, uri=is_uri, timeout=timeout)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
            return conn
        except sqlite3.Error as exc:
            last_error = exc
            if conn is not None:
                conn.close()
    if last_error:
        raise last_error
    raise sqlite3.OperationalError(f"could not open SQLite database: {path}")


def _resolve_storage_path(store_root: Path, raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    path = Path(str(raw_path))
    return path if path.is_absolute() else store_root / path


def _probable_pdf(path: Path | None) -> bool:
    if not path:
        return False
    try:
        if not path.exists() or path.stat().st_size <= 0:
            return False
        with path.open("rb") as fh:
            return fh.read(4) == b"%PDF"
    except OSError:
        return False


def load_manifest_summary(store_root: Path | None, manifest_path: Path | None) -> dict[str, Any]:
    if not store_root or not manifest_path:
        return {
            "status": "not_configured",
            "manifest_path": str(manifest_path or ""),
            "store_root": str(store_root or ""),
            "status_counts": {},
        }
    if not manifest_path.exists():
        return {
            "status": "manifest_missing",
            "manifest_path": str(manifest_path),
            "store_root": str(store_root),
            "status_counts": {},
        }

    conn = _connect_query_only(manifest_path, timeout=5.0)
    try:
        if not _table_exists(conn, "raw_pdf_downloads"):
            return {
                "status": "downloads_table_missing",
                "manifest_path": str(manifest_path),
                "store_root": str(store_root),
                "status_counts": {},
            }
        status_rows = conn.execute(
            """
            SELECT status, COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS bytes
            FROM raw_pdf_downloads
            GROUP BY status
            ORDER BY status
            """
        ).fetchall()
        status_counts = {
            str(row["status"]): {"papers": int(row["n"]), "bytes": int(row["bytes"] or 0)}
            for row in status_rows
        }
        success_rows = conn.execute(
            """
            SELECT storage_path
            FROM raw_pdf_downloads
            WHERE status = 'success'
              AND COALESCE(storage_path, '') != ''
            """
        ).fetchall()
    finally:
        conn.close()

    existing = 0
    probable = 0
    for row in success_rows:
        path = _resolve_storage_path(store_root, row["storage_path"])
        if path and path.exists():
            existing += 1
        if _probable_pdf(path):
            probable += 1

    success = int(status_counts.get("success", {}).get("papers", 0))
    total = sum(int(v["papers"]) for v in status_counts.values())
    return {
        "status": "ok",
        "manifest_path": str(manifest_path),
        "store_root": str(store_root),
        "total_manifest_rows": total,
        "status_counts": status_counts,
        "success_papers": success,
        "success_bytes": int(status_counts.get("success", {}).get("bytes", 0)),
        "success_existing_paths": existing,
        "success_probable_pdfs": probable,
        "success_probable_pdf_rate": probable / success if success else 0.0,
    }


def load_section_reuse_summary(db_main: Path) -> dict[str, Any]:
    conn = _connect_query_only(db_main, timeout=5.0)
    try:
        out: dict[str, Any] = {
            "local_raw_pdf_section_rows": 0,
            "local_raw_pdf_section_papers": 0,
            "local_raw_pdf_success_attempts": 0,
        }
        if _table_exists(conn, "paper_sections") and "section_meta_json" in _columns(conn, "paper_sections"):
            row = conn.execute(
                """
                SELECT COUNT(*) AS rows, COUNT(DISTINCT paper_id) AS papers
                FROM paper_sections
                WHERE section_meta_json LIKE '%local_raw_pdf_cache%'
                """
            ).fetchone()
            out["local_raw_pdf_section_rows"] = int(row["rows"] or 0)
            out["local_raw_pdf_section_papers"] = int(row["papers"] or 0)
        if _table_exists(conn, "section_ingest_attempts"):
            row = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM section_ingest_attempts
                WHERE detail LIKE 'PDF bytes loaded from raw cache:%'
                   OR source_url LIKE 'file:%'
                """
            ).fetchone()
            out["local_raw_pdf_success_attempts"] = int(row["n"] or 0)
        return out
    finally:
        conn.close()


def load_queue_raw_pdf_coverage(
    db_main: Path,
    *,
    store_root: Path | None,
    manifest_path: Path | None,
    candidate_file: Path | None,
    limit: int | None = None,
) -> dict[str, Any]:
    ids = read_candidate_file(candidate_file, limit=limit) if candidate_file and candidate_file.exists() else None
    if not ids:
        return {
            "candidate_file": str(candidate_file or ""),
            "queue_papers": 0,
            "raw_pdf_available_papers": 0,
            "raw_pdf_available_rate": 0.0,
            "sample_missing_paper_ids": [],
        }
    conn = _connect_query_only(db_main, timeout=5.0)
    try:
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"""
            SELECT id, arxiv_id, doi, s2_paper_id, title
            FROM papers
            WHERE id IN ({placeholders})
            """,
            ids,
        ).fetchall()
    finally:
        conn.close()

    by_id = {str(row["id"]): dict(row) for row in rows}
    available = 0
    missing: list[str] = []
    for pid in ids:
        paper = by_id.get(pid) or {"id": pid}
        path = _local_raw_pdf_path(paper, store_root=store_root, manifest_path=manifest_path)
        if path:
            available += 1
        elif len(missing) < 10:
            missing.append(pid)
    total = len(ids)
    return {
        "candidate_file": str(candidate_file or ""),
        "queue_papers": total,
        "raw_pdf_available_papers": available,
        "raw_pdf_available_rate": available / total if total else 0.0,
        "sample_missing_paper_ids": missing,
    }


def run_raw_pdf_store_audit(
    *,
    db_main: Path = DB_MAIN,
    store_root: Path | None = RAW_PDF_STORE_ROOT,
    manifest_path: Path | None = RAW_PDF_MANIFEST,
    candidate_file: Path | None = None,
    out_dir: Path = REPORT_DIR,
    limit: int | None = None,
) -> dict[str, Any]:
    manifest = load_manifest_summary(store_root, manifest_path)
    reuse = load_section_reuse_summary(db_main)
    queue = load_queue_raw_pdf_coverage(
        db_main,
        store_root=store_root,
        manifest_path=manifest_path,
        candidate_file=candidate_file,
        limit=limit,
    )
    status = "pass"
    warnings: list[str] = []
    if manifest.get("status") != "ok":
        status = "warn"
        warnings.append("raw PDF store is not configured or manifest is unavailable")
    elif manifest.get("success_papers", 0) and not reuse.get("local_raw_pdf_section_papers", 0):
        status = "warn"
        warnings.append("raw PDF cache has successful downloads but section ingest has not consumed local-cache PDFs yet")
    if queue.get("queue_papers", 0) and queue.get("raw_pdf_available_papers", 0) == 0:
        status = "warn"
        warnings.append("candidate queue currently has no locally reusable raw PDFs")

    summary = {
        "generated_at": utc_now(),
        "status": status,
        "warnings": warnings,
        "manifest": manifest,
        "section_reuse": reuse,
        "candidate_queue_coverage": queue,
        "next_actions": _next_actions(manifest, reuse, queue),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "raw_pdf_store_audit.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (out_dir / "raw_pdf_store_audit.md").write_text(_markdown(summary), encoding="utf-8")
    return summary


def load_raw_pdf_store_audit_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"available": False, "reason": "unreadable"}
    if not isinstance(data, dict):
        return {"available": False, "reason": "not_object"}
    manifest = data.get("manifest") if isinstance(data.get("manifest"), dict) else {}
    reuse = data.get("section_reuse") if isinstance(data.get("section_reuse"), dict) else {}
    queue = (
        data.get("candidate_queue_coverage")
        if isinstance(data.get("candidate_queue_coverage"), dict)
        else {}
    )
    return {
        "available": True,
        "status": data.get("status"),
        "warnings": data.get("warnings") if isinstance(data.get("warnings"), list) else [],
        "success_papers": int(manifest.get("success_papers") or 0),
        "success_probable_pdfs": int(manifest.get("success_probable_pdfs") or 0),
        "success_probable_pdf_rate": float(manifest.get("success_probable_pdf_rate") or 0.0),
        "local_raw_pdf_section_papers": int(reuse.get("local_raw_pdf_section_papers") or 0),
        "local_raw_pdf_section_rows": int(reuse.get("local_raw_pdf_section_rows") or 0),
        "queue_papers": int(queue.get("queue_papers") or 0),
        "queue_raw_pdf_available_papers": int(queue.get("raw_pdf_available_papers") or 0),
        "queue_raw_pdf_available_rate": float(queue.get("raw_pdf_available_rate") or 0.0),
    }


def _next_actions(manifest: dict[str, Any], reuse: dict[str, Any], queue: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    if manifest.get("status") != "ok":
        actions.append("Configure V14B_RAW_PDF_STORE_ROOT and V14B_RAW_PDF_MANIFEST before the next section ingest run.")
    if manifest.get("success_papers", 0) and not reuse.get("local_raw_pdf_section_papers", 0):
        actions.append("Restart or launch the next section ingest with local raw PDF cache env vars after the active run reaches a safe stop.")
    if queue.get("raw_pdf_available_papers", 0):
        actions.append("Prioritize queue papers with local raw PDFs for low-latency parser tuning and atom/chain rebuilds.")
    return actions


def _markdown(summary: dict[str, Any]) -> str:
    manifest = summary["manifest"]
    reuse = summary["section_reuse"]
    queue = summary["candidate_queue_coverage"]
    lines = [
        "# Raw PDF Store Audit",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- status: **{summary['status']}**",
        f"- store_root: `{manifest.get('store_root', '')}`",
        f"- manifest: `{manifest.get('manifest_path', '')}`",
        "",
        "## Manifest",
        "",
        "| status | papers | GB |",
        "|---|---:|---:|",
    ]
    for status, row in sorted((manifest.get("status_counts") or {}).items()):
        gb = int(row.get("bytes", 0)) / (1024**3)
        lines.append(f"| {status} | {int(row.get('papers', 0))} | {gb:.2f} |")
    if manifest.get("status") == "ok":
        lines.extend(
            [
                "",
                f"- success probable PDFs: {manifest.get('success_probable_pdfs', 0)}/{manifest.get('success_papers', 0)} ({manifest.get('success_probable_pdf_rate', 0.0):.1%})",
                f"- success existing paths: {manifest.get('success_existing_paths', 0)}",
            ]
        )
    lines.extend(
        [
            "",
            "## Section Reuse",
            "",
            f"- section rows from local raw PDF cache: {reuse.get('local_raw_pdf_section_rows', 0)}",
            f"- papers from local raw PDF cache: {reuse.get('local_raw_pdf_section_papers', 0)}",
            f"- successful local-cache section attempts: {reuse.get('local_raw_pdf_success_attempts', 0)}",
            "",
            "## Candidate Queue Coverage",
            "",
            f"- candidate_file: `{queue.get('candidate_file', '')}`",
            f"- queue papers: {queue.get('queue_papers', 0)}",
            f"- raw PDF available papers: {queue.get('raw_pdf_available_papers', 0)} ({queue.get('raw_pdf_available_rate', 0.0):.1%})",
        ]
    )
    if queue.get("sample_missing_paper_ids"):
        lines.append(f"- sample missing paper_ids: {', '.join(queue['sample_missing_paper_ids'])}")
    if summary.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {item}" for item in summary["warnings"])
    if summary.get("next_actions"):
        lines.extend(["", "## Next Actions", ""])
        lines.extend(f"- {item}" for item in summary["next_actions"])
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Read-only audit for external raw PDF store reuse.")
    parser.add_argument("--db", default=str(DB_MAIN))
    parser.add_argument("--store-root", default=str(RAW_PDF_STORE_ROOT or ""))
    parser.add_argument("--manifest", default=str(RAW_PDF_MANIFEST or ""))
    parser.add_argument("--candidate-file", default="reports/v14b_pilot/multi_topic_evidence_gap_queue.csv")
    parser.add_argument("--out-dir", default=str(REPORT_DIR))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    summary = run_raw_pdf_store_audit(
        db_main=Path(args.db),
        store_root=Path(args.store_root).expanduser() if args.store_root else None,
        manifest_path=Path(args.manifest).expanduser() if args.manifest else None,
        candidate_file=Path(args.candidate_file) if args.candidate_file else None,
        out_dir=Path(args.out_dir),
        limit=args.limit,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
