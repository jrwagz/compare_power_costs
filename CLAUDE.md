# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Compares Rocky Mountain Power (RMP) residential electric pricing plans — Schedule 1 block pricing vs. the Time-of-Use (TOU) option — from user-exported hourly usage CSVs. As of 2025-12-01, RMP is moving all Schedule 2E EV customers onto Schedule 1's TOU option, so the tool's main audience is RMP residential customers deciding between block and TOU.

## Common commands

- `make .venv` — create the Python 3.11 venv via `uv` and install runtime + dev deps.
- `make test` — run pytest (`tests/` is the only configured testpath).
- `pytest tests/test_compare_power_costs.py::test_get_rate_schedule_returns_active_schedule` — run a single test.
- `make lint` — ruff, black --check, isort --check.
- `make format` — ruff --fix, black, isort.
- `make ready` — format + lint + test (run before committing).
- `./compare_power_costs.py ./2024-09` — analyze a directory of daily RMP CSV files named `YYYY-MM-DD.csv`.
- `./compare_power_costs.py ./some_dir --alternative-format` — parse the alternative CSV layout (single file with `Date,Time,Usage` columns across many days) instead of one-file-per-day.
- `./current_peak_status.py` — prints whether *now* is peak and the timedelta until the next peak/off-peak transition (prototype for a physical display).

## Architecture

Single-file script (`compare_power_costs.py`) plus a small companion (`current_peak_status.py`) that reuses its holiday/peak logic. The flow:

1. Walk the input directory, find `*.csv`.
2. Parse each file into `(datetime, kWh)` hourly entries — filename drives the date for the RMP format; the date is in-row for the alternative format.
3. For each entry, compute both the block cost (Schedule 1 tiered, with a 400 kWh/month breakpoint) and the TOU cost (peak vs off-peak) and accumulate per `YYYY-MM` bucket plus a `SUMMARY`.
4. Emit a sorted JSON summary with `block_cost`, `ev_cost`, `difference`, `kWh`, `sum_peak_kWh`, `off_peak_%`.

Rate handling is centralized in `RATE_SCHEDULES` (list of `RateSchedule` dataclasses, newest-first) and `get_rate_schedule(usage_date)`. Adding a new RMP rate update means **prepending one entry** — every cost function (`calculate_block_cost`, `get_tou_rates`, `calculate_ev_cost`) resolves rates through `get_rate_schedule`. For dates predating every known schedule, it falls back to the earliest schedule — this is intentional so historical sample data can be scored against current rates ("what would this have cost today?").

Base rates are stored pre-fee; the billed rate is `base_rate * tax_fee_multiplier` (23.84% fees compounded with 10.4% tax ≈ 36.72%). Keep this convention when adding schedules.

Peak hours: weekdays (Mon–Fri), 18:00–21:59 local, excluding RMP holidays. The holiday list is a subclass of `holidays.countries.US` (`RockyMountainPowerHolidays`) that removes MLK Day, Juneteenth, Columbus Day, and Veterans Day. There is a known TODO in `is_peak_hour`: RMP's "Saturday holiday → observe Friday, Sunday holiday → observe Monday" weekend-shift rule is not yet implemented.

Summer months are June–September (`SUMMER_MONTHS = {6,7,8,9}`); everything else is winter.

## Test layout

`tests/test_compare_power_costs.py` uses a set of date fixtures (e.g. `APR2025_SUMMER_WEEKDAY`, `DEC2025_WINTER_WEEKDAY`) named for the schedule epoch they resolve to. When adding a new rate schedule, add matching fixtures and tests rather than editing existing ones — the naming convention encodes which schedule each date is meant to exercise.

## Skills

`.claude/skills/analyze-power-bill/` — skill for analyzing an RMP monthly bill PDF against hypothetical Schedule 1 non-TOU cost. Invoked automatically when the user asks to analyze/review a power bill.
