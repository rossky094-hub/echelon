"""
scibot/visualization/render_d3.py
V13 D3.js 交互式 HTML 渲染器

生成自包含 HTML (含 D3.js v7 from CDN):
- 黑色背景 (模仿 Nature 共引网络)
- 5 个图层开关 (Domains / Fields / Bottlenecks / MetaPrinciples / Landmarks)
- 卡点辉光晕 (bottleneck_halos)
- 元规律虹光带 (meta_principle_bands)
- 节点悬停 tooltip
- 图例自动生成
- 里程碑中文标签
"""

import json
import os
from typing import Optional


def render_interactive_html(
    nodes: list[dict],
    edges: list[dict],
    overlays: dict,
    landmarks: list[dict],
    output_path: str,
) -> str:
    """
    生成自包含 D3.js HTML 可视化。

    Parameters
    ----------
    nodes        : list of {id, x, y, color, shape, size, label,
                             field, subfield, domain, topic, cited_by_count, novelty}
    edges        : list of {src, dst, fused_weight, opacity}
    overlays     : {
                     "bottleneck_halos": [{bottleneck_id, label, cx, cy, r, color}],
                     "meta_principle_bands": [{id, name, color, cluster_ids}]
                   }
    landmarks    : list of {paper_id, x, y, short_label_zh, composite_score, title}
    output_path  : 输出文件路径

    Returns
    -------
    output_path  (写入成功后返回)
    """
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    # 收集图例数据
    fields_in_data: dict[str, str] = {}  # field_name → color
    subfields_in_data: dict[str, str] = {}
    domains_in_data: set[str] = set()

    for n in nodes:
        if n.get("field"):
            fields_in_data[n["field"]] = n.get("color", "#7f7f7f")
        if n.get("subfield"):
            subfields_in_data[n["subfield"]] = n.get("color", "#7f7f7f")
        if n.get("domain"):
            domains_in_data.add(n["domain"])

    domain_shape_map = {
        "Physical Sciences":  "●",
        "Life Sciences":      "■",
        "Health Sciences":    "▲",
        "Social Sciences":    "◆",
    }

    # 序列化数据
    nodes_json = json.dumps(nodes, ensure_ascii=False)
    edges_json = json.dumps(edges, ensure_ascii=False)
    bottleneck_halos = overlays.get("bottleneck_halos", [])
    meta_bands = overlays.get("meta_principle_bands", [])
    halos_json = json.dumps(bottleneck_halos, ensure_ascii=False)
    meta_json = json.dumps(meta_bands, ensure_ascii=False)
    landmarks_json = json.dumps(landmarks, ensure_ascii=False)

    # 图例 HTML
    domain_legend_html = "\n".join(
        f'<div class="legend-item"><span style="color:#fff">{domain_shape_map.get(d,"●")}</span>'
        f' <span>{d}</span></div>'
        for d in sorted(domains_in_data)
    )
    field_legend_html = "\n".join(
        f'<div class="legend-item"><span class="legend-dot" style="background:{c}"></span>'
        f' <span>{f}</span></div>'
        for f, c in sorted(fields_in_data.items())
    )
    subfield_legend_html = "\n".join(
        f'<div class="legend-item"><span class="legend-dot" style="background:{c};opacity:0.7"></span>'
        f' <span style="font-size:11px">{s}</span></div>'
        for s, c in sorted(subfields_in_data.items())
    )

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Echelon V13 — Nature风格知识图谱</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0a0a0f; color: #e8e8e8; font-family: 'Helvetica Neue', Arial, sans-serif; overflow: hidden; }}
  #main {{ display: flex; width: 100vw; height: 100vh; }}
  #chart-container {{ flex: 1; position: relative; }}
  svg {{ width: 100%; height: 100%; }}
  #sidebar {{ width: 260px; background: #0d0d15; border-left: 1px solid #222; padding: 16px; overflow-y: auto; }}
  h1 {{ font-size: 14px; font-weight: 600; color: #aaa; margin-bottom: 16px; letter-spacing: 0.5px; }}
  h2 {{ font-size: 12px; color: #888; margin: 12px 0 6px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .layer-btn {{ display: block; width: 100%; background: #1a1a2e; border: 1px solid #333; color: #ccc;
                padding: 6px 10px; margin: 3px 0; border-radius: 4px; cursor: pointer; font-size: 12px;
                text-align: left; transition: all 0.2s; }}
  .layer-btn.active {{ background: #2a2a4e; border-color: #556; color: #eee; }}
  .layer-btn:hover {{ background: #222240; }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; margin: 3px 0; font-size: 12px; color: #bbb; }}
  .legend-dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
  .tooltip {{ position: absolute; background: rgba(10,10,20,0.92); border: 1px solid #444;
              padding: 10px 14px; border-radius: 6px; font-size: 12px; line-height: 1.6;
              max-width: 300px; pointer-events: none; z-index: 100; color: #ddd; }}
  .tooltip b {{ color: #fff; }}
  .landmark-label {{ font-size: 13px; font-weight: bold; fill: #ffe066; pointer-events: none;
                     text-shadow: 0 0 8px #ffe066; font-family: "PingFang SC", "Microsoft YaHei", sans-serif; }}
  #stats {{ font-size: 11px; color: #666; margin-top: 16px; border-top: 1px solid #222; padding-top: 12px; }}
</style>
</head>
<body>
<div id="main">
  <div id="chart-container">
    <svg id="chart"></svg>
    <div class="tooltip" id="tooltip" style="display:none"></div>
  </div>
  <div id="sidebar">
    <h1>Echelon V13 知识图谱</h1>

    <h2>图层开关</h2>
    <button class="layer-btn active" id="btn-nodes"     onclick="toggleLayer('nodes')">● 论文节点</button>
    <button class="layer-btn active" id="btn-edges"     onclick="toggleLayer('edges')">─ 融合边</button>
    <button class="layer-btn active" id="btn-halos"     onclick="toggleLayer('halos')">◎ 卡点辉光晕</button>
    <button class="layer-btn active" id="btn-meta"      onclick="toggleLayer('meta')">≋ 元规律虹光带</button>
    <button class="layer-btn active" id="btn-landmarks" onclick="toggleLayer('landmarks')">★ 里程碑标签</button>

    <h2>Domain</h2>
    {domain_legend_html}

    <h2>Field</h2>
    {field_legend_html}

    <h2>Subfield</h2>
    {subfield_legend_html}

    <h2>节点大小</h2>
    <div class="legend-item"><span style="font-size:11px;color:#888">= log(1 + cited_by_count)</span></div>

    <h2>径向距离</h2>
    <div class="legend-item"><span style="font-size:11px;color:#888">外圈 = 颠覆性前沿 (novelty↑)</span></div>
    <div class="legend-item"><span style="font-size:11px;color:#888">内圈 = 已知核心 (cited↑)</span></div>

    <div id="stats">
      <div>节点: {len(nodes)}</div>
      <div>边: {len(edges)}</div>
      <div>卡点: {len(bottleneck_halos)}</div>
      <div>里程碑: {len(landmarks)}</div>
    </div>
  </div>
</div>

<script>
const WIDTH  = document.getElementById('chart-container').offsetWidth  || 1200;
const HEIGHT = document.getElementById('chart-container').offsetHeight || 900;

// ── 数据 ─────────────────────────────────────────────────────────────────────
const nodesData      = {nodes_json};
const edgesData      = {edges_json};
const bottleneckData = {halos_json};
const metaData       = {meta_json};
const landmarkData   = {landmarks_json};

// ── SVG 主画布 ────────────────────────────────────────────────────────────────
const svg = d3.select('#chart')
  .attr('width', WIDTH)
  .attr('height', HEIGHT);

// 背景
svg.append('rect').attr('width', WIDTH).attr('height', HEIGHT).attr('fill', '#080810');

// 缩放/平移
const zoom = d3.zoom().scaleExtent([0.1, 10])
  .on('zoom', (event) => {{ mainGroup.attr('transform', event.transform); }});
svg.call(zoom);

const mainGroup = svg.append('g').attr('id', 'main-group');

// 坐标变换: 将节点坐标从原始画布空间映射到当前 SVG 空间
const origW = 1600, origH = 1600;
const scaleX = WIDTH  / origW;
const scaleY = HEIGHT / origH;
const scale  = Math.min(scaleX, scaleY) * 0.85;
const offX   = (WIDTH  - origW * scale) / 2;
const offY   = (HEIGHT - origH * scale) / 2;

function tx(x) {{ return offX + x * scale; }}
function ty(y) {{ return offY + y * scale; }}

// ── SVG 滤镜 (辉光效果) ───────────────────────────────────────────────────────
const defs = svg.append('defs');

function makeGlow(id, color, stdDev) {{
  const filter = defs.append('filter').attr('id', id);
  filter.append('feGaussianBlur').attr('stdDeviation', stdDev).attr('result', 'blur');
  const merge = filter.append('feMerge');
  merge.append('feMergeNode').attr('in', 'blur');
  merge.append('feMergeNode').attr('in', 'SourceGraphic');
}}
makeGlow('glow-halo',     '#ffaa00', 8);
makeGlow('glow-meta',     '#00ffcc', 4);
makeGlow('glow-landmark', '#ffe066', 6);

// ── 图层组 ────────────────────────────────────────────────────────────────────
const layerEdges     = mainGroup.append('g').attr('id', 'layer-edges');
const layerHalos     = mainGroup.append('g').attr('id', 'layer-halos');
const layerMeta      = mainGroup.append('g').attr('id', 'layer-meta');
const layerNodes     = mainGroup.append('g').attr('id', 'layer-nodes');
const layerLandmarks = mainGroup.append('g').attr('id', 'layer-landmarks');

// ── 渲染: 边 ──────────────────────────────────────────────────────────────────
const nodeIndex = new Map(nodesData.map(n => [n.id, n]));

layerEdges.selectAll('line')
  .data(edgesData)
  .enter().append('line')
  .attr('x1', d => tx(nodeIndex.get(d.src)?.x ?? 800))
  .attr('y1', d => ty(nodeIndex.get(d.src)?.y ?? 800))
  .attr('x2', d => tx(nodeIndex.get(d.dst)?.x ?? 800))
  .attr('y2', d => ty(nodeIndex.get(d.dst)?.y ?? 800))
  .attr('stroke', '#334')
  .attr('stroke-width', d => Math.max(0.3, (d.fused_weight ?? 0.5) * 1.5))
  .attr('opacity', d => d.opacity ?? 0.3);

// ── 渲染: 卡点辉光晕 ───────────────────────────────────────────────────────────
layerHalos.selectAll('circle')
  .data(bottleneckData)
  .enter().append('circle')
  .attr('cx', d => tx(d.cx ?? 800))
  .attr('cy', d => ty(d.cy ?? 800))
  .attr('r',  d => (d.r ?? 60) * scale)
  .attr('fill', d => d.color ?? '#ffaa00')
  .attr('opacity', 0.12)
  .attr('filter', 'url(#glow-halo)');

// 卡点标签
layerHalos.selectAll('text')
  .data(bottleneckData)
  .enter().append('text')
  .attr('x', d => tx(d.cx ?? 800))
  .attr('y', d => ty((d.cy ?? 800) - (d.r ?? 60)) - 8)
  .attr('text-anchor', 'middle')
  .attr('fill', '#ffaa88')
  .attr('font-size', 10)
  .attr('opacity', 0.7)
  .text(d => d.label ? d.label.substring(0, 20) : '');

// ── 渲染: 元规律虹光带 ─────────────────────────────────────────────────────────
// 用圆弧连接 meta principle 覆盖的 cluster 中心
layerMeta.selectAll('.meta-arc')
  .data(metaData)
  .enter().append('ellipse')
  .attr('cx', (d, i) => tx(800 + Math.cos(i * Math.PI / 2) * 300))
  .attr('cy', (d, i) => ty(800 + Math.sin(i * Math.PI / 2) * 300))
  .attr('rx', 350 * scale)
  .attr('ry', 200 * scale)
  .attr('fill', 'none')
  .attr('stroke', d => d.color ?? '#00ffcc')
  .attr('stroke-width', 3)
  .attr('opacity', 0.25)
  .attr('filter', 'url(#glow-meta)')
  .attr('transform', (d, i) => `rotate(${{i * 45}}, ${{tx(800)}}, ${{ty(800)}})`);

// ── 渲染: 节点 ────────────────────────────────────────────────────────────────
const tooltip = document.getElementById('tooltip');

function showTooltip(event, d) {{
  tooltip.style.display = 'block';
  tooltip.style.left = (event.pageX + 12) + 'px';
  tooltip.style.top  = (event.pageY - 20) + 'px';
  tooltip.innerHTML = `
    <b>${{d.label || d.id}}</b><br>
    <span style="color:#888">Field:</span> ${{d.field || '—'}}<br>
    <span style="color:#888">Subfield:</span> ${{d.subfield || '—'}}<br>
    <span style="color:#888">Cited by:</span> ${{d.cited_by_count ?? 0}}<br>
    <span style="color:#888">Novelty:</span> ${{(d.novelty ?? 0.5).toFixed(3)}}<br>
    <span style="color:#888">Topic:</span> ${{d.topic || '—'}}
  `;
}}
function hideTooltip() {{ tooltip.style.display = 'none'; }}

// 绘制不同形状
function renderNode(sel) {{
  sel.each(function(d) {{
    const g = d3.select(this);
    const x = tx(d.x ?? 800), y = ty(d.y ?? 800);
    const r = Math.max(2, (d.size ?? 5) * scale);
    const shape = d.shape ?? 'circle';

    if (shape === 'circle') {{
      g.append('circle')
        .attr('cx', x).attr('cy', y).attr('r', r)
        .attr('fill', d.color ?? '#888').attr('opacity', 0.85)
        .on('mouseover', (e) => showTooltip(e, d))
        .on('mouseout', hideTooltip);
    }} else if (shape === 'square') {{
      g.append('rect')
        .attr('x', x - r).attr('y', y - r)
        .attr('width', r*2).attr('height', r*2)
        .attr('fill', d.color ?? '#888').attr('opacity', 0.85)
        .on('mouseover', (e) => showTooltip(e, d))
        .on('mouseout', hideTooltip);
    }} else if (shape === 'triangle') {{
      const path = `M${{x}},${{y - r}} L${{x + r * 0.87}},${{y + r * 0.5}} L${{x - r * 0.87}},${{y + r * 0.5}} Z`;
      g.append('path').attr('d', path)
        .attr('fill', d.color ?? '#888').attr('opacity', 0.85)
        .on('mouseover', (e) => showTooltip(e, d))
        .on('mouseout', hideTooltip);
    }} else if (shape === 'diamond') {{
      const path = `M${{x}},${{y - r}} L${{x + r}},${{y}} L${{x}},${{y + r}} L${{x - r}},${{y}} Z`;
      g.append('path').attr('d', path)
        .attr('fill', d.color ?? '#888').attr('opacity', 0.85)
        .on('mouseover', (e) => showTooltip(e, d))
        .on('mouseout', hideTooltip);
    }}
  }});
}}

layerNodes.selectAll('g.node')
  .data(nodesData)
  .enter().append('g').attr('class', 'node')
  .call(renderNode);

// ── 渲染: 里程碑标签 ───────────────────────────────────────────────────────────
layerLandmarks.selectAll('.landmark-label')
  .data(landmarkData)
  .enter().append('text')
  .attr('class', 'landmark-label')
  .attr('x', d => tx((d.x ?? 800) + 16))
  .attr('y', d => ty(d.y ?? 800))
  .attr('filter', 'url(#glow-landmark)')
  .text(d => d.short_label_zh || '');

// 里程碑标记圆
layerLandmarks.selectAll('.landmark-ring')
  .data(landmarkData)
  .enter().append('circle')
  .attr('class', 'landmark-ring')
  .attr('cx', d => tx(d.x ?? 800))
  .attr('cy', d => ty(d.y ?? 800))
  .attr('r', 12 * scale)
  .attr('fill', 'none')
  .attr('stroke', '#ffe066')
  .attr('stroke-width', 1.5)
  .attr('opacity', 0.8)
  .attr('filter', 'url(#glow-landmark)');

// ── 图层切换 ──────────────────────────────────────────────────────────────────
const layerMap = {{
  'nodes':     layerNodes,
  'edges':     layerEdges,
  'halos':     layerHalos,
  'meta':      layerMeta,
  'landmarks': layerLandmarks,
}};

function toggleLayer(name) {{
  const layer = layerMap[name];
  const btn = document.getElementById('btn-' + name);
  const isVisible = layer.style('display') !== 'none';
  layer.style('display', isVisible ? 'none' : null);
  btn.classList.toggle('active', !isVisible);
}}

// 初始居中
svg.call(zoom.transform, d3.zoomIdentity.translate(0, 0).scale(1));
</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path
