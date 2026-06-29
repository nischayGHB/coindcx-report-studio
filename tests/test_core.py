from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from backend.services.daily_report_engine import build_daywise_report, classify_rows
from backend.services.metrics_engine import build_token_breakdown, generate_summary
from backend.services.transaction_cleaner import transactions_to_dataframe
from backend.services.transaction_fetcher import fetch_all_transactions
from backend.session_store import SessionStore
from backend.utils.file_utils import resolve_safe_report_file
from backend.utils.time_utils import parse_ist_datetime_to_ms
from backend.utils.validation_utils import normalize_token_list


IST = ZoneInfo("Asia/Kolkata")


class TimeAndValidationTests(unittest.TestCase):
    def test_two_digit_year_is_always_20yy(self):
        actual = parse_ist_datetime_to_ms("31/12/99 23:59:59")
        expected = int(datetime(2099, 12, 31, 23, 59, 59, tzinfo=IST).timestamp() * 1000)
        self.assertEqual(actual, expected)

    def test_strict_datetime_rejects_bad_values(self):
        for value in ("1/06/26 09:15:00", "21-06-26 09:15:00", "31/02/26 09:15:00"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_ist_datetime_to_ms(value)

    def test_token_parser_normalizes_and_deduplicates(self):
        self.assertEqual(
            normalize_token_list(" b-eth_usdt, B-SOL_USDT\nB-ETH_USDT "),
            ["B-ETH_USDT", "B-SOL_USDT"],
        )
        with self.assertRaises(ValueError):
            normalize_token_list("ETHUSDT")


class CleanerTests(unittest.TestCase):
    def setUp(self):
        self.start = parse_ist_datetime_to_ms("21/06/26 09:15:00")
        self.end = parse_ist_datetime_to_ms("21/06/26 23:59:59")
        self.bad_id = "be09f054-356b-11f1-a6e6-cf5910827b69"
        self.rows = [
            {"pair": " B-ETH_USDT ", "created_at": self.start, "amount": "100", "fee_amount": "2", "stage": "default", "position_id": "ok"},
            {"pair": "B-ETH_USDT", "created_at": self.start + 1, "amount": -20, "fee_amount": -1, "stage": "LIQUIDATE", "position_id": "ok"},
            {"pair": "B-XAU_USDT", "created_at": self.start + 2, "amount": 30, "fee_amount": 1, "stage": "default", "position_id": "ok"},
            {"pair": "B-SOL_USDT", "created_at": self.start + 3, "amount": 40, "stage": "default", "position_id": self.bad_id},
            {"pair": "B-SOL_USDT", "created_at": self.end + 1, "amount": 50, "fee_amount": None, "stage": "default", "position_id": "ok"},
        ]

    def test_all_filters_and_net_fee_rule(self):
        frame = transactions_to_dataframe(
            self.rows,
            include_pairs=["B-ETH_USDT", "B-SOL_USDT", "B-XAU_USDT"],
            min_timestamp=self.start,
            max_timestamp=self.end,
            excluded_position_ids=[self.bad_id],
            exclude_liquidate_stage=True,
            force_exclude_xau=True,
        )
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["pair"], "B-ETH_USDT")
        self.assertEqual(frame.iloc[0]["net_amount"], 98)
        self.assertIn("datetime_ist", frame.columns)
        self.assertIn("drawdown_net", frame.columns)

    def test_missing_timestamp_is_dropped_when_range_requested(self):
        frame = transactions_to_dataframe(
            [{"pair": "B-ETH_USDT", "amount": 10}],
            min_timestamp=self.start,
            max_timestamp=self.end,
        )
        self.assertTrue(frame.empty)
        self.assertIn("net_amount", frame.columns)

    def test_zero_amount_toggle(self):
        frame = transactions_to_dataframe(
            [{"pair": "B-ETH_USDT", "created_at": self.start, "amount": 0, "fee_amount": 0}],
            include_zero_amounts=False,
        )
        self.assertTrue(frame.empty)


