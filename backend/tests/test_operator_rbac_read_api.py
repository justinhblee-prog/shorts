import json
import unittest
from unittest import mock
from fastapi import HTTPException

from app import queue_control, review_history, operational_health


class OperatorRbacReadApiTests(unittest.TestCase):
    def test_reviewer_can_read_review_history_but_not_queue_controls(self):
        roles = json.dumps({"alice": ["reviewer"]})
        with mock.patch("app.require_review_access", return_value="alice"), \
             mock.patch.dict("os.environ", {"NEXUS_REVIEW_ROLE_MAP_JSON": roles}, clear=False):
            with self.assertRaises(HTTPException) as caught:
                queue_control(x_review_token="token")
            self.assertEqual(caught.exception.status_code, 403)
            # The review read guard passes; the missing record is then handled normally.
            with self.assertRaises(HTTPException) as missing:
                review_history("missing-job", x_review_token="token")
            self.assertEqual(missing.exception.status_code, 404)

    def test_operator_can_read_operations_but_not_review_history(self):
        roles = json.dumps({"ops": ["operator"]})
        with mock.patch("app.require_review_access", return_value="ops"), \
             mock.patch.dict("os.environ", {"NEXUS_REVIEW_ROLE_MAP_JSON": roles}, clear=False), \
             mock.patch("app.queue.operational_health", return_value={"status": "ok"}):
            self.assertEqual(operational_health(x_review_token="token"), {"status": "ok"})
            with self.assertRaises(HTTPException) as caught:
                review_history("missing-job", x_review_token="token")
            self.assertEqual(caught.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
