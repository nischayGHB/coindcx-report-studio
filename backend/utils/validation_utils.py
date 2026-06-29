"""Input normalization shared by HTTP and reporting layers."""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..config import MAX_TOKEN_COUNT


PAIR_PATTERN = re.compile(r"^B-[A-Z0-9][A-Z0-9.-]*_[A-Z0-9][A-Z0-9.-]*$")


def normalize_pair(value: str) -> str:
    pair = str(value).strip().upper()
    if not PAIR_PATTERN.fullmatch(pair):
        raise ValueError("Use a CoinDCX futures pair such as B-SOL_USDT")
    return pair


def normalize_token_list(values: str | Iterable[str] | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        raw_values = re.split(r"[,\s]+", values)
    else:
        raw_values = []
        for value in values:
            raw_values.extend(re.split(r"[,\s]+", str(value)))

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        if not raw.strip():
            continue
        pair = normalize_pair(raw)
        if pair not in seen:
            cleaned.append(pair)
            seen.add(pair)
        if len(cleaned) > MAX_TOKEN_COUNT:
            raise ValueError(f"At most {MAX_TOKEN_COUNT} token pairs are allowed")
    return cleaned


def validate_time_range(from_ms: int, to_ms: int) -> None:
    if from_ms > to_ms:
        raise ValueError("From IST must be earlier than or equal to To IST")

