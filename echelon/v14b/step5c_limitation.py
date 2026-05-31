"""
Step 5c: section-first Limitation 抽取 + Limitation Tracking

当前 V14B 主流程默认不调用外部 LLM。Step5c 先使用已入库 section
evidence 提取 limitation / discussion / conclusion 等段落,再用可重跑的
启发式规则把 limitation 段原子化并跟踪 resolution。LLM opt-in 只允许作为
弱证据辅助抽检/命名/解释,必须保留 extractor_method 与 evidence_quality。

4 个阶段:
  Phase 1: 从结构化 section evidence 选取 limitation/context 段落
  Phase 2: section-first/heuristic 原子化 limitation atoms
  Phase 3: 对每个 atom 遍历后续引用,用可审计规则标记 candidate resolution
  Phase 4: 排序未解决 atoms,供 Step6/Step13 形成低置信候选或 Claim Card 证据

支持中断恢复: 每个 atom/resolution 完成后立即 commit DB

CLI:
    python -m echelon.v14b.step5c_limitation --help
    python -m echelon.v14b.step5c_limitation
    python -m echelon.v14b.step5c_limitation --limit 50  # 只跑 50 篇
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, List, Dict

from echelon.v14b.corpus_registry import create_temp_corpus_table, ensure_corpus_schema
from echelon.v14b.config import (
    DB_MAIN, DB_V14,
    LIMITATION_TOP_N, LIMITATION_MAX_ATOMS_PER_PAPER,
    LIMITATION_MAX_RESOLVERS, LIMITATION_TOP_UNRESOLVED,
    SKIP_LIMITATION_RESOLUTION, LIMITATION_USE_LLM,
    LIMITATION_REQUIRE_SECTION_EVIDENCE, LIMITATION_ALLOW_ABSTRACT_FALLBACK,
    LIMIT,
)
from echelon.v14b.db_schema import get_v14b_conn, upsert_step_meta
from echelon.v14b.llm_client import LLMClient
from echelon.v14b.utils import (
    setup_logging, Checkpoint, add_common_args, make_progress
)

logger = logging.getLogger("echelon.v14b.step5c_limitation")

LIMITATION_EVIDENCE_PROFILES = {
    "structured_sections": ("section_level", 0.75),
    "section_atoms": ("section_level", 0.82),
    "abstract": ("weak_abstract", 0.35),
}

SECTION_ATOM_LIMITATION_TYPES = {
    "constraint",
    "failure_mechanism",
    "new_constraint",
}

SECTION_ATOM_GRADE_WEIGHT = {
    "section_atom_decision_grade": 0.90,
    "section_atom_traced": 0.78,
    "section_atom_weak": 0.52,
}

SECTION_ATOM_BRIDGE_VERSION = "section_atom_bridge_v6_strict_attach_filter"

SECTION_ATOM_BRIDGE_TERMS = re.compile(
    r"\b(limitations?|limited|limits|limiting|challenge[sd]?|bottleneck|drawback|constraint|"
    r"future work|open question|not yet|cannot|"
    r"difficult|scalab(?:le|ility)|expensive|loss|noise|unstable|"
    r"insufficient|degrad(?:e|es|ation)|fail(?:ed|ure|s)?|fabrication error)\b",
    re.I,
)

SECTION_ATOM_BRIDGE_RESOLUTION_TERMS = re.compile(
    r"\b(overcome(?:s|d)?|address(?:es|ed)?|resolve(?:s|d)?|mitigate(?:s|d)?|"
    r"enable(?:d|s)?|improv(?:e|ed|es|ement)|"
    r"achiev(?:e|ed|es)|demonstrat(?:e|ed|es))\b",
    re.I,
)

SECTION_ATOM_BRIDGE_OPEN_PROBLEM_TERMS = re.compile(
    r"\b(still|remain(?:s|ing)?|yet|however|but|challenge[sd]?|bottleneck|"
    r"constraint|insufficient|fail(?:ed|ure|s)?|cannot)\b",
    re.I,
)

SECTION_ATOM_BRIDGE_FALSE_START = re.compile(
    r"^\s*((fig(?:ure)?|table|eq(?:uation)?|supplementary)\b|s\d+\b|\d+[a-z]\b|\d+[a-z]?\))",
    re.I,
)

LIMITATION_ATOM_PROVENANCE_COLUMNS = {
    "source_section_atom_id": "TEXT",
    "source_section_atom_type": "TEXT",
    "source_section_atom_evidence_grade": "TEXT",
    "source_storage_uri": "TEXT",
    "source_page_start": "INTEGER",
    "source_page_end": "INTEGER",
    "source_parser_contract_version": "TEXT",
}

PRIMARY_LIMITATION_SECTION_NAMES = (
    "limitations",
    "limitation",
    "discussion",
    "conclusion",
    "conclusions",
    "future work",
)

SECONDARY_CONTEXT_SECTION_NAMES = (
    "results",
    "result",
    "error analysis",
    "ablation",
    "method",
    "methods",
    "methodology",
    "experiments",
)

TARGET_SECTION_PRIORITY = {
    name.lower(): idx
    for idx, name in enumerate(PRIMARY_LIMITATION_SECTION_NAMES + SECONDARY_CONTEXT_SECTION_NAMES)
}

LIMITATION_TERMS = re.compile(
    r"\b(limit(?:ation)?s?|challenge[sd]?|bottleneck|drawback|constraint|"
    r"remain(?:s|ing)?|future work|open question|not yet|however|although|"
    r"requires?|difficult|scalab(?:le|ility)|expensive|loss|noise|unstable)\b",
    re.I,
)
RESOLUTION_TERMS = re.compile(
    r"\b(overcome|resolve|mitigate|address|improve|improved|enable|enabled|"
    r"demonstrate|scalable|room-temperature|low-loss|robust|efficient|"
    r"high-performance|integrated)\b",
    re.I,
)

HEURISTIC_RESOLUTION_EVIDENCE_TEXT = (
    "Algorithmic lexical match between limitation keyword and resolver claim."
)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'virtual table') AND name = ?",
        (table,),
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_limitation_atom_provenance_schema(conn_v14: sqlite3.Connection) -> None:
    if not _table_exists(conn_v14, "limitation_atoms"):
        return
    cols = _columns(conn_v14, "limitation_atoms")
    for col, col_type in LIMITATION_ATOM_PROVENANCE_COLUMNS.items():
        if col not in cols:
            conn_v14.execute(f"ALTER TABLE limitation_atoms ADD COLUMN {col} {col_type}")
    conn_v14.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_limitation_atoms_source_section_atom
        ON limitation_atoms (source_section_atom_id)
        """
    )
    conn_v14.commit()

