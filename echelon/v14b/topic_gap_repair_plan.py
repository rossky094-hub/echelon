"""Build an execution plan from topic-gap repair contract closure states.

The topic-gap section audit tells us which evidence contracts are closed,
partial, or still open.  This report turns that into a conservative worklist:
reuse local raw PDFs first, materialize deterministic section atoms, use exact
and fuzzy retrieval as context, then let Step5c/Step13 promotion gates decide.
Graph/GNN algorithms remain candidate expansion only; they never atomize
sections or promote a claim.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echelon.v14b.config import REPORT_DIR
from echelon.v14b.utils import add_common_args


GROUP_ORDER = (
    "rebuild_section_atom_chains_quick_close",
    "rebuild_section_atoms_from_existing_sections",
    "targeted_local_raw_pdf_ingest_when_safe",
    "inspect_typed_chain_stage_gaps",
    "inspect_current_parser_no_target",
    "recover_access_links_before_ingest",
    "closed_waiting_step13_gate",
    "hold_as_candidate_context",
)

FORBIDDEN_SHORTCUTS = (
    "do not use GNN/VGAE to create section atoms",
    "do not loosen parser thresholds for current-parser no-target rows without inspection",
    "do not treat fuzzy vector recall as a conclusion",
    "do not mark Radar or high-confidence Claim Cards without Step13 gates",
)

ACTION_GROUPS: dict[str, dict[str, Any]] = {
    "rebuild_section_atom_chains_quick_close": {
        "label": "Atoms exist; rebuild typed chains",
        "rationale": "The section atom substrate is already present, so the fastest closure path is deterministic chain assembly.",
        "command_sequence": [
            "make section-atom-chains",
            "make topic-gap-section-audit",
            "make topic-gap-repair-plan",
        ],
        "can_run_while_broad_ingest_active": False,
    },
    "rebuild_section_atoms_from_existing_sections": {
        "label": "Decision-grade sections exist; build atom/search substrate",
        "rationale": "Current-contract sections are available, but atoms or fuzzy recall embeddings are missing.",
        "command_sequence": [
            "make section-atoms",
            "make section-atom-embeddings",
            "make section-embeddings",
            "make section-atom-chains",
            "make topic-gap-section-audit",
            "make topic-gap-repair-plan",
        ],
        "can_run_while_broad_ingest_active": False,
    },
    "targeted_local_raw_pdf_ingest_when_safe": {
        "label": "Use external raw PDF cache for targeted section ingest",
        "rationale": "The repair contract still lacks decision-grade section evidence; local raw PDFs should be consumed before network fetches.",
        "command_sequence": [
            "python scripts/guard_topic_gap_repair.py",
            "make section-evidence-topic-gaps-local",
            "make section-atoms",
            "make section-atom-embeddings",
            "make section-embeddings",
            "make section-atom-chains",
            "make topic-gap-section-audit",
            "make topic-gap-repair-plan",
        ],
        "can_run_while_broad_ingest_active": False,
    },
    "inspect_typed_chain_stage_gaps": {
        "label": "Typed chains are partial; inspect missing stages",
        "rationale": "Evidence exists, but the bottleneck lineage is incomplete or topic-mismatched.",
        "command_sequence": [
            "make topic-gap-stage-candidate-recall",
            "inspect missing chain stages in reports/v14b_pilot/topic_gap_section_evidence_audit.csv",
            "make section-atoms",
            "make section-embeddings",
            "make section-atom-chains",
            "make topic-gap-section-audit",
            "make topic-gap-repair-plan",
        ],
        "can_run_while_broad_ingest_active": False,
    },
    "inspect_current_parser_no_target": {
        "label": "Current parser found no target section; inspect before tuning",
        "rationale": "A current-contract no-target result is a parser/full-text inspection task, not a reason to loosen evidence thresholds.",
        "command_sequence": [
            "make topic-gap-no-target-inspect",
            "make topic-gap-repair-plan",
        ],
        "can_run_while_broad_ingest_active": True,
    },
    "recover_access_links_before_ingest": {
        "label": "Recover access links or raw PDFs before section ingest",
        "rationale": "No reusable section path is available until DOI/OpenAlex/S2/arXiv access or raw PDF storage is repaired.",
        "command_sequence": [
            "make access-audit",
            "make raw-pdf-store-audit",
            "recover DOI/OpenAlex/S2/arXiv or open-access PDF metadata",
            "make topic-gap-section-audit",
            "make topic-gap-repair-plan",
        ],
        "can_run_while_broad_ingest_active": True,
    },
    "closed_waiting_step13_gate": {
        "label": "Evidence substrate closed; wait for Step13 gates",
        "rationale": "Required section/atom/chain substrate exists, but no direct promotion is allowed.",
        "command_sequence": [
            "make post-frontfill-chain",
            "make direction-readiness-audit",
            "make value-delivery-audit",
        ],
        "can_run_while_broad_ingest_active": False,
    },
    "hold_as_candidate_context": {
        "label": "Hold as candidate context",
        "rationale": "The closure state is not executable yet; keep it in the repair queue with explicit uncertainty.",
        "command_sequence": [
            "make topic-gap-section-audit",
            "make topic-gap-repair-plan",
        ],
        "can_run_while_broad_ingest_active": True,
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _loads(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"missing topic-gap triage JSON: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"topic-gap triage JSON must be an object: {path}")
    return data


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def execution_contract() -> dict[str, Any]:
    return {
        "claim_scope": "evidence_repair_queue_only",
        "promotion_policy": "no_direct_promotion",
        "pipeline": [
            "raw_pdf_local_store",
            "section_ingest_local_first",
            "section_atoms",
            "exact_fts_bm25",
            "atom_embeddings_fuzzy_recall",
            "section_embeddings_fuzzy_context",
            "typed_stage_candidate_recall",
            "section_atom_chains",
            "Step5c_Step13_evidence_gates",
        ],
        "section_atomization_layer": {
            "allowed_methods": [
                "deterministic parser",
                "rules or lightweight classifier",
                "small bounded LLM review only for audit/recheck",
            ],
            "forbidden_methods": ["GNN/VGAE atom generation"],
            "required_trace_fields": [
                "paper_id",
                "section_name",
                "page_start",
                "page_end",
                "span_start",
                "span_end",
                "source_storage_uri",
                "parser_contract_version",
            ],
        },
        "dual_retrieval_layer": {
            "exact": "IDs, DOI, arXiv, title, section name, phrase query, and FTS/BM25 are hard retrieval evidence.",
            "fuzzy": "atom embeddings and section embeddings are fuzzy candidate recall only.",
            "typed_stage_candidate_recall": (
                "missing stage recall may suggest same-paper atoms and cross-paper templates, "
                "but it cannot close repair contracts or promote conclusions."
            ),
        },
        "graph_algorithm_layer": {
            "allowed_outputs": ["candidate expansion", "candidate ranking", "neighborhood discovery"],
            "forbidden_outputs": ["section atom generation", "direct Step13 conclusion", "Radar promotion"],
            "claim_scope": "retrieval_context_only",
        },
        "forbidden_shortcuts": list(FORBIDDEN_SHORTCUTS),
    }


def _closure_items(triage: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in triage.get("rows") or []:
        if not isinstance(row, dict):
            continue
        closures = row.get("repair_contract_closures") or []
        if not isinstance(closures, list):
            continue
        for closure in closures:
            if not isinstance(closure, dict):
                continue
            item = dict(closure)
            item.update(
                {
                    "paper_id": closure.get("paper_id") or row.get("paper_id") or "",
                    "title": row.get("title") or "",
                    "priority_score": _as_float(row.get("priority_score")),
                    "topics": _as_list(row.get("topics")),
                    "gap_types": _as_list(row.get("gap_types")),
                    "row_failure_mode": row.get("failure_mode") or closure.get("failure_mode") or "",
                    "row_next_action": row.get("next_action") or closure.get("next_action") or "",
                    "eligible_pdf": bool(row.get("eligible_pdf")),
                    "source_url": row.get("source_url") or "",
                    "latest_attempt_outcome": row.get("latest_attempt_outcome") or "",
                    "latest_attempt_contract": row.get("latest_attempt_contract") or "",
                    "decision_grade_primary_rows": _as_int(row.get("decision_grade_primary_rows")),
                    "section_atoms": _as_int(row.get("section_atoms")),
                    "section_atom_decision_grade_atoms": _as_int(
                        row.get("section_atom_decision_grade_atoms")
                    ),
                    "section_atom_chains": _as_int(row.get("section_atom_chains")),
                    "section_atom_full_chains": _as_int(row.get("section_atom_full_chains")),
                    "section_atom_chain_missing_stages": row.get("section_atom_chain_missing_stages") or {},
                    "section_atom_chain_missing_stage_examples": row.get(
                        "section_atom_chain_missing_stage_examples"
                    ) or [],
                }
            )
            items.append(item)
    return items


def _group_for(item: dict[str, Any]) -> str:
    state = str(item.get("closure_state") or "")
    failure = str(item.get("row_failure_mode") or item.get("failure_mode") or "")
    decision_sections = _as_int(item.get("decision_grade_primary_rows"))

    if state == "partial_atoms_available_no_chain":
        return "rebuild_section_atom_chains_quick_close"
    if state == "open_atoms_missing" and decision_sections > 0:
        return "rebuild_section_atoms_from_existing_sections"
    if state in {"closed_decision_grade_section", "closed_section_atoms_available", "closed_typed_chain_available"}:
        return "closed_waiting_step13_gate"
    if state in {"partial_chain_incomplete", "open_topic_chain_mismatch"}:
        return "inspect_typed_chain_stage_gaps"
    if state in {"partial_atoms_weak_or_stale"}:
        return "targeted_local_raw_pdf_ingest_when_safe"
    if state == "open_section_evidence_not_decision_grade":
        if failure == "no_target_sections_after_current_parser":
            return "inspect_current_parser_no_target"
        if failure in {"needs_access_link", "not_attempted_no_pdf", "no_local_raw_pdf"}:
            return "recover_access_links_before_ingest"
        return "targeted_local_raw_pdf_ingest_when_safe"
    if state == "open_atoms_missing":
        return "targeted_local_raw_pdf_ingest_when_safe"
    return "hold_as_candidate_context"


def _item_sort_key(item: dict[str, Any]) -> tuple[int, float, str]:
    group_id = str(item.get("action_group") or "hold_as_candidate_context")
    try:
        group_rank = GROUP_ORDER.index(group_id)
    except ValueError:
        group_rank = len(GROUP_ORDER)
    return (group_rank, -_as_float(item.get("priority_score")), str(item.get("paper_id") or ""))


def _slim_item(item: dict[str, Any]) -> dict[str, Any]:
    state = str(item.get("closure_state") or "")
    if state in {"partial_chain_incomplete", "open_topic_chain_mismatch"}:
        missing_stages = item.get("missing_stages") or item.get("section_atom_chain_missing_stages") or {}
        missing_stage_examples = (
            item.get("missing_stage_examples")
            or item.get("section_atom_chain_missing_stage_examples")
            or []
        )
    else:
        missing_stages = {}
        missing_stage_examples = []
    return {
        "paper_id": item.get("paper_id") or "",
        "title": item.get("title") or "",
        "priority_score": _as_float(item.get("priority_score")),
        "topic": item.get("topic") or (item.get("topics") or [""])[0],
        "gap_type": item.get("gap_type") or (item.get("gap_types") or [""])[0],
        "repair_id": item.get("repair_id") or "",
        "source_contract": item.get("source_contract") or "",
        "closure_state": state,
        "failure_mode": item.get("row_failure_mode") or item.get("failure_mode") or "",
        "next_action": item.get("next_action") or item.get("row_next_action") or "",
        "decision_grade_primary_rows": _as_int(item.get("decision_grade_primary_rows")),
        "section_atoms": _as_int(item.get("section_atoms")),
        "section_atom_chains": _as_int(item.get("section_atom_chains")),
        "section_atom_full_chains": _as_int(item.get("section_atom_full_chains")),
        "missing_stages": missing_stages,
        "missing_stage_examples": missing_stage_examples,
    }


def _build_action_groups(items: list[dict[str, Any]], *, top_k: int) -> list[dict[str, Any]]:
    for item in items:
        item["action_group"] = _group_for(item)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in sorted(items, key=_item_sort_key):
        grouped.setdefault(str(item["action_group"]), []).append(item)

    groups: list[dict[str, Any]] = []
    for group_id in GROUP_ORDER:
        members = grouped.get(group_id) or []
        if not members:
            continue
        spec = ACTION_GROUPS[group_id]
        papers = sorted({str(item.get("paper_id") or "") for item in members if item.get("paper_id")})
        closure_counts = Counter(str(item.get("closure_state") or "unknown") for item in members)
        failure_counts = Counter(
            str(item.get("row_failure_mode") or item.get("failure_mode") or "unknown")
            for item in members
        )
        missing_stage_counts: Counter[str] = Counter()
        for item in members:
            if str(item.get("closure_state") or "") in {"partial_chain_incomplete", "open_topic_chain_mismatch"}:
                missing_stage_counts.update(
                    item.get("missing_stages")
                    or item.get("section_atom_chain_missing_stages")
                    or {}
                )
        slim_contracts = [_slim_item(item) for item in members]
        groups.append(
            {
                "group_id": group_id,
                "label": spec["label"],
                "rationale": spec["rationale"],
                "paper_count": len(papers),
                "contract_count": len(members),
                "closure_state_counts": dict(closure_counts),
                "failure_mode_counts": dict(failure_counts),
                "missing_stage_counts": dict(missing_stage_counts),
                "command_sequence": list(spec["command_sequence"]),
                "can_run_while_broad_ingest_active": bool(
                    spec.get("can_run_while_broad_ingest_active")
                ),
                "claim_scope": "evidence_repair_queue_only",
                "evidence_grade": "frontfill_target",
                "promotion_policy": "no_direct_promotion",
                "forbidden_shortcuts": list(FORBIDDEN_SHORTCUTS),
                "contracts": slim_contracts,
                "candidate_examples": _dedupe_examples(slim_contracts)[:top_k],
            }
        )
    return groups


def _dedupe_examples(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = "|".join(
            str(item.get(part) or "")
            for part in ("paper_id", "topic", "closure_state", "failure_mode")
        )
        if key in seen:
            continue
        seen.add(key)
        examples.append(item)
    return examples


def _recommended_sequence(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(group.get("group_id")): group for group in groups}
    sequence: list[dict[str, Any]] = []
    for group_id in GROUP_ORDER:
        group = by_id.get(group_id)
        if not group:
            continue
        sequence.append(
            {
                "group_id": group_id,
                "contract_count": group.get("contract_count", 0),
                "paper_count": group.get("paper_count", 0),
                "command_sequence": group.get("command_sequence") or [],
                "promotion_policy": group.get("promotion_policy"),
            }
        )
    return sequence


def build_topic_gap_repair_plan(
    *,
    triage_json: Path = REPORT_DIR / "topic_gap_section_evidence_audit.json",
    out_dir: Path = REPORT_DIR,
    top_k: int = 25,
) -> dict[str, Any]:
    triage = _loads(triage_json)
    items = _closure_items(triage)
    groups = _build_action_groups(items, top_k=top_k)
    closure_counts = Counter(str(item.get("closure_state") or "unknown") for item in items)
    action_counts = Counter(str(item.get("action_group") or "hold_as_candidate_context") for item in items)
    paper_count = len({str(item.get("paper_id") or "") for item in items if item.get("paper_id")})
    plan = {
        "plan_ts": utc_now(),
        "source_triage_json": str(triage_json),
        "source_triage_audit_ts": triage.get("audit_ts") or "",
        "status": "ready" if items else "empty",
        "execution_contract": execution_contract(),
        "summary": {
            "contracts": len(items),
            "papers": paper_count,
            "closed_contracts": sum(1 for item in items if bool(item.get("closed"))),
            "open_contracts": sum(1 for item in items if not bool(item.get("closed"))),
            "closure_state_counts": dict(closure_counts),
            "action_group_counts": dict(action_counts),
            "quick_close_contracts": int(
                action_counts.get("rebuild_section_atom_chains_quick_close", 0)
                + action_counts.get("rebuild_section_atoms_from_existing_sections", 0)
            ),
            "local_raw_pdf_ingest_contracts": int(
                action_counts.get("targeted_local_raw_pdf_ingest_when_safe", 0)
            ),
            "policy": (
                "This is a report-only execution plan. It may schedule raw-PDF reuse, atom builds, "
                "exact/Fuzzy retrieval substrate, and chain assembly, but it cannot promote claims."
            ),
        },
        "recommended_sequence": _recommended_sequence(groups),
        "action_groups": groups,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "topic_gap_repair_execution_plan.json"
    md_path = out_dir / "topic_gap_repair_execution_plan.md"
    csv_path = out_dir / "topic_gap_repair_execution_plan.csv"
    plan["outputs"] = {"json": str(json_path), "markdown": str(md_path), "csv": str(csv_path)}
    json_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    md_path.write_text(_render_markdown(plan), encoding="utf-8")
    _write_csv(csv_path, plan)
    return plan


def _write_csv(path: Path, plan: dict[str, Any]) -> None:
    fieldnames = [
        "group_id",
        "paper_id",
        "repair_id",
        "source_contract",
        "topic",
        "gap_type",
        "closure_state",
        "failure_mode",
        "priority_score",
        "command_sequence",
        "next_action",
        "missing_stages",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for group in plan.get("action_groups") or []:
            command_sequence = " && ".join(str(cmd) for cmd in group.get("command_sequence") or [])
            for item in group.get("contracts") or []:
                writer.writerow(
                    {
                        "group_id": group.get("group_id") or "",
                        "paper_id": item.get("paper_id") or "",
                        "repair_id": item.get("repair_id") or "",
                        "source_contract": item.get("source_contract") or "",
                        "topic": item.get("topic") or "",
                        "gap_type": item.get("gap_type") or "",
                        "closure_state": item.get("closure_state") or "",
                        "failure_mode": item.get("failure_mode") or "",
                        "priority_score": item.get("priority_score") or 0,
                        "command_sequence": command_sequence,
                        "next_action": item.get("next_action") or "",
                        "missing_stages": json.dumps(
                            item.get("missing_stages") or {},
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    }
                )


def _render_markdown(plan: dict[str, Any]) -> str:
    summary = plan["summary"]
    lines = [
        "# Topic-Gap Repair Execution Plan",
        "",
        f"- plan_ts: `{plan['plan_ts']}`",
        f"- source_triage: `{plan['source_triage_json']}`",
        f"- status: `{plan['status']}`",
        f"- contracts: `{summary['contracts']}`; papers: `{summary['papers']}`",
        f"- quick-close contracts: `{summary['quick_close_contracts']}`",
        f"- local raw-PDF ingest contracts: `{summary['local_raw_pdf_ingest_contracts']}`",
        "",
        "## Execution Contract",
        "",
        "- Section atomization is deterministic/rules-first and traceable to PDF page/span.",
        "- Exact search is hard retrieval evidence; fuzzy embedding search is candidate recall only.",
        "- Graph/GNN expansion may rank or widen candidates only; it cannot create atoms or promote claims.",
        "- Step5c/Step13 Claim Card gates control promotion.",
        "",
        "## Action Groups",
        "",
        "| group | contracts | papers | missing stages | command sequence |",
        "|---|---:|---:|---|---|",
    ]
    for group in plan.get("action_groups") or []:
        commands = "<br>".join(f"`{cmd}`" for cmd in group.get("command_sequence") or [])
        missing = ", ".join(
            f"{stage}:{int(count)}"
            for stage, count in Counter(group.get("missing_stage_counts") or {}).most_common()
        )
        lines.append(
            f"| {group['group_id']} | {int(group['contract_count']):,} | "
            f"{int(group['paper_count']):,} | {missing or '-'} | {commands} |"
        )
    lines.extend(["", "## Top Examples", ""])
    for group in plan.get("action_groups") or []:
        lines.extend(
            [
                f"### {group['group_id']}",
                "",
                f"- policy: `{group['promotion_policy']}`; claim_scope: `{group['claim_scope']}`",
                "",
                "| paper_id | topic | closure_state | failure_mode | missing_stages | next_action |",
                "|---|---|---|---|---|---|",
            ]
        )
        for item in (group.get("candidate_examples") or [])[:10]:
            missing = ", ".join(
                f"{stage}:{int(count)}"
                for stage, count in Counter(item.get("missing_stages") or {}).most_common()
            )
            lines.append(
                f"| `{_md(item.get('paper_id'))}` | {_md(item.get('topic'))} | "
                f"`{_md(item.get('closure_state'))}` | `{_md(item.get('failure_mode'))}` | "
                f"{_md(missing or '-')} | {_md(item.get('next_action'))} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Forbidden Shortcuts",
            "",
            *[f"- {shortcut}" for shortcut in FORBIDDEN_SHORTCUTS],
            "",
        ]
    )
    return "\n".join(lines)


def _md(value: Any) -> str:
    return " ".join(str(value or "").replace("|", ";").split())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Plan topic-gap repairs from closure states.")
    add_common_args(parser)
    parser.add_argument(
        "--triage-json",
        type=Path,
        default=REPORT_DIR / "topic_gap_section_evidence_audit.json",
    )
    parser.add_argument("--out-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--top-k", type=int, default=25)
    args = parser.parse_args(argv)
    plan = build_topic_gap_repair_plan(
        triage_json=args.triage_json,
        out_dir=args.out_dir,
        top_k=args.top_k,
    )
    print(json.dumps({"status": plan["status"], "summary": plan["summary"], "outputs": plan["outputs"]}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
