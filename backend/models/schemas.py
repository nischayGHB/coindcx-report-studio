"""Validated API request schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..config import DEFAULT_BAD_POSITION_IDS, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from ..utils.validation_utils import normalize_pair, normalize_token_list


MarginCurrency = Literal["INR", "USDT"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AuthRequest(StrictModel):
    api_key: str = Field(min_length=1, max_length=500)
    api_secret: str = Field(min_length=1, max_length=500)
    margin_currency: MarginCurrency = "INR"


class LogoutRequest(StrictModel):
    session_id: str = Field(min_length=20, max_length=200)


class ReportBaseRequest(StrictModel):
    session_id: str = Field(min_length=20, max_length=200)
    margin_currency: MarginCurrency = "INR"
    from_ist: str = Field(min_length=17, max_length=17)
    to_ist: str = Field(min_length=17, max_length=17)
    include_zero_amounts: bool = True
    exclude_liquidate_stage: bool = True
    force_exclude_xau: bool = True
    excluded_position_ids: list[str] = Field(default_factory=lambda: list(DEFAULT_BAD_POSITION_IDS), max_length=1_000)
    initial_capital: float = Field(default=5_000, gt=0, le=1e15)
    max_pages: int | None = Field(default=None, ge=1, le=100_000)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)

    @field_validator("excluded_position_ids")
    @classmethod
    def clean_position_ids(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = str(value).strip()
            if item and item not in seen:
                cleaned.append(item)
                seen.add(item)
        return cleaned


class MultiTokenReportRequest(ReportBaseRequest):
    tokens: list[str] = Field(min_length=1, max_length=500)
    exclude_tokens: list[str] = Field(default_factory=list, max_length=500)

    @field_validator("tokens", "exclude_tokens")
    @classmethod
    def clean_tokens(cls, values: list[str]) -> list[str]:
        return normalize_token_list(values)


class SingleTokenReportRequest(ReportBaseRequest):
    token: str = Field(min_length=3, max_length=120)
    initial_capital: float = Field(default=20_000, gt=0, le=1e15)

    @field_validator("token")
    @classmethod
    def clean_token(cls, value: str) -> str:
        return normalize_pair(value)


class DailyFromReportRequest(StrictModel):
    session_id: str = Field(min_length=20, max_length=200)
    report_id: str = Field(min_length=10, max_length=100)
    initial_capital: float = Field(default=20_000, gt=0, le=1e15)
    funding_detection_mode: Literal[
        "parent_type_stage_and_zero_heuristic",
        "parent_type_and_stage_only",
    ] = "parent_type_stage_and_zero_heuristic"
    trade_count_mode: Literal[
        "transaction_pairs",
        "transaction_rows",
        "position_id",
    ] = "transaction_pairs"

