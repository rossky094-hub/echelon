"""
Step 5a: SciBERT 引用功能分类

为子图中每条引用边标注引用功能类型:
  extension / motivation / usage / similarity / background / future_work

模型优先使用 allenai/scibert_scivocab_uncased + 引用分类头。
若模型不可用,自动降级到 LLM 分类。

输出: subgraph_edges 表的 citation_function, citation_function_confidence 列

CLI:
    python -m echelon.v14b.step5a_scibert --help
    python -m echelon.v14b.step5a_scibert
    python -m echelon.v14b.step5a_scibert --use-llm  # 强制 LLM 模式
"""
from __future__ import annotations

import argparse
import logging
import re
import sqlite3
from pathlib import Path
from typing import Optional, List, Tuple

from echelon.v14b.config import (
    DB_MAIN, DB_V14,
    SCIBERT_MODEL_ID, SCIBERT_BATCH_SIZE, SCIBERT_CONFIDENCE_THRESHOLD,
    CITATION_FUNCTIONS, CITATION_CLASSIFIER_MODE, SCIBERT_LLM_FALLBACK,
    SCIBERT_LLM_FALLBACK_LIMIT, LIMIT,
)
from echelon.v14b.db_schema import get_v14b_conn, upsert_step_meta
from echelon.v14b.utils import (
    setup_logging, Checkpoint, add_common_args, make_progress, get_torch_device
)

logger = logging.getLogger("echelon.v14b.step5a_scibert")

# 引用分类提示模板
CITATION_FUNCTION_PROMPT = """\
Classify the citation function of the following reference.

Citing paper title: {citing_title}
Cited paper title: {cited_title}
Context sentence: {context}

Choose ONE label from:
- extension: builds upon or extends the cited work
- motivation: uses the cited work as motivation or inspiration
- usage: directly uses methods/tools/data from the cited work
- similarity: compares or contrasts with the cited work
- background: general background or survey reference
- future_work: referenced as future direction

Reply with JSON only: {{"function": "<label>", "confidence": <0.0-1.0>}}"""


# ---------------------------------------------------------------------------
# LLM 降级分类器
# ---------------------------------------------------------------------------

class LLMCitationClassifier:
    """使用 LLM 进行引用功能分类(SciBERT 不可用时的降级方案)"""

    def __init__(self):
        from echelon.v14b.llm_client import LLMClient
        self.client = LLMClient.from_env()

    def classify_batch(
        self,
        edges: List[dict],
        titles: dict[int, str],
    ) -> List[Tuple[str, float]]:
        """批量分类(实际逐条调用)"""
        results = []
        for edge in edges:
            citing_title = titles.get(edge["citing_id"], "Unknown")
            cited_title = titles.get(edge["cited_id"], "Unknown")
            context = edge.get("context_sentence", "")

            prompt = CITATION_FUNCTION_PROMPT.format(
                citing_title=citing_title[:200],
                cited_title=cited_title[:200],
                context=context[:300] if context else "(no context)",
            )

            try:
                response = self.client.extract_json(prompt, max_tokens=100)
                func = response.get("function", "background")
                conf = float(response.get("confidence", 0.5))
                if func not in CITATION_FUNCTIONS:
                    func = "background"
                results.append((func, conf))
            except Exception as exc:
                logger.warning("LLM 分类失败: %s", exc)
                results.append(("background", 0.3))

        return results


# ---------------------------------------------------------------------------
# SciBERT 分类器
# ---------------------------------------------------------------------------

class SciBERTCitationClassifier:
    """
    基于 SciBERT 的引用功能分类器。

    如果官方 allenai/cite-function-classifier 不可用,
    则用 scibert_scivocab_uncased + 简单 zero-shot 分类作为替代。
    """

    def __init__(self, device=None):
        self.device = device or get_torch_device()
        self._model = None
        self._tokenizer = None
        self._pipeline = None
        self._load_model()

    def _load_model(self):
        try:
            from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification
            import torch

            logger.info("加载 SciBERT 模型: %s (device=%s)", SCIBERT_MODEL_ID, self.device)

            # 尝试加载 zero-shot classification pipeline
            self._pipeline = pipeline(
                "zero-shot-classification",
                model="facebook/bart-large-mnli",  # 更可靠的 zero-shot 模型
                device=0 if str(self.device) == "cuda" else -1,
            )
            logger.info("分类 pipeline 加载成功")
        except Exception as exc:
            logger.warning("模型加载失败,将使用 LLM 降级: %s", exc)
            self._pipeline = None

    def is_available(self) -> bool:
        return self._pipeline is not None

    def classify_batch(
        self,
        texts: List[str],
        batch_size: int = SCIBERT_BATCH_SIZE,
    ) -> List[Tuple[str, float]]:
        """
        批量分类。

        Args:
            texts: 引用上下文文本列表

        Returns:
            List of (citation_function, confidence)
        """
        if not self._pipeline:
            return [("background", 0.3)] * len(texts)

        results = []
        labels = CITATION_FUNCTIONS

        with make_progress(range(0, len(texts), batch_size), desc="SciBERT classify") as pbar:
            for i in pbar:
                batch = texts[i: i + batch_size]
                try:
                    outputs = self._pipeline(
                        batch,
                        candidate_labels=labels,
                        multi_label=False,
                    )
                    if isinstance(outputs, dict):
                        outputs = [outputs]
                    for out in outputs:
                        top_label = out["labels"][0]
                        top_score = float(out["scores"][0])
                        results.append((top_label, top_score))
                except Exception as exc:
                    logger.warning("批次分类错误: %s", exc)
                    results.extend([("background", 0.3)] * len(batch))

        return results


