import json
import sqlite3


def _make_visual_db(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE visual_edges (
            edge_id TEXT PRIMARY KEY,
            source_paper_id TEXT NOT NULL,
            target_paper_id TEXT NOT NULL,
            edge_type TEXT NOT NULL,
            layer TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1.0,
            confidence REAL,
            is_directed INTEGER NOT NULL DEFAULT 1,
            is_main_path INTEGER NOT NULL DEFAULT 0,
            lod_min INTEGER NOT NULL DEFAULT 2,
            style_json TEXT,
            evidence_json TEXT
        );
        CREATE TABLE visual_nodes (
            paper_id TEXT PRIMARY KEY,
            cluster_id TEXT,
            branch_id TEXT,
            x REAL NOT NULL,
            y REAL NOT NULL,
            z REAL NOT NULL,
            publication_year INTEGER,
            node_size REAL,
            color_hex TEXT,
            visual_role TEXT,
            uncertainty_score REAL,
            flags_json TEXT
        );
        CREATE TABLE visual_paper_details (
            paper_id TEXT PRIMARY KEY,
            ids_json TEXT,
            metadata_json TEXT,
            abstract TEXT,
            sections_json TEXT,
            limitations_json TEXT,
            recommendation_json TEXT
        );
        CREATE TABLE branch_lineages (
            branch_id TEXT PRIMARY KEY,
            parent_branch_id TEXT,
            split_year INTEGER,
            strength REAL,
            why_json TEXT,
            future_json TEXT
        );
        CREATE TABLE visual_clusters (
            cluster_id TEXT PRIMARY KEY,
            branch_id TEXT,
            label TEXT,
            n_nodes INTEGER,
            year_start INTEGER,
            year_end INTEGER,
            centroid_x REAL,
            centroid_y REAL,
            centroid_z REAL,
            top_terms_json TEXT,
            representative_papers_json TEXT,
            evidence_json TEXT
        );
        CREATE TABLE v14b_run_meta (
            step_name TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'pending',
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            records_n INTEGER DEFAULT 0,
            notes TEXT
        );
        """
    )
    for i in range(1, 8):
        field = "F1" if i % 2 else "F2"
        cluster = "C1" if i <= 4 else "C2"
        role = "main_path" if i == 1 else "paper"
        conn.execute(
            "INSERT INTO visual_nodes VALUES (?, ?, ?, 0, 0, 0, ?, ?, '#fff', ?, 0.1, '{}')",
            (f"p{i}", cluster, f"B{cluster[-1]}", 2020 + i, 10.0 + i, role),
        )
        conn.execute(
            "INSERT INTO visual_paper_details VALUES (?, '{}', ?, ?, '{}', ?, '{}')",
            (
                f"p{i}",
                json.dumps({"title": f"Paper {i}", "year": 2020 + i, "field": field, "topic": "T1"}),
                f"Abstract for paper {i} about topological photonics and loss.",
                json.dumps([{"keyword": "loss", "description": "loss remains"}]),
            ),
        )
    edge_rows = [
        ("fg1", "p1", "p5", "future_growth", 0.91),
        ("mp1", "p1", "p2", "main_path", 1.0),
        ("c1", "p2", "p3", "citation", 1.0),
        ("c2", "p2", "p6", "citation", 1.0),
        ("s1", "p3", "p4", "semantic_similarity", 0.4),
        ("s2", "p3", "p7", "semantic_similarity", 0.8),
        ("co1", "p4", "p5", "cocitation", 0.2),
        ("co2", "p5", "p6", "cocitation", 0.7),
    ]
    for edge_id, src, dst, edge_type, conf in edge_rows:
        conn.execute(
            "INSERT INTO visual_edges VALUES (?, ?, ?, ?, ?, 1.0, ?, 1, ?, 2, '{}', '{}')",
            (edge_id, src, dst, edge_type, edge_type, conf, int(edge_type == "main_path")),
        )
    conn.execute(
        "INSERT INTO branch_lineages VALUES ('B2', 'B1', 2024, 0.8, ?, ?)",
        (json.dumps({"interpretation": "split"}), json.dumps({"predicted_edges": []})),
    )
    for cid, bid in [("C1", "B1"), ("C2", "B2")]:
        conn.execute(
            "INSERT INTO visual_clusters VALUES (?, ?, ?, 3, 2020, 2026, 0, 0, 0, ?, ?, '{}')",
            (cid, bid, f"cluster {cid}", json.dumps(["topological", "loss"]), json.dumps([])),
        )
    conn.commit()
    return conn


def test_stratified_edge_audit_plan_has_required_buckets(tmp_path):
    from echelon.v14b.step11_llm_edge_audit import (
        insert_audit_job,
        select_audit_candidates,
    )

    conn = _make_visual_db(tmp_path / "v14.sqlite3")
    candidates = select_audit_candidates(
        conn,
        sample_per_layer=1,
        extra_sample=4,
        branch_mode="all",
        seed=7,
    )
    ids = {c.item_id for c in candidates}
    buckets = ",".join(c.sample_bucket for c in candidates)

    assert "edge:fg1" in ids
    assert "edge:mp1" in ids
    assert "branch_lineage:B2" in ids
    assert "sample_citation" in buckets
    assert "sample_semantic_similarity" in buckets
    assert "sample_cocitation" in buckets
    assert len(ids) == len(candidates)

    stats = insert_audit_job(
        conn,
        job_id="test-job",
        provider="doubao",
        model=None,
        sample_config={"sample_per_layer": 1},
        candidates=candidates,
        abstract_chars=120,
    )
    assert stats["selected_items"] == len(candidates)
    assert stats["estimated_cost_rmb"] > 0
    pending = conn.execute(
        "SELECT COUNT(*) FROM llm_edge_audit_items WHERE job_id='test-job' AND status='pending'"
    ).fetchone()[0]
    assert pending == len(candidates)
    conn.close()


def test_edge_audit_prompt_requires_json_verdict(tmp_path):
    from echelon.v14b.step11_llm_edge_audit import (
        AuditCandidate,
        build_audit_prompt,
        build_payload,
    )

    conn = _make_visual_db(tmp_path / "v14.sqlite3")
    payload = build_payload(
        conn,
        AuditCandidate(
            item_type="edge",
            target_id="fg1",
            sample_bucket="all_future_growth",
            priority=10,
            edge_type="future_growth",
            source_paper_id="p1",
            target_paper_id="p5",
        ),
        abstract_chars=120,
    )
    prompt = build_audit_prompt(payload)
    assert "verdict" in prompt
    assert "future_growth" in prompt
    assert "Paper 1" in prompt
    assert "Paper 5" in prompt
    conn.close()
