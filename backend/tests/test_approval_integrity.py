import hashlib
import json
import os
import tempfile
import sqlite3
import unittest

from approval_integrity import approval_snapshot_matches_current_artifacts, verify_staged_media_hash, create_verified_media_snapshot


class ApprovalIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("""
            CREATE TABLE production_artifacts(
                id INTEGER PRIMARY KEY,
                job_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                artifact_type TEXT NOT NULL,
                artifact_url TEXT,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        self.connection.execute("""
            INSERT INTO production_artifacts
              (job_id,stage,artifact_type,artifact_url,metadata_json,created_at)
            VALUES(?,?,?,?,?,?)
        """, ("job-1", "rendering", "video", "https://media.example/video.mp4",
              json.dumps({"duration": 30, "codec": "h264"}), "2026-11-15T00:00:00Z"))
        self.connection.commit()
        self.snapshot = [{
            "stage": "rendering", "artifact_type": "video",
            "artifact_url": "https://media.example/video.mp4",
            "metadata": {"duration": 30, "codec": "h264"},
        }]

    def tearDown(self):
        self.connection.close()

    def test_exact_approved_artifact_set_matches(self):
        self.assertEqual(
            approval_snapshot_matches_current_artifacts(self.connection, "job-1", self.snapshot),
            (True, None),
        )

    def test_changed_artifact_metadata_invalidates_approval(self):
        self.connection.execute(
            "UPDATE production_artifacts SET metadata_json=? WHERE job_id=?",
            (json.dumps({"duration": 31, "codec": "h264"}), "job-1"),
        )
        matches, reason = approval_snapshot_matches_current_artifacts(
            self.connection, "job-1", self.snapshot
        )
        self.assertFalse(matches)
        self.assertIn("changed after human approval", reason)

    def test_added_artifact_invalidates_approval(self):
        self.connection.execute("""
            INSERT INTO production_artifacts
              (job_id,stage,artifact_type,artifact_url,metadata_json,created_at)
            VALUES(?,?,?,?,?,?)
        """, ("job-1", "quality_check", "report", None, "{}", "2026-11-15T00:01:00Z"))
        matches, _ = approval_snapshot_matches_current_artifacts(
            self.connection, "job-1", self.snapshot
        )
        self.assertFalse(matches)

    def test_removed_artifact_invalidates_approval(self):
        self.connection.execute("DELETE FROM production_artifacts WHERE job_id=?", ("job-1",))
        matches, reason = approval_snapshot_matches_current_artifacts(
            self.connection, "job-1", self.snapshot
        )
        self.assertFalse(matches)
        self.assertIn("missing", reason)

    def test_approved_media_hash_accepts_exact_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "video.mp4")
            payload = b"approved-rendered-video"
            with open(path, "wb") as stream:
                stream.write(payload)
            self.assertEqual(
                verify_staged_media_hash(path, hashlib.sha256(payload).hexdigest(), len(payload)),
                (True, None),
            )

    def test_approved_media_hash_rejects_mutated_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "video.mp4")
            with open(path, "wb") as stream:
                stream.write(b"approved-bytes")
            with open(path, "wb") as stream:
                stream.write(b"mutated-bytes")
            matches, reason = verify_staged_media_hash(
                path, hashlib.sha256(b"approved-bytes").hexdigest(), len(b"approved-bytes")
            )
            self.assertFalse(matches)
            self.assertIn("changed after human approval", reason)

    def test_approved_media_hash_rejects_missing_file_and_missing_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = os.path.join(directory, "missing.mp4")
            self.assertFalse(verify_staged_media_hash(missing, "a" * 64, 10)[0])
            path = os.path.join(directory, "video.mp4")
            with open(path, "wb") as stream:
                stream.write(b"video")
            self.assertFalse(verify_staged_media_hash(path, None, None)[0])

    def test_verified_snapshot_is_independent_of_later_source_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "video.mp4")
            payload = b"approved-video"
            with open(source, "wb") as stream:
                stream.write(payload)
            snapshot, size = create_verified_media_snapshot(
                source, hashlib.sha256(payload).hexdigest(), len(payload)
            )
            try:
                with open(source, "wb") as stream:
                    stream.write(b"attacker-replacement")
                with open(snapshot, "rb") as stream:
                    self.assertEqual(stream.read(), payload)
                self.assertEqual(size, len(payload))
            finally:
                os.unlink(snapshot)

    def test_verified_snapshot_rejects_symlink_source(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "real.mp4")
            link = os.path.join(directory, "video.mp4")
            payload = b"approved-video"
            with open(target, "wb") as stream:
                stream.write(payload)
            os.symlink(target, link)
            with self.assertRaisesRegex(ValueError, "symbolic link"):
                create_verified_media_snapshot(
                    link, hashlib.sha256(payload).hexdigest(), len(payload)
                )

    def test_malformed_snapshot_fails_closed(self):
        matches, reason = approval_snapshot_matches_current_artifacts(
            self.connection, "job-1", "{not-json"
        )
        self.assertFalse(matches)
        self.assertIn("malformed", reason)


if __name__ == "__main__":
    unittest.main()
