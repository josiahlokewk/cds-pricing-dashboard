from __future__ import annotations
from datetime import date, timedelta
from typing import Callable, Set

# Business-day conventions and holiday calendars.
#
# CORRECTION (superseding this module's original design): White's OpenGamma paper
# on the ISDA CDS Standard Model, Appendix A ("ISDA Model Dates"), states the
# *normal* CDS convention directly:
#   "Business-day Adjustment: ...This is normally following, i.e. move forward
#    in steps of one day until a good business day is found."
#   "Calendar: ...Except for CDS denominated in JPY (which use the Tokyo holiday
#    calendar), normally a weekend only calendar is used."
# That is plain Following (forward-only, no month-crossing exception) against a
# weekend-only calendar -- NOT Modified Following, and NOT a real bank-holiday
# calendar. This module originally defaulted to `modified_following` + SIFMA,
# built on an unverified assumption that CDS follows the same convention as
# bonds/swaps. It doesn't, per this specific source. `following()` and
# `no_extra_holidays()` below are now the CDS-standard default.
#
# `modified_following` + `us_federal_holidays`/`sifma_holidays` are kept: they
# are real, correctly-implemented, standard conventions in their own right (used
# for other instrument types, e.g. interest-rate swaps), and useful here for
# side-by-side comparison against the CDS-standard path. Just don't reach for
# them as "the CDS convention" without checking a specific contract's term sheet
# or an actual Bloomberg screen -- ISDA's 2021 Definitions name multiple distinct
# New York business-day conventions (New York City Business Days, U.S.
# Government Securities Business Days, New York Fed Business Days), and this
# module cannot capture ad-hoc one-off closures (e.g. the 5 Dec 2018 National
# Day of Mourning) either way -- those only exist in vendor-maintained calendar
# data and would need to come from Bloomberg directly.
#
# Also separate from daycount.py's roll_date, which implements the assignment's
# own simplified convention for the bespoke seasoned contract (see that
# function's docstring -- it turns out to already be plain Following, weekend-
# only, i.e. the same shape as the real CDS-standard default here, by
# coincidence of the assignment's own choice rather than by design).


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """The n-th occurrence (1-indexed) of `weekday` (Mon=0..Sun=6) in the given
    month/year.
    """
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    d += timedelta(days=offset + 7 * (n - 1))
    return d


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    if month == 12:
        d = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)
    offset = (d.weekday() - weekday) % 7
    return d - timedelta(days=offset)


def _observed(d: date) -> date:
    """How the Federal Reserve itself observes a fixed-date holiday landing on a
    weekend -- confirmed directly against the Federal Reserve's own published
    holiday schedule (frbservices.org): "When a holiday falls on Saturday,
    Federal Reserve Banks and Branches will be open the preceding Friday...
    When a holiday falls on Sunday, [they] will be closed the following
    Monday." (Only the Board of Governors closes that Friday, which doesn't
    affect settlement business days.) So: Saturday -> no shift, no extra
    closure added (the Saturday itself is already excluded by the weekend
    check); Sunday -> observed the following Monday.

    This is NOT the same as the OPM/federal-government-office rule (Saturday ->
    observed Friday) that federal employees get -- an earlier version of this
    function implemented that rule instead, despite this module claiming to be
    the Federal Reserve's own schedule.
    """
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def us_federal_holidays(year: int) -> Set[date]:
    """US Federal Reserve holiday schedule for a given year. Juneteenth is only a
    federal holiday from 2021 onward.
    """
    holidays = {
        _observed(date(year, 1, 1)),                          # New Year's Day
        _nth_weekday_of_month(year, 1, 0, 3),                  # MLK Day: 3rd Monday of Jan
        _nth_weekday_of_month(year, 2, 0, 3),                  # Presidents Day: 3rd Monday of Feb
        _last_weekday_of_month(year, 5, 0),                    # Memorial Day: last Monday of May
        _observed(date(year, 7, 4)),                           # Independence Day
        _nth_weekday_of_month(year, 9, 0, 1),                  # Labor Day: 1st Monday of Sep
        _nth_weekday_of_month(year, 10, 0, 2),                 # Columbus Day: 2nd Monday of Oct
        _observed(date(year, 11, 11)),                         # Veterans Day
        _nth_weekday_of_month(year, 11, 3, 4),                 # Thanksgiving: 4th Thursday of Nov
        _observed(date(year, 12, 25)),                         # Christmas
    }
    if year >= 2021:
        holidays.add(_observed(date(year, 6, 19)))              # Juneteenth
    return holidays


