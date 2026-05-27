const token = "pilot-viewer-token";
const state = {
  apiBase: "http://127.0.0.1:8000",
  nodes: [],
  edges: [],
  clusters: [],
  story: [],
  selected: null,
  hover: null,
  scale: 0.86,
  panX: 0,
  panY: 0,
  filterRole: null,
};

const els = {
  apiBase: document.getElementById("apiBase"),
  loadBtn: document.getElementById("loadBtn"),
  storyBtn: document.getElementById("storyBtn"),
  mainPathBtn: document.getElementById("mainPathBtn"),
  futureBtn: document.getElementById("futureBtn"),
  status: document.getElementById("statusText"),
  metrics: document.getElementById("metrics"),
  graph: document.getElementById("graphCanvas"),
  edges: document.getElementById("edgeCanvas"),
  hover: document.getElementById("hoverCard"),
  searchForm: document.getElementById("searchForm"),
  searchInput: document.getElementById("searchInput"),
  paperPane: document.getElementById("paperPane"),
  clusterPane: document.getElementById("clusterPane"),
  storyPane: document.getElementById("storyPane"),
};

const gl = els.graph.getContext("webgl", { antialias: true, alpha: true });
const edgeCtx = els.edges.getContext("2d");

let program;
let buffers = {};

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
      gl_PointSize = clamp(a_size, 2.0, 18.0);
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
      float alpha = smoothstep(0.25, 0.08, d);
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
  const safe = /^#[0-9a-f]{6}$/i.test(hex || "") ? hex : "#0f7b6c";
  const n = Number.parseInt(safe.slice(1), 16);
  return [(n >> 16 & 255) / 255, (n >> 8 & 255) / 255, (n & 255) / 255];
}

