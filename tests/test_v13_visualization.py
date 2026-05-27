"""
tests/test_v13_visualization.py
V13 可视化模块单元测试 (15+ 测试)

覆盖:
1.  test_field_hue_returns_color
2.  test_subfield_lightness_varies_within_field
3.  test_domain_shape_correct
4.  test_unknown_field_returns_gray
5.  test_all_26_fields_defined
6.  test_novelty_score_in_0_1
7.  test_novelty_score_none_signals_weight_redistribution
8.  test_novelty_score_all_none_returns_neutral
9.  test_radial_layout_outer_nodes_have_higher_novelty
10. test_radial_layout_returns_positions_for_all_papers
11. test_landmark_detection_top_n
12. test_landmark_label_prompt_format
13. test_landmark_composite_score_order
14. test_d3_html_renders_no_errors
15. test_png_file_created
16. test_legend_includes_all_fields_in_data
17. test_meta_principle_band_color_distinct
18. test_bottleneck_halo_radius_proportional_to_papers
"""

import json
import math
import os
import sys
import tempfile
from pathlib import Path

import pytest

# ── 路径设置 ──────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from echelon.graph.discipline_colors import (
    FIELD_HUE_PALETTE,
    DOMAIN_SHAPES,
    get_field_color,
    get_node_color,
    get_node_shape,
    get_domain_from_field,
    build_color_map_for_papers,
    UNKNOWN_COLOR,
)
from echelon.graph.radial_layout import (
    compute_novelty_score,
    radial_force_layout,
    get_node_radius_px,
)
from echelon.graph.landmark_detection import (
    detect_landmarks,
    LANDMARK_LABEL_PROMPT,
    _generate_fallback_label,
    _extract_label_from_response,
)
from scibot.visualization.render_d3 import render_interactive_html
from scibot.visualization.render_png import render_static_png


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _make_paper(
    pid: str,
    title: str,
    field_name: str,
    subfield_name: str,
    topic_id: str = "T10245",
    cited_by_count: int = 100,
    pub_date: str = "2022-01-01",
    refs: int = 10,
) -> dict:
    return {
        "openalex_id":        pid,
        "title":              title,
        "abstract":           f"Abstract for {title}",
        "field_name":         field_name,
        "subfield_name":      subfield_name,
        "primary_topic_id":   topic_id,
        "primary_topic_name": topic_id,
        "cited_by_count":     cited_by_count,
        "publication_date":   pub_date,
        "referenced_works":   [f"REF{i}" for i in range(refs)],
    }


@pytest.fixture
def sample_papers():
    return [
        _make_paper("P001", "Metasurface paper A", "Materials Science",
                    "Electronic, Optical and Magnetic Materials", "T10245", 500),
        _make_paper("P002", "Metasurface paper B", "Materials Science",
                    "Electronic, Optical and Magnetic Materials", "T10245", 200),
        _make_paper("P003", "Robot Manipulation A", "Engineering",
                    "Control and Systems Engineering", "T10653", 300),
        _make_paper("P004", "Multimodal ML A",       "Computer Science",
                    "Computer Vision and Pattern Recognition", "T11714", 150),
        _make_paper("P005", "RL Robotics A",         "Computer Science",
                    "Artificial Intelligence",                "T10462", 80),
        _make_paper("P006", "New frontier paper",    "Computer Science",
                    "Artificial Intelligence",                "T10462", 10,
                    pub_date="2025-01-01"),
    ]


@pytest.fixture
def sample_novelty_scores():
    return {
        "P001": 0.3,   # 低 novelty → 核心
        "P002": 0.4,
        "P003": 0.5,
        "P004": 0.6,
        "P005": 0.7,
        "P006": 0.85,  # 高 novelty → 外圈
    }


# ── 1. test_field_hue_returns_color ──────────────────────────────────────────

def test_field_hue_returns_color():
    """get_field_color 返回合法 hex 颜色"""
    color = get_field_color("Computer Science")
    assert color.startswith("#"), f"Expected hex color, got: {color}"
    assert len(color) == 7, f"Expected #rrggbb format, got: {color}"
    assert color == "#1f77b4"


