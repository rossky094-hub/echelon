import importlib.util
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "guard_topic_gap_repair.py"
    spec = importlib.util.spec_from_file_location("guard_topic_gap_repair", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_guard_detects_active_section_ingest_and_ignores_wrappers():
    mod = _load_module()

    commands = [
        "python3 -m echelon.v14b.step5s_section_ingest --top-n 12000",
        "python3 scripts/watch_step5s_section_ingest.py --pid-pattern step5s_section_ingest",
        "python3 scripts/guard_topic_gap_repair.py",
        "SCREEN -dmS run python3 -m echelon.v14b.step5s_section_ingest",
    ]

    active = mod.active_section_ingest_commands(commands)

    assert active == ["python3 -m echelon.v14b.step5s_section_ingest --top-n 12000"]


def test_guard_main_blocks_without_override(monkeypatch, capsys):
    mod = _load_module()
    monkeypatch.setattr(
        mod,
        "process_commands",
        lambda: ["python3 -m echelon.v14b.step5s_section_ingest --candidate-file data/v14b/section_delta_queue.csv"],
    )
    monkeypatch.delenv(mod.OVERRIDE_ENV, raising=False)

    assert mod.main([]) == 3

    captured = capsys.readouterr()
    assert "active broad section ingest detected" in captured.err


def test_guard_main_allows_explicit_override(monkeypatch):
    mod = _load_module()
    monkeypatch.setattr(
        mod,
        "process_commands",
        lambda: ["python3 -m echelon.v14b.step5s_section_ingest --candidate-file data/v14b/section_delta_queue.csv"],
    )

    assert mod.main(["--allow-concurrent"]) == 0


def test_guard_main_allows_when_no_active_ingest(monkeypatch, capsys):
    mod = _load_module()
    monkeypatch.setattr(mod, "process_commands", lambda: ["python3 scripts/watch_step5s_section_ingest.py"])

    assert mod.main([]) == 0

    captured = capsys.readouterr()
    assert "no active broad section ingest detected" in captured.out
