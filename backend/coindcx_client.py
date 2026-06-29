"""Small, read-only CoinDCX Futures API client.

Only reporting endpoints are intentionally exposed. Order creation, editing,
cancellation, margin transfer, and position exit methods do not exist here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

from .config import (
    COINDCX_BASE_URL,
    REQUEST_BACKOFF_SECONDS,
    REQUEST_CONNECT_TIMEOUT_SECONDS,
    REQUEST_MAX_ATTEMPTS,
    REQUEST_READ_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CoinDCXAPIError(Exception):
    """Sanitized API error safe to pass to the HTTP layer."""

    message: str
    status_code: int | None = None
    retryable: bool = False
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


class CoinDCXClient:
    """Authenticated, read-only client for the Futures reporting endpoints."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        base_url: str = COINDCX_BASE_URL,
        timeout: tuple[float, float] = (
            REQUEST_CONNECT_TIMEOUT_SECONDS,
            REQUEST_READ_TIMEOUT_SECONDS,
        ),
        max_attempts: int = REQUEST_MAX_ATTEMPTS,
        backoff_seconds: float = REQUEST_BACKOFF_SECONDS,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("API key is required")
        if not api_secret or not api_secret.strip():
            raise ValueError("API secret is required")

        self.api_key = api_key.strip()
        self._api_secret = api_secret.strip().encode("utf-8")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_attempts = max(1, max_attempts)
        self.backoff_seconds = max(0.0, backoff_seconds)
        self._session = session or requests.Session()

    def _sign(self, body: str) -> str:
        return hmac.new(self._api_secret, body.encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _safe_error_message(status_code: int, payload: Any) -> str:
        if isinstance(payload, dict):
            raw = payload.get("message") or payload.get("error") or payload.get("reason")
            if raw:
                return str(raw)[:300]
        if status_code in {401, 403}:
            return "CoinDCX rejected the API credentials or endpoint permission."
        if status_code == 429:
            return "CoinDCX rate limit reached. Please wait briefly and retry."
        if status_code >= 500:
            return "CoinDCX is temporarily unavailable."
        return f"CoinDCX request failed with HTTP {status_code}."

    def _signed_request(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        base_payload = dict(payload or {})
        url = f"{self.base_url}{endpoint}"

        for attempt in range(1, self.max_attempts + 1):
            request_payload = dict(base_payload)
            request_payload["timestamp"] = int(time.time() * 1000)
            body = json.dumps(request_payload, separators=(",", ":"), ensure_ascii=False)
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-AUTH-APIKEY": self.api_key,
                "X-AUTH-SIGNATURE": self._sign(body),
            }
            try:
                response = self._session.request(
                    method.upper(),
                    url,
                    data=body,
                    headers=headers,
                    timeout=self.timeout,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt < self.max_attempts:
                    time.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
                    continue
                logger.warning("CoinDCX network failure on %s %s: %s", method, endpoint, type(exc).__name__)
                raise CoinDCXAPIError(
                    "Could not reach CoinDCX. Check your network and try again.",
                    retryable=True,
                ) from exc
            except requests.RequestException as exc:
                logger.warning("CoinDCX request failure on %s %s: %s", method, endpoint, type(exc).__name__)
                raise CoinDCXAPIError("CoinDCX request could not be completed.") from exc

            try:
                data = response.json()
            except ValueError as exc:
                snippet = (response.text or "")[:120]
                logger.warning(
                    "Invalid JSON from CoinDCX on %s %s (HTTP %s): %r",
                    method,
                    endpoint,
                    response.status_code,
                    snippet,
                )
                raise CoinDCXAPIError(
                    "CoinDCX returned an unreadable response.",
                    status_code=response.status_code,
                    retryable=response.status_code >= 500,
                ) from exc

            if 200 <= response.status_code < 300:
                return data

            retryable = response.status_code == 429 or response.status_code >= 500
            if retryable and attempt < self.max_attempts:
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = min(float(retry_after), 10.0) if retry_after else self.backoff_seconds * (2 ** (attempt - 1))
                except (TypeError, ValueError):
                    delay = self.backoff_seconds * (2 ** (attempt - 1))
                time.sleep(max(0.0, delay))
                continue

            message = self._safe_error_message(response.status_code, data)
            logger.warning(
                "CoinDCX API error on %s %s: HTTP %s",
                method,
                endpoint,
                response.status_code,
            )
            raise CoinDCXAPIError(
                message,
                status_code=response.status_code,
                retryable=retryable,
                details={"endpoint": endpoint},
            )

        raise CoinDCXAPIError("CoinDCX request failed after retries.", retryable=True)

    def get_transactions(
        self,
        stage: str = "all",
        page: int = 1,
        size: int = 100,
        margin_currency_short_name: list[str] | None = None,
    ) -> Any:
        payload = {
            "stage": stage,
            "page": int(page),
            "size": int(size),
            "margin_currency_short_name": margin_currency_short_name or ["INR"],
        }
        return self._signed_request(
            "POST",
            "/exchange/v1/derivatives/futures/positions/transactions",
            payload,
        )

    def get_wallet_details(self) -> Any:
        return self._signed_request("GET", "/exchange/v1/derivatives/futures/wallets")

    def close(self) -> None:
        self._session.close()
        self._api_secret = b""

