#!/usr/bin/env python3
"""Show current Peak Status and time till next change

This script is mainly a prototype for being able to build a project to display these two stats on a
physical display in the house somewhere.
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta

from compare_power_costs import RockyMountainPowerHolidays, is_peak_hour

logger = logging.getLogger(__name__)


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
    opts = parser.parse_args()
    logging.basicConfig(format="%(message)s", level=opts.log_level)
    return opts


def find_next_peak_change(
    date_object: datetime, rmp_holidays: RockyMountainPowerHolidays
) -> timedelta:
    """Find the next change in peak status from the given date_object

    This is useful for being able to display a countdown timer until the next change in peak status

    Args:
        date_object: initial datetime object to start analysis from
        rmp_holidays: Holiday object defining the RMP holidays

    Returns:
        timedelta: time until next change in peak status
    """
    initial_peak = is_peak_hour(date_object=date_object, rmp_holidays=rmp_holidays)
    # Ensure start_datetime is at the start of the hour
    if (
        date_object.minute != 0
        or date_object.second != 0
        or date_object.microsecond != 0
    ):
        iter_datetime = date_object.replace(
            minute=0, second=0, microsecond=0
        ) + timedelta(hours=1)

    while (
        is_peak_hour(date_object=iter_datetime, rmp_holidays=rmp_holidays)
        == initial_peak
    ):
        iter_datetime += timedelta(hours=1)

    return iter_datetime - date_object


def main() -> int:
    """Run main script

    Returns:
        Unix style return code, 0 for pass.
    """
    _opts = parse_args()
    time_now = datetime.now()
    rmp_holidays = RockyMountainPowerHolidays()
    is_peak = is_peak_hour(date_object=time_now, rmp_holidays=rmp_holidays)
    next_peak_change_delta = find_next_peak_change(
        date_object=time_now, rmp_holidays=rmp_holidays
    )
    logger.info(f"CURRENT_TIME: {time_now}")
    logger.info(f"IS_PEAK: {is_peak}")
    logger.info(f"TIME_TILL_NEXT_PEAK_CHANGE: {next_peak_change_delta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
