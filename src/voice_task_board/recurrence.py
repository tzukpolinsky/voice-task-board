"""Recurrence engine using dateutil.rrule for deterministic date math."""

from datetime import datetime
from dateutil import rrule
from zoneinfo import ZoneInfo


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
    
    # Parse the until datetime if provided
    until_dt = None
    if until_utc:
        until_dt = datetime.fromisoformat(until_utc)
        if tz:
            try:
                zone = ZoneInfo(tz)
                until_dt = until_dt.replace(tzinfo=zone)
            except Exception:
                pass
    
    # Calculate the horizon window end
    from datetime import timedelta
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
    
    # Parse until if provided
    until_dt = None
    if until_utc:
        until_dt = datetime.fromisoformat(until_utc)
        if tz:
            try:
                zone = ZoneInfo(tz)
                until_dt = until_dt.replace(tzinfo=zone)
            except Exception:
                pass
    
    # Use a far-future horizon for next_after
    from datetime import timedelta
    horizon_end = after_dt + timedelta(days=400)  # Look ahead a bit further
    
    try:
        rule = rrule.rrulestr(rrule_str, dtstart=after_dt)
        # Get all occurrences strictly after after_dt
        candidates = list(rule.between(after_dt, horizon_end, inc=False))
    except Exception:
        return None
    
    if not candidates:
        return None
    
    next_dt = candidates[0]
    
    # Check if past until
    if until_dt and next_dt > until_dt:
        return None
    
    # Return as naive string
    if next_dt.tzinfo:
        next_dt = next_dt.replace(tzinfo=None)
    return next_dt.strftime("%Y-%m-%dT%H:%M:%S")


