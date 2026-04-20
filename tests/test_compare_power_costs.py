"""Unit tests for compare_power_costs rate and peak-hour logic."""

import re
from datetime import date, datetime, timedelta

import pytest

import compare_power_costs
from compare_power_costs import (
    RATE_SCHEDULES,
    RateSchedule,
    RockyMountainPowerHolidays,
    calculate_block_cost,
    get_rate_schedule,
    get_tou_rates,
    is_peak_hour,
)
from current_peak_status import find_next_peak_change

# Non-holiday Tuesdays chosen to land unambiguously inside each rate schedule. The year
# in the name is the schedule epoch — 2025-* dates resolve to the Apr 25, 2025 schedule
# and 2026-* dates resolve to the Dec 1, 2025 schedule.
APR2025_WINTER_WEEKDAY: datetime = datetime(
    2025, 1, 21, 12, 0
)  # Tue, winter -> Apr 2025 schedule (via fallback)
APR2025_SUMMER_WEEKDAY: datetime = datetime(
    2025, 7, 15, 12, 0
)  # Tue, summer -> Apr 2025 schedule
DEC2025_WINTER_WEEKDAY: datetime = datetime(
    2026, 1, 20, 12, 0
)  # Tue, winter -> Dec 2025 schedule
DEC2025_SUMMER_WEEKDAY: datetime = datetime(
    2026, 7, 14, 12, 0
)  # Tue, summer -> Dec 2025 schedule


@pytest.fixture
def rmp_holidays() -> RockyMountainPowerHolidays:
    """Provide a fresh RockyMountainPowerHolidays instance for peak-hour tests."""
    return RockyMountainPowerHolidays()


# ---------------------------------------------------------------------------
# get_rate_schedule
# ---------------------------------------------------------------------------


def test_get_rate_schedule_returns_active_schedule() -> None:
    """Lookup for a date inside a known schedule returns that schedule."""
    schedule = get_rate_schedule(date(2025, 6, 1))
    assert schedule.effective_date <= date(2025, 6, 1)


def test_get_rate_schedule_falls_back_for_historical_date() -> None:
    """Dates predating every schedule fall back to the earliest known schedule.

    Preserves the script's original semantics of scoring historical usage data
    against current rates (the repo ships 2024 sample data but the known
    schedule starts 2025-04-25).
    """
    earliest = min(RATE_SCHEDULES, key=lambda s: s.effective_date)
    assert get_rate_schedule(date(2020, 1, 1)) is earliest


def test_get_rate_schedule_picks_most_recent_when_multiple() -> None:
    """With overlapping schedules, lookup returns the most recent one in effect.

    Monkey-patches RATE_SCHEDULES with two synthetic schedules to verify the
    boundary behavior — important because the Dec 2025 TOU change will add a
    second real entry.
    """
    older = RateSchedule(
        effective_date=date(2020, 1, 1),
        tax_fee_multiplier=1.0,
        block_summer_low=0.1,
        block_summer_high=0.2,
        block_winter_low=0.1,
        block_winter_high=0.2,
        tou_summer_peak=0.3,
        tou_summer_off_peak=0.05,
        tou_winter_peak=0.25,
        tou_winter_off_peak=0.04,
    )
    newer = RateSchedule(
        effective_date=date(2024, 1, 1),
        tax_fee_multiplier=1.0,
        block_summer_low=0.2,
        block_summer_high=0.3,
        block_winter_low=0.2,
        block_winter_high=0.3,
        tou_summer_peak=0.4,
        tou_summer_off_peak=0.06,
        tou_winter_peak=0.35,
        tou_winter_off_peak=0.05,
    )
    original = compare_power_costs.RATE_SCHEDULES
    compare_power_costs.RATE_SCHEDULES = [older, newer]
    try:
        assert compare_power_costs.get_rate_schedule(date(2024, 6, 1)) is newer
        assert compare_power_costs.get_rate_schedule(date(2023, 6, 1)) is older
    finally:
        compare_power_costs.RATE_SCHEDULES = original


# ---------------------------------------------------------------------------
# get_tou_rates — precise post-tax rates per schedule
#
# Cases are grouped by which rate schedule they target; the test id
# (``apr2025-*`` vs ``dec2025-*``) makes the schedule explicit in pytest output.
# Expected values are ``base_rate * 1.3672`` (the published tax/fee multiplier),
# pinned to ~10 digits so accidental rate drift is caught immediately.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("when", "expected_peak", "expected_off_peak"),
    [
        # --- Apr 25, 2025 schedule (effective 2025-04-25 through 2025-11-30) ---
        # Summer months (Jun-Sep) resolve to summer TOU rates.
        pytest.param(
            datetime(2025, 6, 15, 12, 0),
            0.4370705976,
            0.0971272552,
            id="apr2025-summer-jun",
        ),
        pytest.param(
            datetime(2025, 7, 15, 12, 0),
            0.4370705976,
            0.0971272552,
            id="apr2025-summer-jul",
        ),
        pytest.param(
            datetime(2025, 8, 15, 12, 0),
            0.4370705976,
            0.0971272552,
            id="apr2025-summer-aug",
        ),
        pytest.param(
            datetime(2025, 9, 15, 12, 0),
            0.4370705976,
            0.0971272552,
            id="apr2025-summer-sep",
        ),
        # Non-summer months resolve to winter TOU rates. Jan-Apr 2025 predate
        # the earliest schedule's effective_date and hit the fallback branch
        # in get_rate_schedule, which still returns the Apr 2025 schedule.
        pytest.param(
            datetime(2025, 1, 15, 12, 0),
            0.3867877160,
            0.0859531296,
            id="apr2025-winter-jan",
        ),
        pytest.param(
            datetime(2025, 2, 15, 12, 0),
            0.3867877160,
            0.0859531296,
            id="apr2025-winter-feb",
        ),
        pytest.param(
            datetime(2025, 3, 15, 12, 0),
            0.3867877160,
            0.0859531296,
            id="apr2025-winter-mar",
        ),
        pytest.param(
            datetime(2025, 4, 15, 12, 0),
            0.3867877160,
            0.0859531296,
            id="apr2025-winter-apr",
        ),
        pytest.param(
            datetime(2025, 5, 15, 12, 0),
            0.3867877160,
            0.0859531296,
            id="apr2025-winter-may",
        ),
        pytest.param(
            datetime(2025, 10, 15, 12, 0),
            0.3867877160,
            0.0859531296,
            id="apr2025-winter-oct",
        ),
        pytest.param(
            datetime(2025, 11, 15, 12, 0),
            0.3867877160,
            0.0859531296,
            id="apr2025-winter-nov",
        ),
        # --- Dec 1, 2025 schedule (effective 2025-12-01 onward) ---
        pytest.param(
            datetime(2025, 12, 15, 12, 0),
            0.3881808928,
            0.0862621168,
            id="dec2025-winter-dec",
        ),
        pytest.param(
            DEC2025_WINTER_WEEKDAY, 0.3881808928, 0.0862621168, id="dec2025-winter-jan"
        ),
        pytest.param(
            DEC2025_SUMMER_WEEKDAY, 0.4386442448, 0.0974758912, id="dec2025-summer-jul"
        ),
    ],
)
def test_get_tou_rates(
    when: datetime, expected_peak: float, expected_off_peak: float
) -> None:
    """TOU peak/off-peak rates match the published post-tax values for each schedule.

    Each case pins the rate the implementation should return for a given date,
    with the case id naming both the target schedule and season so failures
    point directly at the row that drifted.
    """
    peak, off_peak = get_tou_rates(when)
    assert peak == pytest.approx(expected_peak, rel=1e-9)
    assert off_peak == pytest.approx(expected_off_peak, rel=1e-9)


# ---------------------------------------------------------------------------
# calculate_block_cost — boundary handling around 400 kWh, per schedule
#
# Each case id names the schedule (``apr2025`` / ``dec2025``), season, and the
# boundary scenario being exercised. The first four ``dec2025-winter-*`` cases
# cover the inclusive ``<=400`` split-boundary behavior that previously lived
# in four separate tests; any change to that boundary logic fails all four.
# ---------------------------------------------------------------------------

