import os
import hmac
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request

import sync_etle


app = Flask(__name__)

WIB = ZoneInfo("Asia/Jakarta")

SYNC_TRIGGER_TOKEN = os.getenv(
    "SYNC_TRIGGER_TOKEN",
    ""
).strip()

sync_lock = threading.Lock()

sync_status = {
    "running": False,
    "last_start": None,
    "last_finish": None,
    "last_result": None,
    "last_error": None,
}


def now_wib():
    return datetime.now(WIB).isoformat()


def run_sync_background():
    if not sync_lock.acquire(blocking=False):
        return

    try:
        sync_status["running"] = True
        sync_status["last_start"] = now_wib()
        sync_status["last_result"] = None
        sync_status["last_error"] = None

        print(
            "[RENDER] Memulai sinkronisasi ETLE...",
            flush=True
        )

        sync_etle.main()

        sync_status["last_result"] = "BERHASIL"

        print(
            "[RENDER] Sinkronisasi selesai.",
            flush=True
        )

    except Exception as error:
        sync_status["last_result"] = "GAGAL"
        sync_status["last_error"] = str(error)

        print(
            f"[RENDER] ERROR: {error}",
            flush=True
        )

    finally:
        sync_status["running"] = False
        sync_status["last_finish"] = now_wib()

        sync_lock.release()


def token_valid():
    if not SYNC_TRIGGER_TOKEN:
        return False

    supplied_token = (
        request.headers.get("X-Sync-Token")
        or request.args.get("token")
        or ""
    )

    return hmac.compare_digest(
        supplied_token,
        SYNC_TRIGGER_TOKEN
    )


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "service": "G-SMART ETLE Sync",
        "status": "online",
        "sync_running": sync_status["running"]
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "time": now_wib()
    })


@app.route("/status", methods=["GET"])
def status():
    return jsonify(sync_status)


@app.route("/sync", methods=["GET", "POST"])
def sync():
    if not token_valid():
        return jsonify({
            "success": False,
            "message": "Unauthorized"
        }), 401

    if sync_status["running"]:
        return jsonify({
            "success": False,
            "message": "Sinkronisasi masih berjalan.",
            "status": sync_status
        }), 409

    thread = threading.Thread(
        target=run_sync_background,
        daemon=True
    )

    thread.start()

    return jsonify({
        "success": True,
        "message": "Sinkronisasi ETLE dimulai.",
        "time": now_wib()
    }), 202


if __name__ == "__main__":
    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )