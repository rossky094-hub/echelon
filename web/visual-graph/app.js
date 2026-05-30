const token = "pilot-viewer-token";

const state = {
  apiBase: "http://127.0.0.1:8000",
  nodes: [],
  edges: [],
  clusters: [],
  lineages: [],
  story: [],
  nodeById: new Map(),
  edgeById: new Map(),
  visibleNodes: [],
  selected: null,
  topicLens: null,
  mode: "topic",
  scale: 0.86,
  panX: 0,
  panY: 0,
  highlightIds: new Set(),
  loadedEdgeKeys: new Set(["base"]),
  layers: {
    main_path: true,
    topic: true,
    citation: false,
    semantic: false,
    future: true,
    bottleneck: true,
    uncertainty: true,
    fusion_value: true,
  },
  time: {
    min: 1995,
    max: 2026,
    current: 1995,
    playing: false,
    raf: null,
    lastTick: 0,
    yearsPerSecond: 7.5,
  },
};

const LAYER_ORDER = ["main_path", "topic", "citation", "semantic", "future", "bottleneck", "uncertainty", "fusion_value"];

const els = {
  apiBase: document.getElementById("apiBase"),
  loadBtn: document.getElementById("loadBtn"),
  status: document.getElementById("statusText"),
  contextTitle: document.getElementById("contextTitle"),
  contextMeta: document.getElementById("contextMeta"),
  layerMeaning: document.getElementById("layerMeaning"),
  metrics: document.getElementById("metrics"),
  graph: document.getElementById("graphCanvas"),
  edges: document.getElementById("edgeCanvas"),
  hover: document.getElementById("hoverCard"),
  searchForm: document.getElementById("searchForm"),
  searchInput: document.getElementById("searchInput"),
  paperPane: document.getElementById("paperPane"),
  topicPane: document.getElementById("topicPane"),
  radarPane: document.getElementById("radarPane"),
  clusterPane: document.getElementById("clusterPane"),
  storyPane: document.getElementById("storyPane"),
  explainDock: document.getElementById("explainDock"),
  playBtn: document.getElementById("playBtn"),
  timeSlider: document.getElementById("timeSlider"),
  timeLabel: document.getElementById("timeLabel"),
  growthLabel: document.getElementById("growthLabel"),
  modeButtons: Array.from(document.querySelectorAll(".mode")),
  layerInputs: Array.from(document.querySelectorAll("[data-layer]")),
};

const gl = els.graph.getContext("webgl", { antialias: true, alpha: true });
const edgeCtx = els.edges.getContext("2d");

let program;
let buffers = {};

const DEFAULT_VALUE_MODEL = {
  layout_distance: {
    algorithm: "paper embedding/community layout projected with publication year",
    relationship: "nearby dots are semantically/community close; vertical growth is time; edges carry evidence",
    display: "2.5D evolution projection: X is semantic branch space, Y is year-dominant growth axis",
  },
  layers: {
    main_path: {
      algorithm: "SPC main path on SCC-condensed citation DAG",
      relationship: "historical trunk: older cited paper -> newer citing paper",
      display: "black thick edges",
    },
    topic: {
      algorithm: "co-citation/co-reference affinity",
      relationship: "shared intellectual neighborhood",
      display: "blue-green soft branch edges",
    },
    citation: {
      algorithm: "ID-relinked local references",
      relationship: "real citation edge",
      display: "thin grey local edges",
    },
    semantic: {
      algorithm: "embedding kNN",
      relationship: "text/section similarity",
      display: "thin blue proximity edges",
    },
    future: {
      algorithm: "calibrated future candidate generator plus fusion when materialized",
      relationship: "candidate future growth hypothesis",
      display: "purple dashed arcs",
    },
    bottleneck: {
      algorithm: "section-level limitation/claim atoms",
      relationship: "unresolved constraints",
      display: "red/orange node role",
    },
    uncertainty: {
      algorithm: "coverage and calibration quality gates",
      relationship: "where evidence is weaker",
      display: "amber node marker",
    },
    fusion_value: {
      algorithm: "Step6 tiered fusion + Step13 Claim Card gates",
      relationship: "decision value = path support + calibrated candidate score + bottleneck evidence + section quality",
      display: "Radar and Claim Cards",
    },
  },
  counts: { edges_by_layer: {}, future_directions: 0, claim_cards: 0, fusion_adequacy: "unknown" },
  model_components: {
    gnn_future_growth: {
      name: "Step5b GNN/VGAE future candidate generator",
      role: "GNN future candidate generator. Needs Step6/Step13 evidence before investment-grade claims.",
    },
  },
  fusion_status: "unknown",
};

