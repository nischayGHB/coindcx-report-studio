"""Overall and token-level performance metrics."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .daily_report_engine import classify_rows


def _nullable_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _sharpe(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if len(numeric) < 2:
        return None
    std = float(numeric.std(ddof=1))
    if not math.isfinite(std) or std == 0:
        return None
    return float(numeric.mean() / std)


def generate_summary(clean_df: pd.DataFrame, daywise_df: pd.DataFrame, initial_capital: float) -> dict[str, Any]:
    classified = classify_rows(clean_df, zero_zero_as_funding=True) if not clean_df.empty else clean_df.copy()
    amount = pd.to_numeric(clean_df.get("amount", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    fees = pd.to_numeric(clean_df.get("fee_amount", pd.Series(dtype=float)), errors="coerce").fillna(0.0).abs()
    net = pd.to_numeric(clean_df.get("net_amount", amount - fees), errors="coerce").fillna(0.0)
    wins = amount[amount > 0]
    losses = amount[amount < 0]
    total_decisions = len(wins) + len(losses)
    gross_profit = float(wins.sum())
    gross_loss = abs(float(losses.sum()))
    gross_pnl = float(amount.sum())
    total_fees = float(fees.sum())
    net_pnl = float(net.sum())

    daily_pnl = pd.to_numeric(daywise_df.get("net_pnl", pd.Series(dtype=float)), errors="coerce").dropna()
    daily_returns = pd.to_numeric(daywise_df.get("daily_return_pct", pd.Series(dtype=float)), errors="coerce").dropna()
    pnl_sharpe = _sharpe(daily_pnl)
    return_sharpe = _sharpe(daily_returns)

    def date_range(column: str) -> dict[str, str | None]:
        if clean_df.empty or column not in clean_df.columns:
            return {"start": None, "end": None}
        valid = clean_df[column].dropna()
        return {
            "start": str(valid.min()) if not valid.empty else None,
            "end": str(valid.max()) if not valid.empty else None,
        }

    best_day = None
    worst_day = None
    if not daywise_df.empty and "net_pnl" in daywise_df.columns:
        best_row = daywise_df.loc[daywise_df["net_pnl"].idxmax()]
        worst_row = daywise_df.loc[daywise_df["net_pnl"].idxmin()]
        best_day = {"date": str(best_row.get("date")), "net_pnl": _nullable_float(best_row.get("net_pnl"))}
        worst_day = {"date": str(worst_row.get("date")), "net_pnl": _nullable_float(worst_row.get("net_pnl"))}

    max_transaction_dd = _nullable_float(clean_df.get("drawdown_net", pd.Series(dtype=float)).max()) or 0.0
    max_equity_dd = _nullable_float(daywise_df.get("equity_drawdown_abs", pd.Series(dtype=float)).max()) or 0.0
    max_equity_dd_pct = _nullable_float(daywise_df.get("equity_drawdown_pct", pd.Series(dtype=float)).max()) or 0.0

    pairs = []
    if "pair" in clean_df.columns:
        pairs = sorted(clean_df["pair"].dropna().astype(str).loc[lambda value: value.str.len() > 0].unique().tolist())

    insufficient = len(daily_pnl) < 2 or len(daily_returns) < 2
    return {
        "total_transactions": int(len(clean_df)),
        "total_trade_rows": int((~classified["is_funding"]).sum()) if not classified.empty else 0,
        "total_estimated_trades": int(daywise_df.get("total_trades", pd.Series(dtype=float)).sum()) if not daywise_df.empty else 0,
        "total_funding_rows": int(classified["is_funding"].sum()) if not classified.empty else 0,
        "unique_pairs": len(pairs),
        "pairs_list": pairs,
        "date_range_utc": date_range("datetime"),
        "date_range_ist": date_range("datetime_ist"),
        "gross_pnl": round(gross_pnl, 6),
        "total_fees": round(total_fees, 6),
        "net_pnl": round(net_pnl, 6),
        "roi_pct": round(net_pnl / initial_capital * 100, 6) if initial_capital else None,
        "initial_capital": float(initial_capital),
        "total_wins": int(len(wins)),
        "total_losses": int(len(losses)),
        "win_rate": round(len(wins) / total_decisions, 6) if total_decisions else None,
        "average_win": _nullable_float(wins.mean()),
        "average_loss": _nullable_float(losses.mean()),
        "payoff_ratio": _nullable_float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) and losses.mean() else None,
        "profit_factor": _nullable_float(gross_profit / gross_loss) if gross_loss else None,
        "best_transaction": _nullable_float(amount.max()) if len(amount) else None,
        "worst_transaction": _nullable_float(amount.min()) if len(amount) else None,
        "best_day": best_day,
        "worst_day": worst_day,
        "max_drawdown_abs": round(max_transaction_dd, 6),
        "max_drawdown_pct": round(max_transaction_dd / initial_capital * 100, 6) if initial_capital else None,
        "max_equity_drawdown_abs": round(max_equity_dd, 6),
        "max_equity_drawdown_pct": round(max_equity_dd_pct, 6),
        "daily_pnl_sharpe": _nullable_float(pnl_sharpe),
        "daily_return_sharpe": _nullable_float(return_sharpe),
        "annualized_pnl_sharpe": _nullable_float(pnl_sharpe * math.sqrt(365.25)) if pnl_sharpe is not None else None,
        "annualized_return_sharpe": _nullable_float(return_sharpe * math.sqrt(365.25)) if return_sharpe is not None else None,
        "sharpe_message": "At least two daily observations are required for Sharpe." if insufficient else None,
        "average_daily_pnl": _nullable_float(daily_pnl.mean()),
        "standard_deviation_daily_pnl": _nullable_float(daily_pnl.std(ddof=1)) if len(daily_pnl) >= 2 else None,
    }


TOKEN_COLUMNS = [
    "pair",
    "tx_rows",
    "estimated_trades",
    "gross_pnl",
    "total_fees",
    "net_pnl",
    "wins",
    "losses",
    "win_rate",
    "avg_amount",
    "avg_net",
    "best_tx",
    "worst_tx",
    "first_trade_ist",
    "last_trade_ist",
    "contribution_to_total_net_pct",
]


def build_token_breakdown(clean_df: pd.DataFrame) -> pd.DataFrame:
    if clean_df.empty or "pair" not in clean_df.columns:
        return pd.DataFrame(columns=TOKEN_COLUMNS)
    total_net = float(pd.to_numeric(clean_df["net_amount"], errors="coerce").fillna(0).sum())
    rows: list[dict[str, Any]] = []
    for pair, group in clean_df.groupby("pair", sort=False):
        amount = pd.to_numeric(group["amount"], errors="coerce").fillna(0.0)
        fee = pd.to_numeric(group["fee_amount"], errors="coerce").fillna(0.0).abs()
        net = pd.to_numeric(group["net_amount"], errors="coerce").fillna(0.0)
        wins = int((amount > 0).sum())
        losses = int((amount < 0).sum())
        net_sum = float(net.sum())
        rows.append(
            {
                "pair": pair,
                "tx_rows": int(len(group)),
                "estimated_trades": max(len(group) // 2, 1),
                "gross_pnl": float(amount.sum()),
                "total_fees": float(fee.sum()),
                "net_pnl": net_sum,
                "wins": wins,
                "losses": losses,
                "win_rate": wins / (wins + losses) if wins + losses else np.nan,
                "avg_amount": float(amount.mean()),
                "avg_net": float(net.mean()),
                "best_tx": float(amount.max()),
                "worst_tx": float(amount.min()),
                "first_trade_ist": str(group["datetime_ist"].min()) if "datetime_ist" in group else None,
                "last_trade_ist": str(group["datetime_ist"].max()) if "datetime_ist" in group else None,
                "contribution_to_total_net_pct": net_sum / total_net * 100 if total_net else np.nan,
            }
        )
    return pd.DataFrame(rows, columns=TOKEN_COLUMNS).sort_values("net_pnl", ascending=False).reset_index(drop=True)

