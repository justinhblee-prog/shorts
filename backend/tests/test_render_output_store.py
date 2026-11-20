import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from queue_store import JobQueue, LeaseConflict
from render_output_store import (
    RenderOutputError,
    RenderOutputLeaseConflict,
    RenderOutputNotFound,
    RenderOutputStore,
)


class RenderOutputStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.db_path = self.root / "nexus.sqlite3"
        self.media_root = self.root / "media"
        self.media_root.mkdir()
        self.queue = JobQueue(self.db_path, lease_seconds=30)
        self.outputs = RenderOutputStore(self.db_path, self.media_root)
        self.workspace = "workspace-a"
        self.worker = "render-worker-test"
        self.generation = self.queue.register_worker(self.worker, "test-host")["generation_token"]
        self.job = self.queue.enqueue(
            "timeline_render", {"edl": {"schema": "test"}}, channel_name="render",
            max_attempts=2, workspace_id=self.workspace,
        )
        self.claimed = self.queue.claim(
            self.worker, "test-host", job_type="timeline_render",
            generation_token=self.generation,
        )
        self.assertEqual(self.claimed["id"], self.job["id"])
        self.result = self.make_result()

    def tearDown(self):
        self.tmp.cleanup()

    def make_result(self):
        directory = self.media_root / "workspace" / "render-outputs"
        directory.mkdir(parents=True)
        path = directory / ("a" * 32 + ".mp4")
        payload = b"verified-render-output"
        path.write_bytes(payload)
        return {
            "render_id": "a" * 32,
            "media_path": path.relative_to(self.media_root).as_posix(),
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "duration_seconds": 1.0,
            "width": 1080,
            "height": 1920,
            "audio_track_present": False,
            "status": "rendered_unreviewed",
        }

    def adopt_and_finish(self):
        adopted = self.outputs.adopt(
            self.job["id"], self.workspace, self.worker,
            self.claimed["lease_token"], self.claimed["attempt"], self.result,
        )
        self.queue.finish(
            self.job["id"], self.worker, self.claimed["lease_token"],
            {"render_id": adopted["render_id"], "sha256": adopted["sha256"]},
            generation_token=self.generation, workspace_id=self.workspace,
        )
        return adopted

    def test_adoption_is_fenced_by_current_workspace_worker_and_lease(self):
        adopted = self.outputs.adopt(
            self.job["id"], self.workspace, self.worker,
            self.claimed["lease_token"], self.claimed["attempt"], self.result,
        )
        self.assertEqual(adopted["review_status"], "pending")
        with self.assertRaises(RenderOutputNotFound):
            self.outputs.get_reviewable(self.job["id"], self.workspace)
        self.queue.finish(
            self.job["id"], self.worker, self.claimed["lease_token"],
            {"render_id": adopted["render_id"]},
            generation_token=self.generation, workspace_id=self.workspace,
        )
        output = self.outputs.get_reviewable(self.job["id"], self.workspace)
        self.assertEqual(output["render_id"], "a" * 32)
        self.assertEqual(output["path"].read_bytes(), b"verified-render-output")

    def test_rejects_adoption_after_lease_is_cancelled(self):
        self.queue.cancel(
            self.job["id"], "test cancellation", workspace_id=self.workspace
        )
        with self.assertRaises(RenderOutputLeaseConflict):
            self.outputs.adopt(
                self.job["id"], self.workspace, self.worker,
                self.claimed["lease_token"], self.claimed["attempt"], self.result,
            )

    def test_rejects_cross_workspace_output_access(self):
        self.adopt_and_finish()
        with self.assertRaises(RenderOutputNotFound):
            self.outputs.get_reviewable(self.job["id"], "workspace-b")

    def test_rechecks_output_hash_before_download_or_review(self):
        self.adopt_and_finish()
        output = self.outputs.get_reviewable(self.job["id"], self.workspace)
        output["path"].write_bytes(b"tampered")
        with self.assertRaisesRegex(RenderOutputError, "checksum"):
            self.outputs.get_reviewable(self.job["id"], self.workspace)

    def test_human_review_decision_is_workspace_scoped_and_one_time(self):
        self.adopt_and_finish()
        approved = self.outputs.decide(
            self.job["id"], self.workspace, "reviewer-a", "approved", "Looks good"
        )
        self.assertEqual(approved["review_status"], "approved")
        self.assertEqual(approved["reviewed_by"], "reviewer-a")
        self.assertEqual(approved["review_note"], "Looks good")
        events = self.outputs.events(self.job["id"], self.workspace)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "review_decided")
        self.assertEqual(events[0]["reviewer_id"], "reviewer-a")
        with self.assertRaises(sqlite3.IntegrityError):
            with self.outputs.db() as connection:
                connection.execute(
                    "UPDATE render_output_events SET note='rewritten' WHERE job_id=?",
                    (self.job["id"],),
                )
        with self.assertRaisesRegex(ValueError, "already received"):
            self.outputs.decide(
                self.job["id"], self.workspace, "reviewer-a", "rejected", "Second decision"
            )

    def test_rejects_invalid_output_metadata_and_path_escape(self):
        invalid = {**self.result, "width": 720}
        with self.assertRaisesRegex(RenderOutputError, "dimensions"):
            self.outputs.adopt(
                self.job["id"], self.workspace, self.worker,
                self.claimed["lease_token"], self.claimed["attempt"], invalid,
            )
        outside = self.root / "outside.mp4"
        outside.write_bytes(b"outside")
        escaped = {
            **self.result,
            "media_path": "../outside.mp4",
            "size_bytes": len(b"outside"),
            "sha256": hashlib.sha256(b"outside").hexdigest(),
        }
        with self.assertRaisesRegex(RenderOutputError, "escaped"):
            self.outputs.adopt(
                self.job["id"], self.workspace, self.worker,
                self.claimed["lease_token"], self.claimed["attempt"], escaped,
            )


if __name__ == "__main__":
    unittest.main()
