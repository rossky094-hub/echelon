"""
tests/v14b/test_limitation.py

Limitation Tracking 测试 (LLM mock)
"""
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from echelon.v14b.db_schema import init_v14b_db
from echelon.v14b.step5c_limitation import (
    extract_limitation_atoms,
    get_top_papers_for_limitation,
    check_resolution,
    rank_unresolved_limitations,
    HEURISTIC_RESOLUTION_EVIDENCE_TEXT,
    LIMITATION_EXTRACT_PROMPT,
    RESOLUTION_CHECK_PROMPT,
)


# ---------------------------------------------------------------------------
# Mock LLM Client
# ---------------------------------------------------------------------------

def make_mock_llm(response_json: dict):
    """创建返回固定 JSON 的 mock LLM client"""
    mock = MagicMock()
    mock.extract_json.return_value = response_json
    mock.extract.return_value = json.dumps(response_json)
    return mock


# ---------------------------------------------------------------------------
# 测试 extract_limitation_atoms
# ---------------------------------------------------------------------------

class TestExtractLimitationAtoms:
    def test_extract_returns_atoms(self):
        llm = make_mock_llm({
            "limitations": [
                {"description": "Requires cryogenic temperatures", "keyword": "cryogenic", "severity": "high"},
                {"description": "Limited to small scales", "keyword": "scalability", "severity": "medium"},
            ]
        })
        paper = {"id": 42, "title": "Test Paper", "abstract": "We demonstrate..."}
        atoms = extract_limitation_atoms(paper, llm)

        assert len(atoms) == 2
        assert atoms[0]["paper_id"] == 42
        assert atoms[0]["keyword"] == "cryogenic"
        assert atoms[0]["severity"] == "high"
        assert atoms[0]["evidence_quality"] == "weak_abstract"
        assert atoms[0]["evidence_weight"] == pytest.approx(0.35)
        assert atoms[1]["keyword"] == "scalability"

    def test_extract_empty_limitations(self):
        llm = make_mock_llm({"limitations": []})
        paper = {"id": 1, "title": "Good paper", "abstract": "No limitations"}
        atoms = extract_limitation_atoms(paper, llm)
        assert atoms == []

    def test_extract_max_atoms_enforced(self):
        """不超过 LIMITATION_MAX_ATOMS_PER_PAPER"""
        llm = make_mock_llm({
            "limitations": [
                {"description": f"Limitation {i}", "keyword": f"kw{i}", "severity": "low"}
                for i in range(10)  # 10 个限制
            ]
        })
        paper = {"id": 1, "title": "Paper", "abstract": "Abstract"}
        from echelon.v14b.config import LIMITATION_MAX_ATOMS_PER_PAPER
        atoms = extract_limitation_atoms(paper, llm)
        assert len(atoms) <= LIMITATION_MAX_ATOMS_PER_PAPER

    def test_extract_llm_failure_returns_empty(self):
        llm = MagicMock()
        llm.extract_json.side_effect = Exception("LLM error")
        paper = {"id": 1, "title": "Paper", "abstract": "Abstract"}
        atoms = extract_limitation_atoms(paper, llm)
        assert atoms == []

    def test_extract_invalid_json_returns_empty(self):
        llm = make_mock_llm({"unexpected_key": []})
        paper = {"id": 1, "title": "Paper", "abstract": "Abstract"}
        atoms = extract_limitation_atoms(paper, llm)
        assert atoms == []

    def test_extract_description_not_empty(self):
        llm = make_mock_llm({
            "limitations": [
                {"description": "  ", "keyword": "empty", "severity": "low"},  # 空描述
                {"description": "Real limitation", "keyword": "real", "severity": "high"},
            ]
        })
        paper = {"id": 1, "title": "Paper", "abstract": "Abstract"}
        atoms = extract_limitation_atoms(paper, llm)
        # 空描述应被过滤
        assert len(atoms) == 1
        assert atoms[0]["keyword"] == "real"

    def test_structured_section_evidence_is_marked_stronger(self):
        paper = {
            "id": 9,
            "title": "Paper",
            "abstract": "Short abstract",
            "limitation_text": "However, fabrication remains difficult and limits scalability.",
            "limitation_evidence_source": "structured_sections",
            "limitation_evidence_quality": "section_level",
            "limitation_evidence_weight": 0.75,
            "limitation_source_section_name": "discussion",
        }
        atoms = extract_limitation_atoms(paper, None)
        assert atoms
        assert atoms[0]["evidence_source"] == "structured_sections"
        assert atoms[0]["evidence_quality"] == "section_level"
        assert atoms[0]["evidence_weight"] == pytest.approx(0.75)
        assert atoms[0]["source_section_name"] == "discussion"

    def test_section_chunks_keep_exact_source_section_names(self):
        paper = {
            "id": "p1",
            "title": "Paper",
            "abstract": "Short abstract",
            "limitation_evidence_source": "structured_sections",
            "limitation_evidence_quality": "section_level",
            "limitation_evidence_weight": 0.75,
            "limitation_text_sections": [
                {
                    "section_name": "discussion",
                    "section_text": (
                        "However, scalability remains limited by fabrication noise "
                        "and this constraint requires careful calibration."
                    ),
                },
                {
                    "section_name": "method",
                    "section_text": (
                        "The method requires high power and the integration "
                        "bottleneck remains difficult for practical deployment."
                    ),
                },
            ],
        }
        atoms = extract_limitation_atoms(paper, None)
        assert atoms
        source_sections = {atom["source_section_name"] for atom in atoms}
        assert source_sections <= {"discussion", "method"}
        assert all("," not in source for source in source_sections)

    def test_structured_section_loader_preserves_section_chunks(self):
        conn_main = sqlite3.connect(":memory:")
        conn_main.row_factory = sqlite3.Row
        conn_main.executescript(
            """
            CREATE TABLE papers (
                id TEXT PRIMARY KEY,
                title TEXT,
                abstract TEXT
            );
            CREATE TABLE paper_sections (
                paper_id TEXT,
                section_name TEXT,
                section_text TEXT
            );
            """
        )
        conn_main.execute(
            "INSERT INTO papers VALUES (?, ?, ?)",
            ("p1", "Paper", "This abstract is deliberately long enough for the loader to accept it. " * 3),
        )
        conn_main.executemany(
            "INSERT INTO paper_sections VALUES (?, ?, ?)",
            [
                (
                    "p1",
                    "discussion",
                    "However, scalability remains limited by fabrication noise. " * 4,
                ),
                (
                    "p1",
                    "method",
                    "The method requires high power and this bottleneck remains difficult. " * 4,
                ),
            ],
        )
        conn_main.commit()

        conn_v14 = sqlite3.connect(":memory:")
        conn_v14.row_factory = sqlite3.Row
        conn_v14.execute(
            "CREATE TABLE subgraph_nodes (paper_id TEXT, keystone_score_v14 REAL, is_keystone INTEGER)"
        )
        conn_v14.execute("INSERT INTO subgraph_nodes VALUES (?, ?, ?)", ("p1", 1.0, 1))
        conn_v14.commit()

        papers = get_top_papers_for_limitation(conn_main, conn_v14, n=10)
        conn_main.close()
        conn_v14.close()

        assert len(papers) == 1
        assert [s["section_name"] for s in papers[0]["limitation_text_sections"]] == [
            "discussion",
            "method",
        ]
        assert papers[0].get("limitation_source_section_name") is None
        atoms = extract_limitation_atoms(papers[0], None)
        assert atoms
        assert {atom["source_section_name"] for atom in atoms} <= {"discussion", "method"}