# Precomputed post-tax block rates (base * 1.3672), one name per (schedule, season, block).
APR2025_BLOCK_SUMMER_LOW: float = 0.1268953008
APR2025_BLOCK_WINTER_LOW: float = 0.1122963392
APR2025_BLOCK_WINTER_HIGH: float = 0.1448794496
DEC2025_BLOCK_SUMMER_LOW: float = 0.1274216728
DEC2025_BLOCK_WINTER_LOW: float = 0.1127625544
DEC2025_BLOCK_WINTER_HIGH: float = 0.1453456648


@pytest.mark.parametrize(
    ("when", "usage", "usage_sum", "expected_cost"),
    [
        # --- Apr 25, 2025 schedule ---
        pytest.param(
            APR2025_WINTER_WEEKDAY,
            100,
            0,
            100 * APR2025_BLOCK_WINTER_LOW,
            id="apr2025-winter-low-block",
        ),
        pytest.param(
            APR2025_SUMMER_WEEKDAY,
            100,
            0,
            100 * APR2025_BLOCK_SUMMER_LOW,
            id="apr2025-summer-low-block",
        ),
        # --- Dec 1, 2025 schedule ---
        # Usage entirely under 400 kWh bills at the low rate.
        pytest.param(
            DEC2025_WINTER_WEEKDAY,
            100,
            0,
            100 * DEC2025_BLOCK_WINTER_LOW,
            id="dec2025-winter-low-block",
        ),
        # Usage added on top of a running sum already past 400 kWh bills at high.
        pytest.param(
            DEC2025_WINTER_WEEKDAY,
            100,
            500,
            100 * DEC2025_BLOCK_WINTER_HIGH,
            id="dec2025-winter-high-block",
        ),
        # Usage that straddles 400: first 100 at low, remaining 100 at high.
        pytest.param(
            DEC2025_WINTER_WEEKDAY,
            200,
            300,
            100 * DEC2025_BLOCK_WINTER_LOW + 100 * DEC2025_BLOCK_WINTER_HIGH,
            id="dec2025-winter-straddle-400",
        ),
        # Usage landing exactly on 400 stays in the low block (inclusive <=400).
        pytest.param(
            DEC2025_WINTER_WEEKDAY,
            100,
            300,
            100 * DEC2025_BLOCK_WINTER_LOW,
            id="dec2025-winter-exactly-400",
        ),
        # Summer-month date selects the summer block-low rate.
        pytest.param(
            DEC2025_SUMMER_WEEKDAY,
            100,
            0,
            100 * DEC2025_BLOCK_SUMMER_LOW,
            id="dec2025-summer-low-block",
        ),
    ],
)
def test_calculate_block_cost(
    when: datetime, usage: float, usage_sum: float, expected_cost: float
) -> None:
    """Block-rate cost matches the per-schedule post-tax rate for each 400 kWh scenario.

    Covers (a) low-only usage, (b) high-only usage, (c) usage straddling the
    400 kWh threshold, and (d) usage landing exactly on 400 — which pins the
    inclusive ``usage_sum + usage <= 400`` behavior.
    """
    cost = calculate_block_cost(when, usage=usage, usage_sum=usage_sum)
    assert cost == pytest.approx(expected_cost, rel=1e-9)


# ---------------------------------------------------------------------------
# is_peak_hour / find_next_peak_change — peak-hour classification per schedule era
#
# Peak-hour logic itself is schedule-independent (always 18-21 on non-holiday
# weekdays), but every case below is run once against a date in the Apr 2025
# schedule era and once against a date in the Dec 2025 schedule era, so the
# tests continue to provide coverage across both rate schedules. Case ids
# (``apr2025`` / ``dec2025``) name the era in pytest output.
# ---------------------------------------------------------------------------

# Weekday Tuesdays — one per schedule era. Reused across peak-hour tests and
# the find_next_peak_change tests below (all of which key off a Tuesday).
PEAK_HOUR_WEEKDAYS = [
    pytest.param(APR2025_WINTER_WEEKDAY, id="apr2025"),  # 2025-01-21 Tue
    pytest.param(DEC2025_WINTER_WEEKDAY, id="dec2025"),  # 2026-01-20 Tue
]

