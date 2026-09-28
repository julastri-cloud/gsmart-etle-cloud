"""Send the five production shipping lifecycle notifications for manual testing."""

import time

from firebase_notifier import send_event_notification


TEST_EVENTS = (
    "SHIPPING_PRINTED",
    "SHIPPING_IN_TRANSIT",
    "SHIPPING_DELIVERED",
    "SHIPPING_FAILED",
    "SHIPPING_RETURNED",
)

TEST_PAYLOAD = {
    "case_id": "TEST-FCM",
    "ref_number": "TEST-001",
    "tnkb": "TEST1234",
}


def main():
    failed = []
    for index, event_type in enumerate(TEST_EVENTS):
        result = send_event_notification(event_type, **TEST_PAYLOAD)
        if result is None:
            failed.append(event_type)
        if index < len(TEST_EVENTS) - 1:
            time.sleep(2)

    if failed:
        print(f"[FCM] Lifecycle test failed for {len(failed)} event(s).", flush=True)
        return 1

    print("[FCM] Five shipping lifecycle tests sent to topic gsmart_etle.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