class DailyAndMetricsTests(unittest.TestCase):
    def setUp(self):
        day1 = parse_ist_datetime_to_ms("21/06/26 10:00:00")
        day2 = parse_ist_datetime_to_ms("22/06/26 10:00:00")
        day3 = parse_ist_datetime_to_ms("23/06/26 10:00:00")
        raw = [
            {"pair": "B-ETH_USDT", "created_at": day1, "amount": 100, "fee_amount": 10, "stage": "default", "position_id": "p1"},
            {"pair": "B-ETH_USDT", "created_at": day1 + 1, "amount": -40, "fee_amount": 5, "stage": "default", "position_id": "p1"},
            {"pair": "B-ETH_USDT", "created_at": day1 + 2, "amount": 0, "fee_amount": 0, "stage": "funding"},
            {"pair": "B-SOL_USDT", "created_at": day2, "amount": 30, "fee_amount": 3, "stage": "default", "position_id": "p2"},
            {"pair": "B-SOL_USDT", "created_at": day3, "amount": -200, "fee_amount": 2, "stage": "default", "position_id": "p3"},
        ]
        self.clean = transactions_to_dataframe(raw, force_exclude_xau=False)
        self.daily = build_daywise_report(self.clean, initial_capital=1000)

    def test_funding_classification_and_daily_equity(self):
        classified = classify_rows(self.clean)
        self.assertEqual(int(classified["is_funding"].sum()), 1)
        self.assertEqual(len(self.daily), 3)
        first = self.daily.iloc[0]
        self.assertEqual(first["gross_pnl"], 60)
        self.assertEqual(first["total_fees"], 15)
        self.assertEqual(first["net_pnl"], 45)
        self.assertEqual(first["total_trades"], 1)
        self.assertEqual(first["funding_count"], 1)
        self.assertGreater(self.daily.iloc[-1]["equity_drawdown_abs"], 0)

    def test_position_trade_count_mode(self):
        daily = build_daywise_report(self.clean, initial_capital=1000, trade_count_mode="position_id")
        self.assertEqual(daily.iloc[0]["total_trades"], 1)

    def test_summary_and_token_breakdown(self):
        summary = generate_summary(self.clean, self.daily, 1000)
        self.assertEqual(summary["total_transactions"], 5)
        self.assertEqual(summary["total_funding_rows"], 1)
        self.assertEqual(summary["unique_pairs"], 2)
        self.assertIsNotNone(summary["annualized_pnl_sharpe"])
        breakdown = build_token_breakdown(self.clean)
        self.assertEqual(set(breakdown["pair"]), {"B-ETH_USDT", "B-SOL_USDT"})


class FetchAndSafetyTests(unittest.TestCase):
    def test_partial_pages_are_kept(self):
        class Client:
            calls = 0

            def get_transactions(self, **_):
                self.calls += 1
                if self.calls == 1:
                    return [{"id": 1}, {"id": 2}]
                raise RuntimeError("temporary failure")

        messages = []
        rows = fetch_all_transactions(Client(), page_size=2, messages=messages)
        self.assertEqual(len(rows), 2)
        self.assertTrue(any("kept 2 rows" in message for message in messages))

    def test_download_path_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            safe = resolve_safe_report_file(root, "multi_20260101_000000_abcdef12", "summary.json")
            self.assertEqual(safe.parent.name, "multi_20260101_000000_abcdef12")
            with self.assertRaises(ValueError):
                resolve_safe_report_file(root, "multi_20260101_000000_abcdef12", "../secret.txt")

    def test_session_removal_closes_client(self):
        class Client:
            closed = False

            def close(self):
                self.closed = True

        store = SessionStore(ttl_seconds=10)
        client = Client()
        session_id = store.create(client)  # type: ignore[arg-type]
        self.assertIs(store.get_client(session_id), client)
        self.assertTrue(store.remove(session_id))
        self.assertTrue(client.closed)


if __name__ == "__main__":
    unittest.main()

