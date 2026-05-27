"""
echelon.api.graph_visual_openapi_examples
==========================================
[V13 预埋] OpenAPI 文档示例数据。

提供:
  - 11 种 GraphVisualEdit action 的完整 example payload
  - 12 种 GraphSearchQuery query_type 的完整 example payload

各示例均为可直接 POST 的合法 JSON,可用于 Swagger UI "Try it out"。

参考: V13 系统级方案 §4 接口预埋
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Stub ULID values for examples (deterministic, not real-time)
# ---------------------------------------------------------------------------
_EXAMPLE_EDIT_ID = "01HPEXAMPLEEDITID001234"  # 23 chars placeholder — padded below
# Use valid 26-char Crockford base32 ULIDs in examples
_EDIT_ULID   = "01HPEX0000000EDITID00001"   # will be replaced with real values
_QUERY_ULID  = "01HPEX0000000QUERYID0001"

# Use actual valid ULIDs
_E = "01ARZ3NDEKTSV4RRFFQ69G5FAV"   # 26-char placeholder
_Q = "01ARZ3NDEKTSV4RRFFQ69G5FAW"   # 26-char placeholder
_TS = "2025-06-01T12:00:00"


# ===========================================================================
# GraphVisualEdit examples  (11 actions × 1 example each)
# ===========================================================================

GRAPH_VISUAL_EDIT_EXAMPLES: dict[str, dict[str, Any]] = {

    "pin_position": {
        "summary": "固定节点位置",
        "description": "将 paper-01ARY 节点固定在画布坐标 (120.5, -45.0)",
        "value": {
            "edit_id": _E,
            "target_type": "node",
            "target_id": "paper-01ARY",
            "action": "pin_position",
            "payload": {"x": 120.5, "y": -45.0},
            "rationale": "Expert repositioned node to align with cluster centroid for readability",
            "expert_id": "expert_alice",
            "timestamp": _TS,
            "version": 1,
        },
    },

    "override_fused_weight": {
        "summary": "覆盖融合边权重",
        "description": "将两节点间融合权重由算法值覆盖为 0.85",
        "value": {
            "edit_id": _E,
            "target_type": "edge",
            "target_id": "edge-01ARY-01ARZ",
            "action": "override_fused_weight",
            "payload": {"weight": 0.85},
            "rationale": "Algorithm underestimated co-authorship strength; domain expert correction",
            "expert_id": "expert_bob",
            "timestamp": _TS,
            "version": 2,
        },
    },

    "override_color": {
        "summary": "覆盖节点/边颜色",
        "description": "将地标节点高亮为红色以标记争议性成果",
        "value": {
            "edit_id": _E,
            "target_type": "landmark",
            "target_id": "landmark-attention",
            "action": "override_color",
            "payload": {"hex_color": "#FF4444"},
            "rationale": "Mark this landmark as controversial — three replication failures identified",
            "expert_id": "expert_carol",
            "timestamp": _TS,
            "version": 1,
        },
    },

    "add_label": {
        "summary": "添加自定义标签",
        "description": "为 halo 区域添加中文领域标签",
        "value": {
            "edit_id": _E,
            "target_type": "halo",
            "target_id": "halo-nlp-2020",
            "action": "add_label",
            "payload": {"label_text": "预训练语言模型爆发期"},
            "rationale": "Manual label clarifies thematic cluster for reviewers unfamiliar with field",
            "expert_id": "expert_alice",
            "timestamp": _TS,
            "version": 1,
        },
    },

    "merge_nodes": {
        "summary": "合并两个节点",
        "description": "将重复收录的两篇同文论文节点合并",
        "value": {
            "edit_id": _E,
            "target_type": "node",
            "target_id": "paper-01ARY",
            "action": "merge_nodes",
            "payload": {"merge_target_ids": ["paper-01ARY", "paper-01ARZ"]},
            "rationale": "Duplicate ingestion detected: arXiv v1 and journal version indexed separately",
            "expert_id": "expert_bob",
            "timestamp": _TS,
            "version": 1,
        },
    },

    "split_node": {
        "summary": "拆分节点",
        "description": "将一篇综述论文拆分为两个独立子主题节点",
        "value": {
            "edit_id": _E,
            "target_type": "node",
            "target_id": "paper-survey-01ARY",
            "action": "split_node",
            "payload": {"split_into_ids": ["paper-survey-01ARY-a", "paper-survey-01ARY-b"]},
            "rationale": "Survey covers two distinct research threads that mislead proximity metrics",
            "expert_id": "expert_carol",
            "timestamp": _TS,
            "version": 3,
        },
    },

    "hide": {
        "summary": "隐藏对象",
        "description": "隐藏噪声注释节点,不影响底层数据",
        "value": {
            "edit_id": _E,
            "target_type": "annotation",
            "target_id": "annotation-noise-001",
            "action": "hide",
            "payload": {},
            "rationale": "Annotation was auto-generated with low confidence; hiding for cleaner visualization",
            "expert_id": "expert_alice",
            "timestamp": _TS,
            "version": 1,
        },
    },

    "show": {
        "summary": "显示对象",
        "description": "重新显示之前被隐藏的边",
        "value": {
            "edit_id": _E,
            "target_type": "edge",
            "target_id": "edge-01ARY-01ARW",
            "action": "show",
            "payload": {},
            "rationale": "Re-reveal edge after verification showed connection is semantically valid",
            "expert_id": "expert_bob",
            "timestamp": _TS,
            "version": 2,
        },
    },

    "promote_landmark": {
        "summary": "晋升为地标节点",
        "description": "将普通节点晋升为领域地标,附加中文简称",
        "value": {
            "edit_id": _E,
            "target_type": "node",
            "target_id": "paper-transformer-2017",
            "action": "promote_landmark",
            "payload": {"short_label_zh": "Transformer 原始论文"},
            "rationale": "This paper is foundational with 80k+ citations and deserves landmark status",
            "expert_id": "expert_carol",
            "timestamp": _TS,
            "version": 1,
        },
    },

    "demote_landmark": {
        "summary": "降级地标节点",
        "description": "将误标为地标的节点降级回普通节点",
        "value": {
            "edit_id": _E,
            "target_type": "landmark",
            "target_id": "landmark-retracted-paper",
            "action": "demote_landmark",
            "payload": {},
            "rationale": "Paper was retracted in 2024; should not retain landmark status",
            "expert_id": "expert_alice",
            "timestamp": _TS,
            "version": 1,
        },
    },

    "annotate": {
        "summary": "添加专家注释",
        "description": "为 band 带区域添加跨领域洞察注释",
        "value": {
            "edit_id": _E,
            "target_type": "band",
            "target_id": "band-cv-nlp-2022",
            "action": "annotate",
            "payload": {"annotation_text": "This band represents the CV-NLP convergence driven by ViT and CLIP"},
            "rationale": "Expert annotation documents interdisciplinary significance for downstream reviewers",
            "expert_id": "expert_bob",
            "timestamp": _TS,
            "version": 1,
        },
    },
}


# ===========================================================================
# GraphSearchQuery examples  (12 query_types × 1 example each)
# ===========================================================================

GRAPH_SEARCH_QUERY_EXAMPLES: dict[str, dict[str, Any]] = {

    "semantic": {
        "summary": "语义相似性检索",
        "description": "用自然语言查询找语义相近的论文节点",
        "value": {
            "query_id": _Q,
            "query_type": "semantic",
            "query_text": "scalable graph neural network training with sparse attention",
            "filters": {"year_from": 2020, "min_citations": 5},
            "top_k": 20,
            "expert_id": "expert_alice",
            "timestamp": _TS,
        },
    },

    "cite": {
        "summary": "引用关系检索",
        "description": "查找引用或被引用指定论文的节点",
        "value": {
            "query_id": _Q,
            "query_type": "cite",
            "query_text": None,
            "filters": {
                "source_paper_id": "paper-transformer-2017",
                "direction": "cited_by",
                "depth": 2,
            },
            "top_k": 50,
            "expert_id": None,
            "timestamp": _TS,
        },
    },

    "topic": {
        "summary": "主题模型检索",
        "description": "按 LDA/BERTopic 主题词检索论文群",
        "value": {
            "query_id": _Q,
            "query_type": "topic",
            "query_text": "diffusion model image synthesis",
            "filters": {"topic_coherence_min": 0.6},
            "top_k": 30,
            "expert_id": "expert_carol",
            "timestamp": _TS,
        },
    },

    "novelty_range": {
        "summary": "新颖度区间检索",
        "description": "检索新颖度得分在指定区间内的论文",
        "value": {
            "query_id": _Q,
            "query_type": "novelty_range",
            "query_text": None,
            "filters": {"novelty_min": 0.7, "novelty_max": 1.0, "year_from": 2022},
            "top_k": 25,
            "expert_id": None,
            "timestamp": _TS,
        },
    },

    "lifecycle": {
        "summary": "生命周期阶段检索",
        "description": "检索处于指定生命周期阶段的研究节点",
        "value": {
            "query_id": _Q,
            "query_type": "lifecycle",
            "query_text": None,
            "filters": {"lifecycle_stage": "emerging", "min_velocity": 0.3},
            "top_k": 40,
            "expert_id": "expert_alice",
            "timestamp": _TS,
        },
    },

    "field": {
        "summary": "一级学科检索",
        "description": "在指定一级学科范围内检索",
        "value": {
            "query_id": _Q,
            "query_type": "field",
            "query_text": "representation learning",
            "filters": {"field": "Computer Science", "year_from": 2018},
            "top_k": 50,
            "expert_id": None,
            "timestamp": _TS,
        },
    },

    "subfield": {
        "summary": "二级子领域检索",
        "description": "在指定子领域范围内检索",
        "value": {
            "query_id": _Q,
            "query_type": "subfield",
            "query_text": "contrastive learning",
            "filters": {"subfield": "Self-Supervised Learning"},
            "top_k": 30,
            "expert_id": "expert_bob",
            "timestamp": _TS,
        },
    },

    "domain": {
        "summary": "跨领域域检索",
        "description": "在指定应用领域检索",
        "value": {
            "query_id": _Q,
            "query_type": "domain",
            "query_text": None,
            "filters": {"domain": "medical_imaging", "modality": "MRI"},
            "top_k": 20,
            "expert_id": None,
            "timestamp": _TS,
        },
    },

    "landmark_proximity": {
        "summary": "地标邻近度检索",
        "description": "检索与指定地标节点在图谱上邻近的节点",
        "value": {
            "query_id": _Q,
            "query_type": "landmark_proximity",
            "query_text": None,
            "filters": {
                "landmark_id": "landmark-attention",
                "max_hops": 2,
                "min_edge_weight": 0.4,
            },
            "top_k": 30,
            "expert_id": "expert_carol",
            "timestamp": _TS,
        },
    },

    "bottleneck": {
        "summary": "瓶颈节点检索",
        "description": "检索图谱中具有高介数中心性的瓶颈节点",
        "value": {
            "query_id": _Q,
            "query_type": "bottleneck",
            "query_text": None,
            "filters": {"betweenness_percentile_min": 0.9, "subgraph": "nlp-2020-2024"},
            "top_k": 10,
            "expert_id": None,
            "timestamp": _TS,
        },
    },

    "meta_principle": {
        "summary": "元原理检索",
        "description": "检索符合指定元原理(如 scaling law)的研究",
        "value": {
            "query_id": _Q,
            "query_type": "meta_principle",
            "query_text": "scaling law emergent ability",
            "filters": {"principle_category": "scaling", "confidence_min": 0.8},
            "top_k": 15,
            "expert_id": "expert_alice",
            "timestamp": _TS,
        },
    },

    "expert_edited": {
        "summary": "专家编辑过滤检索",
        "description": "仅检索经过专家可视化编辑的节点/边",
        "value": {
            "query_id": _Q,
            "query_type": "expert_edited",
            "query_text": None,
            "filters": {
                "action_types": ["promote_landmark", "override_fused_weight"],
                "expert_id": "expert_alice",
                "since": "2025-01-01T00:00:00",
            },
            "top_k": 50,
            "expert_id": "expert_alice",
            "timestamp": _TS,
        },
    },
}


# ---------------------------------------------------------------------------
# Convenience: flat list exports (for tests)
# ---------------------------------------------------------------------------

ALL_EDIT_ACTIONS: list[str] = list(GRAPH_VISUAL_EDIT_EXAMPLES.keys())
ALL_QUERY_TYPES: list[str] = list(GRAPH_SEARCH_QUERY_EXAMPLES.keys())

assert len(ALL_EDIT_ACTIONS) == 11, f"Expected 11 edit actions, got {len(ALL_EDIT_ACTIONS)}"
assert len(ALL_QUERY_TYPES) == 12, f"Expected 12 query types, got {len(ALL_QUERY_TYPES)}"
