import json
import hashlib
import os
import sqlite3
import tempfile, threading, time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from production_pipeline import ProductionStore
from queue_store import JobQueue
from review_workflow import ReviewStore
from youtube_publishing import YouTubeUploadStore, YouTubePublisher, YouTubeUploadError
from policy_engine import evaluate_content_policy, POLICY_VERSION, POLICY_CHECKED_ON


class FakeRequest:
    def __init__(self,response): self.response=response
    def next_chunk(self): return None,self.response
    def execute(self): return self.response


class FakeVideos:
    def insert(self,**kwargs):
        self.body=kwargs["body"]
        self.media=kwargs["media_body"]
        return FakeRequest({"id":"yt-video-123"})
    def list(self,**kwargs):
        return FakeRequest({"items":[{"statistics":{"viewCount":"123","likeCount":"8",
                            "commentCount":"2"},"status":{"privacyStatus":"private"}}]})


class FakeService:
    def __init__(self): self._videos=FakeVideos()
    def videos(self): return self._videos


class TimeoutRequest:
    def next_chunk(self):
        raise TimeoutError("connection dropped after request started")


class TimeoutVideos:
    def __init__(self): self.insert_calls=0
    def insert(self,**kwargs):
        self.insert_calls+=1
        return TimeoutRequest()


class TimeoutService:
    def __init__(self): self._videos=TimeoutVideos()
    def videos(self): return self._videos


class BatchVideos:
    def __init__(self):
        self.calls=[]
    def list(self,**kwargs):
        self.calls.append(kwargs)
        ids=kwargs["id"].split(",")
        return FakeRequest({"items":[
            {"id":video_id,"statistics":{"viewCount":"250","likeCount":"12",
             "commentCount":"3"},"status":{"privacyStatus":"private"}}
            for video_id in ids
        ]})


class BatchService:
    def __init__(self):
        self._videos=BatchVideos()
    def videos(self):
        return self._videos


class YouTubePublishingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=os.path.join(self.tmp.name,"db.sqlite3")
        self.queue=JobQueue(self.db)
        self.prod=ProductionStore(self.db)
        self.review=ReviewStore(self.db)
        self.uploads=YouTubeUploadStore(self.db)
        self.prod.create("job-1",{"brand":"Brain Glitch","region":"US",
                                  "language":"English","topic":"Sleep"})
        self.prod.stage("job-1","rendered","review_pending")
        with self.queue.db() as connection:
            timestamp="2026-11-16T00:00:00+00:00"
            connection.execute("""
                INSERT INTO pipeline_jobs
                  (id,job_type,payload_json,status,priority,attempt,max_attempts,
                   available_at,created_at,updated_at)
                VALUES(?,?,?,'review_pending',100,0,3,?,?,?)
            """, ("job-1","short_video_production",
                  json.dumps({"brand":"Brain Glitch","region":"US",
                              "language":"English","topic":"Sleep"}),
                  timestamp,timestamp,timestamp))
        os.environ["NEXUS_MEDIA_DIR"]=self.tmp.name
        self.media=os.path.join(self.tmp.name,"video.mp4")
        media_bytes=b"fake-media-for-unit-test"
        Path(self.media).write_bytes(media_bytes)
        media_staging={"media_path":"video.mp4","size_bytes":len(media_bytes),
                       "sha256":hashlib.sha256(media_bytes).hexdigest(),
                       "content_type":"video/mp4"}
        self.prod.artifact("job-1","rendering","video",
                           "https://media.example/video.mp4",
                           {"media_staging":media_staging})
        policy_brief = {
            "rights": {"visuals_cleared": True, "audio_cleared": True,
                       "likeness_authorized": True},
            "synthetic_media_status": "none",
            "factual_claims_verified": True,
            "originality_notes": "Original educational narration.",
        }
        self.prod.artifact(
            "job-1", "script", "text", None,
            {"script": "Approved test script",
             "policy_preflight": evaluate_content_policy(policy_brief)},
        )
        self.review.decide("job-1","approved","reviewer-1")
        self.service=FakeService()
        self.publisher=YouTubePublisher(self.uploads,self.service)

    def tearDown(self): self.tmp.cleanup()

    def test_concurrent_upload_reservations_allow_only_one_attempt(self):
        gate=threading.Event()
        def reserve(title):
            gate.wait()
            try:
                return self.uploads.begin("job-1",title,"Description")["attempt_id"]
            except YouTubeUploadError:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures=[pool.submit(reserve,f"Title {index}") for index in range(8)]
            gate.set()
            results=[future.result() for future in futures]
        winners=[attempt for attempt in results if attempt is not None]
        self.assertEqual(len(winners),1)
        current=self.uploads.get("job-1")
        self.assertEqual(current["attempt_id"],winners[0])
        self.assertEqual(current["status"],"uploading")
        starts=[event for event in current["events"] if event["event_type"]=="upload_attempt_started"]
        self.assertEqual(len(starts),1)

    def test_late_upload_completion_cannot_override_reconciled_not_uploaded(self):
        first_attempt=self.uploads.begin("job-1", "Title", "Description")
        self.uploads.mark_reconciliation_required("job-1", "timeout",first_attempt["attempt_id"])
        self.uploads.reconcile("job-1", "not_uploaded", note="Checked YouTube Studio")
        # A retry can begin after explicit no-upload confirmation. The stale
        # request must not finalize or overwrite that newer attempt.
        second_attempt=self.uploads.begin("job-1", "Retry", "")
        self.assertNotEqual(first_attempt["attempt_id"],second_attempt["attempt_id"])
        with self.assertRaises(YouTubeUploadError):
            self.uploads.finish("job-1", "late-video-id",first_attempt["attempt_id"])
        result = self.uploads.get("job-1")
        self.assertEqual(result["status"], "late_success_review_required")
        self.assertEqual(result["video_id"], "late-video-id")
        self.assertEqual(result["events"][-1]["event_type"], "late_remote_success")
        self.assertEqual(result["events"][-1]["attempt_id"],first_attempt["attempt_id"])
        with self.assertRaisesRegex(YouTubeUploadError, "blocked"):
            self.uploads.begin("job-1", "Retry", "")
        resolved=self.uploads.resolve_late_success(
            "job-1","reviewer-ops","Confirmed late video ID in YouTube Studio","late-video-id"
        )
        self.assertEqual(resolved["status"], "uploaded")
        self.assertEqual(resolved["video_id"], "late-video-id")
        self.assertEqual(resolved["events"][-1]["operator_id"], "reviewer-ops")
        self.assertEqual(resolved["events"][-1]["attempt_id"],first_attempt["attempt_id"])

    def test_superseded_worker_error_is_audited_without_clearing_late_success_review(self):
        first=self.uploads.begin("job-1","First attempt","")
        self.uploads.mark_reconciliation_required(
            "job-1","first request timed out",first["attempt_id"]
        )
        self.uploads.reconcile("job-1","not_uploaded",note="Verified no upload at that time")
        second=self.uploads.begin("job-1","Second attempt","")
        with self.assertRaises(YouTubeUploadError):
            self.uploads.finish("job-1","late-video-id",first["attempt_id"])
        before=self.uploads.get("job-1")
        self.assertEqual(before["status"],"late_success_review_required")
        self.assertEqual(before["attempt_id"],second["attempt_id"])
        self.uploads.mark_reconciliation_required(
            "job-1","late failure from superseded upload worker",first["attempt_id"]
        )
        result=self.uploads.get("job-1")
        self.assertEqual(result["status"],"late_success_review_required")
        self.assertEqual(result["attempt_id"],second["attempt_id"])
        event=result["events"][-1]
        self.assertEqual(event["event_type"],"superseded_attempt_uncertain")
        self.assertEqual(event["outcome"],"informational")
        self.assertEqual(event["attempt_id"],first["attempt_id"])
        self.assertEqual(event["previous_status"],"late_success_review_required")
        self.assertEqual(event["resulting_status"],"late_success_review_required")
        self.assertEqual(event["video_id"],"late-video-id")
        self.assertEqual(result["video_id"],"late-video-id")

    def test_superseded_worker_error_retains_its_own_video_id_after_new_upload(self):
        first=self.uploads.begin("job-1","First attempt","")
        self.uploads.mark_reconciliation_required("job-1","first timeout",first["attempt_id"])
        self.uploads.reconcile("job-1","not_uploaded",note="Verified no upload")
        second=self.uploads.begin("job-1","Second attempt","")
        self.uploads.finish("job-1","current-video",second["attempt_id"])
        with self.uploads.db() as connection:
            connection.execute("""INSERT INTO youtube_upload_events
              (job_id,attempt_id,event_type,outcome,video_id,operator_id,note,
               previous_status,resulting_status,created_at)
              VALUES(?,?,'late_remote_success','informational','old-attempt-video',
                     'system:upload_worker','Old attempt remote video observed',
                     'uploading','late_success_review_required',?)""",
              ("job-1",first["attempt_id"],"2026-01-01T00:00:00+00:00"))
        self.uploads.mark_reconciliation_required(
            "job-1","old worker reported a delayed failure",first["attempt_id"]
        )
        result=self.uploads.get("job-1")
        self.assertEqual(result["status"],"uploaded")
        self.assertEqual(result["video_id"],"current-video")
        event=result["events"][-1]
        self.assertEqual(event["event_type"],"superseded_attempt_uncertain")
        self.assertEqual(event["attempt_id"],first["attempt_id"])
        self.assertEqual(event["video_id"],"old-attempt-video")

    def test_superseded_worker_error_never_borrows_current_attempt_video_id(self):
        first=self.uploads.begin("job-1","First attempt","")
        self.uploads.mark_reconciliation_required("job-1","first timeout",first["attempt_id"])
        self.uploads.reconcile("job-1","not_uploaded",note="Verified no upload")
        second=self.uploads.begin("job-1","Second attempt","")
        self.uploads.finish("job-1","current-video",second["attempt_id"])
        self.uploads.mark_reconciliation_required(
            "job-1","old worker reported an uncertain result",first["attempt_id"]
        )
        result=self.uploads.get("job-1")
        self.assertEqual(result["video_id"],"current-video")
        event=result["events"][-1]
        self.assertEqual(event["attempt_id"],first["attempt_id"])
        self.assertIsNone(event["video_id"])

    def test_superseded_worker_error_preserves_old_video_id_while_new_attempt_uploads(self):
        first=self.uploads.begin("job-1","First attempt","")
        self.uploads.mark_reconciliation_required("job-1","first timeout",first["attempt_id"])
        self.uploads.reconcile("job-1","not_uploaded",note="Verified no upload")
        with self.uploads.db() as connection:
            connection.execute("""INSERT INTO youtube_upload_events
              (job_id,attempt_id,event_type,outcome,video_id,operator_id,note,
               previous_status,resulting_status,created_at)
              VALUES(?,?,'late_remote_success','informational','old-attempt-video',
                     'system:youtube_response','Old remote video observed',
                     'uploading','late_success_review_required',?)""",
              ("job-1",first["attempt_id"],"2026-01-01T00:00:00+00:00"))
        second=self.uploads.begin("job-1","Second attempt","")
        self.uploads.mark_reconciliation_required(
            "job-1","late error from old worker",first["attempt_id"]
        )
        result=self.uploads.get("job-1")
        self.assertEqual(result["attempt_id"],second["attempt_id"])
        self.assertEqual(result["status"],"reconciliation_required")
        self.assertIsNone(result["video_id"])
        event=result["events"][-1]
        self.assertEqual(event["attempt_id"],first["attempt_id"])
        self.assertEqual(event["video_id"],"old-attempt-video")

    def test_late_old_youtube_success_after_new_upload_preserves_both_video_ids(self):
        first=self.uploads.begin("job-1","First attempt","")
        self.uploads.mark_reconciliation_required(
            "job-1","first request timed out",first["attempt_id"]
        )
        self.uploads.reconcile("job-1","not_uploaded",note="Verified no upload")
        second=self.uploads.begin("job-1","Second attempt","")
        self.uploads.finish("job-1","current-attempt-video",second["attempt_id"])
        with self.assertRaisesRegex(YouTubeUploadError,"Late YouTube success"):
            self.uploads.finish("job-1","late-old-attempt-video",first["attempt_id"])
        result=self.uploads.get("job-1")
        self.assertEqual(result["attempt_id"],second["attempt_id"])
        self.assertEqual(result["status"],"late_success_review_required")
        # The canonical row keeps the confirmed current-attempt video ID.
        self.assertEqual(result["video_id"],"current-attempt-video")
        event=result["events"][-1]
        self.assertEqual(event["event_type"],"late_remote_success")
        self.assertEqual(event["attempt_id"],first["attempt_id"])
        self.assertEqual(event["video_id"],"late-old-attempt-video")
        with self.assertRaisesRegex(YouTubeUploadError,"blocked"):
            self.uploads.begin("job-1","Third attempt","")

    def test_operator_can_keep_current_video_when_stale_duplicate_arrives(self):
        first=self.uploads.begin("job-1","First attempt","")
        self.uploads.mark_reconciliation_required(
            "job-1","first request timed out",first["attempt_id"]
        )
        self.uploads.reconcile(
            "job-1","not_uploaded",note="Verified no upload at that time"
        )
        second=self.uploads.begin("job-1","Second attempt","")
        self.uploads.finish("job-1","current-video",second["attempt_id"])
        with self.assertRaises(YouTubeUploadError):
            self.uploads.finish("job-1","late-duplicate-video",first["attempt_id"])
        pending=self.uploads.get("job-1")
        self.assertEqual(pending["status"],"late_success_review_required")
        self.assertEqual(pending["video_id"],"current-video")
        late_ids=[event["video_id"] for event in pending["events"]
                  if event["event_type"]=="late_remote_success"]
        self.assertEqual(late_ids,["late-duplicate-video"])
        late_event=next(event for event in pending["events"]
                        if event["event_type"]=="late_remote_success")
        self.assertEqual(late_event["attempt_id"],first["attempt_id"])
        with self.assertRaisesRegex(YouTubeUploadError,"Choose the currently recorded"):
            self.uploads.resolve_late_success(
                "job-1","reviewer","invalid unrecorded ID","not-a-video"
            )
        resolved=self.uploads.resolve_late_success(
            "job-1","reviewer","Retained the already confirmed canonical video","current-video"
        )
        self.assertEqual(resolved["status"],"uploaded")
        self.assertEqual(resolved["video_id"],"current-video")
        self.assertEqual(resolved["events"][-1]["attempt_id"],second["attempt_id"])

    def test_superseded_attempt_uncertainty_blocks_new_attempt(self):
        first=self.uploads.begin("job-1","First attempt","")
        self.uploads.mark_reconciliation_required("job-1","first attempt timed out",first["attempt_id"])
        self.uploads.reconcile("job-1","not_uploaded",note="Checked YouTube Studio")
        second=self.uploads.begin("job-1","Retry attempt","")
        self.uploads.mark_reconciliation_required(
            "job-1","old request ended after retry began",first["attempt_id"]
        )
        result=self.uploads.get("job-1")
        self.assertEqual(result["status"],"reconciliation_required")
        self.assertEqual(result["attempt_id"],second["attempt_id"])
        self.assertEqual(result["events"][-1]["event_type"],"superseded_attempt_uncertain")
        self.assertEqual(result["events"][-1]["attempt_id"],first["attempt_id"])
        with self.assertRaises(YouTubeUploadError):
            self.uploads.begin("job-1","Third attempt","")

    def test_existing_upload_tables_migrate_attempt_audit_columns(self):
        legacy_db=os.path.join(self.tmp.name,"legacy.sqlite3")
        import sqlite3
        with sqlite3.connect(legacy_db) as connection:
            connection.executescript("""
              CREATE TABLE youtube_uploads(
                job_id TEXT PRIMARY KEY,video_id TEXT,status TEXT NOT NULL,
                privacy_status TEXT NOT NULL DEFAULT 'private',title TEXT NOT NULL,
                description TEXT NOT NULL,uploaded_at TEXT,error TEXT,updated_at TEXT NOT NULL
              );
              CREATE TABLE youtube_upload_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,
                event_type TEXT NOT NULL,outcome TEXT,video_id TEXT,
                operator_id TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',
                previous_status TEXT,resulting_status TEXT,created_at TEXT NOT NULL
              );
              CREATE TABLE production_runs(job_id TEXT PRIMARY KEY,status TEXT);
              CREATE TABLE review_decisions(id INTEGER PRIMARY KEY,job_id TEXT,decision TEXT);
            """)
        migrated=YouTubeUploadStore(legacy_db)
        with migrated.db() as connection:
            upload_columns={row["name"] for row in connection.execute("PRAGMA table_info(youtube_uploads)")}
            event_columns={row["name"] for row in connection.execute("PRAGMA table_info(youtube_upload_events)")}
        self.assertIn("attempt_id",upload_columns)
        self.assertIn("attempt_id",event_columns)
        self.assertIn("policy_version",upload_columns)
        self.assertIn("policy_checked_on",upload_columns)
        self.assertIn("policy_version",event_columns)
        self.assertIn("policy_checked_on",event_columns)

    def test_finish_requires_active_upload_state(self):
        with self.assertRaises(YouTubeUploadError):
            self.uploads.finish("missing-job", "video-id")

    def test_preflight_failure_is_audited_without_remote_request(self):
        attempt=self.uploads.begin("job-1","Bad media","")
        self.uploads.fail("job-1","Unsupported media extension",attempt["attempt_id"])
        result=self.uploads.get("job-1")
        self.assertEqual(result["status"],"failed")
        event=result["events"][-1]
        self.assertEqual(event["event_type"],"upload_preflight_failed")
        self.assertEqual(event["attempt_id"],attempt["attempt_id"])

    def test_upload_is_blocked_when_current_policy_artifact_version_is_stale(self):
        with self.uploads.db() as connection:
            row = connection.execute(
                "SELECT id,metadata_json FROM production_artifacts "
                "WHERE job_id='job-1' AND stage='script'"
            ).fetchone()
            metadata = json.loads(row["metadata_json"])
            metadata["policy_preflight"]["policy_version"] = "outdated-policy-version"
            connection.execute(
                "UPDATE production_artifacts SET metadata_json=? WHERE id=?",
                (json.dumps(metadata), row["id"]),
            )
        with self.assertRaisesRegex(YouTubeUploadError, "rules changed"):
            self.uploads.begin("job-1", "Title", "Description")
        self.assertIsNone(self.uploads.get("job-1"))

    def test_upload_is_blocked_when_approval_snapshot_has_old_policy_version(self):
        with self.uploads.db() as connection:
            row = connection.execute(
                "SELECT id,artifact_snapshot_json FROM review_decisions "
                "WHERE job_id='job-1' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            snapshot = json.loads(row["artifact_snapshot_json"])
            script = next(item for item in snapshot if item["stage"] == "script")
            script["metadata"]["policy_preflight"]["policy_version"] = "outdated-policy-version"
            connection.execute(
                "UPDATE review_decisions SET artifact_snapshot_json=? WHERE id=?",
                (json.dumps(snapshot), row["id"]),
            )
        with self.assertRaisesRegex(YouTubeUploadError, "rules changed"):
            self.uploads.begin("job-1", "Title", "Description")
        self.assertIsNone(self.uploads.get("job-1"))

    def test_upload_is_blocked_if_current_policy_evidence_has_approval_blockers(self):
        with self.uploads.db() as connection:
            row = connection.execute(
                "SELECT id,metadata_json FROM production_artifacts "
                "WHERE job_id='job-1' AND stage='script'"
            ).fetchone()
            metadata = json.loads(row["metadata_json"])
            metadata["policy_preflight"]["approval_blockers"] = [
                "platform_disclosures.youtube_altered_content"
            ]
            connection.execute(
                "UPDATE production_artifacts SET metadata_json=? WHERE id=?",
                (json.dumps(metadata), row["id"]),
            )
        with self.assertRaisesRegex(YouTubeUploadError, "blocking requirements"):
            self.uploads.begin("job-1", "Title", "Description")
        self.assertIsNone(self.uploads.get("job-1"))

    def test_upload_rejects_stale_current_policy_checked_on_date(self):
        with self.uploads.db() as connection:
            row = connection.execute(
                "SELECT id,metadata_json FROM production_artifacts "
                "WHERE job_id='job-1' AND stage='script'"
            ).fetchone()
            metadata = json.loads(row["metadata_json"])
            metadata["policy_preflight"]["policy_checked_on"] = "1900-01-01"
            connection.execute(
                "UPDATE production_artifacts SET metadata_json=? WHERE id=?",
                (json.dumps(metadata), row["id"]),
            )
        with self.assertRaisesRegex(YouTubeUploadError, "rules changed"):
            self.uploads.begin("job-1", "Title", "Description")
        self.assertIsNone(self.uploads.get("job-1"))

    def test_upload_rejects_stale_approved_policy_checked_on_date(self):
        with self.uploads.db() as connection:
            row = connection.execute(
                "SELECT id,artifact_snapshot_json FROM review_decisions "
                "WHERE job_id='job-1' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            snapshot = json.loads(row["artifact_snapshot_json"])
            approved_script = next(
                item for item in snapshot
                if item.get("stage") == "script" and item.get("artifact_type") == "text"
            )
            approved_script["metadata"]["policy_preflight"]["policy_checked_on"] = "1900-01-01"
            connection.execute(
                "UPDATE review_decisions SET artifact_snapshot_json=? WHERE id=?",
                (json.dumps(snapshot), row["id"]),
            )
        with self.assertRaisesRegex(YouTubeUploadError, "rules changed"):
            self.uploads.begin("job-1", "Title", "Description")
        self.assertIsNone(self.uploads.get("job-1"))

    def test_upload_is_blocked_when_an_approved_artifact_is_modified(self):
        with self.uploads.db() as connection:
            row = connection.execute(
                "SELECT id FROM production_artifacts "
                "WHERE job_id='job-1' AND stage='rendering' AND artifact_type='video'"
            ).fetchone()
            connection.execute(
                "UPDATE production_artifacts SET metadata_json=? WHERE id=?",
                (json.dumps({"tampered_after_approval": True}), row["id"]),
            )
        with self.assertRaisesRegex(YouTubeUploadError, "changed after human approval"):
            self.uploads.begin("job-1", "Title", "Description")
        self.assertIsNone(self.uploads.get("job-1"))

    def test_upload_is_blocked_when_an_artifact_is_added_after_approval(self):
        self.prod.artifact(
            "job-1", "post_approval", "report", None,
            {"late_artifact": True},
        )
        with self.assertRaisesRegex(YouTubeUploadError, "changed after human approval"):
            self.uploads.begin("job-1", "Title", "Description")
        self.assertIsNone(self.uploads.get("job-1"))

    def test_upload_rejects_staged_media_modified_after_approval(self):
        Path(self.media).write_bytes(b"modified-after-human-approval")
        with self.assertRaisesRegex(YouTubeUploadError, "changed after human approval"):
            self.publisher.upload_approved("job-1",self.media,self.review,"Title")
        self.assertFalse(hasattr(self.service._videos,"body"))
        self.assertIsNone(self.uploads.get("job-1"))

    def test_upload_rejects_media_path_not_matching_approved_fingerprint(self):
        other=os.path.join(self.tmp.name,"other.mp4")
        Path(other).write_bytes(Path(self.media).read_bytes())
        with self.assertRaisesRegex(YouTubeUploadError, "does not match"):
            self.publisher.upload_approved("job-1",other,self.review,"Title")
        self.assertFalse(hasattr(self.service._videos,"body"))
        self.assertIsNone(self.uploads.get("job-1"))

    def test_upload_requires_approval(self):
        self.prod.create("job-2",{"brand":"Brain Glitch","region":"US",
                                  "language":"English","topic":"Focus"})
        with self.assertRaises(YouTubeUploadError):
            self.publisher.upload_approved("job-2",self.media,self.review,"Title")

    def test_prior_approval_is_invalidated_by_a_later_revision_decision(self):
        # setUp already records the initial approval; simulate a revised
        # artifact returning to review before the later revision decision.
        self.prod.stage("job-1","review","review_pending")
        with self.queue.db() as connection:
            connection.execute(
                "UPDATE pipeline_jobs SET status='review_pending' WHERE id=?",
                ("job-1",),
            )
        self.review.decide("job-1","revision_requested","reviewer-2","Correct captions")
        with self.assertRaisesRegex(YouTubeUploadError,"latest human review decision"):
            self.publisher.upload_approved(
                "job-1",self.media,self.review,"Sleep short"
            )
        self.assertIsNone(self.uploads.get("job-1"))

    def test_current_production_status_must_still_be_approved(self):
        self.prod.stage("job-1","review","review_pending")
        with self.assertRaisesRegex(YouTubeUploadError,"must remain approved"):
            self.publisher.upload_approved(
                "job-1",self.media,self.review,"Sleep short"
            )
        self.assertIsNone(self.uploads.get("job-1"))

    def test_current_queue_status_must_still_be_approved_at_reservation(self):
        with self.queue.db() as connection:
            connection.execute(
                "UPDATE pipeline_jobs SET status='review_pending' WHERE id=?",
                ("job-1",),
            )
        with self.assertRaisesRegex(YouTubeUploadError,"queue job must remain approved"):
            self.publisher.upload_approved(
                "job-1",self.media,self.review,"Sleep short"
            )
        self.assertIsNone(self.uploads.get("job-1"))

    def test_missing_queue_row_blocks_actual_youtube_publish_reservation(self):
        with self.queue.db() as connection:
            connection.execute("DELETE FROM pipeline_jobs WHERE id=?",("job-1",))
        with self.assertRaisesRegex(YouTubeUploadError,"queue job must remain approved"):
            self.publisher.upload_approved(
                "job-1",self.media,self.review,"Sleep short"
            )
        self.assertIsNone(self.uploads.get("job-1"))

    def test_metrics_collector_lease_is_single_owner_and_releasable(self):
        second_store=YouTubeUploadStore(self.db)
        first = self.uploads.acquire_metrics_collector_lease("collector-a")
        self.assertTrue(first)
        self.assertIsNone(second_store.acquire_metrics_collector_lease("collector-b"))
        self.assertTrue(self.uploads.renew_metrics_collector_lease("collector-a", first))
        self.assertTrue(self.uploads.release_metrics_collector_lease("collector-a", first))
        second = second_store.acquire_metrics_collector_lease("collector-b")
        self.assertTrue(second)
        self.assertNotEqual(first, second)

    def test_expired_metrics_collector_cannot_renew_release_or_write_after_takeover(self):
        second_store = YouTubeUploadStore(self.db)
        now = time.time()
        old_token = self.uploads.acquire_metrics_collector_lease(
            "collector-old", lease_seconds=30, now=now,
        )
        self.assertIsNotNone(old_token)

        # Simulate a worker that stalled beyond its lease, then let another
        # process take ownership using the same durable singleton row.
        with self.uploads.db() as connection:
            connection.execute(
                "UPDATE youtube_metrics_collector_lease SET lease_until=? WHERE id=1",
                (now - 1,),
            )
        new_token = second_store.acquire_metrics_collector_lease(
            "collector-new", lease_seconds=300,
        )
        self.assertIsNotNone(new_token)
        self.assertNotEqual(old_token, new_token)

        self.assertFalse(self.uploads.renew_metrics_collector_lease(
            "collector-old", old_token,
        ))
        self.assertFalse(self.uploads.release_metrics_collector_lease(
            "collector-old", old_token,
        ))
        with self.assertRaisesRegex(RuntimeError, "stale write rejected"):
            self.uploads.snapshot(
                "yt-expired-owner", {"viewCount": "77"},
                lease_owner="collector-old", lease_token=old_token,
            )
        with self.assertRaisesRegex(RuntimeError, "stale write rejected"):
            self.uploads.record_metrics_collection(
                "failed", error="late response from expired collector",
                lease_owner="collector-old", lease_token=old_token,
            )

        with self.uploads.db() as connection:
            lease = connection.execute(
                "SELECT owner_id,token,lease_until FROM youtube_metrics_collector_lease WHERE id=1"
            ).fetchone()
            snapshot_count = connection.execute(
                "SELECT COUNT(*) FROM youtube_video_snapshots WHERE video_id='yt-expired-owner'"
            ).fetchone()[0]
        self.assertEqual(lease["owner_id"], "collector-new")
        self.assertEqual(lease["token"], new_token)
        self.assertGreater(lease["lease_until"], time.time())
        self.assertEqual(snapshot_count, 0)

        self.assertTrue(second_store.snapshot(
            "yt-new-owner", {"viewCount": "88"},
            lease_owner="collector-new", lease_token=new_token,
        ))
        self.assertTrue(second_store.release_metrics_collector_lease(
            "collector-new", new_token,
        ))

    def test_stale_metrics_lease_cannot_write_snapshot_or_collection_state(self):
        token = self.uploads.acquire_metrics_collector_lease("collector-a")
        with self.uploads.db() as connection:
            connection.execute(
                "UPDATE youtube_metrics_collector_lease SET token='replacement' WHERE id=1"
            )
        with self.assertRaisesRegex(RuntimeError, "stale write rejected"):
            self.uploads.snapshot(
                "yt-stale", {"viewCount": "5"},
                lease_owner="collector-a", lease_token=token,
            )
        with self.assertRaisesRegex(RuntimeError, "stale write rejected"):
            self.uploads.record_metrics_collection(
                "succeeded", requested=1, collected=1,
                lease_owner="collector-a", lease_token=token,
            )
        with self.uploads.db() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM youtube_video_snapshots WHERE video_id='yt-stale'"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_due_metrics_batch_refreshes_multiple_videos_in_one_api_request(self):
        self.prod.create("job-2",{"brand":"Future Leak","region":"US",
                                  "language":"English","topic":"Robotics"})
        self.prod.stage("job-2","rendered","review_pending")
        with self.queue.db() as connection:
            timestamp="2026-11-16T00:00:00+00:00"
            connection.execute("""
                INSERT INTO pipeline_jobs
                  (id,job_type,payload_json,status,priority,attempt,max_attempts,
                   available_at,created_at,updated_at)
                VALUES(?,?,?,'review_pending',100,0,3,?,?,?)
            """, ("job-2","short_video_production",
                  json.dumps({"brand":"Future Leak","region":"US",
                              "language":"English","topic":"Robotics"}),
                  timestamp,timestamp,timestamp))
        policy = evaluate_content_policy({
            "rights": {"visuals_cleared": True, "audio_cleared": True,
                       "likeness_authorized": True},
            "synthetic_media_status": "none",
            "factual_claims_verified": True,
            "originality_notes": "Original robotics explainer.",
        })
        self.prod.artifact(
            "job-2", "script", "text", None,
            {"script": "Robotics explainer", "policy_preflight": policy},
        )
        self.review.decide("job-2","approved","reviewer-1")
        for job_id,video_id in (("job-1","yt-one"),("job-2","yt-two")):
            attempt=self.uploads.begin(job_id,"Title","")
            self.uploads.finish(job_id,video_id,attempt["attempt_id"])
        batch_service=BatchService()
        publisher=YouTubePublisher(self.uploads,batch_service)
        result=publisher.refresh_due_metrics(limit=50,min_age_seconds=300)
        self.assertEqual(result["requested"],2)
        self.assertEqual(result["collected"],2)
        self.assertEqual(len(batch_service._videos.calls),1)
        self.assertEqual(set(batch_service._videos.calls[0]["id"].split(",")),{"yt-one","yt-two"})
        self.assertEqual(self.uploads.get("job-1")["snapshots"][0]["view_count"],250)
        self.assertEqual(self.uploads.get("job-2")["snapshots"][0]["like_count"],12)

    def test_recently_collected_video_is_not_due_again(self):
        attempt=self.uploads.begin("job-1","Title","")
        self.uploads.finish("job-1","yt-recent",attempt["attempt_id"])
        self.uploads.snapshot("yt-recent",{"viewCount":"100"})
        self.assertEqual(self.uploads.due_metric_video_ids(limit=50,min_age_seconds=21600),[])

    def test_upload_is_always_private_and_persists_source_stats(self):
        result=self.publisher.upload_approved("job-1",self.media,self.review,
                                              "A useful short","Description")
        self.assertEqual(result["status"],"uploaded")
        self.assertEqual(result["privacy_status"],"private")
        self.assertEqual(result["video_id"],"yt-video-123")
        self.assertEqual(result["policy_version"],POLICY_VERSION)
        self.assertEqual(result["policy_checked_on"],POLICY_CHECKED_ON)
        self.assertEqual(result["events"][0]["policy_version"],POLICY_VERSION)
        self.assertEqual(result["events"][0]["policy_checked_on"],POLICY_CHECKED_ON)
        self.assertEqual(result["events"][-1]["event_type"],"upload_confirmed")
        self.assertEqual(result["events"][-1]["video_id"],"yt-video-123")
        self.assertEqual(result["events"][-1]["attempt_id"],result["attempt_id"])
        self.assertEqual(result["events"][0]["event_type"],"upload_attempt_started")
        self.assertEqual(self.service._videos.body["status"]["privacyStatus"],"private")
        self.assertEqual(result["snapshots"][0]["view_count"],123)

    def test_stale_error_cannot_downgrade_confirmed_upload(self):
        uploaded=self.publisher.upload_approved(
            "job-1",self.media,self.review,"Confirmed short"
        )
        self.assertEqual(uploaded["status"],"uploaded")
        self.uploads.mark_reconciliation_required(
            "job-1","late stale worker exception","obsolete-attempt-token"
        )
        current=self.uploads.get("job-1")
        self.assertEqual(current["status"],"uploaded")
        self.assertEqual(current["video_id"],"yt-video-123")
        self.assertEqual(current["events"][-1]["event_type"],"superseded_attempt_uncertain")
        self.uploads.mark_reconciliation_required(
            "job-1","post-confirmation cleanup exception",uploaded["attempt_id"]
        )
        current=self.uploads.get("job-1")
        self.assertEqual(current["status"],"uploaded")
        self.assertEqual(current["events"][-1]["event_type"],"post_confirmation_worker_error")

    def test_upload_is_idempotent_after_success(self):
        first=self.publisher.upload_approved("job-1",self.media,self.review,"Title")
        second=self.publisher.upload_approved("job-1",self.media,self.review,"Title")
        self.assertEqual(first["video_id"],second["video_id"])

    def test_ambiguous_timeout_blocks_duplicate_retry_until_operator_reconciles(self):
        uncertain_service=TimeoutService()
        uncertain_publisher=YouTubePublisher(self.uploads,uncertain_service)
        with self.assertRaises(YouTubeUploadError):
            uncertain_publisher.upload_approved(
                "job-1",self.media,self.review,"Sleep short"
            )
        record=self.uploads.get("job-1")
        self.assertEqual(record["status"],"reconciliation_required")
        self.assertIn("uncertain",record["error"].lower())
        self.assertEqual(record["events"][-1]["event_type"],"upload_outcome_uncertain")
        self.assertEqual(record["events"][-1]["attempt_id"],record["attempt_id"])

        with self.assertRaises(YouTubeUploadError):
            uncertain_publisher.upload_approved(
                "job-1",self.media,self.review,"Sleep short"
            )
        self.assertEqual(uncertain_service._videos.insert_calls,1)

        reconciled=self.uploads.reconcile(
            "job-1","uploaded","yt-video-recovered","Found matching private video in YouTube Studio"
        )
        self.assertEqual(reconciled["status"],"uploaded")
        self.assertEqual(reconciled["video_id"],"yt-video-recovered")

    def test_operator_confirms_no_remote_upload_before_retry_is_allowed(self):
        uncertain_publisher=YouTubePublisher(self.uploads,TimeoutService())
        with self.assertRaises(YouTubeUploadError):
            uncertain_publisher.upload_approved(
                "job-1",self.media,self.review,"Sleep short"
            )
        reconciled=self.uploads.reconcile(
            "job-1","not_uploaded",None,"Checked channel uploads; no matching private video",
            "reviewer-audit"
        )
        self.assertEqual(reconciled["status"],"failed")
        event=reconciled["events"][-1]
        self.assertEqual(event["operator_id"],"reviewer-audit")
        self.assertEqual(event["outcome"],"not_uploaded")
        self.assertTrue(event["created_at"])
        retried=YouTubePublisher(self.uploads,FakeService()).upload_approved(
            "job-1",self.media,self.review,"Sleep short"
        )
        self.assertEqual(retried["status"],"uploaded")

    def test_reconciliation_requires_a_note_and_rejects_conflicting_outcome(self):
        with self.assertRaises(YouTubeUploadError):
            self.uploads.reconcile("missing","uploaded","video-id","checked")
        active=self.uploads.begin("job-1","Sleep short","")
        with self.assertRaises(YouTubeUploadError):
            self.uploads.reconcile("job-1","uploaded","yt-video-1","checked too early")
        self.uploads.mark_reconciliation_required("job-1","Simulated stale upload",active["attempt_id"])
        with self.assertRaises(YouTubeUploadError):
            self.uploads.reconcile("job-1","uploaded",None,"checked")
        reconciled=self.uploads.reconcile(
            "job-1","uploaded","yt-video-1","Verified in YouTube Studio"
        )
        with self.assertRaises(YouTubeUploadError):
            self.uploads.reconcile(
                "job-1","not_uploaded",None,"conflicting operator decision"
            )
        self.assertEqual(reconciled["video_id"],"yt-video-1")
        event_id=reconciled["events"][-1]["id"]
        with self.assertRaises(sqlite3.IntegrityError):
            with self.uploads.db() as connection:
                connection.execute(
                    "UPDATE youtube_upload_events SET note='tampered' WHERE id=?",
                    (event_id,)
                )
        with self.assertRaises(sqlite3.IntegrityError):
            with self.uploads.db() as connection:
                connection.execute(
                    "DELETE FROM youtube_upload_events WHERE id=?",(event_id,)
                )

    def test_reconciliation_rejects_stale_attempt_identity_without_mutation(self):
        attempt = self.uploads.begin("job-1", "Sleep short", "")
        self.uploads.mark_reconciliation_required("job-1", "timeout", attempt["attempt_id"])
        with self.assertRaisesRegex(YouTubeUploadError, "attempt ID does not match"):
            self.uploads.reconcile(
                "job-1", "not_uploaded", note="Checked channel",
                expected_attempt_id="stale-attempt",
            )
        current = self.uploads.get("job-1")
        self.assertEqual(current["status"], "reconciliation_required")
        self.assertEqual(current["attempt_id"], attempt["attempt_id"])
        self.assertFalse(any(
            event["event_type"] == "operator_reconciliation"
            for event in current["events"]
        ))
        resolved = self.uploads.reconcile(
            "job-1", "not_uploaded", note="Verified no matching upload",
            expected_attempt_id=attempt["attempt_id"],
        )
        self.assertEqual(resolved["status"], "failed")
        self.assertEqual(resolved["events"][-1]["attempt_id"], attempt["attempt_id"])

    def test_active_upload_cannot_be_reconciled_early(self):
        self.uploads.begin("job-1","Sleep short","")
        with self.assertRaisesRegex(YouTubeUploadError,"active window"):
            self.uploads.reconcile(
                "job-1","not_uploaded",None,"Premature operator check"
            )

    def test_stale_upload_is_exposed_for_manual_reconciliation(self):
        previous=os.environ.get("NEXUS_UPLOAD_STALE_SECONDS")
        os.environ["NEXUS_UPLOAD_STALE_SECONDS"]="60"
        try:
            self.uploads.begin("job-1","Sleep short","")
            with self.uploads.db() as connection:
                connection.execute(
                    "UPDATE youtube_uploads SET updated_at=? WHERE job_id=?",
                    ("2020-01-01T00:00:00+00:00","job-1")
                )
            self.assertTrue(self.uploads.get("job-1")["reconciliation_required"])
            resolved=self.uploads.reconcile(
                "job-1","not_uploaded",None,"Verified no matching video in channel"
            )
            self.assertEqual(resolved["status"],"failed")
        finally:
            if previous is None:
                os.environ.pop("NEXUS_UPLOAD_STALE_SECONDS",None)
            else:
                os.environ["NEXUS_UPLOAD_STALE_SECONDS"]=previous

    def test_path_outside_media_root_rejected(self):
        outside=os.path.join(self.tmp.name,"..","outside.mp4")
        with self.assertRaises(YouTubeUploadError):
            self.publisher.upload_approved("job-1",outside,self.review,"Title")

    def test_unsupported_extension_rejected(self):
        bad=os.path.join(self.tmp.name,"payload.txt")
        Path(bad).write_text("not video")
        with self.assertRaises(YouTubeUploadError):
            self.publisher.upload_approved("job-1",bad,self.review,"Title")

    def test_missing_media_rejected(self):
        with self.assertRaises(YouTubeUploadError):
            self.publisher.upload_approved("job-1","/missing/video.mp4",
                                           self.review,"Title")


    def test_fail_is_fenced_to_active_attempt_and_audits_once(self):
        first=self.uploads.begin("job-1","First attempt","")
        self.assertTrue(self.uploads.touch_upload("job-1",first["attempt_id"]))
        self.uploads.fail("job-1","remote not started",first["attempt_id"])
        failed=self.uploads.get("job-1")
        self.assertEqual(failed["status"],"failed")
        failures=[event for event in failed["events"]
                  if event["event_type"]=="upload_preflight_failed"]
        self.assertEqual(len(failures),1)
        self.assertEqual(failures[0]["attempt_id"],first["attempt_id"])
        second=self.uploads.begin("job-1","Second attempt","")
        self.assertTrue(self.uploads.touch_upload("job-1",second["attempt_id"]))
        before=self.uploads.get("job-1")
        self.uploads.fail("job-1","late failure from old attempt",first["attempt_id"])
        after=self.uploads.get("job-1")
        self.assertEqual(after["attempt_id"],second["attempt_id"])
        self.assertEqual(after["status"],"uploading")
        self.assertEqual(after["events"],before["events"])

if __name__=="__main__":
    unittest.main()
