from __future__ import annotations
import math
from dataclasses import dataclass
from typing import List, Tuple
from engine.credit_curve import HazardCurve
from engine.discount_curve import OISCurve
from engine.pricing import (
    _epsilon,
    _epsilon_double_prime,
    _epsilon_prime,
    accrual_on_default,
    critical_dates,
    protection_leg_pv,
    rpv01_seasoned,
)

# Newton-Raphson hazard-rate bootstrap: solves for each h_i in maturity order, given all shorter tenors already calibrated
# Protection leg is using the closed-form O'Kane-Turnbull formula (pricing.py), 
# instead of the m=12 discretized grid, and the discount curve is an OISCurve (bootstrapped from real OIS quotes)


@dataclass
class CDSQuote:
    """One calibration instrument: a market-quoted standard CDS."""
    maturity: float               # years from valuation date
    spread: float                  # decimal, e.g. 0.0117 for 116.98bp
    recovery: float                 # decimal, e.g. 0.45
    payment_times: List[float]      # years from valuation date, this tenor's own coupon dates
    payment_deltas: List[float]     # accrual fraction for each payment period


def rpv01(payment_times: List[float], payment_deltas: List[float],
          hazard_curve: HazardCurve, discount_curve: OISCurve,
          exact_accrual: bool = True) -> float:
    """Risky annuity for a calibration instrument: PV of $1/year received on each
    coupon date while the reference entity survives.

    A calibration instrument is simply the degenerate case of a seasoned contract
    where the "prior coupon date" happens to equal the valuation date -- i.e. no
    seasoning, nothing accrued yet. This is deliberate, not an oversight: a
    market-quoted par spread is, by definition, the coupon that gives zero
    upfront for a contract entered fresh today -- "zero upfront" is exactly the
    quantity this degenerate (no-stub) annuity computes zero against. Do NOT
    thread a real pre-valuation stub through here to "match" a seasoned
    contract's own pricing -- that was tried and reverted: it broke the
    calibration's own par condition (a bootstrapped curve stopped repricing its
    own quoted spread) and moved the standard-contract upfront number further
    from a real Bloomberg screen, not closer. Accrued interest for an actual
    traded contract is a separate, additive, pure day-count adjustment applied
    AFTER this annuity is used (see price_standard_contract), not a change to
    the annuity itself.

    rpv01_seasoned already handles this degenerate case correctly (verified:
    identical output to the old, separately-implemented version of this
    function, to the last bit), so this is a thin delegation, not a second
    implementation -- there is no reason for this function and rpv01_seasoned
    to duplicate the same math in two places.
    """
    return rpv01_seasoned(
        delta_prevpay_to_valuation=0.0,
        delta_valuation_to_t0=payment_deltas[0],
        delta_prevpay_to_t0=payment_deltas[0],
        future_payment_times=payment_times,
        future_payment_deltas=payment_deltas[1:],
        hazard_curve=hazard_curve, discount_curve=discount_curve,
        exact_accrual=exact_accrual,
    )


def _dQ_dh_last(t: float, t_prev_boundary: float, hazard_curve: HazardCurve) -> float:
    """d(survival probability at t)/d(hazard rate of the final, currently-being-
    solved segment), where t_prev_boundary is the start of that segment. Zero for
    t at or before the boundary -- Q there doesn't depend on the segment we're
    still solving for.
    """
    if t <= t_prev_boundary + 1e-15:
        return 0.0
    Q = hazard_curve.survival_probability(t)
    return -(t - t_prev_boundary) * Q


def _dprotection_leg_dh_last(maturity: float, recovery: float, t_prev_boundary: float,
                              hazard_curve: HazardCurve, discount_curve: OISCurve) -> float:
    """d(protection_leg_pv)/d(hazard rate of the final segment). Subintervals
    entirely before t_prev_boundary contribute zero -- the trial hazard rate
    hasn't come into effect yet there.
    """
    d_total = 0.0
    t_prev = 0.0
    for t in critical_dates(maturity, hazard_curve, discount_curve):
        if t <= t_prev:
            continue
        if t <= t_prev_boundary + 1e-15:
            t_prev = t
            continue

        lam = hazard_curve.forward_rate(t_prev, t)
        r = discount_curve.forward_rate(t_prev, t)
        Z_prev = discount_curve.discount_factor(t_prev)
        Z_curr = discount_curve.discount_factor(t)
        Q_prev = hazard_curve.survival_probability(t_prev)
        Q_curr = hazard_curve.survival_probability(t)
        dQ_prev = _dQ_dh_last(t_prev, t_prev_boundary, hazard_curve)
        dQ_curr = _dQ_dh_last(t, t_prev_boundary, hazard_curve)

        step = Z_prev * Q_prev - Z_curr * Q_curr
        d_step = Z_prev * dQ_prev - Z_curr * dQ_curr

        if abs(lam + r) < 1e-12:
            d_total += lam * (t - t_prev) * (Z_prev * dQ_prev)
        else:
            d_weight = r / (lam + r) ** 2       # d/dlam of lam/(lam+r), times dlam/dh=1
            d_total += d_weight * step + (lam / (lam + r)) * d_step

        t_prev = t

    return (1.0 - recovery) * d_total


