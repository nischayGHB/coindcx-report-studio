"""Strict Asia/Kolkata timestamp conversion."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")
IST_PATTERN = re.compile(
    r"^(?P<day>\d{2})/(?P<month>\d{2})/(?P<year>\d{2}) "
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})$"
)


def parse_ist_datetime_to_ms(value: str) -> int:
    """Parse DD/MM/YY HH:MM:SS, interpreting every YY as 20YY."""
    if not isinstance(value, str):
        raise ValueError("Datetime must be text in DD/MM/YY HH:MM:SS format")
    match = IST_PATTERN.fullmatch(value.strip())
    if not match:
        raise ValueError(
            f"Invalid datetime '{value}'. Expected DD/MM/YY HH:MM:SS, for example 21/06/26 09:15:00"
        )
    parts = {key: int(raw) for key, raw in match.groupdict().items()}
    try:
        aware = datetime(
            2000 + parts["year"],
            parts["month"],
            parts["day"],
            parts["hour"],
            parts["minute"],
            parts["second"],
            tzinfo=IST,
        )
    except ValueError as exc:
        raise ValueError(f"Invalid Asia/Kolkata datetime '{value}': {exc}") from exc
    return int(aware.timestamp() * 1000)


def ms_to_datetime_ist(ms: int) -> datetime:
    try:
        numeric = int(ms)
    except (TypeError, ValueError) as exc:
        raise ValueError("Epoch timestamp must be an integer in milliseconds") from exc
    return datetime.fromtimestamp(numeric / 1000, tz=timezone.utc).astimezone(IST)

