"""End-to-end integration test: the real assignment contract and dates, run through
the new ISDA-style engine (OIS discount curve + closed-form protection leg) with a
placeholder discount curve approximating the real Nelson-Siegel rates for this
period. Bounds are loose (a few percent) rather than exact-match, because the
methodology has deliberately changed from the original notebook -- the point is
"same ballpark, right sign, right structure", not byte-for-byte reproduction. Once
real Bloomberg OIS data replaces the placeholder curve, this test's tolerance can
tighten.
"""

from datetime import date

import pytest

from engine.bootstrap import CDSQuote, bootstrap_hazard_curve
from engine.daycount import act360, generate_payment_dates, roll_date, standard_payment_dates
from engine.discount_curve import bootstrap_ois_curve
from engine.pricing import mtm_seasoned_cds, protection_leg_pv, rpv01_seasoned

VALUATION_DATE = date(2014, 2, 28)

TABLE_1 = [
    ("6M", date(2014, 9, 20), 103.07),
    ("1Y", date(2015, 3, 20), 104.68),
    ("2Y", date(2016, 3, 20), 106.74),
    ("3Y", date(2017, 3, 20), 110.31),
    ("4Y", date(2018, 3, 20), 113.38),
    ("5Y", date(2019, 3, 20), 116.98),
    ("7Y", date(2021, 3, 20), 128.78),
    ("10Y", date(2024, 3, 20), 143.51),
    ("20Y", date(2034, 3, 20), 159.43),
    ("30Y", date(2044, 3, 20), 164.13),
]
STANDARD_RECOVERY = 0.45

OIS_NODE_YEARS = [0.5, 1, 2, 3, 4, 5, 7, 10, 20, 30]
OIS_PLACEHOLDER_RATES = [0.0003, 0.0007, 0.0036, 0.0076, 0.0114, 0.0152, 0.0208, 0.0263, 0.0362, 0.0395]

# Original notebook headline numbers (Nelson-Siegel + m=12 grid), for comparison.
ORIGINAL_PROTECTION_LEG = 16_599_748.00
ORIGINAL_PREMIUM_LEG = 24_138_762.00
ORIGINAL_FULL_MTM = -7_539_014.00
ORIGINAL_CLEAN_MTM = -7_590_958.00
# Original notebook's accrued interest, $51,944, is deliberately NOT reproduced --
# see test_accrued_interest_reflects_the_unadjusted_prior_coupon_date below.


def _build_calibration_quotes():
    quotes = []
    for _, mat_date, spread_bp in TABLE_1:
        mat_rolled = roll_date(mat_date)
        maturity_years = act360(VALUATION_DATE, mat_rolled)
        pay_dates = standard_payment_dates(mat_rolled, VALUATION_DATE)  # (unadjusted, adjusted) pairs
        # Discounting time uses the adjusted (actually-paid) date; accrual delta
        # uses the unadjusted (nominal) date -- see daycount.py's docstring.
        payment_times = [act360(VALUATION_DATE, adjusted) for _, adjusted in pay_dates]
        deltas = []
        prev_unadjusted = VALUATION_DATE
        for unadjusted, _ in pay_dates:
            deltas.append(act360(prev_unadjusted, unadjusted))
            prev_unadjusted = unadjusted
        quotes.append(CDSQuote(maturity_years, spread_bp / 10000.0, STANDARD_RECOVERY,
                                payment_times, deltas))
    return quotes