# Weekend days — one Saturday and one Sunday per schedule era, chosen near the
# weekday constants. Time-of-day is applied via ``.replace(hour=...)`` at the
# test site so the same date can be exercised across all 24 hours.
WEEKEND_DAYS = [
    pytest.param(datetime(2025, 1, 25), id="apr2025-sat"),
    pytest.param(datetime(2025, 1, 26), id="apr2025-sun"),
    pytest.param(datetime(2026, 1, 17), id="dec2025-sat"),
    pytest.param(datetime(2026, 1, 18), id="dec2025-sun"),
]

# RMP holidays at 19:00 across an 11-year sweep (2025 through 2035 — the two years
# originally covered plus 10 years into the future). Generated from the live
# ``RockyMountainPowerHolidays`` class so newly-added observances are picked up
# automatically. Filters:
#   - weekend holidays are skipped (already off-peak via the weekend rule, so
#     they don't exercise the holiday-exemption branch)
#   - "observed" entries are kept: they're the actual weekday on the holiday
#     list and must also be off-peak at 19:00
_HOLIDAY_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _rmp_weekday_holiday_cases(years: range) -> list:
    """Build pytest params: one per weekday RMP holiday in ``years``, at 19:00."""
    rmp = RockyMountainPowerHolidays()
    for year in years:
        # Trigger lazy _populate(year) so items() returns entries for this year.
        # The class only sets subdiv="UT" after super().__init__(), so Pioneer
        # Day is only populated via on-demand lookup — not via years=... at init.
        _ = date(year, 1, 1) in rmp
    cases: list = []
    for holiday_date, name in sorted(rmp.items()):
        if holiday_date.year not in years or holiday_date.weekday() >= 5:
            continue
        slug = _HOLIDAY_SLUG_RE.sub("-", name.lower()).strip("-")
        cases.append(
            pytest.param(
                datetime(
                    holiday_date.year, holiday_date.month, holiday_date.day, 19, 0
                ),
                id=f"{holiday_date.year}-{slug}",
            )
        )
    return cases


RMP_WEEKDAY_HOLIDAYS_AT_19 = _rmp_weekday_holiday_cases(range(2025, 2036))


@pytest.mark.parametrize("weekday", PEAK_HOUR_WEEKDAYS)
@pytest.mark.parametrize("hour", [18, 19, 20, 21])
def test_peak_hours_on_weekday(
    rmp_holidays: RockyMountainPowerHolidays,
    weekday: datetime,
    hour: int,
) -> None:
    """Hours 18-21 on a non-holiday weekday are classified as peak."""
    assert is_peak_hour(weekday.replace(hour=hour), rmp_holidays) is True


@pytest.mark.parametrize("weekday", PEAK_HOUR_WEEKDAYS)
@pytest.mark.parametrize("hour", [0, 6, 12, 17, 22, 23])
def test_off_peak_hours_on_weekday(
    rmp_holidays: RockyMountainPowerHolidays,
    weekday: datetime,
    hour: int,
) -> None:
    """Hours outside 18-21 on a weekday are classified as off-peak.

    Samples the hour just before peak (17) and just after (22) to guard the
    boundary, plus a spread of daytime and overnight hours.
    """
    assert is_peak_hour(weekday.replace(hour=hour), rmp_holidays) is False


@pytest.mark.parametrize("weekend_day", WEEKEND_DAYS)
@pytest.mark.parametrize("hour", range(24))
def test_weekend_is_never_peak(
    rmp_holidays: RockyMountainPowerHolidays,
    weekend_day: datetime,
    hour: int,
) -> None:
    """Saturdays and Sundays are off-peak at every hour of the day.

    Sweeps all 24 hours — including the 18-21 window that would be peak on a
    weekday — across one Saturday and one Sunday per schedule era.
    """
    assert is_peak_hour(weekend_day.replace(hour=hour), rmp_holidays) is False


