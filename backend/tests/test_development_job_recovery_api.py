import unittest
from unittest import mock

from fastapi import HTTPException

import app as app_module
from app import DevelopmentJobRecoveryAction, recover_development_job


class DevelopmentJobRecoveryApiTests(unittest.TestCase):
    def setUp(self):
        self.body = DevelopmentJobRecoveryAction(
            reason="Reviewed the quarantine evidence and corrected the job scope"
        )

    def test_recovery_requires_operations_manage_and_records_authenticated_actor(self):
        recovered = {
            "id": "job-42",
            "title": "Recover me",
            "status": "ready",
            "attempts": 0,
            "lease_token": "must-not-leak",
            "worker_id": None,
        }
        with (
            mock.patch.object(
                app_module, "require_review_permission", return_value="operator-42"
            ) as authorize,
            mock.patch.object(
                app_module.development_job_store,
                "recover_quarantined",
                return_value=recovered,
            ) as recover,
        ):
            result = recover_development_job(
                "job-42", self.body, x_review_token="operator-token"
            )

        authorize.assert_called_once_with("operator-token", "operations.manage")
        recover.assert_called_once_with(
            "job-42", "operator-42", self.body.reason
        )
        self.assertEqual(result["job"]["status"], "ready")
        self.assertNotIn("lease_token", result["job"])

    def test_recovery_authorization_failure_never_mutates_store(self):
        with (
            mock.patch.object(
                app_module, "require_review_permission",
                side_effect=HTTPException(status_code=403, detail="Forbidden"),
            ) as authorize,
            mock.patch.object(
                app_module.development_job_store, "recover_quarantined"
            ) as recover,
        ):
            with self.assertRaises(HTTPException) as caught:
                recover_development_job(
                    "job-42", self.body, x_review_token="reviewer-token"
                )

        self.assertEqual(caught.exception.status_code, 403)
        authorize.assert_called_once_with("reviewer-token", "operations.manage")
        recover.assert_not_called()

    def test_recovery_maps_missing_job_to_not_found(self):
        with (
            mock.patch.object(app_module, "require_review_permission", return_value="ops"),
            mock.patch.object(
                app_module.development_job_store,
                "recover_quarantined",
                side_effect=app_module.DevelopmentJobNotFound("missing"),
            ),
        ):
            with self.assertRaises(HTTPException) as caught:
                recover_development_job("missing", self.body, x_review_token="token")
        self.assertEqual(caught.exception.status_code, 404)

    def test_recovery_maps_non_quarantined_conflict(self):
        with (
            mock.patch.object(app_module, "require_review_permission", return_value="ops"),
            mock.patch.object(
                app_module.development_job_store,
                "recover_quarantined",
                side_effect=app_module.DevelopmentJobConflict("only quarantined"),
            ),
        ):
            with self.assertRaises(HTTPException) as caught:
                recover_development_job("active", self.body, x_review_token="token")
        self.assertEqual(caught.exception.status_code, 409)

    def test_recovery_maps_invalid_reason_to_unprocessable_entity(self):
        with (
            mock.patch.object(app_module, "require_review_permission", return_value="ops"),
            mock.patch.object(
                app_module.development_job_store,
                "recover_quarantined",
                side_effect=ValueError("invalid reason"),
            ),
        ):
            with self.assertRaises(HTTPException) as caught:
                recover_development_job("job-42", self.body, x_review_token="token")
        self.assertEqual(caught.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
