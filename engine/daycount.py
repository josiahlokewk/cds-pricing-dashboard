from __future__ import annotations
from datetime import date, timedelta
from typing import Callable
from engine.calendar import following as _isda_standard_roll

# Date/schedule utilities: business-day rolling, day counts, and payment schedules.


def roll_date(d: date) -> date:
    """Plain Following, weekend-only roll (no holiday calendar), per assignment spec:
    Saturday moves to the following Monday, Sunday moves to the following Monday.
    (Despite the name, this is NOT Modified Following -- there is no backward-roll
    exception for month-end crossings. See engine/calendar.py's module docstring:
    this plain-Following/weekend-only shape happens to match what White's paper
    says the real ISDA CDS Standard Model normally uses, non-JPY.)
    """
    if d.weekday() == 5:  # Saturday
        return d + timedelta(days=2)
    if d.weekday() == 6:  # Sunday
        return d + timedelta(days=1)
    return d


def act360(d1: date, d2: date) -> float:
    """Actual/360 day count fraction between d1 and d2."""
    return (d2 - d1).days / 360.0


def act365f(d1: date, d2: date) -> float:
    """Actual/365 Fixed day count fraction between d1 and d2 -- divides by exactly
    365 regardless of leap years ("F" = Fixed, as opposed to Act/Act which adjusts
    for them). This is what the ISDA CDS Standard Model uses for curve times (both
    the discount and credit curves), as distinct from the /365.25 approximation
    used elsewhere in this codebase for the original assignment's contract, which
    was chosen only because the assignment's own spec was silent on the convention.
    """
    return (d2 - d1).days / 365.0


def add_months(d: date, months: int) -> date:
    """Add whole months to a date, clamping day-of-month when the target month is shorter."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1

    if month == 12:
        first_next_month = date(year + 1, 1, 1)
    else:
        first_next_month = date(year, month + 1, 1)

    last_day = (first_next_month - timedelta(days=1)).day
    day = min(d.day, last_day)
    return date(year, month, day)


def standard_maturity(trade_date: date, years: float,
                       roll_fn: Callable[[date], date] = _isda_standard_roll) -> date:
    """First standard IMM maturity date (20 Mar/Jun/Sep/Dec) at least `years` years
    after trade_date, rolled per roll_fn.

    Defaults to engine.calendar.following, the real ISDA CDS-standard convention
    (forward-only, weekend-only calendar -- see engine/calendar.py's module
    docstring). Pass roll_fn=roll_date for the assignment's own bespoke path (same
    dates either way, kept only so that path doesn't depend on engine/calendar.py),
    or roll_fn=engine.calendar.modified_following for side-by-side comparison
    against that convention.
    """
    standard_months = [3, 6, 9, 12]
    target_months = int(round(years * 12))
    target = add_months(trade_date, target_months)

    for year in [target.year, target.year + 1]:
        for month in standard_months:
            candidate = date(year, month, 20)
            if candidate >= target:
                return roll_fn(candidate)
    raise ValueError("Could not find a standard maturity date for " + str(trade_date))


def most_recent_imm_date(d: date) -> date:
    """Most recent unadjusted quarterly IMM roll date (20 Mar/Jun/Sep/Dec) on or
    before d -- the date the currently-running on-the-run contract's accrual
    started from.
    """
    for year in (d.year, d.year - 1):
        for month in (12, 9, 6, 3):
            candidate = date(year, month, 20)
            if candidate <= d:
                return candidate
    raise ValueError("Could not find an IMM date on or before " + str(d))


def snac_maturity(trade_date: date, years: float,
                   roll_fn: Callable[[date], date] = _isda_standard_roll) -> date:
    """Real-market (SNAC / ISDA Big Bang) standard maturity date.

    Anchored to the *current* quarterly IMM roll date (the most recent 20 Mar/
    Jun/Sep/Dec on or before trade_date), with the tenor added from THAT anchor
    -- not to standard_maturity()'s "first standard date >= trade_date + years"
    rule above, which is the CDS coursework assignment's own stated definition
    (assignment1.pdf, page 5) and is deliberately kept as-is for that path.

    The two disagree whenever trade_date isn't itself an IMM date, which is
    most of the time. Verified against a real Bloomberg CDSW screenshot for a
    5Y Apple CDS traded 2026-09-01: Bloomberg's own "1st Accr Start" is
    2026-06-22 (2026-06-20 IMM date, weekend-rolled) and its maturity is
    2031-06-20 -- i.e. anchored to the most recent IMM date on or before the
    trade date. standard_maturity() gives 2031-09-22 for the same inputs, a
    full quarter late -- confirmed (by direct A/B pricing comparison) to be the
    dominant source of a ~$13k/0.13-point discrepancy against that Bloomberg
    screen, not the protectStart half-day flag.
    """
    anchor = most_recent_imm_date(trade_date)
    target_months = int(round(years * 12))
    return roll_fn(add_months(anchor, target_months))


def standard_payment_dates(maturity_date: date, valuation_date: date,
                            roll_fn: Callable[[date], date] = _isda_standard_roll) -> list[tuple[date, date]]:
    """Quarterly standard IMM payment dates (20 Mar/Jun/Sep/Dec) strictly after
    valuation_date and up to and including maturity_date.

    Returns (unadjusted, adjusted) pairs, not bare dates: the unadjusted (nominal,
    "on-paper") date is what the accrual/day-count fraction for that period should
    be measured against, so a coupon isn't inflated or shrunk just because its
    nominal date happens to land on a weekend/holiday. The adjusted (rolled) date
    is when the cash actually moves, i.e. the date to use for discounting/payment
    timing. See engine/calendar.py's module docstring for why the two are kept
    separate. roll_fn defaults per standard_maturity's docstring above.
    """
    dates = []
    y = valuation_date.year
    while y <= maturity_date.year:
        for month, day in [(3, 20), (6, 20), (9, 20), (12, 20)]:
            unadjusted = date(y, month, day)
            adjusted = roll_fn(unadjusted)
            if valuation_date < adjusted <= maturity_date:
                dates.append((unadjusted, adjusted))
        y += 1
    return sorted(dates, key=lambda pair: pair[1])


def generate_payment_dates(effective_date: date, maturity_date: date, months_per_payment: int = 3,
                            roll_fn: Callable[[date], date] = _isda_standard_roll) -> list[tuple[date, date]]:
    """Off-cycle payment schedule: every `months_per_payment` months starting from
    effective_date through maturity_date. Used for bespoke (non-IMM-dated)
    contracts.

    Returns (unadjusted, adjusted) pairs -- see standard_payment_dates' docstring
    for why both are needed. roll_fn defaults per standard_maturity's docstring.
    """
    dates = []
    d = effective_date
    while d <= maturity_date:
        dates.append((d, roll_fn(d)))
        d = add_months(d, months_per_payment)
    return dates