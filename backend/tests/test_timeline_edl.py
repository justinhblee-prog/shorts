import unittest

from timeline_edl import EDLValidationError, SCHEMA, validate_edl


class TimelineEDLTests(unittest.TestCase):
    def setUp(self):
        self.valid = {
            "schema": SCHEMA, "version": 1, "timebase": "milliseconds",
            "clips": [
                {"id": "clip-1", "type": "video", "start_ms": 0, "end_ms": 5000,
                 "asset_id": "asset_1", "source_in_ms": 1000, "source_out_ms": 6000},
                {"id": "title-1", "type": "title", "start_ms": 1000, "end_ms": 3000,
                 "text": "Launch"},
            ],
        }

    def test_normalizes_supported_video_and_title_clips(self):
        result = validate_edl(self.valid)
        self.assertEqual(result["clips"][0]["asset_id"], "asset_1")
        self.assertEqual(result["clips"][1]["text"], "Launch")
        self.assertEqual(result["version"], 1)

    def test_rejects_unknown_version_and_fields(self):
        for mutate in (
            lambda p: p.update(version=2),
            lambda p: p.update(version=True),
            lambda p: p.update(remote_url="https://evil.example/video.mp4"),
            lambda p: p["clips"][0].update(local_path="C:/secret.mp4"),
        ):
            payload = {**self.valid, "clips": [dict(x) for x in self.valid["clips"]]}
            mutate(payload)
            with self.subTest(payload=payload), self.assertRaises(EDLValidationError):
                validate_edl(payload)

    def test_rejects_title_only_edl_before_render_submission(self):
        payload = {
            **self.valid,
            "clips": [{
                "id": "title-only", "type": "title",
                "start_ms": 0, "end_ms": 3000, "text": "Opening title",
            }],
        }
        with self.assertRaisesRegex(EDLValidationError, "at least one video clip"):
            validate_edl(payload)

    def test_rejects_duplicate_ids_and_unknown_asset_aliases(self):
        payload = {**self.valid, "clips": [dict(x) for x in self.valid["clips"]]}
        payload["clips"][1]["id"] = "clip-1"
        with self.assertRaisesRegex(EDLValidationError, "unique"):
            validate_edl(payload)
        payload = {**self.valid, "clips": [dict(x) for x in self.valid["clips"]]}
        payload["clips"][0]["asset_id"] = "../private"
        with self.assertRaises(EDLValidationError):
            validate_edl(payload)

    def test_rejects_non_finite_negative_and_inconsistent_times(self):
        for field, value in (("start_ms", float("nan")), ("end_ms", float("inf")),
                             ("source_in_ms", -1), ("source_out_ms", 7000),
                             ("start_ms", 10**10000)):
            payload = {**self.valid, "clips": [dict(x) for x in self.valid["clips"]]}
            payload["clips"][0][field] = value
            with self.subTest(field=field), self.assertRaises(EDLValidationError):
                validate_edl(payload)

    def test_rejects_empty_oversized_and_invalid_titles(self):
        with self.assertRaises(EDLValidationError):
            validate_edl({**self.valid, "clips": []})
        payload = {**self.valid, "clips": [dict(x) for x in self.valid["clips"]]}
        payload["clips"][1]["text"] = " "
        with self.assertRaises(EDLValidationError):
            validate_edl(payload)
        too_many = [dict(self.valid["clips"][1], id=f"t{i}") for i in range(21)]
        with self.assertRaises(EDLValidationError):
            validate_edl({**self.valid, "clips": too_many})

    def test_does_not_mutate_input(self):
        import copy
        payload = copy.deepcopy(self.valid)
        validate_edl(payload)
        self.assertEqual(payload, self.valid)


    def test_normalizes_bounded_audio_tracks_and_rejects_unsafe_values(self):
        payload = {
            **self.valid,
            "audio_tracks": [{
                "id": "music-1", "asset_id": "asset_audio",
                "start_ms": 0, "source_in_ms": 500, "source_out_ms": 4500,
                "gain": 0.5, "fade_in_ms": 100, "fade_out_ms": 200,
            }],
        }
        result = validate_edl(payload)
        self.assertEqual(result["audio_tracks"][0]["source_in_ms"], 500)
        self.assertEqual(result["audio_tracks"][0]["gain"], 0.5)
        for mutation in (
            {"gain": 9}, {"fade_in_ms": 5000}, {"asset_id": "../outside"},
            {"start_ms": -1}, {"source_out_ms": 500},
        ):
            invalid = {
                **payload,
                "audio_tracks": [{**payload["audio_tracks"][0], **mutation}],
            }
            with self.subTest(mutation=mutation), self.assertRaises(EDLValidationError):
                validate_edl(invalid)

    def test_rejects_too_many_audio_tracks_and_unknown_audio_fields(self):
        track = {
            "id": "music0", "asset_id": "asset_audio",
            "start_ms": 0, "source_in_ms": 0, "source_out_ms": 1000,
        }
        too_many = [{**track, "id": f"music{i}"} for i in range(9)]
        with self.assertRaises(EDLValidationError):
            validate_edl({**self.valid, "audio_tracks": too_many})
        with self.assertRaises(EDLValidationError):
            validate_edl({**self.valid, "audio_tracks": [{**track, "filter": "amovie"}]})


    def test_normalizes_explicit_project_duration_and_bounds_audio(self):
        track = {
            "id": "music0", "asset_id": "asset_audio",
            "start_ms": 0, "source_in_ms": 0, "source_out_ms": 6000,
        }
        payload = {
            **self.valid,
            "project_duration_ms": 8000,
            "audio_tracks": [track],
        }
        result = validate_edl(payload)
        self.assertEqual(result["project_duration_ms"], 8000)
        self.assertEqual(result["audio_tracks"][0]["source_out_ms"], 6000)

        for duration, audio_end in ((4999, 0), (8000, 9000), (3_600_001, 0), (8000.5, 0)):
            invalid = {**payload, "project_duration_ms": duration}
            if audio_end:
                invalid["audio_tracks"] = [{**track, "source_out_ms": audio_end}]
            with self.subTest(duration=duration, audio_end=audio_end), self.assertRaises(EDLValidationError):
                validate_edl(invalid)

    def test_normalizes_adjacent_crossfade_and_rejects_unsafe_transitions(self):
        first = {
            "id": "video-a", "type": "video", "start_ms": 0, "end_ms": 5000,
            "asset_id": "asset_a", "source_in_ms": 0, "source_out_ms": 5000,
        }
        second = {
            "id": "video-b", "type": "video", "start_ms": 4500, "end_ms": 8500,
            "asset_id": "asset_b", "source_in_ms": 1000, "source_out_ms": 5000,
        }
        transition = {
            "from_clip_id": "video-a", "to_clip_id": "video-b",
            "type": "crossfade", "duration_ms": 500,
        }
        payload = {
            "schema": SCHEMA, "version": 1, "timebase": "milliseconds",
            "clips": [first, second], "transitions": [transition],
        }
        normalized = validate_edl(payload)
        self.assertEqual(normalized["transitions"], [transition])

        # Renderer sorts by timeline position; validator must not depend on JSON clip order.
        reordered = validate_edl({**payload, "clips": [second, first]})
        self.assertEqual(reordered["transitions"], [transition])

        invalid_cases = (
            [{**transition, "duration_ms": 5001}],
            [{**transition, "duration_ms": 5000}],
            [{**transition, "type": "wipe"}],
            [{**transition, "to_clip_id": "video-a"}],
            [transition, transition],
            [{**transition, "duration_ms": 500.5}],
        )
        for invalid in invalid_cases:
            with self.subTest(transitions=invalid), self.assertRaises(EDLValidationError):
                validate_edl({**payload, "transitions": invalid})

        with self.assertRaises(EDLValidationError):
            validate_edl({**payload, "transitions": [{**transition, "extra": True}]})

    def test_normalizes_explicit_internal_black_gaps_and_rejects_unsafe_pairs(self):
        first = {
            "id": "video-a", "type": "video", "start_ms": 0, "end_ms": 2000,
            "asset_id": "asset_a", "source_in_ms": 0, "source_out_ms": 2000,
        }
        second = {
            "id": "video-b", "type": "video", "start_ms": 2500, "end_ms": 4500,
            "asset_id": "asset_b", "source_in_ms": 1000, "source_out_ms": 3000,
        }
        gap = {"after_clip_id": "video-a", "before_clip_id": "video-b", "duration_ms": 500}
        payload = {
            "schema": SCHEMA, "version": 1, "timebase": "milliseconds",
            "clips": [first, second], "gaps": [gap], "project_duration_ms": 4500,
        }
        normalized = validate_edl(payload)
        self.assertEqual(normalized["gaps"], [gap])

        invalid_cases = (
            [{**gap, "duration_ms": 99}],
            [{**gap, "duration_ms": 10001}],
            [{**gap, "duration_ms": 500.5}],
            [{**gap, "before_clip_id": "video-a"}],
            [gap, gap],
            [{**gap, "extra": True}],
        )
        for invalid in invalid_cases:
            with self.subTest(gaps=invalid), self.assertRaises(EDLValidationError):
                validate_edl({**payload, "gaps": invalid})

        conflicting = {
            **payload,
            "transitions": [{
                "from_clip_id": "video-a", "to_clip_id": "video-b",
                "type": "crossfade", "duration_ms": 500,
            }],
        }
        with self.assertRaisesRegex(EDLValidationError, "both a crossfade and a black gap"):
            validate_edl(conflicting)

    def test_rejects_title_clip_beyond_project_duration(self):
        title = {
            "id": "title-late", "type": "title", "start_ms": 4500,
            "end_ms": 6000, "text": "Too late",
        }
        with self.assertRaisesRegex(EDLValidationError, "title clip extends"):
            validate_edl({
                **self.valid, "clips": [dict(self.valid["clips"][0]), title],
                "project_duration_ms": 5500,
            })
        # Without an explicit duration, the renderer's duration is the video end.
        with self.assertRaisesRegex(EDLValidationError, "title clip extends"):
            validate_edl({
                **self.valid, "clips": [dict(self.valid["clips"][0]), title],
            })

    def test_rejects_crossfade_interval_that_does_not_match_declared_duration(self):
        first = {
            "id": "video-a", "type": "video", "start_ms": 0, "end_ms": 5000,
            "asset_id": "asset_a", "source_in_ms": 0, "source_out_ms": 5000,
        }
        second = {
            "id": "video-b", "type": "video", "start_ms": 4000, "end_ms": 9000,
            "asset_id": "asset_b", "source_in_ms": 0, "source_out_ms": 5000,
        }
        transition = {
            "from_clip_id": "video-a", "to_clip_id": "video-b",
            "type": "crossfade", "duration_ms": 500,
        }
        base = {
            "schema": SCHEMA, "version": 1, "timebase": "milliseconds",
            "clips": [first, second], "transitions": [transition],
        }
        with self.assertRaisesRegex(EDLValidationError, "match their declared"):
            validate_edl(base)
        # A declared transition cannot silently degrade into a hard cut.
        hard_cut = {**second, "start_ms": 5000, "end_ms": 10000}
        with self.assertRaisesRegex(EDLValidationError, "match their declared"):
            validate_edl({**base, "clips": [first, hard_cut]})

    def test_rejects_black_gap_interval_that_does_not_match_declared_duration(self):
        first = {
            "id": "video-a", "type": "video", "start_ms": 0, "end_ms": 2000,
            "asset_id": "asset_a", "source_in_ms": 0, "source_out_ms": 2000,
        }
        second = {
            "id": "video-b", "type": "video", "start_ms": 2300, "end_ms": 4300,
            "asset_id": "asset_b", "source_in_ms": 0, "source_out_ms": 2000,
        }
        gap = {"after_clip_id": "video-a", "before_clip_id": "video-b", "duration_ms": 500}
        with self.assertRaisesRegex(EDLValidationError, "match their declared"):
            validate_edl({
                "schema": SCHEMA, "version": 1, "timebase": "milliseconds",
                "clips": [first, second], "gaps": [gap],
            })

if __name__ == "__main__":
    unittest.main()
