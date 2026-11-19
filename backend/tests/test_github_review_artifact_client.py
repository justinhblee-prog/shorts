import json
import unittest
from unittest.mock import patch

from development_github_intake import _GitHubAPIOnlyRedirectHandler
from publish_development_reviews import GitHubReviewArtifactClient


class Response:
    def __init__(self, payload, link=""):
        self.payload = payload
        self.headers = {"Link": link}

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class GitHubReviewArtifactClientSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = GitHubReviewArtifactClient("test-token")

    def test_authenticated_get_uses_restricted_redirect_handler(self):
        with patch("publish_development_reviews.build_opener") as build_opener:
            build_opener.return_value.open.return_value = Response({"number": 42})
            result = self.client.get_pull_request("acme", "app", 42)
        self.assertEqual(result["number"], 42)
        handler = build_opener.call_args.args[0]
        self.assertIsInstance(handler, _GitHubAPIOnlyRedirectHandler)
        request = build_opener.return_value.open.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-token")

    def test_get_rejects_noncanonical_api_origins_before_network_access(self):
        for url in (
            "https://api.github.com.evil.example/repos/acme/app/pulls/42",
            "http://api.github.com/repos/acme/app/pulls/42",
            "https://user:password@api.github.com/repos/acme/app/pulls/42",
            "https://api.github.com:8443/repos/acme/app/pulls/42",
        ):
            with self.subTest(url=url):
                with patch("publish_development_reviews.build_opener") as build_opener:
                    with self.assertRaises(ValueError):
                        self.client._get(url)
                    build_opener.assert_not_called()

    def test_pull_request_file_pagination_reads_all_pages_on_same_endpoint(self):
        path = "/repos/acme/app/pulls/42/files"
        next_url = "https://api.github.com" + path + "?per_page=100&page=2"
        pages = [
            Response([{"filename": "backend/a.py"}], f'<{next_url}>; rel="next"'),
            Response([{"filename": "backend/b.py"}]),
        ]
        with patch("publish_development_reviews.build_opener") as build_opener:
            build_opener.return_value.open.side_effect = pages
            files = self.client.list_pull_request_files("acme", "app", 42)
        self.assertEqual([item["filename"] for item in files],
                         ["backend/a.py", "backend/b.py"])
        self.assertEqual(build_opener.return_value.open.call_count, 2)

    def test_pull_request_file_pagination_rejects_unsafe_next_url(self):
        response = Response(
            [{"filename": "backend/a.py"}],
            '<https://attacker.example/steal>; rel="next"',
        )
        with patch("publish_development_reviews.build_opener") as build_opener:
            build_opener.return_value.open.return_value = response
            with self.assertRaisesRegex(ValueError, "unsafe or unexpected"):
                self.client.list_pull_request_files("acme", "app", 42)
        self.assertEqual(build_opener.return_value.open.call_count, 1)

    def test_file_pagination_fails_closed_when_page_cap_is_exceeded(self):
        path = "/repos/acme/app/pulls/42/files"
        pages = []
        for page in range(1, self.client.MAX_PAGES + 1):
            next_url = f"https://api.github.com{path}?per_page=100&page={page + 1}"
            pages.append(Response([{"filename": f"backend/{page}.py"}],
                                  f'<{next_url}>; rel="next"'))
        with patch("publish_development_reviews.build_opener") as build_opener:
            build_opener.return_value.open.side_effect = pages
            with self.assertRaisesRegex(RuntimeError, "bounded page limit"):
                self.client.list_pull_request_files("acme", "app", 42)
        self.assertEqual(build_opener.return_value.open.call_count, self.client.MAX_PAGES)

    def test_open_pr_recovery_fails_closed_when_page_cap_is_exceeded(self):
        path = "/repos/acme/app/pulls"
        pages = []
        for page in range(1, self.client.MAX_PAGES + 1):
            next_url = f"https://api.github.com{path}?state=open&per_page=100&page={page + 1}"
            pages.append(Response([{"number": page}],
                                  f'<{next_url}>; rel="next"'))
        with patch("publish_development_reviews.build_opener") as build_opener:
            build_opener.return_value.open.side_effect = pages
            with self.assertRaisesRegex(RuntimeError, "bounded page limit"):
                self.client.list_open_pull_requests("acme", "app")
        self.assertEqual(build_opener.return_value.open.call_count, self.client.MAX_PAGES)


if __name__ == "__main__":
    unittest.main()
