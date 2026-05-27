"""Echelon physics module - physical constants and validation."""
from .n_eff_table import N_EFF_TABLE, effective_wavelength_nm, get_n_eff
from .falsifiability import assess_falsifiability, FalsifiabilityResult

__all__ = [
    "N_EFF_TABLE",
    "effective_wavelength_nm",
    "get_n_eff",
    "assess_falsifiability",
    "FalsifiabilityResult",
]
