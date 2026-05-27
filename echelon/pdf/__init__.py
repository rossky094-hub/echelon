"""Echelon PDF module — parsing and evidence extraction."""
from .extract_abstract import extract_abstract_full
from .parser import (
    PageBlock,
    parse_pdf_pages,
    build_page_pool,
    format_with_page_markers,
    post_validate_evidence_page,
)
from .extract_evidence import (
    build_extraction_prompt,
    validate_and_create_atoms,
)

# EvidenceAtom re-exported from schema for convenience
from echelon.schema.evidence import EvidenceAtom

__all__ = [
    "extract_abstract_full",
    "EvidenceAtom",
    "PageBlock",
    "parse_pdf_pages",
    "build_page_pool",
    "format_with_page_markers",
    "post_validate_evidence_page",
    "build_extraction_prompt",
    "validate_and_create_atoms",
]
