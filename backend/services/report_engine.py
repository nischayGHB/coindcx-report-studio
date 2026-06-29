"""End-to-end report orchestration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from ..models.schemas import MultiTokenReportRequest, SingleTokenReportRequest
from ..utils.file_utils import sanitize_filename
from ..utils.time_utils import parse_ist_datetime_to_ms
from ..utils.validation_utils import validate_time_range
from .daily_report_engine import build_daywise_report
from .export_engine import (
    REPORTS,
    ReportMetadata,
    create_report_id,
    dataframe_preview,
    download_url,
    export_dataframe,
    export_json,
    report_folder,
)
from .metrics_engine import build_token_breakdown, generate_summary
from .transaction_cleaner import transactions_to_dataframe
from .transaction_fetcher import fetch_all_transactions


def _time_bounds(from_ist: str, to_ist: str) -> tuple[int, int]:
    from_ms = parse_ist_datetime_to_ms(from_ist)
    to_ms = parse_ist_datetime_to_ms(to_ist)
    validate_time_range(from_ms, to_ms)
    return from_ms, to_ms


def _response(
    report_id: str,
    summary: dict[str, Any],
    files: dict[str, str],
    clean: pd.DataFrame,
    daywise: pd.DataFrame,
    token_breakdown: pd.DataFrame,
    messages: list[str],
) -> dict[str, Any]:
    return {
        "success": True,
        "report_id": report_id,
        "summary": summary,
        "files": {key: download_url(report_id, filename) for key, filename in files.items()},
        "preview": {
            "transactions": dataframe_preview(clean),
            "daywise": dataframe_preview(daywise),
            "token_breakdown": dataframe_preview(token_breakdown),
        },
        "columns": {
            "transactions": clean.columns.tolist(),
            "daywise": daywise.columns.tolist(),
            "token_breakdown": token_breakdown.columns.tolist(),
        },
        "messages": messages,
    }


def _generate(
    *,
    client: Any,
    session_id: str,
    kind: str,
    margin_currency: str,
    from_ist: str,
    to_ist: str,
    include_pairs: list[str],
    exclude_pairs: list[str],
    include_zero_amounts: bool,
    exclude_liquidate_stage: bool,
    excluded_position_ids: list[str],
    force_exclude_xau: bool,
    initial_capital: float,
    max_pages: int | None,
    page_size: int,
    token_filename: str | None = None,
) -> dict[str, Any]:
    messages: list[str] = ["Validated request and converted IST range to epoch milliseconds."]
    from_ms, to_ms = _time_bounds(from_ist, to_ist)
    raw = fetch_all_transactions(
        client,
        margin_currency=margin_currency,
        max_pages=max_pages,
        page_size=page_size,
        messages=messages,
    )
    clean = transactions_to_dataframe(
        raw,
        include_pairs=include_pairs,
        exclude_pairs=exclude_pairs,
        min_timestamp=from_ms,
        max_timestamp=to_ms,
        include_zero_amounts=include_zero_amounts,
        exclude_liquidate_stage=exclude_liquidate_stage,
        excluded_position_ids=excluded_position_ids,
        force_exclude_xau=force_exclude_xau,
    )
    messages.append(f"Filtered and normalized the result to {len(clean)} rows.")
    daywise = build_daywise_report(clean, initial_capital=initial_capital)
    messages.append(f"Built {len(daywise)} Asia/Kolkata day rows.")
    token_breakdown = build_token_breakdown(clean) if kind == "multi" else pd.DataFrame()
    summary = generate_summary(clean, daywise, initial_capital)

    report_id = create_report_id(kind)
    folder = report_folder(report_id)
    if kind == "multi":
        filenames = {
            "clean_transactions_csv": "clean_transactions_multi.csv",
            "daywise_csv": "daywise_stats_multi.csv",
            "token_breakdown_csv": "token_breakdown_multi.csv",
            "summary_json": "summary_multi.json",
        }
    else:
        safe_token = sanitize_filename(token_filename or "token")
        filenames = {
            "clean_transactions_csv": f"clean_transactions_{safe_token}.csv",
            "daywise_csv": f"daywise_stats_{safe_token}.csv",
            "summary_json": f"summary_{safe_token}.json",
        }

    export_dataframe(clean, folder / filenames["clean_transactions_csv"])
    export_dataframe(daywise, folder / filenames["daywise_csv"])
    if kind == "multi":
        export_dataframe(token_breakdown, folder / filenames["token_breakdown_csv"])
    export_json(summary, folder / filenames["summary_json"])
    messages.append("Exported CSV and JSON files.")

    REPORTS.register(
        ReportMetadata(
            report_id=report_id,
            session_id=session_id,
            kind=kind,
            created_at=datetime.now(timezone.utc),
            folder=folder,
            clean_filename=filenames["clean_transactions_csv"],
            files=dict(filenames),
            summary=summary,
        )
    )
    return _response(report_id, summary, filenames, clean, daywise, token_breakdown, messages)


def generate_multi_token_report(client: Any, request: MultiTokenReportRequest) -> dict[str, Any]:
    return _generate(
        client=client,
        session_id=request.session_id,
        kind="multi",
        margin_currency=request.margin_currency,
        from_ist=request.from_ist,
        to_ist=request.to_ist,
        include_pairs=request.tokens,
        exclude_pairs=request.exclude_tokens,
        include_zero_amounts=request.include_zero_amounts,
        exclude_liquidate_stage=request.exclude_liquidate_stage,
        excluded_position_ids=request.excluded_position_ids,
        force_exclude_xau=request.force_exclude_xau,
        initial_capital=request.initial_capital,
        max_pages=request.max_pages,
        page_size=request.page_size,
    )


def generate_single_token_report(client: Any, request: SingleTokenReportRequest) -> dict[str, Any]:
    return _generate(
        client=client,
        session_id=request.session_id,
        kind="single",
        margin_currency=request.margin_currency,
        from_ist=request.from_ist,
        to_ist=request.to_ist,
        include_pairs=[request.token],
        exclude_pairs=[],
        include_zero_amounts=request.include_zero_amounts,
        exclude_liquidate_stage=request.exclude_liquidate_stage,
        excluded_position_ids=request.excluded_position_ids,
        force_exclude_xau=request.force_exclude_xau,
        initial_capital=request.initial_capital,
        max_pages=request.max_pages,
        page_size=request.page_size,
        token_filename=request.token,
    )


def convert_existing_report_to_daily(
    session_id: str,
    report_id: str,
    initial_capital: float,
    *,
    zero_zero_as_funding: bool,
    trade_count_mode: str,
) -> dict[str, Any]:
    metadata = REPORTS.get(report_id, session_id)
    clean_path = metadata.folder / metadata.clean_filename
    clean = pd.read_csv(clean_path)
    daywise = build_daywise_report(
        clean,
        initial_capital=initial_capital,
        zero_zero_as_funding=zero_zero_as_funding,
        trade_count_mode=trade_count_mode,
    )
    summary = generate_summary(clean, daywise, initial_capital)
    day_filename = "daywise_stats_converted.csv"
    summary_filename = "summary_converted.json"
    export_dataframe(daywise, metadata.folder / day_filename)
    export_json(summary, metadata.folder / summary_filename)
    REPORTS.update_file(report_id, "daywise_csv", day_filename)
    REPORTS.update_file(report_id, "summary_json", summary_filename)
    files = dict(metadata.files)
    files["daywise_csv"] = day_filename
    files["summary_json"] = summary_filename
    return _response(
        report_id,
        summary,
        files,
        clean,
        daywise,
        pd.DataFrame(),
        [
            f"Loaded {len(clean)} rows from the generated clean report.",
            f"Built {len(daywise)} daily rows.",
            "Exported the converted daywise CSV and summary JSON.",
        ],
    )