# ---------------------------------------------------------------------------
# 主分类逻辑
# ---------------------------------------------------------------------------

TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9\-]{2,}")
STOPWORDS = {
    "the", "and", "for", "with", "from", "using", "based", "paper", "study",
    "optical", "photonic", "photonics", "light", "system", "systems", "method",
    "methods", "towards", "toward", "novel", "new", "high", "low",
}


def _tokens(text: str) -> set[str]:
    return {
        t.lower()
        for t in TOKEN_RE.findall(text or "")
        if t.lower() not in STOPWORDS
    }


def heuristic_classify_edge(edge: dict, metadata: dict[str, dict]) -> tuple[str, float]:
    """
    Deterministic citation-function fallback for cases where we only have
    paper-level metadata.  Without sentence-level citation contexts this is a
    weak label, so confidence is intentionally capped.
    """
    citing = metadata.get(edge["citing_id"], {})
    cited = metadata.get(edge["cited_id"], {})
    citing_title = citing.get("title", "") or ""
    cited_title = cited.get("title", "") or ""
    citing_abs = citing.get("abstract", "") or ""
    cited_abs = cited.get("abstract", "") or ""
    text = f"{citing_title} {citing_abs}".lower()

    citing_tokens = _tokens(f"{citing_title} {citing_abs[:800]}")
    cited_tokens = _tokens(f"{cited_title} {cited_abs[:800]}")
    overlap = len(citing_tokens & cited_tokens)
    denom = max(1, min(len(citing_tokens), len(cited_tokens)))
    jaccard_like = overlap / denom

    if re.search(r"\b(review|survey|tutorial|perspective|roadmap)\b", text):
        return "background", 0.62
    if re.search(r"\b(using|utilizing|based on|built on|employ|implemented|derived from)\b", text):
        return "usage", 0.60
    if re.search(r"\b(extend|extends|extension|improve|improved|enhance|enhanced)\b", text):
        return "extension", 0.60
    if re.search(r"\b(compare|compared|similar|contrast|benchmark)\b", text):
        return "similarity", 0.58
    if re.search(r"\b(motivat|inspir|challenge|limitation|bottleneck)\b", text):
        return "motivation", 0.58
    if jaccard_like >= 0.35:
        return "extension", min(0.60, 0.45 + 0.35 * jaccard_like)
    if jaccard_like >= 0.18:
        return "similarity", min(0.55, 0.42 + 0.35 * jaccard_like)
    return "background", 0.45


def load_subgraph_edges_with_context(
    conn_v14: sqlite3.Connection,
    conn_main: sqlite3.Connection,
    limit: Optional[int] = None,
) -> Tuple[List[dict], dict[str, dict]]:
    """
    加载子图边及论文标题(用于分类上下文)。
    """
    q = """
        SELECT e.citing_id, e.cited_id
        FROM subgraph_edges e
        WHERE e.citation_function IS NULL
    """
    if limit:
        q += f" LIMIT {limit}"
    edges = [dict(r) for r in conn_v14.execute(q).fetchall()]

    # 获取论文标题/摘要。当前库没有 citation sentence context 时，只能给出弱
    # paper-level citation-function labels，后续应由 Sci-Bot/PDF parser 补充。
    all_ids = set()
    for e in edges:
        all_ids.add(e["citing_id"])
        all_ids.add(e["cited_id"])

    metadata = {}
    if all_ids:
        placeholders = ",".join("?" * len(all_ids))
        rows = conn_main.execute(
            f"SELECT id, title, abstract FROM papers WHERE id IN ({placeholders})",
            list(all_ids),
        ).fetchall()
        metadata = {
            row[0]: {"title": row[1] or "", "abstract": row[2] or ""}
            for row in rows
        }

    return edges, metadata


