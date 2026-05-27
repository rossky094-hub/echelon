"""
tests/test_v13_graph_visual_preembed.py
========================================
[V13 schema / V14B endpoint] Unit tests for graph_visual_edit schema + FastAPI endpoints.

Coverage (≥20 tests):
  - GraphVisualEdit schema validation (all 11 actions)
  - GraphSearchQuery schema validation (12 query_types)
  - FastAPI endpoint behaviour + RBAC enforcement
  - OpenAPI schema completeness
  - Example coverage for all actions + query_types

参考: V13 系统级方案 §4 接口预埋; AUDIT-056 RBAC; AUDIT-079/080 GraphEditOperation
"""

from __future__ import annotations

import json
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from echelon.schema.graph_visual_edit import (
    GraphVisualEdit,
    GraphSearchQuery,
    GraphSearchResult,
)
from echelon.api.graph_visual import router
from echelon.api.main import app
from echelon.api.graph_visual_openapi_examples import (
    GRAPH_VISUAL_EDIT_EXAMPLES,
    GRAPH_SEARCH_QUERY_EXAMPLES,
    ALL_EDIT_ACTIONS,
    ALL_QUERY_TYPES,
)

# ---------------------------------------------------------------------------
# Test client
# ---------------------------------------------------------------------------
client = TestClient(app, raise_server_exceptions=False)

# ---------------------------------------------------------------------------
# Header helpers (AUDIT-056 Pilot tokens)
# ---------------------------------------------------------------------------
EXPERT_HEADERS = {"X-Pilot-Token": "pilot-expert-token"}
VIEWER_HEADERS = {"X-Pilot-Token": "pilot-viewer-token"}
ADMIN_HEADERS  = {"X-Pilot-Token": "pilot-admin-token"}
NO_AUTH_HEADERS: dict = {}


# ===========================================================================
# 1. GraphVisualEdit schema — valid payloads
# ===========================================================================

def _make_edit(action: str, payload: dict, **kwargs) -> GraphVisualEdit:
    """Helper: create a GraphVisualEdit with required fields."""
    return GraphVisualEdit(
        target_type=kwargs.get("target_type", "node"),
        target_id=kwargs.get("target_id", "node-001"),
        action=action,
        payload=payload,
        rationale="Expert rationale for audit log — at least 10 chars",
        expert_id="expert_test",
        **{k: v for k, v in kwargs.items() if k not in ("target_type", "target_id")},
    )


class TestGraphVisualEditValid:
    """Tests for valid GraphVisualEdit payloads (11 actions)."""

    def test_pin_position_payload_valid(self):
        edit = _make_edit("pin_position", {"x": 10.0, "y": 20.5})
        assert edit.action == "pin_position"
        assert edit.payload["x"] == 10.0

    def test_override_fused_weight_payload_valid(self):
        edit = _make_edit("override_fused_weight", {"weight": 0.75}, target_type="edge")
        assert edit.payload["weight"] == 0.75

    def test_override_color_payload_valid(self):
        edit = _make_edit("override_color", {"hex_color": "#FF0000"}, target_type="node")
        assert edit.payload["hex_color"] == "#FF0000"

    def test_add_label_payload_valid(self):
        edit = _make_edit("add_label", {"label_text": "重要节点"}, target_type="halo")
        assert edit.payload["label_text"] == "重要节点"

    def test_merge_nodes_payload_valid(self):
        edit = _make_edit("merge_nodes", {"merge_target_ids": ["n1", "n2"]})
        assert len(edit.payload["merge_target_ids"]) == 2

    def test_split_node_payload_valid(self):
        edit = _make_edit(
            "split_node",
            {"split_into_ids": ["n-a", "n-b"]},
            target_type="node",
        )
        assert len(edit.payload["split_into_ids"]) == 2

    def test_hide_empty_payload_valid(self):
        edit = _make_edit("hide", {})
        assert edit.action == "hide"

    def test_show_empty_payload_valid(self):
        edit = _make_edit("show", {})
        assert edit.action == "show"

    def test_promote_landmark_payload_valid(self):
        edit = _make_edit(
            "promote_landmark",
            {"short_label_zh": "Transformer 原文"},
            target_type="node",
        )
        assert "short_label_zh" in edit.payload

    def test_demote_landmark_empty_payload_valid(self):
        edit = _make_edit("demote_landmark", {}, target_type="landmark")
        assert edit.action == "demote_landmark"

    def test_annotate_payload_valid(self):
        edit = _make_edit(
            "annotate",
            {"annotation_text": "Cross-domain insight"},
            target_type="band",
        )
        assert edit.payload["annotation_text"] == "Cross-domain insight"


