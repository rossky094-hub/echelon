"""Provider ID normalization helpers for V14B graph construction."""
from __future__ import annotations

import re
from typing import Optional


_DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi:",
    "DOI:",
)


def normalize_doi(value: Optional[str]) -> Optional[str]:
    """Return a lowercase DOI without URI/prefix wrappers."""
    if not value:
        return None
    doi = str(value).strip()
    if not doi:
        return None
    for prefix in _DOI_PREFIXES:
        if doi.lower().startswith(prefix.lower()):
            doi = doi[len(prefix):].strip()
            break
    if doi.upper().startswith("DOI:"):
        doi = doi[4:].strip()
    return doi.lower() or None


def normalize_arxiv_id(value: Optional[str]) -> Optional[str]:
    """Normalize arXiv IDs and strip common wrappers/version suffixes."""
    if not value:
        return None
    aid = str(value).strip()
    for prefix in (
        "arxiv:",
        "ARXIV:",
        "https://arxiv.org/abs/",
        "http://arxiv.org/abs/",
        "https://arxiv.org/pdf/",
        "http://arxiv.org/pdf/",
    ):
        if aid.lower().startswith(prefix.lower()):
            aid = aid[len(prefix):].strip()
            break
    if aid.endswith(".pdf"):
        aid = aid[:-4]
    aid = re.sub(r"v\d+$", "", aid, flags=re.I)
    return aid or None


def normalize_openalex_work_id(value: Optional[str]) -> Optional[str]:
    """Normalize an OpenAlex Work ID, returning W... only."""
    if not value:
        return None
    oid = str(value).strip().split("/")[-1]
    return oid if re.match(r"^W\d+$", oid) else None


def normalize_s2_paper_id(value: Optional[str]) -> Optional[str]:
    """Normalize a Semantic Scholar paper ID, with optional S2: prefix."""
    if not value:
        return None
    sid = str(value).strip()
    if sid.upper().startswith("S2:"):
        sid = sid[3:].strip()
    if sid.upper().startswith("SEMANTIC_SCHOLAR:"):
        sid = sid.split(":", 1)[1].strip()
    return sid or None


def classify_external_id(value: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """
    Classify a reference ID as (provider, normalized_id).

    Provider is one of: openalex, doi, arxiv, s2, other.
    """
    if not value:
        return None, None
    raw = str(value).strip()
    if not raw:
        return None, None

    openalex_id = normalize_openalex_work_id(raw)
    if openalex_id:
        return "openalex", openalex_id

    upper = raw.upper()
    if upper.startswith("DOI:") or raw.lower().startswith(_DOI_PREFIXES[:4]):
        doi = normalize_doi(raw)
        return ("doi", doi) if doi else ("other", raw)
    if re.match(r"^10\.\S+/\S+", raw, flags=re.I):
        doi = normalize_doi(raw)
        return ("doi", doi) if doi else ("other", raw)

    if upper.startswith("ARXIV:") or "arxiv.org/abs/" in raw.lower():
        aid = normalize_arxiv_id(raw)
        return ("arxiv", aid) if aid else ("other", raw)
    if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", raw, flags=re.I):
        return "arxiv", normalize_arxiv_id(raw)
    if re.match(r"^[a-z-]+/\d{7}(v\d+)?$", raw, flags=re.I):
        return "arxiv", normalize_arxiv_id(raw)

    if upper.startswith("S2:") or re.match(r"^[0-9a-f]{32,40}$", raw, flags=re.I):
        sid = normalize_s2_paper_id(raw)
        return ("s2", sid) if sid else ("other", raw)

    return "other", raw