function roleColor(node) {
  if (node.visual_role === "main_path") return [0.06, 0.06, 0.06];
  if (node.visual_role === "future_anchor") return [0.48, 0.25, 0.95];
  if (node.visual_role === "limitation_bottleneck") return [0.82, 0.29, 0.20];
  return hexToRgb(node.color_hex);
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

function uploadNodes() {
  const visible = state.filterRole
    ? state.nodes.filter((node) => node.visual_role === state.filterRole)
    : state.nodes;
  const pos = new Float32Array(visible.length * 3);
  const color = new Float32Array(visible.length * 3);
  const size = new Float32Array(visible.length);
  visible.forEach((node, i) => {
    pos[i * 3] = Number(node.x || 0);
    pos[i * 3 + 1] = Number(node.y || 0);
    pos[i * 3 + 2] = Number(node.z || 0);
    const c = roleColor(node);
    color.set(c, i * 3);
    size[i] = Math.max(2, Math.min(18, Number(node.node_size || 4)));
  });
  state.visibleNodes = visible;
  gl.bindBuffer(gl.ARRAY_BUFFER, buffers.pos);
  gl.bufferData(gl.ARRAY_BUFFER, pos, gl.STATIC_DRAW);
  gl.bindBuffer(gl.ARRAY_BUFFER, buffers.color);
  gl.bufferData(gl.ARRAY_BUFFER, color, gl.STATIC_DRAW);
  gl.bindBuffer(gl.ARRAY_BUFFER, buffers.size);
  gl.bufferData(gl.ARRAY_BUFFER, size, gl.STATIC_DRAW);
}

function drawEdges() {
  const dpr = window.devicePixelRatio || 1;
  const w = els.edges.width / dpr;
  const h = els.edges.height / dpr;
  edgeCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  edgeCtx.clearRect(0, 0, w, h);
  const byId = new Map(state.nodes.map((node) => [node.paper_id, node]));
  edgeCtx.lineWidth = 1;
  for (const edge of state.edges) {
    const a = byId.get(edge.source_paper_id);
    const b = byId.get(edge.target_paper_id);
    if (!a || !b) continue;
    const pa = toScreen(a, w, h);
    const pb = toScreen(b, w, h);
    edgeCtx.strokeStyle = edge.is_main_path ? "rgba(17,17,17,.82)" : "rgba(90,86,78,.16)";
    edgeCtx.beginPath();
    edgeCtx.moveTo(pa.x, pa.y);
    edgeCtx.lineTo(pb.x, pb.y);
    edgeCtx.stroke();
  }
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

function toScreen(node, width, height) {
  const x = (Number(node.x || 0) * state.scale + state.panX) * 0.5 + 0.5;
  const y = 0.5 - (Number(node.y || 0) * state.scale + state.panY) * 0.5;
  return { x: x * width, y: y * height };
}

function nearestNode(evt) {
  const rect = els.graph.getBoundingClientRect();
  const x = evt.clientX - rect.left;
  const y = evt.clientY - rect.top;
  let best = null;
  let bestD = 16 * 16;
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

function renderMetrics(status) {
  const counts = status.counts || {};
  const items = [
    ["Nodes", counts.visual_nodes || state.nodes.length],
    ["Edges", counts.visual_edges || state.edges.length],
    ["Branches", counts.visual_clusters || state.clusters.length],
    ["Tiles", counts.visual_tiles || 0],
  ];
  els.metrics.innerHTML = items.map(([label, value]) => (
    `<div class="metric"><strong>${Number(value || 0).toLocaleString()}</strong><span>${label}</span></div>`
  )).join("");
}

function renderClusters() {
  els.clusterPane.innerHTML = state.clusters.slice(0, 80).map((cluster) => `
    <div class="item">
      <button data-cluster="${cluster.cluster_id}">
        <strong>${cluster.label || cluster.cluster_id}</strong><br>
        <small>${cluster.cluster_id} / ${cluster.n_nodes || 0} papers / ${cluster.year_start || "?"}-${cluster.year_end || "?"}</small>
      </button>
    </div>
  `).join("");
}

function renderStory() {
  els.storyPane.innerHTML = state.story.map((step) => `
    <div class="item">
      <button data-story="${step.story_step_id}">
        <strong>${step.title || step.story_step_id}</strong><br>
        <small>${step.year_start || ""}-${step.year_end || ""}</small>
        <p>${step.narrative || ""}</p>
      </button>
    </div>
  `).join("");
}

function renderPaper(paper, edges = []) {
  if (!paper) {
    els.paperPane.innerHTML = '<div class="item">Click a node or search to inspect a paper.</div>';
    return;
  }
  const ids = paper.ids || {};
  els.paperPane.innerHTML = `
    <div class="item">
      <strong>${paper.title || paper.paper_id}</strong>
      <div class="paper-meta">${paper.paper_id} / ${paper.year || "year unknown"} / ${paper.cluster_label || ""}</div>
    </div>
    <div class="item">
      <div class="paper-meta">IDs</div>
      <small>DOI: ${ids.doi || "-"}<br>arXiv: ${ids.arxiv_id || "-"}<br>OpenAlex: ${ids.openalex_work_id || "-"}</small>
    </div>
    <div class="item">
      <div class="paper-meta">Abstract</div>
      <p>${paper.abstract || "No abstract available."}</p>
    </div>
    <div class="item">
      <div class="paper-meta">Limitations</div>
      ${(paper.limitations || []).map((lim) => `<p>${lim.description || JSON.stringify(lim)}</p>`).join("") || "<p>No limitation atoms yet.</p>"}
    </div>
    <div class="item">
      <div class="paper-meta">Local edges</div>
      <small>${edges.length} loaded</small>
    </div>
  `;
}

async function loadGraph() {
  state.apiBase = els.apiBase.value.replace(/\/$/, "");
  setStatus("Checking visual graph...");
  const status = await api("/graph/visual/status");
  renderMetrics(status);
  if (!status.ready) {
    setStatus(`Not ready: missing ${status.missing_tables.join(", ")}`);
    return;
  }
  setStatus("Loading branches...");
  const clusters = await api("/graph/visual/clusters?limit=300");
  state.clusters = clusters.clusters || [];
  renderClusters();
  setStatus("Loading nodes...");
  const nodes = await api("/graph/visual/nodes?limit=80000");
  state.nodes = nodes.nodes || [];
  setStatus("Loading LOD edges...");
  const edges = await api("/graph/visual/edges?lod_max=0&limit=50000");
  state.edges = edges.edges || [];
  const story = await api("/graph/visual/story");
  state.story = story.story_steps || [];
  renderStory();
  uploadNodes();
  draw();
  setStatus(`Ready: ${state.nodes.length.toLocaleString()} nodes, ${state.edges.length.toLocaleString()} LOD edges`);
}

async function inspectPaper(paperId) {
  setStatus(`Loading ${paperId}...`);
  const detail = await api(`/graph/visual/papers/${encodeURIComponent(paperId)}?edge_limit=80`);
  if (detail.paper) {
    state.selected = detail.paper;
    renderPaper(detail.paper, detail.edges || []);
  }
  setStatus("Ready");
}

async function runSearch(text) {
  if (!text.trim()) return;
  setStatus("Searching...");
  const result = await api("/graph/visual/search", {
    method: "POST",
    body: JSON.stringify({ query_type: "semantic", query_text: text, top_k: 30 }),
  });
  const hits = result.hits || [];
  els.paperPane.innerHTML = hits.map((hit) => `
    <div class="item">
      <button data-paper="${hit.paper_id}">
        <strong>${hit.title || hit.paper_id}</strong><br>
        <small>${hit.paper_id} / ${hit.year || "?"} / ${hit.cluster_label || ""}</small>
      </button>
    </div>
  `).join("") || '<div class="item">No matches.</div>';
  setActiveTab("paper");
  setStatus(`Search: ${hits.length} hits`);
}

function setActiveTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  document.querySelectorAll(".pane").forEach((pane) => pane.classList.remove("active"));
  document.getElementById(`${name}Pane`).classList.add("active");
}

function bindEvents() {
  els.loadBtn.addEventListener("click", () => loadGraph().catch((err) => setStatus(err.message)));
  els.searchForm.addEventListener("submit", (evt) => {
    evt.preventDefault();
    runSearch(els.searchInput.value).catch((err) => setStatus(err.message));
  });
  els.mainPathBtn.addEventListener("click", () => {
    state.filterRole = state.filterRole === "main_path" ? null : "main_path";
    uploadNodes();
    draw();
  });
  els.futureBtn.addEventListener("click", () => {
    state.filterRole = state.filterRole === "future_anchor" ? null : "future_anchor";
    uploadNodes();
    draw();
  });
  els.storyBtn.addEventListener("click", () => setActiveTab("story"));
  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => setActiveTab(tab.dataset.tab)));
  document.body.addEventListener("click", (evt) => {
    const paper = evt.target.closest("[data-paper]");
    if (paper) inspectPaper(paper.dataset.paper).catch((err) => setStatus(err.message));
    const cluster = evt.target.closest("[data-cluster]");
    if (cluster) {
      const cid = cluster.dataset.cluster;
      state.filterRole = null;
      api(`/graph/visual/nodes?cluster_id=${encodeURIComponent(cid)}&limit=80000`).then((data) => {
        state.nodes = data.nodes || [];
        uploadNodes();
        draw();
        setStatus(`Cluster ${cid}: ${state.nodes.length} nodes`);
      }).catch((err) => setStatus(err.message));
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
    els.hover.innerHTML = `<strong>${node.title || node.paper_id}</strong><br><small>${node.paper_id} / ${node.year || ""}</small>`;
  });
  els.graph.addEventListener("click", (evt) => {
    const node = nearestNode(evt);
    if (node) inspectPaper(node.paper_id).catch((err) => setStatus(err.message));
  });
  els.graph.addEventListener("wheel", (evt) => {
    evt.preventDefault();
    const factor = evt.deltaY < 0 ? 1.08 : 0.92;
    state.scale = Math.max(0.2, Math.min(6, state.scale * factor));
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

initGl();
bindEvents();
resize();
renderPaper(null);
