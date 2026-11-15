import json
import unittest
from unittest import mock
from fastapi import HTTPException
import app as app_module
from app import (PolicyEvidenceInput, ReviewDecision, approve_review, reject_review,
                 update_review_policy_evidence, require_review_access)

class ReviewerIdentityApiTests(unittest.TestCase):
    def test_review_token_resolves_authenticated_identity_and_ignores_forged_body_identity(self):
        with mock.patch.dict("os.environ", {"NEXUS_REVIEW_CREDENTIALS_JSON": json.dumps({"alice": "a" * 48}), "NEXUS_REVIEW_TOKEN": "legacy-shared-token"}, clear=False):
            self.assertEqual(require_review_access("a" * 48), "alice")
            with self.assertRaises(HTTPException) as caught:
                require_review_access("legacy-shared-token")
            self.assertEqual(caught.exception.status_code, 401)

    def test_invalid_credentials_configuration_fails_closed(self):
        with mock.patch.dict("os.environ", {"NEXUS_REVIEW_CREDENTIALS_JSON": "not-json", "NEXUS_REVIEW_TOKEN": "legacy-shared-token"}, clear=False):
            with self.assertRaises(HTTPException) as caught:
                require_review_access("legacy-shared-token")
            self.assertEqual(caught.exception.status_code, 503)

    def test_approval_audit_uses_authenticated_reviewer_not_request_body(self):
        body = ReviewDecision(reviewer_id="forged-reviewer", comment="Reviewed")
        with mock.patch("app.require_review_access", return_value="alice"), \
             mock.patch.object(app_module.media_stager, "staged_path", return_value="approved.mp4"), \
             mock.patch.object(app_module.review_store, "decide", return_value={"decision": "approved"}) as decide:
            approve_review("job-1", body, x_review_token="alice-token")
        self.assertEqual(decide.call_args.args[2], "alice")

    def test_rejection_audit_uses_authenticated_reviewer_not_request_body(self):
        body = ReviewDecision(reviewer_id="forged-reviewer", comment="Incorrect claims")
        with mock.patch("app.require_review_access", return_value="alice"), \
             mock.patch.object(app_module.review_store, "decide", return_value={"decision": "rejected"}) as decide:
            reject_review("job-1", body, x_review_token="alice-token")
        self.assertEqual(decide.call_args.args[2], "alice")

    def test_policy_evidence_audit_uses_authenticated_reviewer_not_request_body(self):
        body = PolicyEvidenceInput(reviewer_id="forged-reviewer", rights={"visuals_cleared": True})
        with mock.patch("app.require_review_access", return_value="alice"), \
             mock.patch.object(app_module.review_store, "update_policy_evidence", return_value={"reviewer_id": "alice"}) as update:
            update_review_policy_evidence("job-1", body, x_review_token="alice-token")
        self.assertEqual(update.call_args.args[1], "alice")

if __name__ == "__main__":
    unittest.main()
