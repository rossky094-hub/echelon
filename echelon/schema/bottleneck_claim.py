"""
BottleneckClaim / EvidenceLink / OpticalCondition schema.

Fixes:
- AUDIT-047: evidence_id field added to BottleneckClaim; gatekeeper validates membership
- AUDIT-059: condition_json:dict → OpticalCondition (strong-typed)
- AUDIT-065: binds_optimization_objective added; physical depth = 5-item any-4
- AUDIT-072: @model_validator(mode='after') used for cross-field validation
- AUDIT-018: constraint_inversion split into attempted_circumvention (small positive)
             and claimed_resolution (negative signal) — semantic clarity
- AUDIT-021: Pydantic warning when both attempted_circumvention and
             claimed_resolution are empty (non-blocking)

ULIDStr is a 26-char Base32 string.
"""
from __future__ import annotations

import hashlib
import logging
import warnings
from typing import Annotated, Dict, List, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

ULIDStr = Annotated[str, Field(min_length=26, max_length=26)]


# ---------------------------------------------------------------------------
# OpticalCondition  [AUDIT-059]
# ---------------------------------------------------------------------------

class OpticalCondition(BaseModel):
    """
    Strong-typed optical experimental condition.

    Replaces the free-form ``condition_json: dict`` in V11.1.
    All key names and units are fixed; LLM prompt explicitly lists each field.
    This prevents the key-name divergence problem (wl / wavelength / lambda / …).
    """

    wavelength_nm: Optional[float] = Field(
        None,
        ge=1.0,
        le=100_000.0,
        description="Operating wavelength in nm (1 nm – 100 µm covers UV–THz)",
    )
    wavelength_range_nm: Optional[List[float]] = Field(
        None,
        min_length=2,
        max_length=2,
        description="Wavelength range [min_nm, max_nm]",
    )
    numerical_aperture: Optional[float] = Field(None, ge=0.0, le=2.0)
    polarization: Optional[
        Literal["TE", "TM", "TE+TM", "circular", "elliptical", "unpolarized", "unknown"]
    ] = None
    temperature_k: Optional[float] = Field(None, ge=0.0, le=10_000.0)
    medium: Optional[
        Literal[
            "vacuum", "air", "si", "sin", "sio2", "ln", "gaas", "inp",
            "glass", "water", "polymer", "unknown",
        ]
    ] = None
    input_power_mw: Optional[float] = Field(None, ge=0.0)
    other: Optional[
        Dict[
            Literal[
                "pressure_pa", "beam_waist_um", "rep_rate_ghz",
                "duty_cycle", "fiber_coupling_eff", "fsr_ghz",
            ],
            float,
        ]
    ] = None

    @model_validator(mode="after")
    def validate_wavelength_range(self) -> "OpticalCondition":
        """[AUDIT-072] model_validator ensures all fields parsed before cross-check."""
        if self.wavelength_range_nm is not None:
            lo, hi = self.wavelength_range_nm
            if lo >= hi:
                raise ValueError(
                    f"wavelength_range_nm[0]={lo} must be < wavelength_range_nm[1]={hi}"
                )
            if self.wavelength_nm is not None and not (lo <= self.wavelength_nm <= hi):
                raise ValueError(
                    f"wavelength_nm={self.wavelength_nm} not in range [{lo}, {hi}]"
                )
        return self


# ---------------------------------------------------------------------------
# EvidenceLink  [AUDIT-047]
# ---------------------------------------------------------------------------

class EvidenceLink(BaseModel):
    """
    Link between a BottleneckClaim and a specific evidence atom.

    [AUDIT-047] V11.1 had evidence_span / evidence_page but NO evidence_id.
    The gatekeeper code `assert c.evidence_id in valid_ids` always raised
    AttributeError.  V11.2 adds evidence_id as a mandatory field.
    """

    # [AUDIT-047] Core fix: evidence_id is now mandatory
    evidence_id: UUID = Field(
        ...,
        description=(
            "[AUDIT-047] Evidence atom ID.  Must exist in evidence_pool. "
            "Validated by claim_gatekeeper()."
        ),
    )
    evidence_span: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="Evidence text (at least 3 sentences with ±1 context per AUDIT-057)",
    )
    # [AUDIT-015] page_no comes from real PDF parser, never LLM
    evidence_page: Optional[int] = Field(
        None,
        ge=1,
        description=(
            "[AUDIT-015] PDF page number from pdfplumber index. "
            "NEVER set by LLM."
        ),
    )
    parser: str = Field(
        default="pdfplumber",
        description="Parser: pdfplumber | nougat | grobid",
    )
    content_hash: str = Field(
        ...,
        description="SHA-256 of evidence_span (anti-hallucination)",
    )

    @model_validator(mode="after")
    def validate_content_hash(self) -> "EvidenceLink":
        """[AUDIT-072] Verify hash matches span after all fields parsed."""
        expected = hashlib.sha256(self.evidence_span.encode("utf-8")).hexdigest()
        if self.content_hash != expected:
            raise ValueError(
                f"evidence_span hash mismatch: expected={expected[:8]}…, "
                f"got={self.content_hash[:8]}…"
            )
        return self


# ---------------------------------------------------------------------------
# BottleneckClaim  [AUDIT-047, 059, 065]
# ---------------------------------------------------------------------------

