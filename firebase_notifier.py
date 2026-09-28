"""Best-effort Firebase Cloud Messaging notifications for G-SMART."""

import argparse
import json
import os
import re


FCM_TOPIC = "gsmart_etle"


def _log(message):
    print(f"[FCM] {message}", flush=True)


def _safe_error(exc):
    """Return a useful error without exposing credential-like values."""
    message = str(exc).replace("\n", " ").replace("\r", " ")
    message = re.sub(r"-----BEGIN [^-]+-----.*?-----END [^-]+-----", "[REDACTED]", message)
    message = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", message)
    message = re.sub(r"(?i)(bearer|token|private_key)\s*[:=]?\s*\S+", r"\1=[REDACTED]", message)
    return f"{type(exc).__name__}: {message[:300]}"


def _get_app():
    import firebase_admin
    from firebase_admin import credentials

    try:
        return firebase_admin.get_app()
    except ValueError:
        raw_credential = os.environ["FIREBASE_SERVICE_ACCOUNT"]
        service_account = json.loads(raw_credential)
        app = firebase_admin.initialize_app(credentials.Certificate(service_account))
        _log("Firebase initialized")
        return app


def send_notification(title, body, data, event_label="NOTIFICATION"):
    """Send one topic notification; never propagate an FCM failure."""
    try:
        from firebase_admin import messaging

        app = _get_app()
        string_data = {str(key): "" if value is None else str(value) for key, value in data.items()}
        _log(f"Sending {event_label} -> {string_data.get('tnkb') or '-'}")
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data=string_data,
            topic=FCM_TOPIC,
        )
        message_id = messaging.send(message, app=app)
        _log("Sent successfully")
        return message_id
    except Exception as exc:
        _log(f"Failed: {_safe_error(exc)}")
        return None


def send_event_notification(event_type, case_id, ref_number, tnkb, no_blanko=None, **_ignored):
    """Build and send one supported G-SMART event notification."""
    event_type = str(event_type or "")
    tnkb_text = str(tnkb or "-")

    if event_type == "SHIPPING_PROCESSED":
        title = "📮 Surat ETLE Diproses"
        body = f"{tnkb_text} • Surat mulai diproses untuk pengiriman"
    elif event_type == "BLANKO_CREATED":
        title = "🧾 Blanko Tilang Terbit"
        blanko_text = str(no_blanko or "-")
        body = f"{tnkb_text} • Blanko {blanko_text} telah diterbitkan"
    elif event_type == "OBJECTION_CREATED":
        title = "⚠️ Pelanggaran Tersanggah"
        body = f"{tnkb_text} • Terdapat pelanggaran yang tersanggah"
    else:
        _log(f"Failed: unsupported event type {event_type!r}")
        return None

    return send_notification(
        title,
        body,
        {
            "event_type": event_type,
            "case_id": case_id,
            "ref_number": ref_number,
            "tnkb": tnkb,
        },
        event_label=event_type,
    )


def send_test_notification():
    return send_notification(
        "🔔 G-SMART FCM Test",
        "Firebase Cloud Messaging berhasil terhubung.",
        {
            "event_type": "FCM_TEST",
            "case_id": "",
            "ref_number": "",
            "tnkb": "",
        },
        event_label="FCM_TEST",
    )


def main():
    parser = argparse.ArgumentParser(description="G-SMART Firebase notification utility")
    parser.add_argument("--test", action="store_true", help="send a test notification")
    args = parser.parse_args()
    if not args.test:
        parser.error("use --test to send a test notification")
    return 0 if send_test_notification() else 1


if __name__ == "__main__":
    raise SystemExit(main())