def classify_edges(
    edges: List[dict],
    metadata: dict[str, dict],
    use_llm: bool = False,
) -> List[Tuple[str, float]]:
    """
    分类所有边。优先 SciBERT,降级到 LLM。
    """
    if use_llm:
        logger.info("使用 LLM 分类 %d 条边", len(edges))
        clf = LLMCitationClassifier()
        return clf.classify_batch(edges, {k: v.get("title", "") for k, v in metadata.items()})

    if CITATION_CLASSIFIER_MODE == "heuristic":
        logger.info("使用启发式 citation-function 分类 %d 条边", len(edges))
        return [heuristic_classify_edge(edge, metadata) for edge in edges]

    # 尝试 SciBERT
    clf_scibert = SciBERTCitationClassifier()
    if not clf_scibert.is_available():
        logger.info("Transformer 分类器不可用,降级到启发式分类")
        return [heuristic_classify_edge(edge, metadata) for edge in edges]

    # 构建上下文文本
    texts = []
    for e in edges:
        citing_title = metadata.get(e["citing_id"], {}).get("title", "")
        cited_title = metadata.get(e["cited_id"], {}).get("title", "")
        text = f"Citing: {citing_title}. Cited: {cited_title}."
        texts.append(text[:512])

    results = clf_scibert.classify_batch(texts)

    # 低置信度的降级到 LLM
    low_conf_indices = [
        i for i, (_, conf) in enumerate(results)
        if conf < SCIBERT_CONFIDENCE_THRESHOLD
    ]
    if low_conf_indices:
        logger.info("低置信度边 %d 条,使用启发式修正", len(low_conf_indices))
        low_conf_edges = [edges[i] for i in low_conf_indices]
        fallback_results = [heuristic_classify_edge(edge, metadata) for edge in low_conf_edges]
        for idx, (func, conf) in zip(low_conf_indices, fallback_results):
            results[idx] = (func, conf)

        if SCIBERT_LLM_FALLBACK and len(low_conf_indices) <= SCIBERT_LLM_FALLBACK_LIMIT:
            logger.info("LLM fallback enabled for %d low-confidence edges", len(low_conf_indices))
            try:
                clf_llm = LLMCitationClassifier()
                llm_results = clf_llm.classify_batch(
                    low_conf_edges,
                    {k: v.get("title", "") for k, v in metadata.items()},
                )
                for idx, (func, conf) in zip(low_conf_indices, llm_results):
                    results[idx] = (func, conf)
            except Exception as exc:
                logger.warning("LLM 降级失败: %s", exc)

    return results


def write_classification_results(
    conn_v14: sqlite3.Connection,
    edges: List[dict],
    results: List[Tuple[str, float]],
    batch_size: int = 500,
) -> int:
    """将分类结果写回 subgraph_edges 表"""
    updates = [
        (func, conf, e["citing_id"], e["cited_id"])
        for e, (func, conf) in zip(edges, results)
    ]

    written = 0
    for i in range(0, len(updates), batch_size):
        batch = updates[i: i + batch_size]
        conn_v14.executemany("""
            UPDATE subgraph_edges
            SET citation_function = ?,
                citation_function_confidence = ?
            WHERE citing_id = ? AND cited_id = ?
        """, batch)
        conn_v14.commit()
        written += len(batch)

    return written


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def run_scibert(
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    limit: Optional[int] = None,
    resume: bool = True,
    use_llm: bool = False,
) -> dict:
    """执行 Step 5a: SciBERT 引用功能分类"""
    step_name = "step5a_scibert"
    ck = Checkpoint(step_name)

    if resume and ck.done():
        data = ck.load()
        logger.info("Step5a 已完成 (%d edges),跳过", data.get("records_n", 0))
        return data

    conn_main = sqlite3.connect(str(db_main))
    conn_main.row_factory = sqlite3.Row

    conn_v14 = get_v14b_conn(db_v14)
    upsert_step_meta(conn_v14, step_name, "running")

    edges, titles = load_subgraph_edges_with_context(conn_v14, conn_main, limit=limit)
    logger.info("待分类边: %d", len(edges))

    if not edges:
        logger.info("无待分类边,跳过")
        ck.mark_done(records_n=0)
        return {"records_n": 0}

    results = classify_edges(edges, titles, use_llm=use_llm)
    n_written = write_classification_results(conn_v14, edges, results)

    # 统计分类分布
    from collections import Counter
    func_counts = Counter(func for func, _ in results)

    conn_main.close()
    conn_v14.close()

    stats = {
        "records_n": n_written,
        "function_distribution": dict(func_counts),
    }
    upsert_step_meta(conn_v14, step_name, "done", records_n=n_written)
    ck.mark_done(records_n=n_written, meta=stats)
    logger.info("Step5a 完成: %d edges classified, dist=%s", n_written, dict(func_counts))
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.step5a_scibert",
        description="Step 5a: SciBERT 引用功能分类",
    )
    add_common_args(parser)
    parser.add_argument("--use-llm", action="store_true", help="强制使用 LLM 分类(跳过 SciBERT)")
    args = parser.parse_args(argv)

    log_level = getattr(logging, args.log_level)
    setup_logging("step5a_scibert", level=log_level)

    db_main = Path(args.db) if args.db else DB_MAIN
    db_v14 = Path(args.db_v14) if args.db_v14 else DB_V14
    limit = args.limit or LIMIT

    run_scibert(
        db_main=db_main, db_v14=db_v14,
        limit=limit, resume=args.resume,
        use_llm=args.use_llm,
    )


if __name__ == "__main__":
    main()