# ---------------------------------------------------------------------------
# 测试 check_resolution
# ---------------------------------------------------------------------------

class TestCheckResolution:
    def test_resolution_found(self):
        llm = make_mock_llm({
            "resolves": True,
            "confidence": 0.85,
            "evidence": "This paper explicitly addresses the cryogenic requirement."
        })
        atom = {
            "atom_id": 1,
            "paper_id": 10,
            "description": "Requires cryogenic temperatures",
            "keyword": "cryogenic",
            "severity": "high",
        }
        resolver = {"id": 20, "title": "Room-temp solution", "abstract": "We show...", "publication_year": 2023}

        result = check_resolution(atom, resolver, "Old Paper", llm)
        assert result is not None
        assert result["atom_id"] == 1
        assert result["resolver_paper_id"] == 20
        assert result["confidence"] == pytest.approx(0.85)

    def test_resolution_not_found(self):
        llm = make_mock_llm({
            "resolves": False,
            "confidence": 0.1,
            "evidence": ""
        })
        atom = {"atom_id": 1, "paper_id": 10, "description": "Limitation", "keyword": "kw", "severity": "medium"}
        resolver = {"id": 20, "title": "Unrelated", "abstract": "Different topic", "publication_year": 2023}

        result = check_resolution(atom, resolver, "Old Paper", llm)
        assert result is None

    def test_resolution_llm_failure(self):
        llm = MagicMock()
        llm.extract_json.side_effect = Exception("LLM failure")
        atom = {"atom_id": 1, "paper_id": 10, "description": "Limitation", "keyword": "kw", "severity": "high"}
        resolver = {"id": 20, "title": "Paper", "abstract": "Abstract", "publication_year": 2023}

        result = check_resolution(atom, resolver, "Old Paper", llm)
        assert result is None


