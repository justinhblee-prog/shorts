import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from development_artifact_recovery import DevelopmentArtifactError, restore_pending_artifacts
from development_jobs import DevelopmentJobStore


class DevelopmentArtifactRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.artifacts = Path(self.tmp.name) / "state" / "artifacts"
        self.root.mkdir()
        (self.root / "backend").mkdir()
        self.source = self.root / "backend" / "module.py"
        self.original = b"VALUE = 1\n"
        self.updated = b"VALUE = 2\n"
        self.source.write_bytes(self.original)
        self.store = DevelopmentJobStore(str(Path(self.tmp.name) / "state" / "jobs.sqlite3"))
        self.job = self.store.create("Recover a validated edit", scope=["backend/module.py"])
        self.claim = self.store.claim_ready("worker-a")
        self.artifacts.mkdir(parents=True)
        self.artifact = self.artifacts / "job.zip"
        manifest = {
            "version": 1,
            "job_id": self.job["id"],
            "files": [{
                "path": "backend/module.py",
                "base_sha256": hashlib.sha256(self.original).hexdigest(),
                "content_sha256": hashlib.sha256(self.updated).hexdigest(),
            }],
        }
        with zipfile.ZipFile(self.artifact, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr("files/backend/module.py", self.updated)
        digest = hashlib.sha256(self.artifact.read_bytes()).hexdigest()
        self.store.prepare_review(
            self.job["id"], "worker-a", self.claim["lease_token"],
            ["backend/module.py"], True, "ci://run/900", str(self.artifact), digest,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_restores_pending_snapshot_when_base_still_matches(self):
        restored = restore_pending_artifacts(self.store, self.root, self.artifacts)
        self.assertEqual(restored, [self.job["id"]])
        self.assertEqual(self.source.read_bytes(), self.updated)
        self.assertEqual(self.store.get(self.job["id"])["status"], "review_pending")

    def test_refuses_to_overwrite_a_changed_base_file(self):
        conflicting = b"VALUE = 99\n"
        self.source.write_bytes(conflicting)
        with self.assertRaisesRegex(DevelopmentArtifactError, "refusing to overwrite"):
            restore_pending_artifacts(self.store, self.root, self.artifacts)
        self.assertEqual(self.source.read_bytes(), conflicting)
        self.assertEqual(self.store.get(self.job["id"])["status"], "review_pending")

    def test_rejects_artifact_digest_mismatch(self):
        self.artifact.write_bytes(self.artifact.read_bytes() + b"tampered")
        with self.assertRaisesRegex(DevelopmentArtifactError, "SHA-256 mismatch"):
            restore_pending_artifacts(self.store, self.root, self.artifacts)


if __name__ == "__main__":
    unittest.main()
