from __future__ import annotations
import math
from typing import List
from engine.credit_curve import HazardCurve
from engine.discount_curve import OISCurve

# Closed-form protection leg (O'Kane-Turnbull)
#
# Under the assumption that both the hazard rate and the discount rate are
# piecewise-constant (flat-forward) between calibration nodes -- true by
# construction for both curves here -- the protection leg integral has an exact
# closed form on any subinterval [t1,t2] where both rates are constant:
#
#   integral of Z(s) Q(s) lambda ds from t1 to t2
#     = [lambda / (lambda + r)] * [Z(t1)Q(t1) - Z(t2)Q(t2)]
#
# To apply this to the full [0, T] integral, T is broken at every "critical date":
# every calibration node of either curve that falls before T, plus T itself. Within
# each resulting subinterval, neither curve crosses a node, so both lambda and r
# are genuinely constant and the closed form is exact -- no discretization error,
# no arbitrary grid density to choose.


def critical_dates(maturity: float, hazard_curve: HazardCurve, discount_curve: OISCurve,
                    start: float = 0.0) -> List[float]:
    """Union of both curves' node maturities strictly between `start` and
    `maturity`, plus `maturity` itself -- the breakpoints at which either lambda
    or r can change slope.

    ISDA terminology: the CDS Standard Model distinguishes the valuation date
    (t_v, "today" -- when the model is run) from the step-in/protection-effective
    date (t_e, when protection actually starts). `start` defaults to 0, i.e. the
    valuation date, matching the original assignment (which values everything
    from t_v with no separate step-in offset). Pass start = (t_e - t_v) in years
    to price under the full ISDA convention instead -- see protection_leg_pv.
    """
    dates = set(t for t in hazard_curve.node_years if start < t < maturity)
    dates.update(t for t in discount_curve.node_years if start < t < maturity)
    dates.add(maturity)
    return sorted(dates)


def protection_leg_pv(maturity: float, recovery: float,
                       hazard_curve: HazardCurve, discount_curve: OISCurve,
                       start: float = 0.0) -> float:
    """Closed-form protection leg PV per unit notional, for protection running
    from `start` (years from the valuation date, default 0) to `maturity`.

    ISDA convention for `start`: the assignment's own text is explicit that the
    effective/step-in date is the valuation (trade) date plus one CALENDAR day
    ("T+1 convention. This includes weekends and holidays" -- assignment1.pdf,
    section 3), so start = 1/365 (or the equivalent day-count fraction for one
    calendar day) reproduces that, with no business-day/holiday adjustment
    involved in this particular offset. This is a distinct convention from
    add_business_days() in calendar.py, which IS holiday-aware but is used for
    the cash-settle date (T+3 business days), a different date entirely -- see
    settle_amount() below. The real ISDA Standard Model also has a boolean
    protectStart flag controlling whether the step-in day itself is included in
    the protected period (a half-day timing nicety) -- that flag's exact
    semantics haven't been independently verified here, so it isn't implemented;
    flagged rather than guessed at.
    """
    pv = 0.0
    t_prev = start
    for t in critical_dates(maturity, hazard_curve, discount_curve, start):
        if t <= t_prev:
            continue

        lam = hazard_curve.forward_rate(t_prev, t)
        r = discount_curve.forward_rate(t_prev, t)
        Z_prev = discount_curve.discount_factor(t_prev)
        Z_curr = discount_curve.discount_factor(t)
        Q_prev = hazard_curve.survival_probability(t_prev)
        Q_curr = hazard_curve.survival_probability(t)

        step = Z_prev * Q_prev - Z_curr * Q_curr
        if abs(lam + r) < 1e-12:
            # Degenerate limit (lambda + r -> 0): lambda/(lambda+r) * (1 - exp(-(lambda+r)dt))
            # -> lambda * dt. Only reachable with near-cancelling negative rates and
            # near-zero hazard; guarded so the formula degrades to a sane limit
            # instead of a division by zero.
            pv += lam * (t - t_prev) * Z_prev * Q_prev
        else:
            pv += (lam / (lam + r)) * step

        t_prev = t

    return (1.0 - recovery) * pv


