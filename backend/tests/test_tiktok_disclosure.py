import unittest

from tiktok_disclosure import build_tiktok_disclosure, TikTokDisclosureError


class TikTokDisclosureTests(unittest.TestCase):
    def test_ai_generated_and_realistic_alteration_enable_label(self):
        self.assertEqual(build_tiktok_disclosure("ai_generated"), {"is_aigc": True})
        self.assertEqual(build_tiktok_disclosure("realistic_alteration"), {"is_aigc": True})

    def test_non_ai_and_nonrealistic_assistance_do_not_enable_label(self):
        self.assertEqual(build_tiktok_disclosure("none"), {"is_aigc": False})
        self.assertEqual(
            build_tiktok_disclosure("ai_assisted_nonrealistic"), {"is_aigc": False}
        )

    def test_unknown_or_invalid_status_fails_closed(self):
        for value in ("unknown", "maybe", None):
            with self.subTest(value=value):
                with self.assertRaises(TikTokDisclosureError):
                    build_tiktok_disclosure(value)


if __name__ == "__main__":
    unittest.main()