# ===========================================================================
# 2. GraphVisualEdit schema — invalid payloads
# ===========================================================================

class TestGraphVisualEditInvalid:
    """Tests for invalid GraphVisualEdit payloads that must raise ValidationError."""

    def test_pin_position_missing_y_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            _make_edit("pin_position", {"x": 10.0})  # missing 'y'
        assert "pin_position" in str(exc_info.value)

    def test_override_weight_missing_weight_raises(self):
        with pytest.raises(ValidationError):
            _make_edit("override_fused_weight", {})

    def test_add_label_missing_label_text_raises(self):
        with pytest.raises(ValidationError):
            _make_edit("add_label", {})

    def test_promote_landmark_missing_label_raises(self):
        with pytest.raises(ValidationError):
            _make_edit("promote_landmark", {})

    def test_merge_nodes_missing_ids_raises(self):
        with pytest.raises(ValidationError):
            _make_edit("merge_nodes", {})

    def test_rationale_too_short_raises(self):
        with pytest.raises(ValidationError):
            GraphVisualEdit(
                target_type="node",
                target_id="n1",
                action="hide",
                payload={},
                rationale="short",  # < 10 chars
                expert_id="exp1",
            )

    def test_target_id_empty_raises(self):
        with pytest.raises(ValidationError):
            GraphVisualEdit(
                target_type="node",
                target_id="",  # empty
                action="show",
                payload={},
                rationale="Valid rationale here",
                expert_id="exp1",
            )

    def test_expert_id_invalid_chars_raises(self):
        with pytest.raises(ValidationError):
            GraphVisualEdit(
                target_type="node",
                target_id="n1",
                action="show",
                payload={},
                rationale="Valid rationale here",
                expert_id="invalid expert id!",  # spaces + '!' not allowed
            )


# ===========================================================================
# 3. ULID + optimistic locking
# ===========================================================================

class TestULIDAndVersioning:
    """Tests for ULID uniqueness and optimistic lock version field."""

    def test_edit_ulid_auto_generated(self):
        edit = _make_edit("show", {})
        assert len(edit.edit_id) == 26

    def test_edit_ulid_unique_per_instance(self):
        e1 = _make_edit("show", {})
        e2 = _make_edit("hide", {})
        assert e1.edit_id != e2.edit_id

    def test_edit_version_default_one(self):
        edit = _make_edit("show", {})
        assert edit.version == 1

    def test_edit_version_custom(self):
        edit = _make_edit("show", {}, version=5)
        assert edit.version == 5

    def test_edit_version_zero_raises(self):
        with pytest.raises(ValidationError):
            _make_edit("show", {}, version=0)


# ===========================================================================
# 4. GraphSearchQuery schema
# ===========================================================================

class TestGraphSearchQuery:
    """Tests for GraphSearchQuery schema."""

    def test_semantic_query_valid(self):
        q = GraphSearchQuery(
            query_type="semantic",
            query_text="graph neural networks",
        )
        assert q.query_type == "semantic"
        assert q.top_k == 50  # default

    def test_filters_default_empty(self):
        q = GraphSearchQuery(query_type="cite")
        assert q.filters == {}

    def test_top_k_default(self):
        q = GraphSearchQuery(query_type="bottleneck")
        assert q.top_k == 50

    def test_top_k_max_500(self):
        q = GraphSearchQuery(query_type="field", top_k=500)
        assert q.top_k == 500

    def test_top_k_above_500_raises(self):
        with pytest.raises(ValidationError):
            GraphSearchQuery(query_type="field", top_k=501)

    def test_top_k_zero_raises(self):
        with pytest.raises(ValidationError):
            GraphSearchQuery(query_type="semantic", top_k=0)

    def test_query_ulid_auto_generated(self):
        q = GraphSearchQuery(query_type="topic")
        assert len(q.query_id) == 26

    def test_all_12_query_types_constructible(self):
        all_types = [
            "semantic", "cite", "topic", "novelty_range", "lifecycle",
            "field", "subfield", "domain", "landmark_proximity", "bottleneck",
            "meta_principle", "expert_edited",
        ]
        for qt in all_types:
            q = GraphSearchQuery(query_type=qt)
            assert q.query_type == qt


# ===========================================================================
# 5. FastAPI endpoint tests (V14B + RBAC)
# ===========================================================================

