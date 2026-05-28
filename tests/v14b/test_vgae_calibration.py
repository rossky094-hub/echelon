import numpy as np

from echelon.v14b.step5b_vgae import (
    apply_probability_calibration,
    fit_probability_calibrator,
)


def test_platt_or_histogram_calibration_is_monotonic_enough():
    pos = np.array([0.72, 0.75, 0.78, 0.81, 0.86, 0.91], dtype=np.float32)
    neg = np.array([0.12, 0.16, 0.21, 0.27, 0.33, 0.39], dtype=np.float32)
    cal = fit_probability_calibrator(pos, neg)

    low, _, _ = apply_probability_calibration(0.2, cal)
    mid, _, _ = apply_probability_calibration(0.55, cal)
    high, _, _ = apply_probability_calibration(0.9, cal)

    assert 0.0 <= low <= 1.0
    assert 0.0 <= mid <= 1.0
    assert 0.0 <= high <= 1.0
    assert low <= mid <= high
    # Should not collapse everything into a single calibrated value.
    assert abs(high - low) > 1e-3
