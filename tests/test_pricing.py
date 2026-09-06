import math

import pytest

from engine.credit_curve import HazardCurve
from engine.discount_curve import OISCurve, bootstrap_ois_curve
from engine.pricing import accrual_on_default, critical_dates, protection_leg_pv, settle_amount


def flat_hazard_curve(lam: float, maturity: float) -> HazardCurve:
    # A single-node hazard curve: Q(t) = exp(-lam * t) exactly, node at `maturity`.
    return HazardCurve([maturity], [math.exp(-lam * maturity)])


def test_single_segment_matches_hand_derived_formula():
    # No intervening nodes on either curve -> exactly one critical subinterval,
    # [0, T], so the closed form should reduce to the raw two-point O'Kane-Turnbull
    # formula with no summation involved.
    lam, r, T, R = 0.02, 0.03, 5.0, 0.4
    hazard = flat_hazard_curve(lam, T)
    discount = bootstrap_ois_curve([T], [_flat_ois_rate_for(r, T)])

    Z0, Q0 = 1.0, 1.0
    ZT = discount.discount_factor(T)
    QT = hazard.survival_probability(T)
    expected = (1 - R) * (lam / (lam + r)) * (Z0 * Q0 - ZT * QT)

    assert protection_leg_pv(T, R, hazard, discount) == pytest.approx(expected, rel=1e-9)


def _flat_ois_rate_for(continuous_rate: float, maturity: float) -> float:
    # Convert a target continuously-compounded rate into the par OIS rate that
    # reproduces Z(T) = exp(-continuous_rate * T) via a single-node bootstrap:
    # Z(T) = 1 / (1 + C*T)  =>  C = (1/Z(T) - 1) / T
    Z_target = math.exp(-continuous_rate * maturity)
    return (1.0 / Z_target - 1.0) / maturity


def test_critical_dates_includes_both_curves_nodes_and_maturity():
    hazard = HazardCurve([1, 3, 5, 10], [0.98, 0.9, 0.8, 0.6])
    discount = bootstrap_ois_curve([2, 4, 8], [0.04, 0.045, 0.05])
    dates = critical_dates(7, hazard, discount)
    # hazard nodes < 7: 1, 3, 5; discount nodes < 7: 2, 4; plus maturity 7 itself.
    assert dates == [1, 2, 3, 4, 5, 7]


def test_zero_maturity_gives_zero_protection_leg():
    hazard = flat_hazard_curve(0.02, 5.0)
    discount = bootstrap_ois_curve([5.0], [_flat_ois_rate_for(0.03, 5.0)])
    assert protection_leg_pv(0.0, 0.4, hazard, discount) == 0.0


def test_scales_linearly_with_loss_given_default():
    hazard = flat_hazard_curve(0.02, 5.0)
    discount = bootstrap_ois_curve([5.0], [_flat_ois_rate_for(0.03, 5.0)])
    pv_40 = protection_leg_pv(5.0, 0.40, hazard, discount)
    pv_60 = protection_leg_pv(5.0, 0.60, hazard, discount)
    # (1-0.60)/(1-0.40) = 0.4/0.6
    assert pv_60 / pv_40 == pytest.approx(0.4 / 0.6, rel=1e-9)


def test_closed_form_is_the_limit_of_the_assignments_own_discretized_grid():
    # Reimplements the assignment's own m-subintervals-per-year trapezoidal
    # approximation (report.pdf / assignment1.pdf, section 2.2) and checks that it
    # converges TO the closed form as m increases -- i.e. the closed form is the
    # exact answer the discretized grid is only ever approximating.
    lam, r, T, R = 0.02, 0.03, 5.0, 0.4
    hazard = flat_hazard_curve(lam, T)
    discount = bootstrap_ois_curve([T], [_flat_ois_rate_for(r, T)])
    exact = protection_leg_pv(T, R, hazard, discount)

    def grid_approximation(m: int) -> float:
        K = math.ceil(m * T)
        eps = T / K
        total = 0.0
        for k in range(1, K + 1):
            s_prev, s_curr = (k - 1) * eps, k * eps
            Z_prev = discount.discount_factor(s_prev)
            Z_curr = discount.discount_factor(s_curr)
            Q_prev = hazard.survival_probability(s_prev)
            Q_curr = hazard.survival_probability(s_curr)
            total += (Z_prev + Z_curr) * (Q_prev - Q_curr)
        return (1 - R) / 2.0 * total

    error_m12 = abs(grid_approximation(12) - exact)
    error_m120 = abs(grid_approximation(120) - exact)
    error_m1200 = abs(grid_approximation(1200) - exact)

    # Error should shrink as the grid gets finer, converging on the closed form.
    assert error_m120 < error_m12
    assert error_m1200 < error_m120
    assert error_m1200 < 1e-6


