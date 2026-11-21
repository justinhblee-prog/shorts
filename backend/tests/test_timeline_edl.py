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

    def test_normalizes_explicit_project_duration_and_rejects_short_or_fractional_duration(self):
        payload = {**self.valid, "project_duration_ms": 8000}
        normalized = validate_edl(payload)
        self.assertEqual(normalized["project_duration_ms"], 8000)
        for value in (4999, 8000.5, True, 3_600_001):
            with self.subTest(value=value), self.assertRaises(EDLValidationError):
                validate_edl({**self.valid, "project_duration_ms": value})

    def test_validates_adjacent_bounded_crossfade_transitions(self):
        payload = {
            **self.valid,
            "clips": [
                {"id": "clip-a", "type": "video", "start_ms": 0, "end_ms": 5000,
                 "asset_id": "asset_a", "source_in_ms": 0, "source_out_ms": 5000},
                {"id": "clip-b", "type": "video", "start_ms": 3000, "end_ms": 8000,
                 "asset_id": "asset_b", "source_in_ms": 0, "source_out_ms": 5000},
            ],
            "transitions": [{
                "id": "xfade-ab", "type": "crossfade",
                "from_clip_id": "clip-a", "to_clip_id": "clip-b",
                "duration_ms": 2000,
            }],
        }
        normalized = validate_edl(payload)
        self.assertEqual(normalized["transitions"][0]["duration_ms"], 2000)
        for mutation in (
            {"duration_ms": 1999},
            {"duration_ms": 5001},
            {"type": "wipe"},
            {"to_clip_id": "not-a-clip"},
        ):
            invalid = {**payload, "transitions": [{**payload["transitions"][0], **mutation}]}
            with self.subTest(mutation=mutation), self.assertRaises(EDLValidationError):
                validate_edl(invalid)
        missing = {**payload}
        missing.pop("transitions")
        self.assertNotIn("transitions", validate_edl(missing))

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


if __name__ == "__main__":
    unittest.main()