def _epsilon(x: float) -> float:
    """eps(x) = (e^x - 1)/x, Taylor-safe near x=0 (White 2013, "The Pricing and
    Risk Management of CDS", eqn 43). Needed for the exact ISDA accrual-on-default
    closed form below.
    """
    if abs(x) < 1e-4:
        return 1.0 + x / 2.0 + x ** 2 / 6.0 + x ** 3 / 24.0
    return (math.exp(x) - 1.0) / x


def _epsilon_prime(x: float) -> float:
    """eps'(x), Taylor-safe near x=0 (White 2013, eqn 43)."""
    if abs(x) < 1e-4:
        return 0.5 + x / 3.0 + x ** 2 / 8.0 + x ** 3 / 30.0
    return ((x - 1.0) * (math.exp(x) - 1.0) + x) / (x ** 2)


def _epsilon_double_prime(x: float) -> float:
    """eps''(x), Taylor-safe near x=0 (White 2013, eqn 43). Needed only for the
    analytic derivative of accrual_on_default with respect to a hazard rate
    (bootstrap.py's Newton-Raphson calibration), not for accrual_on_default
    itself.
    """
    if abs(x) < 1e-4:
        return 1.0 / 3.0 + x / 4.0 + x ** 2 / 10.0 + x ** 3 / 36.0
    return ((math.exp(x) - 1.0) * (x ** 2 - 2.0 * x + 2.0) + x ** 2 - 2.0 * x) / (x ** 3)


def accrual_on_default(accrual_reference: float, integration_start: float, integration_end: float,
                        hazard_curve: HazardCurve, discount_curve: OISCurve,
                        isda_half_day_bug: bool = True) -> float:
    """Exact closed-form value of

        integral[integration_start to integration_end] (s - accrual_reference) * Z(s) * (-dQ(s)) ds

    i.e. the expected, discounted accrued premium owed if default happens at some
    random time s within [integration_start, integration_end], where the accrual
    is measured back to accrual_reference (per White 2013, eqns 46/49/53).

    For an ordinary coupon period, accrual_reference == integration_start == the
    period's own start (s_k = t_{k-1} in White's notation) -- pass the same value
    for both. For a seasoned position's stub period, they differ: the accrual is
    measured back to the *prior* coupon date (which may be before the valuation
    date), while the integration only runs over [valuation date, next coupon
    date], since that's the only window where the survival curve is defined and
    where default is actually still possible. The formula is the same closed
    form either way -- what changes is only which date the accrual clock starts
    from vs. which window we're integrating default probability over.

    Breaks the integration window at any curve node inside it -- same idea as
    critical_dates() -- rather than assuming exactly one segment.

    isda_half_day_bug: True (default) replicates the official ISDA C code's
    undocumented half-day reduction to the accrual reference
    (accrual_reference - 1/730, i.e. half a day on a 365 basis). White's paper
    reports this as a known bug that Bloomberg and Markit still use in
    production and have not corrected -- matching Bloomberg means matching this,
    not the mathematically "fixed" version. Set False for the bug-free formula.
    """
    s_k = accrual_reference - (1.0 / 730.0 if isda_half_day_bug else 0.0)

    total = 0.0
    t_prev = integration_start
    for t in critical_dates(integration_end, hazard_curve, discount_curve, start=integration_start):
        if t <= t_prev:
            continue
        delta = t - t_prev
        h_hat = hazard_curve.forward_rate(t_prev, t) * delta
        f_hat = discount_curve.forward_rate(t_prev, t) * delta
        B_prev = discount_curve.discount_factor(t_prev) * hazard_curve.survival_probability(t_prev)

        x = -(f_hat + h_hat)
        total += h_hat * B_prev * ((t_prev - s_k) * _epsilon(x) + delta * _epsilon_prime(x))

        t_prev = t

    return total