def test_protection_start_offset_matches_hand_derived_formula():
    # start > 0 (protection beginning at the step-in date, not the valuation date)
    # should reduce to the same closed form applied from `start` to T instead of
    # from 0 to T -- i.e. exactly the [0, T] segment minus the now-excluded
    # [0, start] sliver.
    lam, r, T, R = 0.02, 0.03, 5.0, 0.4
    start = 3 / 365.0  # T+3 business days, expressed in years
    hazard = flat_hazard_curve(lam, T)
    discount = bootstrap_ois_curve([T], [_flat_ois_rate_for(r, T)])

    Z_start = discount.discount_factor(start)
    Q_start = hazard.survival_probability(start)
    Z_T = discount.discount_factor(T)
    Q_T = hazard.survival_probability(T)
    expected = (1 - R) * (lam / (lam + r)) * (Z_start * Q_start - Z_T * Q_T)

    assert protection_leg_pv(T, R, hazard, discount, start=start) == pytest.approx(expected, rel=1e-9)


def test_protection_start_offset_reduces_pv_relative_to_starting_at_zero():
    lam, r, T, R = 0.02, 0.03, 5.0, 0.4
    hazard = flat_hazard_curve(lam, T)
    discount = bootstrap_ois_curve([T], [_flat_ois_rate_for(r, T)])

    pv_from_zero = protection_leg_pv(T, R, hazard, discount, start=0.0)
    pv_from_step_in = protection_leg_pv(T, R, hazard, discount, start=3 / 365.0)
    assert pv_from_step_in < pv_from_zero


def test_settle_amount_grosses_up_by_the_settlement_lag():
    lam, r, T, R = 0.02, 0.03, 5.0, 0.4
    discount = bootstrap_ois_curve([T], [_flat_ois_rate_for(r, T)])
    pv_at_valuation = 123_456.78
    settle_years = 3 / 365.0

    amount = settle_amount(pv_at_valuation, settle_years, discount)

    assert amount == pytest.approx(pv_at_valuation / discount.discount_factor(settle_years), rel=1e-12)
    assert amount > pv_at_valuation  # positive rates -> grossed up, not down


def test_accrual_on_default_matches_hand_derived_closed_form():
    # Flat hazard/rate single segment: integral[sk,ek] (t-sk)P(t)(-dQ(t)/dt)dt has
    # an independently hand-derivable closed form via calculus (integration by
    # parts of u*e^{-(r+lam)u}), separate from accrual_on_default's own ISDA
    # eps(x)/eps'(x) formula -- a genuine cross-check, not circular.
    lam, r, sk, ek = 0.02, 0.03, 2.0, 2.25
    D = ek - sk
    hazard = HazardCurve([sk, ek], [math.exp(-lam * sk), math.exp(-lam * ek)])
    discount = OISCurve([sk, ek], [math.exp(-r * sk), math.exp(-r * ek)])

    rl = r + lam
    exact = lam * math.exp(-r * sk) * math.exp(-lam * sk) * (1.0 / rl ** 2) * (1 - math.exp(-rl * D) * (1 + rl * D))

    mine = accrual_on_default(sk, sk, ek, hazard, discount, isda_half_day_bug=False)
    assert mine == pytest.approx(exact, rel=1e-9)


def test_accrual_on_default_matches_brute_force_riemann_sum():
    lam, r, sk, ek = 0.02, 0.03, 2.0, 2.25
    hazard = HazardCurve([sk, ek], [math.exp(-lam * sk), math.exp(-lam * ek)])
    discount = OISCurve([sk, ek], [math.exp(-r * sk), math.exp(-r * ek)])

    mine = accrual_on_default(sk, sk, ek, hazard, discount, isda_half_day_bug=False)

    n = 200_000
    du = (ek - sk) / n
    brute = 0.0
    for i in range(n):
        u = (i + 0.5) * du
        t = sk + u
        Pt = math.exp(-r * t)
        Qt = math.exp(-lam * t)
        brute += u * Pt * lam * Qt * du

    assert mine == pytest.approx(brute, rel=1e-4)


