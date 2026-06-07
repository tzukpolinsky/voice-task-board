"""Recurrence engine using dateutil.rrule for deterministic date math."""

from datetime import datetime, timedelta
from dateutil import rrule
from zoneinfo import ZoneInfo


def _parse_until(until_utc: str | None, tz: str | None) -> datetime | None:
    """Parse an `until` bound. A DATE-only value ("2027-12-04") means the whole
    day is included, so we treat it as end-of-day (23:59:59) — otherwise an
    occurrence later that day (e.g. 16:00) would be wrongly excluded by a
    midnight comparison, truncating long bounded recurrences a day early."""
    if not until_utc:
        return None
    dt = datetime.fromisoformat(until_utc)
    # Date-only (no time component) → extend to end of that day.
    if "T" not in until_utc and dt.hour == 0 and dt.minute == 0 and dt.second == 0:
        dt = dt.replace(hour=23, minute=59, second=59)
    if tz:
        try:
            dt = dt.replace(tzinfo=ZoneInfo(tz))
        except Exception:
            pass
    return dt


def generate_occurrences(
    rrule_str: str,
    start_utc: str,
    tz: str | None,
    until_utc: str | None,
    horizon_days: int = 365,
) -> list[str]:
    """
    Generate a list of occurrence datetime strings.
    
    Args:
        rrule_str: RRULE string (e.g. "FREQ=DAILY;INTERVAL=1")
        start_utc: Start datetime as string (format: "%Y-%m-%dT%H:%M:%S")
        tz: Timezone string (e.g. "America/New_York") or None for local
        until_utc: Until datetime as string (format: "%Y-%m-%dT%H:%M:%S") or None
        horizon_days: Number of days to look ahead (default 365)
    
    Returns:
        List of occurrence datetime strings in the same format as start_utc.
    """
    # Parse the start datetime
    start_dt = datetime.fromisoformat(start_utc)
    
    # Apply timezone if provided
    if tz:
        try:
            zone = ZoneInfo(tz)
            start_dt = start_dt.replace(tzinfo=zone)
        except Exception:
            # If tz is invalid, treat as naive/local
            pass
    
    # Parse the until datetime if provided (date-only → end of day)
    until_dt = _parse_until(until_utc, tz)

    # Calculate the horizon window end
    horizon_end = start_dt + timedelta(days=horizon_days)
    
    # Determine the actual end: minimum of horizon and until
    end_dt = horizon_end
    if until_dt:
        end_dt = min(horizon_end, until_dt)
    
    # Parse and apply the RRULE
    try:
        rule = rrule.rrulestr(rrule_str, dtstart=start_dt)
        # Generate all occurrences up to the end date
        occurrences = list(rule.between(start_dt, end_dt, inc=True))
    except Exception:
        # If rule parsing fails, return just the start
        occurrences = [start_dt]
    
    # Convert back to the wall-clock string format, cap at 1000 to prevent pathological cases
    result = []
    for dt in occurrences[:1000]:
        # Remove timezone info to return naive datetime strings
        if dt.tzinfo:
            dt = dt.replace(tzinfo=None)
        result.append(dt.strftime("%Y-%m-%dT%H:%M:%S"))
    
    return result


def next_after(
    rrule_str: str,
    after_utc: str,
    tz: str | None,
    until_utc: str | None,
) -> str | None:
    """
    Get the single next datetime strictly after after_utc.
    
    Args:
        rrule_str: RRULE string
        after_utc: Current datetime as string (find next after this)
        tz: Timezone string or None
        until_utc: Until datetime or None; return None if past this
    
    Returns:
        The next occurrence datetime string, or None if past until or no future match.
    """
    after_dt = datetime.fromisoformat(after_utc)

    # Apply timezone if provided
    if tz:
        try:
            zone = ZoneInfo(tz)
            after_dt = after_dt.replace(tzinfo=zone)
        except Exception:
            pass

    # Parse until if provided (date-only → end of day, same rule as generation)
    until_dt = _parse_until(until_utc, tz)

    try:
        # dtstart=after_dt keeps the wall-clock time-of-day; for the rules this
        # app produces (daily / weekly-by-day / monthly / yearly) the cadence is
        # anchored by FREQ/BYDAY, so phase is preserved. `.after()` returns the
        # single next occurrence with no fixed horizon, so long bounded series
        # (e.g. >1 year) are never truncated by a too-small look-ahead window.
        rule = rrule.rrulestr(rrule_str, dtstart=after_dt)
        next_dt = rule.after(after_dt, inc=False)
    except Exception:
        return None

    if next_dt is None:
        return None

    # Check if past until
    if until_dt and next_dt > until_dt:
        return None
    
    # Return as naive string
    if next_dt.tzinfo:
        next_dt = next_dt.replace(tzinfo=None)
    return next_dt.strftime("%Y-%m-%dT%H:%M:%S")


