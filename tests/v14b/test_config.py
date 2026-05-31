import importlib
from pathlib import Path


def test_raw_pdf_store_defaults_to_external_cache_when_env_absent(monkeypatch):
    monkeypatch.delenv("V14B_RAW_PDF_STORE_ROOT", raising=False)
    monkeypatch.delenv("V14B_RAW_PDF_MANIFEST", raising=False)
    monkeypatch.delenv("V14B_DEFAULT_RAW_PDF_STORE_ROOT", raising=False)

    import echelon.v14b.config as config

    reloaded = importlib.reload(config)

    expected_root = Path("/Volumes/LaCie/Echelon_Paper_Raw_Data")
    assert reloaded.DEFAULT_RAW_PDF_STORE_ROOT == expected_root
    assert reloaded.RAW_PDF_STORE_ROOT == expected_root
    assert reloaded.RAW_PDF_MANIFEST == expected_root / "manifests" / "raw_pdf_downloads.sqlite3"