# ---------------------------------------------------------------------------
# Prompt 模板
# ---------------------------------------------------------------------------

LIMITATION_EXTRACT_PROMPT = """\
Read the following academic paper abstract and extract 3-5 specific technical limitations.

Paper title: {title}
Abstract: {abstract}

For each limitation, provide:
- description: A clear, specific description of the limitation (1-2 sentences)
- keyword: The key technical term for this limitation (1-3 words)
- severity: "high", "medium", or "low" (based on impact on the field)

Reply with JSON only (no markdown):
{{
  "limitations": [
    {{"description": "...", "keyword": "...", "severity": "high/medium/low"}},
    ...
  ]
}}

If the paper has no clear technical limitations, return {{"limitations": []}}."""

RESOLUTION_CHECK_PROMPT = """\
Determine if a newer paper resolves a specific limitation from an older paper.

Limitation from older paper:
- Paper: {older_title}
- Limitation: {limitation_description}
- Technical keyword: {keyword}

Potential resolver paper:
- Title: {newer_title}
- Abstract: {newer_abstract}

Does the newer paper explicitly or implicitly RESOLVE, OVERCOME, or SIGNIFICANTLY MITIGATE this limitation?

Reply with JSON only:
{{
  "resolves": true/false,
  "confidence": <0.0-1.0>,
  "evidence": "<1 sentence explanation if resolves=true>"
}}"""


# ---------------------------------------------------------------------------
# Phase 1: 抽取 limitation 段
# ---------------------------------------------------------------------------