def rpv01_seasoned(delta_prevpay_to_valuation: float, delta_valuation_to_t0: float,
                    delta_prevpay_to_t0: float, future_payment_times: List[float],
                    future_payment_deltas: List[float],
                    hazard_curve: HazardCurve, discount_curve: OISCurve,
                    exact_accrual: bool = True, isda_half_day_bug: bool = True,
                    eta: float = 365.0 / 360.0) -> float:
    """Risky annuity for a seasoned (mid-life) CDS, per the assignment's four-term
    decomposition (assignment1.pdf, section 2.2): term A/B/C handle the stub period
    already partly accrued between the last payment date and today, term D is the
    contribution from the remaining future coupon periods.

    delta_prevpay_to_valuation: day-count fraction from the last payment date to
        the valuation date (Delta(t_-1, 0)), on the ACCRUAL (Act/360) convention
    delta_valuation_to_t0: day-count fraction from the valuation date to the next
        payment date (Delta(0, t0)), Act/360
    delta_prevpay_to_t0: day-count fraction from the last payment date to the next
        payment date (Delta(t_-1, t0)), Act/360
    future_payment_times: [t0, t1, ..., tN], years from the valuation date, on the
        curve's day-count convention (e.g. Act/365F) -- NOT the same convention as
        the deltas above; see `eta`.
    future_payment_deltas: [Delta(t0,t1), ..., Delta(t_{N-1},tN)], Act/360 -- one
        shorter than future_payment_times

    exact_accrual: True (default) uses the exact ISDA closed-form accrual-on-
        default (accrual_on_default(), White eqns 45-49) for both term D and the
        stub period (terms A+B, replaced by one exact calculation) -- this is the
        Bloomberg/ISDA-aligned behavior and is what this codebase should produce
        unless a caller deliberately asks otherwise. Pass False only to reproduce
        the assignment's own mid-period-approximated headline numbers exactly (see
        scripts/smoke_test.py and tests/test_integration.py, which do this
        deliberately and explicitly, not by relying on a default). term_C is
        unaffected either way -- it's an exact point evaluation (full payment if
        survives to t0), not an integral, so there's nothing to approximate there.
    isda_half_day_bug: passed through to accrual_on_default when exact_accrual is
        True; see that function's docstring.
    eta: the ratio of the accrual day-count convention's year-fraction to the
        curve day-count convention's year-fraction for the same date pair
        (White eqn 17's footnote: "in most cases it will be simply 365/360").
        This is an exact constant (not merely an approximation) whenever both
        conventions are actual-days-over-a-fixed-denominator, which Act/360 and
        Act/365F both are -- the "actual days" numerator cancels in the ratio.
        Defaults to 365/360 for the standard Act/360-accrual, Act/365F-curve
        pairing; override if your curve time uses a different fixed denominator
        (e.g. 365.25). Only used when exact_accrual is True, to convert
        accrual_on_default's curve-time-based raw output into accrual-convention-
        scaled dollars, matching White eqn 17's structure exactly.
    """
    t0 = future_payment_times[0]
    Z_t0 = discount_curve.discount_factor(t0)
    Q_t0 = hazard_curve.survival_probability(t0)

    term_C = delta_prevpay_to_t0 * Z_t0 * Q_t0

    if exact_accrual:
        # t_-1 expressed on the curve's day-count convention (negative: before
        # the valuation date), derived exactly from the accrual-convention delta
        # via eta -- both conventions measure the same actual days, so this
        # conversion is exact, not approximate.
        t_minus1_curve_time = -delta_prevpay_to_valuation / eta
        stub_accrual = accrual_on_default(t_minus1_curve_time, 0.0, t0,
                                           hazard_curve, discount_curve,
                                           isda_half_day_bug=isda_half_day_bug)
        term_AB = eta * stub_accrual
    else:
        """
        midpoint approximation instead of integration
        """
        
        term_A = delta_prevpay_to_valuation * Z_t0 * (1.0 - Q_t0)
        term_B = 0.5 * delta_valuation_to_t0 * Z_t0 * (1.0 - Q_t0)
        term_AB = term_A + term_B

    term_D = 0.0
    for n in range(1, len(future_payment_times)):
        t_prev, t_curr = future_payment_times[n - 1], future_payment_times[n]
        delta = future_payment_deltas[n - 1]
        Z_curr = discount_curve.discount_factor(t_curr)
        Q_prev = hazard_curve.survival_probability(t_prev)
        Q_curr = hazard_curve.survival_probability(t_curr)

        if exact_accrual:
            premiums_only = delta * Z_curr * Q_curr
            accrued = eta * accrual_on_default(t_prev, t_prev, t_curr, hazard_curve, discount_curve,
                                                isda_half_day_bug=isda_half_day_bug)
            term_D += premiums_only + accrued
        else:
            term_D += delta * Z_curr * (Q_prev + Q_curr)

    if not exact_accrual:
        term_D *= 0.5

    return term_AB + term_C + term_D


