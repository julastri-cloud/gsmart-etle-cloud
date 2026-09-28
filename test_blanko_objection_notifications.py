import unittest
from unittest.mock import patch

import sync_etle


class BlankoObjectionNotificationTests(unittest.TestCase):
    def test_blanko_historical_does_not_notify(self):
        self.assertFalse(sync_etle.is_new_post_baseline_event(True, False, "incremental"))

    def test_blanko_new_notifies_once(self):
        first_run = sync_etle.is_new_post_baseline_event(True, True, "incremental")
        next_run = sync_etle.is_new_post_baseline_event(False, True, "incremental")
        self.assertTrue(first_run)
        self.assertFalse(next_run)

    def test_blanko_same_next_sync_does_not_notify(self):
        self.assertFalse(sync_etle.is_new_post_baseline_event(False, True, "incremental"))

    def test_objection_historical_does_not_notify(self):
        self.assertFalse(sync_etle.is_new_post_baseline_event(True, False, "incremental"))

    def test_objection_new_notifies_once(self):
        first_run = sync_etle.is_new_post_baseline_event(True, True, "incremental")
        next_run = sync_etle.is_new_post_baseline_event(False, True, "incremental")
        self.assertTrue(first_run)
        self.assertFalse(next_run)

    def test_objection_same_next_sync_does_not_notify(self):
        self.assertFalse(sync_etle.is_new_post_baseline_event(False, True, "incremental"))

    def test_full_sync_does_not_notify_historical_events(self):
        self.assertFalse(sync_etle.is_new_post_baseline_event(True, True, "full"))

    def test_firebase_failure_does_not_stop_main_process(self):
        summaries = {
            "blanko": {
                "new_items": [{"case_id": "wa-still-unchanged"}],
                "fcm_new_items": [
                    {"case_id": "case-1", "ref_number": "ref-1", "tnkb": "AB8191ET"}
                ],
            },
            "disputes": {
                "fcm_new_items": [
                    {"case_id": "case-2", "ref_number": "ref-2", "tnkb": "AB8192ET"}
                ],
            },
        }
        with patch.object(sync_etle, "send_event_notification", side_effect=RuntimeError("FCM unavailable")):
            sync_etle.send_sync_fcm_notifications(summaries)

    def test_dispatch_uses_fcm_list_without_changing_wa_list(self):
        summaries = {
            "blanko": {
                "new_items": [{"case_id": "historical-wa-item"}],
                "fcm_new_items": [],
            }
        }
        with patch.object(sync_etle, "send_event_notification") as send:
            sync_etle.send_sync_fcm_notifications(summaries)
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
