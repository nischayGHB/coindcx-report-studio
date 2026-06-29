"""Resilient pagination for CoinDCX futures transactions."""

from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)


class TransactionFetchError(RuntimeError):
    pass


def _extract_rows(response: Any) -> list[dict[str, Any]]:
    if response is None:
        return []
    if isinstance(response, list):
        return [row for row in response if isinstance(row, dict)]
    if isinstance(response, dict):
        for key in ("data", "transactions", "result", "results"):
            candidate = response.get(key)
            if isinstance(candidate, list):
                return [row for row in candidate if isinstance(row, dict)]
        return [response] if response else []
    return []


def fetch_all_transactions(
    client: Any,
    margin_currency: str = "INR",
    max_pages: int | None = None,
    page_size: int = 100,
    logger_instance: logging.Logger | None = None,
    messages: list[str] | None = None,
) -> list[dict[str, Any]]:
    log = logger_instance or logger
    event_log = messages if messages is not None else []
    rows_all: list[dict[str, Any]] = []
    page = 1

    while True:
        try:
            response = client.get_transactions(
                stage="all",
                page=page,
                size=page_size,
                margin_currency_short_name=[margin_currency],
            )
        except Exception as exc:
            if rows_all:
                warning = f"Page {page} failed after retries; kept {len(rows_all)} rows fetched earlier."
                event_log.append(warning)
                log.warning("%s Cause: %s", warning, exc)
                break
            raise TransactionFetchError(f"Could not fetch transactions: {exc}") from exc

        rows = _extract_rows(response)
        if response is not None and not isinstance(response, (list, dict)):
            if rows_all:
                event_log.append(f"Stopped at page {page}: CoinDCX returned an unexpected response shape.")
                break
            raise TransactionFetchError("CoinDCX returned an unexpected transaction response.")

        if not rows:
            if page == 1:
                event_log.append("CoinDCX returned no transactions for this margin currency.")
            break

        rows_all.extend(rows)
        event_log.append(f"Fetched page {page}: {len(rows)} rows")
        log.info("Fetched CoinDCX transaction page %s (%s rows)", page, len(rows))

        if max_pages is not None and page >= max_pages:
            event_log.append(f"Stopped at the configured {max_pages}-page limit.")
            break
        if len(rows) < page_size:
            break
        page += 1

    event_log.append(f"Fetched {len(rows_all)} transactions in total.")
    return rows_all

