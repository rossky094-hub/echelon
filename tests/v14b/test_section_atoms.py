from __future__ import annotations

import json
import re
import sqlite3

from echelon.v14b.evidence_contracts import SECTION_PARSER_CONTRACT_VERSION
from echelon.v14b.section_atoms import (
    build_section_atom_embeddings,
    build_section_atoms,
    build_section_embeddings,
    classify_atom_type,
    extract_section_atoms_from_row,
    search_section_atoms,
    search_section_atoms_fuzzy,
    search_section_atoms_hybrid,
    search_sections_fuzzy,
)


def _meta(
    *,
    strategies: list[str] | None = None,
    contract: str = SECTION_PARSER_CONTRACT_VERSION,
    repair_contracts: list[dict] | None = None,
) -> str:
    payload = {
        "parser_contract_version": contract,
        "extraction_strategies": strategies or ["explicit_heading"],
        "source_delivery": "local_raw_pdf_cache",
        "source_storage_uri": "/Volumes/LaCie/Echelon_Paper_Raw_Data/pdfs/p1.pdf",
    }
    if repair_contracts is not None:
        payload["repair_contract_source"] = "candidate_file"
        payload["repair_contracts"] = repair_contracts
    return json.dumps(payload)


def test_classify_atom_type_keeps_section_atoms_deterministic():
    assert classify_atom_type("A central bottleneck is fabrication error and optical loss.")[0] == "constraint"
    assert classify_atom_type("The measured efficiency reached 35% at 1550 nm.")[0] == "metric_result"
    assert classify_atom_type("We used a simulation benchmark and experimental setup.")[0] == "attempted_path"
    assert classify_atom_type("This improves manufacturability and mitigates integration risk.")[0] == "local_fix"
    assert classify_atom_type("The calibration mitigates mismatch and reduces coupling loss.")[0] == "local_fix"
    assert classify_atom_type("However, packaging drift remains a constraint for deployment.")[0] == "new_constraint"


def test_extract_section_atoms_keeps_stageful_short_sentences_atomic():
    row = {
        "paper_id": "p_stageful",
        "section_name": "Discussion",
        "section_text": (
            "A central constraint is wafer-scale phase drift during packaging. "
            "The calibration mitigates mismatch and reduces coupling loss. "
            "However, packaging drift remains a constraint for deployment."
        ),
        "source_url": "https://example.test/p_stageful.pdf",
        "section_pages_json": json.dumps([9]),
        "section_meta_json": _meta(),
        "title": "Stageful atomization",
    }

    atoms = extract_section_atoms_from_row(row)
    atom_types = [atom["atom_type"] for atom in atoms]

    assert atom_types[:3] == ["constraint", "local_fix", "new_constraint"]
    assert "mitigates mismatch" in atoms[1]["atom_text"]
    assert atoms[1]["span_start"] < atoms[2]["span_start"]


def test_extract_section_atoms_marks_current_traced_decision_sections_decision_grade():
    row = {
        "paper_id": "p1",
        "section_name": "Discussion",
        "section_text": (
            "A central limitation is fabrication error, thermal drift, and optical loss in dense photonic arrays. "
            "The paper reports this as a bottleneck rather than a solved product claim."
        ),
        "source_url": "https://example.test/p1.pdf",
        "section_pages_json": json.dumps([4, 5]),
        "section_meta_json": _meta(
            repair_contracts=[
                {
                    "repair_id": "repair-p1",
                    "source_contract": "topic_dossier_evidence_repair_plan",
                    "claim_scope": "evidence_repair_queue_only",
                }
            ]
        ),
        "title": "Photonic array constraints",
    }

    atoms = extract_section_atoms_from_row(row)

    assert atoms
    assert atoms[0]["evidence_grade"] == "section_atom_decision_grade"
    assert atoms[0]["claim_scope"] == "retrieval_context_only"
    assert atoms[0]["source_delivery"] == "local_raw_pdf_cache"
    assert atoms[0]["source_storage_uri"].endswith("/p1.pdf")
    assert atoms[0]["page_start"] == 4
    assert atoms[0]["span_unit"] == "normalized_section_text_char_offsets"
    normalized_text = re.sub(r"\s+", " ", row["section_text"]).strip()
    assert normalized_text[atoms[0]["span_start"]:atoms[0]["span_end"]] == atoms[0]["atom_text"]
    assert "deterministic heuristic classification" in atoms[0]["uncertainty_reasons_json"]
    repair_contracts = json.loads(atoms[0]["repair_contracts_json"])
    assert repair_contracts[0]["repair_id"] == "repair-p1"
    assert repair_contracts[0]["contract_source"] == "candidate_file"


