"""
echelon/graph/discipline_colors.py
V13 动态学科着色体系
- 主色 = Field 一级学科 (26 个预定义)
- 亮度 = Subfield 二级学科 (同 Field 内按排序分配)
- 形状 = Domain 零级学科 (4 种)
"""

import colorsys
from typing import Optional

# V13 完整 26 Field 主色调色板
# 参考 V13 动态学科着色补丁 §2.2
FIELD_HUE_PALETTE: dict[str, str] = {
    # Physical Sciences (冷调: 蓝/紫/青)
    "Computer Science":                              "#1f77b4",  # 蓝
    "Engineering":                                   "#5d8fc7",  # 灰蓝
    "Materials Science":                             "#9467bd",  # 紫
    "Physics and Astronomy":                         "#17becf",  # 青
    "Chemistry":                                     "#aec7e8",  # 浅蓝
    "Mathematics":                                   "#c5b0d5",  # 浅紫
    "Earth and Planetary Sciences":                  "#6b8e23",  # 橄榄
    "Environmental Science":                         "#2ca02c",  # 绿
    "Energy":                                        "#bcbd22",  # 黄绿
    "Chemical Engineering":                          "#8c564b",  # 棕

    # Life Sciences (绿黄系)
    "Agricultural and Biological Sciences":          "#f7b801",  # 金黄
    "Biochemistry, Genetics and Molecular Biology":  "#90ee90",  # 浅绿
    "Neuroscience":                                  "#ffa07a",  # 淡橙
    "Immunology and Microbiology":                   "#ff7f0e",  # 橙
    "Pharmacology, Toxicology and Pharmaceutics":    "#ffbb78",  # 浅橙

    # Health Sciences (红粉系)
    "Medicine":                                      "#d62728",  # 红
    "Health Professions":                            "#ff9896",  # 浅红
    "Nursing":                                       "#e377c2",  # 粉紫
    "Dentistry":                                     "#f7b6d2",  # 浅粉
    "Veterinary":                                    "#c49c94",  # 棕粉

    # Social Sciences (橙紫系)
    "Social Sciences":                               "#ffa500",  # 橙
    "Arts and Humanities":                           "#dda0dd",  # 梅紫
    "Economics, Econometrics and Finance":           "#dec2bf",  # 浅棕
    "Business, Management and Accounting":           "#cab2d6",  # 浅紫
    "Psychology":                                    "#fd8d3c",  # 深橙
    "Decision Sciences":                             "#bdbdbd",  # 灰
}

# Domain 零级 → 节点形状
DOMAIN_SHAPES: dict[str, str] = {
    "Physical Sciences":  "circle",    # 圆
    "Life Sciences":      "square",    # 方
    "Health Sciences":    "triangle",  # 三角
    "Social Sciences":    "diamond",   # 菱形
}

# Field → Domain 映射 (OpenAlex 官方分层)
FIELD_TO_DOMAIN: dict[str, str] = {
    "Computer Science":                              "Physical Sciences",
    "Engineering":                                   "Physical Sciences",
    "Materials Science":                             "Physical Sciences",
    "Physics and Astronomy":                         "Physical Sciences",
    "Chemistry":                                     "Physical Sciences",
    "Mathematics":                                   "Physical Sciences",
    "Earth and Planetary Sciences":                  "Physical Sciences",
    "Environmental Science":                         "Physical Sciences",
    "Energy":                                        "Physical Sciences",
    "Chemical Engineering":                          "Physical Sciences",
    "Agricultural and Biological Sciences":          "Life Sciences",
    "Biochemistry, Genetics and Molecular Biology":  "Life Sciences",
    "Neuroscience":                                  "Life Sciences",
    "Immunology and Microbiology":                   "Life Sciences",
    "Pharmacology, Toxicology and Pharmaceutics":    "Life Sciences",
    "Medicine":                                      "Health Sciences",
    "Health Professions":                            "Health Sciences",
    "Nursing":                                       "Health Sciences",
    "Dentistry":                                     "Health Sciences",
    "Veterinary":                                    "Health Sciences",
    "Social Sciences":                               "Social Sciences",
    "Arts and Humanities":                           "Social Sciences",
    "Economics, Econometrics and Finance":           "Social Sciences",
    "Business, Management and Accounting":           "Social Sciences",
    "Psychology":                                    "Social Sciences",
    "Decision Sciences":                             "Social Sciences",
}

UNKNOWN_COLOR = "#7f7f7f"   # 未知/未分类 → 灰色
UNKNOWN_SHAPE = "circle"


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    """#rrggbb → (r, g, b) in [0, 1]"""
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore


def _rgb_to_hex(r: float, g: float, b: float) -> str:
    """(r, g, b) in [0, 1] → #rrggbb"""
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


def get_field_color(field_name: str) -> str:
    """返回 Field 一级学科主色 hex。未知返回灰色。"""
    return FIELD_HUE_PALETTE.get(field_name, UNKNOWN_COLOR)


def get_node_color(
    field_name: str,
    subfield_name: str,
    all_subfields_in_field: list[str],
) -> str:
    """
    主色由 Field 决定,亮度由 Subfield 在该 Field 中的排序位置决定。
    亮度范围: [0.45, 0.85] (V 通道, HSV 色彩空间)
    """
    base_hex = FIELD_HUE_PALETTE.get(field_name, UNKNOWN_COLOR)
    r, g, b = _hex_to_rgb(base_hex)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)

    sorted_subs = sorted(set(all_subfields_in_field))
    n_subs = max(len(sorted_subs), 1)
    try:
        idx = sorted_subs.index(subfield_name)
    except ValueError:
        idx = 0

    # 亮度在 [0.45, 0.85] 均匀分配
    v_adjusted = 0.45 + (0.40 * idx / max(n_subs - 1, 1)) if n_subs > 1 else 0.65

    r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v_adjusted)
    return _rgb_to_hex(r2, g2, b2)


def get_node_shape(domain_name: str) -> str:
    """返回 Domain 零级学科对应的节点形状。未知返回圆形。"""
    return DOMAIN_SHAPES.get(domain_name, UNKNOWN_SHAPE)


def get_domain_from_field(field_name: str) -> str:
    """从 Field 名查 Domain 名。"""
    return FIELD_TO_DOMAIN.get(field_name, "Physical Sciences")


def build_color_map_for_papers(papers: list[dict]) -> dict[str, dict]:
    """
    批量为论文列表计算颜色/形状信息。
    papers 中每篇需含 field_name, subfield_name。
    返回 {paper_id: {color, shape, domain, field, subfield}}
    """
    # 先收集每个 field 下所有 subfield
    field_subfields: dict[str, list[str]] = {}
    for p in papers:
        fn = p.get("field_name", "")
        sn = p.get("subfield_name", "")
        if fn:
            field_subfields.setdefault(fn, [])
            if sn:
                field_subfields[fn].append(sn)

    result = {}
    for p in papers:
        pid = p.get("openalex_id") or p.get("paper_id") or p.get("id", "")
        fn = p.get("field_name", "")
        sn = p.get("subfield_name", "")
        domain = get_domain_from_field(fn)

        subfields_in_field = field_subfields.get(fn, [])
        color = get_node_color(fn, sn, subfields_in_field)
        shape = get_node_shape(domain)

        result[pid] = {
            "color":    color,
            "shape":    shape,
            "domain":   domain,
            "field":    fn,
            "subfield": sn,
        }
    return result