def mtm_seasoned_cds(protection_pv: float, rpv01_value: float, contractual_spread: float,
                      delta_prevpay_to_valuation: float, face_value: float) -> dict:
    """Full/clean MTM and accrued interest for the protection buyer, per unit
    notional scaled up to face_value. Pure algebra -- doesn't care how protection_pv
    or rpv01_value were computed underneath.
    """
    full_mtm_unit = protection_pv - contractual_spread * rpv01_value
    accrued_unit = contractual_spread * delta_prevpay_to_valuation
    clean_mtm_unit = full_mtm_unit - accrued_unit

    return {
        "protection_leg": protection_pv * face_value,
        "premium_leg": contractual_spread * rpv01_value * face_value,
        "full_mtm": full_mtm_unit * face_value,
        "accrued_interest": accrued_unit * face_value,
        "clean_mtm": clean_mtm_unit * face_value,
    }


def settle_amount(pv_at_valuation: float, cash_settle_years: float, discount_curve: OISCurve) -> float:
    """Converts a PV computed as of the valuation date into the actual dollar
    amount payable on the cash-settle date.

    ISDA terminology: t_v is the valuation date ("today", t=0 -- the date curves
    are anchored to and protection_leg_pv/rpv01_seasoned price as of, normally the
    trade date); the cash-settle date is a separate, later date on which money
    actually changes hands -- standard market convention is T+3 business days
    after the trade date (confirmed against general CDS settlement conventions,
    not the assignment, which doesn't address this since it only ever values
    as-of the trade date itself). Getting that date right requires the real
    holiday calendar, not just weekends, for currencies/contracts where that
    applies -- see calendar.add_business_days(), whose default is now
    no_extra_holidays (weekend-only), matching White's paper on what non-JPY CDS
    normally use; pass holiday_fn=sifma_holidays explicitly if a specific
    contract/Bloomberg screen needs a real calendar for this date instead.

    The model values the position as of today; the real cash changes hands a few
    days later, so the amount actually exchanged must be slightly larger than
    today's PV by the time value of that gap -- an amount A paid on the settle
    date is worth A * Z(settle) today, so for that to equal today's PV,
    A = pv_at_valuation / Z(settle). (This direction is derived here from time-
    value-of-money first principles, not independently confirmed against an ISDA
    source document -- worth checking against the OpenGamma CDS paper or a real
    Bloomberg CDSW output before relying on it.)

    cash_settle_years: the cash-settle date's distance from the valuation date,
    in years -- from daycount.act365f(valuation_date, settle_date), where
    settle_date = calendar.add_business_days(trade_date, 3) (T+3 is measured
    from the trade date, not from valuation_date itself, even though
    valuation_date usually equals the trade date).
    """
    return pv_at_valuation / discount_curve.discount_factor(cash_settle_years)
