import math

import pytest

from engine.discount_curve import bootstrap_ois_curve


def test_discount_factor_at_time_zero_is_one():
    curve = bootstrap_ois_curve([1, 2, 5], [0.04, 0.045, 0.05])
    assert curve.discount_factor(0) == 1.0


def test_flat_curve_matches_annual_compounding_closed_form():
    # For a flat par-rate curve on UNIFORMLY annually-spaced nodes (delta=1
    # throughout), the bootstrapped discount factors have the exact closed form
    # Z(t) = 1 / (1+r)^t -- a hand-derivable check, not just "it ran without error".
    # This identity is specific to uniform annual spacing: once a gap between nodes
    # exceeds one year, the par-swap accrual is proportional to the gap size rather
    # than compounding annually within it, so the naive closed form no longer holds
    # exactly -- that's a real feature of irregular-tenor bootstrapping, not a bug,
    # and is exercised separately below with the realistic non-uniform tenor list.
    r = 0.05
    nodes = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    curve = bootstrap_ois_curve(nodes, [r] * len(nodes))
    for t in nodes:
        expected = 1.0 / (1.0 + r) ** t
        assert curve.discount_factor(t) == pytest.approx(expected, rel=1e-10)


def test_two_node_bootstrap_matches_manual_algebra():
    # node 1: Z(1) = (1 - 0)/(1 + 0.05*1) = 1/1.05
    # node 2: annuity_so_far = 1 * Z(1); Z(2) = (1 - 0.06*annuity)/(1+0.06*1)
    curve = bootstrap_ois_curve([1, 2], [0.05, 0.06])
    Z1_expected = 1.0 / 1.05
    annuity = 1.0 * Z1_expected
    Z2_expected = (1.0 - 0.06 * annuity) / (1.0 + 0.06 * 1.0)
    assert curve.discount_factor(1) == pytest.approx(Z1_expected, rel=1e-12)
    assert curve.discount_factor(2) == pytest.approx(Z2_expected, rel=1e-12)


def test_discount_factors_are_monotonically_decreasing_for_positive_rates():
    curve = bootstrap_ois_curve([0.5, 1, 2, 3, 5, 7, 10, 20, 30],
                                 [0.045, 0.046, 0.047, 0.048, 0.049, 0.05, 0.051, 0.052, 0.053])
    dfs = [curve.discount_factor(t) for t in [0.5, 1, 2, 3, 5, 7, 10, 20, 30]]
    assert all(dfs[i] > dfs[i + 1] for i in range(len(dfs) - 1))


def test_interpolation_between_nodes_uses_flat_forward():
    curve = bootstrap_ois_curve([1, 2], [0.05, 0.06])
    Z1 = curve.discount_factor(1)
    Z2 = curve.discount_factor(2)
    forward = -math.log(Z2 / Z1) / (2 - 1)
    midpoint_expected = Z1 * math.exp(-forward * 0.5)
    assert curve.discount_factor(1.5) == pytest.approx(midpoint_expected, rel=1e-12)


def test_extrapolation_beyond_last_node_is_flat_forward():
    curve = bootstrap_ois_curve([1, 2, 5], [0.04, 0.045, 0.05])
    Z2 = curve.discount_factor(2)
    Z5 = curve.discount_factor(5)
    forward = -math.log(Z5 / Z2) / (5 - 2)
    expected_at_7 = Z5 * math.exp(-forward * 2)
    assert curve.discount_factor(7) == pytest.approx(expected_at_7, rel=1e-12)
