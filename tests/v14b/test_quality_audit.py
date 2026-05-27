from pathlib import Path

from echelon.v14b.step0_quality_audit import run_audit


def test_quality_audit_writes_expected_artifacts(tmp_path: Path):
    import sqlite3

    db = tmp_path / "audit.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE papers (
            id TEXT PRIMARY KEY,
            openalex_id TEXT,
            doi TEXT UNIQUE,
            arxiv_id TEXT UNIQUE,
            title TEXT NOT NULL,
            abstract TEXT,
            publication_date TEXT NOT NULL,
            n_authors INTEGER,
            cited_by_count INTEGER,
            primary_topic_id TEXT,
            primary_subfield_id TEXT,
            primary_field_id TEXT,
            primary_domain_id TEXT,
            raw_jsonb TEXT,
            source_provider TEXT,
            openalex_enriched INTEGER DEFAULT 0,
            keystone_score_v14 REAL,
            lifecycle_v14 TEXT
        );
        CREATE TABLE paper_references (
            citing_paper_id TEXT NOT NULL,
            cited_paper_id_external TEXT NOT NULL,
            cited_paper_id_internal TEXT,
            PRIMARY KEY (citing_paper_id, cited_paper_id_external)
        );
        INSERT INTO papers (
            id, openalex_id, doi, arxiv_id, title, abstract,
            publication_date, n_authors, cited_by_count, primary_topic_id,
            raw_jsonb, source_provider, openalex_enriched
        ) VALUES
            ('p1', 'W1', '10.1/a', '2401.00001', 'Optics A', 'abstract',
             '2024-01-01', 2, 10, 'physics.optics',
             '{"categories":["physics.optics"]}', 'arxiv', 1),
            ('p2', 'S2HASH', NULL, '2401.00002', 'Optics B', 'abstract',
             '2024-01-02', 1, 3, 'physics.optics',
             '{"categories":["physics.optics"]}', 'semantic_scholar', 1);
        INSERT INTO paper_references
            (citing_paper_id, cited_paper_id_external, cited_paper_id_internal)
        VALUES
            ('p1', '2401.00002', 'p2'),
            ('p2', 'W1', 'p1');
        """
    )
    conn.commit()
    conn.close()

    out_dir = tmp_path / "reports"
    audit = run_audit(
        db_path=db,
        out_dir=out_dir,
        expected_total=2,
        sample_limit=2,
        expert_limit=2,
    )

    assert audit["summary"]["optics_papers"] == 2
    assert (out_dir / "coverage_quality_audit.json").exists()
    assert (out_dir / "coverage_quality_audit.md").exists()
    assert (out_dir / "sample_for_llm_review.jsonl").exists()
    assert (out_dir / "expert_review_sample.csv").exists()