class BottleneckClaim(BaseModel):
    """
    Atomic bottleneck claim extracted from a gold-seed paper.

    V11.2 comprehensive fix:
    - AUDIT-047: evidence_id field added (gatekeeper-compatible)
    - AUDIT-059: condition: OpticalCondition (replaces condition_json: dict)
    - AUDIT-065: binds_optimization_objective (AI4Science channel)
                 physical depth = any 4 of 5
    - AUDIT-072: @model_validator(mode='after') for cross-field validation
    """

    # Identity
    claim_text: str = Field(..., min_length=10, max_length=500)
    claim_type: Literal["limitation", "failure", "metric_boundary", "unresolved"]
    severity: Literal["weak", "limitation", "failure", "constraint", "unresolved"]

    # Physical depth — 5 dimensions [AUDIT-065]
    binds_metric: bool = Field(..., description="Binds a quantifiable physical metric (m1)")
    binds_mechanism: bool = Field(..., description="Names explicit physical mechanism (m2)")
    binds_condition: bool = Field(..., description="Bound to specific experimental conditions (m3)")
    binds_threshold: bool = Field(..., description="Provides a numerical threshold (m4)")
    binds_optimization_objective: bool = Field(
        default=False,
        description=(
            "[AUDIT-065] Binds a formal optimization objective / NN architecture (m5). "
            "AI4Science channel: allows AI inverse-design papers to pass physical depth."
        ),
    )

    # Metric value
    metric_value: Optional[float] = Field(None, description="Quantitative metric value")
    metric_unit: Optional[str] = Field(None, max_length=30)

    # [AUDIT-059] Strong-typed optical condition (replaces condition_json: dict)
    condition: OpticalCondition = Field(
        default_factory=OpticalCondition,
        description="[AUDIT-059] Strongly typed optical condition",
    )

    # Evidence chain — [AUDIT-047] each item has evidence_id
    evidence_id: str = Field(
        ...,
        description=(
            "[AUDIT-047] Primary evidence ID for this claim. "
            "Must exist in evidence_pool. Validated by claim_gatekeeper()."
        ),
    )
    evidence_span: str = Field(..., min_length=10, max_length=500)
    evidence_page: int = Field(..., ge=1, description="[AUDIT-015] Real PDF page from parser")
    evidence_section: Literal[
        "limitations", "discussion", "conclusion", "future_work", "abstract"
    ]

    # Anti-incremental signals [AUDIT-018]
    # attempted_circumvention: small positive signal — the paper DID try to work
    #   around the constraint (shows the constraint is real and recognised).
    #   Previously named `constraint_inversion` which confused cause and effect.
    attempted_circumvention: Optional[list["EvidenceLink"]] = Field(
        default=None,
        description=(
            "[AUDIT-018] Evidence that the paper attempted to circumvent / work around "
            "this constraint. Small positive signal: confirms constraint is real. "
            "Renamed from constraint_inversion to avoid causal inversion confusion."
        ),
    )
    # claimed_resolution: negative signal — the paper claims to SOLVE the constraint.
    #   If present, the claim may no longer describe an open bottleneck.
    claimed_resolution: Optional[list["EvidenceLink"]] = Field(
        default=None,
        description=(
            "[AUDIT-018] Evidence that the paper CLAIMS to resolve this constraint. "
            "Negative signal: if non-empty, verify claim is genuine before keeping."
        ),
    )
    resolution_verified: bool = Field(
        default=False,
        description="True if claimed_resolution has been independently verified.",
    )

    @model_validator(mode="after")
    def validate_evidence_id_format(self) -> "BottleneckClaim":
        """[AUDIT-072] Cross-field validation after all fields parsed."""
        parts = self.evidence_id.split("_")
        if len(parts) < 2:
            raise ValueError(
                f"evidence_id format invalid: {self.evidence_id!r}. "
                "Expected '<paper_id>_<page>_<hash3>' or similar."
            )
        # [AUDIT-021] Non-blocking warning: both anti-incremental fields empty
        circ_empty = (
            self.attempted_circumvention is None
            or len(self.attempted_circumvention) == 0
        )
        res_empty = (
            self.claimed_resolution is None
            or len(self.claimed_resolution) == 0
        )
        if circ_empty and res_empty:
            warnings.warn(
                f"[AUDIT-021] BottleneckClaim '{self.claim_text[:60]}...' has "
                "both attempted_circumvention and claimed_resolution empty. "
                "Consider filling at least one for richer anti-incremental signal.",
                UserWarning,
                stacklevel=2,
            )
        return self

    @property
    def binds_count(self) -> int:
        return sum([
            self.binds_metric,
            self.binds_mechanism,
            self.binds_condition,
            self.binds_threshold,
            self.binds_optimization_objective,
        ])

    @property
    def physical_depth_score(self) -> float:
        """5 items, any 4 pass = 0.80 ≥ 0.70 threshold. [AUDIT-065]"""
        return self.binds_count / 5.0

    @property
    def physical_depth_pass(self) -> bool:
        """Physical depth passes when ≥ 4 of 5 binds are True."""
        return self.physical_depth_score >= 0.70


# ---------------------------------------------------------------------------
# Gatekeeper  [AUDIT-047]
# ---------------------------------------------------------------------------

def claim_gatekeeper(
    claims: list[BottleneckClaim],
    evidence_pool: dict,  # {evidence_id_str: span_text}
) -> tuple[list[BottleneckClaim], list[BottleneckClaim]]:
    """
    [AUDIT-047] Guard that evidence_id for every claim exists in evidence_pool.

    V11.1 error: `c.evidence_id` raised AttributeError because the field
    did not exist in the schema.
    V11.2 fix: BottleneckClaim.evidence_id is a required field; this function
    validates membership in the pool.

    Returns:
        (valid_claims, rejected_claims)
    """
    valid_ids = set(str(k) for k in evidence_pool.keys())
    valid_claims: list[BottleneckClaim] = []
    rejected_claims: list[BottleneckClaim] = []

    for c in claims:
        # c.evidence_id now exists (AUDIT-047 fix); validate pool membership
        if c.evidence_id in valid_ids:
            valid_claims.append(c)
        else:
            rejected_claims.append(c)

    return valid_claims, rejected_claims