def no_extra_holidays(year: int) -> Set[date]:
    """The 'weekend only' calendar: no holidays beyond Saturday/Sunday. Per White's
    paper, this is what the ISDA CDS Standard Model normally uses (non-JPY), so
    this is the default calendar for `following` and `add_business_days`.
    """
    return set()


def sifma_holidays(year: int) -> Set[date]:
    """SIFMA's full-market-closure schedule. Checked directly against SIFMA's own
    published 2026 schedule: their full closures (New Year's, MLK, Presidents Day,
    Memorial Day, Juneteenth, Independence Day, Labor Day, Columbus Day, Veterans
    Day, Thanksgiving, Christmas) are identical to the Federal Reserve list.

    Good Friday is NOT included here. An earlier version of this module added it,
    on the mistaken assumption that "SIFMA recommends a market close on Good
    Friday" meant a full closure -- SIFMA's own schedule lists it under "early
    close" (e.g. 12:00pm ET), a shortened trading session, not a closure. An
    early-close day is still a business day: settlement can still occur on it, so
    it must not be excluded from business-day rolling. Trading-hours information
    (full close vs. early close) is a different concept from the settlement-date
    business-day calendar this module provides, and is out of scope here.
    """
    return set(us_federal_holidays(year))


def is_business_day(d: date, holiday_fn: Callable[[int], Set[date]] = no_extra_holidays,
                     holiday_cache: dict = None) -> bool:
    if d.weekday() >= 5:
        return False
    if holiday_cache is not None and d.year in holiday_cache:
        holidays = holiday_cache[d.year]
    else:
        holidays = holiday_fn(d.year)
        if holiday_cache is not None:
            holiday_cache[d.year] = holidays
    return d not in holidays


def add_business_days(d: date, n: int, holiday_fn: Callable[[int], Set[date]] = no_extra_holidays) -> date:
    """Step forward n business days from d, skipping weekends and holidays per
    holiday_fn. Used for the CDS cash-settle date (standard market convention:
    T+3 business days after the trade date). Defaults to weekend-only, per
    White's paper statement that non-JPY CDS normally use a weekend-only
    calendar -- pass holiday_fn=sifma_holidays (or another calendar) explicitly
    if a specific contract/Bloomberg screen needs one.
    """
    cache: dict = {}
    result = d
    counted = 0
    while counted < n:
        result += timedelta(days=1)
        if is_business_day(result, holiday_fn, cache):
            counted += 1
    return result


def following(d: date, holiday_fn: Callable[[int], Set[date]] = no_extra_holidays) -> date:
    """Plain Following convention: roll forward, one day at a time, until a good
    business day is found. No month-crossing exception. Per White's paper, this
    -- against a weekend-only calendar -- is what the ISDA CDS Standard Model
    normally uses (non-JPY); this is the CDS-standard default in this module.
    """
    cache: dict = {}
    result = d
    while not is_business_day(result, holiday_fn, cache):
        result += timedelta(days=1)
    return result


def modified_following(d: date, holiday_fn: Callable[[int], Set[date]] = sifma_holidays) -> date:
    """Full Modified Following convention against the given holiday calendar
    (SIFMA by default): roll forward to the next good business day; if that
    crosses into the next month, roll backward from the original date instead.

    NOT the CDS-standard default (see module docstring) -- kept for comparison
    and for instrument types (e.g. interest-rate swaps) that do use it.
    """
    cache: dict = {}
    if is_business_day(d, holiday_fn, cache):
        return d

    forward = d
    while not is_business_day(forward, holiday_fn, cache):
        forward += timedelta(days=1)

    if forward.month != d.month:
        backward = d
        while not is_business_day(backward, holiday_fn, cache):
            backward -= timedelta(days=1)
        return backward

    return forward
