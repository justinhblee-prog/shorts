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

    def test_rejects_title_control_characters_but_allows_line_breaks(self):
        for value in ("unsafe\\x00text", "unsafe\\x7ftext"):
            payload = {**self.valid, "clips": [dict(x) for x in self.valid["clips"]]}
            payload["clips"][1]["text"] = value
            with self.subTest(value=repr(value)), self.assertRaises(EDLValidationError):
                validate_edl(payload)
        payload = {**self.valid, "clips": [dict(x) for x in self.valid["clips"]]}
        payload["clips"][1]["text"] = "Line one\\nLine two"
        self.assertEqual(validate_edl(payload)["clips"][1]["text"], "Line one\\nLine two")

    def test_does_not_mutate_input(self):
        import copy
        payload = copy.deepcopy(self.valid)
        validate_edl(payload)
        self.assertEqual(payload, self.valid)


if __name__ == "__main__":
    unittest.main()
