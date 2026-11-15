import unittest
from unittest import mock
from fastapi import HTTPException

import app as app_module
from app import get_pipeline_performance
from pipeline_performance import build_pipeline_performance


def make_job(job_id, seconds=10):
    return {
        "id": job_id, "status": "review_pending",
        "created_at": "2026-11-15T10:00:00Z",
        "updated_at": f"2026-11-15T10:00:{seconds:02d}Z",
    }


def make_events():
    return [
        {"created_at": "2026-11-15T10:00:05Z",
         "from_status": "queued", "to_status": "running"},
        {"created_at": "2026-11-15T10:00:08Z",
         "from_status": "running", "to_status": "review_pending"},
    ]


class PipelinePerformanceTests(unittest.TestCase):
    def test_percentiles_and_median_are_reported_for_sufficient_cohort(self):
        jobs = [make_job(f"j{i}", 20 + i) for i in range(5)]
        events = {job["id"]: make_events() for job in jobs}
        result = build_pipeline_performance(jobs, events, min_samples=5)
        queued = next(item for item in result["stages"] if item["status"] == "queued")
        self.assertEqual(queued["sample_count"], 5)
        self.assertEqual(queued["median_seconds"], 5.0)
        self.assertEqual(queued["p90_seconds"], 5.0)
        self.assertEqual(queued["assessment"], "measurable")
        self.assertEqual(result["bottleneck_candidate"]["status"], "review_pending")
        self.assertIsNotNone(result["bottleneck_candidate"]["median_seconds"])

    def test_small_cohort_suppresses_statistics_and_bottleneck(self):
        jobs = [make_job("only-one")]
        result = build_pipeline_performance(jobs, {"only-one": make_events()}, min_samples=5)
        self.assertTrue(all(item["assessment"] == "insufficient_samples"
                            for item in result["stages"]))
        self.assertTrue(all(item["median_seconds"] is None for item in result["stages"]))
        self.assertIsNone(result["bottleneck_candidate"])

    def test_empty_cohort_is_safe_and_read_only(self):
        result = build_pipeline_performance([], {})
        self.assertEqual(result["cohort_jobs"], 0)
        self.assertEqual(result["stages"], [])
        self.assertEqual(result["actions_taken"], [])
        self.assertTrue(result["read_only"])

    def test_api_requires_auth_and_uses_bounded_short_video_cohort(self):
        jobs = [make_job("job-api")]
        page = {"items": jobs, "total": 1}
        with mock.patch("app.require_review_access") as access, \
             mock.patch.object(app_module.queue, "list_jobs", return_value=page) as listing, \
             mock.patch.object(app_module.queue, "events", return_value=make_events()):
            result = get_pipeline_performance(limit=25, min_samples=1,
                                              x_review_token="secret")
        access.assert_called_once_with("secret")
        listing.assert_called_once_with(job_type="short_video_production", limit=25)
        self.assertEqual(result["cohort_total_jobs"], 1)
        self.assertTrue(result["read_only"])

    def test_api_rejects_invalid_minimum_sample_count(self):
        with mock.patch("app.require_review_access"):
            with self.assertRaises(HTTPException) as caught:
                get_pipeline_performance(limit=20, min_samples=0,
                                         x_review_token="secret")
        self.assertEqual(caught.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
