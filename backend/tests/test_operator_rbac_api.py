import json
import unittest
from unittest import mock
from fastapi import HTTPException

import app as app_module
from app import (
    TikTokPublishRequest, require_review_permission, publish_tiktok_video,
)
from operator_rbac import OperatorRoleConfigurationError


class OperatorRbacApiTests(unittest.TestCase):
    def test_authenticated_reviewer_can_review_but_cannot_publish(self):
        credentials = json.dumps({"alice": "a" * 48})
        roles = json.dumps({"alice": ["reviewer"]})
        with mock.patch.dict("os.environ", {
            "NEXUS_REVIEW_CREDENTIALS_JSON": credentials,
            "NEXUS_REVIEW_ROLE_MAP_JSON": roles,
        }, clear=False):
            self.assertEqual(require_review_permission("a" * 48, "review.decide"), "alice")
            with self.assertRaises(HTTPException) as caught:
                require_review_permission("a" * 48, "publish.execute")
            self.assertEqual(caught.exception.status_code, 403)

    def test_publisher_can_publish_but_cannot_change_review_decisions(self):
        credentials = json.dumps({"bob": "b" * 48})
        roles = json.dumps({"bob": ["publisher"]})
        with mock.patch.dict("os.environ", {
            "NEXUS_REVIEW_CREDENTIALS_JSON": credentials,
            "NEXUS_REVIEW_ROLE_MAP_JSON": roles,
        }, clear=False):
            self.assertEqual(require_review_permission("b" * 48, "publish.execute"), "bob")
            with self.assertRaises(HTTPException) as caught:
                require_review_permission("b" * 48, "review.decide")
            self.assertEqual(caught.exception.status_code, 403)

    def test_api_publish_route_denies_authenticated_reviewer_before_media_access(self):
        body = TikTokPublishRequest(
            media_path="not-opened.mp4", title="Approved", operator_id="spoofed",
            privacy_level="SELF_ONLY", explicit_consent=True,
            brand_content_toggle=False, brand_organic_toggle=False,
        )
        with mock.patch("app.require_review_access", return_value="alice"), \
             mock.patch("app.has_permission", return_value=False), \
             mock.patch("app.require_canonical_staged_media") as media:
            with self.assertRaises(HTTPException) as caught:
                publish_tiktok_video("job-1", body, x_review_token="token")
        self.assertEqual(caught.exception.status_code, 403)
        media.assert_not_called()

    def test_malformed_role_map_fails_closed_with_service_unavailable(self):
        with mock.patch("app.require_review_access", return_value="alice"), \
             mock.patch("app.has_permission", side_effect=OperatorRoleConfigurationError("bad config")):
            with self.assertRaises(HTTPException) as caught:
                require_review_permission("token", "review.decide")
        self.assertEqual(caught.exception.status_code, 503)

    def test_unknown_authenticated_operator_is_forbidden_with_explicit_map(self):
        with mock.patch("app.require_review_access", return_value="unmapped"), \
             mock.patch.dict("os.environ", {
                 "NEXUS_REVIEW_ROLE_MAP_JSON": json.dumps({"alice": ["reviewer"]})
             }, clear=False):
            with self.assertRaises(HTTPException) as caught:
                require_review_permission("token", "review.read")
        self.assertEqual(caught.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
