"""One-time bounded refresh of TERMINATED module only; no WA/FCM/shipping.

Only ETLE read and Supabase stopped status/history writes are performed.
Existing objection evidence, vehicle photos and unrelated sync modules are
not modified. Sensitive case details are never printed to runner logs.
"""
import contextlib
import io
import json
import os

from playwright.sync_api import sync_playwright
from sync_etle import (
    create_supabase, login_etle, open_blanko_page, sync_terminated,
    validate_environment,
)


def run():
    from datetime import datetime
    validate_environment()
    target=os.getenv("VERIFY_TERMINATED_VIOLATION_ID","").strip()
    if not target.isdecimal() or not 1 <= len(target) <= 12:
        raise RuntimeError("INVALID_TARGET_CONFIG")
    supabase=create_supabase()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,
                 args=["--no-sandbox","--disable-setuid-sandbox","--disable-dev-shm-usage"])
        try:
            page=browser.new_context(viewport={"width":1920,"height":1080}).new_page()
            # Suppress all ETLE row/reference logs, and keep errors generic.
            with contextlib.redirect_stdout(io.StringIO()):
                login_etle(page)
                open_blanko_page(page)
                summary=sync_terminated(page,supabase)
        finally:
            browser.close()
    # This read-only verification does not print case ID or offender data.
    rows=(supabase.table("etle_terminated_cases")
          .select("case_id").eq("violation_id",target).limit(1).execute().data)
    result={
      "module":"TERMINATED",
      "source_rows":int(summary["found"]),
      "updated_rows":int(summary["success"]),
      "failed_rows":int(summary["failed"]),
      "target_now_terminated":bool(rows),
    }
    print("BACKFILL DIHENTIKAN (HITUNGAN SAJA):")
    print(json.dumps(result,sort_keys=True))
    if result["failed_rows"] or not result["target_now_terminated"]:
        raise RuntimeError("TERMINATED_BACKFILL_INCOMPLETE")


if __name__=="__main__":
    try:run()
    except Exception as e:
        print("BACKFILL TIDAK TUNTAS: "+type(e).__name__)
        raise SystemExit(1)
