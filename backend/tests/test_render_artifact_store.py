import hashlib
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from queue_store import JobQueue, LeaseConflict
from render_artifact_store import ArtifactAdoptionError, RenderArtifactStore


class RenderArtifactStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.staging = root / "staging"
        self.artifacts = root / "artifacts"
        self.queue = JobQueue(root / "queue.sqlite3", lease_seconds=10)
        self.worker = "render-worker"
        self.generation = self.queue.register_worker(self.worker)["generation_token"]
        self.snapshot_id = "edl_" + "a" * 32
        self.snapshot_sha = hashlib.sha256(b"snapshot").hexdigest()
        self.job = self.queue.enqueue(
            "timeline_render",
            {"snapshot_id": self.snapshot_id, "snapshot_sha256": self.snapshot_sha, "edl": {}},
            workspace_id="ws_test",
        )
        self.claimed = self.queue.claim(
            self.worker, job_type="timeline_render", generation_token=self.generation
        )
        self.store = RenderArtifactStore(
            self.queue, self.staging, self.artifacts, max_bytes=1024
        )
        self.staged = self.staging / "output.mp4"
        self.staged.write_bytes(b"verified-render-fixture")

    def tearDown(self):
        self.temp.cleanup()

    def adopt(self, **overrides):
        args = {
            "job_id": self.job["id"],
            "worker_id": self.worker,
            "lease_token": self.claimed["lease_token"],
            "generation_token": self.generation,
            "workspace_id": "ws_test",
            "snapshot_id": self.snapshot_id,
            "snapshot_sha256": self.snapshot_sha,
            "staged_path": self.staged,
        }
        args.update(overrides)
        return self.store.adopt(**args)

    def test_adopts_checksum_verified_artifact_under_live_lease(self):
        result = self.adopt()
        record = self.store.get(result["artifact_id"], "ws_test")
        self.assertEqual(result["status"], "review_pending")
        self.assertEqual(record["artifact_sha256"], hashlib.sha256(b"verified-render-fixture").hexdigest())
        self.assertFalse(self.staged.exists())
        self.assertTrue((self.artifacts / result["storage_key"]).is_file())

    def test_rejects_wrong_snapshot_without_moving_output(self):
        with self.assertRaisesRegex(ArtifactAdoptionError, "snapshot"):
            self.adopt(snapshot_sha256="f" * 64)
        self.assertTrue(self.staged.exists())
        self.assertEqual(list(self.artifacts.iterdir()), [])

    def test_rejects_output_outside_staging_root_and_symlink(self):
        outside = Path(self.temp.name) / "outside.mp4"
        outside.write_bytes(b"outside")
        with self.assertRaises(ArtifactAdoptionError):
            self.adopt(staged_path=outside)
        link = self.staging / "linked.mp4"
        link.symlink_to(outside)
        with self.assertRaises(ArtifactAdoptionError):
            self.adopt(staged_path=link)
        self.assertTrue(outside.exists())

    def test_rejects_stale_worker_generation(self):
        new_generation = self.queue.register_worker(self.worker)["generation_token"]
        with self.assertRaises(LeaseConflict):
            self.adopt(generation_token=self.generation)
        self.assertNotEqual(new_generation, self.generation)
        self.assertTrue(self.staged.exists())

    def test_rejects_oversized_or_unsupported_outputs(self):
        self.staged.write_bytes(b"x" * 1025)
        with self.assertRaisesRegex(ArtifactAdoptionError, "size"):
            self.adopt()
        self.staged.unlink()
        bad = self.staging / "output.exe"
        bad.write_bytes(b"x")
        with self.assertRaisesRegex(ArtifactAdoptionError, "extension"):
            self.adopt(staged_path=bad)

    def test_detects_artifact_tampering_after_adoption(self):
        result = self.adopt()
        (self.artifacts / result["storage_key"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(ArtifactAdoptionError, "integrity"):
            self.store.get(result["artifact_id"], "ws_test")


    def test_rejects_expired_lease_before_moving_output(self):
        with self.queue.db() as db:
            db.execute(
                "UPDATE pipeline_jobs SET lease_expires_at=? WHERE id=?",
                ("2000-01-01T00:00:00+00:00", self.job["id"]),
            )
        with self.assertRaises(LeaseConflict):
            self.adopt()
        self.assertTrue(self.staged.exists())
        self.assertEqual(list(self.artifacts.iterdir()), [])

    def test_database_failure_rolls_back_adoption_and_removes_moved_file(self):
        with self.queue.db() as db:
            db.execute("""
                CREATE TRIGGER reject_artifact_insert
                BEFORE INSERT ON render_artifacts
                BEGIN SELECT RAISE(ABORT, 'injected artifact insert failure'); END
            """)
        with self.assertRaisesRegex(Exception, "injected artifact insert failure"):
            self.adopt()
        self.assertTrue(self.staged.exists())
        self.assertEqual(list(self.artifacts.iterdir()), [])
        with self.queue.db() as db:
            db.execute("DROP TRIGGER reject_artifact_insert")


    def test_reconciles_only_unindexed_generated_artifacts(self):
        adopted = self.adopt()
        orphan = self.artifacts / ("rart_" + "b" * 32 + ".mp4")
        orphan.write_bytes(b"orphan")
        unrelated = self.artifacts / "keep.txt"
        unrelated.write_bytes(b"keep")
        result = self.store.reconcile_orphaned_files(grace_seconds=0)
        self.assertEqual(result["removed"], 1)
        self.assertFalse(orphan.exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue((self.artifacts / adopted["storage_key"]).exists())


    def test_staging_reconciliation_respects_grace_and_generated_name_allowlist(self):
        import os
        import time

        valid = self.staging / ("render_" + "c" * 32 + ".mp4")
        valid.write_bytes(b"crash-left-render")
        recent = self.staging / ("render_" + "d" * 32 + ".mp4")
        recent.write_bytes(b"active-render")
        unrelated = self.staging / "operator-notes.txt"
        unrelated.write_bytes(b"keep")
        old_time = time.time() - 8000
        os.utime(valid, (old_time, old_time))
        os.utime(unrelated, (old_time, old_time))

        result = self.store.reconcile_orphaned_staging(grace_seconds=7200)
        self.assertEqual(result["removed_files"], 1)
        self.assertEqual(result["removed_bytes"], len(b"crash-left-render"))
        self.assertFalse(valid.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(unrelated.exists())

    def test_staging_reconciliation_rejects_grace_shorter_than_renderer_timeout(self):
        for grace in (0, 7199, -1, True):
            with self.subTest(grace=grace), self.assertRaises(ValueError):
                self.store.reconcile_orphaned_staging(grace_seconds=grace)

    def test_optional_ffprobe_metadata_is_persisted_with_adopted_artifact(self):
        binary = Path(self.temp.name) / "ffprobe"
        binary.write_bytes(b"fixture-binary")
        store = RenderArtifactStore(
            self.queue, self.staging, self.artifacts,
            ffprobe_path=binary, require_audio=True,
        )
        probe = {
            "duration_ms": 12345,
            "byte_size": self.staged.stat().st_size,
            "video_streams": [{"width": 1280, "height": 720, "codec": "h264"}],
            "audio_streams": 1,
            "audio_codecs": ["aac"],
        }
        with patch("render_artifact_store.probe_media", return_value=probe) as mocked:
            result = store.adopt(
                self.job["id"], self.worker, self.claimed["lease_token"],
                self.generation, "ws_test", self.snapshot_id,
                self.snapshot_sha, self.staged,
            )
        mocked.assert_called_once()
        record = store.get(result["artifact_id"], "ws_test")
        self.assertEqual(record["duration_ms"], 12345)
        self.assertEqual(record["video_width"], 1280)
        self.assertEqual(record["video_height"], 720)
        self.assertEqual(record["audio_streams"], 1)


if __name__ == "__main__":
    unittest.main()
