from __future__ import annotations

import json
import sqlite3

from fastapi.testclient import TestClient

from echelon.api.main import app


client = TestClient(app, raise_server_exceptions=False)
VIEWER_HEADERS = {"X-Pilot-Token": "pilot-viewer-token"}
EXPERT_HEADERS = {"X-Pilot-Token": "pilot-expert-token"}


def _make_visual_db(path):
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
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
            flags_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
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
        CREATE TABLE branch_lineages (
            branch_id TEXT PRIMARY KEY,
            parent_branch_id TEXT,
            split_year INTEGER,
            strength REAL,
            why_json TEXT,
            future_json TEXT
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
        CREATE TABLE visual_recommendations (
            mode TEXT NOT NULL,
            rank INTEGER NOT NULL,
            paper_id TEXT NOT NULL,
            score REAL NOT NULL,
            reason_json TEXT,
            PRIMARY KEY(mode, rank)
        );
        """
    )
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE visual_search_fts USING fts5(
                paper_id UNINDEXED,
                title,
                abstract,
                sections,
                limitations,
                branch_label,
                topics
            )
            """
        )
    except sqlite3.OperationalError:
        pass

    rows = [
        (
            "p1",
            "C0001",
            "B0001",
            0.1,
            0.2,
            0.8,
            2024,
            9.0,
            "#ffffff",
            "limitation_bottleneck",
            0.1,
            json.dumps({"has_unresolved_limitation": True}),
        ),
        (
            "p2",
            "C0001",
            "B0001",
            0.2,
            0.3,
            0.7,
            2022,
            6.0,
            "#ffffff",
            "main_path",
            0.2,
            json.dumps({"is_main_path": True}),
        ),
    ]
    conn.executemany(
        """
        INSERT INTO visual_nodes
            (paper_id, cluster_id, branch_id, x, y, z, publication_year,
             node_size, color_hex, visual_role, uncertainty_score, flags_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.execute(
        """
        INSERT INTO visual_clusters
            (cluster_id, branch_id, label, n_nodes, year_start, year_end,
             centroid_x, centroid_y, centroid_z, top_terms_json,
             representative_papers_json, evidence_json)
        VALUES ('C0001', 'B0001', 'integrated photonics', 2, 2022, 2024,
                0.15, 0.25, 0.75, '[]', '[]', '{}')
        """
    )
    conn.execute(
        """
        INSERT INTO branch_lineages
            (branch_id, parent_branch_id, split_year, strength, why_json, future_json)
        VALUES ('B0001', 'B0000', 2023, 0.42, ?, '{}')
        """,
        (
            json.dumps(
                {
                    "parent_citation_support": 9,
                    "parent_support_ratio": 0.36,
                    "split_reason": "Evidence-backed split from B0000 into integrated photonics.",
                }
            ),
        ),
    )
    for pid, title, abstract, role in (
        ("p1", "Laser photonics bottleneck", "This paper studies laser optical limits.", "bottleneck"),
        ("p2", "Foundational optics path", "A cited main-path optics paper.", "starter"),
    ):
        metadata = {
            "title": title,
            "year": 2024 if pid == "p1" else 2022,
            "cited_by_count": 25 if pid == "p1" else 100,
            "field": "F102",
            "subfield": "SF204",
            "topic": "T999",
            "branch_label": "integrated photonics",
        }
        conn.execute(
            """
            INSERT INTO visual_paper_details
                (paper_id, ids_json, metadata_json, abstract, sections_json,
                 limitations_json, recommendation_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pid,
                json.dumps({"paper_id": pid, "doi": f"10.0000/{pid}"}),
                json.dumps(metadata),
                abstract,
                "[]",
                json.dumps([{"description": "limited device stability"}] if pid == "p1" else []),
                json.dumps({role: True}),
            ),
        )
        try:
            conn.execute(
                """
                INSERT INTO visual_search_fts
                    (paper_id, title, abstract, sections, limitations, branch_label, topics)
                VALUES (?, ?, ?, '', '', 'integrated photonics', 'F102 SF204 T999')
                """,
                (pid, title, abstract),
            )
        except sqlite3.OperationalError:
            pass
    conn.execute(
        """
        INSERT INTO visual_edges
            (edge_id, source_paper_id, target_paper_id, edge_type, layer,
             weight, confidence, is_directed, is_main_path, lod_min,
             style_json, evidence_json)
        VALUES ('citation:p2:p1', 'p2', 'p1', 'citation', 'citation',
                2.0, 1.0, 1, 1, 0, '{}', '{"why":"true linked citation"}')
        """
    )
    conn.execute(
        """
        INSERT INTO visual_recommendations
            (mode, rank, paper_id, score, reason_json)
        VALUES ('bottleneck', 1, 'p1', 0.95, '{"why":"unresolved limitation"}')
        """
    )
    conn.commit()
    conn.close()


