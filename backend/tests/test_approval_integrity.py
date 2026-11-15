import json
import sqlite3
import unittest

from approval_integrity import approval_snapshot_matches_current_artifacts


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

    def test_malformed_snapshot_fails_closed(self):
        matches, reason = approval_snapshot_matches_current_artifacts(
            self.connection, "job-1", "{not-json"
        )
        self.assertFalse(matches)
        self.assertIn("malformed", reason)


if __name__ == "__main__":
    unittest.main()
