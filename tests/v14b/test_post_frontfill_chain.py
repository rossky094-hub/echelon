import importlib.util
import sqlite3
from argparse import Namespace
from pathlib import Path


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


def test_topic_gap_queue_gate_blocks_downstream_when_benchmark_topic_evidence_is_thin():
    mod = _load_module()
    args = Namespace(skip_topic_gap_gate=False, min_topic_gap_primary_rate=0.70)

    ready, failures = mod.topic_gap_queue_ready(
        {
            "exists": True,
            "paper_ids": 10,
            "primary_section_papers": 4,
            "primary_section_rate": 0.4,
        },
        args,
    )

    assert ready is False
    assert "topic_gap_primary_section_rate" in failures[0]


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
