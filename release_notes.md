# Release Notes

## Summary

Three fixes to `compare_power_costs`:

1. **Bugfix** — `current_peak_status.py` crashed with `UnboundLocalError` when called at an exact hour boundary.
2. **Refactor** — Rate tables centralized behind a date-keyed lookup, so future rate-schedule changes (e.g. the Dec 2025 TOU update) are a one-line edit.
3. **Tests** — Added a pytest suite covering rate lookup, TOU rates, block-pricing boundaries, peak-hour classification, and a regression test for fix #1.

No behavior change on existing sample data — output of `./compare_power_costs.py ./2024-09` is byte-identical to the pre-change version.

---

## 4. Add Dec 1, 2025 RMP rate schedule

Rocky Mountain Power's Schedule 1 was updated effective 2025-12-01 (Docket No. 25-035-T12). Prepended a new `RateSchedule` entry with the new base rates, verified against the official PDF and an April 2026 customer bill:

| Rate              | Apr 25, 2025 | Dec 1, 2025  |
|-------------------|--------------|--------------|
| Block summer low  | 0.092814     | **0.093199** |
| Block summer high | 0.119745     | **0.120130** |
| Block winter low  | 0.082136     | **0.082477** |
| Block winter high | 0.105968     | **0.106309** |
| TOU summer peak   | 0.319683     | **0.320834** |
| TOU summer off    | 0.071041     | **0.071296** |
| TOU winter peak   | 0.282905     | **0.283924** |
| TOU winter off    | 0.062868     | **0.063094** |

The `tax_fee_multiplier` (1.3672) is carried over unchanged. Note: real bills now break fees into separate line items (Energy Balancing Account at 22.14% is the largest), so the flat multiplier under-estimates the true bill by ~3%. Modeling individual fee components is left for a follow-up.

Docstrings in `calculate_block_cost`, `get_tou_rates`, and `calculate_ev_cost` updated to reference the Dec 1, 2025 rates.

The winter-month parametrized test in `tests/test_compare_power_costs.py` was split: months 1-5, 10, 11 of 2025 still assert the old rate; a new `test_december_2025_uses_new_winter_rate` covers Dec 2025 under the updated schedule.

---

## 1. Fix `UnboundLocalError` in `find_next_peak_change`

### Problem

In [current_peak_status.py](current_peak_status.py), `find_next_peak_change` crashed whenever it was called with a `datetime` whose minute, second, and microsecond were all zero. The variable `iter_datetime` was only assigned inside an `if` that ran for *non-boundary* times:

```python
# before
if (
    date_object.minute != 0
    or date_object.second != 0
    or date_object.microsecond != 0
):
    iter_datetime = date_object.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

while is_peak_hour(iter_datetime, ...) == initial_peak:  # UnboundLocalError at :00:00.000
    iter_datetime += timedelta(hours=1)
```

This is easy to hit in practice — any automation that polls on hour boundaries (cron, Home Assistant templates) would trigger it.

### Fix

Always initialize `iter_datetime` to the next hour boundary. If already on the boundary, advancing one hour is correct anyway because the current hour is by definition the same peak state as `initial_peak` — no information is lost.

```python
# after
iter_datetime = date_object.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
```

### Test coverage

- `test_find_next_peak_change_on_exact_hour_boundary_does_not_crash` — regression guard for the exact failure mode.
- `test_find_next_peak_change_mid_hour` — unchanged behavior for non-boundary inputs.
- `test_find_next_peak_change_during_peak` — verifies the peak → off-peak transition.

---

## 2. Centralize rates with effective-date lookup

### Problem

Rate numbers were scattered as magic literals across two functions:

- [calculate_block_cost](compare_power_costs.py) hardcoded post-tax rates (e.g. `0.1122963392`).
- [get_tou_rates](compare_power_costs.py) hardcoded base rates and multiplied by `1.3672` inline.

Two issues:

1. **Maintenance cost.** Rocky Mountain Power has already signalled a TOU change coming 2025-12-01 (see [README.md](README.md)). With rates inline, updating them means editing multiple functions and keeping the tax-multiplier handling in sync.
2. **No notion of time.** Every analysis silently used whichever rate was hardcoded, regardless of the usage date. Historical comparisons against *older* rates were not expressible.

### Change

Introduced a dataclass and a module-level list of schedules:

