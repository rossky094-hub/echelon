"""
Echelon V14-B Evidence Decision workflow.

Current V14B is an evidence-constrained research decision pipeline, not the
legacy pilot graph flow.  The active chain runs identifier repair, OpenAlex /
local field-topic coverage, graph features, main path, keystones, evidence
subgraphs, citation-function evidence, calibrated future candidate generation,
section-level limitation/resolution extraction, fusion, Step13 Claim Cards,
mutation/layout, reports, visual Topic Dossier/Radar, and value-delivery audits.

Legacy enrich / pilot / arXiv gap-first entrypoints remain compatibility-only
and must not be treated as the current acceptance workflow.
"""

__version__ = "14.2.0"
__all__ = [
    "config",
    "llm_client",
    "db_schema",
    "utils",
]
