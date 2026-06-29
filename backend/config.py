"""Application configuration and safe reporting defaults."""

from __future__ import annotations

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
OUTPUTS_DIR = Path(__file__).resolve().parent / "outputs"

COINDCX_BASE_URL = "https://api.coindcx.com"
REQUEST_CONNECT_TIMEOUT_SECONDS = 5.0
REQUEST_READ_TIMEOUT_SECONDS = 25.0
REQUEST_MAX_ATTEMPTS = 3
REQUEST_BACKOFF_SECONDS = 0.6

SESSION_TTL_SECONDS = 8 * 60 * 60
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 1_000
MAX_TOKEN_COUNT = 500
PREVIEW_ROW_LIMIT = 200

DEFAULT_BAD_POSITION_IDS = [
    "be09f054-356b-11f1-a6e6-cf5910827b69",
]

