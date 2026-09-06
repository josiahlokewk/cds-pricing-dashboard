"""Sanity checks for scripts/standard_contract.py.

Unlike test_integration.py, there is no "original notebook" reference number to
target here -- this prices a genuinely new (standard, not bespoke) contract
that never existed in the assignment. So these are sanity checks only (signs,
convergence, rough agreement with the calibration input, internal consistency
between full_mtm and the cash-settlement grossed-up amount) -- not a tight
regression target. Tight targets become possible once real Bloomberg CDSW
output for a comparable contract is available.
"""

import pytest

from engine.bootstrap import rpv01
from engine.pricing import protection_leg_pv
from scripts.standard_contract import (
    CALIBRATION_RECOVERY,
    TABLE_1,
    TRADE_DATE,
    build_calibration_quotes,
    price_standard_contract,
)


@pytest.fixture(scope="module")
def priced():
    return price_standard_contract()


def test_all_tenors_converge(priced):
    for (tenor, _, _), history in zip(TABLE_1, priced["histories"]):
        _, _, residual, _ = history[-1]
        assert abs(residual) < 1e-6, f"{tenor} did not converge: residual={residual}"


def test_bootstrap_reprices_every_calibration_instrument_exactly(priced):
    # The defining property of a bootstrap: feeding each calibration instrument's
    # own quoted spread back through the SAME pricing formula used to build the
    # curve must return that same spread, to (near) machine precision. This is
    # a stronger, more direct check than test_all_tenors_converge's residual
    # check above -- it independently recomputes protection PV and RPV01 from
    # scratch using the calibrated curve, rather than trusting the solver's own
    # internal bookkeeping. This exact test would have caught, on the first
    # run, a real bug where the standard-contract path's own par-spread display
    # used a different annuity convention than its calibration -- the 5Y quote
    # was off by 1.83bp before that was found and fixed.
    hazard_curve = priced["hazard_curve"]
    discount_curve = priced["discount_curve"]
    quotes = build_calibration_quotes(TRADE_DATE, TABLE_1, CALIBRATION_RECOVERY)
    for (tenor, _, spread_bp), quote in zip(TABLE_1, quotes):
        prot = protection_leg_pv(quote.maturity, quote.recovery, hazard_curve, discount_curve)
        ann = rpv01(quote.payment_times, quote.payment_deltas, hazard_curve, discount_curve, exact_accrual=True)
        implied_bp = prot / ann * 10000.0
        assert implied_bp == pytest.approx(spread_bp, abs=1e-3), \
            f"{tenor}: reprices to {implied_bp}bp, expected {spread_bp}bp"


def test_survival_curve_is_monotonically_decreasing(priced):
    values = priced["hazard_curve"].node_values
    assert all(values[i] > values[i + 1] for i in range(len(values) - 1))
    assert 0.0 < values[-1] < 1.0


def test_protection_and_premium_legs_are_positive(priced):
    mtm = priced["mtm"]
    assert mtm["protection_leg"] > 0
    assert mtm["premium_leg"] > 0


def test_standard_contract_has_real_accrued_interest(priced):
    # Even a brand-new standard CDS accrues against the fixed quarterly IMM
    # grid, so entering mid-quarter always creates a real accrued stub -- this
    # is NOT a seasoned-only phenomenon. Verified against a real Bloomberg CDSW
    # screenshot for this exact contract: Bloomberg's own "Accrued (72 Days)"
    # is -$20,000 (100bp * 72/360 * $10mm), matching exactly.
    assert priced["mtm"]["accrued_interest"] == pytest.approx(-20_000.0, abs=0.01)
    assert priced["mtm"]["full_mtm"] != priced["mtm"]["clean_mtm"]


def test_par_spread_roughly_matches_the_5y_calibration_quote(priced):
    # The 5Y row of TABLE_1 quotes 41.400bp (real Bloomberg Apple 5Y ask, see
    # module docstring); our own contract's own par spread, computed off the
    # calibrated curve for the same (approximately 5Y) tenor, should land close
    # to that -- small differences are expected from schedule/day-count details
    # (this contract's own maturity/schedule vs. the calibration instrument's),
    # not evidence of a bug. Tight tolerance (0.5bp): both the calibration
    # instruments (build_calibration_quotes) and our own contract now use the
    # same full-first-coupon-plus-accrued convention (rpv01_seasoned via a real
    # delta_prevpay_to_valuation, not the old degenerate 0.0), so there's no
    # structural convention mismatch left to cause a bigger gap here.
    five_year_quote_bp = next(spread for tenor, _, spread in TABLE_1 if tenor == "5Y")
    assert priced["par_spread_bp"] == pytest.approx(five_year_quote_bp, abs=0.5)


def test_points_upfront_sign_matches_par_spread_vs_coupon(priced):
    # The fixed 100bp coupon exceeds the real ~41bp par spread here, so the
    # protection buyer is overpaying via the premium leg relative to the
    # protection actually received -- the buyer must be compensated upfront,
    # so PUF should be negative, matching full_mtm's sign directly (see
    # price_standard_contract's comment on the PUF sign convention).
    assert priced["par_spread_bp"] < 100.0
    assert priced["points_upfront"] < 0
    assert priced["mtm"]["full_mtm"] < 0


def test_cash_settlement_amount_is_grossed_up_from_clean_mtm(priced):
    # cash_settlement_amount is grossed up from clean_mtm (the accrued-inclusive
    # total, matching Bloomberg's "Cash Amount"), not full_mtm (the accrued-free
    # total, matching Bloomberg's "Principal") -- see price_standard_contract's
    # own comment on this split. settle_amount then divides by a discount factor
    # slightly below 1 (T+3 is a few days after the valuation date, at a
    # positive rate), pushing the cash figure slightly further from zero in
    # whatever direction clean_mtm already points -- a small gross-up in
    # magnitude on top of that, not a large one.
    clean_mtm = priced["mtm"]["clean_mtm"]
    settlement = priced["cash_settlement_amount"]
    assert abs(settlement) > abs(clean_mtm)
    assert settlement == pytest.approx(clean_mtm, rel=0.01)