class TestEndpoints:
    """Tests for FastAPI V14B endpoints and RBAC enforcement."""

    @pytest.fixture(autouse=True)
    def _isolated_visual_db(self, tmp_path, monkeypatch):
        monkeypatch.setenv("V14B_DB_V14", str(tmp_path / "v14_pilot.sqlite3"))

    # --- POST /graph/visual/edit ---

    def test_endpoint_edit_accepts_expert_role(self):
        payload = {
            "target_type": "node",
            "target_id": "node-001",
            "action": "hide",
            "payload": {},
            "rationale": "Expert rationale for test endpoint call",
            "expert_id": "expert_test",
        }
        resp = client.post("/graph/visual/edit", json=payload, headers=EXPERT_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["accepted"] is True

    def test_endpoint_edit_accepts_admin_role(self):
        payload = {
            "target_type": "node",
            "target_id": "node-001",
            "action": "show",
            "payload": {},
            "rationale": "Admin override for test endpoint call",
            "expert_id": "admin_test",
        }
        resp = client.post("/graph/visual/edit", json=payload, headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["edit"]["expert_id"] == "admin_test"

    def test_endpoint_edit_rejects_viewer_role(self):
        """Viewer cannot call expert-only /edit endpoint → 403."""
        payload = {
            "target_type": "node",
            "target_id": "node-001",
            "action": "hide",
            "payload": {},
            "rationale": "Viewer attempting expert action",
            "expert_id": "viewer_test",
        }
        resp = client.post("/graph/visual/edit", json=payload, headers=VIEWER_HEADERS)
        assert resp.status_code == 403

    def test_endpoint_edit_rejects_no_auth(self):
        """Missing auth token → 401."""
        payload = {
            "target_type": "node",
            "target_id": "node-001",
            "action": "show",
            "payload": {},
            "rationale": "No auth test case rationale",
            "expert_id": "anon",
        }
        resp = client.post("/graph/visual/edit", json=payload, headers=NO_AUTH_HEADERS)
        assert resp.status_code in (401, 403)

    def test_endpoint_edit_response_contains_edit_id(self):
        """Accepted response must include edit_id."""
        payload = {
            "target_type": "node",
            "target_id": "node-001",
            "action": "show",
            "payload": {},
            "rationale": "Check response contains edit_id field",
            "expert_id": "expert_test",
        }
        resp = client.post("/graph/visual/edit", json=payload, headers=EXPERT_HEADERS)
        assert resp.status_code == 200
        assert "edit_id" in resp.json()["edit"]

    # --- POST /graph/visual/search ---

    def test_endpoint_search_returns_not_ready_with_viewer_role(self):
        payload = {
            "query_type": "semantic",
            "query_text": "test search",
        }
        resp = client.post("/graph/visual/search", json=payload, headers=VIEWER_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ready"] is False

    def test_endpoint_search_accepts_expert_role(self):
        payload = {"query_type": "bottleneck"}
        resp = client.post("/graph/visual/search", json=payload, headers=EXPERT_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["schema_version"].startswith("V14B")

    def test_endpoint_search_rejects_no_auth(self):
        payload = {"query_type": "semantic", "query_text": "test"}
        resp = client.post("/graph/visual/search", json=payload, headers=NO_AUTH_HEADERS)
        assert resp.status_code in (401, 403)

    def test_endpoint_search_response_contains_query_id(self):
        payload = {"query_type": "cite"}
        resp = client.post("/graph/visual/search", json=payload, headers=VIEWER_HEADERS)
        assert resp.status_code == 200
        assert "query_id" in resp.json()

    # --- GET /graph/visual/edits/{edit_id} ---

    def test_endpoint_get_edit_status_returns_not_found(self):
        resp = client.get("/graph/visual/edits/01ARZ3NDEKTSV4RRFFQ69G5FAV")
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_found"

    def test_endpoint_get_edit_status_includes_edit_id(self):
        eid = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
        resp = client.get(f"/graph/visual/edits/{eid}")
        assert resp.status_code == 200
        assert resp.json()["edit_id"] == eid

    # --- GET /graph/visual/edits/history/{expert_id} ---

    def test_endpoint_history_returns_empty_history(self):
        resp = client.get("/graph/visual/edits/history/expert_alice")
        assert resp.status_code == 200
        assert resp.json()["edits"] == []

    def test_endpoint_history_includes_expert_id(self):
        resp = client.get("/graph/visual/edits/history/expert_bob")
        assert resp.status_code == 200
        assert resp.json()["expert_id"] == "expert_bob"


# ===========================================================================
# 6. OpenAPI schema tests
# ===========================================================================

class TestOpenAPISchema:
    """Tests for OpenAPI schema completeness."""

    def test_openapi_schema_is_valid_json(self):
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert "paths" in schema

    def test_openapi_schema_includes_v13_routes(self):
        resp = client.get("/openapi.json")
        paths = resp.json()["paths"]
        assert "/graph/visual/edit" in paths
        assert "/graph/visual/search" in paths

    def test_openapi_schema_includes_get_routes(self):
        resp = client.get("/openapi.json")
        paths = resp.json()["paths"]
        # Check that edit status and history routes are present
        path_keys = list(paths.keys())
        edit_status_routes = [p for p in path_keys if "edits" in p and "{edit_id}" in p]
        history_routes = [p for p in path_keys if "history" in p]
        assert len(edit_status_routes) >= 1
        assert len(history_routes) >= 1

    def test_openapi_schema_tags_include_v14b(self):
        resp = client.get("/openapi.json")
        schema = resp.json()
        tags_in_paths = set()
        for path_item in schema["paths"].values():
            for op in path_item.values():
                if isinstance(op, dict) and "tags" in op:
                    tags_in_paths.update(op["tags"])
        assert "graph_visual_v14b" in tags_in_paths

    def test_router_registered_in_app(self):
        """Verify the graph_visual router is registered in the FastAPI app."""
        route_paths = [r.path for r in app.routes]
        assert "/graph/visual/edit" in route_paths
        assert "/graph/visual/search" in route_paths


# ===========================================================================
# 7. Example coverage tests
# ===========================================================================

class TestExampleCoverage:
    """Tests that all 11 edit actions and 12 query types have examples."""

    def test_all_11_edit_actions_have_examples(self):
        expected_actions = {
            "pin_position", "override_fused_weight", "override_color", "add_label",
            "merge_nodes", "split_node", "hide", "show", "promote_landmark",
            "demote_landmark", "annotate",
        }
        assert set(ALL_EDIT_ACTIONS) == expected_actions
        assert len(ALL_EDIT_ACTIONS) == 11

    def test_all_12_query_types_have_examples(self):
        expected_types = {
            "semantic", "cite", "topic", "novelty_range", "lifecycle",
            "field", "subfield", "domain", "landmark_proximity", "bottleneck",
            "meta_principle", "expert_edited",
        }
        assert set(ALL_QUERY_TYPES) == expected_types
        assert len(ALL_QUERY_TYPES) == 12

    def test_each_edit_example_has_required_fields(self):
        required_fields = {"target_type", "target_id", "action", "payload", "rationale", "expert_id"}
        for action, example in GRAPH_VISUAL_EDIT_EXAMPLES.items():
            val = example["value"]
            missing = required_fields - set(val.keys())
            assert not missing, f"action={action!r} example missing fields: {missing}"

    def test_each_query_example_has_query_type(self):
        for qt, example in GRAPH_SEARCH_QUERY_EXAMPLES.items():
            val = example["value"]
            assert "query_type" in val
            assert val["query_type"] == qt

    def test_edit_examples_are_valid_pydantic(self):
        """Each edit example value must parse as valid GraphVisualEdit."""
        for action, example in GRAPH_VISUAL_EDIT_EXAMPLES.items():
            val = dict(example["value"])
            # Replace placeholder ULID with a fresh one (edit_id is optional on create)
            val.pop("edit_id", None)
            val.pop("timestamp", None)
            edit = GraphVisualEdit(**val)
            assert edit.action == action

    def test_query_examples_are_valid_pydantic(self):
        """Each query example value must parse as valid GraphSearchQuery."""
        for qt, example in GRAPH_SEARCH_QUERY_EXAMPLES.items():
            val = dict(example["value"])
            val.pop("query_id", None)
            val.pop("timestamp", None)
            q = GraphSearchQuery(**val)
            assert q.query_type == qt

    def test_examples_json_serializable(self):
        """All examples must serialize to JSON without error."""
        all_examples = list(GRAPH_VISUAL_EDIT_EXAMPLES.values()) + list(
            GRAPH_SEARCH_QUERY_EXAMPLES.values()
        )
        for ex in all_examples:
            json_str = json.dumps(ex["value"])
            assert isinstance(json_str, str)


# ===========================================================================
# 8. GraphSearchResult schema
# ===========================================================================

class TestGraphSearchResult:
    """Tests for GraphSearchResult schema."""

    def test_search_result_default_schema_version(self):
        from echelon.core.ulid_utils import ulid_new
        result = GraphSearchResult(
            query_id=ulid_new(),
            hits=[],
            total_matches=0,
            elapsed_ms=5,
        )
        assert result.schema_version == "V13.0"

    def test_search_result_total_matches_non_negative(self):
        from echelon.core.ulid_utils import ulid_new
        with pytest.raises(ValidationError):
            GraphSearchResult(
                query_id=ulid_new(),
                hits=[],
                total_matches=-1,
                elapsed_ms=0,
            )