function api(path, options = {}) {
  return fetch(`${state.apiBase}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Pilot-Token": token,
      ...(options.headers || {}),
    },
  }).then(async (res) => {
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || res.statusText);
    return data;
  });
}

function setStatus(text) {
  els.status.textContent = text;
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function fmt(value) {
  return Number(value || 0).toLocaleString();
}

function pct(value) {
  if (value == null || Number.isNaN(Number(value))) return "-";
  return `${Math.round(Number(value) * 100)}%`;
}

function futureCalibrationCopy(edge) {
  const evidence = edge?.evidence || edge?.model_evidence || {};
  const status = evidence.calibration_status || evidence.lifecycle_calibration_status || "run_audit_unknown";
  const score = edge?.candidate_score ?? evidence.candidate_score ?? edge?.confidence ?? edge?.weight ?? evidence.calibrated_prob ?? 0;
  const raw = evidence.raw_candidate_score ?? evidence.raw_predicted_prob ?? score;
  if (status === "calibrated_with_run_audit") {
    return `run-calibrated ${pct(evidence.calibrated_prob ?? score)} / raw ${pct(raw)} / ${evidence.calibration_label || evidence.calibration_method || "calibrated"}`;
  }
  return `not run-calibrated / status ${status} / edge score ${pct(score)}`;
}

function clamp(value, lo, hi) {
  return Math.max(lo, Math.min(hi, value));
}

function asArray(value) {
  if (Array.isArray(value)) return value;
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }
  return [];
}

function truncate(value, max = 150) {
  const text = String(value || "");
  return text.length > max ? `${text.slice(0, max - 1)}...` : text;
}

function renderAccessLinks(links = []) {
  if (!Array.isArray(links) || !links.length) return "<p>No access link recorded.</p>";
  return links.slice(0, 8).map((link) => {
    const url = esc(link.url || "");
    const label = esc(link.label || link.kind || "Open");
    const level = esc(link.access_level || "external");
    return `<p><a href="${url}" target="_blank" rel="noreferrer">${label}</a> <small>${level}</small></p>`;
  }).join("");
}

function sectionEvidenceMeta(section = {}) {
  const meta = section.meta && typeof section.meta === "object" ? section.meta : {};
  const strategies = asArray(section.extraction_strategies || meta.extraction_strategies);
  const pages = asArray(section.pages);
  return [
    section.claim_scope || null,
    section.evidence_grade || null,
    strategies.length ? `strategy: ${strategies.join("+")}` : "strategy: unknown",
    pages.length ? `pages: ${pages.join(", ")}` : "pages: unknown",
    section.parser_name ? `parser: ${section.parser_name}` : null,
  ].filter(Boolean).join(" / ");
}

function renderSectionEvidence(section = {}) {
  const label = section.section_type || section.section_name || section.title || "section";
  const text = section.text || section.section_text || section.content || section.snippet || "";
  const reasons = asArray(section.uncertainty_reasons);
  return `
    <div class="section-evidence">
      <p><strong>${esc(label)}</strong> ${esc(truncate(text, 260))}</p>
      <small>${esc(sectionEvidenceMeta(section))}</small>
      ${section.source_url ? `<p class="mini"><a href="${esc(section.source_url)}" target="_blank" rel="noreferrer">打开证据来源</a></p>` : ""}
      ${reasons.length ? `<p class="mini">不确定性：${reasons.slice(0, 3).map(esc).join(" / ")}</p>` : ""}
    </div>
  `;
}

function renderLocalContent(content = {}, availability = {}) {
  const sections = Array.isArray(content.sections) ? content.sections : [];
  const decisionSections = Array.isArray(content.decision_evidence_sections)
    ? content.decision_evidence_sections
    : [];
  const provenance = availability.primary_section_provenance || content.primary_section_provenance || {};
  const provenanceText = provenance.total
    ? `primary provenance ${fmt(provenance.strong || 0)}/${fmt(provenance.moderate || 0)}/${fmt(provenance.weak || 0)} strong/moderate/weak`
    : null;
  const badges = [
    availability.has_local_abstract ? "abstract" : null,
    sections.length ? `${sections.length} sections` : null,
    decisionSections.length ? `${decisionSections.length} evidence sections` : null,
    provenanceText,
    content.limitation_atoms ? `${content.limitation_atoms} limitations` : null,
    content.claim_cards ? `${content.claim_cards} claim cards` : null,
  ].filter(Boolean);
  return badges.length ? esc(badges.join(" / ")) : "metadata only";
}

function evidencePaperButtons(papers = [], limit = 5) {
  const items = (papers || []).filter((p) => p && p.paper_id).slice(0, limit);
  if (!items.length) return "";
  return `
    <div class="evidence-list">
      ${items.map((paper) => `
        <button class="evidence-paper" data-paper="${esc(paper.paper_id)}">
          <strong>${esc(truncate(paper.title || paper.paper_id, 92))}</strong>
          <small>${esc(paper.paper_id)} / ${esc(paper.year || "?")} ${paper.why ? `/ ${esc(paper.why)}` : ""}</small>
        </button>
      `).join("")}
    </div>
  `;
}

function renderEvidenceObjects(objects = [], limit = 8) {
  const items = (objects || []).filter(Boolean).slice(0, limit);
  if (!items.length) return "";
  return `
    <details class="evidence-objects">
      <summary>查看证据对象 (${fmt(items.length)})</summary>
      ${items.map((obj) => {
        const label = obj.label || obj.title || obj.paper_id || obj.edge_id || obj.type || "evidence";
        const meta = [
          obj.type,
          obj.role,
          obj.source,
          obj.evidence_quality,
          obj.evidence_grade,
          obj.claim_scope,
        ].filter(Boolean).join(" / ");
        if (obj.paper_id) {
          return `
            <button class="evidence-paper" data-paper="${esc(obj.paper_id)}">
              <strong>${esc(truncate(label, 96))}</strong>
              <small>${esc(obj.paper_id)}${meta ? ` / ${esc(meta)}` : ""}</small>
            </button>
          `;
        }
        return `
          <div class="evidence-object">
            <strong>${esc(truncate(label, 110))}</strong>
            <small>${esc(meta || "graph evidence")}</small>
            ${obj.description ? `<p class="mini">${esc(truncate(obj.description, 220))}</p>` : ""}
          </div>
        `;
      }).join("")}
    </details>
  `;
}

function shader(type, source) {
  const s = gl.createShader(type);
  gl.shaderSource(s, source);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
    throw new Error(gl.getShaderInfoLog(s));
  }
  return s;
}

function initGl() {
  if (!gl) throw new Error("WebGL is not available in this browser.");
  const vs = shader(gl.VERTEX_SHADER, `
    attribute vec3 a_pos;
    attribute vec3 a_color;
    attribute float a_size;
    uniform vec2 u_pan;
    uniform float u_scale;
    varying vec3 v_color;
    void main() {
      vec2 xy = a_pos.xy * u_scale + u_pan;
      gl_Position = vec4(xy, 0.0, 1.0);
      gl_PointSize = clamp(a_size, 2.0, 22.0);
      v_color = a_color;
    }
  `);
  const fs = shader(gl.FRAGMENT_SHADER, `
    precision mediump float;
    varying vec3 v_color;
    void main() {
      vec2 p = gl_PointCoord - vec2(0.5);
      float d = dot(p, p);
      if (d > 0.25) discard;
      float alpha = smoothstep(0.25, 0.07, d);
      gl_FragColor = vec4(v_color, alpha);
    }
  `);
  program = gl.createProgram();
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(program));
  }
  buffers.pos = gl.createBuffer();
  buffers.color = gl.createBuffer();
  buffers.size = gl.createBuffer();
}

function hexToRgb(hex) {
  const safe = /^#[0-9a-f]{6}$/i.test(hex || "") ? hex : "#176b5f";
  const n = Number.parseInt(safe.slice(1), 16);
  return [(n >> 16 & 255) / 255, (n >> 8 & 255) / 255, (n & 255) / 255];
}

function yearOf(node) {
  const y = Number(node.year || node.publication_year || node.z);
  return Number.isFinite(y) ? y : null;
}

function nodeVisibleByTime(node) {
  const y = yearOf(node);
  return y == null || y <= Number(state.time.current || state.time.max);
}

function timeAxisY(year) {
  const min = Number(state.time.min || 1995);
  const max = Number(state.time.max || 2026);
  const span = Math.max(1, max - min);
  const value = Number.isFinite(Number(year)) ? Number(year) : (min + max) / 2;
  const norm = clamp((value - min) / span, 0, 1);
  return -0.92 + norm * 1.84;
}

function projectNode(node) {
  const semanticX = Number(node.x || 0);
  const semanticY = Number(node.y || 0);
  const yearY = timeAxisY(yearOf(node));
  return {
    x: semanticX * 0.88,
    y: yearY * 0.72 + semanticY * 0.28,
    z: Number(node.z || yearOf(node) || 0),
  };
}

function toScreenPoint(point, width, height) {
  const x = (Number(point.x || 0) * state.scale + state.panX) * 0.5 + 0.5;
  const y = 0.5 - (Number(point.y || 0) * state.scale + state.panY) * 0.5;
  return { x: x * width, y: y * height };
}

function roleColor(node) {
  const highlighted = state.highlightIds.has(node.paper_id);
  if (state.selected && state.selected.paper_id === node.paper_id) return [0.02, 0.02, 0.02];
  if (highlighted) return [0.05, 0.28, 0.82];
  if (node.visual_role === "main_path") return [0.06, 0.06, 0.06];
  if (node.visual_role === "future_anchor") return [0.43, 0.22, 0.76];
  if (state.layers.bottleneck && node.visual_role === "limitation_bottleneck") return [0.81, 0.30, 0.19];
  if (state.layers.uncertainty && Number(node.uncertainty_score || 0) >= 0.62) return [0.76, 0.48, 0.02];
  return hexToRgb(node.color_hex);
}

function nodeDrawSize(node) {
  const base = Math.max(2, Math.min(18, Number(node.node_size || 4)));
  if (state.selected && state.selected.paper_id === node.paper_id) return base + 7;
  if (state.highlightIds.has(node.paper_id)) return base + 5;
  if (state.layers.uncertainty && Number(node.uncertainty_score || 0) >= 0.75) return base + 1.8;
  return base;
}

function visibleNodes() {
  return state.nodes.filter(nodeVisibleByTime);
}

function uploadNodes() {
  const visible = visibleNodes();
  const pos = new Float32Array(visible.length * 3);
  const color = new Float32Array(visible.length * 3);
  const size = new Float32Array(visible.length);
  visible.forEach((node, i) => {
    const projected = projectNode(node);
    pos[i * 3] = projected.x;
    pos[i * 3 + 1] = projected.y;
    pos[i * 3 + 2] = projected.z;
    color.set(roleColor(node), i * 3);
    size[i] = nodeDrawSize(node);
  });
  state.visibleNodes = visible;
  gl.bindBuffer(gl.ARRAY_BUFFER, buffers.pos);
  gl.bufferData(gl.ARRAY_BUFFER, pos, gl.STATIC_DRAW);
  gl.bindBuffer(gl.ARRAY_BUFFER, buffers.color);
  gl.bufferData(gl.ARRAY_BUFFER, color, gl.STATIC_DRAW);
  gl.bindBuffer(gl.ARRAY_BUFFER, buffers.size);
  gl.bufferData(gl.ARRAY_BUFFER, size, gl.STATIC_DRAW);
  updateTimelineLabels();
}

function toScreen(node, width, height) {
  return toScreenPoint(projectNode(node), width, height);
}

function edgeKey(edge) {
  if (edge.is_main_path || edge.edge_type === "main_path") return "main_path";
  if (edge.layer === "future" || edge.edge_type === "future_growth") return "future";
  if (edge.layer === "semantic") return "semantic";
  if (edge.layer === "topic") return "topic";
  if (edge.layer === "citation") return "citation";
  return edge.layer || edge.edge_type || "citation";
}

function edgeVisible(edge, visibleIds) {
  const key = edgeKey(edge);
  if (!state.layers[key]) return false;
  if (key === "future" && Number(state.time.current) < Number(state.time.max)) return false;
  if (!visibleIds.has(edge.source_paper_id) || !visibleIds.has(edge.target_paper_id)) return false;
  return true;
}

function edgePaint(edge) {
  const key = edgeKey(edge);
  if (key === "main_path") return { color: "rgba(17,17,17,.86)", width: 1.7, dash: [] };
  if (key === "future") return { color: "rgba(111,66,193,.72)", width: 1.4, dash: [6, 5] };
  if (key === "topic") return { color: "rgba(21,127,149,.20)", width: 0.75, dash: [] };
  if (key === "semantic") return { color: "rgba(45,108,223,.13)", width: 0.65, dash: [] };
  return { color: "rgba(82,88,95,.14)", width: 0.65, dash: [] };
}

function drawEdges() {
  const dpr = window.devicePixelRatio || 1;
  const w = els.edges.width / dpr;
  const h = els.edges.height / dpr;
  edgeCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  edgeCtx.clearRect(0, 0, w, h);
  drawYearGuides(w, h);
  const visibleIds = new Set(state.visibleNodes.map((node) => node.paper_id));
  const layerCounts = {};
  const maxByLayer = {
    main_path: 5000,
    future: 1500,
    topic: 36000,
    semantic: 24000,
    citation: 22000,
  };
  for (const edge of state.edges) {
    const key = edgeKey(edge);
    layerCounts[key] = layerCounts[key] || 0;
    if (layerCounts[key] >= (maxByLayer[key] || 12000)) continue;
    if (!edgeVisible(edge, visibleIds)) continue;
    const a = state.nodeById.get(edge.source_paper_id);
    const b = state.nodeById.get(edge.target_paper_id);
    if (!a || !b) continue;
    const pa = toScreen(a, w, h);
    const pb = toScreen(b, w, h);
    const paint = edgePaint(edge);
    edgeCtx.strokeStyle = paint.color;
    edgeCtx.lineWidth = paint.width;
    edgeCtx.setLineDash(paint.dash);
    edgeCtx.beginPath();
    if (key === "future") {
      const mx = (pa.x + pb.x) / 2;
      const my = (pa.y + pb.y) / 2 - Math.min(110, Math.hypot(pa.x - pb.x, pa.y - pb.y) * 0.14 + 16);
      edgeCtx.moveTo(pa.x, pa.y);
      edgeCtx.quadraticCurveTo(mx, my, pb.x, pb.y);
    } else {
      edgeCtx.moveTo(pa.x, pa.y);
      edgeCtx.lineTo(pb.x, pb.y);
    }
    edgeCtx.stroke();
    layerCounts[key] += 1;
  }
  edgeCtx.setLineDash([]);
}

function drawYearGuides(w, h) {
  const min = Math.ceil(Number(state.time.min || 1995) / 5) * 5;
  const max = Math.floor(Number(state.time.max || 2026) / 5) * 5;
  edgeCtx.save();
  edgeCtx.font = "11px Inter, system-ui, sans-serif";
  edgeCtx.fillStyle = "rgba(96,102,109,.68)";
  edgeCtx.strokeStyle = "rgba(23,25,28,.075)";
  edgeCtx.lineWidth = 1;
  for (let year = min; year <= max; year += 5) {
    const p = toScreenPoint({ x: 0, y: timeAxisY(year) }, w, h);
    edgeCtx.beginPath();
    edgeCtx.moveTo(0, p.y);
    edgeCtx.lineTo(w, p.y);
    edgeCtx.stroke();
    edgeCtx.fillText(String(year), 12, clamp(p.y - 5, 12, h - 10));
  }
  const current = toScreenPoint({ x: 0, y: timeAxisY(state.time.current) }, w, h);
  edgeCtx.strokeStyle = "rgba(15,118,110,.42)";
  edgeCtx.beginPath();
  edgeCtx.moveTo(0, current.y);
  edgeCtx.lineTo(w, current.y);
  edgeCtx.stroke();
  edgeCtx.restore();
}

function draw() {
  if (!program) return;
  const visible = state.visibleNodes || [];
  gl.clearColor(0, 0, 0, 0);
  gl.clear(gl.COLOR_BUFFER_BIT);
  gl.useProgram(program);
  const posLoc = gl.getAttribLocation(program, "a_pos");
  const colorLoc = gl.getAttribLocation(program, "a_color");
  const sizeLoc = gl.getAttribLocation(program, "a_size");
  gl.bindBuffer(gl.ARRAY_BUFFER, buffers.pos);
  gl.vertexAttribPointer(posLoc, 3, gl.FLOAT, false, 0, 0);
  gl.enableVertexAttribArray(posLoc);
  gl.bindBuffer(gl.ARRAY_BUFFER, buffers.color);
  gl.vertexAttribPointer(colorLoc, 3, gl.FLOAT, false, 0, 0);
  gl.enableVertexAttribArray(colorLoc);
  gl.bindBuffer(gl.ARRAY_BUFFER, buffers.size);
  gl.vertexAttribPointer(sizeLoc, 1, gl.FLOAT, false, 0, 0);
  gl.enableVertexAttribArray(sizeLoc);
  gl.uniform2f(gl.getUniformLocation(program, "u_pan"), state.panX, state.panY);
  gl.uniform1f(gl.getUniformLocation(program, "u_scale"), state.scale);
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
  gl.drawArrays(gl.POINTS, 0, visible.length);
  drawEdges();
}

function resize() {
  const rect = els.graph.getBoundingClientRect();
  for (const canvas of [els.graph, els.edges]) {
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(rect.width * dpr));
    canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  }
  gl.viewport(0, 0, els.graph.width, els.graph.height);
  draw();
}

function nearestNode(evt) {
  const rect = els.graph.getBoundingClientRect();
  const x = evt.clientX - rect.left;
  const y = evt.clientY - rect.top;
  let best = null;
  let bestD = 17 * 17;
  for (const node of state.visibleNodes || []) {
    const p = toScreen(node, rect.width, rect.height);
    const dx = p.x - x;
    const dy = p.y - y;
    const d = dx * dx + dy * dy;
    if (d < bestD) {
      bestD = d;
      best = node;
    }
  }
  return best;
}

function mergeEdges(edges) {
  for (const edge of edges || []) {
    state.edgeById.set(edge.edge_id, edge);
  }
  state.edges = Array.from(state.edgeById.values());
}

async function ensureLayerEdges(layer) {
  if (state.loadedEdgeKeys.has(layer)) return;
  if (layer === "semantic") {
    setStatus("Loading semantic layer...");
    const data = await api("/graph/visual/edges?layer=semantic&lod_max=2&limit=60000");
    mergeEdges(data.edges || []);
  } else if (layer === "citation") {
    setStatus("Loading citation layer...");
    const data = await api("/graph/visual/edges?layer=citation&lod_max=3&limit=70000");
    mergeEdges((data.edges || []).filter((edge) => edge.edge_type !== "main_path"));
  } else if (layer === "topic") {
    setStatus("Loading co-citation layer...");
    const data = await api("/graph/visual/edges?layer=topic&lod_max=1&limit=100000");
    mergeEdges(data.edges || []);
  }
  state.loadedEdgeKeys.add(layer);
}

function fitToNodes(nodes = state.nodes) {
  const pool = nodes.length ? nodes : state.nodes;
  if (!pool.length) return;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const node of pool) {
    const projected = projectNode(node);
    const x = Number(projected.x || 0);
    const y = Number(projected.y || 0);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    minX = Math.min(minX, x);
    maxX = Math.max(maxX, x);
    minY = Math.min(minY, y);
    maxY = Math.max(maxY, y);
  }
  if (!Number.isFinite(minX)) return;
  const span = Math.max(maxX - minX, maxY - minY, 0.01);
  state.scale = clamp(1.72 / span, 0.35, 5.5);
  state.panX = -((minX + maxX) / 2) * state.scale;
  state.panY = -((minY + maxY) / 2) * state.scale;
}

function focusPaperIds(ids) {
  const focus = Array.from(ids || [])
    .map((id) => state.nodeById.get(id))
    .filter(Boolean);
  if (!focus.length) return;
  fitToNodes(focus);
}

function updateTimelineLabels() {
  const year = Math.round(Number(state.time.current || state.time.max));
  els.timeLabel.textContent = String(year);
  els.timeSlider.value = String(year);
  els.growthLabel.textContent = `${fmt(state.visibleNodes.length)} papers`;
  els.playBtn.textContent = state.time.playing ? "Pause" : "Play";
}

function setTimeCutoff(year, options = {}) {
  state.time.current = clamp(Number(year), state.time.min, state.time.max);
  uploadNodes();
  if (options.draw !== false) draw();
}

function stopPlayback() {
  state.time.playing = false;
  if (state.time.raf) cancelAnimationFrame(state.time.raf);
  state.time.raf = null;
  updateTimelineLabels();
}

function playbackTick(ts) {
  if (!state.time.playing) return;
  if (!state.time.lastTick) state.time.lastTick = ts;
  const dt = Math.min(0.08, (ts - state.time.lastTick) / 1000);
  state.time.lastTick = ts;
  const next = state.time.current + dt * state.time.yearsPerSecond;
  if (next >= state.time.max) {
    setTimeCutoff(state.time.max);
    stopPlayback();
    return;
  }
  setTimeCutoff(next);
  state.time.raf = requestAnimationFrame(playbackTick);
}

function startPlayback(fromStart = false) {
  if (fromStart) state.time.current = state.time.min;
  state.time.playing = true;
  state.time.lastTick = 0;
  updateTimelineLabels();
  state.time.raf = requestAnimationFrame(playbackTick);
}

function renderMetrics(status = {}) {
  const counts = status.counts || {};
  const frontfill = status.frontfill_status || {};
  const items = [
    ["Nodes", counts.visual_nodes || state.nodes.length],
    ["Edges", counts.visual_edges || state.edges.length],
    ["Branches", counts.visual_clusters || state.clusters.length],
    ["Tiles", counts.visual_tiles || 0],
  ];
  els.metrics.innerHTML = items.map(([label, value]) => (
    `<div class="metric"><strong>${fmt(value)}</strong><span>${label}</span></div>`
  )).join("") + (frontfill.available ? `
    <div class="metric warning"><strong>${fmt(frontfill.primary_section_papers || 0)}</strong><span>Primary sections</span></div>
    <div class="metric"><strong>${pct(frontfill.openalex_w_rate || 0)}</strong><span>OpenAlex W</span></div>
  ` : "");
}

function renderExplainDock(model = null) {
  const valueModel = model || state.topicLens?.value_model || DEFAULT_VALUE_MODEL;
  const layers = valueModel.layers || DEFAULT_VALUE_MODEL.layers;
  const counts = valueModel.counts || {};
  const frontfill = valueModel.frontfill_status || {};
  const edgeCounts = counts.edges_by_layer || {};
  const gnn = valueModel.model_components?.gnn_future_growth || DEFAULT_VALUE_MODEL.model_components.gnn_future_growth;
  const combos = valueModel.layer_combinations || [];
  const rows = [
    ["Main", layers.main_path, edgeCounts.main_path],
    ["Co-cite", layers.topic, edgeCounts.topic],
    ["Cite", layers.citation, edgeCounts.citation],
    ["Semantic", layers.semantic, edgeCounts.semantic],
    ["Future", layers.future, edgeCounts.future],
    ["Bottleneck", layers.bottleneck, null],
    ["Uncertainty", layers.uncertainty, null],
    ["Fusion value", layers.fusion_value, null],
  ];
  const layout = valueModel.layout_distance || DEFAULT_VALUE_MODEL.layout_distance;
  els.explainDock.innerHTML = `
    <details open>
      <summary>How to read this evolution map</summary>
      <p><strong>Point distance.</strong> ${esc(layout.relationship || "")}</p>
      <p><strong>Projection.</strong> ${esc(layout.display || "")}</p>
      <p><strong>GNN.</strong> ${esc(gnn.name || "Step5b VGAE")}：${esc(gnn.role || "")}</p>
      <div class="layer-explain-list">
        ${rows.map(([label, item, count]) => `
          <div class="layer-explain">
            <strong>${esc(label)}${count == null ? "" : ` ${fmt(count)}`}</strong>
            <span>${esc(item?.algorithm || "")}</span>
            <small>${esc(item?.relationship || "")} ${esc(item?.display || "")}</small>
          </div>
        `).join("")}
      </div>
      <details>
        <summary>Useful layer combinations</summary>
        <div class="layer-explain-list">
          ${combos.map((combo) => `
          <div class="layer-explain combo">
            <strong>${esc(combo.label || (combo.layers || []).join(" + "))}</strong>
            <span>${esc((combo.layers || []).join(" + "))}</span>
            <small>${esc(combo.question || "")} ${esc(combo.decision_use || "")}</small>
            ${renderComboContract(combo)}
          </div>
        `).join("")}
        </div>
      </details>
      <p class="mini">Fusion status: ${esc(valueModel.fusion_status || "unknown")} / Step6 adequacy ${esc(counts.fusion_adequacy || "unknown")} / claim cards ${fmt(counts.claim_cards || 0)}</p>
      ${frontfill.available ? `
        <p class="mini">Evidence frontfill: primary sections ${fmt(frontfill.primary_section_papers || 0)} papers / OpenAlex W ${pct(frontfill.openalex_w_rate || 0)} / ${esc(frontfill.interpretation || "")}</p>
      ` : ""}
    </details>
  `;
}

function activeLayerKeys() {
  return Object.entries(state.layers)
    .filter(([, enabled]) => enabled)
    .map(([key]) => key)
    .sort((a, b) => LAYER_ORDER.indexOf(a) - LAYER_ORDER.indexOf(b));
}

function sameLayerSet(a = [], b = []) {
  if (a.length !== b.length) return false;
  const sa = new Set(a);
  return b.every((x) => sa.has(x));
}

function activeLayerCombination(keys, valueModel = null) {
  const combos = (valueModel || state.topicLens?.value_model || DEFAULT_VALUE_MODEL).layer_combinations || [];
  const exact = combos.find((combo) => sameLayerSet(combo.layers || [], keys));
  if (exact) return exact;
  const subset = combos
    .filter((combo) => (combo.layers || []).every((layer) => keys.includes(layer)))
    .sort((a, b) => (b.layers || []).length - (a.layers || []).length)[0];
  return subset || null;
}

function activeLayerInterpretation(keys, valueModel = null) {
  const combo = activeLayerCombination(keys, valueModel);
  if (combo) {
    return `${combo.label || "组合视图"}：${combo.question || ""} ${combo.relationship || ""} ${combo.decision_use || ""}`;
  }
  const set = new Set(keys);
  if (set.size === 1 && set.has("main_path")) {
    return "只看 Main：这是历史主干。它回答哪些论文承担了演化树的骨架，但不会显示每个局部主题团。";
  }
  if (set.has("main_path") && set.has("topic") && set.size <= 2) {
    return "Main + Co-cite：先看历史主干，再看哪些主题块围绕主干成团。这是理解“为什么长成这样”的推荐组合。";
  }
  if (set.has("future") && !set.has("bottleneck")) {
    return "Future 单独看只能说明 GNN/VGAE 给出了候选连接评分，不能说明为什么值得下注；应同时打开 Bottleneck 或 Radar。";
  }
  if (set.has("future") && set.has("bottleneck") && set.has("uncertainty")) {
    return "Future + Bottleneck + Uncertainty：这是投资/立项视角，重点看未来候选是否被未解卡点支持，以及证据哪里薄；打开 Fusion value 可区分完整 Claim Card 和候选池。";
  }
  if (set.has("fusion_value")) {
    return "Fusion value：这是 Step6/Step13 合成后的 Claim Card/Radar 价值层，用来区分可审计方向和仍需补证据的候选。";
  }
  if (set.has("semantic") && !set.has("citation") && !set.has("main_path")) {
    return "只看 Semantic：这是相似论文地图，适合找相关工作，不等于历史演化或因果链。";
  }
  return "组合视图：点距给语义/时间位置，边层给证据。Main 是历史骨架，Co-cite 是主题团，Cite 是真实引用，Semantic 是相似，Future 是候选，Bottleneck/Uncertainty/Fusion value 决定可信度和能否进入 Radar。";
}

function renderComboContract(combo = {}) {
  const can = combo.can_explain || [];
  const cannot = combo.cannot_explain || [];
  const required = combo.required_evidence || [];
  const uncertainty = combo.uncertainty_reasons || [];
  return `
    <div class="pill-row">
      <span class="pill">${esc(combo.claim_scope || "claim scope unknown")}</span>
      <span class="pill">${esc(combo.evidence_grade || "evidence unknown")}</span>
    </div>
    ${can.length ? `<p class="mini"><strong>能说明：</strong>${can.slice(0, 3).map(esc).join(" / ")}</p>` : ""}
    ${cannot.length ? `<p class="mini"><strong>不能说明：</strong>${cannot.slice(0, 3).map(esc).join(" / ")}</p>` : ""}
    ${required.length ? `<p class="mini"><strong>需要证据：</strong>${required.slice(0, 4).map(esc).join(" / ")}</p>` : ""}
    ${uncertainty.length ? `<details><summary>不确定性 (${fmt(uncertainty.length)})</summary>${uncertainty.slice(0, 5).map((reason) => `<p class="mini">${esc(reason)}</p>`).join("")}</details>` : ""}
  `;
}

function renderLayerMeaning(model = null) {
  const valueModel = model || state.topicLens?.value_model || DEFAULT_VALUE_MODEL;
  const layers = valueModel.layers || DEFAULT_VALUE_MODEL.layers;
  const keys = activeLayerKeys();
  const combo = activeLayerCombination(keys, valueModel);
  const labels = {
    main_path: "Main",
    topic: "Co-cite",
    citation: "Cite",
    semantic: "Semantic",
    future: "Future",
    bottleneck: "Bottleneck",
    uncertainty: "Uncertainty",
    fusion_value: "Fusion value",
  };
  const activeRows = keys.map((key) => {
    const item = layers[key] || {};
    return `<p><strong>${esc(labels[key] || key)}</strong>：${esc(item.relationship || "")}<br><small>${esc(item.display || "")}</small></p>`;
  }).join("");
  els.layerMeaning.innerHTML = `
    <strong>当前图层读法</strong>
    <p>${esc(activeLayerInterpretation(keys, valueModel))}</p>
    ${combo ? `
      <div class="combo-card">
        <strong>${esc(combo.label || "Layer combination")}</strong>
        <p>${esc(combo.question || "")}</p>
        <small>${esc(combo.display || "")}</small>
        ${renderComboContract(combo)}
      </div>
    ` : ""}
    ${activeRows}
  `;
}

function lineageByBranch() {
  return new Map(state.lineages.map((lineage) => [lineage.branch_id, lineage]));
}

function renderClusters() {
  const lineages = lineageByBranch();
  const intro = `
    <div class="item">
      <strong>Branches 怎么看</strong>
      <p>Branch 不是前端随便画的分组，而是 Step10 把 semantic/community layout、co-citation 主题团、main-path 邻域和 branch lineage 证据合成后的演化分支。</p>
      <p class="mini">parent 表示该分支从哪个父分支裂变；split/support 表示分裂年份和证据支持度。它回答“这个 topic 为什么从旧主干长出这个新方向”。</p>
    </div>
  `;
  els.clusterPane.innerHTML = intro + state.clusters.slice(0, 120).map((cluster) => {
    const lineage = lineages.get(cluster.branch_id) || {};
    const support = lineage.split_confidence == null ? "-" : pct(lineage.split_confidence);
    const terms = (cluster.top_terms || []).slice(0, 5).map((t) => `<span class="pill">${esc(t)}</span>`).join("");
    return `
      <div class="item">
        <button data-cluster="${esc(cluster.cluster_id)}">
          <strong>${esc(cluster.label || cluster.cluster_id)}</strong><br>
          <small>${esc(cluster.cluster_id)} / ${fmt(cluster.n_nodes)} papers / ${esc(cluster.year_start || "?")}-${esc(cluster.year_end || "?")}</small>
        </button>
        <div class="pill-row">${terms}</div>
        <div class="pill-row">
          <span class="pill ${lineage.lineage_status === "evidence_backed_split" ? "good" : "warn"}">${esc(lineage.lineage_status || "layout_cluster_only")}</span>
          <span class="pill">${esc(lineage.claim_scope || "layout_cluster_navigation_only")}</span>
          <span class="pill">${esc(lineage.evidence_grade || "layout_cluster_only")}</span>
        </div>
        <p class="mini">parent ${esc(lineage.parent_branch_id || "-")} / split ${esc(lineage.split_year || "-")} / support ${support}</p>
        ${lineage.split_reason ? `<p class="mini">${esc(lineage.split_reason)}</p>` : ""}
        ${(lineage.required_evidence || []).length ? `<p class="mini"><strong>分支成立还需要：</strong>${(lineage.required_evidence || []).slice(0, 4).map(esc).join(" / ")}</p>` : ""}
        ${(lineage.uncertainty_reasons || []).length ? `
          <details>
            <summary>Branch lineage uncertainty (${fmt((lineage.uncertainty_reasons || []).length)})</summary>
            ${(lineage.uncertainty_reasons || []).slice(0, 5).map((reason) => `<p class="mini">${esc(reason)}</p>`).join("")}
          </details>
        ` : ""}
        ${renderEvidenceObjects(lineage.evidence_objects || [], 4)}
      </div>
    `;
  }).join("");
}

function renderStory() {
  els.storyPane.innerHTML = state.story.map((step) => `
    <div class="item">
      <button data-story="${esc(step.story_step_id)}">
        <strong>${esc(step.title || step.story_step_id)}</strong><br>
        <small>${esc(step.year_start || "")}-${esc(step.year_end || "")} / ${esc(step.focus_cluster_id || "")}</small>
        <p>${esc(step.narrative || "")}</p>
        <div class="pill-row">
          <span class="pill">${esc(step.claim_scope || "timeline_context_only")}</span>
          <span class="pill">${esc(step.evidence_grade || "metadata_cluster_timeline_context")}</span>
        </div>
        ${(step.required_evidence || []).length ? `<p class="mini"><strong>叙事成立还需要：</strong>${(step.required_evidence || []).slice(0, 4).map(esc).join(" / ")}</p>` : ""}
        ${(step.uncertainty_reasons || []).length ? `
          <details>
            <summary>Story uncertainty (${fmt((step.uncertainty_reasons || []).length)})</summary>
            ${(step.uncertainty_reasons || []).slice(0, 5).map((reason) => `<p class="mini">${esc(reason)}</p>`).join("")}
          </details>
        ` : ""}
        ${renderEvidenceObjects(step.evidence_objects || [], 5)}
      </button>
    </div>
  `).join("") || '<div class="item">Story steps are not materialized yet.</div>';
}

function renderLocalEdges(edges = []) {
  const items = asArray(edges).slice(0, 6);
  if (!items.length) return "<small>0 loaded. No local edge context is available yet.</small>";
  return `
    <div class="evidence-list">
      ${items.map((edge) => {
        const edgeScore = edge.confidence == null ? "-" : pct(edge.confidence);
        return `
          <div class="evidence-paper">
            <strong>${esc(edge.edge_type || edge.layer || "edge")}</strong>
            <small>${esc(edge.source_paper_id || "?")} -> ${esc(edge.target_paper_id || "?")} / weight ${fmt(edge.weight || 0)} / edge score ${edgeScore}</small>
            <div class="pill-row">
              <span class="pill">${esc(edge.claim_scope || "graph_edge_context_only")}</span>
              <span class="pill">${esc(edge.evidence_grade || "visual_edge_context")}</span>
            </div>
            ${(edge.uncertainty_reasons || []).length ? `<p class="mini">Edge uncertainty: ${(edge.uncertainty_reasons || []).slice(0, 2).map(esc).join(" / ")}</p>` : ""}
            ${(edge.required_evidence || []).length ? `<p class="mini"><strong>作为结论还需要：</strong>${(edge.required_evidence || []).slice(0, 3).map(esc).join(" / ")}</p>` : ""}
            ${renderEvidenceObjects(edge.evidence_objects || [], 2)}
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderLimitations(limitations = []) {
  const items = asArray(limitations).slice(0, 8);
  if (!items.length) return "<p>No limitation atoms yet.</p>";
  return `
    <div class="evidence-list">
      ${items.map((lim) => `
        <div class="evidence-paper">
          <strong>${esc(lim.keyword || "limitation")}</strong>
          <p>${esc(lim.description || JSON.stringify(lim))}</p>
          <div class="pill-row">
            <span class="pill">${esc(lim.claim_scope || "weak_bottleneck_hypothesis")}</span>
            <span class="pill">${esc(lim.evidence_grade || "metadata_or_abstract_limitation_context")}</span>
            ${lim.is_resolved ? `<span class="pill good">partially resolved</span>` : `<span class="pill warn">unresolved context</span>`}
          </div>
          <small>${esc(lim.paper_id || "")} / section ${esc(lim.source_section_name || "-")} / evidence ${esc(lim.evidence_quality || "unknown")}</small>
          ${(lim.uncertainty_reasons || []).length ? `<p class="mini">Limitation uncertainty: ${(lim.uncertainty_reasons || []).slice(0, 3).map(esc).join(" / ")}</p>` : ""}
          ${(lim.required_evidence || []).length ? `<p class="mini"><strong>作为结论还需要：</strong>${(lim.required_evidence || []).slice(0, 3).map(esc).join(" / ")}</p>` : ""}
          ${renderEvidenceObjects(lim.evidence_objects || [], 3)}
        </div>
      `).join("")}
    </div>
  `;
}

function renderPaper(paper, edges = []) {
  if (!paper) {
    els.paperPane.innerHTML = '<div class="item">Select a paper from the graph or Topic Lens.</div>';
    return;
  }
  const ids = paper.ids || {};
  const localContent = paper.local_content || {};
  const availability = paper.content_availability || {};
  const paperRole = paper.paper_role || {};
  const visualRole = paperRole.role || paper.visual_role || paper.visual?.role || "paper";
  const sections = [
    ...asArray(localContent.decision_evidence_sections),
    ...asArray(localContent.sections),
  ].slice(0, 6);
  const edgeCounts = paperRole.edge_counts_by_layer || {};
  state.selected = paper;
  els.paperPane.innerHTML = `
    <div class="item">
      <strong>${esc(paper.title || paper.paper_id)}</strong>
      <div class="paper-meta">${esc(paper.paper_id)} / ${esc(paper.year || "year unknown")} / ${esc(paper.cluster_label || "")}</div>
      <div class="pill-row">
        <span class="pill">${esc(visualRole)}</span>
        <span class="pill">branch ${esc(paper.branch_id || "-")}</span>
      </div>
    </div>
    <div class="item important">
      <div class="paper-meta">为什么给你看这篇</div>
      ${(paperRole.why_selected || [paper.reason?.why]).filter(Boolean).map((why) => `<p>${esc(why)}</p>`).join("") || "<p>Topic Lens / graph neighborhood selected this paper.</p>"}
      <div class="pill-row">
        <span class="pill">${esc(paperRole.claim_scope || "retrieval_context_only")}</span>
        <span class="pill">${esc(paperRole.evidence_grade || "metadata_search_context")}</span>
      </div>
      <div class="pill-row">
        ${Object.entries(edgeCounts).map(([layer, n]) => `<span class="pill">${esc(layer)} ${fmt(n)}</span>`).join("")}
      </div>
      <p class="mini">${esc(paperRole.evidence_gap || "")}</p>
      ${(paperRole.required_evidence || []).length ? `<p class="mini"><strong>作为结论还需要：</strong>${(paperRole.required_evidence || []).slice(0, 4).map(esc).join(" / ")}</p>` : ""}
      ${(paperRole.uncertainty_reasons || []).length ? `
        <details>
          <summary>Paper role uncertainty (${fmt((paperRole.uncertainty_reasons || []).length)})</summary>
          ${(paperRole.uncertainty_reasons || []).slice(0, 5).map((reason) => `<p class="mini">${esc(reason)}</p>`).join("")}
        </details>
      ` : ""}
      ${renderEvidenceObjects(paperRole.evidence_objects || [], 5)}
      ${paper.reason ? `<p class="mini">选择依据：${esc(paper.reason.why || "")} ${esc(paper.reason.role || "")} / ${esc(paper.reason.relationship_scope || "")}</p>` : ""}
    </div>
    <div class="item">
      <div class="paper-meta">IDs</div>
      <small>DOI: ${esc(ids.doi || "-")}<br>arXiv: ${esc(ids.arxiv_id || "-")}<br>OpenAlex: ${esc(ids.openalex_work_id || "-")}</small>
    </div>
    <div class="item">
      <div class="paper-meta">Local content</div>
      <small>${renderLocalContent(localContent, availability)}<br>storage: ${esc(paper.storage_policy || "metadata_only")}</small>
    </div>
    <div class="item">
      <div class="paper-meta">Access</div>
      ${renderAccessLinks(paper.access_links || [])}
    </div>
    <div class="item">
      <div class="paper-meta">Abstract</div>
      <p>${esc(paper.abstract || "No abstract available.")}</p>
    </div>
    <div class="item">
      <div class="paper-meta">Evidence sections</div>
      ${sections.map((section) => renderSectionEvidence(section)).join("") || "<p>No local section evidence yet. 当前只能用 abstract/metadata，不能作为强证据。</p>"}
    </div>
    <div class="item">
      <div class="paper-meta">Limitations</div>
      ${renderLimitations(paper.limitations || [])}
    </div>
    <div class="item">
      <div class="paper-meta">Local edges</div>
      <small>${edges.length} loaded</small>
      ${renderLocalEdges(edges)}
    </div>
  `;
  uploadNodes();
  draw();
}

function collectTopicIds(lens) {
  const ids = new Set();
  for (const p of lens?.related_papers || []) ids.add(p.paper_id);
  for (const p of lens?.history_main_path?.key_turning_papers || []) ids.add(p.paper_id);
  for (const lim of lens?.unresolved_limitations || []) ids.add(lim.paper_id);
  for (const edge of lens?.future_growth?.candidate_edges || []) {
    ids.add(edge.source_paper_id);
    ids.add(edge.target_paper_id);
  }
  for (const direction of lens?.future_growth?.future_directions || []) {
    for (const pid of asArray(direction.paper_ids_json)) ids.add(pid);
  }
  return ids;
}

function renderPaperList(papers, limit = 12) {
  return (papers || []).slice(0, limit).map((paper) => `
    <div class="item">
      <button data-paper="${esc(paper.paper_id)}">
        <strong>${esc(paper.title || paper.paper_id)}</strong><br>
        <small>${esc(paper.paper_id)} / ${esc(paper.year || "?")} / ${esc(paper.cluster_label || paper.cluster_id || "")}</small>
      </button>
      ${(paper.claim_scope || paper.evidence_grade) ? `
        <div class="pill-row">
          <span class="pill">${esc(paper.claim_scope || "claim scope unknown")}</span>
          <span class="pill">${esc(paper.evidence_grade || "evidence unknown")}</span>
        </div>
      ` : ""}
      ${paper.reason ? `<p class="mini">为什么关键：${esc(paper.reason.why || "")} ${esc(paper.reason.role || "")} / scope ${esc(paper.reason.relationship_scope || "graph")}</p>` : ""}
      ${(paper.uncertainty_reasons || []).length ? `<p class="mini">不确定性：${(paper.uncertainty_reasons || []).slice(0, 2).map(esc).join(" / ")}</p>` : ""}
      ${(paper.required_evidence || []).length ? `<p class="mini"><strong>作为结论还需要：</strong>${(paper.required_evidence || []).slice(0, 3).map(esc).join(" / ")}</p>` : ""}
      ${renderEvidenceObjects(paper.evidence_objects || [], 2)}
      ${Array.isArray(paper.access_links) && paper.access_links.length ? `<p class="mini">可访问：${paper.access_links.slice(0, 3).map((link) => `<a href="${esc(link.url)}" target="_blank" rel="noreferrer">${esc(link.label)}</a>`).join(" / ")}</p>` : ""}
    </div>
  `).join("");
}

function paperLabel(paper, fallback) {
  if (!paper) return fallback || "";
  const title = paper.title || paper.paper_id || fallback || "";
  const year = paper.year ? ` (${paper.year})` : "";
  return `${title}${year}`;
}

function renderTopicDossier(dossier = {}) {
  const strength = dossier.evidence_strength || {};
  const splits = dossier.branch_splits || [];
  const bottlenecks = dossier.hard_bottlenecks || [];
  const directions = dossier.validation_directions || [];
  const readingPath = dossier.reading_path || [];
  const solved = dossier.solved_vs_open || {};
  const insufficient = dossier.insufficient_evidence || [];
  return `
    <div class="dossier-hero">
      <strong>${esc(dossier.headline || "Topic dossier is being assembled.")}</strong>
      ${dossier.value_claim ? `<p class="value-claim">${esc(dossier.value_claim)}</p>` : ""}
      <p>${esc(dossier.decision_summary || "")}</p>
      <div class="pill-row">
        <span class="pill">${esc(dossier.claim_scope || "claim_scope unknown")}</span>
        <span class="pill">${esc(dossier.evidence_grade || "evidence unknown")}</span>
      </div>
      ${dossier.uncertainty_reasons?.length ? `
        <details class="insufficient-evidence" open>
          <summary>不确定性 / 为什么不能过度解读 (${fmt(dossier.uncertainty_reasons.length)})</summary>
          ${dossier.uncertainty_reasons.map((reason) => `<p><small>${esc(reason)}</small></p>`).join("")}
        </details>
      ` : ""}
      <div class="score-row">
        <span class="score"><small>主路径证据</small><strong>${fmt(strength.main_path_context_edges || 0)}</strong></span>
        <span class="score"><small>未来候选</small><strong>${fmt(strength.future_candidate_edges || 0)}</strong></span>
        <span class="score"><small>Section 覆盖</small><strong>${pct(strength.primary_section_coverage_in_results || 0)}</strong></span>
        <span class="score"><small>Limitation 覆盖</small><strong>${pct(strength.limitation_atom_coverage_in_results || 0)}</strong></span>
      </div>
      <div class="pill-row">
        ${(dossier.branch_labels || []).slice(0, 4).map((x) => `<span class="pill">${esc(x)}</span>`).join("")}
        ${(dossier.core_bottlenecks || []).slice(0, 5).map((x) => `<span class="pill warn">${esc(x)}</span>`).join("")}
      </div>
      <p class="mini">${esc(dossier.warning || "")}</p>
      ${renderEvidenceObjects(dossier.evidence_objects || [], 10)}
      ${insufficient.length ? `
        <details class="insufficient-evidence">
          <summary>证据不足，不作为强结论 (${fmt(insufficient.length)})</summary>
          ${insufficient.map((item) => `
            <p><strong>${esc(item.claim || "claim")}</strong><br>
            <small>${esc(item.reason || "")} / 需要：${esc(item.needed || "")}</small></p>
          `).join("")}
        </details>
      ` : ""}
    </div>
    <div class="item important">
      <div class="paper-meta">推荐阅读路径</div>
      <p class="mini">不是通用论文推荐，而是按“先建立上下文、再读转折、再审分支和卡点、最后看未来候选”的证据路径。每一步都说明为什么推荐，以及它不能说明什么。</p>
      ${readingPath.slice(0, 6).map((item) => `
        <div class="branch-card">
          <strong>${esc(item.title || item.mode || "reading step")}</strong>
          <div class="pill-row">
            <span class="pill">${esc(item.mode || "reading")}</span>
            <span class="pill">${esc(item.claim_scope || "claim scope unknown")}</span>
            <span class="pill">${esc(item.evidence_grade || "evidence unknown")}</span>
          </div>
          <p>${esc(item.why || "")}</p>
          ${(item.can_explain || []).length ? `<p class="mini"><strong>能说明：</strong>${(item.can_explain || []).slice(0, 3).map(esc).join(" / ")}</p>` : ""}
          ${(item.cannot_explain || []).length ? `<p class="mini"><strong>不能说明：</strong>${(item.cannot_explain || []).slice(0, 3).map(esc).join(" / ")}</p>` : ""}
          ${(item.required_evidence || []).length ? `<p class="mini"><strong>需要证据：</strong>${(item.required_evidence || []).slice(0, 4).map(esc).join(" / ")}</p>` : ""}
          ${(item.uncertainty_reasons || []).length ? `
            <details>
              <summary>阅读路径不确定性 (${fmt((item.uncertainty_reasons || []).length)})</summary>
              ${(item.uncertainty_reasons || []).map((reason) => `<p class="mini">${esc(reason)}</p>`).join("")}
            </details>
          ` : ""}
          ${evidencePaperButtons(item.papers || [], 5)}
          ${renderEvidenceObjects(item.evidence_objects || [], 6)}
        </div>
      `).join("") || "<p>No evidence-backed reading path yet.</p>"}
    </div>
    <div class="item important">
      <div class="paper-meta">当前真实分支</div>
      ${splits.slice(0, 7).map((split) => `
        <div class="branch-card">
          <strong>${esc(split.name)}</strong>
          <small>${fmt(split.paper_count || 0)} papers / first seen ${esc(split.first_seen_year || "?")}</small>
          <div class="pill-row">
            <span class="pill ${split.lineage_status === "evidence_backed_split" ? "good" : "warn"}">${esc(split.lineage_status || "weak_split_candidate")}</span>
            <span class="pill">${esc(split.claim_scope || "branch claim scope unknown")}</span>
            <span class="pill">${esc(split.evidence_grade || "branch evidence unknown")}</span>
          </div>
          <p class="mini">parent ${esc(split.parent_branch_id || "unverified")} / split ${esc(split.split_year || "-")} / support ${pct(split.split_confidence || 0)}</p>
          <p><strong>为什么出现：</strong>${esc(split.why_appeared || "")}</p>
          ${split.split_reason ? `<p><strong>分叉证据：</strong>${esc(split.split_reason)}</p>` : ""}
          <p><strong>历史卡点：</strong>${esc(split.historical_bottleneck || "")}</p>
          <p><strong>使能条件：</strong>${esc(split.enabling_condition || "")}</p>
          ${(split.required_evidence || []).length ? `<p class="mini"><strong>成为真实分支还需要：</strong>${(split.required_evidence || []).slice(0, 4).map(esc).join(" / ")}</p>` : ""}
          ${(split.uncertainty_reasons || []).length ? `
            <details>
              <summary>分支证据不确定性 (${fmt((split.uncertainty_reasons || []).length)})</summary>
              ${(split.uncertainty_reasons || []).map((reason) => `<p class="mini">${esc(reason)}</p>`).join("")}
            </details>
          ` : ""}
          ${evidencePaperButtons(split.driver_papers || [], 3)}
          ${renderEvidenceObjects(split.evidence_objects || [], 5)}
        </div>
      `).join("") || "<p>No interpretable branch split has enough evidence yet.</p>"}
    </div>
    <div class="item important">
      <div class="paper-meta">硬卡点：已部分解决 vs 仍未解决</div>
      <p><strong>仍未解决：</strong>${esc((solved.still_open || []).slice(0, 6).join(" / ") || "N/A")}</p>
      <p><strong>部分解决：</strong>${esc((solved.partially_addressed || []).slice(0, 6).join(" / ") || "等待 section-level resolution 证据")}</p>
      <p class="mini">${esc(solved.rule || "")}</p>
      ${bottlenecks.slice(0, 6).map((b) => `
        <div class="branch-card bottleneck-card">
          <strong>${esc(b.name)}</strong>
          <small>${fmt(b.evidence_count || 0)} evidence atoms / ${esc(b.evidence_grade || b.evidence_quality || "unknown")}</small>
          <div class="pill-row">
            <span class="pill ${b.resolution_status === "open_no_resolution_evidence" ? "warn" : "good"}">${esc(b.resolution_status || "resolution unknown")}</span>
            <span class="pill">${esc(b.claim_scope || "weak_bottleneck_hypothesis")}</span>
            <span class="pill">${esc(b.evidence_grade || "evidence unknown")}</span>
          </div>
          <p class="mini">open atoms ${fmt(b.unresolved_evidence_count || 0)} / resolution atoms ${fmt(b.resolved_evidence_count || 0)}</p>
          <p>${esc(b.why_it_matters || "")}</p>
          ${(b.uncertainty_reasons || []).length ? `
            <details>
              <summary>证据不确定性 (${fmt((b.uncertainty_reasons || []).length)})</summary>
              ${(b.uncertainty_reasons || []).map((reason) => `<p class="mini">${esc(reason)}</p>`).join("")}
            </details>
          ` : ""}
          ${evidencePaperButtons(b.evidence_papers || [], 4)}
          ${renderEvidenceObjects(b.evidence_objects || [], 6)}
        </div>
      `).join("") || "<p>No bottleneck evidence matched.</p>"}
    </div>
    <div class="item important">
      <div class="paper-meta">未来 6-18 个月值得验证的方向</div>
      ${directions.slice(0, 5).map((d) => `
        <div class="branch-card direction-card">
          <strong>${esc(d.name)}</strong>
          <small>${esc(d.claim_scope || "exploratory")} / evidence ${esc(d.evidence_grade || d.evidence_strength || "unknown")} / ${esc(d.source || "")}</small>
          <div class="pill-row">
            <span class="pill">${esc(d.claim_scope || "exploratory")}</span>
            <span class="pill">${esc(d.evidence_grade || "evidence unknown")}</span>
          </div>
          <p><strong>为什么值得试：</strong>${esc(d.why_worth_testing || "")}</p>
          ${d.why_not_ready ? `<p><strong>为什么还不能下注：</strong>${esc(d.why_not_ready)}</p>` : ""}
          ${d.minimal_validation_experiment ? `<p><strong>最小验证实验：</strong>${esc(d.minimal_validation_experiment)}</p>` : ""}
          ${(d.can_explain || []).length ? `<p class="mini"><strong>能说明：</strong>${(d.can_explain || []).slice(0, 3).map(esc).join(" / ")}</p>` : ""}
          ${(d.cannot_explain || []).length ? `<p class="mini"><strong>不能说明：</strong>${(d.cannot_explain || []).slice(0, 3).map(esc).join(" / ")}</p>` : ""}
          ${(d.required_evidence || []).length ? `<p class="mini"><strong>进入 Radar 还需要：</strong>${(d.required_evidence || []).slice(0, 4).map(esc).join(" / ")}</p>` : ""}
          ${(d.uncertainty_reasons || []).length ? `
            <details>
              <summary>为什么仍需谨慎 (${fmt((d.uncertainty_reasons || []).length)})</summary>
              ${(d.uncertainty_reasons || []).map((reason) => `<p class="mini">${esc(reason)}</p>`).join("")}
            </details>
          ` : ""}
          ${evidencePaperButtons(d.evidence_papers || [], 5)}
          ${renderEvidenceObjects(d.evidence_objects || [], 6)}
        </div>
      `).join("") || "<p>No validation direction has enough evidence yet.</p>"}
    </div>
  `;
}

function renderBranchDossiers(branches = []) {
  return `
    <div class="item">
      <div class="paper-meta">Branch Dossier</div>
      <p class="mini">先看分支，而不是先看点。每个分支都要回答：它是什么、从哪里裂变、由哪些论文推动、证据强度如何。</p>
      ${branches.slice(0, 6).map((branch) => `
        <div class="branch-card">
          <strong>${esc(branch.label || branch.cluster_id)}</strong>
          <small>${esc(branch.cluster_id || "")} / ${esc(branch.branch_id || "")} / topic share ${pct(branch.topic_share || 0)} / ${esc((branch.year_range || []).join("-"))}</small>
          <div class="pill-row">
            <span class="pill ${branch.lineage_status === "evidence_backed_split" ? "good" : "warn"}">${esc(branch.lineage_status || "weak_branch_hypothesis")}</span>
            <span class="pill">${esc(branch.claim_scope || "weak_branch_hypothesis")}</span>
            <span class="pill">${esc(branch.evidence_grade || "branch evidence unknown")}</span>
          </div>
          <p>${esc(branch.interpretation || "")}</p>
          ${branch.split_reason ? `<p><strong>分叉证据：</strong>${esc(branch.split_reason)}</p>` : ""}
          ${branch.constraint_shift ? `<p class="mini"><strong>约束变化：</strong>${esc(branch.constraint_shift.status || "")} ${esc(branch.constraint_shift.note || "")}</p>` : ""}
          ${(branch.required_evidence || []).length ? `<p class="mini"><strong>成为真实分叉还需要：</strong>${(branch.required_evidence || []).slice(0, 4).map(esc).join(" / ")}</p>` : ""}
          ${(branch.uncertainty_reasons || []).length ? `
            <details>
              <summary>分支证据不确定性 (${fmt((branch.uncertainty_reasons || []).length)})</summary>
              ${(branch.uncertainty_reasons || []).map((reason) => `<p class="mini">${esc(reason)}</p>`).join("")}
            </details>
          ` : ""}
          <div class="pill-row">
            ${(branch.top_terms || []).slice(0, 6).map((term) => `<span class="pill">${esc(term)}</span>`).join("")}
          </div>
          <p class="mini">parent ${esc(branch.parent_branch_id || "-")} / split ${esc(branch.split_year || "-")} / support ${pct(branch.split_confidence || 0)}</p>
          ${(branch.driver_papers || []).length ? `<p><strong>Driver papers</strong></p>${renderPaperList(branch.driver_papers || [], 3)}` : ""}
          ${renderEvidenceObjects(branch.evidence_objects || [], 5)}
          <p><strong>Representative papers</strong></p>
          ${renderPaperList(branch.representative_papers || [], 3)}
        </div>
      `).join("") || "<p>No branch dossiers matched.</p>"}
    </div>
  `;
}

function renderBottleneckLineage(lineage = {}) {
  const constraints = lineage.constraints || [];
  return `
    <div class="item">
      <div class="paper-meta">Bottleneck Lineage</div>
      <p>${esc(lineage.summary || "")}</p>
      <div class="pill-row">
        ${(lineage.top_unresolved_keywords || []).slice(0, 8).map((x) => `<span class="pill warn">${esc(x.keyword)} ${fmt(x.count)}</span>`).join("")}
      </div>
      ${constraints.slice(0, 4).map((c) => `
        <div class="claim">
          <strong>${esc(c.name || c.principle_id)}</strong>
          <p>${esc(c.root_cause || "")}</p>
          <small>risk ${esc(c.risk_label || "unknown")} / unresolved ${fmt(c.unresolved_atoms || 0)} / resolved ${fmt(c.resolved_atoms || 0)} / peak ${esc(c.peak_backlog_year || "-")}</small>
          <div class="pill-row">
            <span class="pill">${esc(c.claim_scope || "lineage scope unknown")}</span>
            <span class="pill">${esc(c.evidence_grade || "lineage evidence unknown")}</span>
          </div>
          <div class="pill-row">${(c.top_keywords || []).slice(0, 5).map((kw) => `<span class="pill">${esc(kw)}</span>`).join("")}</div>
          ${(c.can_explain || []).length ? `<p class="mini"><strong>能说明：</strong>${(c.can_explain || []).slice(0, 3).map(esc).join(" / ")}</p>` : ""}
          ${(c.cannot_explain || []).length ? `<p class="mini"><strong>不能说明：</strong>${(c.cannot_explain || []).slice(0, 3).map(esc).join(" / ")}</p>` : ""}
          ${(c.typed_chain || []).length ? `
            <details>
              <summary>Typed lineage chain (${fmt((c.typed_chain || []).length)})</summary>
              ${(c.typed_chain || []).slice(0, 4).map((t) => `
                <p class="mini">
                  <strong>${esc(t.source_stage || "constraint")} → ${esc(t.target_stage || "next")}</strong>
                  ${esc(t.target_text || t.source_text || "")}
                  <br><small>${esc(t.event_year || "-")} / ${esc(t.evidence_section || "section unknown")} / ${esc(t.evidence_quality || "evidence unknown")}</small>
                </p>
              `).join("")}
            </details>
          ` : ""}
          ${(c.required_evidence || []).length ? `<p class="mini"><strong>需要证据：</strong>${(c.required_evidence || []).slice(0, 3).map(esc).join(" / ")}</p>` : ""}
          ${(c.uncertainty_reasons || []).length ? `
            <details>
              <summary>证据不确定性 (${fmt((c.uncertainty_reasons || []).length)})</summary>
              ${(c.uncertainty_reasons || []).map((reason) => `<p class="mini">${esc(reason)}</p>`).join("")}
            </details>
          ` : ""}
          ${renderEvidenceObjects(c.evidence_objects || [], 5)}
        </div>
      `).join("") || "<p>No bottleneck lineage matched.</p>"}
    </div>
  `;
}

function renderDossierRadar(radar = {}) {
  const claimCards = radar.claim_cards || [];
  const candidatePool = radar.candidate_pool || [];
  return `
    <div class="item">
      <div class="paper-meta">Claim Card / R&D Radar</div>
      <p>${esc(radar.summary || "")}</p>
      ${claimCards.length ? claimCards.slice(0, 5).map((item) => `
        <div class="branch-card">
          <strong>${esc(item.title || "candidate")}</strong>
          <div class="score-row">
            <span class="score"><small>优先级</small><strong>${pct(item.priority || 0)}</strong></span>
            <span class="score"><small>候选分数</small><strong>${pct(item.candidate_score ?? 0)}</strong></span>
            <span class="score"><small>Claim scope</small><strong>${esc(item.claim_scope || "exploratory")}</strong></span>
            <span class="score"><small>High confidence</small><strong>${item.eligible ? "yes" : "no"}</strong></span>
          </div>
          <div class="pill-row">
            <span class="pill">${esc(item.claim_scope || "radar_claim_card")}</span>
            <span class="pill">${esc(item.evidence_grade || "claim-card evidence unknown")}</span>
          </div>
          <p>${esc(item.plain_language || "")}</p>
          ${item.claim_card ? renderClaimCard({ claim_card: item.claim_card }) : ""}
          ${(item.missing_gates || []).length ? `<p class="mini">五问缺口：${item.missing_gates.map(esc).join(" / ")}</p>` : ""}
          ${(item.missing_high_confidence_gates || []).length ? `<p class="mini">高置信缺口：${item.missing_high_confidence_gates.map(esc).join(" / ")}</p>` : ""}
          ${(item.required_evidence || []).length ? `<p class="mini"><strong>保持/提升 Radar 可信度还需要：</strong>${(item.required_evidence || []).slice(0, 5).map(esc).join(" / ")}</p>` : ""}
          ${(item.uncertainty_reasons || []).length ? `
            <details>
              <summary>Claim Card uncertainty (${fmt((item.uncertainty_reasons || []).length)})</summary>
              ${(item.uncertainty_reasons || []).map((reason) => `<p class="mini">${esc(reason)}</p>`).join("")}
            </details>
          ` : ""}
          ${renderEvidenceObjects(item.evidence_objects || [], 6)}
        </div>
      `).join("") : `
        <div class="branch-card warning-card">
          <strong>No complete Claim Cards yet</strong>
          <p>Radar 主视图不会展示裸 GNN 边，也不会展示五问不完整的卡。下面只放候选池，必须等 Step6/Step13 生成完整五问卡后才能进入 Radar。</p>
        </div>
      `}
      <details>
        <summary>Future candidate generator pool (${fmt(candidatePool.length)})</summary>
        ${candidatePool.slice(0, 8).map((item) => `
          <div class="candidate-card">
            <strong>${esc(item.title || "candidate edge")}</strong>
            <small>candidate score ${pct(item.candidate_score ?? 0)} / scope ${esc(item.claim_scope || "candidate")} / evidence ${esc(item.evidence_grade || "unknown")}</small>
            ${item.model_evidence ? `
              <p class="mini">模型证据：${esc(item.model_evidence.generator || "future candidate generator")}
              / ${esc(futureCalibrationCopy(item))}
              / ${esc(item.model_evidence.candidate_pool_reason || "candidate pool only")}</p>
            ` : ""}
            <p>${esc(item.plain_language || "")}</p>
            <p class="mini">缺口：${(item.missing_gates || []).map(esc).join(" / ")}</p>
            ${(item.uncertainty_reasons || []).length ? `<p class="mini">不确定性：${(item.uncertainty_reasons || []).slice(0, 3).map(esc).join(" / ")}</p>` : ""}
            ${evidencePaperButtons(item.evidence_papers || [], 2)}
            ${renderEvidenceObjects(item.evidence_objects || [], 4)}
          </div>
        `).join("") || "<p>No future candidates matched.</p>"}
      </details>
    </div>
  `;
}

function renderEvidenceMapSummary(evidence = {}) {
  const combos = evidence.recommended_layer_combinations || [];
  const mainPath = evidence.main_path || {};
  return `
    <div class="item">
      <div class="paper-meta">Evidence Map</div>
      <p>${esc(evidence.summary || "")}</p>
      ${mainPath.claim_scope || mainPath.evidence_grade ? `
        <div class="combo-card">
          <strong>Main-path evidence boundary</strong>
          <p>${esc(mainPath.meaning || "")}</p>
          <small>edges ${fmt(mainPath.metrics?.main_path_edges || 0)} / turning papers ${fmt(mainPath.metrics?.key_turning_papers || 0)} / linked refs ${pct(mainPath.metrics?.linked_ref_rate || 0)}</small>
          ${renderComboContract(mainPath)}
          ${renderEvidenceObjects(mainPath.evidence_objects || [], 4)}
        </div>
      ` : ""}
      ${combos.map((combo) => `
        <div class="combo-card">
          <strong>${esc(combo.label || (combo.layers || []).join(" + "))}</strong>
          <p>${esc(combo.question || "")}</p>
          <small>${esc((combo.layers || []).join(" + "))} / ${esc(combo.use || "")}</small>
          ${renderComboContract(combo)}
        </div>
      `).join("")}
    </div>
  `;
}

function renderTopicReadiness(readiness = {}) {
  if (!readiness || !readiness.readiness_level) return "";
  const metrics = readiness.metrics || {};
  const gates = readiness.gates || [];
  const problemGates = gates.filter((gate) => gate.status !== "pass");
  return `
    <div class="item important">
      <div class="paper-meta">Topic readiness</div>
      <div class="pill-row">
        <span class="pill ${readiness.overall_status === "pass" ? "good" : "warn"}">${esc(readiness.readiness_level)}</span>
        <span class="pill">${esc(readiness.overall_status || "unknown")}</span>
        <span class="pill">no LLM preflight</span>
      </div>
      <p class="mini">${esc(readiness.llm_policy || "")}</p>
      <div class="score-row">
        <span class="score"><small>branches</small><strong>${fmt(metrics.branch_splits || 0)}</strong></span>
        <span class="score"><small>bottlenecks</small><strong>${fmt(metrics.bottleneck_candidates || 0)}</strong></span>
        <span class="score"><small>traced turning</small><strong>${fmt(metrics.turning_with_strong_or_moderate_section_provenance || 0)}</strong></span>
        <span class="score"><small>complete cards</small><strong>${fmt(metrics.complete_claim_cards || 0)}</strong></span>
      </div>
      ${problemGates.length ? `
        <details open>
          <summary>Blocking / warning gates (${fmt(problemGates.length)})</summary>
          ${problemGates.map((gate) => `
            <p class="mini">${esc(gate.name)}: ${esc(gate.status)} (${fmt(gate.actual || 0)} / ${fmt(gate.required || 0)})</p>
          `).join("")}
        </details>
      ` : ""}
    </div>
  `;
}

function renderTopicLens(lens) {
  if (!lens) {
    els.topicPane.innerHTML = `
      <div class="dossier-hero">
        <strong>Topic Dossier first</strong>
        <p>输入一个 topic，例如 Metalens。第一屏会先给演化分支、历史卡点、转折论文、未解约束和可验证方向；右侧图谱用于审计这些判断，不是默认让你看星云。</p>
        <p class="mini">所有分支、卡点和方向都会尽量带可点击证据论文。没有 section/Claim Card 的结论会自动降级为 exploratory。</p>
      </div>
    `;
    return;
  }
  const clusters = (lens.cluster_distribution || []).slice(0, 8).map((cluster) => (
    `<span class="pill">${esc(cluster.cluster_id)} ${fmt(cluster.n || cluster.count || 0)}</span>`
  )).join("");
  const questions = lens.first_principles?.five_questions || [];
  const limitations = lens.unresolved_limitations || [];
  const futureEdges = lens.future_growth?.candidate_edges || [];
  const history = lens.history_main_path || {};
  const valueModel = lens.value_model || DEFAULT_VALUE_MODEL;
  const fusionCounts = valueModel.counts || {};
  const frontfill = valueModel.frontfill_status || {};
  els.topicPane.innerHTML = `
    ${renderTopicDossier(lens.topic_dossier || {})}
    ${renderTopicReadiness(lens.topic_readiness || {})}
    <div class="item">
      <strong>${esc(lens.topic)}</strong>
      <div class="paper-meta">Evidence scope: ${fmt(lens.total_related)} related papers / ${fmt(futureEdges.length)} future candidates / ${fmt(lens.history_main_path?.edges?.length || 0)} main-path context edges</div>
      <div class="pill-row">${clusters}</div>
      <p class="mini">scope: ${esc(lens.context?.scope || "direct_papers")} / seed matches ${fmt(lens.context?.seed_matches || lens.total_related)} / context papers ${fmt(lens.context?.context_papers || 0)}</p>
      <p class="mini">fusion: ${esc(valueModel.fusion_status || "unknown")} / directions ${fmt(fusionCounts.future_directions || 0)} / claim cards ${fmt(fusionCounts.claim_cards || 0)} / adequacy ${esc(fusionCounts.fusion_adequacy || "unknown")}</p>
      ${frontfill.available ? `
        <div class="frontfill-card">
          <strong>Evidence frontfill status</strong>
          <p>Primary section evidence: ${fmt(frontfill.primary_section_papers || 0)} papers. OpenAlex W coverage: ${pct(frontfill.openalex_w_rate || 0)}. ${esc(frontfill.interpretation || "")}</p>
          ${frontfill.high_value_delta_queue ? `<p class="mini">High-value delta queue missing primary section: ${fmt(frontfill.high_value_delta_queue.missing_primary_with_pdf || 0)} papers with accessible PDFs.</p>` : ""}
        </div>
      ` : ""}
    </div>
    ${renderBranchDossiers(lens.branch_dossiers || [])}
    ${renderBottleneckLineage(lens.bottleneck_lineage || {})}
    ${renderDossierRadar(lens.rd_radar || {})}
    ${renderEvidenceMapSummary(lens.evidence_map || {})}
    <div class="item">
      <div class="paper-meta">First principles</div>
      <div class="claim-grid">
        ${questions.map((qa) => `
          <div class="claim">
            <strong>${esc(qa.question || "")}</strong>
            <p>${esc(qa.answer || "")}</p>
            <div class="pill-row">
              <span class="pill">${esc(qa.claim_scope || "claim scope unknown")}</span>
              <span class="pill">${esc(qa.evidence_grade || "evidence unknown")}</span>
            </div>
            ${(qa.required_evidence || []).length ? `<p class="mini"><strong>需要证据：</strong>${(qa.required_evidence || []).slice(0, 4).map(esc).join(" / ")}</p>` : ""}
            ${(qa.uncertainty_reasons || []).length ? `
              <details>
                <summary>不确定性 (${fmt((qa.uncertainty_reasons || []).length)})</summary>
                ${(qa.uncertainty_reasons || []).slice(0, 5).map((reason) => `<p class="mini">${esc(reason)}</p>`).join("")}
              </details>
            ` : ""}
            ${renderEvidenceObjects(qa.evidence_objects || [], 5)}
          </div>
        `).join("") || "<p>No claim card evidence yet.</p>"}
      </div>
    </div>
    <div class="item">
      <div class="paper-meta">Key turning papers</div>
      <div class="pill-row">
        <span class="pill">${esc(history.claim_scope || "main path scope unknown")}</span>
        <span class="pill">${esc(history.evidence_grade || "main path evidence unknown")}</span>
      </div>
      <p class="mini">判定逻辑：这些论文位于该 topic 所属 cluster/branch 的 Main Path 高权重边上；优先按 main_path_weight 累计贡献排序。</p>
      <p class="mini">每篇都带 claim_scope/evidence_grade。broader field context 不能被当作该 topic 的关键转折论文。</p>
      ${(history.uncertainty_reasons || []).length ? `
        <details>
          <summary>Main-path uncertainty (${fmt((history.uncertainty_reasons || []).length)})</summary>
          ${(history.uncertainty_reasons || []).map((reason) => `<p class="mini">${esc(reason)}</p>`).join("")}
        </details>
      ` : ""}
      ${(history.required_evidence || []).length ? `<p class="mini"><strong>需要证据：</strong>${(history.required_evidence || []).slice(0, 4).map(esc).join(" / ")}</p>` : ""}
      ${renderEvidenceObjects(history.evidence_objects || [], 6)}
      ${renderPaperList(history.key_turning_papers || [], 8) || "<p>No main-path match.</p>"}
    </div>
    <div class="item">
      <div class="paper-meta">Future candidate generator pool</div>
      <p class="mini">这里是 Step5b GNN/VGAE 候选生成器，不是结论。只有经过 Step6 融合和 Step13 五问 Claim Card 的方向，才会进入 Radar 主视图。</p>
      ${futureEdges.slice(0, 8).map((edge) => `
        <p><strong>${esc(paperLabel(edge.source_paper, edge.source_paper_id))}</strong><br>
        <span class="mini">可能连接到</span><br>
        <strong>${esc(paperLabel(edge.target_paper, edge.target_paper_id))}</strong><br>
        <small>GNN/VGAE candidate score ${pct(edge.candidate_score ?? edge.confidence ?? edge.weight)} / ${esc(edge.evidence?.relationship_scope || "graph")}</small><br>
        <small>${esc(futureCalibrationCopy(edge))}</small><br>
        <small>${esc(edge.plain_language || "")}</small></p>
        <div class="pill-row">
          <span class="pill">${esc(edge.claim_scope || "candidate_pool_only")}</span>
          <span class="pill">${esc(edge.evidence_grade || "future candidate evidence unknown")}</span>
        </div>
        ${(edge.required_evidence || []).length ? `<p class="mini"><strong>进入 Radar 还需要：</strong>${(edge.required_evidence || []).slice(0, 4).map(esc).join(" / ")}</p>` : ""}
        ${(edge.uncertainty_reasons || []).length ? `
          <details>
            <summary>Future edge uncertainty (${fmt((edge.uncertainty_reasons || []).length)})</summary>
            ${(edge.uncertainty_reasons || []).slice(0, 5).map((reason) => `<p class="mini">${esc(reason)}</p>`).join("")}
          </details>
        ` : ""}
        ${evidencePaperButtons([edge.source_paper, edge.target_paper].filter(Boolean), 2)}
        ${renderEvidenceObjects(edge.evidence_objects || [], 4)}
      `).join("") || "<p>No future edge matched this topic context yet.</p>"}
    </div>
    <div class="item">
      <div class="paper-meta">Unresolved bottlenecks</div>
      ${renderLimitations(limitations)}
    </div>
    <div class="item">
      <div class="paper-meta">Related papers</div>
      ${renderPaperList(lens.related_papers || [], 12) || "<p>No matches.</p>"}
    </div>
  `;
}

function validationCost(direction) {
  const experiment = direction.claim_card?.minimal_validation_experiment || {};
  const level = String(experiment.cost_level || "").toLowerCase();
  if (level.includes("low")) return 0.35;
  if (level.includes("high")) return 0.9;
  if (level.includes("medium")) return 0.6;
  const weeks = Number(experiment.cycle_weeks);
  if (Number.isFinite(weeks) && weeks > 0) return clamp(weeks / 26, 0.25, 0.95);
  return 0.65;
}

function radarScore(direction) {
  const candidateScore = clamp(Number(direction.candidate_score ?? direction.confidence ?? direction.weight ?? 0.45), 0, 1);
  const commercial = clamp(Number(direction.commercial_relevance || direction.market_relevance || 0.5), 0, 1);
  const cost = validationCost(direction);
  return clamp((candidateScore * (0.55 + commercial)) / (0.65 + cost), 0, 1);
}

function renderClaimCard(direction) {
  const card = direction.claim_card || {};
  const root = card.root_constraint || {};
  const attempts = card.attempts_last_10y || [];
  const enabling = card.enabling_conditions || {};
  const bottleneck = card.unresolved_bottleneck || {};
  const experiment = card.minimal_validation_experiment || {};
  const attemptText = attempts.slice(0, 3).map((x) => `${x.year || "?"}: ${x.keyword || x.attempt || "attempt"}`).join("; ");
  const bottleneckItems = asArray(bottleneck.items).map((x) => x.keyword || x.description).filter(Boolean).slice(0, 3).join("; ");
  const successCriteria = asArray(experiment.success_criteria).slice(0, 2).join("; ");
  const falsification = asArray(experiment.falsification_conditions).slice(0, 2).join("; ");
  return `
    <div class="claim-grid">
      <div class="claim"><strong>Root constraint</strong><p>${esc(root.constraint || root.type || "N/A")}</p></div>
      <div class="claim"><strong>Last 10 years</strong><p>${esc(attemptText || "N/A")}</p></div>
      <div class="claim"><strong>New enablers</strong><p>${esc(asArray(enabling.new_enablers).join("; ") || "N/A")}</p></div>
      <div class="claim"><strong>Open bottleneck</strong><p>${esc(bottleneckItems || bottleneck.keyword || "N/A")} <small>${esc(card.evidence_strength_level || "unknown")}</small></p></div>
      <div class="claim"><strong>Minimal validation</strong><p>${esc(experiment.experiment || "N/A")} <small>${esc(experiment.cost_level || "-")} / ${esc(experiment.cycle_weeks || "-")} weeks</small></p></div>
      <div class="claim"><strong>Success criteria</strong><p>${esc(successCriteria || "N/A")}</p></div>
      <div class="claim"><strong>Falsification</strong><p>${esc(falsification || "N/A")}</p></div>
    </div>
  `;
}

function renderRadar(lens = state.topicLens) {
  if (lens?.rd_radar) {
    els.radarPane.innerHTML = renderDossierRadar(lens.rd_radar);
    return;
  }
  els.radarPane.innerHTML = `
    <div class="item">
      <strong>Radar requires a Topic Dossier</strong>
      <div class="paper-meta">Claim Card gated view</div>
      <p class="mini">Radar 主视图只渲染完整 Step13 Claim Card。请选择 topic 生成 Dossier；裸 GNN/VGAE future edges 只能在 Future candidate generator pool 或 candidate pool 中审计。</p>
    </div>
  `;
}

function buildSearchFallbackTopicLens(text, hits = []) {
  const fallbackUncertainty = [
    "Topic Lens API route was unavailable; this is semantic retrieval only",
    "No branch lineage, bottleneck lineage, main-path, Step6 fusion, or Step13 Claim Card was generated for this topic",
    "No LLM preflight was used",
  ];
  const papers = (hits || []).map((hit) => ({
    ...hit,
    claim_scope: hit.claim_scope || "retrieval_context_only",
    evidence_grade: hit.evidence_grade || "metadata_search_hit",
    uncertainty_reasons: Array.from(new Set([
      ...asArray(hit.uncertainty_reasons),
      "semantic search hit is not a Topic Dossier conclusion",
    ])),
  }));
  const evidenceObjects = papers.slice(0, 8).map((paper) => ({
    type: "paper",
    role: "semantic_search_fallback_hit",
    source: "visual_search",
    paper_id: paper.paper_id,
    title: paper.title || paper.paper_id,
    claim_scope: "retrieval_context_only",
    evidence_grade: "metadata_search_hit",
    description: "Search-only fallback evidence object. It can guide reading, but cannot support branch, bottleneck, or Radar claims.",
  }));
  const retrievalGrade = evidenceObjects.length ? "metadata_search_hits" : "insufficient";
  const readingPapers = papers.slice(0, 6).map((paper) => ({
    ...paper,
    why: "semantic search match; not evidence-backed Topic Dossier evidence",
  }));
  const readinessGates = [
    ["topic dossier evidence contract", "fail", 0, 1],
    ["bottleneck lineage typed contracts", "fail", 0, 1],
    ["complete Claim Cards", "fail", 0, 1],
    ["auditable reading path", readingPapers.length ? "warn" : "fail", readingPapers.length, 4],
  ].map(([name, status, actual, required]) => ({ name, status, actual, required }));
  return {
    topic: text,
    related_papers: papers,
    total_related: papers.length,
    cluster_distribution: [],
    topic_dossier: {
      headline: `${text} is in search-only fallback mode`,
      value_claim: "The only safe next action is to inspect retrieved papers or restore the Topic Lens route, then rerun the V14B evidence chain.",
      decision_summary: "This fallback is intentionally insufficient evidence. It does not infer real branches, bottlenecks, turning papers, or future directions.",
      claim_scope: "insufficient_evidence",
      evidence_grade: "insufficient",
      uncertainty_reasons: fallbackUncertainty,
      claim_policy: "Search fallback cannot promote claims. It must stay retrieval_context_only until the Topic Dossier API returns evidence contracts.",
      branch_splits: [],
      hard_bottlenecks: [],
      validation_directions: [],
      reading_path: [
        {
          mode: "fallback_retrieval",
          title: "Search-only papers",
          why: "These papers are semantic search results. Use them to recover context, not as evidence-backed branch or direction claims.",
          claim_scope: "retrieval_context_only",
          evidence_grade: retrievalGrade,
          uncertainty_reasons: fallbackUncertainty,
          required_evidence: [
            "Topic Lens API route",
            "main-path context",
            "section-level bottleneck evidence",
            "Step6/Step13 Claim Card generation",
          ],
          can_explain: ["which papers matched the fallback retrieval query"],
          cannot_explain: ["real branch splits", "key turning papers", "unresolved bottlenecks", "future direction value"],
          papers: readingPapers,
          evidence_objects: evidenceObjects,
        },
      ],
      evidence_objects: evidenceObjects,
      insufficient_evidence: [
        {
          claim: "Topic Dossier",
          reason: "semantic search fallback has no branch, bottleneck, lineage, calibration, or Claim Card synthesis",
          needed: "/graph/visual/topic-lens route plus current V14B product-chain outputs",
        },
        {
          claim: "R&D Radar direction",
          reason: "no complete Step13 five-question Claim Card was produced",
          needed: "Step6 fusion and Step13 Claim Card engine",
        },
      ],
      solved_vs_open: {
        still_open: [],
        partially_addressed: [],
        rule: "Search fallback cannot classify solved vs open bottlenecks.",
      },
      warning: "Search fallback is retrieval-only and must not be read as a scientific conclusion.",
    },
    topic_readiness: {
      audit_type: "ui_search_fallback_readiness",
      readiness_level: "insufficient_evidence",
      overall_status: "fail",
      llm_policy: "No LLM preflight; fallback is deterministic retrieval only.",
      metrics: {
        branch_splits: 0,
        bottleneck_candidates: 0,
        turning_with_strong_or_moderate_section_provenance: 0,
        complete_claim_cards: 0,
      },
      gates: readinessGates,
    },
    history_main_path: {
      claim_scope: "insufficient_evidence",
      evidence_grade: "insufficient",
      uncertainty_reasons: fallbackUncertainty,
      required_evidence: ["Topic Lens API route", "main-path context edges", "linked-ref audit"],
      evidence_objects: [],
      key_turning_papers: [],
    },
    branch_dossiers: [],
    bottleneck_lineage: {
      summary: "Bottleneck lineage unavailable in search-only fallback.",
      constraints: [],
      top_unresolved_keywords: [],
    },
    unresolved_limitations: [],
    future_growth: { candidate_edges: [], future_directions: [] },
    rd_radar: {
      summary: "Radar is empty because semantic search fallback produced no complete Step13 Claim Cards.",
      items: [
        {
          kind: "radar_empty_state",
          title: "No complete Claim Cards yet",
          claim_scope: "insufficient_evidence",
          evidence_grade: "no_complete_claim_card",
          uncertainty_reasons: fallbackUncertainty,
          eligible: false,
        },
      ],
      claim_cards: [],
      incomplete_claim_cards: [],
      candidate_pool: [],
      claim_cards_ready: false,
      high_confidence_ready: false,
    },
    evidence_map: {
      summary: "Evidence Map is unavailable in search-only fallback; only semantic retrieval context is known.",
      recommended_layer_combinations: [
        {
          layers: ["semantic", "uncertainty"],
          label: "Search fallback retrieval context",
          question: "What papers matched the query when the Topic Lens route was unavailable?",
          relationship: "Semantic search can recover candidate reading material but cannot explain lineage, bottlenecks, or Radar value.",
          display: "Related paper list plus uncertainty labels.",
          decision_use: "Use only to recover papers for a later evidence-backed Topic Dossier run.",
          can_explain: ["candidate papers to inspect"],
          cannot_explain: ["real branch splits", "key turning papers", "unresolved bottlenecks", "future direction value"],
          required_evidence: ["Topic Lens API", "section evidence", "main-path and bottleneck lineage contracts"],
          claim_scope: "retrieval_context_only",
          evidence_grade: retrievalGrade,
          uncertainty_reasons: fallbackUncertainty,
        },
      ],
    },
    first_principles: { five_questions: [] },
    value_model: DEFAULT_VALUE_MODEL,
  };
}

async function runSearchFallback(text) {
  const result = await api("/graph/visual/search", {
    method: "POST",
    body: JSON.stringify({ query_type: "semantic", query_text: text, top_k: 40 }),
  });
  const hits = result.hits || [];
  state.topicLens = buildSearchFallbackTopicLens(text, hits);
  state.highlightIds = new Set(state.topicLens.related_papers.map((hit) => hit.paper_id));
  renderTopicLens(state.topicLens);
  renderRadar(state.topicLens);
  renderExplainDock(DEFAULT_VALUE_MODEL);
  renderLayerMeaning(DEFAULT_VALUE_MODEL);
  focusPaperIds(state.highlightIds);
  setTimeCutoff(state.time.max);
}

async function runTopicLens(text) {
  const topic = text.trim();
  if (!topic) return;
  stopPlayback();
  setStatus("Running Topic Lens...");
  try {
    const lens = await api(`/graph/visual/topic-lens?topic=${encodeURIComponent(topic)}&top_k=50`);
    state.topicLens = lens;
    state.highlightIds = collectTopicIds(lens);
    renderTopicLens(lens);
    renderRadar(lens);
    renderExplainDock(lens.value_model);
    renderLayerMeaning(lens.value_model);
    focusPaperIds(state.highlightIds);
    setTimeCutoff(state.time.max);
    setMode("topic");
    setActiveTab("topic");
    setStatus(`Topic Lens: ${fmt(lens.total_related)} papers`);
  } catch (err) {
    if (String(err.message || "").includes("Not Found")) {
      await runSearchFallback(topic);
      setMode("topic");
      setActiveTab("topic");
      setStatus("Topic Lens route not loaded; used semantic search");
    } else {
      throw err;
    }
  }
}

async function inspectPaper(paperId) {
  setStatus(`Loading ${paperId}...`);
  const detail = await api(`/graph/visual/papers/${encodeURIComponent(paperId)}?edge_limit=100`);
  if (detail.paper) {
    renderPaper(detail.paper, detail.edges || []);
    state.highlightIds.add(detail.paper.paper_id);
  }
  setMode("topic");
  setActiveTab("paper");
  setStatus("Ready");
}

function setActiveTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  document.querySelectorAll(".pane").forEach((pane) => pane.classList.remove("active"));
  const pane = document.getElementById(`${name}Pane`);
  if (pane) pane.classList.add("active");
}

function setMode(mode) {
  state.mode = mode;
  els.modeButtons.forEach((button) => button.classList.toggle("active", button.dataset.mode === mode));
  const titles = {
    map: ["Field Evolution Map", "Optics corpus"],
    topic: ["Topic Lens", state.topicLens?.topic || "Topic query"],
    radar: ["Claim Card / R&D Radar", state.topicLens?.topic || "All candidates"],
  };
  els.contextTitle.textContent = titles[mode][0];
  els.contextMeta.textContent = titles[mode][1];
  if (mode === "topic") setActiveTab("topic");
  if (mode === "radar") setActiveTab("radar");
  if (mode === "map" && !document.querySelector(".pane.active")) setActiveTab("paper");
}

async function loadGraph({ autoplay = true } = {}) {
  stopPlayback();
  state.apiBase = els.apiBase.value.replace(/\/$/, "");
  setStatus("Checking visual graph...");
  const status = await api("/graph/visual/status");
  renderMetrics(status);
  if (!status.ready) {
    setStatus(`Not ready: missing ${status.missing_tables.join(", ")}`);
    return;
  }
  setStatus("Loading branches...");
  const clusters = await api("/graph/visual/clusters?limit=700");
  state.clusters = clusters.clusters || [];
  state.lineages = clusters.branch_lineages || [];
  renderClusters();
  setStatus("Loading nodes...");
  const nodes = await api("/graph/visual/nodes?limit=80000");
  state.nodes = nodes.nodes || [];
  state.nodeById = new Map(state.nodes.map((node) => [node.paper_id, node]));
  const years = state.nodes.map(yearOf).filter((y) => y != null);
  state.time.min = Math.min(...years);
  state.time.max = Math.max(...years);
  els.timeSlider.min = String(state.time.min);
  els.timeSlider.max = String(state.time.max);
  setStatus("Loading evolution edges...");
  state.edgeById = new Map();
  state.loadedEdgeKeys = new Set(["base"]);
  const edges = await api("/graph/visual/edges?lod_max=1&limit=100000");
  mergeEdges(edges.edges || []);
  const story = await api("/graph/visual/story");
  state.story = story.story_steps || [];
  renderStory();
  renderExplainDock(DEFAULT_VALUE_MODEL);
  renderLayerMeaning(DEFAULT_VALUE_MODEL);
  fitToNodes();
  setMode("map");
  setTimeCutoff(autoplay ? state.time.min : state.time.max, { draw: false });
  draw();
  renderPaper(null);
  renderTopicLens(state.topicLens);
  renderRadar(state.topicLens);
  setStatus(`Ready: ${fmt(state.nodes.length)} nodes, ${fmt(state.edges.length)} loaded edges`);
  if (autoplay) startPlayback(false);
}

function bindEvents() {
  els.loadBtn.addEventListener("click", () => loadGraph({ autoplay: true }).catch((err) => setStatus(err.message)));
  els.searchForm.addEventListener("submit", (evt) => {
    evt.preventDefault();
    runTopicLens(els.searchInput.value).catch((err) => setStatus(err.message));
  });
  els.modeButtons.forEach((button) => {
    button.addEventListener("click", () => setMode(button.dataset.mode));
  });
  els.layerInputs.forEach((input) => {
    input.addEventListener("change", async () => {
      const layer = input.dataset.layer;
      state.layers[layer] = input.checked;
      if (input.checked) await ensureLayerEdges(layer).catch((err) => setStatus(err.message));
      renderLayerMeaning();
      renderExplainDock();
      uploadNodes();
      draw();
      setStatus("Ready");
    });
  });
  els.playBtn.addEventListener("click", () => {
    if (state.time.playing) {
      stopPlayback();
    } else {
      startPlayback(state.time.current >= state.time.max);
    }
  });
  els.timeSlider.addEventListener("input", () => {
    stopPlayback();
    setTimeCutoff(Number(els.timeSlider.value));
  });
  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => setActiveTab(tab.dataset.tab)));
  document.body.addEventListener("click", (evt) => {
    const paper = evt.target.closest("[data-paper]");
    if (paper) inspectPaper(paper.dataset.paper).catch((err) => setStatus(err.message));
    const cluster = evt.target.closest("[data-cluster]");
    if (cluster) {
      const cid = cluster.dataset.cluster;
      api(`/graph/visual/nodes?cluster_id=${encodeURIComponent(cid)}&limit=80000`).then((data) => {
        const clusterNodes = data.nodes || [];
        state.highlightIds = new Set(clusterNodes.map((node) => node.paper_id));
        focusPaperIds(state.highlightIds);
        setTimeCutoff(state.time.max);
        setMode("map");
        setStatus(`Cluster ${cid}: ${fmt(clusterNodes.length)} nodes`);
      }).catch((err) => setStatus(err.message));
    }
    const story = evt.target.closest("[data-story]");
    if (story) {
      const step = state.story.find((x) => x.story_step_id === story.dataset.story);
      if (step) {
        stopPlayback();
        state.highlightIds = new Set((step.focus_papers || []).map((paper) => paper.paper_id));
        if (step.focus_cluster_id) {
          const cluster = state.clusters.find((c) => c.cluster_id === step.focus_cluster_id);
          if (cluster?.centroid) {
            state.panX = -Number(cluster.centroid.x || 0) * state.scale;
            state.panY = -Number(cluster.centroid.y || 0) * state.scale;
          }
        }
        setTimeCutoff(step.year_end || state.time.max);
        setMode("map");
      }
    }
  });
  els.graph.addEventListener("mousemove", (evt) => {
    const node = nearestNode(evt);
    if (!node) {
      els.hover.classList.add("hidden");
      return;
    }
    els.hover.classList.remove("hidden");
    els.hover.style.left = `${evt.offsetX + 14}px`;
    els.hover.style.top = `${evt.offsetY + 14}px`;
    const hoverUncertainty = asArray(node.uncertainty_reasons).slice(0, 2).map(esc).join(" / ");
    els.hover.innerHTML = `
      <strong>${esc(node.title || node.paper_id)}</strong><br>
      <small>${esc(node.paper_id)} / ${esc(node.year || "")} / ${esc(node.cluster_id || "")}</small>
      <div class="pill-row">
        <span class="pill">${esc(node.claim_scope || "retrieval_context_only")}</span>
        <span class="pill">${esc(node.evidence_grade || "graph_node_role_context")}</span>
      </div>
      ${hoverUncertainty ? `<small>${hoverUncertainty}</small>` : ""}
    `;
  });
  els.graph.addEventListener("click", (evt) => {
    const node = nearestNode(evt);
    if (node) inspectPaper(node.paper_id).catch((err) => setStatus(err.message));
  });
  els.graph.addEventListener("wheel", (evt) => {
    evt.preventDefault();
    const factor = evt.deltaY < 0 ? 1.08 : 0.92;
    state.scale = clamp(state.scale * factor, 0.18, 8);
    draw();
  }, { passive: false });
  let dragging = false;
  let last = null;
  els.graph.addEventListener("pointerdown", (evt) => {
    dragging = true;
    last = { x: evt.clientX, y: evt.clientY };
    els.graph.setPointerCapture(evt.pointerId);
  });
  els.graph.addEventListener("pointermove", (evt) => {
    if (!dragging || !last) return;
    const rect = els.graph.getBoundingClientRect();
    state.panX += 2 * (evt.clientX - last.x) / rect.width;
    state.panY -= 2 * (evt.clientY - last.y) / rect.height;
    last = { x: evt.clientX, y: evt.clientY };
    draw();
  });
  els.graph.addEventListener("pointerup", () => {
    dragging = false;
    last = null;
  });
  window.addEventListener("resize", resize);
}

try {
  initGl();
  bindEvents();
  resize();
  renderPaper(null);
  renderTopicLens(null);
  renderRadar(null);
  renderExplainDock(DEFAULT_VALUE_MODEL);
  renderLayerMeaning(DEFAULT_VALUE_MODEL);
  setMode("topic");
  setActiveTab("topic");
  setTimeout(() => {
    loadGraph({ autoplay: true }).catch((err) => setStatus(err.message));
  }, 80);
} catch (err) {
  setStatus(err.message);
}
