from datetime import date

from engine.calendar import (
    add_business_days,
    following,
    is_business_day,
    modified_following,
    no_extra_holidays,
    sifma_holidays,
    us_federal_holidays,
)


def test_fixed_date_holiday_on_saturday_is_not_shifted_to_friday():
    # Independence Day 2015 fell on a Saturday. Confirmed against the Federal
    # Reserve's own published holiday schedule (frbservices.org): Reserve Banks
    # and Branches are open the preceding Friday for a Saturday holiday -- only
    # the Board of Governors closes, which doesn't affect settlement business
    # days. So Friday 3 July 2015 is NOT a holiday; the Saturday date itself is
    # left unshifted (already excluded by the weekend check on its own).
    holidays = us_federal_holidays(2015)
    assert date(2015, 7, 3) not in holidays
    assert date(2015, 7, 4) in holidays


def test_fixed_date_holiday_observed_on_sunday_shifts_to_monday():
    # Christmas 2016 fell on a Sunday -> observed Monday 26 Dec 2016.
    holidays = us_federal_holidays(2016)
    assert date(2016, 12, 26) in holidays
    assert date(2016, 12, 25) not in holidays


def test_floating_holidays_known_dates():
    holidays_2014 = us_federal_holidays(2014)
    assert date(2014, 1, 20) in holidays_2014    # MLK Day: 3rd Monday of Jan
    assert date(2014, 5, 26) in holidays_2014    # Memorial Day: last Monday of May
    assert date(2014, 11, 27) in holidays_2014   # Thanksgiving: 4th Thursday of Nov


def test_juneteenth_only_from_2021():
    assert date(2020, 6, 19) not in us_federal_holidays(2020)
    # Juneteenth 2021 fell on a Saturday -> Reserve Banks open Friday 18 June
    # 2021 (not a holiday); the Saturday itself, 19 June, is left unshifted.
    assert date(2021, 6, 18) not in us_federal_holidays(2021)
    assert date(2021, 6, 19) in us_federal_holidays(2021)


def test_good_friday_is_a_business_day_under_both_calendars():
    # Checked directly against SIFMA's own published 2026 schedule: Good Friday is
    # listed under "early close" (a shortened trading session), not under "full
    # market closures" -- so it is NOT a holiday for business-day/settlement
    # purposes under either calendar, despite SIFMA recommending shorter hours
    # that day. (An earlier version of this test wrongly asserted the opposite.)
    good_friday_2014 = date(2014, 4, 18)
    assert good_friday_2014 not in us_federal_holidays(2014)
    assert good_friday_2014 not in sifma_holidays(2014)
    assert is_business_day(good_friday_2014)


def test_modified_following_plain_weekend_roll_within_month():
    # A Saturday mid-month with no holiday nearby just rolls to the following
    # Monday, same as the assignment's simplified convention.
    assert modified_following(date(2014, 3, 22)) == date(2014, 3, 24)


def test_modified_following_rolls_backward_when_forward_crosses_month_end():
    # 31 Dec 2016 is a Saturday. Forward would land on 3 Jan 2017 (1 Jan is New
    # Year's Day, a Sunday observed Monday 2 Jan, so both 1 and 2 Jan are out) --
    # crossing into January, so Modified Following rolls backward instead, to the
    # last good business day in December: Friday 30 Dec 2016.
    assert modified_following(date(2016, 12, 31)) == date(2016, 12, 30)


def test_modified_following_leaves_a_good_business_day_unchanged():
    assert modified_following(date(2014, 3, 20)) == date(2014, 3, 20)


def test_modified_following_can_be_run_against_the_plain_federal_reserve_calendar():
    # us_federal_holidays and sifma_holidays are currently identical (see
    # sifma_holidays' docstring) -- both accept the holiday_fn parameter and both
    # leave Good Friday, a business day under either, unchanged.
    assert modified_following(date(2014, 4, 18), holiday_fn=us_federal_holidays) == date(2014, 4, 18)
    assert modified_following(date(2014, 4, 18)) == date(2014, 4, 18)


def test_add_business_days_skips_weekend():
    # Friday 28 Feb 2014 + 3 business days: Mon 3 Mar, Tue 4 Mar, Wed 5 Mar --
    # the weekend in between is skipped, not counted.
    assert add_business_days(date(2014, 2, 28), 3) == date(2014, 3, 5)


def test_add_business_days_default_calendar_does_not_skip_holidays():
    # Default is now no_extra_holidays (weekend-only), per White's paper: Wed 24
    # Dec 2014 + 3 business days counts Thu 25 Dec (Christmas) as a business day
    # since the default calendar has no holidays beyond weekends -- Thu=1, Fri=2,
    # Sat/Sun skipped, Mon 29 Dec=3.
    assert add_business_days(date(2014, 12, 24), 3) == date(2014, 12, 29)


def test_add_business_days_skips_weekend_and_holiday_when_calendar_passed_explicitly():
    # Same dates as above, but with sifma_holidays passed explicitly: Thu 25 Dec
    # is Christmas (skipped), Fri 26 Dec counts as 1, Sat/Sun 27-28 Dec skipped,
    # Mon 29 Dec counts as 2, Tue 30 Dec counts as 3.
    assert add_business_days(date(2014, 12, 24), 3, holiday_fn=sifma_holidays) == date(2014, 12, 30)


def test_following_rolls_forward_only_even_across_month_end():
    # 31 Dec 2016 is a Saturday. Under plain Following (weekend-only calendar),
    # there is no backward-roll exception: it just rolls forward to the next
    # good business day, Mon 2 Jan 2017 -- crossing into January is fine.
    assert following(date(2016, 12, 31)) == date(2017, 1, 2)


def test_following_leaves_a_good_business_day_unchanged():
    assert following(date(2014, 3, 20)) == date(2014, 3, 20)


def test_following_plain_weekend_roll():
    assert following(date(2014, 3, 22)) == date(2014, 3, 24)  # Saturday -> Monday


def test_no_extra_holidays_is_always_empty():
    assert no_extra_holidays(2014) == set()
    assert no_extra_holidays(2026) == set()
