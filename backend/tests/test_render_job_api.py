import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

import app as app_module
from timeline_edl import SCHEMA


def sample_edl():
    return {
        "schema": SCHEMA, "version": 1, "timebase": "milliseconds",
        "clips": [{
            "id": "clip-1", "type": "video", "start_ms": 0, "end_ms": 1000,
            "asset_id": "a" * 32, "source_in_ms": 0, "source_out_ms": 1000,
        }],
    }


def sample_job(status="queued"):
    return {
        "id": str(uuid4()),
        "job_type": "timeline_render",
        "status": status,
        "attempt": 0,
        "max_attempts": 2,
        "created_at": "2026-11-20T00:00:00+00:00",
        "updated_at": "2026-11-20T00:00:00+00:00",
        "error_code": None,
        "error_message": None,
        "payload": {"edl": sample_edl(), "audio_asset_id": None},
        "lease_token": "must-not-leak",
        "worker_id": "render-worker-private",
        "workspace_id": "workspace-a",
    }


class RenderJobApiTests(unittest.TestCase):
    def test_list_render_jobs_is_workspace_scoped_and_returns_cursor(self):
        first = sample_job()
        second = sample_job()
        first["created_at"] = "2026-11-20T00:00:02+00:00"
        second["created_at"] = "2026-11-20T00:00:01+00:00"
        first["status"] = second["status"] = "review_pending"
        cursor_id = str(uuid4())
        with (
            patch.object(app_module, "require_review_permission", return_value="operator-a") as auth,
            patch.object(app_module, "resolve_operator_workspace_scope", return_value="workspace-a"),
            patch.object(app_module.queue, "list_jobs", return_value=[first, second]) as list_jobs,
        ):
            result = app_module.list_render_jobs(
                limit=2, status="review_pending",
                before_created_at="2026-11-19T23:59:00+00:00",
                before_job_id=cursor_id,
                x_review_token="token", x_nexus_workspace_id="workspace-a",
            )
        auth.assert_called_once_with("token", "production.read")
        list_jobs.assert_called_once_with(
            workspace_id="workspace-a", job_type="timeline_render",
            status="review_pending", limit=2,
            before_created_at="2026-11-19T23:59:00+00:00",
            before_job_id=cursor_id,
        )
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["items"][0]["job_id"], first["id"])
        self.assertNotIn("lease_token", result["items"][0])
        self.assertEqual(result["next_cursor"]["before_job_id"], second["id"])

    def test_list_render_jobs_rejects_missing_workspace_and_invalid_status(self):
        with (
            patch.object(app_module, "require_review_permission", return_value="operator-a"),
            patch.object(app_module, "resolve_operator_workspace_scope", return_value=None),
        ):
            with self.assertRaises(HTTPException) as denied:
                app_module.list_render_jobs(x_review_token="token")
        self.assertEqual(denied.exception.status_code, 403)
        with (
            patch.object(app_module, "require_review_permission", return_value="operator-a"),
            patch.object(app_module, "resolve_operator_workspace_scope", return_value="workspace-a"),
        ):
            with self.assertRaises(HTTPException) as invalid:
                app_module.list_render_jobs(status="all", x_review_token="token")
        self.assertEqual(invalid.exception.status_code, 422)

    def test_enqueue_uses_authenticated_workspace_and_durable_job_type(self):
        job = sample_job()
        with (
            patch.object(app_module, "require_review_permission", return_value="operator-a"),
            patch.object(app_module, "resolve_operator_workspace_scope", return_value="workspace-a"),
            patch.object(app_module.render_asset_store, "resolve_asset_paths", return_value={}) as resolve,
            patch.object(app_module.queue, "enqueue", return_value=job) as enqueue,
        ):
            result = app_module.enqueue_render_job(
                {"edl": sample_edl()},
                x_review_token="token",
                x_nexus_workspace_id="workspace-a",
                idempotency_key="render-request-1",
            )
        self.assertEqual(result["job_id"], job["id"])
        self.assertEqual(result["status"], "queued")
        resolve.assert_called_once_with(
            "workspace-a", ["a" * 32], expected_asset_type="video"
        )
        args, kwargs = enqueue.call_args
        self.assertEqual(args[0], "timeline_render")
        self.assertEqual(args[1]["edl"], sample_edl())
        self.assertEqual(kwargs["channel_name"], "render")
        self.assertEqual(kwargs["workspace_id"], "workspace-a")
        self.assertEqual(kwargs["idempotency_key"], "render-request-1")

    def test_enqueue_rejects_missing_explicit_workspace(self):
        with (
            patch.object(app_module, "require_review_permission", return_value="operator-a"),
            patch.object(app_module, "resolve_operator_workspace_scope", return_value=None),
            patch.object(app_module.queue, "enqueue") as enqueue,
        ):
            with self.assertRaises(HTTPException) as denied:
                app_module.enqueue_render_job(
                    {"edl": sample_edl()}, x_review_token="token",
                    x_nexus_workspace_id=None,
                )
        self.assertEqual(denied.exception.status_code, 403)
        enqueue.assert_not_called()

    def test_job_status_never_exposes_worker_or_lease_credentials(self):
        job = sample_job()
        with (
            patch.object(app_module, "require_review_permission", return_value="operator-a"),
            patch.object(app_module, "resolve_operator_workspace_scope", return_value="workspace-a"),
            patch.object(app_module.queue, "get", return_value=job),
            patch.object(app_module.queue, "events", return_value=[]),
        ):
            result = app_module.get_render_job(
                job["id"], x_review_token="token", x_nexus_workspace_id="workspace-a"
            )
        self.assertEqual(result["job_id"], job["id"])
        self.assertNotIn("lease_token", result)
        self.assertNotIn("worker_id", result)
        self.assertNotIn("must-not-leak", str(result))

    def test_review_pending_job_exposes_only_output_metadata_not_internal_path(self):
        job = sample_job("review_pending")
        output = {
            "job_id": job["id"], "render_id": "b" * 32,
            "path": "/private/media/output.mp4", "sha256": "c" * 64,
            "size_bytes": 100, "duration_seconds": 1.0,
            "width": 1080, "height": 1920, "review_status": "pending",
        }
        with (
            patch.object(app_module, "require_review_permission", return_value="operator-a"),
            patch.object(app_module, "resolve_operator_workspace_scope", return_value="workspace-a"),
            patch.object(app_module.queue, "get", return_value=job),
            patch.object(app_module.queue, "events", return_value=[]),
            patch.object(app_module.render_output_store, "get_reviewable", return_value=output),
        ):
            result = app_module.get_render_job(
                job["id"], x_review_token="token", x_nexus_workspace_id="workspace-a"
            )
        self.assertEqual(result["output"]["render_id"], "b" * 32)
        self.assertNotIn("path", result["output"])
        self.assertNotIn("/private/media/output.mp4", str(result))

    def test_review_decision_uses_authenticated_reviewer_and_workspace(self):
        job = sample_job("review_pending")
        output = {"job_id": job["id"], "review_status": "approved", "path": "/private/output.mp4"}
        with (
            patch.object(app_module, "require_review_permission", return_value="reviewer-a") as auth,
            patch.object(app_module, "resolve_operator_workspace_scope", return_value="workspace-a"),
            patch.object(app_module.queue, "get", return_value=job),
            patch.object(app_module.render_output_store, "decide", return_value=output) as decide,
        ):
            result = app_module.decide_render_review(
                job["id"], {"decision": "approved", "note": "Looks good"},
                x_review_token="token", x_nexus_workspace_id="workspace-a",
            )
        auth.assert_called_once_with("token", "review.decide")
        decide.assert_called_once_with(job["id"], "workspace-a", "reviewer-a", "approved", "Looks good")
        self.assertEqual(result["review_status"], "approved")
        self.assertNotIn("path", result)


if __name__ == "__main__":
    unittest.main()