def test_extract_section_atoms_marks_legacy_or_weak_sections_weak():
    row = {
        "paper_id": "p2",
        "section_name": "Background",
        "section_text": (
            "The paper briefly mentions loss and scaling issues in passing, but this is not a decision section "
            "and the source provenance is legacy."
        ),
        "source_url": "",
        "section_pages_json": "[]",
        "section_meta_json": json.dumps({"parser_contract_version": "legacy_unknown_contract"}),
        "title": "Weak source",
    }

    atoms = extract_section_atoms_from_row(row)

    assert atoms[0]["evidence_grade"] == "section_atom_weak"
    reasons = json.loads(atoms[0]["uncertainty_reasons_json"])
    assert "section is not a primary decision section" in reasons
    assert "section parser contract is legacy or unknown" in reasons
    assert "section extraction provenance is weak" in reasons


def test_build_and_search_section_atoms_exact_fts(tmp_path):
    db = tmp_path / "main.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE papers (id TEXT PRIMARY KEY, title TEXT);
        CREATE TABLE paper_sections (
            paper_id TEXT,
            section_name TEXT,
            section_text TEXT,
            source_url TEXT,
            section_pages_json TEXT,
            section_meta_json TEXT
        );
        """
    )
    conn.execute("INSERT INTO papers VALUES ('p1', 'Photonic fabrication loss study')")
    conn.execute("INSERT INTO papers VALUES ('p2', 'Efficiency benchmark study')")
    conn.execute(
        "INSERT INTO paper_sections VALUES (?, ?, ?, ?, ?, ?)",
        (
            "p1",
            "Discussion",
            (
                "A central limitation is fabrication error, optical loss, and thermal drift in dense photonic arrays. "
                "The authors describe this as an unresolved constraint for scalable deployment."
            ),
            "https://example.test/p1.pdf",
            json.dumps([6]),
            _meta(
                repair_contracts=[
                    {
                        "repair_id": "repair-p1",
                        "target_pipeline_steps": ["section-atom-chains"],
                        "claim_scope": "evidence_repair_queue_only",
                    }
                ]
            ),
        ),
    )
    conn.execute(
        "INSERT INTO paper_sections VALUES (?, ?, ?, ?, ?, ?)",
        (
            "p2",
            "Results",
            (
                "Measured efficiency reached 35% at 1550 nm in a simulation benchmark and prototype validation setup. "
                "The result is reported as a metric rather than a proof of product readiness."
            ),
            "https://example.test/p2.pdf",
            json.dumps([8]),
            _meta(),
        ),
    )
    conn.commit()
    conn.close()

    stats = build_section_atoms(db)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    hits = search_section_atoms(conn, "fabrication loss", top_k=5)
    metric_hits = search_section_atoms(conn, "1550", top_k=5, filters={"atom_type": "metric_result"})
    discussion_hits = search_section_atoms(conn, "constraint", top_k=5, filters={"section_name": "Discussion"})
    conn.close()

    assert stats["sections_processed"] == 2
    assert stats["atoms_written"] >= 2
    assert stats["fts_enabled"] is True
    assert hits[0]["paper_id"] == "p1"
    assert hits[0]["claim_scope"] == "retrieval_context_only"
    assert hits[0]["search_semantics"].startswith("retrieval hit only")
    assert hits[0]["repair_contracts"][0]["repair_id"] == "repair-p1"
    assert metric_hits and metric_hits[0]["paper_id"] == "p2"
    assert discussion_hits and discussion_hits[0]["section_key"] == "discussion"


def test_exact_section_atom_search_supports_identifiers_titles_and_phrase_spans(tmp_path):
    db = tmp_path / "main.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE papers (
            id TEXT PRIMARY KEY,
            openalex_id TEXT,
            doi TEXT,
            arxiv_id TEXT,
            s2_paper_id TEXT,
            title TEXT
        );
        CREATE TABLE paper_sections (
            paper_id TEXT,
            section_name TEXT,
            section_text TEXT,
            source_url TEXT,
            section_pages_json TEXT,
            section_meta_json TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?)",
        (
            "p1",
            "https://openalex.org/W123",
            "https://doi.org/10.1234/EXAMPLE.PAPER",
            "2401.12345v2",
            "S2:abcdef1234567890abcdef1234567890abcdef12",
            "Traceable photonic limitation paper",
        ),
    )
    conn.execute(
        "INSERT INTO paper_sections VALUES (?, ?, ?, ?, ?, ?)",
        (
            "p1",
            "Discussion",
            (
                "Thermal drift appears after packaging and remains a reproducible bottleneck. "
                "The authors report fabrication loss as the limiting constraint."
            ),
            "https://example.test/p1.pdf",
            json.dumps([7]),
            _meta(),
        ),
    )
    conn.commit()
    conn.close()

    build_section_atoms(db)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    doi_hits = search_section_atoms(conn, "thermal", top_k=5, filters={"doi": "10.1234/example.paper"})
    arxiv_hits = search_section_atoms(conn, "2401.12345", top_k=5)
    title_hits = search_section_atoms(
        conn,
        "fabrication loss",
        top_k=5,
        filters={"title": "Traceable photonic limitation paper"},
    )
    phrase_hits = search_section_atoms(conn, "Thermal drift", top_k=5, phrase_query=True)
    conn.close()

    hit = doi_hits[0]
    assert hit["paper_id"] == "p1"
    assert hit["doi"] == "10.1234/example.paper"
    assert hit["arxiv_id"] == "2401.12345"
    assert hit["openalex_id"] == "W123"
    assert hit["s2_paper_id"] == "abcdef1234567890abcdef1234567890abcdef12"
    assert hit["span"]["unit"] == "normalized_section_text_char_offsets"
    assert arxiv_hits and arxiv_hits[0]["paper_id"] == "p1"
    assert title_hits and title_hits[0]["title"] == "Traceable photonic limitation paper"
    assert phrase_hits and "Thermal drift" in phrase_hits[0]["atom_text"]


def test_build_section_atom_embeddings_and_fuzzy_search_are_context_only(tmp_path):
    db = tmp_path / "main.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE papers (id TEXT PRIMARY KEY, title TEXT);
        CREATE TABLE paper_sections (
            paper_id TEXT,
            section_name TEXT,
            section_text TEXT,
            source_url TEXT,
            section_pages_json TEXT,
            section_meta_json TEXT
        );
        """
    )
    conn.execute("INSERT INTO papers VALUES ('p1', 'Photonic fabrication loss study')")
    conn.execute("INSERT INTO papers VALUES ('p2', 'Efficiency benchmark study')")
    conn.execute(
        "INSERT INTO paper_sections VALUES (?, ?, ?, ?, ?, ?)",
        (
            "p1",
            "Discussion",
            (
                "A central limitation is fabrication error, optical loss, and thermal drift in dense photonic arrays. "
                "The authors describe this as an unresolved constraint for scalable deployment."
            ),
            "https://example.test/p1.pdf",
            json.dumps([6]),
            _meta(),
        ),
    )
    conn.execute(
        "INSERT INTO paper_sections VALUES (?, ?, ?, ?, ?, ?)",
        (
            "p2",
            "Results",
            (
                "Measured efficiency reached 35% at 1550 nm in a simulation benchmark and prototype validation setup. "
                "The result is reported as a metric rather than a proof of product readiness."
            ),
            "https://example.test/p2.pdf",
            json.dumps([8]),
            _meta(),
        ),
    )
    conn.commit()
    conn.close()

    build_section_atoms(db)
    stats = build_section_atom_embeddings(db, rebuild=True, embedding_dim=64)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    hits = search_section_atoms_fuzzy(conn, "thermal fabrication loss", top_k=5, embedding_dim=64)
    metric_hits = search_section_atoms_fuzzy(
        conn,
        "prototype validation efficiency",
        top_k=5,
        filters={"atom_type": "metric_result"},
        embedding_dim=64,
    )
    discussion_hits = search_section_atoms_fuzzy(
        conn,
        "thermal optical constraint",
        top_k=5,
        filters={"section_name": "Discussion"},
        embedding_dim=64,
    )
    conn.close()

    assert stats["atoms_seen"] >= 2
    assert stats["embeddings_written"] >= 2
    assert stats["claim_scope"] == "retrieval_context_only"
    assert hits[0]["paper_id"] == "p1"
    assert hits[0]["search_mode"] == "fuzzy_vector_recall"
    assert hits[0]["claim_scope"] == "retrieval_context_only"
    assert hits[0]["search_semantics"].startswith("candidate recall only")
    assert "embedding_json" not in hits[0]
    assert metric_hits and all(hit["atom_type"] == "metric_result" for hit in metric_hits)
    assert discussion_hits and all(hit["section_key"] == "discussion" for hit in discussion_hits)


