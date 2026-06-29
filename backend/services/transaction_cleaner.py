"""Dynamic transaction normalization, filtering, and cumulative calculations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd


NUMERIC_COLUMNS = [
    "amount",
    "fee_amount",
    "price",
    "quantity",
    "size",
    "value",
    "total",
    "executed_qty",
    "executed_value",
]

EXPECTED_COLUMNS = [
    "_idx",
    "created_at",
    "datetime",
    "datetime_ist",
    "date_ist",
    "_date_ist",
    "day_of_week",
    "is_weekend",
    "pair",
    "position_id",
    "parent_type",
    "stage",
    "amount",
    "fee_amount",
    "is_win",
    "is_loss",
    "trade_result",
    "net_amount",
    "cum_pnl",
    "cum_net",
    "cum_fee",
    "peak_gross_pnl",
    "drawdown_gross",
    "peak_net_pnl",
    "drawdown_net",
]


def _empty_dataframe(extra_columns: Sequence[str] | None = None) -> pd.DataFrame:
    columns = list(dict.fromkeys([*(extra_columns or []), *EXPECTED_COLUMNS]))
    return pd.DataFrame(columns=columns)


def transactions_to_dataframe(
    transactions: list[dict[str, Any]],
    include_pairs: list[str] | None = None,
    exclude_pairs: list[str] | None = None,
    min_timestamp: int | None = None,
    max_timestamp: int | None = None,
    include_zero_amounts: bool = True,
    exclude_liquidate_stage: bool = True,
    excluded_position_ids: list[str] | None = None,
    force_exclude_xau: bool = True,
    normalize_fee_abs: bool = True,
) -> pd.DataFrame:
    raw_rows = [row for row in transactions if isinstance(row, dict)]
    raw_columns = sorted({str(key) for row in raw_rows for key in row.keys()})
    if not raw_rows:
        return _empty_dataframe(raw_columns)

    records: list[dict[str, Any]] = []
    for index, source in enumerate(raw_rows):
        row = {str(key): value for key, value in source.items()}
        row["_idx"] = index
        records.append(row)

    df = pd.DataFrame.from_records(records)
    for column in raw_columns:
        if column not in df.columns:
            df[column] = None

    if "stage" not in df.columns:
        df["stage"] = ""
    if "position_id" not in df.columns:
        df["position_id"] = ""
    if "pair" not in df.columns:
        df["pair"] = ""

    df["stage"] = df["stage"].fillna("").astype(str).str.strip()
    df["position_id"] = df["position_id"].fillna("").astype(str).str.strip()
    df["pair"] = df["pair"].fillna("").astype(str).str.strip()

    if exclude_liquidate_stage:
        df = df[df["stage"].str.lower() != "liquidate"]

    excluded_ids = {str(value).strip() for value in (excluded_position_ids or []) if str(value).strip()}
    if excluded_ids:
        df = df[~df["position_id"].isin(excluded_ids)]

    include_set = {str(value).strip() for value in (include_pairs or []) if str(value).strip()}
    exclude_set = {str(value).strip() for value in (exclude_pairs or []) if str(value).strip()}
    if include_set:
        df = df[df["pair"].isin(include_set)]
    if exclude_set:
        df = df[~df["pair"].isin(exclude_set)]
    if force_exclude_xau:
        df = df[~df["pair"].str.contains("XAU", case=False, na=False)]

    for column in NUMERIC_COLUMNS:
        if column not in df.columns:
            df[column] = 0.0
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)

    if "created_at" not in df.columns:
        df["created_at"] = np.nan
    created_at = pd.to_numeric(df["created_at"], errors="coerce")
    df["created_at"] = created_at
    if min_timestamp is not None:
        df = df[df["created_at"].notna() & (df["created_at"] >= int(min_timestamp))]
    if max_timestamp is not None:
        df = df[df["created_at"].notna() & (df["created_at"] <= int(max_timestamp))]
    if not include_zero_amounts:
        df = df[df["amount"] != 0]

    if df.empty:
        return _empty_dataframe(raw_columns)

    df["datetime"] = pd.to_datetime(df["created_at"], unit="ms", utc=True, errors="coerce")
    df["datetime_ist"] = df["datetime"].dt.tz_convert("Asia/Kolkata")
    df["date_ist"] = df["datetime_ist"].dt.date
    df["_date_ist"] = df["datetime_ist"].dt.normalize()
    df["day_of_week"] = df["datetime_ist"].dt.day_name()
    df["is_weekend"] = df["datetime_ist"].dt.dayofweek.ge(5).fillna(False)

    df["is_win"] = df["amount"] > 0
    df["is_loss"] = df["amount"] < 0
    df["trade_result"] = np.select(
        [df["amount"] > 0, df["amount"] < 0],
        ["WIN", "LOSS"],
        default="NEUTRAL",
    )
    fee_for_net = df["fee_amount"].abs() if normalize_fee_abs else df["fee_amount"]
    df["net_amount"] = df["amount"] - fee_for_net

    df = df.sort_values(["datetime", "_idx"], kind="stable", na_position="last").reset_index(drop=True)
    df["cum_pnl"] = df["amount"].cumsum()
    df["cum_net"] = df["net_amount"].cumsum()
    df["cum_fee"] = df["fee_amount"].abs().cumsum()
    df["peak_gross_pnl"] = df["cum_pnl"].cummax()
    df["drawdown_gross"] = df["peak_gross_pnl"] - df["cum_pnl"]
    df["peak_net_pnl"] = df["cum_net"].cummax()
    df["drawdown_net"] = df["peak_net_pnl"] - df["cum_net"]

    return df.reset_index(drop=True)

