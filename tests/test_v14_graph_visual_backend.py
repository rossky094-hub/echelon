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
        CREATE TABLE visual_story_steps (
            story_step_id TEXT PRIMARY KEY,
            order_idx INTEGER NOT NULL,
            year_start INTEGER,
            year_end INTEGER,
            title TEXT,
            narrative TEXT,
            focus_cluster_id TEXT,
            focus_papers_json TEXT,
            evidence_json TEXT
        );
        CREATE TABLE first_principles_principles (
            principle_id TEXT PRIMARY KEY,
            principle_name TEXT,
            root_cause TEXT,
            bottleneck_score REAL,
            unresolved_atoms INTEGER,
            resolved_atoms INTEGER,
            emergence_year INTEGER,
            peak_backlog_year INTEGER,
            current_backlog INTEGER,
            evidence_quality_json TEXT,
            top_keywords_json TEXT,
            top_branches_json TEXT,
            top_papers_json TEXT,
            future_alignment_json TEXT,
            direction_tier_json TEXT,
            risk_label TEXT,
            notes_json TEXT
        );
        CREATE TABLE bottleneck_lineage_triples (
            triple_id TEXT PRIMARY KEY,
            principle_id TEXT,
            direction_id INTEGER,
            atom_id INTEGER,
            edge_order INTEGER,
            source_stage TEXT,
            target_stage TEXT,
            source_text TEXT,
            target_text TEXT,
            relation_type TEXT,
            paper_id TEXT,
            resolver_paper_id TEXT,
            event_year INTEGER,
            evidence_section TEXT,
            evidence_page INTEGER,
            evidence_quality TEXT,
            evidence_weight REAL,
            metadata_json TEXT
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
    conn.execute(
        """
        INSERT INTO visual_story_steps
            (story_step_id, order_idx, year_start, year_end, title, narrative,
             focus_cluster_id, focus_papers_json, evidence_json)
        VALUES ('story:2020-2024', 1, 2020, 2024, 'Branch expansion',
                'Time-sliced view of active optics branches.', 'C0001', ?, ?)
        """,
        (
            json.dumps([{"paper_id": "p1", "title": "Laser photonics bottleneck", "year": 2024}]),
            json.dumps({"active_clusters": ["C0001"]}),
        ),
    )
    conn.execute(
        """
        INSERT INTO visual_story_steps
            (story_step_id, order_idx, year_start, year_end, title, narrative,
             focus_cluster_id, focus_papers_json, evidence_json)
        VALUES ('story:future', 2, 2024, 2029, 'Future growth candidates',
                'Future candidate edges and unresolved limitations.', NULL, '[]', ?)
        """,
        (
            json.dumps({"source": "future_candidate_edges + limitation_atoms + direction_claim_cards"}),
        ),
    )
    conn.execute(
        """
        INSERT INTO first_principles_principles
            (principle_id, principle_name, root_cause, bottleneck_score,
             unresolved_atoms, resolved_atoms, emergence_year, peak_backlog_year,
             current_backlog, evidence_quality_json, top_keywords_json,
             top_branches_json, top_papers_json, future_alignment_json,
             direction_tier_json, risk_label, notes_json)
        VALUES ('bp1', 'Laser stability constraint',
                'Device stability limits repeatable laser optics experiments.',
                0.91, 3, 1, 2020, 2024, 2, '{}',
                '[{"key":"laser"},{"key":"stability"}]',
                '[]', '[]', '{}', '{}', 'open_constraint', '{}')
        """
    )
    conn.execute(
        """
        INSERT INTO bottleneck_lineage_triples
            (triple_id, principle_id, direction_id, atom_id, edge_order,
             source_stage, target_stage, source_text, target_text, relation_type,
             paper_id, resolver_paper_id, event_year, evidence_section,
             evidence_page, evidence_quality, evidence_weight, metadata_json)
        VALUES ('bt1', 'bp1', NULL, NULL, 1,
                'constraint', 'failure_mechanism',
                'laser stability constraint',
                'instability causes measurement drift',
                'causes', 'p1', NULL, 2024,
                'discussion', 4, 'section_level', 1.0, '{}')
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
    hit = data["hits"][0]
    assert hit["claim_scope"] == "bottleneck_context_only"
    assert hit["evidence_grade"]
    assert hit["uncertainty_reasons"]
    assert hit["required_evidence"]
    assert hit["evidence_objects"][0]["type"] == "paper"


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
    assert cite["hits"][0]["claim_scope"] == "main_path_context_only"
    assert cite["hits"][0]["evidence_objects"][0]["type"] == "paper"

    bottleneck = client.post(
        "/graph/visual/search",
        headers=VIEWER_HEADERS,
        json={"query_type": "bottleneck", "top_k": 5},
    ).json()
    assert bottleneck["hits"][0]["paper_id"] == "p1"
    assert bottleneck["hits"][0]["claim_scope"] == "bottleneck_context_only"
    assert bottleneck["hits"][0]["uncertainty_reasons"]


def test_visual_paper_detail_paper_role_carries_evidence_contract(tmp_path, monkeypatch):
    db_path = tmp_path / "v14_pilot.sqlite3"
    _make_visual_db(db_path)
    monkeypatch.setenv("V14B_DB_V14", str(db_path))

    resp = client.get("/graph/visual/papers/p1", headers=VIEWER_HEADERS)

    assert resp.status_code == 200
    role = resp.json()["paper"]["paper_role"]
    assert role["role"] == "limitation_bottleneck"
    assert role["claim_scope"] == "bottleneck_context_only"
    assert role["evidence_grade"] in {"metadata_bottleneck_context", "weak_bottleneck_context", "section_bottleneck_context"}
    assert role["uncertainty_reasons"]
    assert role["required_evidence"]
    assert role["evidence_objects"]
    assert role["evidence_objects"][0]["type"] == "paper"
    limitation = resp.json()["paper"]["limitations"][0]
    assert limitation["claim_scope"] == "weak_bottleneck_hypothesis"
    assert limitation["evidence_grade"] == "metadata_or_abstract_limitation_context"
    assert limitation["uncertainty_reasons"]
    assert limitation["required_evidence"]
    assert limitation["evidence_objects"][0]["type"] == "limitation_atom"
    edge = resp.json()["edges"][0]
    assert edge["claim_scope"] == "main_path_context_only"
    assert edge["evidence_grade"]
    assert edge["uncertainty_reasons"]
    assert edge["required_evidence"]
    assert edge["evidence_objects"][0]["type"] == "visual_edge"


def test_visual_nodes_carry_hover_evidence_contract(tmp_path, monkeypatch):
    db_path = tmp_path / "v14_pilot.sqlite3"
    _make_visual_db(db_path)
    monkeypatch.setenv("V14B_DB_V14", str(db_path))

    resp = client.get("/graph/visual/nodes", headers=VIEWER_HEADERS, params={"limit": 5})

    assert resp.status_code == 200
    data = resp.json()
    nodes = {node["paper_id"]: node for node in data["nodes"]}
    bottleneck = nodes["p1"]
    assert bottleneck["claim_scope"] == "bottleneck_context_only"
    assert bottleneck["evidence_grade"] == "graph_bottleneck_node_context"
    assert any("navigation context" in reason for reason in bottleneck["uncertainty_reasons"])
    assert bottleneck["required_evidence"]
    assert bottleneck["evidence_objects"][0]["type"] == "visual_node_role"
    assert bottleneck["evidence_objects"][0]["click_target"] == {"kind": "paper", "id": "p1"}

    main_path = nodes["p2"]
    assert main_path["claim_scope"] == "main_path_context_only"
    assert main_path["evidence_grade"] == "graph_main_path_node_context"


def test_visual_edges_carry_evidence_contract(tmp_path, monkeypatch):
    db_path = tmp_path / "v14_pilot.sqlite3"
    _make_visual_db(db_path)
    monkeypatch.setenv("V14B_DB_V14", str(db_path))

    resp = client.get("/graph/visual/edges", headers=VIEWER_HEADERS, params={"lod_max": 1})

    assert resp.status_code == 200
    data = resp.json()
    edge = data["edges"][0]
    assert edge["claim_scope"] == "main_path_context_only"
    assert edge["evidence_grade"]
    assert any("main-path" in reason for reason in edge["uncertainty_reasons"])
    assert edge["required_evidence"]
    assert edge["evidence_objects"][0]["type"] == "visual_edge"
    assert edge["evidence_objects"][0]["click_target"]["kind"] == "edge"


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
    assert "candidate_edges" in data["future_growth"]
    assert "predicted_edges" not in data["future_growth"]
    assert "value_model" in data
    assert "topic_dossier" in data
    assert "branch_dossiers" in data
    assert "bottleneck_lineage" in data
    assert "rd_radar" in data
    assert "evidence_map" in data
    evidence_main = data["evidence_map"]["main_path"]
    assert evidence_main["claim_scope"]
    assert evidence_main["evidence_grade"]
    assert evidence_main["uncertainty_reasons"]
    assert evidence_main["required_evidence"]
    assert evidence_main["can_explain"]
    assert evidence_main["cannot_explain"]
    assert evidence_main["evidence_objects"][0]["type"] == "main_path_edge"
    reading_step = data["topic_dossier"]["reading_path"][0]
    assert reading_step["claim_scope"]
    assert reading_step["evidence_grade"]
    assert reading_step["can_explain"]
    assert reading_step["cannot_explain"]
    assert reading_step["uncertainty_reasons"]
    assert reading_step["required_evidence"]
    assert reading_step["evidence_objects"]
    direction = data["topic_dossier"]["validation_directions"][0]
    assert direction["claim_scope"]
    assert direction["evidence_grade"]
    assert direction["can_explain"]
    assert direction["cannot_explain"]
    assert direction["required_evidence"]
    assert direction["uncertainty_reasons"]
    assert direction["evidence_objects"]
    constraint = data["bottleneck_lineage"]["constraints"][0]
    assert constraint["claim_scope"]
    assert constraint["evidence_grade"]
    assert constraint["can_explain"]
    assert constraint["cannot_explain"]
    assert constraint["required_evidence"]
    assert constraint["uncertainty_reasons"]
    assert constraint["evidence_objects"]
    assert data["related_papers"][0]["access_links"]
    related = data["related_papers"][0]
    assert related["claim_scope"]
    assert related["evidence_grade"]
    assert related["uncertainty_reasons"]
    assert related["required_evidence"]
    assert related["evidence_objects"][0]["type"] == "paper"
    limitation = data["unresolved_limitations"][0]
    assert limitation["claim_scope"] in {"weak_bottleneck_hypothesis", "bottleneck_context_only", "partial_resolution_context_only"}
    assert limitation["evidence_grade"]
    assert limitation["uncertainty_reasons"]
    assert limitation["required_evidence"]
    assert limitation["evidence_objects"][0]["type"] == "limitation_atom"


def test_visual_topic_lens_prioritizes_promotable_typed_lineage(tmp_path, monkeypatch):
    db_path = tmp_path / "v14_pilot.sqlite3"
    _make_visual_db(db_path)
    conn = sqlite3.connect(str(db_path))
    partial_meta = json.dumps(
        {
            "typed_chain_complete": False,
            "typed_chain_completeness": "sparse_stage_partial",
            "claim_scope": "exploratory_bottleneck_lineage",
            "evidence_grade": "partial_typed_section_lineage",
            "source": "section_atom_chain",
        }
    )
    for idx in range(25):
        conn.execute(
            """
            INSERT INTO bottleneck_lineage_triples
                (triple_id, principle_id, direction_id, atom_id, edge_order,
                 source_stage, target_stage, source_text, target_text, relation_type,
                 paper_id, resolver_paper_id, event_year, evidence_section,
                 evidence_page, evidence_quality, evidence_weight, metadata_json)
            VALUES (?, 'bp1', NULL, NULL, ?, 'constraint', 'failure_mechanism',
                    'recent weak partial', 'missing evidence: no attempt path',
                    'constraint_causes_failure', 'p1', NULL, 2026,
                    'discussion', 4, 'section_level', 0.45, ?)
            """,
            (f"partial:{idx}", idx + 1, partial_meta),
        )
    full_meta = json.dumps(
        {
            "typed_chain_complete": True,
            "typed_chain_completeness": "full",
            "claim_scope": "bottleneck_lineage_evidence",
            "evidence_grade": "typed_section_lineage_traced",
            "source": "section_atom_chain",
            "section_atom_chain_id": "sac_promotable",
            "placeholder_stages": [],
        }
    )
    conn.execute(
        """
        INSERT INTO bottleneck_lineage_triples
            (triple_id, principle_id, direction_id, atom_id, edge_order,
             source_stage, target_stage, source_text, target_text, relation_type,
             paper_id, resolver_paper_id, event_year, evidence_section,
             evidence_page, evidence_quality, evidence_weight, metadata_json)
        VALUES ('full:old', 'bp1', NULL, NULL, 1,
                'constraint', 'failure_mechanism',
                'older complete typed constraint',
                'complete failure mechanism',
                'constraint_causes_failure', 'p1', NULL, 2020,
                'discussion', 4, 'section_level', 0.85, ?)
        """,
        (full_meta,),
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("V14B_DB_V14", str(db_path))

    resp = client.get(
        "/graph/visual/topic-lens",
        headers=VIEWER_HEADERS,
        params={"topic": "laser optics", "top_k": 20},
    )

    assert resp.status_code == 200
    constraint = resp.json()["bottleneck_lineage"]["constraints"][0]
    assert constraint["typed_chain_completeness"] == "full"
    assert constraint["claim_scope"] == "bottleneck_lineage_evidence"
    assert constraint["evidence_grade"] == "typed_section_lineage_traced"
    assert constraint["typed_chain"][0]["triple_id"] == "full:old"
    assert constraint["typed_chain"][0]["typed_chain_promotable"] is True
    assert constraint["evidence_objects"][0]["section_atom_chain_id"] == "sac_promotable"


def test_visual_topic_lens_links_claim_cards_by_future_edge_overlap(tmp_path, monkeypatch):
    db_path = tmp_path / "v14_pilot.sqlite3"
    _make_visual_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE future_directions (
            direction_id INTEGER PRIMARY KEY,
            direction_name TEXT,
            confidence REAL,
            evidence_tier TEXT,
            claim_scope TEXT,
            main_path_evidence TEXT,
            vgae_evidence TEXT,
            limitation_evidence TEXT,
            paper_ids_json TEXT
        );
        CREATE TABLE direction_claim_cards (
            claim_card_id TEXT PRIMARY KEY,
            direction_id INTEGER,
            root_constraint_json TEXT,
            attempts_last_10y_json TEXT,
            enabling_conditions_json TEXT,
            unresolved_bottleneck_json TEXT,
            minimal_validation_experiment_json TEXT,
            evidence_strength_level TEXT,
            evidence_grade TEXT,
            uncertainty_reasons_json TEXT,
            evidence_objects_json TEXT,
            five_question_complete INTEGER,
            high_confidence_eligible INTEGER,
            quality_gate_json TEXT
        );
        """
    )
    conn.execute(
        """
        INSERT INTO visual_edges
            (edge_id, source_paper_id, target_paper_id, edge_type, layer,
             weight, confidence, is_directed, is_main_path, lod_min,
             style_json, evidence_json)
        VALUES ('future:p1:p2', 'p1', 'p2', 'future_growth', 'future',
                0.8, 0.8, 1, 0, 1, '{}',
                '{"calibrated_candidate_score":0.7,"calibration_status":"calibrated_with_run_audit"}')
        """
    )
    conn.execute(
        """
        INSERT INTO future_directions VALUES (
            9, 'Frequency-comb validation direction', 0.8, 'exploratory',
            'exploratory_with_claim_card', '', '', '', '["p1","p2"]'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO direction_claim_cards VALUES (
            'cc9', 9, '{}', '[]', '{}', '{}',
            '{"experiment":"measure future candidate"}',
            'strong', 'complete_claim_card_pending_high_confidence_evidence',
            '[]', '[]', 1, 0, '{}'
        )
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("V14B_DB_V14", str(db_path))

    resp = client.get(
        "/graph/visual/topic-lens",
        headers=VIEWER_HEADERS,
        params={"topic": "laser optics", "top_k": 20},
    )

    assert resp.status_code == 200
    radar = resp.json()["rd_radar"]
    assert len(radar["claim_cards"]) == 1
    assert radar["claim_cards"][0]["direction_id"] == 9
    assert radar["claim_cards"][0]["topic_relevance_contract"]["future_edge_paper_overlap"] == ["p1", "p2"]
    assert radar["claim_cards"][0]["topic_relevance_contract"]["relationship_scope"] == "topic_text_or_context"


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


def test_visual_story_steps_carry_evidence_contract(tmp_path, monkeypatch):
    db_path = tmp_path / "v14_pilot.sqlite3"
    _make_visual_db(db_path)
    monkeypatch.setenv("V14B_DB_V14", str(db_path))

    resp = client.get("/graph/visual/story", headers=VIEWER_HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    story = {step["story_step_id"]: step for step in data["story_steps"]}
    assert story["story:2020-2024"]["claim_scope"] == "timeline_context_only"
    assert story["story:2020-2024"]["evidence_grade"] == "metadata_cluster_timeline_context"
    assert story["story:2020-2024"]["uncertainty_reasons"]
    assert story["story:2020-2024"]["required_evidence"]
    assert any(obj["type"] == "paper" for obj in story["story:2020-2024"]["evidence_objects"])
    assert story["story:future"]["claim_scope"] == "candidate_pool_only"
    assert story["story:future"]["evidence_grade"] == "future_candidate_story_context"
    assert any("Claim Card" in reason for reason in story["story:future"]["uncertainty_reasons"])


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
        for e in data["future_growth"]["candidate_edges"]
    )
    assert any(
        e["evidence"]["relationship_scope"] == "cluster_branch_context"
        for e in data["history_main_path"]["edges"]
    )
