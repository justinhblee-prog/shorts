import io
import tempfile
import unittest
import urllib.error
import time
from threading import Event, Thread
from unittest.mock import patch
from pathlib import Path

from production_pipeline import (
    JsonProvider, ProductionPipeline, ProductionStore, ProductionLeaseConflict, ProviderAttemptConflict, ProviderError,
    submit_production,
)
from queue_store import JobQueue


class FakeProvider:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, stage, payload):
        self.calls.append((stage, payload))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakeQueue:
    def __init__(self):
        self.job = None

    def enqueue(self, job_type, payload, channel_name=None, idempotency_key=None):
        if self.job is None:
            self.job = {"id": "job-1", "job_type": job_type, "payload": payload,
                        "channel_name": channel_name, "status": "queued"}
        return self.job


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ProductionStore(str(Path(self.tmp.name) / "test.sqlite3"))
        self.brief = {"brand": "Future Leak", "region": "US",
                      "language": "en", "topic": "AI agents"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_uses_one_timestamp_after_acquiring_write_lock(self):
        decision = "2036-07-08T09:10:11+00:00"
        clock_called = Event()
        started = Event()
        outcome = {}

        def controlled_now():
            clock_called.set()
            return decision

        def create():
            started.set()
            try:
                self.store.create("job-create-lock-time", self.brief)
            except Exception as exc:
                outcome["error"] = exc

        with self.store.db() as holder:
            holder.execute("BEGIN IMMEDIATE")
            with patch("production_pipeline.utc_now", side_effect=controlled_now):
                thread = Thread(target=create)
                thread.start()
                self.assertTrue(started.wait(1))
                time.sleep(0.1)
                self.assertFalse(
                    clock_called.is_set(),
                    "production creation must not sample its timestamp while waiting for the write lock",
                )
                holder.commit()
                thread.join(2)
            self.assertFalse(thread.is_alive(), "production creation did not finish after lock release")

        self.assertNotIn("error", outcome)
        run = self.store.get("job-create-lock-time")
        self.assertEqual(run["created_at"], decision)
        self.assertEqual(run["updated_at"], decision)

    def test_submit_is_durable_and_does_not_call_providers(self):
        queue = FakeQueue()
        result = submit_production(queue, self.store, self.brief)
        self.assertEqual(result["job"]["status"], "queued")
        self.assertEqual(result["production"]["status"], "queued")
        self.assertEqual(result["production"]["artifacts"], [])

    def test_submit_includes_policy_report_and_blocks_explicit_flags(self):
        queue = FakeQueue()
        result = submit_production(queue, self.store, self.brief)
        self.assertEqual(result["job"]["payload"]["policy_report"]["status"], "review_required")
        blocked = {**self.brief, "policy_flags": {"known_unauthorized_assets": True}}
        with self.assertRaisesRegex(ValueError, "blocked by policy preflight"):
            submit_production(FakeQueue(), self.store, blocked)

    def test_pipeline_blocks_explicit_policy_flags_before_provider_calls(self):
        script = FakeProvider({"script": "must not run"})
        pipeline = ProductionPipeline(self.store, script,
            FakeProvider({"audio_url": "https://media.example/audio.mp3"}),
            FakeProvider({"video_url": "https://media.example/video.mp4"}))
        brief = {**self.brief, "policy_flags": {"deceptive_impersonation": True}}
        self.store.create("job-blocked", brief)
        with self.assertRaises(ProviderError) as caught:
            pipeline.execute("job-blocked", brief)
        self.assertEqual(caught.exception.stage, "policy_preflight")
        self.assertEqual(self.store.get("job-blocked")["status"], "failed_terminal")
        self.assertEqual(script.calls, [])

    def test_policy_report_is_passed_to_script_and_saved_for_review(self):
        script = FakeProvider({"script": "Original, sourced explanation."})
        voice = FakeProvider({"audio_url": "https://media.example/audio.mp3"})
        render = FakeProvider({"video_url": "https://media.example/video.mp4"})
        brief = {**self.brief,
            "rights": {"visuals_cleared": True, "audio_cleared": True, "likeness_authorized": True},
            "synthetic_media_status": "ai_generated",
            "platform_disclosures": {
                "youtube_altered_content": True,
                "tiktok_ai_generated_content": True,
            },
            "factual_claims_verified": True, "originality_notes": "Distinct narrative."}
        self.store.create("job-policy", brief)
        result = ProductionPipeline(self.store, script, voice, render).execute("job-policy", brief)
        report = result["artifacts"][0]["metadata"]["policy_preflight"]
        self.assertEqual(report["status"], "ready_for_human_review")
        self.assertEqual(script.calls[0][1]["policy_preflight"]["status"], "ready_for_human_review")
        self.assertIn("Never claim this content is policy-approved",
                      script.calls[0][1]["platform_compliance_instructions"])
    def test_pipeline_runs_script_voice_render_and_waits_for_review(self):
        script = FakeProvider({"script": "Hook. Evidence. Takeaway."})
        voice = FakeProvider({"audio_url": "https://media.example/audio.mp3", "voice": "en-US"})
        render = FakeProvider({"video_url": "https://media.example/video.mp4", "duration_seconds": 28})
        pipeline = ProductionPipeline(self.store, script, voice, render)
        self.store.create("job-1", self.brief)
        result = pipeline.execute("job-1", self.brief)
        self.assertEqual(result["status"], "rendered")
        self.assertEqual([a["stage"] for a in result["artifacts"]],
                         ["script", "originality_check", "voice_generation", "rendering", "quality_check"])
        quality = result["artifacts"][-1]["metadata"]
        self.assertEqual(quality["status"], "review_required")
        self.assertFalse(quality["automatic_publication"])
        self.assertIsNone(result["artifacts"][0]["artifact_url"])
        self.assertEqual(len(script.calls), 1)
        self.assertEqual(len(voice.calls), 1)
        self.assertEqual(len(render.calls), 1)
        self.assertTrue(script.calls[0][1]["request_idempotency_key"])
        self.assertTrue(voice.calls[0][1]["request_idempotency_key"])
        self.assertTrue(render.calls[0][1]["request_idempotency_key"])
        attempts=self.store.provider_attempts("job-1")
        self.assertEqual([item["stage"] for item in attempts],
                         ["script","voice_generation","rendering"])
        self.assertTrue(all(item["state"]=="adopted" for item in attempts))
        self.assertTrue(all(item["response_json"] for item in attempts))

    def test_pipeline_transcribes_generated_audio_and_records_script_alignment(self):
        script_text = (
            "The human brain predicts what happens next using patterns from previous "
            "experiences. When expectations are violated, attention increases and the "
            "brain updates its model of the world."
        )
        script = FakeProvider({"script": script_text, "factual_claims_verified": True})
        voice = FakeProvider({"audio_url": "https://media.example/audio.mp3",
                              "duration_seconds": 30})
        transcription = FakeProvider({
            "transcript": script_text,
            "provider": "test-asr",
        })
        render = FakeProvider({"video_url": "https://media.example/video.mp4",
                               "duration_seconds": 30, "aspect_ratio": "9:16",
                               "audio_track_present": True, "subtitles_enabled": True})
        pipeline = ProductionPipeline(
            self.store, script, voice, render, transcription_provider=transcription
        )
        self.store.create("job-asr", self.brief)
        result = pipeline.execute("job-asr", self.brief)
        speech = next(item for item in result["artifacts"]
                      if item["stage"] == "speech_alignment")
        quality = next(item for item in result["artifacts"]
                       if item["stage"] == "quality_check")
        self.assertEqual(speech["metadata"]["status"], "aligned")
        self.assertEqual(speech["metadata"]["provider"], "test-asr")
        self.assertEqual(speech["metadata"]["word_error_rate"], 0)
        self.assertEqual(quality["metadata"]["speech_alignment"]["status"], "aligned")
        self.assertNotIn("speech_transcription_not_configured",
                         quality["metadata"]["warnings"])
        self.assertEqual(len(transcription.calls), 1)
        self.assertEqual(transcription.calls[0][1]["audio_url"],
                         "https://media.example/audio.mp3")
        self.assertIn("Do not correct", transcription.calls[0][1]["instructions"])

    def test_pipeline_flags_audio_script_mismatch_for_human_review(self):
        script_text = (
            "The human brain predicts what happens next using patterns from previous "
            "experiences. When expectations are violated, attention increases and the "
            "brain updates its model of the world."
        )
        script = FakeProvider({"script": script_text, "factual_claims_verified": True})
        voice = FakeProvider({"audio_url": "https://media.example/audio.mp3",
                              "duration_seconds": 30})
        transcription = FakeProvider({
            "transcript": (
                "Ocean researchers explore deep water habitats using specialized robotic "
                "vehicles to observe unusual species around underwater volcanic vents."
            ),
            "provider": "test-asr",
        })
        render = FakeProvider({"video_url": "https://media.example/video.mp4",
                               "duration_seconds": 30, "aspect_ratio": "9:16",
                               "audio_track_present": True, "subtitles_enabled": True})
        pipeline = ProductionPipeline(
            self.store, script, voice, render, transcription_provider=transcription
        )
        self.store.create("job-asr-mismatch", self.brief)
        result = pipeline.execute("job-asr-mismatch", self.brief)
        quality = next(item for item in result["artifacts"]
                       if item["stage"] == "quality_check")
        self.assertIn("spoken_audio_differs_from_generated_script",
                      quality["metadata"]["warnings"])
        self.assertEqual(quality["metadata"]["speech_alignment"]["status"],
                         "material_mismatch")
        self.assertEqual(result["status"], "rendered")

    def test_pipeline_extracts_and_aligns_text_subtitles_before_review(self):
        class FakeStager:
            def __init__(self, folder):
                self.media_dir = Path(folder)
            def stage(self, job_id, url):
                path = self.media_dir / "caption-fixture.mp4"
                path.write_bytes(b"fixture")
                return {"media_path": path.name, "size_bytes": 7}
        script_text = (
            "The human brain predicts what happens next using patterns from previous "
            "experiences. When expectations are violated, attention increases and the "
            "brain updates its model of the world."
        )
        class FakeInspector:
            def inspect(self, path):
                return {
                    "status": "inspected", "inspection_method": "ffprobe_file_bytes",
                    "duration_seconds": 30, "width": 1080, "height": 1920,
                    "audio_track_present": True, "video_codec": "h264",
                    "audio_codec": "aac", "subtitle_stream_present": True,
                    "subtitle_extraction": {"status": "extracted"},
                    "subtitle_text": (
                        "1\n00:00:00,000 --> 00:00:05,000\n"
                        + script_text + "\n"
                    ),
                }
        pipeline = ProductionPipeline(
            self.store,
            FakeProvider({"script": script_text, "factual_claims_verified": True}),
            FakeProvider({"audio_url": "https://media.example/audio.mp3",
                          "duration_seconds": 30}),
            FakeProvider({"video_url": "https://media.example/video.mp4",
                          "duration_seconds": 30, "aspect_ratio": "9:16",
                          "audio_track_present": True, "subtitles_enabled": True}),
            media_stager=FakeStager(self.tmp.name),
            media_inspector=FakeInspector(),
        )
        self.store.create("job-captions", self.brief)
        result = pipeline.execute("job-captions", self.brief)
        caption = next(item for item in result["artifacts"]
                       if item["stage"] == "caption_alignment")
        quality = next(item for item in result["artifacts"]
                       if item["stage"] == "quality_check")
        self.assertEqual(caption["metadata"]["status"], "aligned")
        self.assertEqual(caption["metadata"]["reference"], "generated_script")
        self.assertEqual(quality["metadata"]["caption_alignment"]["status"], "aligned")
        self.assertNotIn("subtitle_text",
                         quality["metadata"]["media_inspection"])

    def test_pipeline_flags_similar_script_from_another_brand_for_review(self):
        previous_script = (
            "The human brain predicts what happens next using patterns from previous "
            "experiences. When expectations are violated, attention increases and the "
            "brain updates its model of the world. This process helps people learn, "
            "adapt, and make decisions under uncertainty."
        )
        self.store.create("prior-job", {
            "brand": "Brain Glitch", "region": "US", "language": "en",
            "topic": "Brain prediction",
        })
        self.store.stage("prior-job", "rendered", "rendered")
        self.store.artifact("prior-job", "script", "text", None,
                            {"script": previous_script})
        script = FakeProvider({"script": previous_script,
                               "factual_claims_verified": True})
        voice = FakeProvider({"audio_url": "https://media.example/audio.mp3",
                              "duration_seconds": 30})
        render = FakeProvider({"video_url": "https://media.example/video.mp4",
                               "duration_seconds": 30, "aspect_ratio": "9:16",
                               "audio_track_present": True, "subtitles_enabled": True})
        pipeline = ProductionPipeline(self.store, script, voice, render)
        self.store.create("job-current", self.brief)
        result = pipeline.execute("job-current", self.brief)
        originality = next(a["metadata"] for a in result["artifacts"]
                           if a["stage"] == "originality_check")
        quality = next(a["metadata"] for a in result["artifacts"]
                       if a["stage"] == "quality_check")
        self.assertEqual(originality["status"], "similar_content_found")
        self.assertEqual(originality["similar_matches"][0]["brand"], "Brain Glitch")
        self.assertIn("script_similarity_to_prior_production_above_threshold",
                      quality["warnings"])

    def test_pipeline_blocks_explicitly_nonvertical_render_before_review(self):
        script = FakeProvider({"script": "This script has enough words to explain the topic clearly and give viewers a useful takeaway."})
        voice = FakeProvider({"audio_url": "https://media.example/audio.mp3", "duration_seconds": 30})
        render = FakeProvider({"video_url": "https://media.example/video.mp4",
                               "duration_seconds": 30, "aspect_ratio": "16:9",
                               "audio_track_present": True})
        pipeline = ProductionPipeline(self.store, script, voice, render)
        self.store.create("job-bad-format", self.brief)
        with self.assertRaisesRegex(ProviderError, "quality gate blocked"):
            pipeline.execute("job-bad-format", self.brief)
        result = self.store.get("job-bad-format")
        self.assertEqual(result["status"], "failed_terminal")
        quality = next(item for item in result["artifacts"]
                       if item["stage"] == "quality_check")
        self.assertEqual(quality["metadata"]["status"], "blocked")
        self.assertIn("render_format_is_not_vertical_9_16",
                      quality["metadata"]["blockers"])

    def test_pipeline_records_provider_attested_quality_before_human_review(self):
        script = FakeProvider({
            "script": "A clear opening explains the problem. Evidence supports the claim. "
                      "The ending gives viewers a useful next step with a concise summary.",
            "factual_claims_verified": True,
        })
        voice = FakeProvider({"audio_url": "https://media.example/audio.mp3",
                              "duration_seconds": 30})
        render = FakeProvider({"video_url": "https://media.example/video.mp4",
                               "duration_seconds": 30, "aspect_ratio": "9:16",
                               "audio_track_present": True, "subtitles_enabled": True})
        pipeline = ProductionPipeline(self.store, script, voice, render)
        self.store.create("job-quality-ready", self.brief)
        result = pipeline.execute("job-quality-ready", self.brief)
        quality = next(item for item in result["artifacts"]
                       if item["stage"] == "quality_check")
        self.assertEqual(quality["metadata"]["status"], "review_required")
        self.assertIn("actual_media_bytes_not_inspected", quality["metadata"]["warnings"])
        self.assertEqual(result["status"], "rendered")

    def test_pipeline_inspects_actual_staged_media_before_review_handoff(self):
        class FakeStager:
            def __init__(self, folder):
                self.media_dir = Path(folder)
            def stage(self, job_id, url):
                path = self.media_dir / "staged.mp4"
                path.write_bytes(b"verified fixture")
                return {"media_path": "staged.mp4", "size_bytes": 15}
        class FakeInspector:
            def inspect(self, path):
                self.assert_exists = Path(path).is_file()
                return {
                    "status": "inspected", "inspection_method": "ffprobe_file_bytes",
                    "duration_seconds": 30, "width": 1080, "height": 1920,
                    "aspect_ratio": 0.5625, "audio_track_present": True,
                    "video_codec": "h264", "audio_codec": "aac",
                    "subtitle_stream_present": True,
                    "subtitle_note": "Subtitle stream detected.",
                }
        script = FakeProvider({
            "script": "A clear opening explains the problem. Evidence supports the claim. "
                      "The ending gives viewers a useful next step with a concise summary.",
            "factual_claims_verified": True,
        })
        voice = FakeProvider({"audio_url": "https://media.example/audio.mp3",
                              "duration_seconds": 30})
        render = FakeProvider({"video_url": "https://media.example/video.mp4",
                               "duration_seconds": 30, "aspect_ratio": "9:16",
                               "audio_track_present": True, "subtitles_enabled": True})
        pipeline = ProductionPipeline(
            self.store, script, voice, render,
            media_stager=FakeStager(self.tmp.name), media_inspector=FakeInspector(),
        )
        self.store.create("job-byte-inspected", self.brief)
        result = pipeline.execute("job-byte-inspected", self.brief)
        quality = next(a["metadata"] for a in result["artifacts"]
                       if a["stage"] == "quality_check")
        self.assertEqual(quality["status"], "review_required")
        self.assertIn("speech_transcription_not_configured", quality["warnings"])
        self.assertNotIn("actual_media_bytes_not_inspected", quality["warnings"])
        self.assertEqual(quality["media_inspection"]["inspection_method"],
                         "ffprobe_file_bytes")
        self.assertTrue(quality["checks"][-1]["status"] == "inspected")
        video = next(a for a in result["artifacts"] if a["stage"] == "rendering")
        self.assertEqual(video["metadata"]["media_staging"]["media_path"], "staged.mp4")

    def test_pipeline_blocks_actual_nonvertical_or_silent_media_even_if_provider_claims_good(self):
        class FakeStager:
            def __init__(self, folder):
                self.media_dir = Path(folder)
            def stage(self, job_id, url):
                path = self.media_dir / "bad.mp4"
                path.write_bytes(b"untrusted fixture")
                return {"media_path": "bad.mp4", "size_bytes": 16}
        class FakeInspector:
            def inspect(self, path):
                return {
                    "status": "inspected", "inspection_method": "ffprobe_file_bytes",
                    "duration_seconds": 30, "width": 1920, "height": 1080,
                    "aspect_ratio": 1.77778, "audio_track_present": False,
                    "video_codec": "h264", "audio_codec": None,
                    "subtitle_stream_present": False,
                }
        script = FakeProvider({"script": "A clear opening explains the problem and gives viewers a useful takeaway."})
        voice = FakeProvider({"audio_url": "https://media.example/audio.mp3",
                              "duration_seconds": 30})
        render = FakeProvider({"video_url": "https://media.example/video.mp4",
                               "duration_seconds": 30, "aspect_ratio": "9:16",
                               "audio_track_present": True, "subtitles_enabled": True})
        pipeline = ProductionPipeline(
            self.store, script, voice, render,
            media_stager=FakeStager(self.tmp.name), media_inspector=FakeInspector(),
        )
        self.store.create("job-actual-bad-media", self.brief)
        with self.assertRaisesRegex(ProviderError, "quality gate blocked"):
            pipeline.execute("job-actual-bad-media", self.brief)
        result = self.store.get("job-actual-bad-media")
        quality = next(a["metadata"] for a in result["artifacts"]
                       if a["stage"] == "quality_check")
        self.assertEqual(quality["status"], "blocked")
        self.assertIn("actual_media_dimensions_are_not_vertical_9_16",
                      quality["blockers"])
        self.assertIn("actual_media_contains_no_audio_track", quality["blockers"])

    def test_brand_profile_is_applied_to_script_voice_and_render_provider_payloads(self):
        profile = {
            "positioning": "Evidence-led AI explainers",
            "audience": "technology-curious adults",
            "tone": ["clear", "grounded"],
            "risk_level": "elevated",
            "review_rules": ["Distinguish demos from shipped capabilities"],
        }
        brief = {**self.brief, "brand_profile": profile}
        script = FakeProvider({"script": "Hook. Evidence. Takeaway."})
        voice = FakeProvider({"audio_url": "https://media.example/audio.mp3"})
        render = FakeProvider({"video_url": "https://media.example/video.mp4"})
        pipeline = ProductionPipeline(self.store, script, voice, render)
        self.store.create("job-brand-profile", brief)

        pipeline.execute("job-brand-profile", brief)

        script_payload = script.calls[0][1]
        voice_payload = voice.calls[0][1]
        render_payload = render.calls[0][1]
        self.assertEqual(script_payload["brand_profile"], profile)
        self.assertEqual(script_payload["editorial_constraints"], profile["review_rules"])
        self.assertEqual(voice_payload["voice_tone"], profile["tone"])
        self.assertEqual(voice_payload["target_audience"], profile["audience"])
        self.assertEqual(render_payload["brand_profile"], profile)

    def test_trend_context_is_validated_and_passed_as_untrusted_source_material(self):
        trend = {
            "source": "google_news_rss", "title": "AI agent adoption grows",
            "url": "https://news.example/story", "summary": "A report describes adoption.",
            "published_at": "2026-11-15T00:00:00+00:00", "region": "US",
        }
        brief = {**self.brief, "trend_context": trend}
        script = FakeProvider({"script": "Hook. Evidence. Takeaway."})
        voice = FakeProvider({"audio_url": "https://media.example/audio.mp3"})
        render = FakeProvider({"video_url": "https://media.example/video.mp4"})
        pipeline = ProductionPipeline(self.store, script, voice, render)
        self.store.create("job-trend", brief)
        pipeline.execute("job-trend", brief)
        payload = script.calls[0][1]
        self.assertEqual(payload["trend_context"], trend)
        self.assertIn("untrusted source material", payload["trend_context_handling"])
        self.assertIn("do not invent facts", payload["trend_context_handling"])

    def test_invalid_trend_context_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "HTTP"):
            ProductionPipeline.validate_brief({
                **self.brief, "trend_context": {
                    "title": "A title", "url": "javascript:alert(1)"
                }
            })
        with self.assertRaisesRegex(ValueError, "source URL"):
            ProductionPipeline.validate_brief({
                **self.brief, "trend_context": {"title": "A title", "url": ""}
            })

    def test_invalid_brand_profile_fails_before_provider_calls(self):
        script = FakeProvider({"script": "must not run"})
        voice = FakeProvider({"audio_url": "https://media.example/audio.mp3"})
        render = FakeProvider({"video_url": "https://media.example/video.mp4"})
        pipeline = ProductionPipeline(self.store, script, voice, render)
        with self.assertRaisesRegex(ValueError, "brand_profile.risk_level"):
            pipeline.validate_brief({**self.brief, "brand_profile": {"risk_level": "unknown"}})
        self.assertEqual(script.calls, [])
        self.assertEqual(voice.calls, [])
        self.assertEqual(render.calls, [])

    def test_retry_start_clears_stale_downstream_artifacts(self):
        self.store.create("job-1", self.brief)
        first = ProductionPipeline(
            self.store,
            FakeProvider({"script": "Old script"}),
            FakeProvider({"audio_url": "https://media.example/old.mp3"}),
            FakeProvider({"video_url": "https://media.example/old.mp4"}),
        )
        first.execute("job-1", self.brief)
        self.assertEqual(len(self.store.get("job-1")["artifacts"]), 5)

        retry = ProductionPipeline(
            self.store,
            FakeProvider(ProviderError("script", "Temporary script failure", True)),
            FakeProvider({"audio_url": "https://media.example/unused.mp3"}),
            FakeProvider({"video_url": "https://media.example/unused.mp4"}),
        )
        with self.assertRaises(ProviderError):
            retry.execute("job-1", self.brief)
        result = self.store.get("job-1")
        self.assertEqual(result["status"], "failed_retriable")
        self.assertEqual(result["artifacts"], [])

    def test_missing_audio_url_fails_without_fake_video(self):
        script = FakeProvider({"script": "Real script"})
        voice = FakeProvider({"status": "ok"})
        render = FakeProvider({"video_url": "https://media.example/never.mp4"})
        pipeline = ProductionPipeline(self.store, script, voice, render)
        self.store.create("job-1", self.brief)
        with self.assertRaises(ProviderError) as caught:
            pipeline.execute("job-1", self.brief)
        self.assertEqual(caught.exception.stage, "voice_generation")
        result = self.store.get("job-1")
        self.assertEqual(result["status"], "failed_terminal")
        self.assertEqual(len(result["artifacts"]), 2)
        self.assertEqual(render.calls, [])

    def test_json_provider_http_error_body_is_not_in_exception(self):
        secret_body = b'{"error":"Bearer provider-body-secret","access_token":"body-token"}'
        error = urllib.error.HTTPError(
            "https://provider.example/generate", 500, "Server Error", {},
            io.BytesIO(secret_body),
        )
        from unittest import mock
        with mock.patch("production_pipeline.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(ProviderError) as caught:
                JsonProvider._request(
                    "https://provider.example/generate", {}, b"{}", 5
                )
        self.assertIn("Provider HTTP 500", str(caught.exception))
        self.assertNotIn("provider-body-secret", str(caught.exception))
        self.assertNotIn("body-token", str(caught.exception))
        self.assertTrue(caught.exception.retryable)

    def test_missing_provider_url_fails_closed(self):
        provider = JsonProvider("")
        with self.assertRaises(ProviderError) as caught:
            provider.post("script", {"topic": "test"})
        self.assertFalse(caught.exception.retryable)

    def test_queue_claim_filters_by_job_type(self):
        queue = JobQueue(str(Path(self.tmp.name) / "queue.sqlite3"))
        queue.enqueue("unrelated_task", {}, idempotency_key="other")
        queue.enqueue("short_video_production", self.brief, idempotency_key="video")
        claimed = queue.claim("worker-1", job_type="short_video_production")
        self.assertEqual(claimed["job_type"], "short_video_production")
        self.assertEqual(queue.get(claimed["id"])["status"], "running")

    def test_stale_worker_cannot_write_after_ambiguous_lease_expiry(self):
        db = self.store.db_path
        queue = JobQueue(db, lease_seconds=10)
        submitted = submit_production(queue, self.store, self.brief)
        job_id = submitted["job"]["id"]
        old_claim = queue.claim("worker-old", "host-old",
                                job_type="short_video_production")
        with queue.db() as connection:
            connection.execute(
                "UPDATE pipeline_jobs SET lease_expires_at=? WHERE id=?",
                ("2000-01-01T00:00:00+00:00", job_id)
            )
        new_claim = queue.claim("worker-new", "host-new",
                                job_type="short_video_production")
        self.assertIsNone(new_claim)
        self.assertTrue(queue.is_paused())
        failed_job = queue.get(job_id)
        self.assertEqual(failed_job["status"], "failed_terminal")
        self.assertEqual(failed_job["error_code"], "production_lease_expired_ambiguous")
        self.assertEqual(self.store.get(job_id)["status"], "failed_terminal")

        script = FakeProvider({"script": "Must never be called"})
        voice = FakeProvider({"audio_url": "https://media.example/audio.mp3"})
        render = FakeProvider({"video_url": "https://media.example/video.mp4"})
        pipeline = ProductionPipeline(self.store, script, voice, render)
        with self.assertRaises(ProductionLeaseConflict):
            pipeline.execute(job_id, self.brief, worker_id="worker-old",
                             lease_token=old_claim["lease_token"])
        self.assertEqual(script.calls, [])
        with self.assertRaises(ProductionLeaseConflict):
            self.store.artifact(job_id, "rendering", "video",
                                "https://media.example/stale.mp4", {},
                                worker_id="worker-old",
                                lease_token=old_claim["lease_token"])
    def test_queue_job_without_production_row_is_recovered_after_enqueue_crash(self):
        queue = JobQueue(self.store.db_path)
        job = queue.enqueue("short_video_production", self.brief,
                            idempotency_key="crash-window")
        self.assertIsNone(self.store.get(job["id"]))

        result = self.store.reconcile_missing_runs(queue)
        self.assertEqual(result["restored"], 1)
        self.assertEqual(result["job_ids"], [job["id"]])
        restored = self.store.get(job["id"])
        self.assertEqual(restored["status"], "queued")
        self.assertEqual(restored["topic"], self.brief["topic"])

        # Reconciliation is idempotent and does not replace an existing run.
        again = self.store.reconcile_missing_runs(queue)
        self.assertEqual(again["restored"], 0)
        self.assertEqual(self.store.get(job["id"])["status"], "queued")

    def test_recovery_can_target_a_job_claimed_during_enqueue_race(self):
        queue = JobQueue(self.store.db_path)
        job = queue.enqueue("short_video_production", self.brief)
        claimed = queue.claim("worker-race", "test-host",
                              job_type="short_video_production")
        self.assertEqual(claimed["id"], job["id"])

        result = self.store.reconcile_missing_runs(queue, job_ids=[claimed["id"]])
        self.assertEqual(result["restored"], 1)
        self.assertEqual(self.store.get(job["id"])["status"], "queued")

    def test_orphan_recovery_skips_non_object_payload_without_crashing(self):
        queue = JobQueue(self.store.db_path)
        job = queue.enqueue("short_video_production", ["not", "an", "object"])
        result = self.store.reconcile_missing_runs(queue)
        self.assertEqual(result["restored"], 0)
        self.assertEqual(result["invalid"], [job["id"]])
        self.assertIsNone(self.store.get(job["id"]))

    def test_worker_pause_mirrors_terminal_state_into_production_record(self):
        queue = JobQueue(self.store.db_path)
        submitted = submit_production(queue, self.store, self.brief)
        job_id = submitted["job"]["id"]
        queue.claim("worker-paused", job_type="short_video_production")

        queue.pause("provider result uncertain", job_id)

        job = queue.get(job_id)
        production = self.store.get(job_id)
        self.assertEqual(job["status"], "failed_terminal")
        self.assertEqual(job["error_code"], "production_pause_external_outcome_ambiguous")
        self.assertEqual(production["status"], "failed_terminal")
        self.assertEqual(production["current_stage"], "pause_outcome_ambiguous")

    def test_lost_worker_signal_stops_before_any_provider_call(self):
        import threading

        script = FakeProvider({"script": "must not run"})
        voice = FakeProvider({"audio_url": "https://media.example/audio.mp3"})
        render = FakeProvider({"video_url": "https://media.example/video.mp4"})
        pipeline = ProductionPipeline(self.store, script, voice, render)
        self.store.create("job-stop", self.brief)
        stop_event = threading.Event()
        stop_event.set()

        with self.assertRaises(ProductionLeaseConflict):
            pipeline.execute("job-stop", self.brief, stop_event=stop_event)

        self.assertEqual(script.calls, [])
        self.assertEqual(voice.calls, [])
        self.assertEqual(render.calls, [])

    def test_provider_response_is_durable_before_artifact_adoption(self):
        self.store.create("job-provider-journal",self.brief)
        number=self.store.next_provider_attempt_number("job-provider-journal","rendering")
        self.assertEqual(number,1)
        key=self.store.begin_provider_attempt("job-provider-journal","rendering",number)
        attempts=self.store.provider_attempts("job-provider-journal")
        self.assertEqual(attempts[0]["state"],"request_started")
        self.store.finish_provider_attempt(
            "job-provider-journal","rendering",number,key,
            {"request_id":"render-remote-123","video_url":"https://media.example/ready.mp4"})
        saved=self.store.provider_attempts("job-provider-journal")
        self.assertEqual(saved[0]["state"],"response_received")
        self.assertEqual(saved[0]["provider_request_id"],"render-remote-123")
        self.assertIn("ready.mp4",saved[0]["response_json"])
        self.assertEqual(self.store.next_provider_attempt_number("job-provider-journal","rendering"),2)
        self.assertEqual(self.store.get("job-provider-journal")["artifacts"],[])

    def test_pipeline_recovers_persisted_script_response_without_duplicate_provider_call(self):
        self.store.create("job-script-recovery",self.brief)
        key=self.store.begin_provider_attempt("job-script-recovery","script",1)
        self.store.finish_provider_attempt(
            "job-script-recovery","script",1,key,
            {"script":"Recovered script text with a useful opening and takeaway.",
             "provider":"fixture","request_id":"script-remote-42"})
        script=FakeProvider(AssertionError("script provider must not be called again"))
        voice=FakeProvider({"audio_url":"https://media.example/recovered.mp3"})
        render=FakeProvider({"video_url":"https://media.example/recovered.mp4"})
        result=ProductionPipeline(self.store,script,voice,render).execute(
            "job-script-recovery",self.brief)
        self.assertEqual(result["status"],"rendered")
        self.assertEqual(script.calls,[])
        self.assertEqual(len(voice.calls),1)
        self.assertEqual(len(render.calls),1)
        attempts=self.store.provider_attempts("job-script-recovery")
        script_attempt=next(item for item in attempts if item["stage"]=="script")
        self.assertEqual(script_attempt["state"],"adopted")
        artifact=next(item for item in result["artifacts"] if item["stage"]=="script")
        self.assertIn("Recovered script text",artifact["metadata"]["script"])

    def test_pipeline_recovers_persisted_render_response_without_duplicate_render_call(self):
        self.store.create("job-render-recovery",self.brief)
        self.store.artifact("job-render-recovery","script","text",None,{
            "script":"Recovered script text with a useful opening and takeaway.",
            "provider_quality_metadata":{},"policy_preflight":{}})
        self.store.artifact("job-render-recovery","voice_generation","audio",
            "https://media.example/recovered.mp3",{"voice":"en-US"})
        key=self.store.begin_provider_attempt("job-render-recovery","rendering",1)
        self.store.finish_provider_attempt(
            "job-render-recovery","rendering",1,key,
            {"video_url":"https://media.example/recovered.mp4","duration_seconds":28})
        script=FakeProvider(AssertionError("existing script artifact should be used"))
        voice=FakeProvider(AssertionError("existing voice artifact should be used"))
        render=FakeProvider(AssertionError("render provider must not be called again"))
        # The pipeline's current orchestration still requests upstream stages; seed
        # their durable response journals so each stage resumes without external calls.
        for stage,response in (
            ("script",{"script":"Recovered script text with a useful opening and takeaway."}),
            ("voice_generation",{"audio_url":"https://media.example/recovered.mp3"}),
        ):
            key=self.store.begin_provider_attempt("job-render-recovery",stage,1)
            self.store.finish_provider_attempt(
                "job-render-recovery",stage,1,key,response)
        result=ProductionPipeline(self.store,script,voice,render).execute(
            "job-render-recovery",self.brief)
        self.assertEqual(result["status"],"rendered")
        self.assertEqual(script.calls,[])
        self.assertEqual(voice.calls,[])
        self.assertEqual(render.calls,[])
        self.assertTrue(all(item["state"]=="adopted"
                            for item in self.store.provider_attempts("job-render-recovery")))

    def test_provider_transport_error_is_recorded_as_unknown_not_retried(self):
        self.store.create("job-provider-unknown",self.brief)
        key=self.store.begin_provider_attempt("job-provider-unknown","voice_generation",1)
        self.store.mark_provider_attempt_unknown(
            "job-provider-unknown","voice_generation",1,key,"connection timed out")
        attempt=self.store.provider_attempts("job-provider-unknown")[0]
        self.assertEqual(attempt["state"],"outcome_unknown")
        self.assertEqual(attempt["error"],"connection timed out")
        self.assertEqual(self.store.next_provider_attempt_number(
            "job-provider-unknown","voice_generation"),2)

    def test_unresolved_provider_attempt_blocks_new_attempt_for_all_ambiguous_states(self):
        for state in ("request_started","outcome_unknown","response_received"):
            with self.subTest(state=state):
                job_id="job-unresolved-"+state
                self.store.create(job_id,self.brief)
                key=self.store.begin_provider_attempt(job_id,"rendering",1)
                if state=="outcome_unknown":
                    self.store.mark_provider_attempt_unknown(
                        job_id,"rendering",1,key,"transport timeout")
                elif state=="response_received":
                    self.store.finish_provider_attempt(
                        job_id,"rendering",1,key,
                        {"request_id":"remote-"+state,"video_url":"https://media.example/video.mp4"})
                with self.assertRaisesRegex(
                        ProviderAttemptConflict,"unresolved external outcome"):
                    self.store.begin_provider_attempt(job_id,"rendering",2)
                attempts=self.store.provider_attempts(job_id)
                self.assertEqual(len(attempts),1)
                self.assertEqual(attempts[0]["state"],state)

    def test_ambiguous_provider_attempt_requires_evidenced_operator_reconciliation(self):
        self.store.create("job-provider-reconcile",self.brief)
        key=self.store.begin_provider_attempt("job-provider-reconcile","script",1)
        self.store.mark_provider_attempt_unknown(
            "job-provider-reconcile","script",1,key,"connection timed out")
        attempt=self.store.provider_attempts("job-provider-reconcile")[0]
        with self.assertRaisesRegex(ValueError,"operator, evidence reference and note"):
            self.store.confirm_provider_attempt_not_executed(
                "job-provider-reconcile",attempt["id"],"admin-1","","confirmed")
        result=self.store.confirm_provider_attempt_not_executed(
            "job-provider-reconcile",attempt["id"],"admin-1",
            "provider-console-case-123","Provider console confirms no remote job.")
        self.assertEqual(result["state"],"not_executed_confirmed")
        saved=self.store.provider_attempts("job-provider-reconcile")[0]
        self.assertEqual(saved["state"],"not_executed_confirmed")
        with self.store.db() as connection:
            event=connection.execute(
                """SELECT operator_id,evidence_reference,note,resolution
                   FROM provider_attempt_reconciliation_events WHERE job_id=?""",
                ("job-provider-reconcile",)).fetchone()
        self.assertEqual(event["operator_id"],"admin-1")
        self.assertEqual(event["evidence_reference"],"provider-console-case-123")
        self.assertEqual(event["resolution"],"not_executed_confirmed")
        with self.assertRaisesRegex(ValueError,"only an ambiguous"):
            self.store.confirm_provider_attempt_not_executed(
                "job-provider-reconcile",attempt["id"],"admin-1","case-123","duplicate")

    def test_provider_response_received_cannot_be_dismissed_as_not_executed(self):
        self.store.create("job-provider-response",self.brief)
        key=self.store.begin_provider_attempt("job-provider-response","script",1)
        self.store.finish_provider_attempt(
            "job-provider-response","script",1,key,{"script":"Durable response"})
        attempt=self.store.provider_attempts("job-provider-response")[0]
        with self.assertRaisesRegex(ValueError,"only an ambiguous"):
            self.store.confirm_provider_attempt_not_executed(
                "job-provider-response",attempt["id"],"admin-1","case-123","not executed")

    def test_provider_response_rejects_oversized_or_non_object_payload(self):
        self.store.create("job-provider-bounds",self.brief)
        key=self.store.begin_provider_attempt("job-provider-bounds","script",1)
        with self.assertRaisesRegex(ValueError,"object"):
            self.store.finish_provider_attempt(
                "job-provider-bounds","script",1,key,["not","an","object"])
        with self.assertRaisesRegex(ValueError,"2 MB"):
            self.store.finish_provider_attempt(
                "job-provider-bounds","script",1,key,{"data":"x"*(2*1024*1024)})

    def test_verified_provider_render_is_adopted_once_and_requires_human_review(self):
        queue=JobQueue(self.store.db_path)
        job_id=queue.enqueue("short_video_production",self.brief)["id"]
        self.store.create(job_id,self.brief)
        self.store.artifact(job_id,"script","text",None,{
            "script":"A sufficiently detailed recovered video script with useful context.",
            "provider_quality_metadata":{"factual_claims_verified":True},
            "policy_preflight":{"status":"review_required","approval_blockers":[]}})
        self.store.artifact(job_id,"voice_generation","audio",
            "https://cdn.example.test/audio.mp3",{"duration_seconds":32.5})
        key=self.store.begin_provider_attempt(job_id,"rendering",1)
        self.store.finish_provider_attempt(
            job_id,"rendering",1,key,
            {"request_id":"render-verified-77",
             "video_url":"https://cdn.example.test/output.mp4"})
        staged={"media_path":"abc123.mp4","size_bytes":4096,
                "sha256":"a"*64,"content_type":"video/mp4"}
        inspection={"status":"inspected","duration_seconds":32.5,
                    "width":1080,"height":1920,"audio_track_present":True,
                    "inspection_method":"ffprobe_file_bytes"}
        attempt=self.store.provider_attempts(job_id)[0]
        result=self.store.adopt_recovered_render(
            job_id,attempt["id"],staged,inspection)
        self.assertEqual(result["status"],"review_pending")
        production=self.store.get(job_id)
        self.assertEqual(production["status"],"review_pending")
        self.assertEqual(production["current_stage"],"recovered_render_adopted")
        self.assertEqual(len(production["artifacts"]),4)
        artifact=next(item for item in production["artifacts"]
                      if item["stage"]=="rendering")
        quality=next(item for item in production["artifacts"]
                     if item["stage"]=="quality_check")
        self.assertIn(quality["metadata"]["status"],("ready_for_human_review","review_required"))
        self.assertIsNotNone(quality["metadata"]["checks"])
        self.assertEqual(artifact["artifact_url"],"https://cdn.example.test/output.mp4")
        self.assertEqual(artifact["metadata"]["media_staging"]["sha256"],"a"*64)
        self.assertEqual(self.store.provider_attempts(job_id)[0]["state"],"adopted")
        self.assertEqual(queue.get(job_id)["status"],"review_pending")
        self.assertEqual(queue.events(job_id)[-1]["event_type"],"provider_result_recovered")
        with self.assertRaisesRegex(ValueError,"not available"):
            self.store.adopt_recovered_render(
                job_id,attempt["id"],staged,inspection)

    def test_provider_render_adoption_rejects_unverified_or_nonvertical_media(self):
        queue=JobQueue(self.store.db_path)
        job_id=queue.enqueue("short_video_production",self.brief)["id"]
        self.store.create(job_id,self.brief)
        key=self.store.begin_provider_attempt(job_id,"rendering",1)
        self.store.finish_provider_attempt(
            job_id,"rendering",1,key,
            {"video_url":"https://cdn.example.test/output.mp4"})
        attempt=self.store.provider_attempts(job_id)[0]
        staged={"media_path":"abc123.mp4","size_bytes":4096,
                "sha256":"b"*64,"content_type":"video/mp4"}
        bad={"status":"inspected","duration_seconds":32.5,
             "width":1920,"height":1080,"audio_track_present":True}
        with self.assertRaisesRegex(ValueError,"failed required"):
            self.store.adopt_recovered_render(job_id,attempt["id"],staged,bad)
        bad["width"],bad["height"]=1080,1920
        bad["audio_track_present"]=False
        with self.assertRaisesRegex(ValueError,"failed required"):
            self.store.adopt_recovered_render(job_id,attempt["id"],staged,bad)
        self.assertEqual(self.store.provider_attempts(job_id)[0]["state"],
                         "response_received")
        self.assertEqual(self.store.get(job_id)["artifacts"],[])
        self.assertEqual(queue.get(job_id)["status"],"queued")



    def test_integrity_report_paginates_without_duplicate_or_missing_records(self):
        queue = JobQueue(self.store.db_path)
        created = []
        for index in range(3):
            job = queue.enqueue(
                "short_video_production", {"brand": "", "region": "US",
                                           "language": "en", "topic": ""},
                channel_name=f"page-{index}"
            )
            created.append(job["id"])
        first = self.store.integrity_report(queue, limit=2, offset=0)
        second = self.store.integrity_report(queue, limit=2, offset=2)
        first_ids = [item["job_id"] for item in first["items"]]
        second_ids = [item["job_id"] for item in second["items"]]
        self.assertEqual(first["offset"], 0)
        self.assertEqual(first["next_offset"], 2)
        self.assertTrue(first["has_more"])
        self.assertEqual(second["offset"], 2)
        self.assertIsNone(second["next_offset"])
        self.assertFalse(second["has_more"])
        self.assertEqual(len(first_ids), 2)
        self.assertEqual(len(second_ids), 1)
        self.assertEqual(len(set(first_ids + second_ids)), 3)
        self.assertEqual(set(first_ids + second_ids), set(created))


    def test_integrity_report_cursor_is_stable_when_existing_rows_change(self):
        queue = JobQueue(self.store.db_path)
        created = []
        for index in range(4):
            job = queue.enqueue(
                "short_video_production", {"brand": "", "region": "US",
                                           "language": "en", "topic": ""},
                channel_name=f"cursor-{index}"
            )
            created.append(job["id"])
        first = self.store.integrity_report(queue, limit=2)
        self.assertTrue(first["has_more"])
        self.assertIsNotNone(first["next_cursor"])
        first_ids = [item["job_id"] for item in first["items"]]
        with queue.db() as connection:
            connection.execute(
                "UPDATE pipeline_jobs SET updated_at='2999-01-01T00:00:00+00:00' WHERE id=?",
                (first_ids[0],)
            )
        second = self.store.integrity_report(
            queue, limit=2, cursor=first["next_cursor"]
        )
        second_ids = [item["job_id"] for item in second["items"]]
        self.assertEqual(len(second_ids), 2)
        self.assertFalse(set(first_ids) & set(second_ids))
        self.assertEqual(set(first_ids + second_ids), set(created))
        self.assertFalse(second["has_more"])
        self.assertIsNone(second["next_cursor"])

    def test_integrity_report_rejects_malformed_cursor(self):
        queue = JobQueue(self.store.db_path)
        with self.assertRaisesRegex(ValueError, "Invalid integrity report cursor"):
            self.store.integrity_report(queue, cursor="not-a-valid-cursor")

    def test_integrity_report_detects_both_orphan_record_directions_without_mutation(self):
        queue = JobQueue(self.store.db_path)
        queue_only = queue.enqueue(
            "short_video_production", {"brand": "", "region": "US",
                                       "language": "en", "topic": ""},
            channel_name="orphan-queue"
        )
        production_only_id = "production-without-queue"
        self.store.create(production_only_id, self.brief)

        report = self.store.integrity_report(queue, limit=20)
        self.assertEqual(report["orphaned"], 2)
        by_id = {item["job_id"]: item for item in report["items"]}
        queue_item = by_id[queue_only["id"]]
        self.assertEqual(queue_item["record_kind"], "queue_without_production")
        self.assertEqual(queue_item["classification"], "queue_without_production_record")
        self.assertIsNone(queue_item["production_status"])
        self.assertEqual(queue_item["queue_status"], "queued")
        production_item = by_id[production_only_id]
        self.assertEqual(production_item["record_kind"], "production_without_queue")
        self.assertEqual(production_item["classification"], "production_without_queue_record")
        self.assertEqual(production_item["production_status"], "queued")
        self.assertIsNone(production_item["queue_status"])
        self.assertEqual(queue.get(queue_only["id"])["status"], "queued")
        self.assertIsNone(self.store.get(queue_only["id"]))
        with queue.db() as connection:
            self.assertIsNone(connection.execute(
                "SELECT id FROM pipeline_jobs WHERE id=?", (production_only_id,)
            ).fetchone())
        self.assertEqual(self.store.get(production_only_id)["status"], "queued")

    def test_integrity_report_orphan_scan_respects_bound(self):
        queue = JobQueue(self.store.db_path)
        for index in range(3):
            queue.enqueue(
                "short_video_production", {"brand": "", "region": "US",
                                           "language": "en", "topic": ""},
                channel_name=f"orphan-{index}"
            )
        production_only_id = "production-without-queue-bounded"
        self.store.create(production_only_id, self.brief)
        mismatch_id = submit_production(queue, self.store, {
            **self.brief, "topic": "A mismatched lifecycle row"
        })["job"]["id"]
        with queue.db() as connection:
            connection.execute(
                "UPDATE pipeline_jobs SET status='review_pending' WHERE id=?",
                (mismatch_id,)
            )
        report = self.store.integrity_report(queue, limit=1)
        self.assertEqual(report["limit"], 1)
        self.assertEqual(report["scanned"], 1)
        self.assertEqual(report["unresolved"], 5)
        self.assertEqual(report["orphaned"], 4)
        self.assertTrue(report["has_more"])
        self.assertEqual(report["counts"], {
            "state_mismatch": 1,
            "queue_without_production": 3,
            "production_without_queue": 1,
        })
        self.assertIn(report["items"][0]["record_kind"], (
            "queue_without_production", "production_without_queue"
        ))
        self.assertEqual(len(report["items"]), 1)


    def test_integrity_report_batches_and_bounds_audit_history_per_job(self):
        queue = JobQueue(self.store.db_path)
        job_id = submit_production(queue, self.store, self.brief)["job"]["id"]
        with queue.db() as connection:
            connection.execute(
                "UPDATE pipeline_jobs SET status='review_pending' WHERE id=?", (job_id,)
            )
            for index in range(12):
                connection.execute("""
                    INSERT INTO job_events
                      (job_id,event_type,from_status,to_status,worker_id,details_json,created_at)
                    VALUES(?,?,?,?,?,?,?)
                """, (job_id, f"diagnostic_history_{index}", None, None, None, "{}",
                      f"2026-11-16T00:00:{index:02d}+00:00"))
        report = self.store.integrity_report(queue)
        item = next(entry for entry in report["items"] if entry["job_id"] == job_id)
        history = item["audit_history"]
        self.assertEqual(len(history), 10)
        self.assertEqual(
            [event["event_type"] for event in history],
            [f"diagnostic_history_{index}" for index in range(2, 12)]
        )


    def test_integrity_report_withholds_raw_provider_error_text(self):
        queue = JobQueue(self.store.db_path)
        job_id = submit_production(queue, self.store, self.brief)["job"]["id"]
        secret_detail = "Authorization: Bearer provider-secret-do-not-expose"
        with queue.db() as connection:
            connection.execute(
                "UPDATE pipeline_jobs SET status='review_pending',error_code='provider_render',"
                "error_message=? WHERE id=?",
                (secret_detail, job_id)
            )
        report = self.store.integrity_report(queue)
        item = next(entry for entry in report["items"] if entry["job_id"] == job_id)
        self.assertEqual(item["error_code"], "provider_render")
        self.assertEqual(
            item["error_message"],
            "상세 오류는 보호된 서버 로그에서 확인하세요."
        )
        self.assertNotIn(secret_detail, str(report))
        self.assertNotIn("provider-secret-do-not-expose", str(report))

    def test_integrity_report_explains_mismatch_without_mutating_either_ledger(self):
        queue = JobQueue(self.store.db_path)
        job_id = submit_production(queue, self.store, self.brief)["job"]["id"]
        with queue.db() as connection:
            connection.execute(
                "UPDATE pipeline_jobs SET status='review_pending' WHERE id=?",
                (job_id,)
            )
            connection.execute(
                "UPDATE production_runs SET status='approved',current_stage='review' WHERE job_id=?",
                (job_id,)
            )
            connection.execute("""
                INSERT INTO job_events
                  (job_id,event_type,from_status,to_status,worker_id,details_json,created_at)
                VALUES(?,'operator_reconciliation','failed_terminal','failed_retriable',
                       NULL,?,?)
            """, (job_id, '{"outcome":"confirmed_no_external_side_effect",'
                          '"operator_id":"review-operator",'
                          '"evidence_reference":"ticket-123","secret":"must-not-leak"}',
                  "2026-11-16T00:00:00+00:00"))

        report = self.store.integrity_report(queue)
        self.assertEqual(report["scanned"], 1)
        item = report["items"][0]
        self.assertEqual(item["job_id"], job_id)
        self.assertEqual(item["classification"], "approval_or_upload_boundary")
        self.assertIn("automatic promotion is prohibited", item["reason"])
        reconciliation = next(event for event in item["audit_history"]
                               if event["event_type"] == "operator_reconciliation")
        self.assertEqual(reconciliation["details"]["operator_id"], "review-operator")
        self.assertNotIn("secret", str(item["audit_history"]))
        self.assertEqual(self.store.get(job_id)["status"], "approved")
        self.assertEqual(queue.get(job_id)["status"], "review_pending")
        self.assertFalse(report["worker_control"]["paused"])

    def test_integrity_report_is_bounded_and_requires_shared_database(self):
        queue = JobQueue(self.store.db_path)
        first = submit_production(queue, self.store, self.brief)["job"]["id"]
        second = submit_production(queue, self.store, {**self.brief, "topic": "Second"})["job"]["id"]
        with queue.db() as connection:
            for job_id in (first, second):
                connection.execute(
                    "UPDATE pipeline_jobs SET status='review_pending' WHERE id=?", (job_id,)
                )
                connection.execute(
                    "UPDATE production_runs SET status='approved' WHERE job_id=?", (job_id,)
                )
        report = self.store.integrity_report(queue, limit=1)
        self.assertEqual(report["limit"], 1)
        self.assertEqual(report["scanned"], 1)
        other = JobQueue(str(Path(self.tmp.name) / "other.sqlite3"))
        with self.assertRaisesRegex(ValueError, "same SQLite database"):
            self.store.integrity_report(other)

    def test_status_integrity_repairs_only_safe_terminal_and_review_handoffs(self):
        queue = JobQueue(self.store.db_path)
        terminal_job = submit_production(queue, self.store, self.brief)["job"]["id"]
        review_job = submit_production(queue, self.store, self.brief)["job"]["id"]
        approved_job = submit_production(queue, self.store, self.brief)["job"]["id"]

        # Simulate a crash after queue terminalization but before production sync.
        with queue.db() as connection:
            connection.execute(
                "UPDATE pipeline_jobs SET status='failed_terminal',error_message='provider failed' WHERE id=?",
                (terminal_job,)
            )
            connection.execute(
                "UPDATE pipeline_jobs SET status='review_pending' WHERE id=?",
                (review_job,)
            )
            connection.execute(
                "UPDATE production_runs SET status='rendered',current_stage='rendered' WHERE job_id=?",
                (review_job,)
            )
            connection.execute(
                "UPDATE pipeline_jobs SET status='review_pending' WHERE id=?",
                (approved_job,)
            )
            connection.execute(
                "UPDATE production_runs SET status='approved',current_stage='review' WHERE job_id=?",
                (approved_job,)
            )

        result = self.store.reconcile_status_integrity(queue)
        self.assertEqual(result["repaired"], 2)
        self.assertEqual(result["unresolved"], 1)
        self.assertEqual(self.store.get(terminal_job)["status"], "failed_terminal")
        self.assertEqual(self.store.get(review_job)["status"], "review_pending")
        self.assertEqual(self.store.get(approved_job)["status"], "approved")
        self.assertEqual(queue.get(approved_job)["status"], "review_pending")
        self.assertEqual(
            [event["event_type"] for event in queue.events(terminal_job)].count(
                "production_state_reconciled"
            ), 1
        )
        self.assertEqual(
            [event["event_type"] for event in queue.events(review_job)].count(
                "production_state_reconciled"
            ), 1
        )
        self.assertEqual(result["unresolved_jobs"][0]["job_id"], approved_job)

    def test_status_integrity_is_idempotent_after_safe_repair(self):
        queue = JobQueue(self.store.db_path)
        job_id = submit_production(queue, self.store, self.brief)["job"]["id"]
        with queue.db() as connection:
            connection.execute(
                "UPDATE pipeline_jobs SET status='cancelled',error_message='operator cancel' WHERE id=?",
                (job_id,)
            )
        first = self.store.reconcile_status_integrity(queue)
        second = self.store.reconcile_status_integrity(queue)
        self.assertEqual(first["repaired"], 1)
        self.assertEqual(second["scanned"], 0)
        self.assertEqual(
            [event["event_type"] for event in queue.events(job_id)].count(
                "production_state_reconciled"
            ), 1
        )

    def test_status_integrity_rejects_different_databases(self):
        other = JobQueue(str(Path(self.tmp.name) / "other.sqlite3"))
        with self.assertRaisesRegex(ValueError, "same SQLite database"):
            self.store.reconcile_status_integrity(other)


    def _create_claimed_production_job(self):
        queue = JobQueue(self.store.db_path)
        job = queue.enqueue("short_video_production", self.brief)
        self.store.create(job["id"], self.brief)
        claimed = queue.claim("worker-old", job_type="short_video_production")
        self.assertEqual(claimed["id"], job["id"])
        request_key = self.store.begin_provider_attempt(
            job["id"], "rendering", 1,
            worker_id="worker-old", lease_token=claimed["lease_token"],
        )
        # Simulate a replacement lease while the provider request is in flight.
        with queue.db() as connection:
            connection.execute(
                "UPDATE pipeline_jobs SET lease_token=? WHERE id=?",
                ("replacement-fencing-token", job["id"]),
            )
        return queue, job["id"], request_key, claimed["lease_token"]

    def test_stale_worker_cannot_finalize_provider_response_after_lease_replacement(self):
        queue, job_id, request_key, old_token = self._create_claimed_production_job()
        with self.assertRaises(ProductionLeaseConflict):
            self.store.finish_provider_attempt(
                job_id, "rendering", 1, request_key,
                {"video_url": "https://cdn.example.test/stale.mp4"},
                worker_id="worker-old", lease_token=old_token,
            )
        attempt = self.store.provider_attempts(job_id)[0]
        self.assertEqual(attempt["state"], "request_started")
        self.assertIsNone(attempt["response_json"])
        self.assertEqual(queue.get(job_id)["lease_token"], "replacement-fencing-token")

    def test_stale_worker_cannot_finalize_unknown_provider_outcome_after_lease_replacement(self):
        queue, job_id, request_key, old_token = self._create_claimed_production_job()
        with self.assertRaises(ProductionLeaseConflict):
            self.store.mark_provider_attempt_unknown(
                job_id, "rendering", 1, request_key, "connection lost",
                worker_id="worker-old", lease_token=old_token,
            )
        attempt = self.store.provider_attempts(job_id)[0]
        self.assertEqual(attempt["state"], "request_started")
        self.assertIsNone(attempt["error"])
        self.assertEqual(queue.get(job_id)["lease_token"], "replacement-fencing-token")

    def test_concurrent_provider_attempt_starts_allow_only_one_external_request(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        self.store.create("job-concurrent-provider-start", self.brief)
        gate = Barrier(2)

        def start_attempt():
            gate.wait()
            try:
                return self.store.begin_provider_attempt(
                    "job-concurrent-provider-start", "rendering", 1
                )
            except ProviderAttemptConflict as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: start_attempt(), range(2)))

        keys = [value for value in outcomes if isinstance(value, str)]
        conflicts = [value for value in outcomes
                     if isinstance(value, ProviderAttemptConflict)]
        self.assertEqual(len(keys), 1)
        self.assertEqual(len(conflicts), 1)
        attempts = self.store.provider_attempts("job-concurrent-provider-start")
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["state"], "request_started")
        self.assertEqual(attempts[0]["idempotency_key"], keys[0])

        # A second worker cannot create a new provider request while the first
        # request's external outcome is unresolved.
        with self.assertRaises(ProviderAttemptConflict):
            self.store.begin_provider_attempt(
                "job-concurrent-provider-start", "rendering", 2
            )

        self.store.confirm_provider_attempt_not_executed(
            "job-concurrent-provider-start", attempts[0]["id"],
            "operator-1", "provider-console:request-not-found",
            "Provider history confirms the request was not executed",
        )
        replacement = self.store.begin_provider_attempt(
            "job-concurrent-provider-start", "rendering", 2
        )
        self.assertNotEqual(replacement, keys[0])
        final_attempts = self.store.provider_attempts("job-concurrent-provider-start")
        self.assertEqual([item["state"] for item in final_attempts],
                         ["not_executed_confirmed", "request_started"])
        self.assertEqual([item["attempt_number"] for item in final_attempts], [1, 2])

    def test_invalid_brief_rejected(self):
        with self.assertRaises(ValueError):
            ProductionPipeline.validate_brief({"brand": "x", "region": "US",
                                                "language": "en", "topic": ""})


if __name__ == "__main__":
    unittest.main()
