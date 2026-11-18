from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class FrontendDevelopmentReviewStateTests(unittest.TestCase):
    def test_review_pending_state_and_exact_pr_evidence_are_visible(self):
        source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('review_pending:"Draft PR 검토 대기"', source)
        self.assertIn('counts.review_pending||0', source)
        self.assertIn('job.review_url', source)
        self.assertIn('job.review_head_sha', source)
        self.assertIn(".development-job-status.review_pending", styles)


if __name__ == "__main__":
    unittest.main()
