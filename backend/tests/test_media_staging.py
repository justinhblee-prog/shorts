import os
import tempfile
import unittest
from media_staging import MediaStager, MediaStagingError

class MediaStagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.payload = b"0000ftypisom" + b"x" * 64
        self.calls = []
        def fetcher(host, ip, path, timeout):
            self.calls.append((host, ip, path))
            return 200, {"content-type":"video/mp4","content-length":str(len(self.payload))}, [self.payload[:20],self.payload[20:]]
        self.stager = MediaStager(self.tmp.name, "cdn.example.test",
            1024, resolver=lambda host:["8.8.8.8"], fetcher=fetcher)
    def tearDown(self):
        self.tmp.cleanup()
    def test_downloads_allowlisted_mp4_to_staging(self):
        result = self.stager.stage("job-1","https://cdn.example.test/path/video.mp4?sig=abc")
        self.assertTrue(os.path.isfile(os.path.join(self.tmp.name,result["media_path"])))
        self.assertEqual(result["size_bytes"],len(self.payload))
        self.assertEqual(self.calls[0][2],"/path/video.mp4?sig=abc")
    def test_rejects_non_allowlisted_host_before_network(self):
        with self.assertRaises(MediaStagingError):
            self.stager.stage("job-1","https://evil.example/video.mp4")
        self.assertEqual(self.calls,[])
    def test_rejects_private_dns_resolution(self):
        self.stager.resolver=lambda host:["127.0.0.1"]
        with self.assertRaises(MediaStagingError):
            self.stager.stage("job-1","https://cdn.example.test/video.mp4")
    def test_rejects_redirects(self):
        self.stager.fetcher=lambda *args:(302,{"location":"https://evil.test/x"},[])
        with self.assertRaises(MediaStagingError):
            self.stager.stage("job-1","https://cdn.example.test/video.mp4")
    def test_rejects_oversize_and_bad_signature(self):
        self.stager.max_bytes=8
        with self.assertRaises(MediaStagingError):
            self.stager.stage("job-1","https://cdn.example.test/video.mp4")
        self.stager.max_bytes=1024
        self.stager.fetcher=lambda *args:(200,{"content-type":"video/mp4"},[b"not-a-video-file"])
        with self.assertRaises(MediaStagingError):
            self.stager.stage("job-2","https://cdn.example.test/video.mp4")
    def test_cleanup_requires_confirmed_upload_and_is_idempotent(self):
        staged = self.stager.stage("job-clean", "https://cdn.example.test/video.mp4")
        class UploadStore:
            def __init__(self, status): self.status = status
            def get(self, job_id):
                return {"status": self.status, "video_id": "yt-123" if self.status == "uploaded" else None}
        with self.assertRaises(MediaStagingError):
            self.stager.cleanup_uploaded("job-clean", UploadStore("reconciliation_required"))
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, staged["media_path"])))
        result = self.stager.cleanup_uploaded("job-clean", UploadStore("uploaded"))
        self.assertTrue(result["removed"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, staged["media_path"])))
        self.assertTrue(self.stager.cleanup_uploaded("job-clean", UploadStore("uploaded"))["removed"])

    def test_prunes_only_old_temporary_parts(self):
        old_part = os.path.join(self.tmp.name, ".nexus-old.part")
        normal_file = os.path.join(self.tmp.name, "keep.mp4")
        with open(old_part, "wb") as f: f.write(b"x")
        with open(normal_file, "wb") as f: f.write(b"x")
        os.utime(old_part, (1, 1))
        result = self.stager.prune_temporary_files(older_than_seconds=3600, now=10000)
        self.assertEqual(result["count"], 1)
        self.assertFalse(os.path.exists(old_part))
        self.assertTrue(os.path.exists(normal_file))
        with self.assertRaises(ValueError):
            self.stager.prune_temporary_files(older_than_seconds=60)

    def test_rejects_http_and_embedded_credentials(self):
        for url in ("http://cdn.example.test/a.mp4","https://user:pass@cdn.example.test/a.mp4"):
            with self.assertRaises(MediaStagingError):
                self.stager.stage("job-1",url)

if __name__ == "__main__":
    unittest.main()
