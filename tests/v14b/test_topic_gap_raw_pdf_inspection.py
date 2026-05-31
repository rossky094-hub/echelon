from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

from echelon.v14b.topic_gap_raw_pdf_inspection import (
    classify_recommended_action,
    inspect_parsed_blocks,
    load_topic_gap_raw_pdf_inspection_state,
    run_topic_gap_raw_pdf_inspection,
)


def _block(text: str, page_no: int = 1):
    return SimpleNamespace(text=text, page_no=page_no, section_hint="body")


def test_inspect_parsed_blocks_detects_primary_sections():
    result = inspect_parsed_blocks(
        [
            _block(
                "1 Results and Discussion\n"
                "The experiment reports a bottleneck caused by thermal drift and fabrication error. "
                "The discussion continues with measurement evidence, unresolved constraints, and mitigation attempts. "
                "This deliberately long body exceeds the section extraction threshold for parser dry-run inspection."
            )
        ]
    )

    assert result["classification"] == "parser_success_primary"
    assert "discussion" in result["primary_sections"]
    assert result["section_chars"]["discussion"] >= result["min_section_chars"]


def test_inspect_parsed_blocks_reports_no_target_when_current_parser_extracts_nothing():
    result = inspect_parsed_blocks(
        [
            _block(
                "Abstract\n"
                "This short paper text does not expose one of the current target section headings. "
                "References"
            )
        ]
    )

    assert result["classification"] == "parser_no_target_sections"
    assert result["no_target_classification"] == "sectionless_or_non_target_heading_format"
    assert result["section_names"] == []


def test_inspect_parsed_blocks_marks_terminal_summary_as_weak_primary():
    result = inspect_parsed_blocks(
        [
            _block("Abstract\nThis opening cue is not enough. " * 12, page_no=1),
            _block(
                "In summary, the device improves brightness but still has packaging drift "
                "and fabrication sensitivity. "
                + "This terminal context is intentionally long enough for weak extraction. " * 8,
                page_no=2,
            ),
        ]
    )

    assert result["classification"] == "parser_success_weak_primary"
    assert result["primary_sections"] == ["conclusion"]
    assert result["provenance_strengths"]["conclusion"] == "weak"
    assert classify_recommended_action(result) == "weak_primary_context_only"


def test_run_topic_gap_raw_pdf_inspection_uses_local_cache_without_db_writes(tmp_path, monkeypatch):
    db = tmp_path / "main.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE papers (id TEXT PRIMARY KEY, title TEXT, arxiv_id TEXT, doi TEXT, s2_paper_id TEXT)"
    )
    conn.execute("INSERT INTO papers VALUES ('p1', 'Local PDF paper', '2401.00001', '', '')")
    conn.execute("INSERT INTO papers VALUES ('p2', 'Missing local paper', '', '', '')")
    conn.commit()
    conn.close()

    triage = tmp_path / "triage.json"
    triage.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "paper_id": "p1",
                        "title": "Local PDF paper",
                        "topics": ["metalens"],
                        "failure_mode": "unattempted_pdf_available",
                        "promotion_policy": "candidate_pool_only",
                    },
                    {
                        "paper_id": "p2",
                        "title": "Missing local paper",
                        "topics": ["metalens"],
                        "failure_mode": "no_pdf_url",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    local_pdf = tmp_path / "p1.pdf"
    local_pdf.write_bytes(b"%PDF-1.4\nfake")

    import echelon.v14b.topic_gap_raw_pdf_inspection as mod

    def fake_local_path(paper, *, store_root=None, manifest_path=None):
        return local_pdf if paper["id"] == "p1" else None

    def fake_parse(path):
        assert path == str(local_pdf)
        return [
            _block(
                "1 Discussion\n"
                "A current limitation is optical loss and fabrication drift in the local PDF. "
                "The paper describes failed attempts and a partial fix with enough body text for extraction."
            )
        ]

    monkeypatch.setattr(mod, "_local_raw_pdf_path", fake_local_path)
    monkeypatch.setattr(mod, "parse_pdf_pages_with_timeout", fake_parse)

    result = run_topic_gap_raw_pdf_inspection(
        db_main=db,
        triage_json=triage,
        store_root=tmp_path,
        manifest_path=tmp_path / "manifest.sqlite3",
        out_dir=tmp_path / "reports",
    )

    assert result["summary"]["triage_papers"] == 2
    assert result["summary"]["local_pdf_available_papers"] == 1
    assert result["summary"]["skipped_no_local_pdf"] == 1
    assert result["summary"]["parser_primary_ready_papers"] == 1
    assert result["summary"]["parser_primary_ready_repair_candidates"] == 1
    assert result["summary"]["parser_primary_ready_already_covered"] == 0
    assert result["summary"]["parser_no_target_shape_counts"] == {}
    assert result["summary"]["recommended_action_counts"] == {"local_cache_ingest_candidate": 1}
    assert result["rows"][0]["recommended_action"] == "local_cache_ingest_candidate"
    assert result["rows"][0]["paper_id"] == "p1"
    assert (tmp_path / "reports" / "topic_gap_raw_pdf_inspection.md").exists()

    loaded = load_topic_gap_raw_pdf_inspection_state(
        tmp_path / "reports" / "topic_gap_raw_pdf_inspection.json"
    )
    assert loaded["available"] is True
    assert loaded["parser_primary_ready_papers"] == 1
    assert loaded["parser_primary_ready_repair_candidates"] == 1


def test_run_topic_gap_raw_pdf_inspection_counts_no_target_shapes(tmp_path, monkeypatch):
    db = tmp_path / "main.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE papers (id TEXT PRIMARY KEY, title TEXT, arxiv_id TEXT, doi TEXT, s2_paper_id TEXT)"
    )
    conn.execute("INSERT INTO papers VALUES ('p1', 'No target local PDF', '2401.00001', '', '')")
    conn.commit()
    conn.close()

    triage = tmp_path / "triage.json"
    triage.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "paper_id": "p1",
                        "title": "No target local PDF",
                        "topics": ["metalens"],
                        "failure_mode": "no_target_sections_after_current_parser",
                        "promotion_policy": "candidate_pool_only",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    local_pdf = tmp_path / "p1.pdf"
    local_pdf.write_bytes(b"%PDF-1.4\nfake")

    import echelon.v14b.topic_gap_raw_pdf_inspection as mod

    monkeypatch.setattr(
        mod,
        "_local_raw_pdf_path",
        lambda paper, *, store_root=None, manifest_path=None: local_pdf,
    )
    monkeypatch.setattr(
        mod,
        "parse_pdf_pages_with_timeout",
        lambda path: [_block("Abstract\nShort format paper body.\nReferences")],
    )

    result = run_topic_gap_raw_pdf_inspection(
        db_main=db,
        triage_json=triage,
        store_root=tmp_path,
        manifest_path=tmp_path / "manifest.sqlite3",
        out_dir=tmp_path / "reports",
    )

    assert result["summary"]["parser_no_target_papers"] == 1
    assert result["summary"]["parser_no_target_shape_counts"] == {
        "sectionless_or_non_target_heading_format": 1
    }
    assert result["summary"]["parser_no_target_repair_signal_papers"] == 0
    assert result["summary"]["recommended_action_counts"] == {"weak_fulltext_or_metadata_only": 1}
    assert result["rows"][0]["recommended_action"] == "weak_fulltext_or_metadata_only"


