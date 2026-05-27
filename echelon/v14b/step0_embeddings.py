"""Step 0.3: build paper abstract embeddings for graph layout and VGAE."""
from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Optional

import numpy as np

from echelon.v14b.config import DB_MAIN
from echelon.v14b.utils import make_progress, setup_logging

logger = logging.getLogger("echelon.v14b.step0_embeddings")


def available_memory_gb() -> Optional[float]:
    """Best-effort macOS available memory estimate for embedding batch caps."""
    try:
        out = subprocess.check_output(["vm_stat"], text=True, timeout=3)
    except Exception:
        return None
    page_size = 16384
    m = re.search(r"page size of (\d+) bytes", out)
    if m:
        page_size = int(m.group(1))
    pages = {}
    for key in ("Pages free", "Pages speculative", "Pages inactive", "Pages purgeable"):
        m = re.search(rf"{key}:\s+(\d+)", out)
        if m:
            pages[key] = int(m.group(1))
    available_bytes = (
        pages.get("Pages free", 0)
        + pages.get("Pages speculative", 0)
        + pages.get("Pages inactive", 0)
        + pages.get("Pages purgeable", 0)
    ) * page_size
    return available_bytes / (1024 ** 3)


def memory_capped_batch_size(requested: int) -> int:
    avail_gb = available_memory_gb()
    requested = max(1, requested)
    if avail_gb is None:
        return requested
    if avail_gb < 1.5:
        cap = 4
    elif avail_gb < 3.0:
        cap = 8
    elif avail_gb < 6.0:
        cap = 16
    else:
        cap = requested
    capped = max(1, min(requested, cap))
    if capped != requested:
        logger.warning(
            "Capping embedding batch size from %d to %d because available memory is %.2f GiB",
            requested,
            capped,
            avail_gb,
        )
    else:
        logger.info("Embedding batch size=%d; available memory %.2f GiB", capped, avail_gb)
    return capped


def ensure_embedding_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_embeddings (
            paper_id TEXT PRIMARY KEY,
            model_id TEXT NOT NULL,
            embedding_dim INTEGER NOT NULL,
            embedding_blob BLOB NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def build_embeddings(
    db_path: Path = DB_MAIN,
    *,
    model_id: str = "sentence-transformers/all-mpnet-base-v2",
    batch_size: int = 16,
    limit: Optional[int] = None,
) -> dict:
    """Generate sentence-transformer embeddings for title + abstract."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is required for paper embeddings; "
            "install requirements-v14b.txt first"
        ) from exc

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_embedding_table(conn)
    batch_size = memory_capped_batch_size(batch_size)

    q = """
        SELECT id, title, abstract
        FROM papers
        WHERE abstract IS NOT NULL
          AND length(trim(abstract)) > 0
          AND id NOT IN (SELECT paper_id FROM paper_embeddings WHERE model_id = ?)
        ORDER BY publication_date, id
    """
    params: list = [model_id]
    if limit:
        q += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(q, params).fetchall()
    logger.info("待生成 embedding: %d", len(rows))
    if not rows:
        conn.close()
        return {"records_n": 0, "model_id": model_id}

    model = SentenceTransformer(model_id)
    written = 0
    with make_progress(range(0, len(rows), batch_size), desc="Embeddings") as pbar:
        for start in pbar:
            batch = rows[start:start + batch_size]
            texts = [
                ((r["title"] or "") + "\n\n" + (r["abstract"] or ""))[:6000]
                for r in batch
            ]
            vectors = model.encode(
                texts,
                batch_size=batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            upserts = []
            for row, vec in zip(batch, vectors):
                arr = np.asarray(vec, dtype=np.float32)
                upserts.append((row["id"], model_id, int(arr.shape[0]), arr.tobytes()))
            conn.executemany("""
                INSERT OR REPLACE INTO paper_embeddings
                    (paper_id, model_id, embedding_dim, embedding_blob, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, upserts)
            conn.commit()
            written += len(upserts)
            pbar.set_postfix(written=written)

    conn.close()
    stats = {"records_n": written, "model_id": model_id}
    logger.info("Embedding build done: %s", stats)
    return stats


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Build V14B paper embeddings")
    parser.add_argument("--db", type=Path, default=DB_MAIN)
    parser.add_argument("--model", default="sentence-transformers/all-mpnet-base-v2")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    setup_logging("step0_embeddings")
    build_embeddings(
        args.db,
        model_id=args.model,
        batch_size=args.batch_size,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