```python
@dataclass(frozen=True)
class RateSchedule:
    effective_date: date
    tax_fee_multiplier: float
    block_summer_low: float
    block_summer_high: float
    block_winter_low: float
    block_winter_high: float
    tou_summer_peak: float
    tou_summer_off_peak: float
    tou_winter_peak: float
    tou_winter_off_peak: float

RATE_SCHEDULES: list[RateSchedule] = [
    RateSchedule(
        effective_date=date(2025, 4, 25),
        tax_fee_multiplier=1.3672,
        block_summer_low=0.092814,
        # ... base rates only; multiplier applied at lookup time
    ),
]

def get_rate_schedule(usage_date: date) -> RateSchedule: ...
```

`calculate_block_cost` and `get_tou_rates` now call `get_rate_schedule(date_object.date())` and read from the returned schedule. Both functions lost their rate literals entirely.

Also promoted `summer_months` and `peak_hours` from per-call `list` rebuilds to module-level `frozenset` constants (`SUMMER_MONTHS`, `PEAK_HOURS`).

### When `usage_date` predates every known schedule

The original script's semantics were "score these usages against the current rates" — it applied the April 2025 rates to the 2024 sample data in the repo without issue. To preserve that, `get_rate_schedule` falls back to the earliest known schedule when the usage date predates every `effective_date`. A strict "raise ValueError" mode would have broken the sample-data workflow documented in the README.

### How to add a future rate change

When RMP publishes the Dec 2025 TOU rates, prepend a new entry:

```python
RATE_SCHEDULES: list[RateSchedule] = [
    RateSchedule(effective_date=date(2025, 12, 1), ...),   # new
    RateSchedule(effective_date=date(2025, 4, 25), ...),   # existing
]
```

No other code changes required. Cross-boundary analyses (usage spanning Nov–Dec 2025) will automatically apply the right rates to each hour.

### Numerical equivalence

Verified by running `./compare_power_costs.py ./2024-09` before and after — output matches exactly (`block_cost: 151.903`, `ev_cost: 144.638`, etc.). The base rates in the schedule, times `1.3672`, produce the same post-tax values that were previously hardcoded:

| Rate               | Base × 1.3672          | Old hardcoded value |
|--------------------|------------------------|---------------------|
| Block summer low   | 0.092814 × 1.3672      | 0.1268953008        |
| Block summer high  | 0.119745 × 1.3672      | 0.163715364         |
| Block winter low   | 0.082136 × 1.3672      | 0.1122963392        |
| Block winter high  | 0.105968 × 1.3672      | 0.1448794496        |

---

## 3. Pytest suite

### Scope

Added [tests/test_compare_power_costs.py](tests/test_compare_power_costs.py) with 38 tests grouped by module area:

- **`get_rate_schedule`** — active-schedule lookup, historical fallback, most-recent wins when multiple schedules overlap.
- **`get_tou_rates`** — winter/summer values to 9-digit precision; parametrized over all 12 months to confirm the summer-month set.
- **`calculate_block_cost`** — entirely-low, entirely-high, split at the 400 kWh boundary, exact-boundary edge case, and summer rate selection.
- **`is_peak_hour`** — all four peak hours (18–21), a sampling of off-peak hours, weekend exclusion, holiday exclusion on a weekday, and a Thanksgiving regression guard (recent bugfix per git log).
- **`find_next_peak_change`** — the hour-boundary regression test, mid-hour, and during-peak cases.

### Running

```bash
make test      # new target
# or
pytest tests/
```

### Dev dependency

Added `pytest` to [requirements-dev.txt](requirements-dev.txt).

---

## Files changed

| File                                                         | Change                                          |
|--------------------------------------------------------------|-------------------------------------------------|
| [compare_power_costs.py](compare_power_costs.py)             | Rate dataclass + lookup; constants hoisted      |
| [current_peak_status.py](current_peak_status.py)             | `UnboundLocalError` fix                         |
| [tests/test_compare_power_costs.py](tests/test_compare_power_costs.py) | New — 38 tests                        |
| [tests/__init__.py](tests/__init__.py)                       | New — empty package marker                      |
| [requirements-dev.txt](requirements-dev.txt)                 | Added `pytest`                                  |
| [makefile](makefile)                                         | New `test` target; added to `ready`             |

## Verification

```text
$ make test
pytest tests/
======================== 38 passed, 1 warning in 0.08s =========================

$ ./compare_power_costs.py ./2024-09
# Output matches README example exactly (block_cost 151.903, ev_cost 144.638, …)
```
