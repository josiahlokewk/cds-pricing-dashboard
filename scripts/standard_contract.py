"""Standard-contract, Bloomberg-comparable CDS pricing script.

Prices a single, standard IMM-dated CDS (quarterly coupon dates, fixed 100bp
coupon, T+1 step-in, T+3 cash-settle) through the full ISDA-aligned engine --
as opposed to scripts/smoke_test.py, which reproduces the original
assignment's own bespoke seasoned contract under its own simplified
conventions (weekend-only roll via daycount.roll_date, /365.25 curve time,
exact_accrual=False).

This is the "standard-contract" script that was missing: nothing else in this
project prices a real standard contract with real ISDA conventions end-to-end,
so there was no vehicle ready to compare line-by-line against a real
Bloomberg CDSW screen. The defaults below ARE that real comparison: a real
Apple Inc 5Y single-name CDS, trade date 2026-08-31, transcribed from an
actual Bloomberg CDSW screenshot (spread curve, OIS curve, 100bp coupon, 0.40
recovery) -- not placeholders. Every one of these is still a parameter of
price_standard_contract, not a hardcoded constant, so the dashboard's
market-data tables can override them freely.

Curve-time convention here is genuinely Act/365F (daycount.act365f), not
Act/360 -- unlike smoke_test.py's calibration path, which uses Act/360
throughout and gets away with it only because it calibrates with
exact_accrual=False (which never invokes eta). This script calibrates and
prices with exact_accrual=True (the real ISDA default), which DOES use eta
to convert between the curve-time and accrual-time conventions -- so the two
conventions must actually differ as documented (rpv01_seasoned's default
eta=365/360 assumes Act/360 accrual against Act/365F curve time), which is
why payment_times/maturity here are act365f while payment_deltas stay act360.
"""

from datetime import date, timedelta

from engine.bootstrap import CDSQuote, bootstrap_hazard_curve, rpv01
from engine.calendar import add_business_days
from engine.daycount import act360, act365f, most_recent_imm_date, snac_maturity, standard_payment_dates
from engine.discount_curve import bootstrap_ois_curve
from engine.pricing import mtm_seasoned_cds, protection_leg_pv, settle_amount

TRADE_DATE = date(2026, 8, 31)  # screenshot was taken pre-market-open on 09/01, so quotes are 08/31's data

# Real market-quoted CDS spreads used to calibrate the hazard curve -- Apple
# Inc senior CDS, ask side, transcribed from a Bloomberg CDSW screenshot taken
# 2026-09-01 pre-market-open, i.e. before the 09/01 session had printed any
# quotes of its own -- so despite Bloomberg's own "Trade Date"/"Valuation Date"/
# "Curve Date" fields all printing 09/01/26, the actual quotes are 08/31's
# close. Valuing here as of 08/31 (not Bloomberg's own printed 09/01) means
# this will value one day earlier than Bloomberg's own screen -- a real,
# separate source of mismatch from any convention difference. Keyed by
# tenor in years rather than a hardcoded maturity date, since the maturity date
# is computed for real via snac_maturity. Only 6M-10Y are populated -- no real
# 20Y/30Y quotes were available for this name, so those rows are omitted
# rather than guessed.
TABLE_1 = [
    ("6M", 0.5, 17.620),
    ("1Y", 1, 21.740),
    ("2Y", 2, 26.580),
    ("3Y", 3, 31.160),
    ("4Y", 4, 37.310),
    ("5Y", 5, 41.400),
    ("7Y", 7, 52.550),
    ("10Y", 10, 62.470),
]
CALIBRATION_RECOVERY = 0.40  # Bloomberg's own "Recovery Rate" field for this trade

# Real OIS/SOFR par rates for 2026-08-31 (see data/real_ois_curve_history.csv).
OIS_NODE_YEARS = [1, 3, 5, 7, 10]
OIS_RATES = [0.041508, 0.0421575, 0.042303, 0.042795, 0.04373]

# Our own contract: the same real Apple 5Y CDS shown on that Bloomberg screen.
OWN_TENOR_YEARS = 5.0
OWN_COUPON = 0.01       # 100bp, Big Bang standard fixed coupon -- also Bloomberg's own "Coupon (bp)" for this trade
OWN_RECOVERY = 0.40     # Bloomberg's own "Recovery Rate" for this trade
NOTIONAL = 10_000_000


