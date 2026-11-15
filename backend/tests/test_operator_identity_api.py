import unittest
from unittest import mock
import app as app_module
from app import (
    QueueControlAction, YouTubeUploadReconciliation, YouTubeLateSuccessResolution,
    TikTokPublishRequest, TikTokPublicationReconciliation,
    RecommendationExperimentCreate, RecommendationSkipFeedback,
    reconcile_youtube_upload, resolve_late_youtube_upload, publish_tiktok_video,
    reconcile_tiktok_publication, create_recommendation_experiment,
    skip_recommendation_feedback, pause_queue, resume_queue,
)

class AuthenticatedOperatorAuditTests(unittest.TestCase):
    def setUp(self):
        self.auth = mock.patch("app.require_review_access", return_value="verified-operator")
        self.auth.start()
        self.addCleanup(self.auth.stop)

    def test_youtube_reconciliation_uses_authenticated_operator(self):
        body = YouTubeUploadReconciliation(outcome="not_uploaded", confirmed=True, note="Checked remote channel", operator_id="forged-user")
        with mock.patch.object(app_module.youtube_upload_store, "reconcile", return_value={"status": "reconciled"}) as reconcile:
            reconcile_youtube_upload("job-1", body, x_review_token="token")
        self.assertEqual(reconcile.call_args.args[4], "verified-operator")

    def test_youtube_late_success_resolution_uses_authenticated_operator(self):
        body = YouTubeLateSuccessResolution(operator_id="forged-user", video_id="video-1", note="Verified upload")
        with mock.patch.object(app_module.youtube_upload_store, "resolve_late_success", return_value={"status": "resolved"}) as resolve:
            resolve_late_youtube_upload("job-1", body, x_review_token="token")
        self.assertEqual(resolve.call_args.args[1], "verified-operator")

    def test_tiktok_publish_uses_authenticated_operator(self):
        body = TikTokPublishRequest(media_path="job-1.mp4", title="Approved", operator_id="forged-user", privacy_level="SELF_ONLY", explicit_consent=True, brand_content_toggle=False, brand_organic_toggle=False)
        with mock.patch("app.require_canonical_staged_media", return_value="/media/job-1.mp4"), \
             mock.patch.object(app_module.tiktok_publisher, "publish_private_approved", return_value={"status": "created"}) as publish:
            publish_tiktok_video("job-1", body, x_review_token="token")
        self.assertEqual(publish.call_args.args[4], "verified-operator")

    def test_tiktok_reconciliation_uses_authenticated_operator(self):
        body = TikTokPublicationReconciliation(outcome="not_published", confirmed=True, note="Checked creator account", operator_id="forged-user")
        with mock.patch.object(app_module.tiktok_publish_store, "reconcile", return_value={"status": "reconciled"}) as reconcile:
            reconcile_tiktok_publication("job-1", body, x_review_token="token")
        self.assertEqual(reconcile.call_args.args[2], "verified-operator")

    def test_recommendation_experiment_audit_uses_authenticated_operator(self):
        body = RecommendationExperimentCreate(name="Test", operator_id="forged-user", control_label="control", treatment_label="treatment", treatment_allocation_basis_points=5000)
        with mock.patch.object(app_module.recommendation_evaluation_store, "create_experiment", return_value={"id": "exp-1"}) as create:
            create_recommendation_experiment(body, x_review_token="token")
        self.assertEqual(create.call_args.args[1], "verified-operator")

    def test_recommendation_skip_feedback_uses_authenticated_reviewer(self):
        body = RecommendationSkipFeedback(trend_id="trend-1", brand_slug="brain-glitch", recommendation_candidate_id="candidate-1", reviewer_id="forged-user", reason="Not relevant")
        with mock.patch.object(app_module.recommendation_evaluation_store, "record_skip", return_value={"recorded": True}) as record:
            skip_recommendation_feedback(body, x_review_token="token")
        self.assertEqual(record.call_args.args[2], "verified-operator")

    def test_queue_pause_audit_uses_authenticated_operator(self):
        body = QueueControlAction(operator_id="forged-user", note="Investigated queue failure")
        with mock.patch.object(app_module.queue, "pause", return_value={"paused": True}) as pause, \
             mock.patch.object(app_module.queue, "worker_control", return_value={}), \
             mock.patch.object(app_module.queue, "worker_control_events", return_value=[]):
            pause_queue(body, x_review_token="token")
        self.assertEqual(pause.call_args.kwargs["actor"], "verified-operator")

    def test_queue_resume_audit_uses_authenticated_operator(self):
        body = QueueControlAction(operator_id="forged-user", note="Recovery verified", recovery_confirmed=True)
        with mock.patch.object(app_module.queue, "operational_health", return_value={"blockers": []}), \
             mock.patch.object(app_module.queue, "resume", return_value={"paused": False}) as resume, \
             mock.patch.object(app_module.queue, "worker_control", return_value={}), \
             mock.patch.object(app_module.queue, "worker_control_events", return_value=[]):
            resume_queue(body, x_review_token="token")
        self.assertEqual(resume.call_args.kwargs["actor"], "verified-operator")

if __name__ == "__main__":
    unittest.main()
