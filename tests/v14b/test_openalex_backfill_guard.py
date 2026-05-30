import importlib.util
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "guard_openalex_backfill.py"
    spec = importlib.util.spec_from_file_location("guard_openalex_backfill", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_guard_detects_active_openalex_backfill_and_ignores_itself():
    mod = _load_module()
    commands = [
        "python3 -m echelon.v14b.step0_openalex_backfill --db db/echelon_library.sqlite3",
        "python3 scripts/guard_openalex_backfill.py --repo-root .",
        "rg step0_openalex_backfill",
    ]

    active = mod.active_openalex_backfill_commands(commands)

    assert active == ["python3 -m echelon.v14b.step0_openalex_backfill --db db/echelon_library.sqlite3"]


def test_guard_blocks_active_cooldown(monkeypatch, capsys):
    mod = _load_module()
    monkeypatch.setattr(mod, "process_commands", lambda: [])
    monkeypatch.setattr(
        mod,
        "select_openalex_frontfill_state",
        lambda _root: {
            "status": "cooling_down_or_stopped",
            "cooldown_remaining_s": 7200,
            "log_path": "logs/v14b/openalex_backfill_current.log",
            "processed": 3000,
            "total": 22643,
            "cooldown_until": "2026-05-31T08:00:00",
        },
    )
    monkeypatch.delenv(mod.OVERRIDE_ENV, raising=False)

    assert mod.main([]) == 3

    captured = capsys.readouterr()
    assert "active 429 cooldown detected" in captured.err


def test_guard_allows_cooldown_override(monkeypatch):
    mod = _load_module()
    monkeypatch.setattr(mod, "process_commands", lambda: [])
    monkeypatch.setattr(
        mod,
        "select_openalex_frontfill_state",
        lambda _root: {"status": "cooling_down_or_stopped", "cooldown_remaining_s": 7200},
    )

    assert mod.main(["--allow-cooldown"]) == 0


def test_guard_blocks_duplicate_backfill(monkeypatch, capsys):
    mod = _load_module()
    monkeypatch.setattr(
        mod,
        "process_commands",
        lambda: ["python3 -m echelon.v14b.step0_openalex_backfill --delay 1.2"],
    )
    monkeypatch.setattr(mod, "select_openalex_frontfill_state", lambda _root: {"status": "completed"})
    monkeypatch.delenv(mod.DUPLICATE_OVERRIDE_ENV, raising=False)

    assert mod.main([]) == 4

    captured = capsys.readouterr()
    assert "active OpenAlex backfill already detected" in captured.err
