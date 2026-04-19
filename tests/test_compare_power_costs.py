"""Unit tests for compare_power_costs rate and peak-hour logic."""

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

# A Tuesday in January (winter, non-holiday) and a Tuesday in July (summer, non-holiday).
# 2025-01-21 and 2025-07-15 are both Tuesdays; neither is an RMP holiday.
WINTER_WEEKDAY = datetime(2025, 1, 21, 12, 0)
SUMMER_WEEKDAY = datetime(2025, 7, 15, 12, 0)


@pytest.fixture
def rmp_holidays():
    """Provide a fresh RockyMountainPowerHolidays instance for peak-hour tests."""
    return RockyMountainPowerHolidays()


# ---------------------------------------------------------------------------
# get_rate_schedule
# ---------------------------------------------------------------------------


def test_get_rate_schedule_returns_active_schedule():
    """Lookup for a date inside a known schedule returns that schedule."""
    schedule = get_rate_schedule(date(2025, 6, 1))
    assert schedule.effective_date <= date(2025, 6, 1)


def test_get_rate_schedule_falls_back_for_historical_date():
    """Dates predating every schedule fall back to the earliest known schedule.

    Preserves the script's original semantics of scoring historical usage data
    against current rates (the repo ships 2024 sample data but the known
    schedule starts 2025-04-25).
    """
    earliest = min(RATE_SCHEDULES, key=lambda s: s.effective_date)
    assert get_rate_schedule(date(2020, 1, 1)) is earliest


def test_get_rate_schedule_picks_most_recent_when_multiple():
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
# get_tou_rates
# ---------------------------------------------------------------------------


def test_get_tou_rates_winter():
    """Winter-month TOU lookup returns the Oct-May billed rates.

    Verifies the exact post-tax values (base * 1.3672) to 9-digit precision —
    this is a guard against accidental drift when rate data is refactored.
    """
    peak, off_peak = get_tou_rates(WINTER_WEEKDAY)
    assert peak == pytest.approx(0.386787716, rel=1e-9)
    assert off_peak == pytest.approx(0.0859531296, rel=1e-9)


def test_get_tou_rates_summer():
    """Summer-month TOU lookup returns the Jun-Sep billed rates.

    Verifies the exact post-tax values (base * 1.3672) to 9-digit precision.
    """
    peak, off_peak = get_tou_rates(SUMMER_WEEKDAY)
    assert peak == pytest.approx(0.4370705976, rel=1e-9)
    assert off_peak == pytest.approx(0.0971272552, rel=1e-9)


@pytest.mark.parametrize("month", [6, 7, 8, 9])
def test_summer_months_use_summer_rates(month):
    """Months 6-9 are classified as summer and use the summer peak rate."""
    peak, _ = get_tou_rates(datetime(2025, month, 15, 12, 0))
    assert peak == pytest.approx(0.4370705976, rel=1e-9)


@pytest.mark.parametrize("month", [1, 2, 3, 4, 5, 10, 11])
def test_winter_months_use_winter_rates(month):
    """All non-summer months use the winter peak rate.

    December 2025 is excluded because it falls under the Dec 1, 2025 schedule
    update; that case is covered by ``test_december_2025_uses_new_winter_rate``.
    """
    peak, _ = get_tou_rates(datetime(2025, month, 15, 12, 0))
    assert peak == pytest.approx(0.386787716, rel=1e-9)


def test_december_2025_uses_new_winter_rate():
    """December 2025 falls under the Dec 1, 2025 schedule with the new winter peak rate."""
    peak, _ = get_tou_rates(datetime(2025, 12, 15, 12, 0))
    assert peak == pytest.approx(0.283924 * 1.3672, rel=1e-9)


# ---------------------------------------------------------------------------
# calculate_block_cost — boundary handling around 400 kWh
# ---------------------------------------------------------------------------


def test_block_cost_entirely_in_low_block_winter():
    """Usage entirely under the 400 kWh monthly threshold bills at the low rate."""
    cost = calculate_block_cost(WINTER_WEEKDAY, usage=100, usage_sum=0)
    assert cost == pytest.approx(100 * 0.1122963392, rel=1e-9)


def test_block_cost_entirely_in_high_block_winter():
    """Usage added on top of a running sum already past 400 kWh bills at the high rate."""
    cost = calculate_block_cost(WINTER_WEEKDAY, usage=100, usage_sum=500)
    assert cost == pytest.approx(100 * 0.1448794496, rel=1e-9)