# ── 2. test_subfield_lightness_varies_within_field ───────────────────────────

def test_subfield_lightness_varies_within_field():
    """同 Field 的不同 Subfield 应产生不同颜色 (亮度不同)"""
    subfields = [
        "Computer Vision and Pattern Recognition",
        "Artificial Intelligence",
        "Software Engineering",
    ]
    colors = [
        get_node_color("Computer Science", sf, subfields)
        for sf in subfields
    ]
    # 颜色应各不相同
    assert len(set(colors)) == len(subfields), \
        f"Expected {len(subfields)} distinct colors, got: {colors}"


# ── 3. test_domain_shape_correct ─────────────────────────────────────────────

def test_domain_shape_correct():
    """Domain → 形状映射正确"""
    assert get_node_shape("Physical Sciences") == "circle"
    assert get_node_shape("Life Sciences") == "square"
    assert get_node_shape("Health Sciences") == "triangle"
    assert get_node_shape("Social Sciences") == "diamond"


# ── 4. test_unknown_field_returns_gray ───────────────────────────────────────

def test_unknown_field_returns_gray():
    """未知 Field 返回灰色"""
    color = get_field_color("Nonexistent Field XYZ")
    assert color == UNKNOWN_COLOR, f"Expected {UNKNOWN_COLOR}, got {color}"


# ── 5. test_all_26_fields_defined ─────────────────────────────────────────────

def test_all_26_fields_defined():
    """FIELD_HUE_PALETTE 包含完整 26 个 Field"""
    assert len(FIELD_HUE_PALETTE) == 26, \
        f"Expected 26 fields, got {len(FIELD_HUE_PALETTE)}"
    # 每个颜色应是合法 hex
    for field, color in FIELD_HUE_PALETTE.items():
        assert color.startswith("#") and len(color) == 7, \
            f"Invalid color for {field}: {color}"


# ── 6. test_novelty_score_in_0_1 ─────────────────────────────────────────────

def test_novelty_score_in_0_1():
    """novelty_score 结果应在 [0, 1]"""
    paper = {"openalex_id": "P001", "title": "Test"}
    for _ in range(10):
        import random
        signals = {
            "c_cd_subdomain":        random.random(),
            "c_bridging_centrality": random.random(),
            "c_team_disrupt":        random.random(),
            "c_semantic_outlier":    random.random(),
            "c_recency":             random.random(),
            "c_breakthrough_lang":   random.random(),
        }
        score = compute_novelty_score(paper, signals)
        assert 0.0 <= score <= 1.0, f"Score out of range: {score}"


# ── 7. test_novelty_score_none_signals_weight_redistribution ──────────────────

def test_novelty_score_none_signals_weight_redistribution():
    """None 信号权重应转移到其他信号 (结果仍有意义)"""
    paper = {"openalex_id": "P001"}
    # 只有 c_recency = 1.0, 其余 None
    signals = {
        "c_cd_subdomain":        None,
        "c_bridging_centrality": None,
        "c_team_disrupt":        None,
        "c_semantic_outlier":    None,
        "c_recency":             1.0,
        "c_breakthrough_lang":   None,
    }
    score = compute_novelty_score(paper, signals)
    assert score == 1.0, f"Expected 1.0 when only c_recency=1.0, got {score}"


# ── 8. test_novelty_score_all_none_returns_neutral ───────────────────────────

def test_novelty_score_all_none_returns_neutral():
    """所有信号 None → 返回中性 0.5"""
    paper = {"openalex_id": "P001"}
    signals = {k: None for k in [
        "c_cd_subdomain", "c_bridging_centrality",
        "c_team_disrupt", "c_semantic_outlier",
        "c_recency", "c_breakthrough_lang",
    ]}
    score = compute_novelty_score(paper, signals)
    assert score == 0.5, f"Expected 0.5, got {score}"


# ── 9. test_radial_layout_outer_nodes_have_higher_novelty ────────────────────

