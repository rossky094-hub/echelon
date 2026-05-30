from __future__ import annotations

import sqlite3
from pathlib import Path

from echelon.v14b.product_baseline import (
    PRODUCT_BASELINE_TOPICS,
    build_snapshot,
    collect_main_metrics,
    collect_v14_metrics,
    evaluate_topic_lens,
    render_snapshot_md,
    render_tasklist_md,
)


def _make_main_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE papers (
            id TEXT PRIMARY KEY,
            openalex_id TEXT,
            doi TEXT,
            arxiv_id TEXT,
            title TEXT,
            abstract TEXT,
            publication_date TEXT,
            cited_by_count INTEGER,
            primary_field_id TEXT,
            openalex_enriched INTEGER
        );
        CREATE TABLE paper_references (
            citing_paper_id TEXT,
            cited_paper_id_external TEXT,
            cited_paper_id_internal TEXT
        );
        CREATE TABLE paper_sections (
            paper_id TEXT,
            section_name TEXT,
            section_text TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("p1", "W1", "10.1/a", "2101.1", "Paper 1", "abs", "2021-01-01", 10, "F1", 1),
            ("p2", "S2-legacy", None, None, "Paper 2", "abs", "2022-01-01", 3, "F1", 0),
        ],
    )
    conn.executemany(
        "INSERT INTO paper_references VALUES (?, ?, ?)",
        [("p2", "W1", "p1"), ("p1", "W0", None)],
    )
    conn.execute(
        "INSERT INTO paper_sections VALUES ('p1', 'discussion', ?)",
        ("primary evidence " * 10,),
    )
    conn.commit()
    conn.close()


def _make_v14_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE main_path_edges (
            source_paper_id TEXT,
            target_paper_id TEXT,
            is_main_path INTEGER
        );
        CREATE TABLE future_directions (
            direction_id INTEGER PRIMARY KEY,
            claim_scope TEXT
        );
        CREATE TABLE direction_claim_cards (
            claim_card_id TEXT PRIMARY KEY,
            five_question_complete INTEGER,
            high_confidence_eligible INTEGER
        );
        CREATE TABLE visual_nodes (paper_id TEXT);
        CREATE TABLE section_priority_summary (
            audit_ts TEXT,
            category TEXT,
            total INTEGER,
            in_top_n INTEGER,
            any_section INTEGER,
            primary_section INTEGER,
            eligible_pdf INTEGER
        );
        """
    )
    conn.execute("INSERT INTO main_path_edges VALUES ('p1', 'p2', 1)")
    conn.execute("INSERT INTO future_directions VALUES (1, 'exploratory')")
    conn.execute("INSERT INTO direction_claim_cards VALUES ('cc1', 1, 0)")
    conn.execute("INSERT INTO visual_nodes VALUES ('p1')")
    conn.execute(
        "INSERT INTO section_priority_summary VALUES ('2026-01-01T00:00:00Z', 'main_path_node', 2, 2, 1, 1, 2)"
    )
    conn.commit()
    conn.close()


def test_collect_product_baseline_metrics(tmp_path):
    db_main = tmp_path / "main.sqlite3"
    db_v14 = tmp_path / "v14.sqlite3"
    _make_main_db(db_main)
    _make_v14_db(db_v14)

    main = collect_main_metrics(db_main)
    v14 = collect_v14_metrics(db_v14)

    assert main["papers"] == 2
    assert main["openalex_w"] == 1
    assert main["invalid_openalex_id"] == 1
    assert main["linked_refs"] == 1
    assert main["primary_section_papers"] == 1
    assert v14["main_path_is_main"] == 1
    assert v14["claim_cards_complete"] == 1
    assert v14["section_priority_summary"][0]["category"] == "main_path_node"


def test_evaluate_topic_lens_flags_value_gaps():
    lens = {
        "ready": True,
        "topic_dossier": {
            "branch_splits": [
                {
                    "name": "Imaging systems",
                    "driver_papers": [{"paper_id": "p1", "title": "Metalens microscope"}],
                }
            ],
            "bottleneck_dossiers": [
                {"name": "chromatic aberration", "evidence_papers": [{"paper_id": "p1"}]}
            ],
        },
        "history_main_path": {"key_turning_papers": [{"paper_id": "p1", "access_links": []}]},
        "future_growth": {"candidate_edges": [{"source_paper_id": "p1", "target_paper_id": "p2"}]},
        "rd_radar": {"claim_cards": []},
    }

    result = evaluate_topic_lens("metalens", lens)

    assert result["expected_branch_coverage"] < 1
    assert "Imaging systems" in result["expected_branch_hits"]
    assert any("missing expected branches" in gap for gap in result["quality_gaps"])
    assert any("future candidates exist" in gap for gap in result["quality_gaps"])


def test_snapshot_can_skip_live_topic_lens(tmp_path):
    db_main = tmp_path / "main.sqlite3"
    db_v14 = tmp_path / "v14.sqlite3"
    _make_main_db(db_main)
    _make_v14_db(db_v14)

    snapshot = build_snapshot(
        db_main=db_main,
        db_v14=db_v14,
        topic="metalens",
        top_k=10,
        include_topic_lens=False,
    )
    md = render_tasklist_md(snapshot["task_backlog"])

    assert snapshot["main"]["papers"] == 2
    assert "P0-01" in md
    assert "GNN-only future edges" in md


def test_product_baseline_defaults_to_multi_topic_suite(tmp_path, monkeypatch):
    db_main = tmp_path / "main.sqlite3"
    db_v14 = tmp_path / "v14.sqlite3"
    _make_main_db(db_main)
    _make_v14_db(db_v14)

    def fake_load_topic_lens(topic: str, top_k: int) -> dict:
        return {
            "ready": True,
            "topic_dossier": {
                "branch_splits": [
                    {"name": "placeholder branch", "driver_papers": [{"paper_id": f"{topic}-driver"}]}
                ],
                "bottleneck_dossiers": [
                    {"name": "constraint", "evidence_papers": [{"paper_id": f"{topic}-limit"}]}
                ],
            },
            "history_main_path": {
                "key_turning_papers": [
                    {
                        "paper_id": f"{topic}-turning",
                        "access_links": [{"url": "https://example.test"}],
                        "content_availability": {"has_primary_evidence_sections": True},
                    }
                ]
            },
            "future_growth": {"candidate_edges": []},
            "rd_radar": {"claim_cards": []},
        }

    monkeypatch.setattr(
        "echelon.v14b.product_baseline.load_topic_lens",
        fake_load_topic_lens,
    )

    snapshot = build_snapshot(
        db_main=db_main,
        db_v14=db_v14,
        topic="all",
        top_k=10,
        include_topic_lens=True,
    )
    md = render_snapshot_md(snapshot)

    assert {row["topic"] for row in snapshot["topic_lens_quality_suite"]} == set(PRODUCT_BASELINE_TOPICS)
    assert snapshot["topic_lens_quality"]["topic"] == "all"
    assert "Multi-topic Topic Baseline" in md
    assert "Metalens Baseline" not in md
