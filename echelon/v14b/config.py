"""
V14-B 集中配置 — 所有阈值/超参/路径

修改超参时只需改此文件,各 step 自动读取。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Any

# ---------------------------------------------------------------------------
# 工程路径
# ---------------------------------------------------------------------------

# 工程根目录 (此文件的三级父目录)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 自动加载项目根目录 .env (make pilot / python -m echelon.v14b.*)
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

DB_MAIN = PROJECT_ROOT / "db" / "echelon_library.sqlite3"
DB_V14 = PROJECT_ROOT / "db" / "v14_pilot.sqlite3"

LOG_DIR = PROJECT_ROOT / "logs" / "v14b"
REPORT_DIR = PROJECT_ROOT / "reports" / "v14b_pilot"
CHECKPOINT_DIR = REPORT_DIR / "checkpoints"

# ---------------------------------------------------------------------------
# 全局限制(调试用)
# ---------------------------------------------------------------------------

# V14B_LIMIT: 留空跑全量,填数字只跑前 N 条(用于快速调试)
LIMIT: int | None = (
    int(os.environ["V14B_LIMIT"]) if os.environ.get("V14B_LIMIT") else None
)

# 并发数
CONCURRENCY: int = int(os.environ.get("V14B_CONCURRENCY", "10"))

# 是否使用 MPS (Apple Silicon GPU)
USE_MPS: bool = os.environ.get("V14B_USE_MPS", "true").lower() == "true"

# ---------------------------------------------------------------------------
# Step 1: OpenAlex Enrich
# ---------------------------------------------------------------------------

OPENALEX_EMAIL: str = os.environ.get("OPENALEX_EMAIL", "pilot@echelon.ai")
OPENALEX_POLITE_DELAY: float = float(os.environ.get("V14B_OPENALEX_DELAY", "0.2"))
OPENALEX_MAX_RETRIES: int = 5
OPENALEX_RETRY_DELAY: float = 2.0   # seconds before retry

# Step 1: 多源 enrich.  S2 is preferred when a key is configured because it
# often provides richer arXiv reference lists; without a key it is skipped.
_raw_providers = os.environ.get("V14B_ENRICH_PROVIDERS", "s2,crossref,openalex")
ENRICH_PROVIDERS: list[str] = [p.strip() for p in _raw_providers.split(",") if p.strip()]

SEMANTIC_SCHOLAR_API_KEY: str = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
# S2 官方限速: 1 request/second (全端点累计)
S2_REQUESTS_PER_SEC: float = float(os.environ.get("V14B_S2_REQUESTS_PER_SEC", "1"))
S2_MIN_INTERVAL: float = 1.0 / max(S2_REQUESTS_PER_SEC, 0.1)
S2_DELAY: float = max(
    float(os.environ.get("V14B_S2_DELAY", "1.05")),
    S2_MIN_INTERVAL,
)
S2_MAX_RETRIES: int = int(os.environ.get("V14B_S2_MAX_RETRIES", "3"))
SKIP_S2_WITHOUT_KEY: bool = os.environ.get("V14B_SKIP_S2_WITHOUT_KEY", "true").lower() == "true"
USE_OPENALEX: bool = os.environ.get("V14B_USE_OPENALEX", "true").lower() == "true"
ENRICH_PARALLEL_CR_OA: bool = os.environ.get("V14B_ENRICH_PARALLEL", "false").lower() == "true"
OPENALEX_ENRICH_CONCURRENCY: int = int(os.environ.get("V14B_OPENALEX_CONCURRENCY", "2"))

CROSSREF_EMAIL: str = os.environ.get("CROSSREF_EMAIL", OPENALEX_EMAIL)
CROSSREF_DELAY: float = float(os.environ.get("V14B_CROSSREF_DELAY", "0.35"))

# ---------------------------------------------------------------------------
# Step 2: SPC Main Path
# ---------------------------------------------------------------------------

# top X% 边标记为 is_main_path
SPC_MAIN_PATH_PERCENTILE: float = 0.99  # top 1%

# OOM 降级: 按时间窗口分批(年)
SPC_WINDOW_YEARS: int = 5

# ---------------------------------------------------------------------------
# Step 3: V14 KeystoneScore
# ---------------------------------------------------------------------------

# V14-B 生命周期权重表(见 spec 第三节)
LIFECYCLE_WEIGHTS_V14: Dict[str, Dict[str, float]] = {
    "fresh": {
        "c_recency":            0.15,
        "c_venue":              0.05,
        "c_team_disrupt":       0.10,
        "c_recent_burst":       0.15,   # ↑ vs V13 fresh (0.00)
        "c_review_filter":     -0.10,   # penalty
        "c_bib_breadth":        0.10,
        "c_cocite_breadth":     0.00,
        "c_bridging_centrality": 0.20,  # ↑ vs V13 fresh (0.10)
        "c_cd_subdomain":       0.00,
        "c_semantic_outlier":   0.10,
        "c_breakthrough_lang":  0.20,   # ↑ 全新信号
        "c_mechanism_novelty":  0.20,   # ↑ 全新信号
    },
    "growing": {
        "c_recency":            0.10,
        "c_venue":              0.05,
        "c_team_disrupt":       0.10,
        "c_recent_burst":       0.20,   # ↑
        "c_review_filter":     -0.10,
        "c_bib_breadth":        0.15,
        "c_cocite_breadth":     0.05,
        "c_bridging_centrality": 0.25,  # ↑
        "c_cd_subdomain":       0.00,
        "c_semantic_outlier":   0.10,
        "c_breakthrough_lang":  0.05,
        "c_mechanism_novelty":  0.05,
    },
    "mature": {
        "c_recency":            0.05,
        "c_venue":              0.05,
        "c_team_disrupt":       0.05,
        "c_recent_burst":       0.05,
        "c_review_filter":     -0.10,
        "c_bib_breadth":        0.10,
        "c_cocite_breadth":     0.15,
        "c_bridging_centrality": 0.25,  # ↑
        "c_cd_subdomain":       0.25,   # ↑
        "c_semantic_outlier":   0.05,
        "c_breakthrough_lang":  0.00,
        "c_mechanism_novelty":  0.00,
    },
}

# ---------------------------------------------------------------------------
# Step 4: 子图构建
# ---------------------------------------------------------------------------

# top N keystone score 节点
SUBGRAPH_TOP_KEYSTONE: int = 1000

# top N fresh (2024+) 节点
SUBGRAPH_TOP_FRESH: int = 500
SUBGRAPH_FRESH_YEAR: int = 2024

# 子图大小(OOM 时可缩小)
SUBGRAPH_MAX_SIZE: int = int(os.environ.get("V14B_SUBGRAPH_SIZE", "5000"))

# ---------------------------------------------------------------------------
# Step 5a: SciBERT 引用功能分类
# ---------------------------------------------------------------------------

# HuggingFace 模型 ID. Citation-function classification is only a weak
# evidence layer unless real citation contexts are available, so the default
# product-chain classifier is deterministic/heuristic. Low-confidence edges fall
# back to heuristic correction; use --use-llm only for explicit weak-label audit.
SCIBERT_MODEL_ID: str = "allenai/scibert_scivocab_uncased"
CITATION_CLASSIFIER_MODE: str = os.environ.get("V14B_CITATION_CLASSIFIER", "heuristic").lower()
SCIBERT_LLM_FALLBACK: bool = os.environ.get("V14B_SCIBERT_LLM_FALLBACK", "false").lower() == "true"
SCIBERT_LLM_FALLBACK_LIMIT: int = int(os.environ.get("V14B_SCIBERT_LLM_FALLBACK_LIMIT", "200"))

# 推理 batch size (MPS/CPU)
SCIBERT_BATCH_SIZE: int = 32

# 置信度阈值,低于此值只做 heuristic 修正,不隐式调用 LLM
SCIBERT_CONFIDENCE_THRESHOLD: float = 0.6

# 引用功能标签
CITATION_FUNCTIONS = [
    "extension",
    "motivation",
    "usage",
    "similarity",
    "background",
    "future_work",
]

# 高权重引用功能(主路径分析中保留)
HIGH_WEIGHT_FUNCTIONS = {"extension", "motivation", "usage"}

# ---------------------------------------------------------------------------
# Step 5b: VGAE
# ---------------------------------------------------------------------------

# 节点特征维度
VGAE_ABSTRACT_DIM: int = 768    # all-mpnet-base-v2
VGAE_FIELD_DIM: int = 26        # OpenAlex Field one-hot
VGAE_INPUT_DIM: int = VGAE_ABSTRACT_DIM + 1 + 1 + 1 + VGAE_FIELD_DIM  # 797

# GCN 隐层维度
VGAE_HIDDEN_DIM: int = 256
VGAE_LATENT_DIM: int = 128

# 训练超参
VGAE_EPOCHS: int = 200
VGAE_LR: float = 1e-3
VGAE_BETA: float = 0.5          # KL weight
VGAE_DROPOUT: float = 0.5

# 边划分
VGAE_TRAIN_RATIO: float = 0.8
VGAE_VAL_RATIO: float = 0.1
VGAE_TEST_RATIO: float = 0.1

# 早停
VGAE_EARLY_STOP_PATIENCE: int = 20

# 预测输出阈值
VGAE_PREDICT_THRESHOLD: float = 0.7
VGAE_PREDICT_TOP_K: int = int(os.environ.get("V14B_VGAE_PREDICT_TOP_K", "1000"))

# 时间间隔约束(防止预测过早)
VGAE_MIN_YEAR_GAP: int = 1

# ---------------------------------------------------------------------------
# Step 5c: Limitation Tracking
# ---------------------------------------------------------------------------

# Step 5s: Section-level evidence ingestion (arXiv/Sci-Bot/PDF)
SECTION_INGEST_TOP_N: int = int(
    os.environ.get("V14B_SECTION_INGEST_TOP_N", "1200")
)
SECTION_INGEST_CONCURRENCY: int = int(
    os.environ.get("V14B_SECTION_INGEST_CONCURRENCY", "2")
)
SECTION_INGEST_TIMEOUT_SEC: float = float(
    os.environ.get("V14B_SECTION_INGEST_TIMEOUT_SEC", "60")
)
SECTION_INGEST_MIN_CHARS: int = int(
    os.environ.get("V14B_SECTION_INGEST_MIN_CHARS", "160")
)
SECTION_INGEST_MAX_CHARS: int = int(
    os.environ.get("V14B_SECTION_INGEST_MAX_CHARS", "12000")
)
SECTION_INGEST_REQUIRE_ARXIV: bool = (
    os.environ.get("V14B_SECTION_INGEST_REQUIRE_ARXIV", "true").lower()
    in ("1", "true", "yes")
)
DEFAULT_RAW_PDF_STORE_ROOT: Path = Path(
    os.environ.get("V14B_DEFAULT_RAW_PDF_STORE_ROOT", "/Volumes/LaCie/Echelon_Paper_Raw_Data")
).expanduser()
RAW_PDF_STORE_ROOT: Path | None = (
    Path(os.environ["V14B_RAW_PDF_STORE_ROOT"]).expanduser()
    if os.environ.get("V14B_RAW_PDF_STORE_ROOT")
    else DEFAULT_RAW_PDF_STORE_ROOT
)
RAW_PDF_MANIFEST: Path | None = (
    Path(os.environ["V14B_RAW_PDF_MANIFEST"]).expanduser()
    if os.environ.get("V14B_RAW_PDF_MANIFEST")
    else (
        RAW_PDF_STORE_ROOT / "manifests" / "raw_pdf_downloads.sqlite3"
        if RAW_PDF_STORE_ROOT
        else None
    )
)
SECTION_INGEST_PREFER_LOCAL_RAW_PDF: bool = (
    os.environ.get("V14B_SECTION_INGEST_PREFER_LOCAL_RAW_PDF", "true").lower()
    in ("1", "true", "yes")
)
RAW_PDF_MAX_BYTES: int = int(
    os.environ.get("V14B_RAW_PDF_MAX_BYTES", str(200 * 1024 * 1024))
)

# Sci-Bot 抽取 top N 论文
LIMITATION_TOP_N: int = 1000

# Step5c 默认严格要求 section-level 证据。若必须兼容旧库可显式放开 fallback。
LIMITATION_REQUIRE_SECTION_EVIDENCE: bool = (
    os.environ.get("V14B_LIMITATION_REQUIRE_SECTION_EVIDENCE", "true").lower()
    in ("1", "true", "yes")
)
LIMITATION_ALLOW_ABSTRACT_FALLBACK: bool = (
    os.environ.get("V14B_LIMITATION_ALLOW_ABSTRACT_FALLBACK", "false").lower()
    in ("1", "true", "yes")
)

# LLM 提取的 limitation atoms 数量限制
LIMITATION_MAX_ATOMS_PER_PAPER: int = 5
LIMITATION_USE_LLM: bool = os.environ.get("V14B_LIMITATION_USE_LLM", "false").lower() == "true"

# Resolution Tracking: 每个 atom 最多追踪 N 篇后续论文
LIMITATION_MAX_RESOLVERS: int = int(
    os.environ.get("V14B_LIMITATION_MAX_RESOLVERS", "10")
)

# Pilot 可跳过 Phase3（3200+ atoms × resolvers 会导致数万次 LLM 调用）
SKIP_LIMITATION_RESOLUTION: bool = (
    os.environ.get("V14B_SKIP_LIMITATION_RESOLUTION", "false").lower()
    in ("1", "true", "yes")
)

# 输出 top N 未解决 limitation
LIMITATION_TOP_UNRESOLVED: int = 50

# ---------------------------------------------------------------------------
# Step 6: 三路融合
# ---------------------------------------------------------------------------

FUSION_TOP_DIRECTIONS: int = 20

# 两路命中(宽松模式)
FUSION_MIN_EVIDENCE_PATHS: int = 2

# Direction naming should not block the product chain on an external LLM.
# Set V14B_FUSION_USE_LLM_NAMING=true only for optional semantic polishing.
FUSION_USE_LLM_NAMING: bool = (
    os.environ.get("V14B_FUSION_USE_LLM_NAMING", "false").lower()
    in ("1", "true", "yes")
)

# ---------------------------------------------------------------------------
# Step 7: 三色突变标记
# ---------------------------------------------------------------------------

# 红: mature 论文 CD-index 阈值
MUTATION_RED_CD_THRESHOLD: float = 0.3

# 橙: 跨 Field 桥接分数分位数
MUTATION_ORANGE_BRIDGE_PERCENTILE: float = 0.90

# 紫: 18 月内 burstiness 分位数
MUTATION_PURPLE_BURST_PERCENTILE: float = 0.95
MUTATION_BURST_WINDOW_MONTHS: int = 18

# ---------------------------------------------------------------------------
# Step 8: UMAP-3D
# ---------------------------------------------------------------------------

UMAP_N_NEIGHBORS: int = 15
UMAP_MIN_DIST: float = 0.1
UMAP_N_COMPONENTS: int = 2         # XY; Z is from publication_year
UMAP_RANDOM_STATE: int = 42

# 论文最早年份(Z=0)
YEAR_MIN: int = 1991
YEAR_MAX: int = 2026

# 节点大小归一化
NODE_SIZE_MIN: float = 2.0
NODE_SIZE_MAX: float = 20.0

# ---------------------------------------------------------------------------
# Step 9: 报告生成器
# ---------------------------------------------------------------------------

REPORT_ALGO_VALIDATION = REPORT_DIR / "V14B_Evidence_Decision_算法验证报告.md"
REPORT_FUTURE_DIRECTIONS = REPORT_DIR / "未来候选方向_证据合同报告.md"

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

# Anthropic
ANTHROPIC_MODEL: str = "claude-sonnet-4-6"
ANTHROPIC_MAX_TOKENS: int = 4096

# OpenAI
OPENAI_MODEL: str = "gpt-4o"
OPENAI_MODEL_MINI: str = "o3-mini"
OPENAI_MAX_TOKENS: int = 4096

# Ollama
OLLAMA_BASE_URL: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = "qwen2.5:14b"

# Token 成本估算 (USD per 1M tokens)
TOKEN_COST: Dict[str, Dict[str, float]] = {
    "anthropic": {
        "input":  3.0,   # claude-sonnet-4-6
        "output": 15.0,
    },
    "openai_gpt4o": {
        "input":  2.5,
        "output": 10.0,
    },
    "openai_o3mini": {
        "input":  1.1,
        "output": 4.4,
    },
    "ollama": {
        "input":  0.0,   # 本地, 免费
        "output": 0.0,
    },
}