@pytest.mark.parametrize("holiday_at_19", RMP_WEEKDAY_HOLIDAYS_AT_19)
def test_rmp_holiday_weekday_is_off_peak(
    rmp_holidays: RockyMountainPowerHolidays,
    holiday_at_19: datetime,
) -> None:
    """Every RMP holiday that lands on a weekday is off-peak at 19:00.

    19:00 would be peak on an ordinary weekday, so each case pins that the
    holiday-exemption branch wins. Sweeps 2025 through 2035 inclusive, which
    covers both rate-schedule eras plus 10 years of future holidays. Regression
    guard for the Thanksgiving misclassification fixed in commit a28499b.

    Observed-day coverage (holidays that fall on a weekend get their observed
    date moved to an adjacent weekday — that weekday is the date billing treats
    as the holiday, so it must also be off-peak):

    - Fixed-date holidays (New Year's Day, Independence Day, Pioneer Day,
      Christmas Day) drift across the week year-over-year, so the 11-year
      sweep naturally catches every Sat/Sun landing and the corresponding
      Fri-prior / Mon-after observed-day entry. Examples in-range:

        * 2026-07-03 Fri "Independence Day (observed)" — 7/4 falls on Sat
        * 2027-07-05 Mon "Independence Day (observed)" — 7/4 falls on Sun
        * 2027-07-23 Fri "Pioneer Day (observed)"      — 7/24 falls on Sat
        * 2027-12-24 Fri "Christmas Day (observed)"    — 12/25 falls on Sat
        * 2027-12-31 Fri "New Year's Day (observed)"   — 1/1/2028 falls on Sat
        * 2033-07-25 Mon "Pioneer Day (observed)"      — 7/24 falls on Sun
        * 2033-12-26 Mon "Christmas Day (observed)"    — 12/25 falls on Sun
        * 2034-01-02 Mon "New Year's Day (observed)"   — 1/1 falls on Sun

    - Dynamically-dated holidays (Washington's Birthday, Memorial Day, Labor
      Day, Thanksgiving) are defined as a specific weekday of a month, so they
      never fall on a weekend and have no observed-day variant.

    The observed-day shift rule itself is verified separately by
    ``test_rmp_holiday_observed_day_shifts`` below, which pins exactly which
    weekday each weekend-landing fixed-date holiday moves to. If the upstream
    ``holidays`` library ever changes its shift rule, that test fails first
    and isolates the cause before this broader peak-hour sweep reports it.
    """
    assert is_peak_hour(holiday_at_19, rmp_holidays) is False


# Fixed-date RMP holidays — the only ones that can land on a weekend and
# therefore trigger the observed-day shift. Dynamically-dated holidays
# (Washington's Birthday, Memorial Day, Labor Day, Thanksgiving) are anchored
# to a weekday-of-month rule and always land on a weekday.
FIXED_DATE_RMP_HOLIDAYS: list[tuple[int, int, str]] = [
    (1, 1, "New Year's Day"),
    (7, 4, "Independence Day"),
    (7, 24, "Pioneer Day"),
    (12, 25, "Christmas Day"),
]


def _fixed_date_holiday_cases(years: range) -> list:
    """Build pytest params: one (year, month, day, name) per fixed-date holiday."""
    cases: list = []
    for year in years:
        for month, day, name in FIXED_DATE_RMP_HOLIDAYS:
            slug = _HOLIDAY_SLUG_RE.sub("-", name.lower()).strip("-")
            cases.append(pytest.param(year, month, day, name, id=f"{year}-{slug}"))
    return cases


