import tempfile
import unittest
from pathlib import Path

from production_pipeline import (
    JsonProvider, ProductionPipeline, ProductionStore, ProductionLeaseConflict, ProviderError,
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
        self.assertEqual(job["error_code"], "worker_paused")
        self.assertEqual(production["status"], "failed_terminal")
        self.assertEqual(production["current_stage"], "worker_paused")

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
        with self.assertRaisesRegex(ProviderError,"remains outcome_unknown"):
            self.store.begin_provider_attempt("job-provider-unknown","voice_generation",2)

    def test_provider_response_must_be_adopted_before_a_new_attempt(self):
        self.store.create("job-provider-unadopted",self.brief)
        key=self.store.begin_provider_attempt("job-provider-unadopted","script",1)
        self.store.finish_provider_attempt(
            "job-provider-unadopted","script",1,key,{"script":"durable result"})
        with self.assertRaisesRegex(ProviderError,"remains response_received"):
            self.store.begin_provider_attempt("job-provider-unadopted","script",2)
        self.store.mark_provider_attempt_adopted(
            "job-provider-unadopted","script",1,key)
        next_key=self.store.begin_provider_attempt("job-provider-unadopted","script",2)
        self.assertTrue(next_key)

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
                    "size_bytes":4096,"media_path":"abc123.mp4",
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

    def test_recovered_render_adoption_rejects_inspection_for_different_staged_bytes(self):
        queue=JobQueue(self.store.db_path)
        job_id=queue.enqueue("short_video_production",self.brief)["id"]
        self.store.create(job_id,self.brief)
        self.store.artifact(job_id,"script","text",None,{
            "script":"A sufficiently detailed recovered video script with useful context."})
        self.store.artifact(job_id,"voice_generation","audio",
            "https://cdn.example.test/audio.mp3",{"duration_seconds":32.5})
        key=self.store.begin_provider_attempt(job_id,"rendering",1)
        self.store.finish_provider_attempt(
            job_id,"rendering",1,key,
            {"video_url":"https://cdn.example.test/output.mp4"})
        attempt=self.store.provider_attempts(job_id)[0]
        staged={"media_path":"verified.mp4","size_bytes":4096,
                "sha256":"c"*64,"content_type":"video/mp4"}
        inspection={"status":"inspected","duration_seconds":32.5,
                    "width":1080,"height":1920,"audio_track_present":True,
                    "size_bytes":4095,"media_path":"verified.mp4",
                    "inspection_method":"ffprobe_file_bytes"}
        with self.assertRaisesRegex(ValueError,"does not match the staged media fingerprint"):
            self.store.adopt_recovered_render(job_id,attempt["id"],staged,inspection)
        inspection["size_bytes"]=4096
        inspection["media_path"]="different.mp4"
        with self.assertRaisesRegex(ValueError,"does not match the staged media fingerprint"):
            self.store.adopt_recovered_render(job_id,attempt["id"],staged,inspection)
        self.assertEqual(self.store.provider_attempts(job_id)[0]["state"],"response_received")
        self.assertEqual(
            {item["stage"] for item in self.store.get(job_id)["artifacts"]},
            {"script","voice_generation"})
        self.assertEqual(queue.get(job_id)["status"],"queued")

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

    def test_recovered_render_rejects_boolean_and_nonfinite_measurements(self):
        queue=JobQueue(self.store.db_path)
        job_id=queue.enqueue("short_video_production",self.brief)["id"]
        self.store.create(job_id,self.brief)
        key=self.store.begin_provider_attempt(job_id,"rendering",1)
        self.store.finish_provider_attempt(
            job_id,"rendering",1,key,{"video_url":"https://cdn.example.test/output.mp4"})
        attempt=self.store.provider_attempts(job_id)[0]
        staged={"media_path":"finite.mp4","size_bytes":4096,
                "sha256":"d"*64,"content_type":"video/mp4"}
        base={"status":"inspected","duration_seconds":32.5,
              "width":1080,"height":1920,"audio_track_present":True,
              "size_bytes":4096,"media_path":"finite.mp4",
              "inspection_method":"ffprobe_file_bytes"}
        for field,value in (("duration_seconds",float("nan")),
                            ("duration_seconds",float("inf")),
                            ("width",True),("height",True)):
            invalid={**base,field:value}
            with self.assertRaisesRegex(ValueError,"metadata is invalid|failed required"):
                self.store.adopt_recovered_render(job_id,attempt["id"],staged,invalid)
        invalid_staged={**staged,"size_bytes":True}
        with self.assertRaisesRegex(ValueError,"size must be an integer"):
            self.store.adopt_recovered_render(job_id,attempt["id"],invalid_staged,base)
        self.assertEqual(self.store.provider_attempts(job_id)[0]["state"],"response_received")
        self.assertEqual(self.store.get(job_id)["artifacts"],[])
        self.assertEqual(queue.get(job_id)["status"],"queued")

    def test_invalid_brief_rejected(self):
        with self.assertRaises(ValueError):
            ProductionPipeline.validate_brief({"brand": "x", "region": "US",
                                                "language": "en", "topic": ""})


if __name__ == "__main__":
    unittest.main()