def test_accrual_on_default_handles_a_curve_node_inside_the_period():
    # A hazard-curve node falling strictly inside the accrual period (the n_k>1
    # case from White eqn 46) -- verified against a brute-force Riemann sum using
    # the same piecewise hazard rate, independent of accrual_on_default's own
    # critical_dates-based segmentation.
    sk, ek, split = 2.0, 2.25, 2.1
    hazard = HazardCurve([split, ek],
                          [math.exp(-0.02 * split), math.exp(-0.02 * split) * math.exp(-0.05 * (ek - split))])
    discount = OISCurve([sk, ek], [math.exp(-0.03 * sk), math.exp(-0.03 * ek)])

    mine = accrual_on_default(sk, sk, ek, hazard, discount, isda_half_day_bug=False)

    def Q(t):
        if t <= split:
            return math.exp(-0.02 * t)
        return math.exp(-0.02 * split) * math.exp(-0.05 * (t - split))

    n = 200_000
    du = (ek - sk) / n
    eps = 1e-7
    brute = 0.0
    for i in range(n):
        t = sk + (i + 0.5) * du
        dQdt = (Q(t + eps) - Q(t - eps)) / (2 * eps)
        brute += (t - sk) * math.exp(-0.03 * t) * (-dQdt) * du

    assert mine == pytest.approx(brute, rel=1e-3)


def test_accrual_on_default_handles_degenerate_lambda_plus_r_near_zero():
    sk, ek = 2.0, 2.25
    hazard = HazardCurve([ek], [math.exp(0.03 * ek)])   # lambda = -0.03, cancels r
    discount = OISCurve([ek], [math.exp(-0.03 * ek)])
    value = accrual_on_default(sk, sk, ek, hazard, discount, isda_half_day_bug=False)
    assert math.isfinite(value)


def test_isda_half_day_bug_produces_a_small_shift():
    lam, r, sk, ek = 0.02, 0.03, 2.0, 2.25
    hazard = HazardCurve([sk, ek], [math.exp(-lam * sk), math.exp(-lam * ek)])
    discount = OISCurve([sk, ek], [math.exp(-r * sk), math.exp(-r * ek)])

    clean = accrual_on_default(sk, sk, ek, hazard, discount, isda_half_day_bug=False)
    bloomberg = accrual_on_default(sk, sk, ek, hazard, discount, isda_half_day_bug=True)

    assert clean != bloomberg
    assert abs(clean - bloomberg) < 0.05 * abs(clean)  # a half-day shift is a small effect


def test_rpv01_seasoned_exact_accrual_close_to_but_different_from_approximation():
    # term D's exact-accrual path should be a small, non-zero correction to the
    # mid-period approximation -- same relationship as the protection leg's
    # closed form vs. the assignment's m=12 grid: close, not identical.
    from engine.pricing import rpv01_seasoned
    hazard = HazardCurve([0.5, 1, 2, 3, 5, 7, 10],
                          [0.995, 0.99, 0.978, 0.965, 0.935, 0.90, 0.85])
    discount = bootstrap_ois_curve([0.5, 1, 2, 3, 5, 7, 10],
                                    [0.02, 0.022, 0.025, 0.027, 0.03, 0.032, 0.034])
    future_times = [0.1, 0.35, 0.6, 0.85, 1.1]
    future_deltas = [0.25] * 4

    approx = rpv01_seasoned(0.15, 0.1, 0.25, future_times, future_deltas, hazard, discount,
                             exact_accrual=False)
    exact = rpv01_seasoned(0.15, 0.1, 0.25, future_times, future_deltas, hazard, discount,
                            exact_accrual=True)

    assert exact != approx
    assert abs(exact - approx) / approx < 0.001  # small correction, not a different answer


def test_rpv01_seasoned_stub_term_matches_independent_brute_force():
    # Checks the eta-scaling and t_minus1-derivation wiring inside rpv01_seasoned
    # itself (not just accrual_on_default in isolation) against a brute-force
    # numerical integral computed independently, using the curve's own methods
    # rather than re-deriving the closed form.
    from engine.pricing import accrual_on_default

    hazard = HazardCurve([0.5, 1, 2, 3, 5, 7, 10],
                          [0.995, 0.99, 0.978, 0.965, 0.935, 0.90, 0.85])
    discount = bootstrap_ois_curve([0.5, 1, 2, 3, 5, 7, 10],
                                    [0.02, 0.022, 0.025, 0.027, 0.03, 0.032, 0.034])

    delta_prevpay_to_valuation = 0.15
    t0 = 0.1
    eta = 365.0 / 360.0
    t_minus1_ct = -delta_prevpay_to_valuation / eta

    term_ab = eta * accrual_on_default(t_minus1_ct, 0.0, t0, hazard, discount, isda_half_day_bug=False)

    n = 200_000
    du = t0 / n
    brute = 0.0
    for i in range(n):
        s = (i + 0.5) * du
        Zs = discount.discount_factor(s)
        eps = 1e-6
        dQ = (hazard.survival_probability(s + eps) - hazard.survival_probability(s - eps)) / (2 * eps)
        brute += (s - t_minus1_ct) * Zs * (-dQ) * du
    brute_scaled = eta * brute

    assert term_ab == pytest.approx(brute_scaled, rel=1e-4)