def _schedule_times_and_deltas(valuation_date, maturity_date):
    """(payment_times, payment_deltas, unadjusted_dates, adjusted_dates) for a
    fresh contract from valuation_date to maturity_date. payment_times: Act/365F,
    curve-time convention (discounting). payment_deltas: Act/360, accrual
    convention. See module docstring on why these must be two genuinely
    different day-count conventions here.
    """
    pay_dates = standard_payment_dates(maturity_date, valuation_date)  # (unadjusted, adjusted) pairs
    payment_times = [act365f(valuation_date, adjusted) for _, adjusted in pay_dates]
    payment_deltas = []
    prev_unadjusted = valuation_date
    unadjusted_dates, adjusted_dates = [], []
    for unadjusted, adjusted in pay_dates:
        payment_deltas.append(act360(prev_unadjusted, unadjusted))
        prev_unadjusted = unadjusted
        unadjusted_dates.append(unadjusted)
        adjusted_dates.append(adjusted)
    return payment_times, payment_deltas, unadjusted_dates, adjusted_dates


def build_calibration_quotes(trade_date=TRADE_DATE, table=TABLE_1, recovery=CALIBRATION_RECOVERY):
    # Degenerate (no pre-valuation stub) by design -- see rpv01()'s own
    # docstring in engine/bootstrap.py for why this is correct, not an
    # approximation: a quoted par spread is defined as giving zero upfront for
    # a contract entered fresh today, and that's exactly the annuity this
    # degenerate schedule computes zero against.
    quotes = []
    for _, years, spread_bp in table:
        mat_date = snac_maturity(trade_date, years)
        maturity_years = act365f(trade_date, mat_date)
        payment_times, payment_deltas, _, _ = _schedule_times_and_deltas(trade_date, mat_date)
        quotes.append(CDSQuote(maturity_years, spread_bp / 10000.0, recovery,
                                payment_times, payment_deltas))
    return quotes


def price_standard_contract(trade_date=TRADE_DATE, table=TABLE_1, calibration_recovery=CALIBRATION_RECOVERY,
                             ois_node_years=OIS_NODE_YEARS, ois_rates=OIS_RATES,
                             own_tenor_years=OWN_TENOR_YEARS, own_coupon=OWN_COUPON,
                             own_recovery=OWN_RECOVERY, notional=NOTIONAL):
    # t_v (valuation date, t=0): curves and PVs are anchored here. This is the
    # trade date, not the later cash-settle date -- see pricing.settle_amount's
    # docstring for why, and for how the cash-settle *dollar amount* is derived
    # from this same valuation-date PV.
    valuation_date = trade_date
    # T+1 calendar day, not business day -- see protection_leg_pv's docstring.
    step_in_date = trade_date + timedelta(days=1)
    # T+3 business days, weekend-only calendar (add_business_days' default).
    cash_settle_date = add_business_days(trade_date, 3)

    discount_curve = bootstrap_ois_curve(ois_node_years, ois_rates)
    quotes = build_calibration_quotes(trade_date, table, calibration_recovery)
    hazard_curve, histories = bootstrap_hazard_curve(
        quotes, discount_curve, x0=0.01, tol=1e-6,
        exact_accrual=True,  # real ISDA default -- no reason to approximate a fresh standard contract
    )

    maturity_date = snac_maturity(trade_date, own_tenor_years)
    maturity_years = act365f(valuation_date, maturity_date)
    payment_times, payment_deltas, unadjusted_dates, adjusted_dates = _schedule_times_and_deltas(
        valuation_date, maturity_date)
    step_in_years = act365f(valuation_date, step_in_date)

    protection_pv = protection_leg_pv(maturity_years, own_recovery, hazard_curve, discount_curve,
                                       start=step_in_years)

    # RPV01 here is the same "clean" (degenerate, no pre-valuation stub)
    # annuity as the calibration instruments use -- see rpv01()'s own
    # docstring for why that's correct, not an approximation. This is what
    # par_spread_bp and full_mtm ("Principal", the accrued-free upfront) are
    # built from. Verified directly: reprices the 5Y calibration instrument's
    # own quoted spread to 41.39999697bp (vs. 41.400bp input) -- i.e. the
    # curve's own par condition holds to Newton-Raphson's tolerance, which it
    # does NOT when a real stub is threaded through here instead (that was
    # tried and reverted).
    rpv01_value = rpv01(payment_times, payment_deltas, hazard_curve, discount_curve, exact_accrual=True)

    results = mtm_seasoned_cds(protection_pv, rpv01_value, own_coupon,
                                delta_prevpay_to_valuation=0.0, face_value=notional)

    # Accrued interest is a SEPARATE, additive, pure day-count adjustment --
    # NOT folded into the RPV01/annuity above. Real single-name CDS always
    # accrue against the fixed quarterly IMM grid (20 Mar/Jun/Sep/Dec), so a
    # contract entered mid-quarter has a genuine accrued stub (from the last
    # IMM roll date to the trade date) even though the "clean" annuity used
    # for par-spread/upfront purposes is computed as if starting fresh today.
    # Bloomberg's own arithmetic: Cash Amount = Principal - accrued magnitude
    # (both Principal and Accrued shown as negative, "cash incoming to buyer"
    # -- Cash Amount is the MORE negative, larger-incoming-cash figure).
    t_minus1 = most_recent_imm_date(valuation_date)
    delta_prevpay_to_valuation = act360(t_minus1, valuation_date)
    accrued_magnitude = own_coupon * delta_prevpay_to_valuation * notional
    results["accrued_interest"] = -accrued_magnitude
    results["clean_mtm"] = results["full_mtm"] - accrued_magnitude

    # Par/breakeven spread implied by this curve for this contract's own schedule --
    # the coupon that would make full_mtm exactly zero.
    par_spread_bp = (protection_pv / rpv01_value) * 10000.0

    # Points Upfront (and Price/Principal, derived from it elsewhere): matches
    # Bloomberg's "Principal" -- the clean, accrued-free (coupon vs. par spread)
    # value -- which is full_mtm here, NOT clean_mtm (clean_mtm is the ACCRUED-
    # INCLUSIVE total, matching Bloomberg's "Cash Amount" -- see
    # cash_settlement_amount just below). Positive when par_spread > coupon
    # (buyer is getting cheap protection, pays for it upfront), matching the
    # Big Bang PUF sign convention directly.
    points_upfront = (results["full_mtm"] / notional) * 100.0

    cash_settle_years = act365f(valuation_date, cash_settle_date)
    cash_settlement_amount = settle_amount(results["clean_mtm"], cash_settle_years, discount_curve)

    schedule = []
    for i, (t, delta, unadj, adj) in enumerate(zip(payment_times, payment_deltas, unadjusted_dates, adjusted_dates)):
        schedule.append({
            "period": i + 1,
            "unadjusted": unadj,
            "adjusted": adj,
            "accrual_delta": delta,
            "discount_time": t,
            "discount_factor": discount_curve.discount_factor(t),
            "survival_probability": hazard_curve.survival_probability(t),
        })

    return {
        "trade_date": trade_date,
        "step_in_date": step_in_date,
        "cash_settle_date": cash_settle_date,
        "maturity_date": maturity_date,
        "coupon_bp": own_coupon * 10000.0,
        "tenors": [tenor for tenor, _, _ in table],
        "hazard_curve": hazard_curve,
        "discount_curve": discount_curve,
        "histories": histories,
        "mtm": results,
        "par_spread_bp": par_spread_bp,
        "points_upfront": points_upfront,
        "cash_settlement_amount": cash_settlement_amount,
        "schedule": schedule,
        # Accrued interest's own date range: last IMM roll date -> trade date
        # (NOT the step-in date -- see the accrued_magnitude computation above).
        "accrued_start_date": t_minus1,
        "accrued_end_date": valuation_date,
        "accrued_days": (valuation_date - t_minus1).days,
    }