def _daccrual_on_default_dh_last(accrual_reference: float, integration_start: float, integration_end: float,
                                  t_prev_boundary: float,
                                  hazard_curve: HazardCurve, discount_curve: OISCurve,
                                  isda_half_day_bug: bool = True) -> float:
    """d(accrual_on_default)/d(hazard rate of the final segment). Same 'boundary'
    convention as _dprotection_leg_dh_last / _dQ_dh_last: subintervals entirely
    before t_prev_boundary contribute zero. Within [t_prev_boundary,
    integration_end], the local hazard rate for every sub-segment IS the trial
    value being solved for (no other hazard-curve node exists in that region by
    construction), so h_hat = x_trial * delta exactly, letting the chain rule
    collapse cleanly through eps, eps', and eps''.
    """
    s_k = accrual_reference - (1.0 / 730.0 if isda_half_day_bug else 0.0)
    d_total = 0.0
    t_prev = integration_start
    for t in critical_dates(integration_end, hazard_curve, discount_curve, start=integration_start):
        if t <= t_prev:
            continue
        if t <= t_prev_boundary + 1e-15:
            t_prev = t
            continue

        delta = t - t_prev
        h_hat = hazard_curve.forward_rate(t_prev, t) * delta
        f_hat = discount_curve.forward_rate(t_prev, t) * delta
        Z_prev = discount_curve.discount_factor(t_prev)
        Q_prev = hazard_curve.survival_probability(t_prev)
        B_prev = Z_prev * Q_prev

        x = -(f_hat + h_hat)
        d_h_hat_dx = delta          # h_hat = x_trial * delta in this region
        d_x_dx = -d_h_hat_dx        # f_hat is independent of the hazard rate

        dQ_prev_dx = _dQ_dh_last(t_prev, t_prev_boundary, hazard_curve)
        dB_prev_dx = Z_prev * dQ_prev_dx

        bracket = (t_prev - s_k) * _epsilon(x) + delta * _epsilon_prime(x)
        d_bracket_dx = d_x_dx * ((t_prev - s_k) * _epsilon_prime(x) + delta * _epsilon_double_prime(x))

        d_total += (d_h_hat_dx * B_prev * bracket
                    + h_hat * dB_prev_dx * bracket
                    + h_hat * B_prev * d_bracket_dx)

        t_prev = t

    return d_total


def _drpv01_dh_last(payment_times: List[float], payment_deltas: List[float],
                     t_prev_boundary: float,
                     hazard_curve: HazardCurve, discount_curve: OISCurve,
                     exact_accrual: bool = True, isda_half_day_bug: bool = True,
                     eta: float = 365.0 / 360.0) -> float:
    """Derivative of rpv01() with respect to the final segment's trial hazard
    rate. Mirrors rpv01()'s own degenerate-stub delegation: a calibration
    instrument has no seasoning, so every period is "ordinary" -- premiums-only
    plus accrual-on-default, differentiated term by term.
    """
    if not exact_accrual:
        total = 0.0
        t_prev = 0.0
        for t, delta in zip(payment_times, payment_deltas):
            dQ_prev = _dQ_dh_last(t_prev, t_prev_boundary, hazard_curve)
            dQ_curr = _dQ_dh_last(t, t_prev_boundary, hazard_curve)
            Z = discount_curve.discount_factor(t)
            total += delta * Z * (dQ_prev + dQ_curr)
            t_prev = t
        return 0.5 * total

    total = 0.0
    t_prev = 0.0
    for t, delta in zip(payment_times, payment_deltas):
        Z = discount_curve.discount_factor(t)
        d_premiums_only = delta * Z * _dQ_dh_last(t, t_prev_boundary, hazard_curve)
        d_accrued = eta * _daccrual_on_default_dh_last(t_prev, t_prev, t, t_prev_boundary,
                                                        hazard_curve, discount_curve,
                                                        isda_half_day_bug=isda_half_day_bug)
        total += d_premiums_only + d_accrued
        t_prev = t
    return total


