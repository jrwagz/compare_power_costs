#!/usr/bin/env python3
"""Summarize Hourly Usage Stats by month

The input to this is the Path to a directory.  We will recursively find all CSV files under that
directory, and it's assumed that the filenames are of the format YYYY-MM-DD.csv, so that we can
learn what date is associated with the specific measured data.  Which is used to determine the
actual power cost for that day.  Since each CSV file represents the power usage for a given day.

"""

import argparse
import csv
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any

logger = logging.getLogger(__name__)

HOLIDAYS = (
    "2023-01-02",  # New Year's Day
    "2023-02-20",  # President's Day
    "2023-05-29",  # Memorial Day
    "2023-07-04",  # Independence Day
    "2023-07-24",  # Pioneer Day
    "2023-09-04",  # Labor Day
    "2023-11-23",  # Thanksgiving Day
    "2023-12-25",  # Christmas Day
    "2024-01-01",  # New Year's Day
    "2024-02-19",  # President's Day
    "2024-05-27",  # Memorial Day
    "2024-07-04",  # Independence Day
    "2024-07-24",  # Pioneer Day
    "2024-09-02",  # Labor Day
    "2024-11-28",  # Thanksgiving Day
    "2024-12-25",  # Christmas Day
)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments

    Args:
        argv: arguments to parse

    Returns:
        Parsed command line options
    """
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        description=__doc__,
    )
    parser.add_argument(
        "--debug",
        action="store_const",
        dest="log_level",
        const=logging.DEBUG,
        default=logging.INFO,
        help="Enable debug printout",
    )
    # Now add other options here
    parser.add_argument(
        "directory",
        help="Path to CSV file containing the input data structure",
        type=Path,
    )
    parser.add_argument(
        "--alternative-format",
        action="store_true",
        help="Specify this option if the directory is filled with CSVs in an alternative format",
    )
    opts = parser.parse_args()
    logging.basicConfig(format="%(message)s", level=opts.log_level)
    return opts


def hourly_usage_entries_from_rmp_csv_file(
    date_object: datetime, csv_file: Path
) -> list[datetime, float]:
    """Given a date, and an RMP CSV file, get the list of hourly usages from that file

    Args:
        date_object: date associated with CSV file
        csv_file: file with usage data for that day

    Returns:
        list[tuple[datetime, float]]: List of tuples containing
            datetime: datetime object with year, month, day, and hour that sample was taken.
                Hour of 12 means it's for the usage between 12noon and 1pm
                Hour of 23 means it's for the usage between 11pm and Midnight
                Hour of 0 means it's for the usage between Midnight and 1am
            float: kWh usage during this period
    """
    hourly_entries = []
    with open(csv_file, newline="", encoding="utf-8") as file_obj:
        reader = csv.reader(file_obj)
        seen_header = False
        for row in reader:
            if not seen_header:
                # This is the header!
                seen_header = True
            else:
                # Get an int for the hour
                usage_hour = int(row[0].split(":")[0]) - 1
                usage_datetime = datetime(
                    year=date_object.year,
                    month=date_object.month,
                    day=date_object.day,
                    hour=usage_hour,
                )
                hour_kwh_usage = float(row[1])
                hourly_entries.append((usage_datetime, hour_kwh_usage))
    return hourly_entries


def hourly_usage_entries_from_alternative_csv_file(
    csv_file: Path,
) -> list[datetime, float]:
    """Given a Johnny CSV file, get the list of hourly usages from that file

    Alternative CSV format is as follows:
        Date,Time,Usage
        1/1/2024,0:00,0.685  # Assumed usage from 0:00-1:00
        1/1/2024,1:00,0.724  # Assumed usage from 1:00-2:00
        1/1/2024,2:00,0.749
        1/1/2024,3:00,0.642
        1/1/2024,4:00,0.449
        1/1/2024,5:00,0.467
        1/1/2024,6:00,0.454
        1/1/2024,7:00,0.45
        1/1/2024,8:00,0.457
        1/1/2024,8:00,0.328

    Args:
        csv_file: file with usage data for that day

    Returns:
        list[tuple[datetime, float]]: List of tuples containing
            datetime: datetime object with year, month, day, and hour that sample was taken.
                Hour of 12 means it's for the usage between 12noon and 1pm
                Hour of 23 means it's for the usage between 11pm and Midnight
                Hour of 0 means it's for the usage between Midnight and 1am
            float: kWh usage during this period
    """
    hourly_entries = []
    with open(csv_file, newline="", encoding="utf-8") as file_obj:
        reader = csv.reader(file_obj)
        seen_header = False
        for row in reader:
            if not seen_header:
                # This is the header!
                seen_header = True
            else:
                # Get an int for the hour
                date_parts = row[0].split("/")
                date_month = int(date_parts[0])
                date_day = int(date_parts[1])
                date_year = int(date_parts[2])
                usage_hour = int(row[1].split(":")[0])
                hour_kwh_usage = float(row[2])

                usage_datetime = datetime(
                    year=date_year,
                    month=date_month,
                    day=date_day,
                    hour=usage_hour,
                )
                hourly_entries.append((usage_datetime, hour_kwh_usage))
    return hourly_entries


def calculate_block_cost(
    date_object: datetime, usage: float, usage_sum: float
) -> float:
    """Calculate the additional cost based on block pricing

    Definition of "bock pricing" comes from this document
    https://www.rockymountainpower.net/content/dam/pcorp/documents/en/rockymountainpower/rates-regulation/utah/rates/001_Residential_Service.pdf

    MONTHLY BILL:
    Energy Charge:
        Billing Months - June through September inclusive (4 months)
            9.0279¢ per kWh first 400 kWh
            11.7210¢ per kWh all additional kWh
        Billing Months - October through May inclusive (8 months)
            7.9893¢ per kWh first 400 kWh
            10.3725¢ per kWh all additional kWh

    Args:
        date_object: object representing the day/hour in question
        usage: usage
        usage_sum: monthly usage so far

    Returns:
        float: cost in USD
    """
    month_index = date_object.month
    summer_months = [6, 7, 8, 9]
    low_rate = 0.0798930
    high_rate = 0.1037250
    if month_index in summer_months:
        low_rate = 0.0902790
        high_rate = 0.1172100

    if usage_sum + usage <= 400:  # Still in the first 400 kWh block
        block_cost = usage * low_rate
    elif usage_sum < 400:  # Split between the first and second blocks
        first_block_usage = 400 - usage_sum
        second_block_usage = usage - first_block_usage
        block_cost = first_block_usage * low_rate + second_block_usage * high_rate
    else:  # All in the second block
        block_cost = usage * high_rate

    return block_cost


def is_peak_hour(date_object: datetime) -> bool:
    """Given a day/hour, determine if it's considered peak or not for time of usage billing

    Args:
        date_object: object representing the day/hour in question

    Returns:
        bool: True if peak hour, else false
    """
    usage_year = date_object.year
    usage_month = date_object.month
    usage_day = date_object.day
    usage_hour = date_object.hour

    summer_months = [5, 6, 7, 8, 9]
    peak_hours = [8, 9, 15, 16, 17, 18, 19]
    if usage_month in summer_months:
        peak_hours = [15, 16, 17, 18, 19]

    day_str = f"{usage_year}-{str(usage_month).zfill(2)}-{str(usage_day).zfill(2)}"
    is_weekday = date_object.weekday() in range(0, 5)
    is_holiday = day_str in HOLIDAYS
    peak_day = is_weekday and not is_holiday
    is_peak = peak_day and usage_hour in peak_hours
    return is_peak


def calculate_ev_cost(date_object: datetime, usage: float) -> tuple[float, bool]:
    """Calculate the day's EV cost

    MONTHLY BILL: (continued)
    Energy Charge:
    Rate Option 1:
        25.3532¢ per kWh for all On-Peak kWh
        5.2004¢ per kWh for all Off-Peak kWh
    TIME PERIODS:
        On-Peak:
            October through April inclusive (7 months)
                8:00 a.m. to 10:00 a.m., and 3:00 p.m. to 8:00 p.m., Monday thru Friday, except
                holidays.
            May through September inclusive (5 months)
                3:00 p.m. to 8:00 p.m., Monday thru Friday, except holidays.
        Off-Peak: All other times.

    Holidays include only
        - New Year's Day
        - President's Day
        - Memorial Day
        - Independence Day
        - Pioneer Day
        - Labor Day
        - Thanksgiving Day
        - Christmas Day.
    When a holiday falls on a Saturday or Sunday, the Friday before the holiday (if the holiday
    falls on a Saturday) or the Monday following the holiday (if the holiday falls on a Sunday)
    will be considered a holiday and consequently Off-Peak.

    Args:
        date_object: object representing the day/hour in question
        usage: usage

    Returns:
        Tuple containing:
            float: usage cost in USD
            bool: True if peak hour, else false
    """
    peak_hour = is_peak_hour(date_object=date_object)
    hour_rate = 0.052004
    if peak_hour:
        hour_rate = 0.253532

    cost = usage * hour_rate
    return cost, peak_hour


def many_month_usage_summary_from_hourly_entries(
    hourly_entries: list[tuple[datetime, float]]
) -> dict[int, dict]:
    """Summarize many months of usage data

    Args:
        date_path_tuples: list of tuples of datetime and float objects, one row for each hour

    Returns:
        dict[int, dict]: each month's usage and cost summary
    """
    month_sums = {}
    for date_object, hour_usage in hourly_entries:
        month_key = f"{date_object.year}-{str(date_object.month).zfill(2)}"
        if month_key not in month_sums:
            month_sums[month_key] = {
                "kWh": 0,
                "block_cost": 0,
                "ev_cost": 0,
                "sum_peak_kWh": 0,
            }

        block_cost = calculate_block_cost(
            date_object=date_object,
            usage=hour_usage,
            usage_sum=month_sums[month_key]["kWh"],
        )
        ev_cost, peak_hour = calculate_ev_cost(
            date_object=date_object, usage=hour_usage
        )
        month_sums[month_key]["kWh"] += hour_usage
        month_sums[month_key]["block_cost"] += block_cost
        month_sums[month_key]["ev_cost"] += ev_cost
        if peak_hour:
            month_sums[month_key]["sum_peak_kWh"] += hour_usage

    overall_block_cost = 0
    overall_ev_cost = 0
    overall_kwh = 0
    overall_sum_peak_kwh = 0
    for _month, m_dict in month_sums.items():
        m_dict["difference"] = m_dict["block_cost"] - m_dict["ev_cost"]
        overall_block_cost += m_dict["block_cost"]
        overall_ev_cost += m_dict["ev_cost"]
        overall_kwh += m_dict["kWh"]
        overall_sum_peak_kwh += m_dict["sum_peak_kWh"]

    month_sums["SUMMARY"] = {
        "kWh": overall_kwh,
        "block_cost": overall_block_cost,
        "ev_cost": overall_ev_cost,
        "difference": overall_block_cost - overall_ev_cost,
        "sum_peak_kWh": overall_sum_peak_kwh,
    }

    return month_sums


def find_csv_files(root_dir: Path) -> list[Path]:
    """Finds all CSV files in a directory

    Args:
        root_dir: top directory to search

    Returns:
        a list of Paths to all CSV files under the directory
    """
    csv_files = []

    # Use walk to find all .csv files recursively
    for root, _dirs, files in os.walk(root_dir):
        for file in files:
            if file.endswith(".csv"):
                # Append the full path of the CSV file to the list
                csv_files.append(Path(root) / file)

    return csv_files


def get_hourly_usage_entries_from_rmp_csvs(
    csv_files: list[Path],
) -> list[tuple[datetime, float]]:
    """Given a list of RMP CSV files, named YYYY-MM-DD, return list of hourly usage entries

    Args:
        csv_files: list of files to analyze

    Returns:
        list[tuple[datetime, float]]: List of tuples containing
            datetime: datetime object with year, month, day, and hour that sample was taken.
                Hour of 13 means it's for the usage between 12noon and 1pm
                Hour of 24 means it's for the usage between 11pm and Midnight
                Hour of 1 means it's for the usage between Midnight and 1am
            float: kWh usage during this period
    """
    hourly_usage_entries = []
    date_format = "%Y-%m-%d.csv"  # Format for the date string
    for csv_file in csv_files:
        try:
            date_object = datetime.strptime(csv_file.name, date_format)
            hourly_entries = hourly_usage_entries_from_rmp_csv_file(
                date_object=date_object, csv_file=csv_file
            )
            hourly_usage_entries += hourly_entries
        except ValueError:
            logger.warning(
                f"WARNING: {csv_file} doesn't match YYYY-MM-DD.csv format!!!"
            )
            continue
    return hourly_usage_entries


def get_hourly_usage_entries_from_alternative_csvs(
    csv_files: list[Path],
) -> list[tuple[datetime, float]]:
    """Given a list of Alternative CSV files, return list of hourly usage entries

    Args:
        csv_files: list of files to analyze

    Returns:
        list[tuple[datetime, float]]: List of tuples containing
            datetime: datetime object with year, month, day, and hour that sample was taken.
                Hour of 13 means it's for the usage between 12noon and 1pm
                Hour of 24 means it's for the usage between 11pm and Midnight
                Hour of 1 means it's for the usage between Midnight and 1am
            float: kWh usage during this period
    """
    hourly_usage_entries = []
    for csv_file in csv_files:
        hourly_entries = hourly_usage_entries_from_alternative_csv_file(
            csv_file=csv_file
        )
        hourly_usage_entries += hourly_entries
    return hourly_usage_entries


def sort_dict_recursively(d: Any) -> Any:
    """Recursively sort a dictionary by its keys."""
    if isinstance(d, dict):
        return {k: sort_dict_recursively(v) for k, v in sorted(d.items())}
    elif isinstance(d, list):
        return [sort_dict_recursively(i) for i in d]
    else:
        return d


def pretty_str_dict(d: dict[str, Any]) -> str:
    """Return a string of a dictionary with keys sorted recursively."""
    sorted_dict = sort_dict_recursively(d)
    return json.dumps(sorted_dict, indent=4, sort_keys=True)


def main() -> int:
    """Run main script

    Returns:
        Unix style return code, 0 for pass.
    """
    opts = parse_args()
    all_csv_files = find_csv_files(root_dir=opts.directory)
    if opts.alternative_format:
        hourly_usage_entries = get_hourly_usage_entries_from_alternative_csvs(
            csv_files=all_csv_files
        )
    else:
        hourly_usage_entries = get_hourly_usage_entries_from_rmp_csvs(
            csv_files=all_csv_files
        )
    stats = many_month_usage_summary_from_hourly_entries(
        hourly_entries=hourly_usage_entries
    )
    logger.info(pretty_str_dict(stats))


if __name__ == "__main__":
    sys.exit(main())
