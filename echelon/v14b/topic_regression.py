"""Topic-level product regression audits.

The first gold topic is Metalens because it is mainstream enough that an empty
or generic Topic Lens is obviously wrong.  This audit checks whether the system
returns decision-grade evidence: named branches, bottlenecks, turning papers,
future candidates, access links, and Claim Card readiness.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echelon.v14b.product_baseline import (
    METALENS_EXPECTED_BRANCHES,
    evaluate_topic_lens,
)


@dataclass(frozen=True)
class GoldTopic:
    topic: str
    expected_branches: tuple[str, ...]
    expected_bottlenecks: tuple[str, ...]
    minimum_key_turning_papers: int = 5
    minimum_branches_with_driver_papers: int = 4
    minimum_turning_papers_with_access: int = 5
    minimum_turning_papers_with_primary_section: int = 3


METALENS_GOLD = GoldTopic(
    topic="metalens",
    expected_branches=METALENS_EXPECTED_BRANCHES,
    expected_bottlenecks=(
        "efficiency",
        "chromatic aberration",
        "field of view",
        "manufacturing consistency",
        "system integration",
        "cost",
    ),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _lower_text(value: Any) -> str:
    if isinstance(value, str):
        return value.lower()
    return json.dumps(value, ensure_ascii=False).lower()


def _branch_by_name(lens: dict[str, Any]) -> dict[str, dict[str, Any]]:
    dossier = lens.get("topic_dossier") or {}
    branches = dossier.get("branch_splits") or []
    return {
        str(branch.get("name") or ""): branch
        for branch in branches
        if isinstance(branch, dict)
    }


def _bottleneck_text(lens: dict[str, Any]) -> str:
    dossier = lens.get("topic_dossier") or {}
    pieces = [
        dossier.get("hard_bottlenecks") or dossier.get("bottleneck_dossiers") or [],
        lens.get("unresolved_limitations") or [],
        lens.get("bottleneck_lineage") or [],
    ]
    return " ".join(_lower_text(piece) for piece in pieces)


def _turning_papers(lens: dict[str, Any]) -> list[dict[str, Any]]:
    history = lens.get("history_main_path") or {}
    return [
        p for p in (history.get("key_turning_papers") or [])
        if isinstance(p, dict)
    ]


def _future_edges(lens: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        e for e in ((lens.get("future_growth") or {}).get("predicted_edges") or [])
        if isinstance(e, dict)
    ]


def _claim_cards(lens: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        c for c in ((lens.get("rd_radar") or {}).get("claim_cards") or [])
        if isinstance(c, dict)
    ]


def _paper_has_primary_section(paper: dict[str, Any]) -> bool:
    availability = paper.get("content_availability") or {}
    return bool(availability.get("has_primary_evidence_sections"))


def _paper_has_access(paper: dict[str, Any]) -> bool:
    return bool(paper.get("access_links") or [])


def _status(passed: bool, warn: bool = False) -> str:
    if passed:
        return "pass"
    return "warn" if warn else "fail"


def run_topic_regression(lens: dict[str, Any], gold: GoldTopic = METALENS_GOLD) -> dict[str, Any]:
    baseline = evaluate_topic_lens(gold.topic, lens)
    branches = _branch_by_name(lens)
    bottleneck_text = _bottleneck_text(lens)
    turning = _turning_papers(lens)
    future_edges = _future_edges(lens)
    claim_cards = _claim_cards(lens)

    branch_results = []
    branches_with_drivers = 0
    for name in gold.expected_branches:
        branch = branches.get(name)
        driver_papers = (branch or {}).get("driver_papers") or []
        has_driver = bool(driver_papers)
        branches_with_drivers += int(has_driver)
        branch_results.append(
            {
                "name": name,
                "present": bool(branch),
                "driver_papers": len(driver_papers),
                "has_bottleneck": bool((branch or {}).get("historical_bottleneck")),
                "has_enabler": bool((branch or {}).get("enabling_condition")),
                "status": _status(bool(branch) and has_driver),
            }
        )

    bottleneck_results = []
    for label in gold.expected_bottlenecks:
        matched = label.lower() in bottleneck_text
        bottleneck_results.append(
            {
                "name": label,
                "present_in_evidence": matched,
                "status": _status(matched),
            }
        )

    turning_with_access = sum(1 for p in turning if _paper_has_access(p))
    turning_with_primary_section = sum(1 for p in turning if _paper_has_primary_section(p))
    complete_claim_cards = sum(
        1
        for c in claim_cards
        if c.get("eligible")
        or c.get("five_question_complete")
        or ((c.get("claim_card") or {}).get("five_question_complete"))
    )

    gates = [
        {
            "name": "expected branches found",
            "actual": baseline.get("expected_branch_coverage"),
            "required": 1.0,
            "status": _status(float(baseline.get("expected_branch_coverage") or 0.0) >= 1.0),
        },
        {
            "name": "branches with driver papers",
            "actual": branches_with_drivers,
            "required": gold.minimum_branches_with_driver_papers,
            "status": _status(branches_with_drivers >= gold.minimum_branches_with_driver_papers),
        },
        {
            "name": "expected bottlenecks evidenced",
            "actual": sum(1 for b in bottleneck_results if b["present_in_evidence"]),
            "required": len(gold.expected_bottlenecks),
            "status": _status(all(b["present_in_evidence"] for b in bottleneck_results)),
        },
        {
            "name": "key turning papers",
            "actual": len(turning),
            "required": gold.minimum_key_turning_papers,
            "status": _status(len(turning) >= gold.minimum_key_turning_papers),
        },
        {
            "name": "turning papers with access links",
            "actual": turning_with_access,
            "required": gold.minimum_turning_papers_with_access,
            "status": _status(turning_with_access >= gold.minimum_turning_papers_with_access),
        },
        {
            "name": "turning papers with primary sections",
            "actual": turning_with_primary_section,
            "required": gold.minimum_turning_papers_with_primary_section,
            "status": _status(turning_with_primary_section >= gold.minimum_turning_papers_with_primary_section),
        },
        {
            "name": "Claim Cards for Radar",
            "actual": complete_claim_cards,
            "required": 1,
            "status": _status(complete_claim_cards >= 1, warn=bool(future_edges)),
        },
    ]
    fail = [gate for gate in gates if gate["status"] == "fail"]
    warn = [gate for gate in gates if gate["status"] == "warn"]
    overall = "fail" if fail else "warn" if warn else "pass"

    return {
        "audit_ts": utc_now(),
        "topic": gold.topic,
        "overall_status": overall,
        "gates": gates,
        "branch_results": branch_results,
        "bottleneck_results": bottleneck_results,
        "key_turning_papers": {
            "total": len(turning),
            "with_access_links": turning_with_access,
            "with_primary_section": turning_with_primary_section,
        },
        "future_candidates": {
            "total": len(future_edges),
            "claim_cards": len(claim_cards),
            "complete_claim_cards": complete_claim_cards,
        },
        "baseline_quality": baseline,
    }


def render_regression_md(result: dict[str, Any]) -> str:
    lines = [
        "# Metalens Topic Regression",
        "",
        f"- Audit: `{result['audit_ts']}`",
        f"- Topic: `{result['topic']}`",
        f"- Overall status: **{result['overall_status']}**",
        "",
        "## Gates",
        "",
        "| Gate | Actual | Required | Status |",
        "| --- | ---: | ---: | --- |",
    ]
    for gate in result["gates"]:
        actual = gate["actual"]
        if isinstance(actual, float):
            actual = f"{actual:.2f}"
        lines.append(f"| {gate['name']} | {actual} | {gate['required']} | {gate['status']} |")
    lines.extend(["", "## Expected Branches", "", "| Branch | Drivers | Bottleneck | Enabler | Status |", "| --- | ---: | --- | --- | --- |"])
    for row in result["branch_results"]:
        lines.append(
            f"| {row['name']} | {row['driver_papers']} | {row['has_bottleneck']} | {row['has_enabler']} | {row['status']} |"
        )
    lines.extend(["", "## Expected Bottlenecks", "", "| Bottleneck | Present In Evidence | Status |", "| --- | --- | --- |"])
    for row in result["bottleneck_results"]:
        lines.append(f"| {row['name']} | {row['present_in_evidence']} | {row['status']} |")
    k = result["key_turning_papers"]
    f = result["future_candidates"]
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            f"- Key turning papers: {k['total']} total, {k['with_access_links']} with access links, {k['with_primary_section']} with primary local sections.",
            f"- Future candidates: {f['total']} graph candidates, {f['claim_cards']} Radar cards, {f['complete_claim_cards']} complete cards.",
            "- This regression fails loudly when the UI is only showing paper lists or raw GNN edges.  Passing it means the Topic Dossier is closer to a decision-grade research brief.",
        ]
    )
    gaps = (result.get("baseline_quality") or {}).get("quality_gaps") or []
    if gaps:
        lines.extend(["", "## Quality Gaps", ""])
        for gap in gaps:
            lines.append(f"- {gap}")
    return "\n".join(lines) + "\n"


def load_topic_lens(topic: str, top_k: int) -> dict[str, Any]:
    from echelon.api.graph_visual_backend import get_topic_lens

    return get_topic_lens(topic=topic, top_k=top_k)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a Topic Lens product regression.")
    parser.add_argument("--topic", default="metalens")
    parser.add_argument("--top-k", type=int, default=80)
    parser.add_argument("--out-dir", default="reports/v14b_pilot")
    args = parser.parse_args(argv)
    if args.topic.lower() != "metalens":
        raise SystemExit("Only the Metalens gold topic is currently defined.")

    lens = load_topic_lens(args.topic, args.top_k)
    result = run_topic_regression(lens, METALENS_GOLD)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / "metalens_topic_regression.md"
    json_path = out_dir / "metalens_topic_regression.json"
    md.write_text(render_regression_md(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(md), "json": str(json_path), "overall_status": result["overall_status"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
