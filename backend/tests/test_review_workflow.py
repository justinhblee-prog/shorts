import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from production_pipeline import ProductionStore
from review_workflow import ReviewStore, ReviewConflict, ReviewNotFound, valid_review_token
from queue_store import JobQueue
from queue_store import JobQueue


class ReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "review.sqlite3")
        self.production = ProductionStore(self.db)
        self.queue = JobQueue(self.db)
        self.review = ReviewStore(self.db)
        brief = {
            "brand": "Brain Glitch", "region": "US",
            "language": "English", "topic": "Sleep"
        }
        self.production.create("job-1", brief)
        self.production.stage("job-1", "rendered", "review_pending")
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.queue.db() as connection:
            connection.execute("""
                INSERT INTO pipeline_jobs
                  (id,job_type,payload_json,status,priority,attempt,max_attempts,
                   available_at,created_at,updated_at)
                VALUES(?,?,?,'review_pending',100,0,3,?,?,?)
            """, (
                "job-1", "short_video_production",
                json.dumps(brief, ensure_ascii=False),
                timestamp, timestamp, timestamp,
            ))
            self.queue.event(
                connection, "job-1", "rendered", "running",
                "review_pending", "test-worker",
            )
        self.production.artifact("job-1", "rendering", "video",
                                  "https://media.example/video.mp4", {"duration": 30})

    def tearDown(self):
        self.tmp.cleanup()

    def test_pending_queue_contains_real_artifact_reference(self):
        pending = self.review.list_pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["artifacts"][0]["artifact_url"],
                         "https://media.example/video.mp4")

    def test_review_payloads_redact_provider_errors_and_nested_secrets(self):
        secret_error = "Authorization: Bearer provider-secret-value"
        self.production.stage("job-1", "review", "review_pending", error=secret_error)
        self.production.artifact("job-1", "script", "text", None, {
            "script": "Safe script text",
            "provider": "test-provider",
            "access_token": "provider-access-secret",
            "provider_token": "provider-generic-token-secret",
            "nested": {
                "authorization": "Bearer nested-secret",
                "signed_url": "https://cdn.example/video?sig=signed-secret",
                "provider_request_id": "private-request-id",
                "error": "raw-provider-error",
                "safe_metric": 0.97,
            },
        })

        pending = self.review.list_pending()[0]
        serialized_pending = str(pending)
        for secret in (
            "provider-secret-value", "provider-access-secret", "provider-generic-token-secret", "nested-secret",
            "signed-secret", "private-request-id", "raw-provider-error",
        ):
            self.assertNotIn(secret, serialized_pending)
        self.assertEqual(pending["error"], ReviewStore.SAFE_ERROR_NOTICE)
        script = next(item for item in pending["artifacts"] if item["stage"] == "script")
        self.assertEqual(script["metadata"]["script"], "Safe script text")
        self.assertEqual(script["metadata"]["nested"]["safe_metric"], 0.97)
        self.assertEqual(script["metadata"]["nested"]["error"], ReviewStore.SAFE_ERROR_NOTICE)

        self.review.decide("job-1", "approved", "operator-1", "Reviewed")
        approved = self.review.list_approved()[0]
        serialized_approved = str(approved)
        for secret in (
            "provider-secret-value", "provider-access-secret", "nested-secret",
            "signed-secret", "private-request-id", "raw-provider-error",
        ):
            self.assertNotIn(secret, serialized_approved)
        # Approval clears the operational error; no raw diagnostic is returned.
        self.assertIsNone(approved["error"])

    def test_pending_review_exposes_frozen_brand_guidance_from_job_payload(self):
        queue = JobQueue(self.db)
        job = queue.enqueue("short_video_production", {
            "brand": "Brain Glitch", "region": "US", "language": "English",
            "topic": "Sleep", "brand_profile": {
                "positioning": "Evidence-led brain explainers",
                "audience": "curious adults", "tone": ["clear", "careful"],
                "risk_level": "high",
                "review_rules": ["Cite sources", "No diagnosis"],
            },
        })
        self.production.create(job["id"], {
            "brand": "Brain Glitch", "region": "US",
            "language": "English", "topic": "Sleep",
        })
        self.production.stage(job["id"], "rendered", "review_pending")
        pending = self.review.list_pending()
        item = next(entry for entry in pending if entry["job_id"] == job["id"])
        self.assertEqual(item["brand_profile"]["risk_level"], "high")
        self.assertEqual(item["brand_profile"]["review_rules"],
                         ["Cite sources", "No diagnosis"])
        self.assertNotIn("job_payload_json", item)

    def test_policy_review_required_needs_explicit_approval_note(self):
        self.production.artifact("job-1", "script", "text", None, {
            "script": "Example", "policy_preflight": {
                "status": "review_required",
                "required_confirmations": ["rights.visuals_cleared", "factual_claims_verified"]
            }
        })
        with self.assertRaisesRegex(ValueError, "explicit reviewer confirmation"):
            self.review.decide("job-1", "approved", "operator-1", "")
        result = self.review.decide("job-1", "approved", "operator-1",
                                    "Confirmed rights and factual claims in source records")
        self.assertEqual(result["production"]["status"], "approved")
        self.assertIn("Confirmed rights", result["decision"]["comment"])

    def test_policy_evidence_update_is_audited_and_unblocks_only_after_platform_disclosures(self):
        brief = {
            "brand": "Brain Glitch", "region": "US",
            "language": "English", "topic": "Synthetic explainer",
        }
        job = self.queue.enqueue("short_video_production", brief)
        job_id = job["id"]
        claimed = self.queue.claim("policy-worker", job_type="short_video_production")
        self.production.create(job_id, brief)
        self.production.stage(job_id, "rendered", "review_pending")
        self.production.artifact(job_id, "script", "text", None, {"script": "Example"})
        self.queue.finish(job_id, "policy-worker", claimed["lease_token"], {})

        first = self.review.update_policy_evidence(job_id, "operator-1", {
            "rights": {
                "visuals_cleared": True, "audio_cleared": True,
                "likeness_authorized": True,
            },
            "synthetic_media_status": "realistic_alteration",
            "platform_disclosures": {"youtube_altered_content": True},
        })
        self.assertIn(
            "platform_disclosures.tiktok_ai_generated_content",
            first["policy_preflight"]["approval_blockers"],
        )
        with self.assertRaisesRegex(ReviewConflict, "approval blockers"):
            self.review.decide(job_id, "approved", "operator-1", "Reviewed")

        second = self.review.update_policy_evidence(job_id, "operator-1", {
            "platform_disclosures": {"tiktok_ai_generated_content": True},
        })
        self.assertEqual(second["policy_preflight"]["approval_blockers"], [])
        history = self.review.policy_evidence_history(job_id)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[-1]["policy_preflight"]["platforms"], ["youtube", "tiktok"])
        approved = self.review.decide(
            job_id, "approved", "operator-1", "Reviewed script, rights, and disclosure settings"
        )
        self.assertEqual(approved["production"]["status"], "approved")

    def test_policy_evidence_api_store_accepts_tiktok_prohibited_aigc_flags(self):
        brief = {
            "brand": "Brain Glitch", "region": "US",
            "language": "English", "topic": "AI likeness safety",
        }
        job = self.queue.enqueue("short_video_production", brief)
        job_id = job["id"]
        claimed = self.queue.claim("policy-worker-2", job_type="short_video_production")
        self.production.create(job_id, brief)
        self.production.stage(job_id, "rendered", "review_pending")
        self.production.artifact(job_id, "script", "text", None, {"script": "Example"})
        self.queue.finish(job_id, "policy-worker-2", claimed["lease_token"], {})
        result = self.review.update_policy_evidence(job_id, "operator-1", {
            "policy_flags": {"tiktok_prohibited_aigc_minor_likeness": True},
        })
        self.assertEqual(result["policy_preflight"]["status"], "blocked")
        self.assertIn(
            "tiktok_prohibited_aigc_minor_likeness",
            result["policy_preflight"]["blocking_reasons"],
        )

    def test_policy_approval_blockers_cannot_be_overridden_by_reviewer_comment(self):
        self.production.artifact("job-1", "script", "text", None, {
            "script": "Example", "policy_preflight": {
                "status": "review_required",
                "required_confirmations": ["platform_disclosures.youtube_altered_content"],
                "approval_blockers": ["platform_disclosures.youtube_altered_content"],
            }
        })
        with self.assertRaisesRegex(ReviewConflict, "approval blockers"):
            self.review.decide(
                "job-1", "approved", "operator-1",
                "I reviewed it; proceed despite missing disclosure"
            )
        self.assertEqual(self.production.get("job-1")["status"], "review_pending")

    def test_policy_blocked_content_cannot_be_approved(self):
        self.production.artifact("job-1", "script", "text", None, {
            "script": "Example", "policy_preflight": {
                "status": "blocked", "blocking_reasons": ["known_unauthorized_assets"]
            }
        })
        with self.assertRaisesRegex(ReviewConflict, "Policy-blocked"):
            self.review.decide("job-1", "approved", "operator-1", "Reviewed")
        self.assertEqual(self.production.get("job-1")["status"], "review_pending")

    def test_quality_blockers_cannot_be_overridden_by_reviewer_comment(self):
        self.production.artifact("job-1", "quality_check", "report", None, {
            "status": "blocked",
            "blockers": ["render_format_is_not_vertical_9_16"],
            "warnings": [],
        })
        with self.assertRaisesRegex(ReviewConflict, "Quality-blocked"):
            self.review.decide("job-1", "approved", "operator-1",
                               "I reviewed it; approve despite quality blocker")
        self.assertEqual(self.production.get("job-1")["status"], "review_pending")

    def test_quality_warnings_require_explicit_reviewer_confirmation(self):
        self.production.artifact("job-1", "quality_check", "report", None, {
            "status": "review_required",
            "blockers": [],
            "warnings": ["render_aspect_ratio_not_reported"],
        })
        with self.assertRaisesRegex(ValueError, "Quality warnings"):
            self.review.decide("job-1", "approved", "operator-1", "")
        result = self.review.decide(
            "job-1", "approved", "operator-1",
            "Reviewed actual rendered dimensions and captions manually"
        )
        self.assertEqual(result["production"]["status"], "approved")

    def _create_queue_backed_review_job(self, job_id):
        brief = {
            "brand": "Brain Glitch", "region": "US",
            "language": "English", "topic": "Review transition",
        }
        job = self.queue.enqueue("short_video_production", brief)
        claimed = self.queue.claim("review-worker", job_type="short_video_production")
        self.production.create(job["id"], brief)
        self.production.stage(job["id"], "rendered", "review_pending")
        self.queue.finish(job["id"], "review-worker", claimed["lease_token"], {})
        return job["id"]

    def test_review_decision_fails_closed_when_durable_queue_job_is_missing(self):
        with self.queue.db() as connection:
            connection.execute("DELETE FROM pipeline_jobs WHERE id=?", ("job-1",))
        with self.assertRaisesRegex(ReviewConflict, "Durable queue job is missing"):
            self.review.decide("job-1", "approved", "operator-1", "Reviewed")
        self.assertEqual(self.production.get("job-1")["status"], "review_pending")
        self.assertEqual(self.review.history("job-1"), [])

    def test_review_decision_fails_closed_when_durable_queue_table_is_missing(self):
        with self.queue.db() as connection:
            connection.execute("DROP TABLE job_events")
            connection.execute("DROP TABLE pipeline_jobs")
        with self.assertRaisesRegex(ReviewConflict, "Durable queue is unavailable"):
            self.review.decide("job-1", "approved", "operator-1", "Reviewed")
        self.assertEqual(self.production.get("job-1")["status"], "review_pending")
        self.assertEqual(self.review.history("job-1"), [])

    def test_approval_atomically_synchronizes_queue_and_audit_event(self):
        job_id = self._create_queue_backed_review_job("unused")
        result = self.review.decide(
            job_id, "approved", "operator-approval", "Recovered render reviewed"
        )
        self.assertEqual(result["production"]["status"], "approved")
        self.assertEqual(self.queue.get(job_id)["status"], "approved")
        events = self.queue.events(job_id)
        review_event = events[-1]
        self.assertEqual(review_event["event_type"], "review_approved")
        self.assertEqual(review_event["from_status"], "review_pending")
        self.assertEqual(review_event["to_status"], "approved")
        self.assertEqual(review_event["worker_id"], "operator-approval")
        self.assertEqual(review_event["details"]["reviewer_id"], "operator-approval")

    def test_changed_artifacts_reopen_approved_queue_for_fresh_review(self):
        job_id = self._create_queue_backed_review_job("unused")
        self.review.decide(job_id, "approved", "operator-approval", "First approval")
        self.assertEqual(self.queue.get(job_id)["status"], "approved")
        self.production.stage(job_id, "review", "review_pending")
        self.assertEqual(self.production.get(job_id)["status"], "review_pending")
        self.assertEqual(self.queue.get(job_id)["status"], "review_pending")
        self.assertEqual(self.queue.events(job_id)[-1]["event_type"], "review_reopened")
        self.review.decide(job_id, "approved", "operator-reapproval", "Fresh review complete")
        self.assertEqual(self.queue.get(job_id)["status"], "approved")
        self.assertEqual(len(self.review.history(job_id)), 2)

    def test_rejection_atomically_synchronizes_queue_and_audit_event(self):
        job_id = self._create_queue_backed_review_job("unused")
        self.review.decide(job_id, "rejected", "operator-rejection", "Output is unsuitable")
        self.assertEqual(self.production.get(job_id)["status"], "rejected")
        self.assertEqual(self.queue.get(job_id)["status"], "rejected")
        self.assertEqual(self.queue.events(job_id)[-1]["event_type"], "review_rejected")

    def test_queue_state_mismatch_rolls_back_review_decision(self):
        job_id = self._create_queue_backed_review_job("unused")
        with self.queue.db() as connection:
            connection.execute(
                "UPDATE pipeline_jobs SET status='queued' WHERE id=?", (job_id,)
            )
        with self.assertRaisesRegex(ReviewConflict, "matching review_pending"):
            self.review.decide(job_id, "approved", "operator-1", "Reviewed")
        self.assertEqual(self.production.get(job_id)["status"], "review_pending")
        self.assertEqual(self.queue.get(job_id)["status"], "queued")
        self.assertEqual(self.review.history(job_id), [])

    def test_approval_is_explicit_and_audited_with_snapshot(self):
        result = self.review.decide("job-1", "approved", "operator-1", "Looks good")
        self.assertEqual(result["production"]["status"], "approved")
        self.assertEqual(result["decision"]["reviewer_id"], "operator-1")
        self.assertEqual(result["decision"]["artifact_snapshot"][0]["artifact_url"],
                         "https://media.example/video.mp4")
        self.assertEqual(len(self.review.history("job-1")), 1)


    def test_approved_queue_contains_only_approved_jobs(self):
        self.review.decide("job-1", "approved", "operator-1", "Looks good")
        items = self.review.list_approved()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["job_id"], "job-1")
        self.assertEqual(items[0]["status"], "approved")
        self.assertEqual(items[0]["artifacts"][0]["artifact_type"], "video")

    def test_rejection_and_revision_require_reason(self):
        with self.assertRaises(ValueError):
            self.review.decide("job-1", "rejected", "operator-1", "")
        result = self.review.decide("job-1", "revision_requested",
                                    "operator-1", "Captions are inaccurate")
        self.assertEqual(result["production"]["status"], "revision_requested")

    def test_second_decision_cannot_overwrite_first(self):
        self.review.decide("job-1", "approved", "operator-1")
        with self.assertRaises(ReviewConflict):
            self.review.decide("job-1", "rejected", "operator-2", "Changed mind")
        self.assertEqual(len(self.review.history("job-1")), 1)

    def test_unknown_job(self):
        with self.assertRaises(ReviewNotFound):
            self.review.decide("missing", "approved", "operator-1")

    def test_review_token_fails_closed(self):
        self.assertFalse(valid_review_token("abc", None))
        self.assertFalse(valid_review_token("wrong", "secret"))
        self.assertTrue(valid_review_token("secret", "secret"))


if __name__ == "__main__":
    unittest.main()