def get_top_papers_for_limitation(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    n: int = LIMITATION_TOP_N,
    corpus_id: str | None = None,
) -> List[dict]:
    """
    获取 top N 关键石论文(按 keystone_score_v14),
    且在子图中,用于 limitation 抽取。
    """
    rows = conn_v14.execute("""
        SELECT paper_id, keystone_score_v14
        FROM subgraph_nodes
        WHERE is_keystone = 1
        ORDER BY keystone_score_v14 DESC
        LIMIT ?
    """, (n,)).fetchall()
    keystone_ids = [row[0] for row in rows]

    if not keystone_ids:
        # fallback: 任意子图节点
        rows = conn_v14.execute(f"SELECT paper_id FROM subgraph_nodes LIMIT {n}").fetchall()
        keystone_ids = [row[0] for row in rows]

    placeholders = ",".join("?" * len(keystone_ids))
    papers = [dict(p) for p in conn_main.execute(f"""
        SELECT id, title, abstract
        FROM papers
        WHERE id IN ({placeholders})
          {"AND id IN (SELECT paper_id FROM temp.v14b_corpus_papers)" if corpus_id else ""}
          AND abstract IS NOT NULL
          AND LENGTH(abstract) > 100
    """, keystone_ids).fetchall()]

    # Prefer structured full-text sections when a future Sci-Bot/PDF parser
    # has materialized them. Fall back to abstracts only when no section table
    # exists yet.
    table_names = {
        row[0] for row in conn_main.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    section_table = None
    for candidate in ("paper_sections", "scibot_sections", "paper_fulltext_sections"):
        if candidate in table_names:
            section_table = candidate
            break
    if section_table:
        ids = [p["id"] for p in papers]
        ph = ",".join("?" * len(ids))
        target_sections = PRIMARY_LIMITATION_SECTION_NAMES + SECONDARY_CONTEXT_SECTION_NAMES
        sec_placeholders = ",".join("?" * len(target_sections))
        try:
            rows = conn_main.execute(f"""
                SELECT paper_id, section_name, section_text
                FROM {section_table}
                WHERE paper_id IN ({ph})
                  AND lower(section_name) IN ({sec_placeholders})
            """, (*ids, *target_sections)).fetchall()
            sections_by_paper: dict[str, list[dict]] = {}
            for row in rows:
                section_name = (row[1] or "").strip()
                section_text = (row[2] or "").strip()
                if not section_name or not section_text:
                    continue
                sections_by_paper.setdefault(row[0], []).append({
                    "section_name": section_name,
                    "section_text": section_text,
                })
            for paper in papers:
                sections = sorted(
                    sections_by_paper.get(paper["id"], []),
                    key=lambda item: (
                        TARGET_SECTION_PRIORITY.get(item["section_name"].lower(), 999),
                        item["section_name"].lower(),
                    ),
                )
                if sections:
                    paper["limitation_text_sections"] = sections
                    paper["limitation_text"] = "\n\n".join(
                        f"[{item['section_name']}]\n{item['section_text']}"
                        for item in sections
                    )[:6000]
                    paper["limitation_evidence_source"] = "structured_sections"
                    if len(sections) == 1:
                        paper["limitation_source_section_name"] = sections[0]["section_name"][:200]
        except sqlite3.Error as exc:
            logger.warning("Structured section lookup failed: %s", exc)

    if "section_atoms" in table_names:
        try:
            _attach_section_atom_limitations(conn_main, papers)
        except sqlite3.Error as exc:
            logger.warning("Section atom limitation lookup failed: %s", exc)

    section_ready = [
        p for p in papers
        if p.get("limitation_evidence_source") in {"structured_sections", "section_atoms"}
        or p.get("limitation_section_atoms")
    ]
    if LIMITATION_REQUIRE_SECTION_EVIDENCE:
        if not section_table:
            logger.warning(
                "Step5c strict mode: no section table found; limitation extraction will return 0 "
                "until Step5s paper_sections/scibot_sections is ingested."
            )
        papers = section_ready
    elif not LIMITATION_ALLOW_ABSTRACT_FALLBACK:
        # Soft strict mode: do not consume abstract-only evidence, but keep
        # pipeline compatibility by returning any section-ready papers.
        papers = section_ready

    if not papers:
        return []

    for paper in papers:
        source = paper.get("limitation_evidence_source") or "abstract"
        quality, weight = LIMITATION_EVIDENCE_PROFILES[source]
        paper["limitation_evidence_source"] = source
        paper["limitation_evidence_quality"] = quality
        paper["limitation_evidence_weight"] = weight

    return papers


def _attach_section_atom_limitations(conn_main: sqlite3.Connection, papers: list[dict]) -> None:
    ids = [str(p["id"]) for p in papers if p.get("id")]
    if not ids:
        return
    cols = _columns(conn_main, "section_atoms")
    required = {
        "atom_id",
        "paper_id",
        "section_name",
        "atom_type",
        "atom_text",
        "evidence_grade",
    }
    if not required <= cols:
        return
    placeholders = ",".join("?" * len(ids))
    type_placeholders = ",".join("?" * len(SECTION_ATOM_LIMITATION_TYPES))
    page_start = "page_start" if "page_start" in cols else "NULL AS page_start"
    page_end = "page_end" if "page_end" in cols else "NULL AS page_end"
    source_url = "source_url" if "source_url" in cols else "'' AS source_url"
    source_storage_uri = "source_storage_uri" if "source_storage_uri" in cols else "'' AS source_storage_uri"
    parser_contract = (
        "parser_contract_version"
        if "parser_contract_version" in cols
        else "'legacy_unknown_contract' AS parser_contract_version"
    )
    source_delivery = "source_delivery" if "source_delivery" in cols else "'' AS source_delivery"
    rows = conn_main.execute(
        f"""
        SELECT atom_id, paper_id, section_name, atom_type, atom_text,
               evidence_grade, {page_start}, {page_end}, {source_url},
               {source_storage_uri}, {parser_contract}, {source_delivery}
        FROM section_atoms
        WHERE paper_id IN ({placeholders})
          AND atom_type IN ({type_placeholders})
        ORDER BY
            paper_id,
            CASE evidence_grade
                WHEN 'section_atom_decision_grade' THEN 0
                WHEN 'section_atom_traced' THEN 1
                ELSE 2
            END,
            CASE atom_type
                WHEN 'constraint' THEN 0
                WHEN 'new_constraint' THEN 1
                ELSE 2
            END,
            section_name,
            atom_id
        """,
        (*ids, *sorted(SECTION_ATOM_LIMITATION_TYPES)),
    ).fetchall()
    by_paper: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        atom_text = re.sub(r"\s+", " ", str(row["atom_text"] or "")).strip()
        if not _is_section_atom_bridge_candidate(atom_text):
            continue
        paper_id = str(row["paper_id"])
        bucket = by_paper.setdefault(paper_id, [])
        if len(bucket) >= LIMITATION_MAX_ATOMS_PER_PAPER:
            continue
        item = dict(row)
        item["atom_text"] = atom_text
        bucket.append(item)
    for paper in papers:
        atoms = by_paper.get(str(paper.get("id") or ""))
        if not atoms:
            continue
        paper["limitation_section_atoms"] = atoms
        paper["limitation_evidence_source"] = "section_atoms"
        paper["limitation_evidence_quality"] = "section_level"
        paper["limitation_evidence_weight"] = max(
            SECTION_ATOM_GRADE_WEIGHT.get(str(atom.get("evidence_grade") or ""), 0.52)
            for atom in atoms
        )


# ---------------------------------------------------------------------------
# Phase 2: 原子化 limitation
# ---------------------------------------------------------------------------

def extract_limitation_atoms(
    paper: dict,
    llm_client,
) -> List[dict]:
    """
    从 section/abstract evidence 抽取 limitation atoms。

    默认路径是 deterministic heuristic；只有显式传入 llm_client 时才调用
    LLM,并通过 _limitation_evidence_common 继承 weak/section evidence
    provenance,不能自动升级为决策级证据。
    """
    section_atom_atoms = section_atom_limitation_atoms(paper)
    if section_atom_atoms:
        return section_atom_atoms

    text = (paper.get("limitation_text") or paper.get("abstract", "") or "")[:6000]
    if llm_client is None:
        return heuristic_limitation_atoms(paper, text)

    atoms = []
    for source_section_name, chunk_text in _limitation_text_chunks(paper, text):
        common = _limitation_evidence_common(
            paper,
            "llm",
            source_section_name=source_section_name,
        )
        prompt = LIMITATION_EXTRACT_PROMPT.format(
            title=paper.get("title", "")[:200],
            abstract=chunk_text[:3000],
        )

        try:
            result = llm_client.extract_json(prompt, max_tokens=800)
            limitations = result.get("limitations", [])
            if not isinstance(limitations, list):
                continue

            for lim in limitations:
                desc = lim.get("description", "").strip()
                if not desc:
                    continue
                atoms.append({
                    "paper_id": paper["id"],
                    "description": desc,
                    "keyword": lim.get("keyword", "").strip()[:100],
                    "severity": lim.get("severity", "medium").lower(),
                    **common,
                })
                if len(atoms) >= LIMITATION_MAX_ATOMS_PER_PAPER:
                    return atoms
        except Exception as exc:
            logger.warning(
                "limitation 抽取失败 paper_id=%s section=%s: %s",
                paper["id"],
                source_section_name or "",
                exc,
            )
    return atoms


def section_atom_limitation_atoms(paper: dict) -> list[dict]:
    """Bridge pre-materialized section_atoms into Step5c limitation_atoms."""
    raw_atoms = paper.get("limitation_section_atoms") or []
    if not isinstance(raw_atoms, list):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for raw in raw_atoms:
        if not isinstance(raw, dict):
            continue
        atom_type = str(raw.get("atom_type") or "")
        text = re.sub(r"\s+", " ", str(raw.get("atom_text") or "")).strip()
        source_atom_id = str(raw.get("atom_id") or "")
        if atom_type not in SECTION_ATOM_LIMITATION_TYPES or not text or not source_atom_id:
            continue
        if not _is_section_atom_bridge_candidate(text):
            continue
        key = source_atom_id or text[:120].lower()
        if key in seen:
            continue
        seen.add(key)
        evidence_grade = str(raw.get("evidence_grade") or "section_atom_weak")
        weight = SECTION_ATOM_GRADE_WEIGHT.get(evidence_grade, 0.52)
        out.append(
            {
                "paper_id": paper["id"],
                "description": text[:500],
                "keyword": _keyword_from_limitation_text(text),
                "severity": _severity_from_section_atom(raw, text),
                "evidence_source": "section_atoms",
                "evidence_quality": "section_level",
                "evidence_weight": weight,
                "source_section_name": str(raw.get("section_name") or ""),
                "extractor_method": "section_atom_bridge",
                "source_section_atom_id": source_atom_id,
                "source_section_atom_type": atom_type,
                "source_section_atom_evidence_grade": evidence_grade,
                "source_storage_uri": raw.get("source_storage_uri") or "",
                "source_page_start": raw.get("page_start"),
                "source_page_end": raw.get("page_end"),
                "source_parser_contract_version": raw.get("parser_contract_version") or "legacy_unknown_contract",
            }
        )
        if len(out) >= LIMITATION_MAX_ATOMS_PER_PAPER:
            break
    return out


def _is_section_atom_bridge_candidate(text: str) -> bool:
    if not text or len(text.strip()) < 50:
        return False
    if SECTION_ATOM_BRIDGE_FALSE_START.search(text):
        return False
    if (
        SECTION_ATOM_BRIDGE_RESOLUTION_TERMS.search(text)
        and not SECTION_ATOM_BRIDGE_OPEN_PROBLEM_TERMS.search(text)
    ):
        return False
    return bool(SECTION_ATOM_BRIDGE_TERMS.search(text))


def _keyword_from_limitation_text(text: str) -> str:
    keyword_match = re.search(
        r"\b(scalability|efficiency|loss|noise|stability|fabrication|"
        r"power|bandwidth|resolution|temperature|integration|dispersion|"
        r"coupling|nonlinearity|sensitivity|thermal|manufacturing|yield)\b",
        text,
        re.I,
    )
    return (keyword_match.group(1).lower() if keyword_match else "technical limitation")[:100]


def _severity_from_section_atom(atom: dict, text: str) -> str:
    evidence_grade = str(atom.get("evidence_grade") or "")
    atom_type = str(atom.get("atom_type") or "")
    if (
        evidence_grade == "section_atom_decision_grade"
        and atom_type in {"constraint", "new_constraint"}
    ):
        return "high"
    if re.search(r"\b(severe|critical|fundamental|major|limited|requires?|bottleneck)\b", text, re.I):
        return "high"
    return "medium"


def _limitation_text_chunks(paper: dict, fallback_text: str) -> list[tuple[str | None, str]]:
    chunks = []
    sections = paper.get("limitation_text_sections")
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict):
                continue
            section_name = (section.get("section_name") or "").strip() or None
            section_text = (section.get("section_text") or "").strip()
            if section_text:
                chunks.append((section_name, section_text[:6000]))
    if chunks:
        return chunks
    return [(paper.get("limitation_source_section_name"), (fallback_text or "")[:6000])]