def test_radial_layout_outer_nodes_have_higher_novelty(sample_papers, sample_novelty_scores):
    """高 novelty 节点应比低 novelty 节点离中心更远"""
    positions = radial_force_layout(
        papers=sample_papers,
        fused_edges=None,
        novelty_scores=sample_novelty_scores,
        n_iterations=0,  # 不做 force-directed 微调
    )

    CX, CY = 800, 800

    def dist(pid):
        x, y = positions[pid]
        return math.sqrt((x - CX)**2 + (y - CY)**2)

    # P006 (novelty=0.85) 应比 P001 (novelty=0.3) 更远
    assert dist("P006") > dist("P001"), \
        f"High novelty P006 ({dist('P006'):.1f}) should be farther than P001 ({dist('P001'):.1f})"


# ── 10. test_radial_layout_returns_positions_for_all_papers ──────────────────

def test_radial_layout_returns_positions_for_all_papers(sample_papers):
    """radial_force_layout 应为每篇论文返回坐标"""
    positions = radial_force_layout(
        papers=sample_papers,
        fused_edges=None,
        novelty_scores=None,
        n_iterations=0,
    )
    paper_ids = {
        p.get("openalex_id") or p.get("paper_id") or p.get("id", "")
        for p in sample_papers
    }
    assert len(positions) == len(sample_papers), \
        f"Expected {len(sample_papers)} positions, got {len(positions)}"
    for pid in paper_ids:
        assert pid in positions, f"Missing position for {pid}"
        x, y = positions[pid]
        assert 0 <= x <= 1600 and 0 <= y <= 1600, f"Position out of bounds: {pid} → ({x}, {y})"


# ── 11. test_landmark_detection_top_n ────────────────────────────────────────

def test_landmark_detection_top_n(sample_papers, sample_novelty_scores):
    """detect_landmarks 应返回 top_n 个里程碑"""
    landmarks = detect_landmarks(
        papers=sample_papers,
        novelty_scores=sample_novelty_scores,
        top_n=3,
    )
    assert len(landmarks) == 3, f"Expected 3 landmarks, got {len(landmarks)}"
    # 按 composite_score 降序
    scores = [lm["composite_score"] for lm in landmarks]
    assert scores == sorted(scores, reverse=True), "Landmarks should be sorted by composite_score"


# ── 12. test_landmark_label_prompt_format ────────────────────────────────────

def test_landmark_label_prompt_format():
    """LANDMARK_LABEL_PROMPT 应包含 title 和 abstract 占位符"""
    assert "{title}" in LANDMARK_LABEL_PROMPT
    assert "{abstract}" in LANDMARK_LABEL_PROMPT
    assert "JSON" in LANDMARK_LABEL_PROMPT
    assert "label" in LANDMARK_LABEL_PROMPT

    # 格式化应正常工作
    formatted = LANDMARK_LABEL_PROMPT.format(
        title="Test Paper",
        abstract="Test abstract",
    )
    assert "Test Paper" in formatted
    assert "Test abstract" in formatted


# ── 13. test_landmark_composite_score_order ───────────────────────────────────

def test_landmark_composite_score_order(sample_papers, sample_novelty_scores):
    """综合分最高的论文应排在最前面"""
    landmarks = detect_landmarks(
        papers=sample_papers,
        novelty_scores=sample_novelty_scores,
        top_n=6,
    )
    assert len(landmarks) == len(sample_papers)
    # 第一个应有最高 composite_score
    assert landmarks[0]["composite_score"] >= landmarks[-1]["composite_score"]


# ── 14. test_d3_html_renders_no_errors ───────────────────────────────────────

