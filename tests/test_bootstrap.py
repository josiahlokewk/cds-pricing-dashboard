import math

import pytest

from engine.bootstrap import (
    CDSQuote,
    _dprotection_leg_dh_last,
    _drpv01_dh_last,
    bootstrap_hazard_curve,
    rpv01,
    solve_hazard_rate_newton,
)
from engine.credit_curve import HazardCurve
from engine.discount_curve import bootstrap_ois_curve
from engine.pricing import protection_leg_pv


def _simple_discount_curve():
    # Near-zero rates, consistent with the assignment's actual valuation date
    # (28 Feb 2014, deep in the post-crisis ZIRP era) -- the professor-supplied
    # Nelson-Siegel curve gives r(1) approx 0.07%, r(10) approx 2.6%. An arbitrary
    # flat 4% here (this test's original choice) is unrealistic for this period and
    # can silently create a genuinely negative-forward-hazard scenario for some
    # spread pairs, which is a fixture problem, not an engine bug -- see the
    # debugging note on test_bootstrap_hazard_curve_sequential_dependency below.
    nodes = [0.5, 1, 2, 3, 4, 5, 7, 10]
    rates = [0.0003, 0.0007, 0.0036, 0.0076, 0.0114, 0.0152, 0.0208, 0.0263]
    return bootstrap_ois_curve(nodes, rates)


def test_analytic_protection_leg_derivative_matches_finite_difference():
    # This is the most important correctness check on the freshly-derived closed-
    # form Jacobian: bump h by +-eps and compare to the analytic derivative,
    # exactly as you'd validate any hand-derived Jacobian against a numerical one.
    discount = _simple_discount_curve()
    t_prev_boundary = 2.0
    maturity = 5.0
    recovery = 0.4
    h_known = [(1.0, 0.02), (2.0, 0.025)]  # (node_year, hazard) pairs already calibrated
    known_years = [t for t, _ in h_known]

    def survival_curve_for(x):
        node_years = []
        node_values = []
        t_prev, Q_prev = 0.0, 1.0
        for t, h in h_known:
            Q = Q_prev * math.exp(-h * (t - t_prev))
            node_years.append(t)
            node_values.append(Q)
            t_prev, Q_prev = t, Q
        Q_final = Q_prev * math.exp(-x * (maturity - t_prev))
        node_years.append(maturity)
        node_values.append(Q_final)
        return HazardCurve(node_years, node_values)

    def f(x):
        return protection_leg_pv(maturity, recovery, survival_curve_for(x), discount)

    x0 = 0.03
    eps = 1e-6
    numerical = (f(x0 + eps) - f(x0 - eps)) / (2 * eps)
    analytic = _dprotection_leg_dh_last(maturity, recovery, t_prev_boundary, survival_curve_for(x0), discount)

    assert analytic == pytest.approx(numerical, rel=1e-5)


def test_analytic_rpv01_derivative_matches_finite_difference():
    discount = _simple_discount_curve()
    t_prev_boundary = 2.0
    maturity = 5.0
    payment_times = [2.5, 3.0, 3.5, 4.0, 4.5, 5.0]
    payment_deltas = [0.25] * 6
    h_known = [(1.0, 0.02), (2.0, 0.025)]

    def survival_curve_for(x):
        node_years, node_values = [], []
        t_prev, Q_prev = 0.0, 1.0
        for t, h in h_known:
            Q = Q_prev * math.exp(-h * (t - t_prev))
            node_years.append(t)
            node_values.append(Q)
            t_prev, Q_prev = t, Q
        Q_final = Q_prev * math.exp(-x * (maturity - t_prev))
        node_years.append(maturity)
        node_values.append(Q_final)
        return HazardCurve(node_years, node_values)

    def f(x):
        return rpv01(payment_times, payment_deltas, survival_curve_for(x), discount)

    x0 = 0.03
    eps = 1e-6
    numerical = (f(x0 + eps) - f(x0 - eps)) / (2 * eps)
    analytic = _drpv01_dh_last(payment_times, payment_deltas, t_prev_boundary, survival_curve_for(x0), discount)

    assert analytic == pytest.approx(numerical, rel=1e-5)


def test_single_tenor_bootstrap_converges_to_zero_residual():
    discount = _simple_discount_curve()
    quote = CDSQuote(
        maturity=5.0, spread=0.0117, recovery=0.45,
        payment_times=[0.25 * i for i in range(1, 21)],
        payment_deltas=[0.25] * 20,
    )
    h, history = solve_hazard_rate_newton(quote, 0.0, [], [], discount, x0=0.01, tol=1e-6)
    assert h > 0
    _, _, last_residual, _ = history[-1]
    assert abs(last_residual) < 1e-6
    assert len(history) < 10  # should converge quickly, same order as the original notebook (3-4 iters)


def test_bootstrap_hazard_curve_sequential_dependency():
    # Real 1Y/2Y spreads from the assignment's Table 1.
    discount = _simple_discount_curve()
    quotes = [
        CDSQuote(1.0, 0.010468, 0.45, [0.25, 0.5, 0.75, 1.0], [0.25] * 4),
        CDSQuote(2.0, 0.010674, 0.45, [1.25, 1.5, 1.75, 2.0], [0.25] * 4),
    ]
    curve, histories = bootstrap_hazard_curve(quotes, discount, x0=0.01, tol=1e-6)
    assert len(histories) == 2
    assert curve.node_years == [1.0, 2.0]
    for history in histories:
        _, _, last_residual, _ = history[-1]
        assert abs(last_residual) < 1e-6
    # Survival probability must be strictly decreasing.
    assert curve.survival_probability(1.0) > curve.survival_probability(2.0)
    assert curve.survival_probability(0.5) > curve.survival_probability(1.0)
    # Both tenors' calibration should have converged.
    for history in histories:
        _, _, last_residual, _ = history[-1]
        assert abs(last_residual) < 1e-6


def test_bootstrap_hazard_curve_full_ten_tenor_curve_is_well_behaved():
    # Full 10-tenor calibration using the assignment's own market spreads (Table 1),
    # but against a flat OIS discount curve rather than the professor-supplied
    # Nelson-Siegel curve -- a plausibility/robustness check, not a reproduction of
    # the original headline numbers (which are expected to change now that both the
    # discount curve source and protection-leg integration method have changed).
    discount = _simple_discount_curve()
    tenors_years = [0.5, 1, 2, 3, 4, 5, 7, 10]
    spreads_bp = [103.07, 104.68, 106.74, 110.31, 113.38, 116.98, 128.78, 143.51]

    quotes = []
    for T, S in zip(tenors_years, spreads_bp):
        n_payments = max(1, round(T * 4))
        payment_times = [T * k / n_payments for k in range(1, n_payments + 1)]
        payment_deltas = [T / n_payments] * n_payments
        quotes.append(CDSQuote(T, S / 10000.0, 0.45, payment_times, payment_deltas))

    curve, histories = bootstrap_hazard_curve(quotes, discount, x0=0.01, tol=1e-6)

    assert len(histories) == len(quotes)
    for history in histories:
        assert len(history) < 15
        _, _, last_residual, _ = history[-1]
        assert abs(last_residual) < 1e-6

    survival_values = [curve.survival_probability(t) for t in tenors_years]
    assert all(survival_values[i] > survival_values[i + 1] for i in range(len(survival_values) - 1))
    assert survival_values[0] < 1.0
    assert survival_values[-1] > 0.0
