"""Echelon seeds module - L2 candidate seed selection."""
from .consistency import robust_consistency
from .mmr import mmr_select
from .score_keystone import safe_clip, KeystoneScore
from .bt_pairing import (
    BTPlayer,
    BTMatchResult,
    swiss_system_pair,
    num_swiss_rounds,
    total_swiss_comparisons,
    estimate_bt_strengths,
    run_swiss_bt_tournament,
)

__all__ = [
    # L2 core
    "robust_consistency",
    "mmr_select",
    "safe_clip",
    "KeystoneScore",
    # AUDIT-037: Swiss-system BT pairing
    "BTPlayer",
    "BTMatchResult",
    "swiss_system_pair",
    "num_swiss_rounds",
    "total_swiss_comparisons",
    "estimate_bt_strengths",
    "run_swiss_bt_tournament",
]