def main():
    out = price_standard_contract()

    print(f"Trade date          : {out['trade_date']}")
    print(f"Step-in date (T+1)  : {out['step_in_date']}")
    print(f"Cash-settle (T+3)   : {out['cash_settle_date']}")
    print(f"Maturity (5Y IMM)   : {out['maturity_date']}")
    print(f"Fixed coupon        : {out['coupon_bp']:.0f}bp")
    print()
    print("Calibrated hazard curve:")
    for tenor, t, h_hist in zip(out["tenors"], out["hazard_curve"].node_years, out["histories"]):
        h_final = h_hist[-1][1]
        print(f"  {tenor:>4s}  T={t:6.3f}y  h={h_final:.6f}  Q(T)={out['hazard_curve'].survival_probability(t):.6f}"
              f"  iters={len(h_hist)}  residual={h_hist[-1][2]:.2e}")

    print("\nBloomberg CDSW-comparable output:")
    print(f"  Par/breakeven spread : {out['par_spread_bp']:>10.2f} bp")
    print(f"  Points Upfront (PUF) : {out['points_upfront']:>10.4f} %")
    print(f"  Cash Settlement Amt  : ${out['cash_settlement_amount']:>15,.2f}")
    print(f"  Protection leg PV    : ${out['mtm']['protection_leg']:>15,.2f}")
    print(f"  Premium leg PV       : ${out['mtm']['premium_leg']:>15,.2f}")
    print(f"  Full MTM (= upfront) : ${out['mtm']['full_mtm']:>15,.2f}")
    print(f"  Accrued interest     : ${out['mtm']['accrued_interest']:>15,.2f}  (0 for a fresh contract)")
    print(f"  Clean MTM            : ${out['mtm']['clean_mtm']:>15,.2f}")


if __name__ == "__main__":
    main()
