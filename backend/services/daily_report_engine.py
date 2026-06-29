"""Funding classification and detailed Asia/Kolkata daywise reporting."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


DAYWISE_COLUMNS = [
    "date",
    "total_tx_rows",
    "total_trades",
    "wins",
    "losses",
    "win_rate",
    "gross_pnl",
    "total_fees",
    "net_pnl",
    "gross_per_trade",
    "fee_per_trade",
    "net_per_trade",
    "max_intraday_drawdown",
    "max_intraday_drawdown_pct",
    "funding_count",
    "funding_gross_sum",
    "cum_gross_pnl",
    "cum_net_pnl",
    "cum_fees",
    "cum_trades",
    "starting_equity",
    "ending_equity",
    "peak_equity",
    "equity_drawdown_abs",
    "equity_drawdown_pct",
    "daily_return_pct",
]


def _empty_daywise() -> pd.DataFrame:
    return pd.DataFrame(columns=DAYWISE_COLUMNS)


def _timestamp_to_ist(value: Any) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return pd.NaT
    if pd.isna(timestamp):
        return pd.NaT
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("Asia/Kolkata")
    return timestamp.tz_convert("Asia/Kolkata")


def ensure_datetime_ist(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    if "datetime_ist" in work.columns:
        work["datetime_ist"] = work["datetime_ist"].map(_timestamp_to_ist)
        return work
    if "datetime" in work.columns:
        utc_values = pd.to_datetime(work["datetime"], errors="coerce", utc=True)
        work["datetime_ist"] = utc_values.dt.tz_convert("Asia/Kolkata")
        return work
    if "created_at" in work.columns:
        created = pd.to_numeric(work["created_at"], errors="coerce")
        work["datetime"] = pd.to_datetime(created, unit="ms", errors="coerce", utc=True)
        work["datetime_ist"] = work["datetime"].dt.tz_convert("Asia/Kolkata")
        return work
    work["datetime_ist"] = pd.NaT
    return work


def classify_rows(df: pd.DataFrame, zero_zero_as_funding: bool = True) -> pd.DataFrame:
    work = df.copy()
    is_funding = pd.Series(False, index=work.index, dtype=bool)
    if "parent_type" in work.columns:
        is_funding |= work["parent_type"].fillna("").astype(str).str.strip().str.lower().eq("funding")
    if "stage" in work.columns:
        is_funding |= work["stage"].fillna("").astype(str).str.strip().str.lower().eq("funding")

    amount = pd.to_numeric(work.get("amount", pd.Series(0, index=work.index)), errors="coerce").fillna(0.0)
    fee = pd.to_numeric(work.get("fee_amount", pd.Series(0, index=work.index)), errors="coerce").fillna(0.0)
    if zero_zero_as_funding:
        is_funding |= (amount == 0) & (fee == 0)

    work["is_funding"] = is_funding
    work["row_type"] = np.select(
        [is_funding, amount != 0],
        ["FUNDING", "TRADE"],
        default="OTHER",
    )
    return work


def _estimated_trade_count(group: pd.DataFrame, mode: str) -> int:
    count = len(group)
    if count == 0:
        return 0
    if mode == "transaction_rows":
        return count
    if mode == "position_id" and "position_id" in group.columns:
        position_count = group["position_id"].dropna().astype(str).str.strip().replace("", np.nan).dropna().nunique()
        if position_count:
            return int(position_count)
    return max(count // 2, 1)


def build_daywise_report(
    df: pd.DataFrame,
    initial_capital: float,
    zero_zero_as_funding: bool = True,
    trade_count_mode: str = "transaction_pairs",
) -> pd.DataFrame:
    if df.empty:
        return _empty_daywise()
    if trade_count_mode not in {"transaction_pairs", "transaction_rows", "position_id"}:
        raise ValueError("Invalid trade count mode")

    work = classify_rows(ensure_datetime_ist(df), zero_zero_as_funding=zero_zero_as_funding)
    work = work[work["datetime_ist"].notna()].copy()
    if work.empty:
        return _empty_daywise()
    work = work.sort_values("datetime_ist", kind="stable")
    work["_date_ist"] = work["datetime_ist"].dt.normalize()
    work["amount"] = pd.to_numeric(work.get("amount", 0), errors="coerce").fillna(0.0)
    work["fee_amount"] = pd.to_numeric(work.get("fee_amount", 0), errors="coerce").fillna(0.0).abs()

    trade_rows = work[~work["is_funding"]].copy()
    funding_rows = work[work["is_funding"]].copy()
    dates = sorted(work["_date_ist"].dropna().unique())
    records: list[dict[str, Any]] = []

    for date in dates:
        trades = trade_rows[trade_rows["_date_ist"] == date]
        funding = funding_rows[funding_rows["_date_ist"] == date]
        amount = trades["amount"]
        fees = trades["fee_amount"]
        gross = float(amount.sum())
        total_fees = float(fees.sum())
        net = gross - total_fees
        wins = int((amount > 0).sum())
        losses = int((amount < 0).sum())
        estimated = _estimated_trade_count(trades, trade_count_mode)

        running = 0.0
        peak = 0.0
        max_intraday_dd = 0.0
        for value in amount.to_numpy(dtype=float):
            running += value
            peak = max(peak, running)
            max_intraday_dd = max(max_intraday_dd, peak - running)

        records.append(
            {
                "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
                "total_tx_rows": int(len(trades)),
                "total_trades": estimated,
                "wins": wins,
                "losses": losses,
                "win_rate": wins / (wins + losses) if wins + losses else np.nan,
                "gross_pnl": gross,
                "total_fees": total_fees,
                "net_pnl": net,
                "gross_per_trade": gross / estimated if estimated else np.nan,
                "fee_per_trade": total_fees / estimated if estimated else np.nan,
                "net_per_trade": net / estimated if estimated else np.nan,
                "max_intraday_drawdown": max_intraday_dd,
                "max_intraday_drawdown_pct": max_intraday_dd / initial_capital * 100 if initial_capital else np.nan,
                "funding_count": int(len(funding)),
                "funding_gross_sum": float(funding["amount"].sum()),
            }
        )

    result = pd.DataFrame.from_records(records).sort_values("date").reset_index(drop=True)
    result["cum_gross_pnl"] = result["gross_pnl"].cumsum()
    result["cum_net_pnl"] = result["net_pnl"].cumsum()
    result["cum_fees"] = result["total_fees"].cumsum()
    result["cum_trades"] = result["total_trades"].cumsum().astype(int)

    running_equity = float(initial_capital)
    peak_equity = float(initial_capital)
    equity_rows: list[tuple[float, float, float, float, float, float]] = []
    for net_pnl in result["net_pnl"].fillna(0).to_numpy(dtype=float):
        start = running_equity
        running_equity += net_pnl
        peak_equity = max(peak_equity, running_equity)
        drawdown = peak_equity - running_equity
        equity_rows.append(
            (
                start,
                running_equity,
                peak_equity,
                drawdown,
                drawdown / peak_equity * 100 if peak_equity else 0.0,
                net_pnl / start * 100 if start else np.nan,
            )
        )
    result[
        [
            "starting_equity",
            "ending_equity",
            "peak_equity",
            "equity_drawdown_abs",
            "equity_drawdown_pct",
            "daily_return_pct",
        ]
    ] = pd.DataFrame(equity_rows, index=result.index)

    numeric_columns = result.select_dtypes(include=[np.number]).columns
    result[numeric_columns] = result[numeric_columns].round(6)
    return result[DAYWISE_COLUMNS]