def _limitation_evidence_common(
    paper: dict,
    method: str,
    source_section_name: str | None = None,
) -> dict:
    source = paper.get("limitation_evidence_source") or "abstract"
    quality = paper.get("limitation_evidence_quality")
    weight = paper.get("limitation_evidence_weight")
    if quality is None or weight is None:
        quality, weight = LIMITATION_EVIDENCE_PROFILES.get(source, LIMITATION_EVIDENCE_PROFILES["abstract"])
    return {
        "evidence_source": source,
        "evidence_quality": quality,
        "evidence_weight": float(weight),
        "source_section_name": source_section_name or paper.get("limitation_source_section_name"),
        "extractor_method": method,
    }


def heuristic_limitation_atoms(paper: dict, text: str) -> List[dict]:
    """Algorithmic limitation extraction used by the product chain by default."""
    atoms = []
    seen = set()
    for source_section_name, chunk_text in _limitation_text_chunks(paper, text):
        common = _limitation_evidence_common(
            paper,
            "heuristic",
            source_section_name=source_section_name,
        )
        sentences = [
            s.strip()
            for s in re.split(r"(?<=[.!?])\s+", chunk_text or "")
            if len(s.strip()) > 40
        ]
        for sent in sentences:
            if not LIMITATION_TERMS.search(sent):
                continue
            keyword_match = re.search(
                r"\b(scalability|efficiency|loss|noise|stability|fabrication|"
                r"power|bandwidth|resolution|temperature|integration|dispersion|"
                r"coupling|nonlinearity|sensitivity)\b",
                sent,
                re.I,
            )
            keyword = (keyword_match.group(1).lower() if keyword_match else "technical limitation")
            key = (source_section_name or "", keyword, sent[:80].lower())
            if key in seen:
                continue
            seen.add(key)
            severity = "high" if re.search(r"\b(severe|critical|fundamental|major|limited|requires?)\b", sent, re.I) else "medium"
            atoms.append({
                "paper_id": paper["id"],
                "description": sent[:500],
                "keyword": keyword[:100],
                "severity": severity,
                **common,
            })
            if len(atoms) >= LIMITATION_MAX_ATOMS_PER_PAPER:
                return atoms
    return atoms