def test_run_topic_gap_raw_pdf_inspection_routes_heading_like_to_taxonomy_review(tmp_path, monkeypatch):
    db = tmp_path / "main.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE papers (id TEXT PRIMARY KEY, title TEXT, arxiv_id TEXT, doi TEXT, s2_paper_id TEXT)"
    )
    conn.execute("INSERT INTO papers VALUES ('p1', 'Heading-like local PDF', '2401.00001', '', '')")
    conn.commit()
    conn.close()

    triage = tmp_path / "triage.json"
    triage.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "paper_id": "p1",
                        "title": "Heading-like local PDF",
                        "topics": ["photonic crystal cavity"],
                        "failure_mode": "no_target_sections_after_current_parser",
                        "promotion_policy": "candidate_pool_only",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    local_pdf = tmp_path / "p1.pdf"
    local_pdf.write_bytes(b"%PDF-1.4\nfake")

    import echelon.v14b.topic_gap_raw_pdf_inspection as mod

    monkeypatch.setattr(
        mod,
        "_local_raw_pdf_path",
        lambda paper, *, store_root=None, manifest_path=None: local_pdf,
    )
    monkeypatch.setattr(
        mod,
        "parse_pdf_pages_with_timeout",
        lambda path: [_block("Device Design\nThe body is short and does not form a target section.")],
    )

    result = run_topic_gap_raw_pdf_inspection(
        db_main=db,
        triage_json=triage,
        store_root=tmp_path,
        manifest_path=tmp_path / "manifest.sqlite3",
        out_dir=tmp_path / "reports",
    )

    assert result["summary"]["parser_no_target_shape_counts"] == {
        "heading_like_but_not_target_section": 1
    }
    assert result["summary"]["recommended_action_counts"] == {"heading_taxonomy_review": 1}
    assert result["rows"][0]["recommended_action"] == "heading_taxonomy_review"
    assert result["rows"][0]["no_target_probe"]["heading_like_examples"][0]["text"] == "Device Design"


def test_classify_recommended_action_keeps_already_covered_primary_as_control():
    action = classify_recommended_action(
        {
            "classification": "parser_success_primary",
            "promotion_policy": "covered",
            "failure_mode": "decision_grade_current_contract",
        }
    )

    assert action == "already_covered_parser_control"
