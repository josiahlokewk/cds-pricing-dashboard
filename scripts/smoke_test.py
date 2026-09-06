"""End-to-end smoke test: real assignment dates and contract terms, run through the
new ISDA-style engine (OIS discount curve + closed-form protection leg). The
discount curve here is a placeholder approximating the real near-zero-rate
environment of Feb 2014 -- it stands in for real Bloomberg SOFR OIS data, which
will replace it once the one-time terminal session happens. Not expected to
reproduce the original notebook's exact headline numbers (that's the point: the
discounting source and protection-leg integration method have both deliberately
changed), but should be the same order of magnitude and directionally sensible.
"""

from datetime import date

from engine.bootstrap import CDSQuote, bootstrap_hazard_curve
from engine.daycount import act360, generate_payment_dates, roll_date, standard_payment_dates
from engine.discount_curve import bootstrap_ois_curve
from engine.pricing import mtm_seasoned_cds, protection_leg_pv, rpv01_seasoned

VALUATION_DATE = date(2014, 2, 28)

# Table 1: standard CDS spreads observed in the market as of 28 Feb 2014.
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

# Placeholder discount curve: approximates the real Nelson-Siegel-implied rates for
# this period (beta0=0.0408, beta1=-0.0396, beta2=-0.0511, tau=1.614), used here only
# as a stand-in until real Bloomberg SOFR OIS quotes are available.
OIS_NODE_YEARS = [0.5, 1, 2, 3, 4, 5, 7, 10, 20, 30]
OIS_PLACEHOLDER_RATES = [0.0003, 0.0007, 0.0036, 0.0076, 0.0114, 0.0152, 0.0208, 0.0263, 0.0362, 0.0395]


def build_calibration_quotes(table=TABLE_1, recovery=STANDARD_RECOVERY):
    quotes = []
    for tenor, mat_date, spread_bp in table:
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
        quotes.append(CDSQuote(maturity_years, spread_bp / 10000.0, recovery,
                                payment_times, deltas))
    return quotes


NS_EFFECTIVE = date(2012, 5, 15)
NS_MATURITY = date(2042, 5, 15)
NS_SPREAD = 170 / 10000.0
NS_RECOVERY = 0.60
NS_FACE_VALUE = 100_000_000