def write_atoms(conn_v14: sqlite3.Connection, atoms: List[dict]) -> List[int]:
    """写入 limitation_atoms,返回 atom_ids"""
    ensure_limitation_atom_provenance_schema(conn_v14)
    cols = _columns(conn_v14, "limitation_atoms")
    atom_ids = []
    for atom in atoms:
        row = {
            "paper_id": atom["paper_id"],
            "description": atom["description"],
            "keyword": atom["keyword"],
            "severity": atom["severity"],
            "evidence_source": atom.get("evidence_source", "abstract"),
            "evidence_quality": atom.get("evidence_quality", "weak_abstract"),
            "evidence_weight": float(atom.get("evidence_weight", 0.35)),
            "source_section_name": atom.get("source_section_name"),
            "extractor_method": atom.get("extractor_method"),
            "source_section_atom_id": atom.get("source_section_atom_id"),
            "source_section_atom_type": atom.get("source_section_atom_type"),
            "source_section_atom_evidence_grade": atom.get("source_section_atom_evidence_grade"),
            "source_storage_uri": atom.get("source_storage_uri"),
            "source_page_start": atom.get("source_page_start"),
            "source_page_end": atom.get("source_page_end"),
            "source_parser_contract_version": atom.get("source_parser_contract_version"),
        }
        insert_cols = [col for col in row if col in cols]
        placeholders = ",".join("?" * len(insert_cols))
        cursor = conn_v14.execute(
            f"""
            INSERT OR IGNORE INTO limitation_atoms
                ({",".join(insert_cols)})
            VALUES ({placeholders})
            """,
            tuple(row[col] for col in insert_cols),
        )
        atom_id = cursor.lastrowid
        if atom_id:
            atom_ids.append(atom_id)
    conn_v14.commit()
    return atom_ids


# ---------------------------------------------------------------------------
# Phase 3: Resolution Tracking
# ---------------------------------------------------------------------------

def get_later_citations(
    conn_main: sqlite3.Connection,
    paper_id: int,
    paper_year: int,
    max_resolvers: int = LIMITATION_MAX_RESOLVERS,
    corpus_id: str | None = None,
) -> List[dict]:
    """
    找出发表于 paper_year 之后、引用了 paper_id 的论文。
    """
    rows = conn_main.execute(f"""
        SELECT p.id, p.title, p.abstract, p.publication_year
        FROM papers p
        JOIN paper_references pr ON p.id = pr.citing_paper_id
        WHERE pr.cited_paper_id_internal = ?
          AND p.publication_year > ?
          AND p.abstract IS NOT NULL
          AND LENGTH(p.abstract) > 100
          {"AND p.id IN (SELECT paper_id FROM temp.v14b_corpus_papers)" if corpus_id else ""}
        ORDER BY p.publication_year ASC
        LIMIT ?
    """, (paper_id, paper_year, max_resolvers)).fetchall()
    return [dict(r) for r in rows]


