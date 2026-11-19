import os
import sqlite3
import tempfile
import unittest

from development_jobs import (
    DevelopmentJobConflict, DevelopmentJobNotFound, DevelopmentJobStore,
)


class DevelopmentJobStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DevelopmentJobStore(os.path.join(self.tmp.name, "jobs.sqlite3"), lease_seconds=30)

    def tearDown(self):
        self.tmp.cleanup()

    def test_source_ref_is_indexed_and_duplicate_creation_is_rejected(self):
        first = self.store.create("Imported issue", source_ref="github:issue:acme/app#17")
        self.assertTrue(self.store.source_ref_exists("github:issue:acme/app#17"))
        self.assertFalse(self.store.source_ref_exists("github:issue:acme/app#18"))
        with self.assertRaisesRegex(DevelopmentJobConflict, "source_ref already exists"):
            self.store.create("Duplicate import", source_ref="github:issue:acme/app#17")
        with self.store.db() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM development_jobs WHERE source_ref=?",
                ("github:issue:acme/app#17",),
            ).fetchone()[0]
            indexes = {
                row["name"] for row in connection.execute("PRAGMA index_list(development_jobs)")
            }
        self.assertEqual(count, 1)
        self.assertIn("idx_development_jobs_source_ref", indexes)
        self.assertEqual(self.store.get(first["id"])["title"], "Imported issue")

    def test_create_and_claim_ready_job(self):
        job = self.store.create("Add job registry", scope=["backend/development_jobs.py"],
                                acceptance=["persistent", "audited"])
        claimed = self.store.claim_ready("worker-a")
        self.assertEqual(claimed["id"], job["id"])
        self.assertEqual(claimed["status"], "leased")
        self.assertEqual(claimed["attempts"], 1)
        self.assertTrue(claimed["lease_token"])
        self.assertIsNone(self.store.claim_ready("worker-b"))

    def test_dependency_blocks_until_parent_completed(self):
        parent = self.store.create("Parent", scope=["backend/module.py"])
        child = self.store.create("Child")
        self.store.add_dependency(child["id"], parent["id"])
        self.assertEqual(self.store.get(child["id"])["status"], "blocked")
        claim = self.store.claim_ready("worker-a")
        self.assertEqual(claim["id"], parent["id"])
        self.store.heartbeat(parent["id"], "worker-a", claim["lease_token"])
        self.store.mark_review_pending(parent["id"], "worker-a", claim["lease_token"],
                                       ["backend/module.py"], True, "ci://run/123")
        self.assertEqual(self.store.get(child["id"])["status"], "blocked")
        self.store.publish_review_artifact(
            parent["id"], "https://github.com/acme/app/pull/1", "a" * 40,
            ["backend/module.py"], is_draft=True, is_open=True,
        )
        next_job = self.store.claim_ready("worker-b")
        self.assertEqual(next_job["id"], child["id"])

    def test_dependency_cycle_is_rejected(self):
        first = self.store.create("First")
        second = self.store.create("Second")
        self.store.add_dependency(second["id"], first["id"])
        with self.assertRaises(DevelopmentJobConflict):
            self.store.add_dependency(first["id"], second["id"])

    def test_missing_dependency_is_rejected(self):
        job = self.store.create("Job")
        with self.assertRaises(DevelopmentJobNotFound):
            self.store.add_dependency(job["id"], "missing")

    def test_completion_gate_rejects_noop_and_test_only(self):
        job = self.store.create("Must change code")
        claim = self.store.claim_ready("worker-a")
        with self.assertRaisesRegex(ValueError, "changed file"):
            self.store.mark_review_pending(job["id"], "worker-a", claim["lease_token"],
                                [], True, "ci://run/1")
        with self.assertRaisesRegex(ValueError, "tests_passed"):
            self.store.mark_review_pending(job["id"], "worker-a", claim["lease_token"],
                                ["backend/file.py"], False, "ci://run/1")
        self.assertEqual(self.store.get(job["id"])["status"], "leased")

    def test_completion_requires_evidence_and_valid_fence(self):
        job = self.store.create("Completion", scope=["backend/file.py"])
        claim = self.store.claim_ready("worker-a")
        with self.assertRaisesRegex(ValueError, "validation evidence"):
            self.store.mark_review_pending(job["id"], "worker-a", claim["lease_token"],
                                ["backend/file.py"], True, "")
        with self.assertRaises(DevelopmentJobConflict):
            self.store.mark_review_pending(job["id"], "worker-b", claim["lease_token"],
                                ["backend/file.py"], True, "ci://run/2")
        pending = self.store.mark_review_pending(job["id"], "worker-a", claim["lease_token"],
                                                 ["backend/file.py"], True, "ci://run/2")
        self.assertEqual(pending["status"], "review_pending")
        completed = self.store.publish_review_artifact(
            job["id"], "https://github.com/acme/app/pull/2", "b" * 40,
            ["backend/file.py"], is_draft=True, is_open=True,
        )
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["changed_files"], ["backend/file.py"])
        self.assertEqual(completed["review_head_sha"], "b" * 40)
        self.assertTrue(completed["tests_passed"])

    def test_event_history_is_append_only(self):
        job = self.store.create("Audit")
        with self.store.db() as connection:
            event_id = connection.execute(
                "SELECT id FROM development_job_events WHERE job_id=? LIMIT 1",
                (job["id"],),
            ).fetchone()["id"]
            with self.assertRaisesRegex(sqlite3.IntegrityError,
                                        "development job events are immutable"):
                connection.execute("UPDATE development_job_events SET actor='tampered' WHERE id=?",
                                   (event_id,))

    def test_retry_wait_is_reclaimed_and_non_retryable_failure_quarantines(self):
        job = self.store.create("Retry", max_attempts=3)
        first = self.store.claim_ready("worker-a")
        waiting = self.store.fail(job["id"], "worker-a", first["lease_token"],
                                  "temporary provider error", retry_delay_seconds=0)
        self.assertEqual(waiting["status"], "retry_wait")
        second = self.store.claim_ready("worker-b")
        self.assertEqual(second["id"], job["id"])
        self.assertEqual(second["attempts"], 2)
        quarantined = self.store.fail(job["id"], "worker-b", second["lease_token"],
                                      "permanent validation error", retryable=False)
        self.assertEqual(quarantined["status"], "quarantined")
        self.assertIsNone(self.store.claim_ready("worker-c"))

    def test_overlapping_file_scope_serializes_jobs(self):
        first = self.store.create("Writer A", scope=["backend/shared.py"])
        second = self.store.create("Writer B", scope=["backend/shared.py"])
        claim = self.store.claim_ready("worker-a")
        self.assertEqual(claim["id"], first["id"])
        self.assertIsNone(self.store.claim_ready("worker-b"))
        self.store.mark_review_pending(first["id"], "worker-a", claim["lease_token"],
                                       ["backend/shared.py"], True, "ci://run/1")
        self.assertIsNone(self.store.claim_ready("worker-b"))
        self.store.publish_review_artifact(
            first["id"], "https://github.com/acme/app/pull/3", "c" * 40,
            ["backend/shared.py"], is_draft=True, is_open=True,
        )
        next_claim = self.store.claim_ready("worker-b")
        self.assertEqual(next_claim["id"], second["id"])

    def test_store_scope_gate_requires_explicit_directory_marker(self):
        extensionless = self.store.create("Extensionless file", scope=["LICENSE"])
        file_claim = self.store.claim_ready("worker-file")
        with self.assertRaisesRegex(ValueError, "outside the declared scope"):
            self.store.mark_review_pending(
                extensionless["id"], "worker-file", file_claim["lease_token"],
                ["LICENSE/generated.py"], True, "ci://run/extensionless",
            )

        directory = self.store.create("Directory scope", scope=["backend/"])
        directory_claim = self.store.claim_ready("worker-directory")
        pending = self.store.mark_review_pending(
            directory["id"], "worker-directory", directory_claim["lease_token"],
            ["backend/module.py"], True, "ci://run/directory",
        )
        self.assertEqual(pending["status"], "review_pending")

    def test_parent_child_path_scopes_conflict(self):
        self.assertTrue(self.store._scopes_conflict(["backend"], ["backend/api.py"]))
        self.assertFalse(self.store._scopes_conflict(["backend/api.py"], ["frontend/app.js"]))
        self.assertTrue(self.store._scopes_conflict([], ["frontend/app.js"]))

    def test_case_only_scope_aliases_serialize_on_windows_runner(self):
        self.assertTrue(self.store._scopes_conflict(["Backend/"], ["backend/api.py"]))
        self.assertTrue(self.store._scopes_conflict(["BACKEND/API.py"], ["backend/api.py"]))
        self.assertTrue(self.store._scopes_conflict(["backend//api.py"], ["backend/api.py"]))
        self.assertTrue(self.store._scopes_conflict(["./backend/api.py"], ["backend/api.py"]))
        self.assertTrue(self.store._scopes_conflict(["backend\\\\api.py"], ["backend/api.py"]))
        self.assertFalse(self.store._scopes_conflict(["Backend/"], ["frontend/app.js"]))

        self.store.create("Uppercase directory writer", priority=1, scope=["Backend/"])
        self.store.create("Lowercase child writer", priority=2, scope=["backend/api.py"])
        first = self.store.claim_ready("worker-case-a")
        self.assertEqual(first["scope"], ["Backend/"])
        self.assertIsNone(self.store.claim_ready("worker-case-b"))

    def test_attempt_limit_quarantines_job(self):
        job = self.store.create("One attempt only", max_attempts=1)
        claim = self.store.claim_ready("worker-a")
        result = self.store.fail(job["id"], "worker-a", claim["lease_token"], "failed")
        self.assertEqual(result["status"], "quarantined")

    def test_expired_lease_is_reclaimed_and_old_worker_is_fenced(self):
        job = self.store.create("Lease recovery")
        first = self.store.claim_ready("worker-a")
        with self.store.db() as connection:
            connection.execute(
                "UPDATE development_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
                (job["id"],),
            )
        second = self.store.claim_ready("worker-b")
        self.assertEqual(second["id"], job["id"])
        self.assertNotEqual(first["lease_token"], second["lease_token"])
        with self.assertRaises(DevelopmentJobConflict):
            self.store.mark_review_pending(job["id"], "worker-a", first["lease_token"],
                                ["backend/file.py"], True, "ci://run/stale")
        self.assertEqual(self.store.get(job["id"])["worker_id"], "worker-b")

    def test_parallel_workers_claim_distinct_jobs(self):
        from concurrent.futures import ThreadPoolExecutor
        jobs = [self.store.create("Job " + str(i), scope=["backend/module_" + str(i) + ".py"]) for i in range(4)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            claimed = list(pool.map(lambda i: self.store.claim_ready("worker-" + str(i)), range(4)))
        ids = [item["id"] for item in claimed if item]
        self.assertEqual(len(ids), 4)
        self.assertEqual(len(set(ids)), 4)


    def test_completion_rejects_changed_files_outside_declared_scope(self):
        job = self.store.create("Scoped completion", scope=["backend/allowed.py"])
        claim = self.store.claim_ready("worker-a")
        with self.assertRaisesRegex(ValueError, "outside the declared scope"):
            self.store.mark_review_pending(job["id"], "worker-a", claim["lease_token"],
                                ["backend/other.py"], True, "ci://run/3")
        self.assertEqual(self.store.get(job["id"])["status"], "leased")

    def test_completion_rejects_unsafe_and_duplicate_paths(self):
        job = self.store.create("Safe paths", scope=["backend"])
        claim = self.store.claim_ready("worker-a")
        for paths in (["../outside.py"], ["backend\\\\secret.py"], ["backend/a.py", "backend/a.py"]):
            with self.subTest(paths=paths):
                with self.assertRaises(ValueError):
                    self.store.mark_review_pending(job["id"], "worker-a", claim["lease_token"],
                                        paths, True, "ci://run/4")
        self.assertEqual(self.store.get(job["id"])["status"], "leased")


    def test_summary_reports_active_expired_leases_and_latest_validation(self):
        active = self.store.create("Active lease", scope=["backend/active.py"])
        claim = self.store.claim_ready("worker-a")
        completed = self.store.create("Completed work", scope=["backend/done.py"])
        done_claim = self.store.claim_ready("worker-b")
        self.store.mark_review_pending(completed["id"], "worker-b", done_claim["lease_token"],
                            ["backend/done.py"], True, "ci://run/42")
        expired = self.store.create("Expired lease", scope=["backend/expired.py"])
        expired_claim = self.store.claim_ready("worker-c")
        with self.store.db() as connection:
            connection.execute(
                "UPDATE development_jobs SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
                (expired["id"],),
            )
        summary = self.store.summary()
        self.assertEqual(summary["active_leases"], 1)
        self.assertEqual(summary["expired_leases"], 1)
        self.assertEqual(summary["latest_validation_ref"], "ci://run/42")
        self.assertTrue(summary["latest_updated_at"])


    def test_worker_presence_lifecycle_and_summary(self):
        worker = self.store.touch_worker("runner-a", hostname="WINNER", current_job_id="DEV-1")
        self.assertEqual(worker["status"], "online")
        self.assertEqual(worker["hostname"], "WINNER")
        self.assertEqual(worker["current_job_id"], "DEV-1")
        listed = self.store.list_workers()
        self.assertEqual(len(listed), 1)
        self.assertTrue(listed[0]["is_online"])
        self.assertEqual(self.store.summary()["online_workers"], 1)
        self.assertTrue(self.store.stop_worker("runner-a"))
        stopped = self.store.get_worker("runner-a")
        self.assertEqual(stopped["status"], "offline")
        self.assertIsNone(stopped["current_job_id"])
        self.assertEqual(self.store.summary()["online_workers"], 0)

    def test_worker_presence_rejects_invalid_identity(self):
        with self.assertRaises(ValueError):
            self.store.touch_worker("")
        with self.assertRaises(ValueError):
            self.store.list_workers(online_within_seconds=0)



    def test_review_artifact_requires_draft_open_and_all_changed_files(self):
        job = self.store.create("Review evidence", scope=["backend/review.py"])
        claim = self.store.claim_ready("worker-review")
        self.store.mark_review_pending(
            job["id"], "worker-review", claim["lease_token"],
            ["backend/review.py"], True, "ci://run/55",
        )
        with self.assertRaisesRegex(ValueError, "does not contain"):
            self.store.publish_review_artifact(
                job["id"], "https://github.com/acme/app/pull/4", "d" * 40,
                ["backend/other.py"], is_draft=True, is_open=True,
            )
        with self.assertRaisesRegex(ValueError, "Draft"):
            self.store.publish_review_artifact(
                job["id"], "https://github.com/acme/app/pull/4", "d" * 40,
                ["backend/review.py"], is_draft=False, is_open=True,
            )
        with self.assertRaisesRegex(ValueError, "open"):
            self.store.publish_review_artifact(
                job["id"], "https://github.com/acme/app/pull/4", "d" * 40,
                ["backend/review.py"], is_draft=True, is_open=False,
            )
        self.assertEqual(self.store.get(job["id"])["status"], "review_pending")
        published = self.store.publish_review_artifact(
            job["id"], "https://github.com/acme/app/pull/4", "d" * 40,
            ["backend/review.py"], is_draft=True, is_open=True,
        )
        self.assertEqual(published["status"], "completed")
        self.assertEqual(published["review_url"], "https://github.com/acme/app/pull/4")
        event_types = [event["event_type"] for event in self.store.events(job["id"])]
        self.assertIn("review_pending", event_types)
        self.assertIn("review_published", event_types)

    def test_review_artifact_columns_migrate_existing_database_in_place(self):
        import sqlite3
        if sqlite3.sqlite_version_info < (3, 35, 0):
            self.skipTest("SQLite DROP COLUMN requires 3.35+")
        with self.store.db() as connection:
            connection.execute("ALTER TABLE development_jobs DROP COLUMN review_published_at")
            connection.execute("ALTER TABLE development_jobs DROP COLUMN review_head_sha")
            connection.execute("ALTER TABLE development_jobs DROP COLUMN review_url")
        migrated = DevelopmentJobStore(self.store.db_path)
        with migrated.db() as connection:
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(development_jobs)")}
        self.assertTrue({"review_url", "review_head_sha", "review_published_at"}.issubset(columns))

    def test_review_artifact_publication_is_idempotent_for_same_head(self):
        job = self.store.create("Idempotent review", scope=["backend/review.py"])
        claim = self.store.claim_ready("worker-review")
        self.store.mark_review_pending(
            job["id"], "worker-review", claim["lease_token"],
            ["backend/review.py"], True, "ci://run/56",
        )
        args = (
            job["id"], "https://github.com/acme/app/pull/5", "e" * 40,
            ["backend/review.py"],
        )
        first = self.store.publish_review_artifact(*args, is_draft=True, is_open=True)
        second = self.store.publish_review_artifact(*args, is_draft=True, is_open=True)
        self.assertEqual(first["status"], "completed")
        self.assertEqual(second["review_head_sha"], "e" * 40)
        with self.assertRaises(DevelopmentJobConflict):
            self.store.publish_review_artifact(
                job["id"], "https://github.com/acme/app/pull/5", "f" * 40,
                ["backend/review.py"], is_draft=True, is_open=True,
            )


if __name__ == "__main__":
    unittest.main()