@pytest.fixture(scope="module")
def priced_contract():
    discount_curve = bootstrap_ois_curve(OIS_NODE_YEARS, OIS_PLACEHOLDER_RATES)
    quotes = _build_calibration_quotes()
    hazard_curve, histories = bootstrap_hazard_curve(
        quotes, discount_curve, x0=0.01, tol=1e-6,
        exact_accrual=False,  # deliberately reproducing the assignment's own approximated calibration
    )

    ns_effective = date(2012, 5, 15)
    ns_maturity = date(2042, 5, 15)
    ns_spread = 170 / 10000.0
    ns_recovery = 0.60
    face_value = 100_000_000

    all_dates = generate_payment_dates(ns_effective, ns_maturity)  # (unadjusted, adjusted) pairs
    # Past/future partition is about whether cash has actually moved yet, so it's
    # based on the adjusted (paid) date.
    past_dates = [pair for pair in all_dates if pair[1] <= VALUATION_DATE]
    future_dates = [pair for pair in all_dates if pair[1] > VALUATION_DATE]
    (t_minus1, _), (t0, _) = past_dates[-1], future_dates[0]

    ns_maturity_years = (ns_maturity - VALUATION_DATE).days / 365.25
    # Discounting time uses adjusted dates; accrual deltas use unadjusted dates.
    future_payment_times = [(adjusted - VALUATION_DATE).days / 365.25 for _, adjusted in future_dates]
    future_unadjusted = [unadjusted for unadjusted, _ in future_dates]
    future_payment_deltas = [act360(future_unadjusted[n - 1], future_unadjusted[n])
                             for n in range(1, len(future_unadjusted))]

    protection_pv = protection_leg_pv(ns_maturity_years, ns_recovery, hazard_curve, discount_curve)
    rpv01_value = rpv01_seasoned(
        delta_prevpay_to_valuation=act360(t_minus1, VALUATION_DATE),
        delta_valuation_to_t0=act360(VALUATION_DATE, t0),
        delta_prevpay_to_t0=act360(t_minus1, t0),
        future_payment_times=future_payment_times,
        future_payment_deltas=future_payment_deltas,
        hazard_curve=hazard_curve, discount_curve=discount_curve,
        exact_accrual=False,  # deliberately reproducing the assignment's own approximated numbers
    )
    results = mtm_seasoned_cds(protection_pv, rpv01_value, ns_spread,
                                act360(t_minus1, VALUATION_DATE), face_value)
    return hazard_curve, histories, results


def test_all_tenors_converge(priced_contract):
    _, histories, _ = priced_contract
    for (tenor, _, _), history in zip(TABLE_1, histories):
        _, _, residual, _ = history[-1]
        assert abs(residual) < 1e-6, f"{tenor} did not converge: residual={residual}"
        assert len(history) < 10, f"{tenor} took too many iterations: {len(history)}"


def test_survival_curve_is_monotonically_decreasing(priced_contract):
    hazard_curve, _, _ = priced_contract
    values = hazard_curve.node_values
    assert all(values[i] > values[i + 1] for i in range(len(values) - 1))
    assert 0.0 < values[-1] < 1.0


def test_mtm_signs_and_magnitudes_are_sane(priced_contract):
    _, _, results = priced_contract
    assert results["protection_leg"] > 0
    assert results["premium_leg"] > 0
    assert results["full_mtm"] < 0  # contractual 170bp exceeds the fair spread
    assert results["accrued_interest"] > 0


def test_accrued_interest_reflects_the_unadjusted_prior_coupon_date(priced_contract):
    # Accrued interest is pure day-count arithmetic (spread * day-count fraction),
    # but it no longer matches the original notebook's number: the previous coupon
    # date here is 15 Feb 2014, a Saturday. The original notebook rolled that to
    # Mon 17 Feb 2014 and accrued from there (11 days to 28 Feb) -- giving its
    # $51,944 figure. Per the unadjusted/adjusted split (see daycount.py), accrual
    # should be measured from the unadjusted nominal date, 15 Feb, not the rolled
    # one -- 13 days to 28 Feb, not 11. This is a deliberate, understood 2-day
    # divergence from the original number, not a bug: 170bp * 13/360 * $100mm.
    _, _, results = priced_contract
    expected = 0.017 * (13 / 360.0) * 100_000_000
    assert results["accrued_interest"] == pytest.approx(expected, abs=0.01)


def test_new_engine_agrees_with_original_within_a_few_percent(priced_contract):
    # Loose bound: the discount curve here is a placeholder approximation of the
    # real Nelson-Siegel curve, not an exact reproduction, so exact match isn't
    # expected. This tightens once real Bloomberg OIS data replaces the placeholder.
    _, _, results = priced_contract
    assert results["protection_leg"] == pytest.approx(ORIGINAL_PROTECTION_LEG, rel=0.02)
    assert results["premium_leg"] == pytest.approx(ORIGINAL_PREMIUM_LEG, rel=0.02)
    assert results["full_mtm"] == pytest.approx(ORIGINAL_FULL_MTM, rel=0.02)
    assert results["clean_mtm"] == pytest.approx(ORIGINAL_CLEAN_MTM, rel=0.02)
