import importlib.util
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