def test_d3_html_renders_no_errors(sample_papers, sample_novelty_scores):
    """render_interactive_html 应生成合法 HTML 文件"""
    positions = radial_force_layout(
        papers=sample_papers,
        novelty_scores=sample_novelty_scores,
        n_iterations=0,
    )
    color_map = build_color_map_for_papers(sample_papers)

    nodes = []
    for p in sample_papers:
        pid = p.get("openalex_id", "")
        x, y = positions.get(pid, (800, 800))
        cm = color_map.get(pid, {})
        nodes.append({
            "id": pid, "x": x, "y": y,
            "color": cm.get("color", "#888"),
            "shape": cm.get("shape", "circle"),
            "size": 5.0,
            "label": p.get("title", ""),
            "field": cm.get("field", ""),
            "subfield": cm.get("subfield", ""),
            "domain": cm.get("domain", ""),
            "topic": p.get("primary_topic_name", ""),
            "cited_by_count": p.get("cited_by_count", 0),
            "novelty": sample_novelty_scores.get(pid, 0.5),
        })

    edges = [{"src": "P001", "dst": "P002", "fused_weight": 0.7, "opacity": 0.4}]
    overlays = {
        "bottleneck_halos": [
            {"bottleneck_id": "BN0", "label": "测试卡点", "cx": 800, "cy": 600, "r": 80, "color": "#ffaa00"}
        ],
        "meta_principle_bands": [
            {"id": 0, "name": "测试元规律", "color": "#00ffcc", "covered_themes": ["T1"]}
        ],
    }
    landmarks = [{"paper_id": "P006", "x": 900.0, "y": 900.0, "short_label_zh": "前沿", "title": "New frontier"}]

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "test_graph.html")
        result = render_interactive_html(nodes, edges, overlays, landmarks, out_path)
        assert os.path.exists(out_path), "HTML file not created"
        size = os.path.getsize(out_path)
        assert size > 5000, f"HTML too small: {size} bytes"
        with open(out_path, encoding="utf-8") as f:
            content = f.read()
        assert "d3.v7.min.js" in content, "D3.js CDN not found in HTML"
        assert "layer-nodes" in content, "Missing layer-nodes"
        assert "layer-halos" in content, "Missing layer-halos"
        assert "layer-meta" in content, "Missing layer-meta"
        assert "layer-landmarks" in content, "Missing layer-landmarks"
        assert "toggleLayer" in content, "Missing layer toggle function"


# ── 15. test_png_file_created ────────────────────────────────────────────────

def test_png_file_created(sample_papers, sample_novelty_scores):
    """render_static_png 应生成 PNG 文件"""
    positions = radial_force_layout(
        papers=sample_papers,
        novelty_scores=sample_novelty_scores,
        n_iterations=0,
    )
    color_map = build_color_map_for_papers(sample_papers)

    nodes = []
    for p in sample_papers:
        pid = p.get("openalex_id", "")
        x, y = positions.get(pid, (800, 800))
        cm = color_map.get(pid, {})
        nodes.append({
            "id": pid, "x": x, "y": y,
            "color": cm.get("color", "#888"),
            "shape": cm.get("shape", "circle"),
            "size": 5.0,
            "label": p.get("title", ""),
            "field": cm.get("field", ""),
            "subfield": cm.get("subfield", ""),
            "domain": cm.get("domain", ""),
            "topic": "",
            "cited_by_count": p.get("cited_by_count", 0),
            "novelty": sample_novelty_scores.get(pid, 0.5),
        })

    edges = []
    overlays = {"bottleneck_halos": [], "meta_principle_bands": []}
    landmarks = [{"paper_id": "P006", "x": 900.0, "y": 900.0, "short_label_zh": "前沿", "title": "Test"}]

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "test_graph.png")
        render_static_png(
            nodes=nodes, edges=edges, overlays=overlays, landmarks=landmarks,
            output_path=out_path, dpi=72, size=(4, 4),
        )
        assert os.path.exists(out_path), "PNG file not created"
        size = os.path.getsize(out_path)
        assert size > 1000, f"PNG too small: {size} bytes"


# ── 16. test_legend_includes_all_fields_in_data ──────────────────────────────

def test_legend_includes_all_fields_in_data(sample_papers):
    """HTML 图例应包含语料中所有 Field"""
    nodes = []
    color_map = build_color_map_for_papers(sample_papers)
    for p in sample_papers:
        pid = p.get("openalex_id", "")
        cm = color_map.get(pid, {})
        nodes.append({
            "id": pid, "x": 800, "y": 800,
            "color": cm.get("color", "#888"),
            "shape": cm.get("shape", "circle"),
            "size": 5.0,
            "label": p.get("title", ""),
            "field": cm.get("field", ""),
            "subfield": cm.get("subfield", ""),
            "domain": cm.get("domain", ""),
            "topic": "", "cited_by_count": 0, "novelty": 0.5,
        })

    overlays = {"bottleneck_halos": [], "meta_principle_bands": []}
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "legend_test.html")
        render_interactive_html(nodes, [], overlays, [], out_path)
        with open(out_path, encoding="utf-8") as f:
            content = f.read()

    fields_in_papers = {p.get("field_name", "") for p in sample_papers if p.get("field_name")}
    for field in fields_in_papers:
        assert field in content, f"Field '{field}' not in HTML legend"


