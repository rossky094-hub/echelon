"""
V13: CD index (Funk & Owen-Smith 2017) + Macher 2023 baseline correction.

CD ∈ [-1, 1] where:
  +1 = fully disruptive (citing papers abandon focal's references)
  -1 = fully consolidating (citing papers also cite focal's references)

Formula:
  CD = (n_i - n_j) / (n_i + n_j + n_k)
  n_i = papers citing focal but NOT citing focal's references (disruptive)
  n_j = papers citing focal AND citing focal's references (consolidating)
  n_k = papers NOT citing focal but citing focal's references (background)

Macher 2023 correction: subtract same-year same-subfield mean CD as baseline.

Availability constraint:
  - Only for publication_year <= now-3 (needs ≥3 years of citations to accumulate)
  - Newer papers → return None

Pilot simplification:
  - Operates on closed-world corpus (e.g. 2000 papers in DB)
  - Acknowledges incompleteness vs full OpenAlex universe
"""
from __future__ import annotations

import math
from datetime import date
from typing import Dict, FrozenSet, List, Optional, Set


def compute_cd_index(
    focal_paper_id: str,
    focal_refs: Set[str],
    citing_papers: List[Dict],
    publication_year: Optional[int] = None,
    today: Optional[date] = None,
) -> Optional[float]:
    """
    Compute CD index for a focal paper.

    Args:
        focal_paper_id:  Identifier of the focal paper.
        focal_refs:      Set of paper IDs that the focal paper cites.
        citing_papers:   List of dicts, each with:
                           - "id": str
                           - "refs": set/list of paper IDs cited by that paper
        publication_year: Year focal paper was published (for 3-year guard).
        today:           Reference date (default: date.today()).

    Returns:
        CD index ∈ [-1.0, 1.0], or None if paper is too recent (< 3 years old).

    Examples:
        >>> focal_refs = {"R1", "R2"}
        >>> citing = [
        ...     {"id": "C1", "refs": {"F"}},           # cites focal, not refs -> n_i
        ...     {"id": "C2", "refs": {"F", "R1"}},     # cites focal + refs -> n_j
        ...     {"id": "C3", "refs": {"R1", "R2"}},    # not focal, cites refs -> n_k
        ... ]
        >>> cd = compute_cd_index("F", focal_refs, citing, publication_year=2015)
        >>> round(cd, 4)
        0.0
    """
    if today is None:
        today = date.today()

    # 3-year guard
    if publication_year is not None:
        age_years = today.year - publication_year
        if age_years < 3:
            return None

    focal_refs_frozen: FrozenSet[str] = frozenset(focal_refs)

    n_i = 0  # citing focal but NOT focal_refs
    n_j = 0  # citing focal AND focal_refs
    n_k = 0  # NOT citing focal but citing focal_refs

    for paper in citing_papers:
        pid = paper.get("id", "")
        if pid == focal_paper_id:
            continue

        paper_refs: Set[str] = set(paper.get("refs", []))

        cites_focal = focal_paper_id in paper_refs
        cites_focal_refs = bool(paper_refs & focal_refs_frozen)

        if cites_focal and not cites_focal_refs:
            n_i += 1
        elif cites_focal and cites_focal_refs:
            n_j += 1
        elif not cites_focal and cites_focal_refs:
            n_k += 1
        # else: cites neither → excluded from denominator

    denominator = n_i + n_j + n_k
    if denominator == 0:
        return None  # no signal at all

    return (n_i - n_j) / denominator


def compute_cd_index_macher_corrected(
    focal_paper_id: str,
    focal_refs: Set[str],
    citing_papers: List[Dict],
    subfield_papers: List[Dict],
    publication_year: Optional[int] = None,
    today: Optional[date] = None,
) -> Optional[float]:
    """
    Macher 2023 correction: subtract same-year same-subfield mean CD.

    Args:
        focal_paper_id:   ID of the focal paper.
        focal_refs:       Set of references of the focal paper.
        citing_papers:    List of papers that cite the focal paper.
        subfield_papers:  List of papers from same year + subfield, each with:
                            - "id", "refs", "citing_papers" (list of citing dicts),
                            - "publication_year"
        publication_year: Publication year of focal paper.
        today:            Reference date.

    Returns:
        Macher-corrected CD ∈ [-2, 2], or None if too recent / no signal.
    """
    raw_cd = compute_cd_index(
        focal_paper_id,
        focal_refs,
        citing_papers,
        publication_year=publication_year,
        today=today,
    )
    if raw_cd is None:
        return None

    # Compute mean CD of subfield peers
    peer_cds = []
    for sp in subfield_papers:
        sp_id = sp.get("id", "")
        if sp_id == focal_paper_id:
            continue
        sp_refs = set(sp.get("refs", []))
        sp_citing = sp.get("citing_papers", [])
        sp_year = sp.get("publication_year", publication_year)
        cd_peer = compute_cd_index(
            sp_id, sp_refs, sp_citing, publication_year=sp_year, today=today
        )
        if cd_peer is not None:
            peer_cds.append(cd_peer)

    if not peer_cds:
        return raw_cd  # no correction possible

    baseline = sum(peer_cds) / len(peer_cds)
    return raw_cd - baseline


def compute_cd_subdomain_percentile(
    focal_paper_id: str,
    focal_refs: Set[str],
    focal_citing: List[Dict],
    subfield_papers: List[Dict],
    publication_year: Optional[int] = None,
    today: Optional[date] = None,
) -> Optional[float]:
    """
    Convert CD index into subfield percentile ∈ [0, 1].

    High value (close to 1.0) = more disruptive than peers.
    Low value (close to 0.0) = more consolidating than peers.

    Args:
        focal_paper_id:   ID of focal paper.
        focal_refs:       References of focal paper.
        focal_citing:     Papers citing focal paper.
        subfield_papers:  Peers in same subfield/year with same structure.
        publication_year: Publication year.
        today:            Reference date.

    Returns:
        Percentile ∈ [0.0, 1.0], or None if paper is too recent.

    Examples:
        >>> # If focal CD is highest among 3 peers, percentile = 1.0
        >>> # If focal CD is lowest, percentile = 0.0
    """
    if today is None:
        today = date.today()

    focal_cd = compute_cd_index(
        focal_paper_id,
        focal_refs,
        focal_citing,
        publication_year=publication_year,
        today=today,
    )
    if focal_cd is None:
        return None

    peer_cds = []
    for sp in subfield_papers:
        sp_id = sp.get("id", "")
        if sp_id == focal_paper_id:
            continue
        sp_refs = set(sp.get("refs", []))
        sp_citing = sp.get("citing_papers", [])
        sp_year = sp.get("publication_year", publication_year)
        cd_p = compute_cd_index(
            sp_id, sp_refs, sp_citing, publication_year=sp_year, today=today
        )
        if cd_p is not None:
            peer_cds.append(cd_p)

    if not peer_cds:
        # No peers: map raw CD from [-1,1] to [0,1]
        return (focal_cd + 1.0) / 2.0

    # Percentile rank
    rank = sum(1 for cd in peer_cds if cd <= focal_cd)
    return rank / len(peer_cds)