def test_block_cost_splits_across_400_boundary_winter():
    """Usage that straddles the 400 kWh threshold is split between the two rates.

    With 300 kWh already used, adding 200 kWh should bill the first 100 at the
    low rate and the remaining 100 at the high rate.
    """
    cost = calculate_block_cost(WINTER_WEEKDAY, usage=200, usage_sum=300)
    expected = 100 * 0.1122963392 + 100 * 0.1448794496
    assert cost == pytest.approx(expected, rel=1e-9)


def test_block_cost_exactly_at_400_boundary_is_all_low():
    """Usage that lands exactly on 400 kWh (not past it) stays in the low block.

    Pins the inclusive ``usage_sum + usage <= 400`` behavior of the current
    implementation — any change to a strict ``<`` would fail this test.
    """
    cost = calculate_block_cost(WINTER_WEEKDAY, usage=100, usage_sum=300)
    assert cost == pytest.approx(100 * 0.1122963392, rel=1e-9)


def test_block_cost_uses_summer_rates_in_summer():
    """Block-cost lookup selects summer rates for summer-month dates."""
    cost = calculate_block_cost(SUMMER_WEEKDAY, usage=100, usage_sum=0)
    assert cost == pytest.approx(100 * 0.1268953008, rel=1e-9)


# ---------------------------------------------------------------------------
# is_peak_hour
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hour", [18, 19, 20, 21])
def test_peak_hours_on_weekday(rmp_holidays, hour):
    """Hours 18-21 on a non-holiday weekday are classified as peak.

    Uses 2025-01-21, a Tuesday with no RMP holiday.
    """
    assert is_peak_hour(datetime(2025, 1, 21, hour, 0), rmp_holidays) is True


@pytest.mark.parametrize("hour", [0, 6, 12, 17, 22, 23])
def test_off_peak_hours_on_weekday(rmp_holidays, hour):
    """Hours outside 18-21 on a weekday are classified as off-peak.

    Samples the hour just before peak (17) and just after (22) to guard the
    boundary, plus a spread of daytime and overnight hours.
    """
    assert is_peak_hour(datetime(2025, 1, 21, hour, 0), rmp_holidays) is False


def test_weekend_is_never_peak(rmp_holidays):
    """Saturdays and Sundays are always off-peak, even during the 18-21 window."""
    assert is_peak_hour(datetime(2025, 1, 25, 19, 0), rmp_holidays) is False
    assert is_peak_hour(datetime(2025, 1, 26, 19, 0), rmp_holidays) is False


def test_holiday_weekday_is_off_peak(rmp_holidays):
    """RMP holidays that fall on a weekday are off-peak.

    2025-01-01 is a Wednesday and New Year's Day — the 19:00 hour would be
    peak on an ordinary Wednesday but must be off-peak on the holiday.
    """
    assert is_peak_hour(datetime(2025, 1, 1, 19, 0), rmp_holidays) is False


def test_thanksgiving_is_off_peak(rmp_holidays):
    """Thanksgiving is recognized as a holiday.

    Regression guard for the prior bug (see commit a28499b) where Thanksgiving
    was misclassified as a peak weekday.
    """
    assert is_peak_hour(datetime(2025, 11, 27, 19, 0), rmp_holidays) is False


# ---------------------------------------------------------------------------
# find_next_peak_change — UnboundLocalError regression test
# ---------------------------------------------------------------------------


def test_find_next_peak_change_on_exact_hour_boundary_does_not_crash(rmp_holidays):
    """Calling at an exact hour boundary no longer raises UnboundLocalError.

    Previously ``iter_datetime`` was only assigned inside an if-branch that
    skipped when minute/second/microsecond were all zero. 14:00 on a Tuesday
    is off-peak; the next change is at 18:00, a 4-hour delta.
    """
    delta = find_next_peak_change(datetime(2025, 1, 21, 14, 0, 0), rmp_holidays)
    assert delta == timedelta(hours=4)


def test_find_next_peak_change_mid_hour(rmp_holidays):
    """Non-boundary input returns the delta to the next transition.

    14:30 on a Tuesday is off-peak; peak starts at 18:00, a 3h30m delta.
    """
    delta = find_next_peak_change(datetime(2025, 1, 21, 14, 30, 0), rmp_holidays)
    assert delta == timedelta(hours=3, minutes=30)


def test_find_next_peak_change_during_peak(rmp_holidays):
    """During a peak window, the delta is the remaining peak time.

    19:00 on a Tuesday is peak; peak ends at 22:00, a 3-hour delta.
    """
    delta = find_next_peak_change(datetime(2025, 1, 21, 19, 0, 0), rmp_holidays)
    assert delta == timedelta(hours=3)
