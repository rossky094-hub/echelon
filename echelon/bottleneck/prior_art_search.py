"""
Prior-Art Search — AUDIT-042 + AUDIT-073 + AUDIT-044 fixes.

AUDIT-042: Replace dual-bucket search with RRF fusion across three channels:
  - Channel A: SPECTER2 ANN (Qdrant)
  - Channel B: bge-m3 ANN (Qdrant)
  - Channel C: BM25 keyword search

AUDIT-073: Strictly separate text and vector paths.
  - Vectors go to Qdrant ANN only
  - Text (description + key_concepts) goes to Cross-Encoder only
  - Cross-Encoder NEVER receives a stringified vector
  - Both paths are fused via Reciprocal Rank Fusion (RRF)

AUDIT-044: SPECTER2 was fed single-sentence claims (OOD collapse).
  Fix: embed_claim_with_context(claim, abstract, window=1) extracts claim ±1
  sentence before embedding. Also supports bge-m3 as fallback embedding
  (local or HuggingFace API) when SPECTER2 is unavailable.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

import re

logger = logging.getLogger(__name__)

# RRF constant (k=60 is standard per Cormack et al. 2009)
RRF_K = 60


# ---------------------------------------------------------------------------
# AUDIT-044: Context-window embedding for claim sentences
# ---------------------------------------------------------------------------

def _split_to_sentences(text: str) -> list[str]:
    """
    Split text into sentences using pysbd (falls back to naive split).
    Internal helper shared by embed_claim_with_context and extend_evidence.
    """
    try:
        import pysbd
        seg = pysbd.Segmenter(language="en", clean=False)
        return [s.strip() for s in seg.segment(text.strip()) if s.strip()]
    except ImportError:
        # Naive fallback: split on period/exclamation/question + space + capital
        parts = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text.strip())
        return [p.strip() for p in parts if p.strip()]


def embed_claim_with_context(
    claim: str,
    abstract: str,
    window: int = 1,
) -> str:
    """
    [AUDIT-044] Extract the claim sentence plus ±window surrounding sentences
    from the abstract, returning a richer context string for embedding.

    Feeding a single isolated claim sentence to SPECTER2 causes OOD collapse
    because SPECTER2 was trained on full abstracts / titles, not one-liners.
    Providing ±1 sentence context bridges the distribution gap.

    Args:
        claim:    The claim sentence to find in the abstract.
        abstract: Full abstract text (used as the sentence pool).
        window:   Number of sentences before and after the claim (default 1).

    Returns:
        A multi-sentence string: up to (2*window+1) sentences centred on
        the best-matching sentence. Falls back to `claim` alone if the
        abstract is empty or the claim cannot be located.

    Examples:
        >>> text = embed_claim_with_context(
        ...     "Bandwidth is limited by the Q-factor.",
        ...     "Metasurfaces have been widely studied. Bandwidth is limited by "
        ...     "the Q-factor. Future work should address this.",
        ...     window=1,
        ... )
        >>> assert "Metasurfaces" in text  # preceding sentence included
        >>> assert "Future work" in text   # following sentence included
    """
    if not abstract or not abstract.strip():
        return claim

    sentences = _split_to_sentences(abstract)
    if not sentences:
        return claim

    # Find the sentence that best overlaps with the claim (simple token overlap)
    claim_lower = claim.lower()
    best_idx: int = 0
    best_overlap: float = -1.0
    claim_tokens = set(claim_lower.split())

    for i, sent in enumerate(sentences):
        sent_tokens = set(sent.lower().split())
        if not sent_tokens:
            continue
        overlap = len(claim_tokens & sent_tokens) / len(claim_tokens | sent_tokens)
        if overlap > best_overlap:
            best_overlap = overlap
            best_idx = i

    lo = max(0, best_idx - window)
    hi = min(len(sentences), best_idx + window + 1)
    context_sentences = sentences[lo:hi]
    return " ".join(context_sentences)


def embed_text_with_specter2(
    text: str,
    specter2_model: Optional[object] = None,
) -> Optional[list[float]]:
    """
    [AUDIT-044] Embed text using SPECTER2.

    Args:
        text:           Text to embed (should be context-enriched via embed_claim_with_context).
        specter2_model: Pre-loaded SPECTER2 model/tokenizer pair.  When None,
                        attempts to load from the HuggingFace hub.

    Returns:
        768D float list, or None on failure.
    """
    if specter2_model is None:
        try:
            from transformers import AutoTokenizer, AutoModel
            import torch
            model_name = "allenai/specter2"
            tokenizer = AutoTokenizer.from_pretrained(model_name)
            model = AutoModel.from_pretrained(model_name)
            model.eval()
        except Exception as exc:
            logger.warning(f"[AUDIT-044] SPECTER2 load failed: {exc}; trying bge-m3 fallback")
            return embed_text_with_bge_m3(text)
    else:
        # Unpack tuple (model, tokenizer) or just model
        if isinstance(specter2_model, tuple):
            model, tokenizer = specter2_model
        else:
            logger.warning("[AUDIT-044] specter2_model should be (model, tokenizer) tuple")
            return None

    try:
        import torch
        inputs = tokenizer(
            text, return_tensors="pt", max_length=512, truncation=True, padding=True
        )
        with torch.no_grad():
            outputs = model(**inputs)
        embedding = outputs.last_hidden_state[:, 0, :].squeeze().tolist()
        return embedding
    except Exception as exc:
        logger.error(f"[AUDIT-044] SPECTER2 embedding failed: {exc}")
        return embed_text_with_bge_m3(text)


def embed_text_with_bge_m3(
    text: str,
    bge_model: Optional[object] = None,
) -> Optional[list[float]]:
    """
    [AUDIT-044] Embed text using bge-m3 as fallback when SPECTER2 is unavailable.

    Supports local FlagEmbedding / BAAI/bge-m3 or HuggingFace API.
    Returns 768D (or 1024D for large variant) float list, or None on failure.

    Args:
        text:      Text to embed.
        bge_model: Pre-loaded bge-m3 model (FlagModel or SentenceTransformer).
                   When None, attempts local FlagEmbedding then sentence-transformers.

    Returns:
        Float list embedding, or None on all failures.
    """
    if bge_model is not None:
        try:
            # FlagEmbedding API: model.encode(sentences, ...)
            if hasattr(bge_model, "encode"):
                result = bge_model.encode([text], max_length=512)
                if hasattr(result, "tolist"):
                    return result[0].tolist()
                if isinstance(result, list):
                    return list(result[0])
        except Exception as exc:
            logger.warning(f"[AUDIT-044] bge-m3 encode (provided model) failed: {exc}")

    # Try FlagEmbedding (BAAI/bge-m3)
    try:
        from FlagEmbedding import FlagModel  # type: ignore
        model = FlagModel(
            "BAAI/bge-m3",
            query_instruction_for_retrieval="Represent this sentence: ",
            use_fp16=True,
        )
        embeddings = model.encode([text])
        return embeddings[0].tolist()
    except ImportError:
        logger.debug("[AUDIT-044] FlagEmbedding not installed; trying sentence-transformers")
    except Exception as exc:
        logger.warning(f"[AUDIT-044] FlagEmbedding bge-m3 failed: {exc}")

    # Try sentence-transformers
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        st_model = SentenceTransformer("BAAI/bge-m3")
        embedding = st_model.encode(text, normalize_embeddings=True)
        return embedding.tolist()
    except ImportError:
        logger.debug("[AUDIT-044] sentence-transformers not installed")
    except Exception as exc:
        logger.warning(f"[AUDIT-044] sentence-transformers bge-m3 failed: {exc}")

    logger.error("[AUDIT-044] All bge-m3 fallback strategies failed")
    return None


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class PriorArtCandidate:
    """A single prior-art candidate with metadata."""
    pool_id: str
    title: str
    abstract_snippet: str = ""
    publication_year: Optional[int] = None
    source: str = "unknown"  # specter2_ann|bge_m3_ann|bm25
    score: float = 0.0
    rrf_score: float = 0.0


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion  [AUDIT-042, AUDIT-073]
# ---------------------------------------------------------------------------

def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],
    k: int = RRF_K,
) -> list[tuple[str, float]]:
    """
    Fuse multiple ranked lists using Reciprocal Rank Fusion (RRF).

    RRF score for document d: sum_{r in R} 1/(k + rank_r(d))
    where R is the set of ranked lists that contain d.

    Args:
        ranked_lists: Each inner list is a ranking of pool_ids (best first).
        k:            RRF constant. Default 60.

    Returns:
        List of (pool_id, rrf_score) sorted descending by rrf_score.
    """
    scores: dict[str, float] = {}
    for ranked_list in ranked_lists:
        for rank, doc_id in enumerate(ranked_list):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


# ---------------------------------------------------------------------------
# Channel A: SPECTER2 ANN  [AUDIT-073 — vectors only, no stringify]
# ---------------------------------------------------------------------------

def search_specter2_ann(
    query_vector: list[float],  # 768D numpy array or list — NEVER stringified
    qdrant_client: Optional[object],
    collection: str = "paper_abstract_specter2",
    limit: int = 200,
) -> list[str]:
    """
    ANN search using SPECTER2 embeddings via Qdrant.

    [AUDIT-073] Vectors ONLY go here — NEVER to Cross-Encoder.
    The raw float vector is passed directly to Qdrant ANN.
    No string conversion of the vector occurs at any point.

    Returns:
        Ranked list of pool_ids.
    """
    if qdrant_client is None:
        logger.warning("qdrant_client is None; skipping SPECTER2 ANN search")
        return []

    try:
        results = qdrant_client.search(
            collection_name=collection,
            query_vector=query_vector,  # raw float array, NOT str()
            limit=limit,
            score_threshold=0.5,
        )
        return [str(r.id) for r in results]
    except Exception as exc:
        logger.error(f"SPECTER2 ANN search failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Channel B: bge-m3 ANN  [AUDIT-073 — vectors only]
# ---------------------------------------------------------------------------

def search_bge_m3_ann(
    query_vector: list[float],  # 768D bge-m3 embedding — NEVER stringified
    qdrant_client: Optional[object],
    collection: str = "section_chunk_bge_m3",
    limit: int = 200,
) -> list[str]:
    """
    ANN search using bge-m3 embeddings via Qdrant.

    [AUDIT-073] Same contract as search_specter2_ann — vector path only.

    Returns:
        Ranked list of pool_ids.
    """
    if qdrant_client is None:
        logger.warning("qdrant_client is None; skipping bge-m3 ANN search")
        return []

    try:
        results = qdrant_client.search(
            collection_name=collection,
            query_vector=query_vector,  # raw float array — NOT stringified
            limit=limit,
            score_threshold=0.5,
        )
        return [str(r.id) for r in results]
    except Exception as exc:
        logger.error(f"bge-m3 ANN search failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Channel C: BM25 keyword search  [AUDIT-042]
# ---------------------------------------------------------------------------

def search_bm25(
    query_text: str,   # text only — never a vector
    corpus: list[dict],  # [{pool_id, title, abstract_snippet}, ...]
    limit: int = 200,
) -> list[str]:
    """
    BM25 keyword search over the prior-art corpus.

    [AUDIT-073] Text path — receives description/key_concepts text ONLY.
    Never receives a vector representation.

    Simple BM25 implementation for offline use.
    In production, use a proper BM25 library (rank_bm25, elasticsearch, etc.).

    Returns:
        Ranked list of pool_ids.
    """
    if not corpus or not query_text.strip():
        return []

    try:
        from rank_bm25 import BM25Okapi  # type: ignore
        tokenized_corpus = [
            (doc.get("title", "") + " " + doc.get("abstract_snippet", "")).lower().split()
            for doc in corpus
        ]
        bm25 = BM25Okapi(tokenized_corpus)
        query_tokens = query_text.lower().split()
        scores = bm25.get_scores(query_tokens)

        # Return top-limit pool_ids sorted by score
        indexed = [(corpus[i]["pool_id"], scores[i]) for i in range(len(corpus))]
        indexed.sort(key=lambda x: x[1], reverse=True)
        return [pid for pid, _ in indexed[:limit]]

    except ImportError:
        # Fallback: simple TF-IDF-like scoring
        logger.warning("rank_bm25 not installed; using simple keyword overlap BM25 fallback")
        query_terms = set(query_text.lower().split())
        scored = []
        for doc in corpus:
            doc_text = (doc.get("title", "") + " " + doc.get("abstract_snippet", "")).lower()
            doc_terms = set(doc_text.split())
            overlap = len(query_terms & doc_terms)
            scored.append((doc["pool_id"], overlap))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [pid for pid, _ in scored[:limit]]


# ---------------------------------------------------------------------------
# Cross-Encoder reranking  [AUDIT-073]
# ---------------------------------------------------------------------------

def rerank_with_cross_encoder(
    query_text: str,        # TEXT only — description + key_concepts
    candidates: list[dict], # [{pool_id, title, abstract_snippet}, ...]
    cross_encoder: Optional[object] = None,
    top_k: int = 50,
) -> list[str]:
    """
    Rerank candidates using a cross-encoder.

    [AUDIT-073] STRICT CONTRACT:
    - Input: query_text (pure text, description + key_concepts)
    - Input: candidates with title + abstract_snippet (text fields)
    - NEVER: vector arrays, NEVER: str(embedding_array)

    V11.1 bug: `description + cluster_centroid_embedding` concatenated a 768D
    numpy array as a string (6000+ char digit noise) → bge-reranker exceeded
    512 token limit → transformer attention destroyed.

    V11.2 fix: cross-encoder receives only text.

    Returns:
        Ranked list of pool_ids.
    """
    if not candidates:
        return []

    if cross_encoder is None:
        # No reranker available — return in original order
        return [c["pool_id"] for c in candidates[:top_k]]

    try:
        pairs = [
            (query_text, f"{c.get('title', '')} {c.get('abstract_snippet', '')}"[:512])
            for c in candidates[:top_k * 2]
        ]
        scores = cross_encoder.predict(pairs)
        indexed = [(candidates[i]["pool_id"], float(scores[i])) for i in range(len(pairs))]
        indexed.sort(key=lambda x: x[1], reverse=True)
        return [pid for pid, _ in indexed[:top_k]]
    except Exception as exc:
        logger.error(f"Cross-encoder rerank failed: {exc}")
        return [c["pool_id"] for c in candidates[:top_k]]


# ---------------------------------------------------------------------------
# RRF Fusion — main entry point  [AUDIT-042, AUDIT-073]
# ---------------------------------------------------------------------------

def search_prior_art_rrf(
    # [AUDIT-073] TEXT and VECTOR are STRICTLY SEPARATED
    query_text: str,            # For BM25 + Cross-Encoder (text path)
    query_vector_specter2: Optional[list[float]] = None,  # For Qdrant ANN (vector path)
    query_vector_bge_m3: Optional[list[float]] = None,    # For Qdrant ANN (vector path)
    corpus: Optional[list[dict]] = None,
    qdrant_client: Optional[object] = None,
    cross_encoder: Optional[object] = None,
    limit: int = 50,
    rrf_k: int = RRF_K,
) -> list[PriorArtCandidate]:
    """
    Three-channel RRF fusion prior-art search.

    [AUDIT-042] Replaces dual-bucket search with unified RRF across:
      - Channel A: SPECTER2 ANN (Qdrant)
      - Channel B: bge-m3 ANN (Qdrant)
      - Channel C: BM25 keyword

    [AUDIT-073] Strict text/vector separation:
      - query_text → BM25 (Channel C) + Cross-Encoder rerank
      - query_vector_* → Qdrant ANN only (Channels A, B)
      - Vectors are NEVER stringified or passed to Cross-Encoder

    Args:
        query_text:            Description + key_concepts (text only).
        query_vector_specter2: 768D SPECTER2 embedding (None to skip).
        query_vector_bge_m3:   768D bge-m3 embedding (None to skip).
        corpus:                List of {pool_id, title, abstract_snippet} dicts.
        qdrant_client:         Qdrant client instance (None for offline tests).
        cross_encoder:         Cross-encoder model (None to skip reranking).
        limit:                 Number of results to return.
        rrf_k:                 RRF constant (default 60).

    Returns:
        List of PriorArtCandidate sorted by RRF score (best first).
    """
    ranked_lists: list[list[str]] = []

    # ── Channel A: SPECTER2 ANN ─────────────────────────────────────────────
    if query_vector_specter2 is not None and qdrant_client is not None:
        # [AUDIT-073] Pass float vector directly — NEVER str(vector)
        specter2_results = search_specter2_ann(
            query_vector=query_vector_specter2,  # raw floats
            qdrant_client=qdrant_client,
            limit=200,
        )
        if specter2_results:
            ranked_lists.append(specter2_results)
            logger.debug(f"SPECTER2 ANN: {len(specter2_results)} results")

    # ── Channel B: bge-m3 ANN ───────────────────────────────────────────────
    if query_vector_bge_m3 is not None and qdrant_client is not None:
        # [AUDIT-073] Pass float vector directly — NEVER str(vector)
        bge_results = search_bge_m3_ann(
            query_vector=query_vector_bge_m3,  # raw floats
            qdrant_client=qdrant_client,
            limit=200,
        )
        if bge_results:
            ranked_lists.append(bge_results)
            logger.debug(f"bge-m3 ANN: {len(bge_results)} results")

    # ── Channel C: BM25 keyword ─────────────────────────────────────────────
    if corpus and query_text.strip():
        # [AUDIT-073] Text path — receives text ONLY
        bm25_results = search_bm25(
            query_text=query_text,  # text only
            corpus=corpus,
            limit=200,
        )
        if bm25_results:
            ranked_lists.append(bm25_results)
            logger.debug(f"BM25: {len(bm25_results)} results")

    if not ranked_lists:
        logger.warning("All three search channels returned empty results")
        return []

    # ── RRF Fusion ──────────────────────────────────────────────────────────
    fused = reciprocal_rank_fusion(ranked_lists, k=rrf_k)

    # Build corpus lookup
    corpus_map: dict[str, dict] = {}
    if corpus:
        corpus_map = {str(doc["pool_id"]): doc for doc in corpus}

    # Optionally rerank top candidates with cross-encoder (text only)
    top_pool_ids = [pid for pid, _ in fused[:limit * 2]]
    top_candidates = [corpus_map.get(pid, {"pool_id": pid}) for pid in top_pool_ids]

    if cross_encoder is not None and top_candidates:
        # [AUDIT-073] Cross-encoder gets TEXT only: query_text vs abstract_snippet
        reranked_ids = rerank_with_cross_encoder(
            query_text=query_text,   # text only
            candidates=top_candidates,
            cross_encoder=cross_encoder,
            top_k=limit,
        )
        # Use reranked order, supplemented by RRF scores for ties
        rrf_dict = dict(fused)
        result_ids = reranked_ids
    else:
        result_ids = top_pool_ids[:limit]

    # Assemble final results
    results: list[PriorArtCandidate] = []
    rrf_dict = dict(fused)
    for pid in result_ids:
        doc = corpus_map.get(pid, {"pool_id": pid})
        results.append(PriorArtCandidate(
            pool_id=pid,
            title=doc.get("title", ""),
            abstract_snippet=doc.get("abstract_snippet", ""),
            publication_year=doc.get("publication_year"),
            source="rrf_fusion",
            rrf_score=rrf_dict.get(pid, 0.0),
        ))

    return results
