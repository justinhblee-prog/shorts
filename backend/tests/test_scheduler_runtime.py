import unittest

from scheduler import poll_tiktok_status_if_leader


class SchedulerLeadershipPollTests(unittest.TestCase):
    class LeaseStore:
        def __init__(self, renew=True, valid=True):
            self.renew = renew
            self.valid = valid
            self.calls = []
        def renew_scheduler_lease(self, owner_id, token, lease_seconds=90):
            self.calls.append(("renew", owner_id, token, lease_seconds))
            return self.renew
        def scheduler_lease_is_valid(self, owner_id, token):
            self.calls.append(("valid", owner_id, token))
            return self.valid

    class Publisher:
        def __init__(self):
            self.calls = 0
        def refresh_due_statuses(self, **kwargs):
            self.calls += 1
            return {"skipped": False, "checked": 2, "updated": 1, "errors": []}

    def test_lost_lease_prevents_tiktok_api_poll(self):
        store = self.LeaseStore(renew=False)
        publisher = self.Publisher()
        result = poll_tiktok_status_if_leader(
            store, publisher, "scheduler-a", "lease-a", True
        )
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "scheduler_lease_lost")
        self.assertEqual(publisher.calls, 0)
        self.assertEqual([call[0] for call in store.calls], ["renew"])

    def test_poll_is_bracketed_by_lease_renewal_and_validation(self):
        store = self.LeaseStore(renew=True, valid=True)
        publisher = self.Publisher()
        result = poll_tiktok_status_if_leader(
            store, publisher, "scheduler-a", "lease-a", True, lease_seconds=120
        )
        self.assertEqual(result["checked"], 2)
        self.assertEqual(publisher.calls, 1)
        self.assertEqual([call[0] for call in store.calls], ["renew", "valid"])
        self.assertEqual(store.calls[0][3], 120)

    def test_lease_loss_during_poll_is_reported_to_scheduler_loop(self):
        store = self.LeaseStore(renew=True, valid=False)
        publisher = self.Publisher()
        result = poll_tiktok_status_if_leader(
            store, publisher, "scheduler-a", "lease-a", True
        )
        self.assertTrue(result["lease_lost"])
        self.assertEqual(publisher.calls, 1)

    def test_disconnected_tiktok_skips_without_touching_scheduler_lease(self):
        store = self.LeaseStore()
        publisher = self.Publisher()
        result = poll_tiktok_status_if_leader(
            store, publisher, "scheduler-a", "lease-a", False
        )
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "tiktok_not_connected")
        self.assertEqual(store.calls, [])
        self.assertEqual(publisher.calls, 0)


if __name__ == "__main__":
    unittest.main()
