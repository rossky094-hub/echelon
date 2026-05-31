"""First-principles path challenge audit for V14B.

The algorithm-logic audit checks whether each step has a sound role.  This
audit asks a different question: is the current path of effort still the best
route to an evidence-constrained research decision system, or are we drifting
toward graph polish, broad crawling, model scores, or green tests as proxies
for scientific readiness?
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from echelon.v14b.config import DB_MAIN, DB_V14


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _count(db_path: Path, table: str) -> int | None:
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type IN ('table','virtual table') AND name=?",
                (table,),
            ).fetchone()
            if not row:
                return None
            count_row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            return int(count_row[0] or 0) if count_row else 0
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def _gate(value_audit: dict[str, Any], issue: str) -> dict[str, Any]:
    for gate in value_audit.get("gates") or []:
        if isinstance(gate, dict) and gate.get("issue") == issue:
            return gate
    return {}


def _multi_topic_counts(raw: Any) -> dict[str, int]:
    counts: Counter[str] = Counter()
    if isinstance(raw, list):
        for row in raw:
            if isinstance(row, dict):
                counts[str(row.get("overall_status") or row.get("status") or "unknown")] += 1
    elif isinstance(raw, dict):
        counts[str(raw.get("overall_status") or raw.get("status") or "unknown")] += 1
    return dict(sorted(counts.items()))


def _value_summary(value_audit: dict[str, Any]) -> dict[str, int]:
    raw = value_audit.get("summary") or {}
    return {str(k): int(v or 0) for k, v in raw.items()}


def _challenge(
    *,
    area: str,
    current_path: str,
    first_principles_test: str,
    evidence: dict[str, Any],
    verdict: str,
    risk: str,
    better_path: str,
) -> dict[str, Any]:
    return {
        "area": area,
        "current_path": current_path,
        "first_principles_test": first_principles_test,
        "evidence": evidence,
        "verdict": verdict,
        "risk": risk,
        "better_path": better_path,
    }


def build_path_challenge_audit(
    *,
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    report_dir: Path = Path("reports/v14b_pilot"),
) -> dict[str, Any]:
    value_audit = _load_json(report_dir / "value_delivery_audit.json", {})
    direction = _load_json(report_dir / "direction_readiness_audit.json", {})
    algorithm = _load_json(report_dir / "algorithm_logic_audit.json", {})
    release = _load_json(report_dir / "release_readiness.json", {})
    multi_topic = _load_json(report_dir / "multi_topic_regression.json", [])
    raw_pdf = _load_json(report_dir / "raw_pdf_store_audit.json", {})

    value_summary = _value_summary(value_audit)
    direction_metrics = direction.get("metrics") or {}
    release_checks = release.get("checks") or {}
    multi_counts = _multi_topic_counts(multi_topic)
    section_embeddings = _count(db_main, "section_embeddings")
    section_atoms = _count(db_main, "section_atoms")
    section_atom_embeddings = _count(db_main, "section_atom_embeddings")
    direction_claim_cards = _count(db_v14, "direction_claim_cards")

    linked_ref_rate = float(direction_metrics.get("linked_ref_rate") or 0.0)
    openalex_rate = float(direction_metrics.get("openalex_w_rate") or 0.0)
    high_conf_cards = int(direction_metrics.get("high_confidence_claim_cards") or 0)
    topic_gap_gate = _gate(value_audit, "Multi-topic Regression")
    evidence_gate = _gate(value_audit, "Evidence Bone")

    challenges = [
        _challenge(
            area="release_go_no_go",
            current_path="Use green tests, rendered graph, or generated reports as a release proxy.",
            first_principles_test=(
                "A decision system is release-ready only when evidence gates, multi-topic "
                "regression, and high-confidence Claim Card gates are closed."
            ),
            evidence={
                "release_status": release.get("release_status") or "unknown",
                "acceptance_ready": bool(release.get("acceptance_ready")),
                "value_delivery_summary": value_summary,
                "multi_topic_status_counts": multi_counts,
            },
            verdict="hold" if value_summary.get("fail") or multi_counts.get("fail") else "aligned",
            risk="Graph/demo progress can be mistaken for scientific readiness.",
            better_path="Treat release_readiness as the go/no-go surface; keep user-visible claims evidence-scoped until it clears.",
        ),
        _challenge(
            area="evidence_acquisition_strategy",
            current_path="Continue broad PDF/section crawling as a background substrate.",
            first_principles_test=(
                "Evidence acquisition should maximize decision lift per parsed paper, especially "
                "for benchmark-topic turning papers, future endpoints, and Claim Card inputs."
            ),
            evidence={
                "raw_pdf_store_status": raw_pdf.get("status"),
                "topic_gap_blocking": bool(topic_gap_gate.get("topic_gap_blocking")),
                "topic_gap_decision_grade_section_rate": topic_gap_gate.get("topic_gap_decision_grade_section_rate"),
                "section_atoms": section_atoms,
            },
            verdict="redirect" if topic_gap_gate.get("topic_gap_blocking") else "aligned",
            risk="Full-corpus crawling can consume time while the benchmark-topic decision gaps remain open.",
            better_path=(
                "Keep broad crawling alive, but route engineering attention to topic-gap-repair "
                "and stale-contract/unattempted-PDF queues before promoting Dossier/Radar output."
            ),
        ),
        _challenge(
            area="retrieval_substrate",
            current_path="Use atom exact/fuzzy search now; wait to materialize section-level fuzzy context.",
            first_principles_test=(
                "Fuzzy retrieval can widen recall, but every retrieved context must remain candidate-only "
                "and must be available before downstream Claim Cards rely on it."
            ),
            evidence={
                "section_atom_embeddings": section_atom_embeddings,
                "section_embeddings": section_embeddings,
                "release_check_section_embeddings": release_checks.get("section_embeddings_materialized"),
            },
            verdict="hold" if not section_embeddings else "aligned",
            risk="Long-section semantic recall is code-complete but absent from the live DB; Step13 may miss context until post-frontfill rebuild.",
            better_path="At the first safe section-ingest boundary, run post-frontfill-chain so section-embeddings, chains, Step5c/6/13, and audits rebuild together.",
        ),
        _challenge(
            area="citation_backbone",
            current_path="Use current citation/main-path graph while linked references remain sparse.",
            first_principles_test=(
                "Citation evolution and main-path claims require enough linked references to distinguish "
                "field history from local-corpus sampling artifacts."
            ),
            evidence={
                "linked_ref_rate": linked_ref_rate,
                "threshold": 0.30,
            },
            verdict="hold" if linked_ref_rate < 0.30 else "aligned",
            risk="Main path can look causal while actually reflecting missing cited works.",
            better_path="Keep main-path output as low-linked-ref context and prioritize exact cited-work backfill plus relinking.",
        ),
        _challenge(
            area="future_to_radar",
            current_path="Use GNN/VGAE future candidates as growth signal.",
            first_principles_test=(
                "A future edge is only an inspection target until calibrated evidence, Step6 fusion, "
                "and a complete/high-confidence Step13 Claim Card exist."
            ),
            evidence={
                "direction_claim_cards": direction_claim_cards,
                "high_confidence_claim_cards": high_conf_cards,
            },
            verdict="hold" if high_conf_cards <= 0 else "aligned",
            risk="Candidate ranking can be misread as investable direction confidence.",
            better_path="Keep raw future edges in candidate_pool and focus repair on complete five-question Claim Cards with falsifiable experiments.",
        ),
        _challenge(
            area="openalex_field_context",
            current_path="Use OpenAlex/local field-topic enrichment as context.",
            first_principles_test=(
                "Field/topic context is useful only as uncertainty-aware context; it cannot substitute "
                "for local section evidence or linked citation evidence."
            ),
            evidence={
                "openalex_w_rate": openalex_rate,
                "threshold": 0.70,
            },
            verdict="hold" if openalex_rate < 0.70 else "aligned",
            risk="Cross-field claims may look broader than the current metadata support allows.",
            better_path="Continue conservative OpenAlex/local field-topic repair and label cross-field claims with uncertainty until coverage improves.",
        ),
    ]

    counts = Counter(str(item["verdict"]) for item in challenges)
    if counts.get("redirect"):
        overall = "redirect_evidence_first"
    elif counts.get("hold"):
        overall = "hold_high_confidence_promotion"
    else:
        overall = "path_aligned"
    return {
        "generated_at": utc_now(),
        "audit_type": "v14b_first_principles_path_challenge",
        "overall_status": overall,
        "verdict_counts": dict(sorted(counts.items())),
        "algorithm_logic_status_counts": algorithm.get("status_counts") or {},
        "evidence_bone_status": evidence_gate.get("status") or "unknown",
        "challenges": challenges,
        "policy": (
            "This audit challenges the current route before more execution. It cannot promote claims; "
            "it only redirects effort toward the evidence path most likely to produce auditable Topic Dossiers, "
            "Evolution Evidence Maps, and Claim Cards."
        ),
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# V14B First-Principles Path Challenge Audit",
        "",
        f"- generated_at: `{result['generated_at']}`",
        f"- overall_status: `{result['overall_status']}`",
        f"- verdict_counts: `{json.dumps(result['verdict_counts'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Challenge Matrix",
        "",
        "| Area | Verdict | First-principles test | Risk | Better path |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in result["challenges"]:
        lines.append(
            f"| {item['area']} | {item['verdict']} | "
            f"{item['first_principles_test']} | {item['risk']} | {item['better_path']} |"
        )
    lines.extend(
        [
            "",
            "## Evidence Snapshot",
            "",
        ]
    )
    for item in result["challenges"]:
        lines.append(f"- **{item['area']}**: `{json.dumps(item['evidence'], ensure_ascii=False, sort_keys=True)}`")
    lines.extend(["", "## Policy", "", result["policy"], ""])
    return "\n".join(lines)


def run_path_challenge_audit(
    *,
    db_main: Path = DB_MAIN,
    db_v14: Path = DB_V14,
    out_dir: Path = Path("reports/v14b_pilot"),
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    result = build_path_challenge_audit(db_main=db_main, db_v14=db_v14, report_dir=out_dir)
    (out_dir / "path_challenge_audit.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_dir / "path_challenge_audit.md").write_text(render_markdown(result), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the V14B first-principles path challenge audit.")
    parser.add_argument("--db", type=Path, default=DB_MAIN)
    parser.add_argument("--db-v14", type=Path, default=DB_V14)
    parser.add_argument("--out-dir", type=Path, default=Path("reports/v14b_pilot"))
    args = parser.parse_args(argv)
    result = run_path_challenge_audit(db_main=args.db, db_v14=args.db_v14, out_dir=args.out_dir)
    print(json.dumps(
        {
            "overall_status": result["overall_status"],
            "json": str(args.out_dir / "path_challenge_audit.json"),
            "report": str(args.out_dir / "path_challenge_audit.md"),
        },
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
