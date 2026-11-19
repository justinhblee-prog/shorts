import tempfile
import unittest
from pathlib import Path

from run_development_agent import _normalize_approved_scopes


class ApprovedScopeNormalizationTests(unittest.TestCase):
    def test_existing_directories_are_explicit_and_extensionless_files_stay_exact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "backend").mkdir()
            (root / "LICENSE").write_text("license", encoding="utf-8")
            scopes = _normalize_approved_scopes(
                {"github:issue:acme/app#1": ["backend", "LICENSE"]},
                root,
            )
        self.assertEqual(scopes, {"github:issue:acme/app#1": ["backend/", "LICENSE"]})

    def test_nested_directories_are_marked_and_traversal_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "backend" / "tools").mkdir(parents=True)
            scopes = _normalize_approved_scopes(
                {"github:issue:acme/app#2": ["backend/tools", "../outside"]},
                root,
            )
        self.assertEqual(scopes, {"github:issue:acme/app#2": ["backend/tools/", "../outside"]})


if __name__ == "__main__":
    unittest.main()
