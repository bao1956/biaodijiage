import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

import fetch_prices as prices
from scripts.record_success import record_success


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)
        self.pivot = pd.DataFrame({"600519": [1288.0]}, index=pd.to_datetime(["2026-10-12"]))

    def push(self):
        return prices.push_table_to_sheet(self.pivot, ["600519"], {"600519": "贵州茅台"}, "股票", 30, "30交易日")

    @patch.object(prices, "WEBHOOK_URL", "")
    def test_missing_webhook_fails(self):
        with self.assertRaises(RuntimeError):
            self.push()

    @patch.object(prices, "WEBHOOK_URL", "https://example.invalid")
    @patch.object(prices.requests, "post")
    def test_http_200_application_error_fails(self, post):
        post.return_value.json.return_value = {"ok": False}
        with self.assertRaises(RuntimeError):
            self.push()

    @patch.object(prices, "WEBHOOK_URL", "https://example.invalid")
    @patch.object(prices.requests, "post")
    def test_success_reports_per_asset_date(self, post):
        post.return_value.json.return_value = {"ok": True}
        self.assertEqual(self.push()["latest_dates"], {"600519": "2026/10/12"})

    @patch.object(prices, "push_table_to_sheet")
    @patch.object(prices.time, "sleep")
    def test_partial_fetch_preserves_existing_table(self, sleep, push):
        fetch = Mock(side_effect=[pd.DataFrame({"日期": pd.to_datetime(["2026-10-12"]), "代码": ["600519"], "价格": [1288.0]}), ValueError("source unavailable")])
        with self.assertRaises(RuntimeError):
            prices.run_price_tab([("600519", "茅台"), ("600036", "招行")], "股票", fetch)
        push.assert_not_called()

    @patch.object(prices, "run_fund_tab", return_value={})
    @patch.object(prices, "run_price_tab", side_effect=[RuntimeError("failed"), {}])
    def test_failed_tab_does_not_hide_failure_or_skip_other_tabs(self, run_price, run_fund):
        with self.assertRaises(RuntimeError):
            prices.main()
        self.assertEqual(run_price.call_count, 2)
        self.assertEqual(run_fund.call_count, 2)


class HealthRecordTests(unittest.TestCase):
    def test_initial_record_and_thirty_day_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "run.json", Path(directory) / "last.json"
            report = {"completed_at": "2026-10-19T08:00:00+00:00", "sheets": [
                {"sheet": name, "assets": 1, "latest_dates": {"test": "2026/10/19"}}
                for name in ["ETF", "股票", "基金", "买入标的"]
            ]}
            def save():
                source.write_text(json.dumps(report), encoding="utf-8")
            save()
            self.assertTrue(record_success(source, target))
            original = target.read_bytes()
            report["completed_at"] = "2026-11-17T08:00:00+00:00"
            save()
            self.assertFalse(record_success(source, target))
            self.assertEqual(target.read_bytes(), original)
            report["completed_at"] = "2026-11-18T08:00:00+00:00"
            save()
            self.assertTrue(record_success(source, target))
            report["sheets"].pop()
            save()
            with self.assertRaises(ValueError):
                record_success(source, target)


if __name__ == "__main__":
    unittest.main()
