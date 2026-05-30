from __future__ import annotations

import sqlite3
from pathlib import Path

from echelon.v14b.reference_relink_audit import run_audit


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE papers (
            id TEXT PRIMARY KEY,
            title TEXT,
            openalex_id TEXT,
            doi TEXT,
            arxiv_id TEXT,
            s2_paper_id TEXT
        );
        CREATE TABLE paper_references (
            citing_paper_id TEXT,
            cited_paper_id_external TEXT,
            cited_paper_id_internal TEXT,
            cited_paper_id_provider TEXT,
            cited_paper_id_norm TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("p_doi", "DOI paper", None, "10.1000/abc", None, None),
            ("p_openalex", "OpenAlex paper", "https://openalex.org/W123", None, None, None),
            ("p_arxiv", "arXiv paper", None, None, "2301.00001", None),
            ("p_s2", "S2 paper", None, None, None, "S2HASH"),
            ("p_dup1", "Dup one", None, "10.2000/dup", None, None),
            ("p_dup2", "Dup two", None, "10.2000/dup", None, None),
        ],
    )
    conn.executemany(
        "INSERT INTO paper_references VALUES (?, ?, ?, ?, ?)",
        [
            ("c1", "https://doi.org/10.1000/ABC", "", None, None),
            ("c2", "https://openalex.org/W123", None, "openalex", "https://openalex.org/W123"),
            ("c3", "10.48550/arXiv.2301.00001v2", None, "doi", "10.48550/arXiv.2301.00001v2"),
            ("c4", "S2:S2HASH", None, None, None),
            ("c5", "10.2000/dup", None, "doi", "10.2000/dup"),
            ("c6", "plain title only", None, None, None),
            ("c7", "https://doi.org/10.9999/missing", None, None, None),
        ],
    )
    conn.commit()
    conn.close()


def _linked_count(path: Path) -> int:
    conn = sqlite3.connect(str(path))
    n = conn.execute(
        "SELECT COUNT(*) FROM paper_references WHERE COALESCE(cited_paper_id_internal, '') <> ''"
    ).fetchone()[0]
    conn.close()
    return int(n)


def test_reference_relink_dry_run_does_not_mutate(tmp_path):
    db = tmp_path / "library.sqlite3"
    _make_db(db)

    result = run_audit(db_path=db, out_dir=tmp_path / "reports", apply=False)

    counts = result["candidate_summary"]["status_counts"]
    assert counts["exact_linkable"] == 4
    assert counts["ambiguous_local_match"] == 1
    assert counts["no_local_match"] == 1
    assert counts["unclassifiable"] == 1
    assert result["candidate_summary"]["stale_norm_updates"]["doi"] == 2
    assert _linked_count(db) == 0
    assert (tmp_path / "reports" / "reference_relink_audit.md").exists()


def test_reference_relink_apply_links_only_exact_unambiguous_refs(tmp_path):
    db = tmp_path / "library.sqlite3"
    _make_db(db)

    result = run_audit(db_path=db, out_dir=tmp_path / "reports", apply=True, chunk_size=2)

    assert result["apply_result"]["link_updates_applied"] == 4
    assert result["apply_result"]["norm_updates_applied"] == 6
    assert _linked_count(db) == 4
    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        """
        SELECT citing_paper_id, cited_paper_id_internal, cited_paper_id_provider, cited_paper_id_norm
        FROM paper_references
        ORDER BY citing_paper_id
        """
    ).fetchall()
    conn.close()
    by_citing = {r[0]: r for r in rows}
    assert by_citing["c1"][1] == "p_doi"
    assert by_citing["c2"][1] == "p_openalex"
    assert by_citing["c2"][3] == "W123"
    assert by_citing["c3"][1] == "p_arxiv"
    assert by_citing["c3"][2] == "arxiv"
    assert by_citing["c4"][1] == "p_s2"
    assert by_citing["c5"][1] is None
    assert by_citing["c6"][1] is None
    assert by_citing["c7"][1] is None
    assert by_citing["c7"][2] == "doi"
    assert by_citing["c7"][3] == "10.9999/missing"
