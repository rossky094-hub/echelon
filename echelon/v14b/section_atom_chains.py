"""Typed chain assembly over section evidence atoms.

This step consumes materialized `section_atoms` and groups co-located atoms into
auditable bottleneck-chain candidates:

    constraint -> failure_mechanism -> attempted_path -> local_fix -> new_constraint

The chain rows are evidence objects, not conclusions.  Step13 can later consume
them to reduce placeholder lineage, but promotion still requires Claim Card and
value-delivery gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echelon.v14b.config import DB_MAIN
from echelon.v14b.utils import add_common_args, setup_logging


CHAIN_STAGES = (
    "constraint",
    "failure_mechanism",
    "attempted_path",
    "local_fix",
    "new_constraint",
)

CHAIN_RELATIONS = (
    ("constraint", "failure_mechanism", "constraint_causes_failure"),
    ("failure_mechanism", "attempted_path", "failure_triggers_attempt"),
    ("attempted_path", "local_fix", "attempt_produces_local_fix"),
    ("local_fix", "new_constraint", "local_fix_reveals_new_constraint"),
)

CHAIN_ATOM_TYPES = set(CHAIN_STAGES)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def jdumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def ensure_section_atom_chains_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS section_atom_chains (
            chain_id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL,
            section_name TEXT NOT NULL,
            section_key TEXT NOT NULL,
            chain_index INTEGER NOT NULL,
            constraint_atom_id TEXT,
            failure_mechanism_atom_id TEXT,
            attempted_path_atom_id TEXT,
            local_fix_atom_id TEXT,
            new_constraint_atom_id TEXT,
            constraint_text TEXT,
            failure_mechanism_text TEXT,
            attempted_path_text TEXT,
            local_fix_text TEXT,
            new_constraint_text TEXT,
            relation_edges_json TEXT NOT NULL,
            typed_chain_complete INTEGER NOT NULL,
            typed_chain_completeness TEXT NOT NULL,
            missing_stages_json TEXT NOT NULL,
            evidence_grade TEXT NOT NULL,
            claim_scope TEXT NOT NULL,
            uncertainty_reasons_json TEXT NOT NULL,
            evidence_objects_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_section_atom_chains_paper ON section_atom_chains(paper_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_section_atom_chains_section ON section_atom_chains(section_key)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_section_atom_chains_completeness "
        "ON section_atom_chains(typed_chain_completeness)"
    )
    conn.commit()


def assemble_chains_for_section(
    atoms: list[dict[str, Any]],
    *,
    max_chains_per_section: int = 3,
) -> list[dict[str, Any]]:
    stage_atoms: dict[str, list[dict[str, Any]]] = defaultdict(list)
    chain_atoms = []
    for atom in sorted(atoms, key=lambda row: int(row.get("atom_index") or 0)):
        stage = str(atom.get("atom_type") or "")
        if stage in CHAIN_ATOM_TYPES:
            stage_atoms[stage].append(atom)
            chain_atoms.append(atom)
    if len({str(a.get("atom_type") or "") for a in chain_atoms}) < 2:
        return []

    starts = (stage_atoms.get("constraint") or []) + (stage_atoms.get("failure_mechanism") or [])
    if not starts:
        return []
    starts = sorted(starts, key=lambda row: int(row.get("atom_index") or 0))[:max_chains_per_section]

    chains: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for chain_index, start in enumerate(starts):
        selected = _select_stage_atoms(stage_atoms, start)
        if len(selected) < 2:
            continue
        key = tuple(str((selected.get(stage) or {}).get("atom_id") or "") for stage in CHAIN_STAGES)
        if key in seen:
            continue
        seen.add(key)
        chains.append(_chain_row(selected, chain_index=chain_index))
    return chains


def _select_stage_atoms(
    stage_atoms: dict[str, list[dict[str, Any]]],
    start: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    start_stage = str(start.get("atom_type") or "")
    if start_stage not in CHAIN_ATOM_TYPES:
        return selected

    start_index = int(start.get("atom_index") or 0)
    if start_stage == "failure_mechanism":
        prior_constraints = [
            atom for atom in stage_atoms.get("constraint", [])
            if int(atom.get("atom_index") or 0) <= start_index
        ]
        if prior_constraints:
            selected["constraint"] = prior_constraints[-1]
    selected[start_stage] = start

    cursor = int((selected.get(start_stage) or start).get("atom_index") or 0)
    for stage in CHAIN_STAGES:
        if stage in selected:
            cursor = int(selected[stage].get("atom_index") or cursor)
            continue
        candidate = _first_at_or_after(stage_atoms.get(stage, []), cursor)
        if candidate:
            selected[stage] = candidate
            cursor = int(candidate.get("atom_index") or cursor)

    if "constraint" not in selected and stage_atoms.get("constraint"):
        selected["constraint"] = stage_atoms["constraint"][0]
    return selected


def _first_at_or_after(atoms: list[dict[str, Any]], atom_index: int) -> dict[str, Any] | None:
    for atom in atoms:
        if int(atom.get("atom_index") or 0) >= atom_index:
            return atom
    return None


def _chain_row(selected: dict[str, dict[str, Any]], *, chain_index: int) -> dict[str, Any]:
    paper_id = str(next(iter(selected.values())).get("paper_id") or "")
    section_name = str(next(iter(selected.values())).get("section_name") or "")
    section_key = str(next(iter(selected.values())).get("section_key") or "")
    atom_ids = [str((selected.get(stage) or {}).get("atom_id") or "") for stage in CHAIN_STAGES]
    chain_id = _chain_id(paper_id, section_key, atom_ids)
    missing = [stage for stage in CHAIN_STAGES if stage not in selected]
    complete = not missing
    relation_edges = _relation_edges(selected)
    grade = _evidence_grade(selected, complete=complete)
    claim_scope = "bottleneck_lineage_evidence" if complete and not grade.startswith("weak") else "exploratory_bottleneck_lineage"
    uncertainty_reasons = _uncertainty_reasons(selected, missing)
    evidence_objects = _evidence_objects(selected)
    out: dict[str, Any] = {
        "chain_id": chain_id,
        "paper_id": paper_id,
        "section_name": section_name,
        "section_key": section_key,
        "chain_index": chain_index,
        "relation_edges_json": jdumps(relation_edges),
        "typed_chain_complete": 1 if complete else 0,
        "typed_chain_completeness": _typed_chain_completeness(set(selected), complete=complete),
        "missing_stages_json": jdumps(missing),
        "evidence_grade": grade,
        "claim_scope": claim_scope,
        "uncertainty_reasons_json": jdumps(uncertainty_reasons),
        "evidence_objects_json": jdumps(evidence_objects),
        "created_at": utc_now(),
    }
    for stage in CHAIN_STAGES:
        atom = selected.get(stage) or {}
        out[f"{stage}_atom_id"] = atom.get("atom_id")
        out[f"{stage}_text"] = atom.get("atom_text")
    return out


def _relation_edges(selected: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    edges = []
    for source_stage, target_stage, relation in CHAIN_RELATIONS:
        source = selected.get(source_stage)
        target = selected.get(target_stage)
        edges.append(
            {
                "source_stage": source_stage,
                "target_stage": target_stage,
                "relation_type": relation,
                "source_atom_id": source.get("atom_id") if source else None,
                "target_atom_id": target.get("atom_id") if target else None,
                "source_stage_is_placeholder": source is None,
                "target_stage_is_placeholder": target is None,
            }
        )
    return edges


def _evidence_grade(selected: dict[str, dict[str, Any]], *, complete: bool) -> str:
    grades = {str(atom.get("evidence_grade") or "") for atom in selected.values()}
    traced = grades <= {"section_atom_decision_grade", "section_atom_traced"}
    decision = grades == {"section_atom_decision_grade"}
    if complete and decision:
        return "typed_section_lineage"
    if complete and traced:
        return "typed_section_lineage_traced"
    if complete:
        return "weak_typed_section_lineage"
    if traced:
        return "partial_typed_section_lineage"
    return "weak_partial_typed_section_lineage"


def _typed_chain_completeness(present: set[str], *, complete: bool) -> str:
    if complete:
        return "full"
    if {"constraint", "failure_mechanism", "attempted_path", "local_fix"} <= present:
        return "local_fix_partial"
    if {"constraint", "failure_mechanism", "attempted_path"} <= present:
        return "attempted_path_partial"
    if {"constraint", "failure_mechanism"} <= present:
        return "constraint_failure_only"
    return "sparse_stage_partial"


def _uncertainty_reasons(selected: dict[str, dict[str, Any]], missing: list[str]) -> list[str]:
    reasons = ["typed chain assembled deterministically from co-located section atoms"]
    if missing:
        reasons.append("typed lineage is partial; missing stages: " + ", ".join(missing))
    if any(str(atom.get("evidence_grade") or "").endswith("_weak") for atom in selected.values()):
        reasons.append("one or more atoms have weak section provenance")
    if any(str(atom.get("parser_contract_version") or "") == "legacy_unknown_contract" for atom in selected.values()):
        reasons.append("one or more atoms come from legacy or unknown parser contract")
    reasons.append("chain is evidence context only until Step13 Claim Card promotion")
    return reasons


def _evidence_objects(selected: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    objects = []
    for stage in CHAIN_STAGES:
        atom = selected.get(stage)
        if not atom:
            continue
        objects.append(
            {
                "type": "section_atom",
                "role": stage,
                "atom_id": atom.get("atom_id"),
                "paper_id": atom.get("paper_id"),
                "section_name": atom.get("section_name"),
                "page_start": atom.get("page_start"),
                "page_end": atom.get("page_end"),
                "evidence_grade": atom.get("evidence_grade"),
                "claim_scope": atom.get("claim_scope"),
                "source_url": atom.get("source_url"),
                "source_storage_uri": atom.get("source_storage_uri"),
                "click_target": {"kind": "paper", "id": atom.get("paper_id")},
            }
        )
    return objects


def _chain_id(paper_id: str, section_key: str, atom_ids: list[str]) -> str:
    digest = hashlib.sha1("|".join([paper_id, section_key, *atom_ids]).encode("utf-8")).hexdigest()[:20]
    return f"sac_{digest}"


def _insert_chains(conn: sqlite3.Connection, chains: list[dict[str, Any]]) -> int:
    if not chains:
        return 0
    conn.executemany(
        """
        INSERT OR REPLACE INTO section_atom_chains (
            chain_id, paper_id, section_name, section_key, chain_index,
            constraint_atom_id, failure_mechanism_atom_id, attempted_path_atom_id,
            local_fix_atom_id, new_constraint_atom_id,
            constraint_text, failure_mechanism_text, attempted_path_text,
            local_fix_text, new_constraint_text,
            relation_edges_json, typed_chain_complete, typed_chain_completeness,
            missing_stages_json, evidence_grade, claim_scope,
            uncertainty_reasons_json, evidence_objects_json, created_at
        )
        VALUES (
            :chain_id, :paper_id, :section_name, :section_key, :chain_index,
            :constraint_atom_id, :failure_mechanism_atom_id, :attempted_path_atom_id,
            :local_fix_atom_id, :new_constraint_atom_id,
            :constraint_text, :failure_mechanism_text, :attempted_path_text,
            :local_fix_text, :new_constraint_text,
            :relation_edges_json, :typed_chain_complete, :typed_chain_completeness,
            :missing_stages_json, :evidence_grade, :claim_scope,
            :uncertainty_reasons_json, :evidence_objects_json, :created_at
        )
        """,
        chains,
    )
    return len(chains)


def build_section_atom_chains(
    db_main: Path = DB_MAIN,
    *,
    limit: int | None = None,
    rebuild: bool = True,
    max_chains_per_section: int = 3,
) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_main), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    ensure_section_atom_chains_schema(conn)
    if not table_exists(conn, "section_atoms"):
        conn.close()
        return {"status": "section_atoms_missing", "sections_processed": 0, "chains_written": 0}
    if rebuild:
        conn.execute("DELETE FROM section_atom_chains")
        conn.commit()

    rows = conn.execute(
        """
        SELECT *
        FROM section_atoms
        WHERE atom_type IN ('constraint', 'failure_mechanism', 'attempted_path', 'local_fix', 'new_constraint')
        ORDER BY paper_id, section_key, atom_index
        """
    ).fetchall()
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["paper_id"]), str(row["section_key"]))].append(dict(row))
    groups = list(grouped.values())
    if limit is not None:
        groups = groups[: int(limit)]

    total = 0
    by_grade: dict[str, int] = {}
    by_completeness: dict[str, int] = {}
    pending: list[dict[str, Any]] = []
    for atoms in groups:
        chains = assemble_chains_for_section(atoms, max_chains_per_section=max_chains_per_section)
        for chain in chains:
            by_grade[chain["evidence_grade"]] = by_grade.get(chain["evidence_grade"], 0) + 1
            by_completeness[chain["typed_chain_completeness"]] = (
                by_completeness.get(chain["typed_chain_completeness"], 0) + 1
            )
        pending.extend(chains)
        if len(pending) >= 500:
            total += _insert_chains(conn, pending)
            conn.commit()
            pending = []
    if pending:
        total += _insert_chains(conn, pending)
    conn.commit()
    conn.close()
    return {
        "sections_processed": len(groups),
        "chains_written": total,
        "by_evidence_grade": by_grade,
        "by_completeness": by_completeness,
    }


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'virtual table') AND name = ?",
        (table,),
    ).fetchone() is not None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build typed chains from section evidence atoms.")
    add_common_args(parser)
    parser.add_argument("--max-chains-per-section", type=int, default=3)
    parser.add_argument("--no-rebuild", action="store_true")
    args = parser.parse_args(argv)
    setup_logging("section_atom_chains", level=getattr(logging, args.log_level))
    db_main = Path(args.db) if args.db else DB_MAIN
    stats = build_section_atom_chains(
        db_main,
        limit=args.limit,
        rebuild=not args.no_rebuild,
        max_chains_per_section=args.max_chains_per_section,
    )
    print(jdumps(stats))


if __name__ == "__main__":
    main()