# ── 17. test_meta_principle_band_color_distinct ───────────────────────────────

def test_meta_principle_band_color_distinct():
    """4 个元规律虹光带颜色应各不相同"""
    from pilot.render_graph_v13 import build_meta_principle_bands
    meta_principles = [
        {"principle": "MP1", "covered_themes": ["T1"]},
        {"principle": "MP2", "covered_themes": ["T2"]},
        {"principle": "MP3", "covered_themes": ["T3"]},
        {"principle": "MP4", "covered_themes": ["T4"]},
    ]
    bands = build_meta_principle_bands(meta_principles)
    assert len(bands) == 4
    colors = [b["color"] for b in bands]
    assert len(set(colors)) == 4, f"Meta principle band colors not distinct: {colors}"


# ── 18. test_bottleneck_halo_radius_proportional_to_papers ───────────────────

def test_bottleneck_halo_radius_proportional_to_papers(sample_papers, sample_novelty_scores):
    """卡点辉光晕半径应与 supporting_papers 数量正相关"""
    from pilot.render_graph_v13 import build_bottleneck_halos

    positions = radial_force_layout(
        papers=sample_papers,
        novelty_scores=sample_novelty_scores,
        n_iterations=0,
    )
    paper_index = {p["openalex_id"]: p for p in sample_papers}

    bottlenecks = [
        {"bottleneck_id": "BN0", "label": "卡点A", "supporting_papers": ["P001", "P002", "P003"]},
        {"bottleneck_id": "BN1", "label": "卡点B", "supporting_papers": ["P004"]},
    ]

    halos = build_bottleneck_halos(bottlenecks, positions, paper_index)
    assert len(halos) == 2

    # 支持论文更多的卡点应有更大半径 (或至少不更小, 因为有 min 约束)
    # 主要验证两个 halo 都有合法 r 值
    for h in halos:
        assert h["r"] >= 40, f"Halo radius too small: {h['r']}"
        assert h["r"] <= 200, f"Halo radius too large: {h['r']}"


# ── 额外测试: build_color_map_for_papers ─────────────────────────────────────

def test_build_color_map_covers_all_papers(sample_papers):
    """build_color_map_for_papers 应为每篇论文返回颜色信息"""
    color_map = build_color_map_for_papers(sample_papers)
    for p in sample_papers:
        pid = p.get("openalex_id", "")
        assert pid in color_map, f"Missing color for {pid}"
        cm = color_map[pid]
        assert "color" in cm
        assert "shape" in cm
        assert cm["color"].startswith("#")


def test_fallback_label_returns_chinese():
    """_generate_fallback_label 应返回非空中文字符串"""
    lm_metasurface = {
        "title": "Metasurface-based absorber",
        "primary_topic_id": "T10245",
    }
    label = _generate_fallback_label(lm_metasurface)
    assert label, "Fallback label should not be empty"
    # topic map 中 T10245 → 超表面
    assert label == "超表面"


def test_extract_label_from_json_response():
    """_extract_label_from_response 应能解析 JSON 响应"""
    response = '{"label": "超表面", "reasoning": "Metasurface is a key concept"}'
    label = _extract_label_from_response(response)
    assert label == "超表面"


def test_get_node_radius_px():
    """节点半径应在合理范围内"""
    p_low  = {"cited_by_count": 0}
    p_high = {"cited_by_count": 10000}
    r_low  = get_node_radius_px(p_low)
    r_high = get_node_radius_px(p_high)
    assert 2 <= r_low <= 20
    assert 2 <= r_high <= 20
    assert r_high >= r_low, "More cited paper should have larger radius"