def test_build_section_embeddings_and_fuzzy_search_are_context_only(tmp_path):
    db = tmp_path / "main.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE papers (id TEXT PRIMARY KEY, title TEXT, doi TEXT);
        CREATE TABLE paper_sections (
            paper_id TEXT,
            section_name TEXT,
            section_text TEXT,
            source_url TEXT,
            section_pages_json TEXT,
            section_meta_json TEXT
        );
        """
    )
    conn.execute("INSERT INTO papers VALUES ('p1', 'Photonic fabrication loss study', '10.1234/p1')")
    conn.execute("INSERT INTO papers VALUES ('p2', 'Efficiency benchmark study', '10.1234/p2')")
    conn.execute(
        "INSERT INTO paper_sections VALUES (?, ?, ?, ?, ?, ?)",
        (
            "p1",
            "Discussion",
            (
                "A central limitation is fabrication error, optical loss, and thermal drift in dense photonic arrays. "
                "The authors describe this as an unresolved constraint for scalable deployment."
            ),
            "https://example.test/p1.pdf",
            json.dumps([6]),
            _meta(),
        ),
    )
    conn.execute(
        "INSERT INTO paper_sections VALUES (?, ?, ?, ?, ?, ?)",
        (
            "p2",
            "Methods",
            (
                "The method uses a prototype validation setup and simulation benchmark for a different device class. "
                "It is useful context, but it is not the thermal fabrication-loss discussion."
            ),
            "https://example.test/p2.pdf",
            json.dumps([8]),
            _meta(),
        ),
    )
    conn.commit()
    conn.close()

    stats = build_section_embeddings(db, rebuild=True, embedding_dim=64)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    hits = search_sections_fuzzy(conn, "thermal fabrication loss unresolved constraint", top_k=5, embedding_dim=64)
    filtered = search_sections_fuzzy(
        conn,
        "thermal fabrication loss unresolved constraint",
        top_k=5,
        filters={"doi": "10.1234/p1", "section_name": "Discussion"},
        embedding_dim=64,
    )
    conn.close()

    assert stats["sections_seen"] == 2
    assert stats["embeddings_written"] == 2
    assert stats["claim_scope"] == "retrieval_context_only"
    assert hits[0]["paper_id"] == "p1"
    assert hits[0]["search_mode"] == "section_fuzzy_vector_recall"
    assert hits[0]["retrieval_context_kind"] == "paper_section_embedding_context"
    assert hits[0]["claim_scope"] == "retrieval_context_only"
    assert hits[0]["search_semantics"].startswith("candidate recall only")
    assert hits[0]["evidence_grade"] == "section_context_decision_grade"
    assert "embedding_json" not in hits[0]
    assert filtered and filtered[0]["paper_id"] == "p1"
    assert filtered[0]["section_key"] == "discussion"


def test_hybrid_section_atom_search_keeps_exact_and_fuzzy_contracts(tmp_path):
    db = tmp_path / "main.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE papers (id TEXT PRIMARY KEY, title TEXT);
        CREATE TABLE paper_sections (
            paper_id TEXT,
            section_name TEXT,
            section_text TEXT,
            source_url TEXT,
            section_pages_json TEXT,
            section_meta_json TEXT
        );
        """
    )
    conn.execute("INSERT INTO papers VALUES ('p1', 'Photonic fabrication loss study')")
    conn.execute("INSERT INTO papers VALUES ('p2', 'Efficiency benchmark study')")
    conn.execute(
        "INSERT INTO paper_sections VALUES (?, ?, ?, ?, ?, ?)",
        (
            "p1",
            "Discussion",
            (
                "A central limitation is fabrication error, optical loss, and thermal drift in dense photonic arrays. "
                "The authors describe this as an unresolved constraint for scalable deployment."
            ),
            "https://example.test/p1.pdf",
            json.dumps([6]),
            _meta(),
        ),
    )
    conn.execute(
        "INSERT INTO paper_sections VALUES (?, ?, ?, ?, ?, ?)",
        (
            "p2",
            "Results",
            (
                "Measured efficiency reached 35% at 1550 nm in a simulation benchmark and prototype validation setup. "
                "The result is reported as a metric rather than a proof of product readiness."
            ),
            "https://example.test/p2.pdf",
            json.dumps([8]),
            _meta(),
        ),
    )
    conn.commit()
    conn.close()

    build_section_atoms(db)
    build_section_atom_embeddings(db, rebuild=True, embedding_dim=64)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    result = search_section_atoms_hybrid(conn, "thermal fabrication loss", top_k=5, embedding_dim=64)
    conn.close()

    assert result["search_mode"] == "hybrid_exact_then_fuzzy_recall"
    assert result["search_contract"]["claim_scope"] == "retrieval_context_only"
    assert "graph/GNN expansion may rank" in result["search_contract"]["graph_expansion_semantics"]
    assert result["exact_hits"]
    assert result["fuzzy_candidate_hits"]
    assert result["merged_hits"][0]["paper_id"] == "p1"
    assert result["merged_hits"][0]["claim_scope"] == "retrieval_context_only"
    assert "exact_fts_bm25" in result["merged_hits"][0]["retrieval_channels"]
    assert any("fuzzy_vector_recall" in hit["retrieval_channels"] for hit in result["merged_hits"])
    assert all("embedding_json" not in hit for hit in result["merged_hits"])
