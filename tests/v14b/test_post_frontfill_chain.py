import json
import importlib.util
import sqlite3
from argparse import Namespace
from pathlib import Path

from echelon.v14b.evidence_contracts import SECTION_PARSER_CONTRACT_VERSION


def _load_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "run_after_frontfill_product_chain.py"
    spec = importlib.util.spec_from_file_location("run_after_frontfill_product_chain", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_post_frontfill_rebuilds_evidence_sensitive_steps_with_no_resume(tmp_path):
    mod = _load_module()

    cmd = mod.build_step_command(
        python_exe="python3",
        step="limitation",
        db_main=tmp_path / "main.sqlite3",
        db_v14=tmp_path / "v14.sqlite3",
        corpus_id="optics",
        force_rerun=True,
    )

    assert cmd[:3] == ["python3", "-m", "echelon.v14b.step5c_limitation"]
    assert "--no-resume" in cmd
    assert cmd[cmd.index("--corpus-id") + 1] == "optics"


def test_post_frontfill_default_chain_rebuilds_section_retrieval_substrate_before_step5c():
    mod = _load_module()

    assert list(mod.DEFAULT_STEPS[:5]) == [
        "section-atoms",
        "section-atom-embeddings",
        "section-embeddings",
        "section-atom-chains",
        "limitation",
    ]


def test_post_frontfill_section_atom_embedding_step_rebuilds_vectors(tmp_path):
    mod = _load_module()

    cmd = mod.build_step_command(
        python_exe="python3",
        step="section-atom-embeddings",
        db_main=tmp_path / "main.sqlite3",
        db_v14=tmp_path / "v14.sqlite3",
        force_rerun=True,
    )

    assert cmd[:3] == ["python3", "-m", "echelon.v14b.section_atoms"]
    assert "--skip-atom-build" in cmd
    assert "--build-embeddings" in cmd
    assert "--embedding-rebuild" in cmd
    assert "--no-resume" in cmd


def test_post_frontfill_section_embedding_step_rebuilds_vectors(tmp_path):
    mod = _load_module()

    cmd = mod.build_step_command(
        python_exe="python3",
        step="section-embeddings",
        db_main=tmp_path / "main.sqlite3",
        db_v14=tmp_path / "v14.sqlite3",
        force_rerun=True,
    )

    assert cmd[:3] == ["python3", "-m", "echelon.v14b.section_atoms"]
    assert "--skip-atom-build" in cmd
    assert "--build-section-embeddings" in cmd
    assert "--section-embedding-rebuild" in cmd
    assert "--no-resume" in cmd


def test_post_frontfill_rebuilds_visual_outputs_without_checkpoint_flag(tmp_path):
    mod = _load_module()

    cmd = mod.build_step_command(
        python_exe="python3",
        step="visual-graph",
        db_main=tmp_path / "main.sqlite3",
        db_v14=tmp_path / "v14.sqlite3",
        force_rerun=True,
    )

    assert cmd[:3] == ["python3", "-m", "echelon.v14b.step10_visual_graph_builder"]
    assert "--no-resume" not in cmd


def test_post_frontfill_unknown_step_falls_back_to_make(tmp_path):
    mod = _load_module()

    cmd = mod.build_step_command(
        python_exe="python3",
        step="custom-step",
        db_main=tmp_path / "main.sqlite3",
        db_v14=tmp_path / "v14.sqlite3",
        force_rerun=True,
    )

    assert cmd == ["make", "custom-step"]


def test_topic_gap_queue_metrics_counts_primary_section_coverage(tmp_path):
    mod = _load_module()
    db = tmp_path / "main.sqlite3"
    queue = tmp_path / "topic_gap_queue.csv"
    queue.write_text("paper_id\np1\np2\np3\n", encoding="utf-8")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE paper_sections (
            paper_id TEXT,
            section_name TEXT,
            section_text TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO paper_sections VALUES (?, ?, ?)",
        ("p1", "discussion", "x" * 100),
    )
    conn.execute(
        "INSERT INTO paper_sections VALUES (?, ?, ?)",
        ("p2", "abstract", "x" * 100),
    )
    conn.commit()
    conn.close()

    metrics = mod.collect_topic_gap_queue_metrics(db, queue)

    assert metrics["paper_ids"] == 3
    assert metrics["primary_section_papers"] == 1
    assert metrics["missing_primary_section_papers"] == 2
    assert metrics["primary_section_rate"] == 1 / 3
    assert metrics["decision_grade_section_papers"] == 0
    assert metrics["decision_grade_section_rate"] == 0.0


def test_topic_gap_queue_metrics_reads_regression_candidate_paper_ids(tmp_path):
    mod = _load_module()
    db = tmp_path / "main.sqlite3"
    queue = tmp_path / "multi_topic_evidence_gap_queue.csv"
    queue.write_text(
        "topic,gap_type,candidate_paper_ids\n"
        "metalens,key_turning,p1;p2\n"
        "holography,bottleneck,p2;p3\n",
        encoding="utf-8",
    )
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE paper_sections (
            paper_id TEXT,
            section_name TEXT,
            section_text TEXT
        )
        """
    )
    conn.execute("INSERT INTO paper_sections VALUES ('p1', 'discussion', ?)", ("x" * 100,))
    conn.execute("INSERT INTO paper_sections VALUES ('p3', 'results', ?)", ("x" * 100,))
    conn.commit()
    conn.close()

    metrics = mod.collect_topic_gap_queue_metrics(db, queue)

    assert metrics["paper_ids"] == 3
    assert metrics["primary_section_papers"] == 2
    assert metrics["primary_section_rate"] == 2 / 3
    assert metrics["decision_grade_section_papers"] == 0


def test_topic_gap_queue_metrics_counts_decision_grade_current_contract_sections(tmp_path):
    mod = _load_module()
    db = tmp_path / "main.sqlite3"
    queue = tmp_path / "topic_gap_queue.csv"
    queue.write_text("paper_id\np1\np2\np3\n", encoding="utf-8")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE paper_sections (
            paper_id TEXT,
            section_name TEXT,
            section_text TEXT,
            parser_name TEXT,
            section_meta_json TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO paper_sections VALUES (?, ?, ?, ?, ?)",
        (
            "p1",
            "discussion",
            "current contract evidence " * 20,
            "v14b_section_ingest_v3",
            json.dumps(
                {
                    "extraction_strategies": ["explicit_heading"],
                    "parser_contract_version": SECTION_PARSER_CONTRACT_VERSION,
                }
            ),
        ),
    )
    conn.execute(
        "INSERT INTO paper_sections VALUES (?, ?, ?, ?, ?)",
        (
            "p2",
            "results",
            "legacy weak evidence " * 20,
            "v14b_section_ingest_v2",
            json.dumps({"extraction_strategies": ["loose_inline_heading"]}),
        ),
    )
    conn.commit()
    conn.close()

    metrics = mod.collect_topic_gap_queue_metrics(db, queue)

    assert metrics["primary_section_papers"] == 2
    assert metrics["decision_grade_section_papers"] == 1
    assert metrics["missing_decision_grade_section_papers"] == 2
    assert metrics["decision_grade_section_rate"] == 1 / 3


def test_topic_gap_queue_gate_blocks_downstream_when_benchmark_topic_evidence_is_thin():
    mod = _load_module()
    args = Namespace(skip_topic_gap_gate=False, min_topic_gap_decision_grade_rate=0.70)

    ready, failures = mod.topic_gap_queue_ready(
        {
            "exists": True,
            "paper_ids": 10,
            "primary_section_papers": 4,
            "primary_section_rate": 0.4,
            "decision_grade_section_papers": 2,
            "decision_grade_section_rate": 0.2,
        },
        args,
    )

    assert ready is False
    assert "topic_gap_decision_grade_section_rate" in failures[0]
    assert "raw_primary=4" in failures[0]


def test_frontfill_gate_requires_decision_grade_primary_sections():
    mod = _load_module()
    args = Namespace(
        min_primary_section_papers=10,
        min_decision_grade_primary_section_papers=10,
        min_openalex_w_rate=0.70,
        min_primary_field_rate=0.95,
    )

    ready, failures = mod.frontfill_ready(
        {
            "primary_section_papers": 10,
            "decision_grade_primary_section_papers": 2,
            "openalex_w_rate": 0.80,
            "primary_field_rate": 0.99,
        },
        args,
    )

    assert ready is False
    assert any("decision_grade_primary_section_papers" in failure for failure in failures)


def test_topic_gap_frontfill_is_not_blocked_by_broad_frontfill_gate():
    mod = _load_module()
    args = Namespace(
        run_topic_gap_frontfill=True,
        force=False,
        skip_topic_gap_gate=False,
    )

    assert mod.should_run_topic_gap_frontfill(args, topic_gap_ready=False)


def test_topic_gap_frontfill_respects_force_and_skip_flags():
    mod = _load_module()

    assert not mod.should_run_topic_gap_frontfill(
        Namespace(run_topic_gap_frontfill=True, force=True, skip_topic_gap_gate=False),
        topic_gap_ready=False,
    )
    assert not mod.should_run_topic_gap_frontfill(
        Namespace(run_topic_gap_frontfill=True, force=False, skip_topic_gap_gate=True),
        topic_gap_ready=False,
    )
    assert not mod.should_run_topic_gap_frontfill(
        Namespace(run_topic_gap_frontfill=True, force=False, skip_topic_gap_gate=False),
        topic_gap_ready=True,
    )


def test_post_frontfill_detects_active_section_ingest_without_screen_wrappers():
    mod = _load_module()

    assert mod._is_active_section_ingest_line(
        "123 python3 -m echelon.v14b.step5s_section_ingest --top-n 12000",
        "step5s_section_ingest",
    )
    assert not mod._is_active_section_ingest_line(
        "123 SCREEN -dmS run python3 -m echelon.v14b.step5s_section_ingest",
        "step5s_section_ingest",
    )
    assert not mod._is_active_section_ingest_line(
        "123 python3 scripts/watch_step5s_section_ingest.py",
        "step5s_section_ingest",
    )


def test_post_frontfill_active_section_ingest_blocks_downstream_writers(tmp_path, monkeypatch):
    mod = _load_module()
    monkeypatch.setattr(mod, "active_section_ingest", lambda _pattern: True)
    monkeypatch.setattr(
        mod,
        "run_step",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("run_step should not be called")),
    )

    rc = mod.main(
        [
            "--repo-root",
            str(tmp_path),
            "--db-main",
            "main.sqlite3",
            "--db-v14",
            "v14.sqlite3",
            "--log-file",
            "after_frontfill.log",
            "--force",
        ]
    )

    assert rc == 0
    assert "active_section_ingest still running" in (tmp_path / "after_frontfill.log").read_text(
        encoding="utf-8"
    )
