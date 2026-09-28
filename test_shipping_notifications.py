import unittest
from unittest.mock import patch

import sync_etle


NO_INFO = {
    "tracking_number": None,
    "status": None,
    "status_description": None,
    "courier": None,
}
WITH_INFO = {
    "tracking_number": "JNE123",
    "status": "Diproses",
    "status_description": "Diterima JNE",
    "courier": "JNE",
}


class ShippingNotificationTests(unittest.TestCase):
    def test_historical_first_read_does_not_notify(self):
        self.assertFalse(sync_etle.is_new_shipping_event([], WITH_INFO, False, "incremental"))

    def test_existing_record_transition_notifies(self):
        self.assertTrue(sync_etle.is_new_shipping_event([NO_INFO], WITH_INFO, True, "incremental"))

    def test_new_record_after_baseline_notifies(self):
        self.assertTrue(sync_etle.is_new_shipping_event([], WITH_INFO, True, "incremental"))

    def test_same_record_next_sync_does_not_notify(self):
        self.assertFalse(sync_etle.is_new_shipping_event([WITH_INFO], WITH_INFO, True, "incremental"))

    def test_full_sync_never_notifies_shipping(self):
        self.assertFalse(sync_etle.is_new_shipping_event([], WITH_INFO, True, "full"))
        self.assertFalse(sync_etle.is_new_shipping_event([NO_INFO], WITH_INFO, True, "full"))

    def test_firebase_failure_does_not_escape_dispatch(self):
        summaries = {
            "shipping": {
                "new_items": [{"case_id": "case-1", "ref_number": "ref-1", "tnkb": "AB8191ET"}]
            }
        }
        with patch.object(sync_etle, "send_event_notification", side_effect=RuntimeError("FCM unavailable")):
            sync_etle.send_sync_fcm_notifications(summaries)

    def test_normal_workflow_retry_does_not_repeat_event(self):
        first_run = sync_etle.is_new_shipping_event([], WITH_INFO, True, "incremental")
        retry_after_upsert = sync_etle.is_new_shipping_event([WITH_INFO], WITH_INFO, True, "incremental")
        self.assertTrue(first_run)
        self.assertFalse(retry_after_upsert)


if __name__ == "__main__":
    unittest.main()