def _survival_at_trial(boundary_curve: HazardCurve, t_prev_boundary: float,
                        x: float, maturity: float) -> float:
    """Returns survival probability at `maturity`, given an already-calibrated curve up to
    t_prev_boundary plus a trial hazard rate x applying from t_prev_boundary to
    maturity.
    """
    Q_boundary = boundary_curve.survival_probability(t_prev_boundary) if boundary_curve.node_years else 1.0
    return Q_boundary * math.exp(-x * (maturity - t_prev_boundary))


def solve_hazard_rate_newton(quote: CDSQuote, t_prev_boundary: float,
                              known_node_years: List[float], known_node_values: List[float],
                              discount_curve: OISCurve,
                              x0: float = 0.01, tol: float = 1e-6, max_iter: int = 100,
                              exact_accrual: bool = True, isda_half_day_bug: bool = True
                              ) -> Tuple[float, List[Tuple[int, float, float, float]]]:
    """Newton-Raphson solve for the hazard rate of the segment ending at
    quote.maturity, given all shorter segments already calibrated
    (known_node_years/known_node_values).
    """
    boundary_curve = HazardCurve(known_node_years, known_node_values) if known_node_years else \
        HazardCurve([], [])
    x = x0
    history: List[Tuple[int, float, float, float]] = []

    for iteration in range(max_iter):
        Q_at_maturity = _survival_at_trial(boundary_curve, t_prev_boundary, x, quote.maturity)
        trial_curve = HazardCurve(known_node_years + [quote.maturity], known_node_values + [Q_at_maturity])

        fx = (protection_leg_pv(quote.maturity, quote.recovery, trial_curve, discount_curve)
              - quote.spread * rpv01(quote.payment_times, quote.payment_deltas, trial_curve, discount_curve,
                                      exact_accrual=exact_accrual))
        dfx = (_dprotection_leg_dh_last(quote.maturity, quote.recovery, t_prev_boundary, trial_curve, discount_curve)
               - quote.spread * _drpv01_dh_last(quote.payment_times, quote.payment_deltas,
                                                 t_prev_boundary, trial_curve, discount_curve,
                                                 exact_accrual=exact_accrual, isda_half_day_bug=isda_half_day_bug))
        history.append((iteration, x, fx, dfx))

        if abs(fx) < tol:
            return x, history
        if abs(dfx) < 1e-12:
            raise ValueError(f"Derivative too small at iteration {iteration}, x={x}")

        x_new = x - fx / dfx
        if x_new <= 0:
            x_new = x / 2.0
        x = x_new

    raise ValueError(
        f"Newton-Raphson failed to converge for maturity={quote.maturity} within {max_iter} iterations "
        f"(last x={x}, |fx|={abs(fx)} >= tol={tol}) -- calibration cannot silently return a wrong curve."
    )


def bootstrap_hazard_curve(quotes: List[CDSQuote], discount_curve: OISCurve,
                            x0: float = 0.01, tol: float = 1e-6, max_iter: int = 100,
                            exact_accrual: bool = True, isda_half_day_bug: bool = True
                            ) -> Tuple[HazardCurve, List[List[Tuple[int, float, float, float]]]]:
    """Sequential Newton-Raphson bootstrap, tenor by tenor, exactly as in the
    original notebook. Returns the calibrated HazardCurve plus the full per-tenor
    Newton-Raphson history (iteration, x, f(x), f'(x)) -- this is the raw material
    the dashboard's step-by-step bootstrap player will consume later.

    exact_accrual: True (default) calibrates against the exact ISDA closed-form
    premium leg (same flag as rpv01_seasoned/rpv01); False reproduces the
    assignment's original mid-period-approximated calibration.
    """
    node_years: List[float] = []
    node_values: List[float] = []
    histories: List[List[Tuple[int, float, float, float]]] = []

    for quote in quotes:
        t_prev_boundary = node_years[-1] if node_years else 0.0
        h_i, history = solve_hazard_rate_newton(
            quote, t_prev_boundary, node_years, node_values, discount_curve,
            x0=x0, tol=tol, max_iter=max_iter,
            exact_accrual=exact_accrual, isda_half_day_bug=isda_half_day_bug,
        )
        boundary_curve = HazardCurve(node_years, node_values) if node_years else HazardCurve([], [])
        Q_at_maturity = _survival_at_trial(boundary_curve, t_prev_boundary, h_i, quote.maturity) # returns survival probability
        node_years.append(quote.maturity)
        node_values.append(Q_at_maturity)
        histories.append(history)

    return HazardCurve(node_years, node_values), histories
