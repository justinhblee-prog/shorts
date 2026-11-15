import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from fastapi import HTTPException

import app as app_module
from app import get_operations_economics
from operational_economics import build_operational_economics


class OperationalEconomicsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name) / "analytics.sqlite3")
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE pipeline_jobs (
                    id TEXT PRIMARY KEY, job_type TEXT, status TEXT, error_code TEXT,
                    created_at TEXT, updated_at TEXT
                );
                CREATE TABLE production_runs (
                    job_id TEXT PRIMARY KEY, brand TEXT, status TEXT,
                    current_stage TEXT, error TEXT
                );
                CREATE TABLE review_decisions (
                    id INTEGER PRIMARY KEY, job_id TEXT, decision TEXT
                );
                CREATE TABLE youtube_uploads (job_id TEXT PRIMARY KEY, status TEXT);
                CREATE TABLE tiktok_publications (job_id TEXT PRIMARY KEY, status TEXT);
                CREATE TABLE financial_ledger (
                    id TEXT PRIMARY KEY, job_id TEXT, brand TEXT, region TEXT,
                    entry_type TEXT, amount REAL, currency TEXT, source_type TEXT,
                    source_reference TEXT, occurred_at TEXT, note TEXT, created_at TEXT
                );
                INSERT INTO pipeline_jobs VALUES
                    ('j1','short_video_production','uploaded',NULL,'2026-11-01','2026-11-02'),
                    ('j2','short_video_production','failed_terminal','render_error','2026-11-01','2026-11-03'),
                    ('j3','short_video_production','review_pending',NULL,'2026-11-01','2026-11-04');
                INSERT INTO production_runs VALUES
                    ('j1','Brain Glitch','approved','rendering',NULL),
                    ('j2','Brain Glitch','failed_terminal','rendering','render failed'),
                    ('j3','Silent Signals','review_pending','script',NULL);
                INSERT INTO review_decisions VALUES
                    (1,'j1','approved'),(2,'j2','rejected');
                INSERT INTO youtube_uploads VALUES ('j1','uploaded');
                INSERT INTO tiktok_publications VALUES ('j1','PUBLISHED');
                INSERT INTO financial_ledger VALUES
                    ('l1','j1','Brain Glitch','US','youtube_ads',12.5,'USD','youtube_analytics','ref1','2026-11-02','','2026-11-02'),
                    ('l2','j1','Brain Glitch','US','production_cost',4.5,'USD','ai_provider','ref2','2026-11-02','','2026-11-02'),
                    ('l3','j2','Brain Glitch','US','production_cost',3,'EUR','render_provider','ref3','2026-11-03','','2026-11-03');
            """)
    def tearDown(self):
        self.temp.cleanup()

    def test_brand_failure_approval_and_platform_counts(self):
        result = build_operational_economics(self.db_path)
        brain = next(x for x in result["brands"] if x["brand"] == "Brain Glitch")
        self.assertEqual(brain["jobs"], 2)
        self.assertEqual(brain["failed"], 1)
        self.assertEqual(brain["failure_rate_percent"], 50.0)
        self.assertEqual(brain["approved"], 1)
        self.assertEqual(brain["youtube_published"], 1)
        self.assertEqual(brain["tiktok_published"], 1)

    def test_financials_are_linked_and_never_cross_currency(self):
        result = build_operational_economics(self.db_path)
        usd = next(x for x in result["financial_by_currency"] if x["currency"] == "USD")
        eur = next(x for x in result["financial_by_currency"] if x["currency"] == "EUR")
        self.assertEqual(usd["recorded_revenue"], 12.5)
        self.assertEqual(usd["recorded_costs"], 4.5)
        self.assertEqual(usd["recorded_net"], 8.0)
        self.assertEqual(eur["recorded_revenue"], 0)
        self.assertEqual(eur["recorded_costs"], 3.0)
        self.assertFalse(result["data_quality"]["currency_conversion_applied"])
        self.assertEqual(len(result["job_financial_records"]), 2)

    def test_stage_failure_rates_and_read_only_contract(self):
        before = Path(self.db_path).read_bytes()
        result = build_operational_economics(self.db_path)
        after = Path(self.db_path).read_bytes()
        self.assertEqual(before, after)
        rendering = next(x for x in result["stages"] if x["stage"] == "rendering")
        self.assertEqual(rendering["failure_rate_percent"], 50.0)
        self.assertTrue(result["read_only"])
        self.assertEqual(result["actions_taken"], [])

    def test_api_authenticates_and_bounds_cohort(self):
        with mock.patch("app.require_review_access") as access, \
             mock.patch.object(app_module.queue, "db_path", self.db_path):
            result = get_operations_economics(limit=20, x_review_token="secret")
        access.assert_called_once_with("secret")
        self.assertEqual(result["cohort_jobs"], 3)

    def test_api_rejects_invalid_limit(self):
        with mock.patch("app.require_review_access"):
            with self.assertRaises(HTTPException) as caught:
                get_operations_economics(limit=501, x_review_token="secret")
        self.assertEqual(caught.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