def check_resolution(
    atom: dict,
    resolver_paper: dict,
    older_title: str,
    llm_client,
) -> Optional[dict]:
    """
    判断 resolver_paper 是否可能解决 atom 描述的 limitation。

    默认路径用 keyword/term overlap + resolution verbs 生成可审计候选；
    LLM 只在显式 opt-in 时辅助解释,不能替代 section/citation evidence。
    """
    if llm_client is None:
        text = f"{resolver_paper.get('title', '')} {resolver_paper.get('abstract', '')}"
        keyword = (atom.get("keyword") or "").lower()
        keyword_hit = bool(keyword and keyword != "technical limitation" and keyword in text.lower())
        desc_terms = {
            t.lower()
            for t in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{3,}", atom.get("description", ""))
        }
        resolver_terms = {
            t.lower()
            for t in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{3,}", text[:2500])
        }
        overlap = len(desc_terms & resolver_terms)
        if (keyword_hit or overlap >= 2) and RESOLUTION_TERMS.search(text):
            confidence = 0.65 if keyword_hit else 0.55
            return {
                "atom_id": atom["atom_id"],
                "resolver_paper_id": resolver_paper["id"],
                "resolution_year": resolver_paper.get("publication_year"),
                "confidence": confidence,
                "evidence_text": HEURISTIC_RESOLUTION_EVIDENCE_TEXT,
            }
        return None

    prompt = RESOLUTION_CHECK_PROMPT.format(
        older_title=older_title[:200],
        limitation_description=atom["description"][:300],
        keyword=atom["keyword"][:50],
        newer_title=resolver_paper.get("title", "")[:200],
        newer_abstract=resolver_paper.get("abstract", "")[:1500],
    )

    try:
        result = llm_client.extract_json(prompt, max_tokens=200)
        if result.get("resolves", False):
            return {
                "atom_id": atom["atom_id"],
                "resolver_paper_id": resolver_paper["id"],
                "resolution_year": resolver_paper.get("publication_year"),
                "confidence": float(result.get("confidence", 0.5)),
                "evidence_text": result.get("evidence", "")[:500],
            }
    except Exception as exc:
        logger.debug("Resolution check 失败: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Phase 4: 未解决 limitation 排序
# ---------------------------------------------------------------------------

def rank_unresolved_limitations(
    conn_v14: sqlite3.Connection,
    top_n: int = LIMITATION_TOP_UNRESOLVED,
) -> List[dict]:
    """
    排序未解决 limitations。
    排序依据: severity × 未解决率 × 引用强度
    """
    # 找出没有 high-confidence resolution 的 atoms
    rows = conn_v14.execute("""
        SELECT
            a.atom_id,
            a.paper_id,
            a.description,
            a.keyword,
            a.severity,
            COUNT(r.atom_id) AS n_resolved,
            MAX(COALESCE(r.confidence, 0)) AS max_confidence
        FROM limitation_atoms a
        LEFT JOIN limitation_resolutions r
            ON a.atom_id = r.atom_id
           AND r.confidence >= 0.75
           AND (
                r.evidence_text IS NULL
                OR r.evidence_text != ?
           )
        GROUP BY a.atom_id
        HAVING max_confidence < 0.7 OR max_confidence IS NULL
        ORDER BY
            CASE a.severity WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC,
            n_resolved ASC
        LIMIT ?
    """, (HEURISTIC_RESOLUTION_EVIDENCE_TEXT, top_n)).fetchall()

    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def run_limitation(
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    limit: Optional[int] = None,
    resume: bool = True,
    corpus_id: str | None = None,
) -> dict:
    """执行 Step 5c: Limitation Tracking"""
    step_name = "step5c_limitation"
    ck = Checkpoint(step_name)

    if resume and ck.done():
        data = ck.load()
        if (
            data.get("skipped_resolution")
            and not SKIP_LIMITATION_RESOLUTION
            and int(data.get("total_resolutions") or 0) == 0
        ):
            logger.info(
                "Step5c atoms 已完成,继续补跑 Phase3 resolution tracking"
            )
        elif data.get("section_atom_bridge_version") != SECTION_ATOM_BRIDGE_VERSION:
            logger.info(
                "Step5c checkpoint predates current section_atom_bridge filter; resuming to refresh traceable section atom provenance"
            )
        else:
            logger.info("Step5c 已完成 (%d atoms),跳过", data.get("records_n", 0))
            return data

    conn_main = sqlite3.connect(str(db_main))
    conn_main.row_factory = sqlite3.Row
    ensure_corpus_schema(conn_main)
    scoped_count = create_temp_corpus_table(conn_main, corpus_id)

    conn_v14 = get_v14b_conn(db_v14)
    ensure_limitation_atom_provenance_schema(conn_v14)
    upsert_step_meta(conn_v14, step_name, "running")
    conn_v14.execute(
        """
        DELETE FROM limitation_atoms
        WHERE evidence_source = 'section_atoms'
          AND COALESCE(extractor_method, '') != 'section_atom_bridge'
        """
    )
    conn_v14.commit()
    if not resume:
        conn_v14.execute("DELETE FROM limitation_resolutions")
        conn_v14.execute("DELETE FROM limitation_atoms")
        conn_v14.commit()

    llm_client = LLMClient.from_env() if LIMITATION_USE_LLM else None

    # Phase 1: 选取目标论文
    top_n = limit or LIMITATION_TOP_N
    papers = get_top_papers_for_limitation(conn_main, conn_v14, n=top_n, corpus_id=corpus_id)
    logger.info("Phase 1: 目标论文 %d 篇", len(papers))

    # Phase 2: 原子化 limitation
    total_atoms = 0
    atoms_with_ids = []
    section_atom_bridge_atoms = 0

    processed = 0
    with make_progress(papers, desc="Phase2 原子化") as pbar:
        for paper in pbar:
            processed += 1
            # 检查该论文是否已处理
            existing = conn_v14.execute(
                "SELECT COUNT(*) FROM limitation_atoms WHERE paper_id = ?",
                (paper["id"],)
            ).fetchone()[0]
            bridge_atoms = section_atom_limitation_atoms(paper)
            bridge_source_ids = {
                str(atom.get("source_section_atom_id") or "")
                for atom in bridge_atoms
                if str(atom.get("source_section_atom_id") or "")
            }

            if existing > 0 and resume:
                if bridge_source_ids:
                    placeholders = ",".join("?" * len(bridge_source_ids))
                    conn_v14.execute(
                        f"""
                        DELETE FROM limitation_atoms
                        WHERE paper_id = ?
                          AND extractor_method = 'section_atom_bridge'
                          AND COALESCE(source_section_atom_id, '') NOT IN ({placeholders})
                        """,
                        (paper["id"], *sorted(bridge_source_ids)),
                    )
                else:
                    conn_v14.execute(
                        """
                        DELETE FROM limitation_atoms
                        WHERE paper_id = ?
                          AND extractor_method = 'section_atom_bridge'
                        """,
                        (paper["id"],),
                    )
                conn_v14.commit()
                # 已处理,从 DB 加载
                rows = conn_v14.execute(
                    "SELECT * FROM limitation_atoms WHERE paper_id = ?",
                    (paper["id"],)
                ).fetchall()
                existing_bridge_source_ids = {
                    str((dict(row).get("source_section_atom_id") or ""))
                    for row in rows
                    if str((dict(row).get("source_section_atom_id") or ""))
                }
                for row in rows:
                    atoms_with_ids.append(dict(row))
                total_atoms += len(rows)
                missing_bridge_atoms = [
                    atom for atom in bridge_atoms
                    if str(atom.get("source_section_atom_id") or "") not in existing_bridge_source_ids
                ]
                if missing_bridge_atoms:
                    atom_ids = write_atoms(conn_v14, missing_bridge_atoms)
                    for atom, aid in zip(missing_bridge_atoms, atom_ids):
                        if aid:
                            atom["atom_id"] = aid
                            atoms_with_ids.append(atom)
                    total_atoms += len(atom_ids)
                    section_atom_bridge_atoms += len(atom_ids)
                if processed % 50 == 0:
                    logger.info("Phase2 进度: %d/%d papers, atoms=%d", processed, len(papers), total_atoms)
                continue

            atoms = extract_limitation_atoms(paper, llm_client)
            if atoms:
                atom_ids = write_atoms(conn_v14, atoms)
                for atom, aid in zip(atoms, atom_ids):
                    if aid:
                        atom["atom_id"] = aid
                        atoms_with_ids.append(atom)
                total_atoms += len(atoms)
                section_atom_bridge_atoms += sum(
                    1 for atom in atoms
                    if atom.get("extractor_method") == "section_atom_bridge"
                )
            elif processed % 20 == 0:
                logger.info("Phase2: paper %s 无 atoms", paper["id"])

            if processed % 10 == 0:
                logger.info("Phase2 进度: %d/%d papers, atoms=%d", processed, len(papers), total_atoms)
            pbar.set_postfix(atoms=total_atoms)

    logger.info("Phase 2 完成: %d atoms", total_atoms)

    # Phase 3: Resolution Tracking
    # 构建 paper_id → title 映射
    all_paper_ids = list({a["paper_id"] for a in atoms_with_ids})
    if all_paper_ids:
        placeholders = ",".join("?" * len(all_paper_ids))
        title_rows = conn_main.execute(
            f"SELECT id, title, publication_year FROM papers WHERE id IN ({placeholders})",
            all_paper_ids,
        ).fetchall()
    else:
        title_rows = []
    paper_titles = {row[0]: row[1] for row in title_rows}
    paper_years = {row[0]: row[2] or 2000 for row in title_rows}

    total_resolutions = 0

    if SKIP_LIMITATION_RESOLUTION:
        logger.info(
            "Phase 3 已跳过 (V14B_SKIP_LIMITATION_RESOLUTION=true); "
            "fusion 仍可使用未解决 limitation_atoms"
        )
    elif LIMITATION_MAX_RESOLVERS <= 0:
        logger.info("Phase 3 已跳过 (V14B_LIMITATION_MAX_RESOLVERS=0)")
    else:
        _run_resolution_phase(
            conn_main, conn_v14, atoms_with_ids, paper_titles, paper_years,
            llm_client, resume, corpus_id=corpus_id,
        )
        total_resolutions = conn_v14.execute(
            "SELECT COUNT(*) FROM limitation_resolutions"
        ).fetchone()[0]

    # Phase 4: 排序未解决 limitations
    unresolved = rank_unresolved_limitations(conn_v14, top_n=LIMITATION_TOP_UNRESOLVED)
    logger.info("Phase 4: top %d 未解决 limitations", len(unresolved))

    evidence_quality_rows = conn_v14.execute("""
        SELECT COALESCE(evidence_quality, 'unknown') AS evidence_quality,
               COALESCE(evidence_source, 'unknown') AS evidence_source,
               COUNT(*) AS n,
               AVG(COALESCE(evidence_weight, 0)) AS avg_weight
        FROM limitation_atoms
        GROUP BY evidence_quality, evidence_source
        ORDER BY n DESC
    """).fetchall()
    evidence_quality = [dict(r) for r in evidence_quality_rows]
    has_section_quality = any(
        (r.get("evidence_quality") == "section_level" or r.get("evidence_source") == "structured_sections")
        and int(r.get("n") or 0) > 0
        for r in evidence_quality
    )
    remaining_risk = (
        "Section-level limitation evidence is active; continue expanding coverage "
        "for better branch-level bottleneck confidence."
        if has_section_quality else
        "Limitation evidence is still abstract-dominant. Keep Step5s ingestion "
        "enabled and expand paper_sections/Sci-Bot sections before strong claims."
    )
    meta = {
        "total_atoms": total_atoms,
        "total_resolutions": total_resolutions,
        "unresolved_top": len(unresolved),
        "records_n": total_atoms,
        "corpus_id": corpus_id,
        "scoped_papers": scoped_count if corpus_id else len(papers),
        "skipped_resolution": SKIP_LIMITATION_RESOLUTION,
        "section_atom_bridge_enabled": True,
        "section_atom_bridge_version": SECTION_ATOM_BRIDGE_VERSION,
        "section_atom_bridge_atoms": section_atom_bridge_atoms,
        "evidence_quality": evidence_quality,
        "remaining_risk": remaining_risk,
    }
    upsert_step_meta(
        conn_v14,
        step_name,
        "done",
        records_n=total_atoms,
        notes=json.dumps(meta, ensure_ascii=False),
    )
    ck.mark_done(records_n=total_atoms, meta=meta)
    conn_main.close()
    conn_v14.close()

    stats = {
        "total_atoms": total_atoms,
        "total_resolutions": total_resolutions,
        "unresolved_top": len(unresolved),
        "evidence_quality": evidence_quality,
        "corpus_id": corpus_id,
        "scoped_papers": scoped_count if corpus_id else len(papers),
        "section_atom_bridge_atoms": section_atom_bridge_atoms,
        "records_n": total_atoms,
    }
    logger.info(
        "Step5c 完成: atoms=%d resolutions=%d unresolved_top=%d",
        total_atoms, total_resolutions, len(unresolved),
    )
    return stats


def _run_resolution_phase(
    conn_main: sqlite3.Connection,
    conn_v14: sqlite3.Connection,
    atoms_with_ids: list,
    paper_titles: dict,
    paper_years: dict,
    llm_client,
    resume: bool,
    corpus_id: str | None = None,
) -> None:
    """Phase 3: 逐 atom 检查后续引用是否解决 limitation。"""
    total_resolutions = 0
    with make_progress(atoms_with_ids, desc="Phase3 Resolution") as pbar:
        for atom in pbar:
            atom_id = atom.get("atom_id")
            if not atom_id:
                continue

            # 检查是否已处理
            existing_res = conn_v14.execute(
                "SELECT COUNT(*) FROM limitation_resolutions WHERE atom_id = ?",
                (atom_id,)
            ).fetchone()[0]
            if existing_res > 0 and resume:
                total_resolutions += existing_res
                continue

            # 找后续引用论文
            paper_id = atom["paper_id"]
            paper_year = paper_years.get(paper_id, 2000)
            resolvers = get_later_citations(
                conn_main,
                paper_id,
                paper_year,
                corpus_id=corpus_id,
            )
            older_title = paper_titles.get(paper_id, "Unknown")

            for resolver in resolvers:
                resolution = check_resolution(atom, resolver, older_title, llm_client)
                if resolution:
                    conn_v14.execute("""
                        INSERT OR IGNORE INTO limitation_resolutions
                            (atom_id, resolver_paper_id, resolution_year,
                             confidence, evidence_text)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        resolution["atom_id"],
                        resolution["resolver_paper_id"],
                        resolution["resolution_year"],
                        resolution["confidence"],
                        resolution["evidence_text"],
                    ))
                    conn_v14.commit()  # 立即 commit
                    total_resolutions += 1

            pbar.set_postfix(resolutions=total_resolutions)

    logger.info("Phase 3 完成: %d resolutions", total_resolutions)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m echelon.v14b.step5c_limitation",
        description="Step 5c: Limitation Tracking",
    )
    add_common_args(parser)
    args = parser.parse_args(argv)

    log_level = getattr(logging, args.log_level)
    setup_logging("step5c_limitation", level=log_level)

    db_main = Path(args.db) if args.db else DB_MAIN
    db_v14 = Path(args.db_v14) if args.db_v14 else DB_V14
    limit = args.limit or LIMIT

    run_limitation(
        db_main=db_main,
        db_v14=db_v14,
        limit=limit,
        resume=args.resume,
        corpus_id=args.corpus_id,
    )


if __name__ == "__main__":
    main()
