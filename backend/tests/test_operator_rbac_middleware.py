import json
import os
import unittest
from unittest import mock
from fastapi.testclient import TestClient

from app import app


class OperatorRbacMiddlewareTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app)
        self.credentials=json.dumps({
            "reviewer":"r"*48,
            "publisher":"p"*48,
            "unmapped":"u"*48,
        })

    def headers(self,token):
        return {"X-Review-Token":token}

    def test_reviewer_can_review_but_cannot_publish(self):
        roles=json.dumps({"reviewer":["reviewer"],"publisher":["publisher"]})
        with mock.patch.dict(os.environ,{
            "NEXUS_REVIEW_CREDENTIALS_JSON":self.credentials,
            "NEXUS_REVIEW_ROLE_MAP_JSON":roles,
            "NEXUS_REVIEW_TOKEN":"",
        },clear=False):
            read=self.client.get("/api/review/pending",headers=self.headers("r"*48))
            publish=self.client.post("/api/tiktok/publish/job-1",
                headers=self.headers("r"*48),json={})
        self.assertEqual(read.status_code,200)
        self.assertEqual(publish.status_code,403)

    def test_publisher_can_reach_publish_route_but_not_review_decisions(self):
        roles=json.dumps({"reviewer":["reviewer"],"publisher":["publisher"]})
        with mock.patch.dict(os.environ,{
            "NEXUS_REVIEW_CREDENTIALS_JSON":self.credentials,
            "NEXUS_REVIEW_ROLE_MAP_JSON":roles,
            "NEXUS_REVIEW_TOKEN":"",
        },clear=False):
            publish=self.client.post("/api/tiktok/publish/job-1",
                headers=self.headers("p"*48),json={})
            approve=self.client.post("/api/review/job-1/approve",
                headers=self.headers("p"*48),json={"reviewer_id":"spoofed","comment":"ok"})
        self.assertEqual(publish.status_code,422)
        self.assertEqual(approve.status_code,403)

    def test_unmapped_authenticated_operator_is_denied(self):
        roles=json.dumps({"reviewer":["reviewer"]})
        with mock.patch.dict(os.environ,{
            "NEXUS_REVIEW_CREDENTIALS_JSON":self.credentials,
            "NEXUS_REVIEW_ROLE_MAP_JSON":roles,
            "NEXUS_REVIEW_TOKEN":"",
        },clear=False):
            response=self.client.get("/api/review/pending",headers=self.headers("u"*48))
        self.assertEqual(response.status_code,403)

    def test_malformed_role_configuration_fails_closed(self):
        with mock.patch.dict(os.environ,{
            "NEXUS_REVIEW_CREDENTIALS_JSON":self.credentials,
            "NEXUS_REVIEW_ROLE_MAP_JSON":"not-json",
            "NEXUS_REVIEW_TOKEN":"",
        },clear=False):
            response=self.client.get("/api/review/pending",headers=self.headers("r"*48))
        self.assertEqual(response.status_code,503)

    def test_public_brand_catalog_and_oauth_callback_remain_public(self):
        with mock.patch.dict(os.environ,{
            "NEXUS_REVIEW_CREDENTIALS_JSON":self.credentials,
            "NEXUS_REVIEW_ROLE_MAP_JSON":json.dumps({"reviewer":["reviewer"]}),
            "NEXUS_REVIEW_TOKEN":"",
        },clear=False):
            brands=self.client.get("/api/brands")
            callback=self.client.get("/api/tiktok/oauth/callback")
        self.assertEqual(brands.status_code,200)
        self.assertNotEqual(callback.status_code,401)


if __name__=="__main__":
    unittest.main()
