import tempfile
import unittest
from pathlib import Path

from brand_operations import BrandStore, BrandNotFound


class BrandOperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "brands.sqlite3")
        self.store = BrandStore(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_seeds_ten_global_brands(self):
        brands = self.store.list()
        self.assertEqual(len(brands), 10)
        self.assertEqual({b["slug"] for b in brands}.__len__(), 10)
        self.assertTrue(all("KR" in b["config"]["regions"] for b in brands))

    def test_activation_persists_and_filters(self):
        updated = self.store.set_active("money-glitch", False)
        self.assertFalse(updated["active"])
        self.assertEqual(len(self.store.list(active_only=True)), 9)
        reloaded = BrandStore(self.db)
        self.assertFalse(reloaded.get("money-glitch")["active"])

    def test_unknown_brand_rejected(self):
        with self.assertRaises(BrandNotFound):
            self.store.set_active("not-a-brand", True)


if __name__ == "__main__":
    unittest.main()