# ---------------------------------------------------------------------------
# 测试 rank_unresolved_limitations
# ---------------------------------------------------------------------------

class TestRankUnresolvedLimitations:
    def _create_test_db(self, tmp_path):
        db_path = tmp_path / "test_v14.sqlite3"
        conn = init_v14b_db(db_path)

        # 插入测试 atoms
        conn.executemany("""
            INSERT INTO limitation_atoms (atom_id, paper_id, description, keyword, severity)
            VALUES (?, ?, ?, ?, ?)
        """, [
            (1, 10, "High severity unresolved", "hw1", "high"),
            (2, 11, "Medium severity unresolved", "kw2", "medium"),
            (3, 12, "Low severity", "kw3", "low"),
            (4, 10, "High severity resolved", "kw4", "high"),
        ])

        # 为 atom_id=4 添加 high-confidence resolution
        conn.execute("""
            INSERT INTO limitation_resolutions (atom_id, resolver_paper_id, confidence)
            VALUES (4, 20, 0.9)
        """)
        conn.commit()
        return conn

    def test_returns_unresolved_only(self, tmp_path):
        conn = self._create_test_db(tmp_path)
        unresolved = rank_unresolved_limitations(conn, top_n=10)
        conn.close()

        atom_ids = {r["atom_id"] for r in unresolved}
        assert 4 not in atom_ids, "Resolved atom should not appear"

    def test_heuristic_resolution_does_not_remove_unresolved_atom(self, tmp_path):
        conn = self._create_test_db(tmp_path)
        conn.execute(
            "DELETE FROM limitation_resolutions WHERE atom_id = 4"
        )
        conn.execute(
            """
            INSERT INTO limitation_resolutions (atom_id, resolver_paper_id, confidence, evidence_text)
            VALUES (?, ?, ?, ?)
            """,
            (4, 21, 0.65, HEURISTIC_RESOLUTION_EVIDENCE_TEXT),
        )
        conn.commit()
        unresolved = rank_unresolved_limitations(conn, top_n=10)
        conn.close()

        atom_ids = {r["atom_id"] for r in unresolved}
        assert 4 in atom_ids, "Lexical resolver candidates should not close unresolved atoms"

    def test_high_severity_first(self, tmp_path):
        conn = self._create_test_db(tmp_path)
        unresolved = rank_unresolved_limitations(conn, top_n=10)
        conn.close()

        if len(unresolved) >= 2:
            # High severity should come before medium
            high_idx = next((i for i, r in enumerate(unresolved) if r["severity"] == "high"), None)
            low_idx = next((i for i, r in enumerate(unresolved) if r["severity"] == "low"), None)
            if high_idx is not None and low_idx is not None:
                assert high_idx <= low_idx

    def test_top_n_respected(self, tmp_path):
        conn = self._create_test_db(tmp_path)
        unresolved = rank_unresolved_limitations(conn, top_n=2)
        conn.close()
        assert len(unresolved) <= 2