def price_bespoke_contract(exact_accrual: bool = False, table=TABLE_1, calibration_recovery=STANDARD_RECOVERY,
                            ois_node_years=OIS_NODE_YEARS, ois_rates=OIS_PLACEHOLDER_RATES,
                            spread=NS_SPREAD, recovery=NS_RECOVERY, notional=NS_FACE_VALUE):
    """Prices the assignment's own bespoke seasoned contract -- fixed effective/
    maturity/valuation dates (2012-05-15 / 2042-05-15 / 2014-02-28), since those
    dates are this contract's identity, not a parameter (a different valuation
    date is what scripts/standard_contract.py is for). Calibration inputs
    (curves) and the contract's own economic terms (spread/recovery/notional)
    are parameters so the dashboard can feed in uploaded/edited market data.

    exact_accrual=False (default) deliberately reproduces the assignment's own
    approximated numbers; pass True to price the same contract dates/terms
    through the exact ISDA closed-form formulas instead (still under the
    assignment's own simplified weekend-only roll_date and /365.25 curve time --
    this flag only toggles the midpoint-approximation-vs-exact distinction, not
    the convention set).
    """
    discount_curve = bootstrap_ois_curve(ois_node_years, ois_rates)
    quotes = build_calibration_quotes(table, calibration_recovery)
    hazard_curve, histories = bootstrap_hazard_curve(
        quotes, discount_curve, x0=0.01, tol=1e-6,
        exact_accrual=exact_accrual,
    )

    all_dates = generate_payment_dates(NS_EFFECTIVE, NS_MATURITY)  # (unadjusted, adjusted) pairs
    # Past/future partition is about whether cash has actually moved yet, so it's
    # based on the adjusted (paid) date.
    past_dates = [pair for pair in all_dates if pair[1] <= VALUATION_DATE]
    future_dates = [pair for pair in all_dates if pair[1] > VALUATION_DATE]
    (t_minus1, _), (t0, _) = past_dates[-1], future_dates[0]

    ns_maturity_years = (NS_MATURITY - VALUATION_DATE).days / 365.25
    # Discounting time uses adjusted dates; accrual deltas use unadjusted dates.
    future_payment_times = [(adjusted - VALUATION_DATE).days / 365.25 for _, adjusted in future_dates]
    future_unadjusted = [unadjusted for unadjusted, _ in future_dates]
    future_payment_deltas = [act360(future_unadjusted[n - 1], future_unadjusted[n])
                             for n in range(1, len(future_unadjusted))]

    protection_pv = protection_leg_pv(ns_maturity_years, recovery, hazard_curve, discount_curve)
    rpv01_value = rpv01_seasoned(
        delta_prevpay_to_valuation=act360(t_minus1, VALUATION_DATE),
        delta_valuation_to_t0=act360(VALUATION_DATE, t0),
        delta_prevpay_to_t0=act360(t_minus1, t0),
        future_payment_times=future_payment_times,
        future_payment_deltas=future_payment_deltas,
        hazard_curve=hazard_curve, discount_curve=discount_curve,
        exact_accrual=exact_accrual,
    )
    results = mtm_seasoned_cds(protection_pv, rpv01_value, spread,
                                act360(t_minus1, VALUATION_DATE), notional)

    # Full schedule (past + future) for display -- each entry carries both the
    # unadjusted (nominal, accrual-basis) and adjusted (actual payment) date,
    # plus this period's discount factor/survival probability at the adjusted
    # (curve-time) date, for future periods (past ones have already settled, so
    # a "survival probability of a past date" isn't a meaningful curve query --
    # the curve is defined relative to the valuation date, not before it).
    schedule = []
    for i, (unadjusted, adjusted) in enumerate(all_dates):
        is_future = adjusted > VALUATION_DATE
        row = {
            "period": i + 1,
            "unadjusted": unadjusted, "adjusted": adjusted,
            "is_future": is_future,
        }
        if is_future:
            t = (adjusted - VALUATION_DATE).days / 365.25
            row["discount_factor"] = discount_curve.discount_factor(t)
            row["survival_probability"] = hazard_curve.survival_probability(t)
        schedule.append(row)

    return {
        "hazard_curve": hazard_curve,
        "discount_curve": discount_curve,
        "histories": histories,
        "tenors": [tenor for tenor, _, _ in table],
        "mtm": results,
        "schedule": schedule,
        "maturity_date": NS_MATURITY,
        "effective_date": NS_EFFECTIVE,
        "valuation_date": VALUATION_DATE,
        "coupon_bp": spread * 10000.0,
        "recovery": recovery,
        "notional": notional,
    }


def main():
    out = price_bespoke_contract(exact_accrual=False)
    hazard_curve, histories = out["hazard_curve"], out["histories"]

    print("Calibrated hazard curve:")
    for tenor, t, h_hist in zip(out["tenors"], hazard_curve.node_years, histories):
        h_final = h_hist[-1][1]
        print(f"  {tenor:>4s}  T={t:6.3f}y  h={h_final:.6f}  Q(T)={hazard_curve.survival_probability(t):.6f}"
              f"  iters={len(h_hist)}  residual={h_hist[-1][2]:.2e}")

    print("\nNew ISDA-style engine, non-standard seasoned CDS:")
    for k, v in out["mtm"].items():
        print(f"  {k:20s}: ${v:>18,.2f}")

    print("\nOriginal notebook (Nelson-Siegel + m=12 grid), for comparison:")
    print("  protection_leg      : $     16,599,748.00")
    print("  premium_leg         : $     24,138,762.00")
    print("  full_mtm            : $     -7,539,014.00")
    print("  accrued_interest    : $         51,944.00  (not reproduced: original rolled")
    print("                                              the prior coupon date for accrual too;")
    print("                                              this engine uses the unadjusted date)")
    print("  clean_mtm           : $     -7,590,958.00")


if __name__ == "__main__":
    main()
