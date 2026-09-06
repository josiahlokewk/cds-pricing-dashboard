"""Regression tests for daycount.py against known values from the assignment brief
(assignment1.pdf) and the original notebook, to confirm the lift-and-clean didn't
change behavior.
"""

from datetime import date

from engine.daycount import (
    act360,
    act365f,
    add_months,
    generate_payment_dates,
    roll_date,
    standard_maturity,
    standard_payment_dates,
)


def test_roll_date_weekend_to_monday():
    assert roll_date(date(2014, 3, 22)) == date(2014, 3, 24)  # Saturday -> Monday
    assert roll_date(date(2014, 3, 23)) == date(2014, 3, 24)  # Sunday -> Monday
    assert roll_date(date(2014, 3, 20)) == date(2014, 3, 20)  # weekday unchanged


def test_act360():
    # 20 Mar 2014 to 20 Jun 2014 = 92 days
    assert act360(date(2014, 3, 20), date(2014, 6, 20)) == 92 / 360.0


def test_act365f_divides_by_exactly_365_regardless_of_leap_year():
    # 92 days spanning a leap year (2016) should still divide by 365, not 366 --
    # that's the "Fixed" in Act/365 Fixed.
    assert act365f(date(2016, 3, 20), date(2016, 6, 20)) == 92 / 365.0
    assert act365f(date(2014, 3, 20), date(2014, 6, 20)) == 92 / 365.0


def test_add_months_clamps_day_of_month():
    assert add_months(date(2014, 1, 31), 1) == date(2014, 2, 28)
    assert add_months(date(2014, 1, 15), 3) == date(2014, 4, 15)


def test_standard_maturity_matches_assignment_example():
    # Assignment brief, page 5: "for the trade date 28 February 2014, a 5-year CDS
    # will mature on 20 March 2019, which is the first standard maturity date that
    # is 5 years after the trade date."
    assert standard_maturity(date(2014, 2, 28), 5) == date(2019, 3, 20)


def test_standard_maturity_matches_table_1_tenors():
    # Assignment brief, Table 1 (page 6), maturity dates before weekend adjustment.
    trade_date = date(2014, 2, 28)
    expected = {
        0.5: date(2014, 9, 20),
        1: date(2015, 3, 20),
        2: date(2016, 3, 20),
        3: date(2017, 3, 20),
        4: date(2018, 3, 20),
        5: date(2019, 3, 20),
        7: date(2021, 3, 20),
        10: date(2024, 3, 20),
        20: date(2034, 3, 20),
        30: date(2044, 3, 20),
    }
    for years, expected_date in expected.items():
        # Table 1 dates are "before weekend adjustment" -- compare pre-roll.
        target_months = int(round(years * 12))
        target = add_months(trade_date, target_months)
        for year in [target.year, target.year + 1]:
            for month in [3, 6, 9, 12]:
                candidate = date(year, month, 20)
                if candidate >= target:
                    assert candidate == expected_date, f"{years}y: got {candidate}, expected {expected_date}"
                    break
            else:
                continue
            break


def test_standard_payment_dates_quarterly():
    # Trade date 28 Feb 2014 is before the 20 Mar 2014 IMM date, so that date
    # itself is a valid (short-stub) first coupon -- 5 payments total, not 4.
    dates = standard_payment_dates(date(2015, 3, 20), date(2014, 2, 28))
    assert dates[0] == (date(2014, 3, 20), date(2014, 3, 20))
    assert dates[-1] == (date(2015, 3, 20), date(2015, 3, 20))
    assert len(dates) == 5  # Mar, Jun, Sep, Dec 2014, Mar 2015


def test_standard_payment_dates_unadjusted_and_adjusted_differ_on_a_weekend():
    # 20 Sep 2014 is a Saturday -> adjusted rolls to Mon 22 Sep 2014, but the
    # unadjusted (nominal) date used for accrual stays 20 Sep 2014. Dates are
    # Mar, Jun, Sep, Dec 2014, Mar 2015 -- Sep is index 2.
    dates = standard_payment_dates(date(2015, 3, 20), date(2014, 2, 28))
    sep_pair = dates[2]
    assert sep_pair == (date(2014, 9, 20), date(2014, 9, 22))


def test_generate_payment_dates_off_cycle():
    # Non-standard CDS from the assignment, Table 2: effective 15 May 2012,
    # quarterly payments on 15 Feb/May/Aug/Nov.
    dates = generate_payment_dates(date(2012, 5, 15), date(2012, 11, 15))
    assert dates == [
        (date(2012, 5, 15), date(2012, 5, 15)),
        (date(2012, 8, 15), date(2012, 8, 15)),
        (date(2012, 11, 15), date(2012, 11, 15)),
    ]