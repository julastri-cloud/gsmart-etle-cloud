import unittest
from unittest.mock import patch

import firebase_notifier
import sync_etle


def row(status=None, tracking=None, description=None, courier=None):
    return {
        "status": status,
        "tracking_number": tracking,
        "status_description": description,
        "courier": courier,
    }


class ShippingLifecycleTests(unittest.TestCase):
    def event(self, old, new, baseline=True, mode="incremental"):
        existing = [] if old is None else [old]
        return sync_etle.select_shipping_notification(existing, new, baseline, mode)

    def test_historical_before_baseline_has_no_notification(self):
        self.assertIsNone(self.event(None, row("Tercetak"), baseline=False))

    def test_new_printed_record(self):
        self.assertEqual(self.event(None, row("Tercetak")), "SHIPPING_PRINTED")

    def test_printed_to_in_transit(self):
        self.assertEqual(
            self.event(row("Tercetak"), row("Dalam Proses Pengiriman")),
            "SHIPPING_IN_TRANSIT",
        )

    def test_in_transit_to_delivered(self):
        self.assertEqual(
            self.event(row("Dalam Proses Pengiriman"), row("Terkirim")),
            "SHIPPING_DELIVERED",
        )

    def test_in_transit_to_failed(self):
        self.assertEqual(
            self.event(row("Dalam Proses Pengiriman"), row("Gagal Kirim")),
            "SHIPPING_FAILED",
        )

    def test_failed_to_returned(self):
        self.assertEqual(
            self.event(row("Gagal Kirim"), row("Dikembalikan")),
            "SHIPPING_RETURNED",
        )

    def test_description_only_change_has_no_notification(self):
        self.assertIsNone(
            self.event(
                row("Dalam Proses Pengiriman", description="WAREHOUSE A"),
                row("Dalam Proses Pengiriman", description="WAREHOUSE B"),
            )
        )

    def test_milestone_with_tracking_selects_only_lifecycle(self):
        event_type = self.event(None, row("Tercetak", tracking="JNE123", courier="JNE"))
        self.assertEqual(event_type, "SHIPPING_PRINTED")
        summaries = {
            "shipping": {
                "new_items": [{
                    "event_type": event_type,
                    "case_id": "case-1",
                    "ref_number": "ref-1",
                    "tnkb": "AB8191ET",
                }]
            }
        }
        with patch.object(sync_etle, "send_event_notification") as send:
            sync_etle.send_sync_fcm_notifications(summaries)
        send.assert_called_once_with(
            "SHIPPING_PRINTED",
            case_id="case-1",
            ref_number="ref-1",
            tnkb="AB8191ET",
        )

    def test_unknown_status_with_new_shipping_info_uses_processed_fallback(self):
        self.assertEqual(
            self.event(None, row("Status Provider Baru", tracking="JNE123", courier="JNE")),
            "SHIPPING_PROCESSED",
        )

    def test_same_status_next_sync_has_no_notification(self):
        self.assertIsNone(self.event(row("Terkirim"), row("Terkirim")))

    def test_full_sync_has_no_notification(self):
        self.assertIsNone(
            self.event(row("Tercetak"), row("Terkirim"), mode="full")
        )

    def test_firebase_failure_does_not_escape_dispatch(self):
        summaries = {
            "shipping": {
                "new_items": [{
                    "event_type": "SHIPPING_DELIVERED",
                    "case_id": "case-1",
                    "ref_number": "ref-1",
                    "tnkb": "AB8191ET",
                }]
            }
        }
        with patch.object(sync_etle, "send_event_notification", side_effect=RuntimeError("offline")):
            sync_etle.send_sync_fcm_notifications(summaries)

    def test_case_and_whitespace_variations_do_not_duplicate(self):
        self.assertIsNone(
            self.event(row("  Dalam Proses Pengiriman "), row("DALAM  PROSES PENGIRIMAN"))
        )

    def test_notifier_supports_all_lifecycle_events(self):
        events = {
            "SHIPPING_PRINTED",
            "SHIPPING_IN_TRANSIT",
            "SHIPPING_DELIVERED",
            "SHIPPING_FAILED",
            "SHIPPING_RETURNED",
        }
        with patch.object(firebase_notifier, "send_notification", return_value="message-id") as send:
            for event_type in events:
                self.assertEqual(
                    firebase_notifier.send_event_notification(event_type, "case", "ref", "AB8191ET"),
                    "message-id",
                )
        self.assertEqual(send.call_count, len(events))


if __name__ == "__main__":
    unittest.main()