@pytest.mark.parametrize(
    ("year", "month", "day", "canonical_name"),
    _fixed_date_holiday_cases(range(2025, 2036)),
)
def test_rmp_holiday_observed_day_shifts(
    rmp_holidays: RockyMountainPowerHolidays,
    year: int,
    month: int,
    day: int,
    canonical_name: str,
) -> None:
    """Fixed-date RMP holidays shift to an adjacent weekday when they land on a weekend.

    The ``holidays`` library applies the standard US federal-holiday rule:

        Sat landing  ->  observed on Friday-prior (may be in the prior year
                         for New Year's Day, e.g. 2027-12-31 observes
                         2028-01-01)
        Sun landing  ->  observed on Monday-after
        Mon-Fri      ->  no observed-day entry; the fixed date is the holiday

    This test anchors the assumption that
    ``test_rmp_holiday_weekday_is_off_peak`` above relies on: weekend-landing
    holidays must produce a weekday observed entry, or the peak-hour logic
    would silently have nothing to exempt. Sweeps the same 2025-2035 range so
    any drift in the shift rule — or in which names the library applies
    ``(observed)`` to — is caught by a failure whose id names the exact
    (year, holiday) that regressed.
    """
    fixed = date(year, month, day)
    weekday = fixed.weekday()  # 0=Mon .. 6=Sun

    # Populate the year plus its neighbors so cross-year shifts resolve
    # correctly (a Jan 1 Sat observation lands on Dec 31 of the prior year).
    for y in (year - 1, year, year + 1):
        _ = date(y, 6, 15) in rmp_holidays

    if weekday == 5:  # Saturday -> Friday-prior
        expected_observed = fixed - timedelta(days=1)
        assert expected_observed in rmp_holidays, (
            f"{canonical_name} falls on {fixed} (Sat); expected observed-day "
            f"entry at {expected_observed} (Fri) is missing"
        )
        observed_name = rmp_holidays[expected_observed]
        assert canonical_name in observed_name
        assert "(observed)" in observed_name.lower()
    elif weekday == 6:  # Sunday -> Monday-after
        expected_observed = fixed + timedelta(days=1)
        assert expected_observed in rmp_holidays, (
            f"{canonical_name} falls on {fixed} (Sun); expected observed-day "
            f"entry at {expected_observed} (Mon) is missing"
        )
        observed_name = rmp_holidays[expected_observed]
        assert canonical_name in observed_name
        assert "(observed)" in observed_name.lower()
    else:
        # No shift: the fixed date itself is the holiday and carries the
        # canonical name without an "(observed)" suffix.
        assert fixed in rmp_holidays
        assert rmp_holidays[fixed] == canonical_name


# ---------------------------------------------------------------------------
# find_next_peak_change — UnboundLocalError regression + delta math, per era
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tuesday", PEAK_HOUR_WEEKDAYS)
def test_find_next_peak_change_on_exact_hour_boundary_does_not_crash(
    rmp_holidays: RockyMountainPowerHolidays,
    tuesday: datetime,
) -> None:
    """Calling at an exact hour boundary no longer raises UnboundLocalError.

    Previously ``iter_datetime`` was only assigned inside an if-branch that
    skipped when minute/second/microsecond were all zero. 14:00 on a Tuesday
    is off-peak; the next change is at 18:00, a 4-hour delta.
    """
    delta = find_next_peak_change(
        tuesday.replace(hour=14, minute=0, second=0), rmp_holidays
    )
    assert delta == timedelta(hours=4)


@pytest.mark.parametrize("tuesday", PEAK_HOUR_WEEKDAYS)
def test_find_next_peak_change_mid_hour(
    rmp_holidays: RockyMountainPowerHolidays,
    tuesday: datetime,
) -> None:
    """Non-boundary input returns the delta to the next transition.

    14:30 on a Tuesday is off-peak; peak starts at 18:00, a 3h30m delta.
    """
    delta = find_next_peak_change(
        tuesday.replace(hour=14, minute=30, second=0), rmp_holidays
    )
    assert delta == timedelta(hours=3, minutes=30)


@pytest.mark.parametrize("tuesday", PEAK_HOUR_WEEKDAYS)
def test_find_next_peak_change_during_peak(
    rmp_holidays: RockyMountainPowerHolidays,
    tuesday: datetime,
) -> None:
    """During a peak window, the delta is the remaining peak time.

    19:00 on a Tuesday is peak; peak ends at 22:00, a 3-hour delta.
    """
    delta = find_next_peak_change(
        tuesday.replace(hour=19, minute=0, second=0), rmp_holidays
    )
    assert delta == timedelta(hours=3)