def test_visual_search_uses_materialized_tables(tmp_path, monkeypatch):
    db_path = tmp_path / "v14_pilot.sqlite3"
    _make_visual_db(db_path)
    monkeypatch.setenv("V14B_DB_V14", str(db_path))

    resp = client.post(
        "/graph/visual/search",
        headers=VIEWER_HEADERS,
        json={"query_type": "semantic", "query_text": "laser optics", "top_k": 5},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is True
    assert data["hits"][0]["paper_id"] == "p1"
    assert data["hits"][0]["cluster_label"] == "integrated photonics"


def test_visual_citation_and_bottleneck_search(tmp_path, monkeypatch):
    db_path = tmp_path / "v14_pilot.sqlite3"
    _make_visual_db(db_path)
    monkeypatch.setenv("V14B_DB_V14", str(db_path))

    cite = client.post(
        "/graph/visual/search",
        headers=VIEWER_HEADERS,
        json={"query_type": "cite", "filters": {"paper_id": "p1"}, "top_k": 5},
    ).json()
    assert cite["hits"][0]["paper_id"] == "p2"
    assert cite["hits"][0]["reason"]["layer"] == "citation"

    bottleneck = client.post(
        "/graph/visual/search",
        headers=VIEWER_HEADERS,
        json={"query_type": "bottleneck", "top_k": 5},
    ).json()
    assert bottleneck["hits"][0]["paper_id"] == "p1"


def test_visual_edit_roundtrip(tmp_path, monkeypatch):
    db_path = tmp_path / "v14_pilot.sqlite3"
    _make_visual_db(db_path)
    monkeypatch.setenv("V14B_DB_V14", str(db_path))

    payload = {
        "target_type": "node",
        "target_id": "p1",
        "action": "annotate",
        "payload": {"annotation_text": "Expert confirms this bottleneck"},
        "rationale": "Expert annotation for the visual graph node",
        "expert_id": "expert_alice",
    }
    accepted = client.post("/graph/visual/edit", headers=EXPERT_HEADERS, json=payload)
    assert accepted.status_code == 200
    edit_id = accepted.json()["edit"]["edit_id"]

    status = client.get(f"/graph/visual/edits/{edit_id}").json()
    assert status["status"] == "accepted"
    assert status["payload"]["annotation_text"] == "Expert confirms this bottleneck"

    history = client.get("/graph/visual/edits/history/expert_alice").json()
    assert history["total_matches"] == 1


def test_visual_topic_lens(tmp_path, monkeypatch):
    db_path = tmp_path / "v14_pilot.sqlite3"
    _make_visual_db(db_path)
    monkeypatch.setenv("V14B_DB_V14", str(db_path))

    resp = client.get(
        "/graph/visual/topic-lens",
        headers=VIEWER_HEADERS,
        params={"topic": "laser optics", "top_k": 20},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is True
    assert data["topic"] == "laser optics"
    assert data["total_related"] >= 1
    assert isinstance(data["cluster_distribution"], list)
    assert "history_main_path" in data
    assert "future_growth" in data
    assert "value_model" in data
    assert "topic_dossier" in data
    assert "branch_dossiers" in data
    assert "bottleneck_lineage" in data
    assert "rd_radar" in data
    assert "evidence_map" in data
    assert data["related_papers"][0]["access_links"]


def test_visual_clusters_branch_lineages_carry_evidence_contract(tmp_path, monkeypatch):
    db_path = tmp_path / "v14_pilot.sqlite3"
    _make_visual_db(db_path)
    monkeypatch.setenv("V14B_DB_V14", str(db_path))

    resp = client.get("/graph/visual/clusters", headers=VIEWER_HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    lineage = data["branch_lineages"][0]
    assert lineage["lineage_status"] == "evidence_backed_split"
    assert lineage["claim_scope"] == "evidence_backed_branch_split_candidate"
    assert lineage["evidence_grade"] == "graph_backed_branch_split"
    assert lineage["uncertainty_reasons"]
    assert lineage["required_evidence"]
    assert lineage["evidence_objects"][0]["type"] == "branch_lineage"


def test_visual_topic_lens_expands_to_cluster_context(tmp_path, monkeypatch):
    db_path = tmp_path / "v14_pilot.sqlite3"
    _make_visual_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO visual_nodes
            (paper_id, cluster_id, branch_id, x, y, z, publication_year,
             node_size, color_hex, visual_role, uncertainty_score, flags_json)
        VALUES ('p3', 'C0001', 'B0001', 0.4, 0.35, 0.9, 2025,
                5.0, '#ffffff', 'future_anchor', 0.2, '{}')
        """
    )
    conn.execute(
        """
        INSERT INTO visual_paper_details
            (paper_id, ids_json, metadata_json, abstract, sections_json,
             limitations_json, recommendation_json)
        VALUES ('p3', '{}',
                '{"title":"Nonmatching future branch paper","year":2025,"branch_label":"integrated photonics"}',
                'A branch-context paper without the query term.',
                '[]', '[]', '{}')
        """
    )
    conn.execute(
        """
        INSERT INTO visual_edges
            (edge_id, source_paper_id, target_paper_id, edge_type, layer,
             weight, confidence, is_directed, is_main_path, lod_min,
             style_json, evidence_json)
        VALUES ('main:p2:p3', 'p2', 'p3', 'main_path', 'citation',
                9.0, 1.0, 1, 1, 0, '{}', '{}')
        """
    )
    conn.execute(
        """
        INSERT INTO visual_edges
            (edge_id, source_paper_id, target_paper_id, edge_type, layer,
             weight, confidence, is_directed, is_main_path, lod_min,
             style_json, evidence_json)
        VALUES ('future:p2:p3', 'p2', 'p3', 'future_growth', 'future',
                0.82, 0.77, 1, 0, 0, '{}', '{}')
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("V14B_DB_V14", str(db_path))

    resp = client.get(
        "/graph/visual/topic-lens",
        headers=VIEWER_HEADERS,
        params={"topic": "laser", "top_k": 5},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["context"]["scope"] == "topic_cluster_branch_context"
    assert any(
        e["edge_id"] == "future:p2:p3"
        for e in data["future_growth"]["predicted_edges"]
    )
    assert any(
        e["evidence"]["relationship_scope"] == "cluster_branch_context"
        for e in data["history_main_path"]["edges"]
    )
