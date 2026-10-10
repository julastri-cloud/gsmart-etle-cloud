import os
import json
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright
from supabase import create_client

import sync_etle as core

DRY_RUN = os.getenv("DRY_RUN", "true").strip().lower() == "true"
CONFIRMATION_MISSING_THRESHOLD = max(2, int(os.getenv("CONFIRMATION_MISSING_THRESHOLD", "2")))


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def log(message):
    print(message, flush=True)


def source_shipping_snapshot_is_complete(rows, seen_refs, historical_refs):
    if not rows:
        return False
    min_overlap = max(5, int(len(historical_refs) * 0.7)) if len(historical_refs) >= 10 else 1
    return not historical_refs or len(seen_refs & historical_refs) >= min_overlap


def verify_daya_angkut_confirmations(page, supabase):
    # Hanya membaca daftar Pengiriman Surat. Tidak membuka printed_detail.
    rows = core.get_printed_list(page)
    seen_refs = {
        core.clean(row.get("ref_number"))
        for row in rows
        if core.clean(row.get("ref_number"))
    }

    from_date = core.ddmmyyyy_to_iso(core.DATE_FROM)
    shipping_rows = core.select_all_pages(
        supabase, "etle_shipping", "case_id,ref_number,printed_date"
    )
    shipping_rows = [
        row for row in shipping_rows
        if row.get("case_id")
        and row.get("ref_number")
        and (not row.get("printed_date") or str(row.get("printed_date")) >= from_date)
    ]

    # Safety: absence can only be interpreted when the historical ETLE source
    # returns a sufficiently complete, plausible snapshot. A truncated/empty
    # DataTables response is NOT an official transport confirmation.
    historical_refs = {core.clean(x.get("ref_number")) for x in shipping_rows
                       if core.clean(x.get("ref_number"))}
    if not source_shipping_snapshot_is_complete(rows, seen_refs, historical_refs):
        raise RuntimeError("SOURCE_SHIPPING_SNAPSHOT_INCOMPLETE")

    downstream = set()
    for table in ("etle_disputes", "etle_terminated_cases", "etle_court_info"):
        data = core.select_all_pages(supabase, table, "case_id")
        downstream.update(row.get("case_id") for row in data if row.get("case_id"))

    blanko_rows = core.select_all_pages(
        supabase, "etle_cases", "case_id,no_blanko"
    )
    downstream.update(
        row.get("case_id")
        for row in blanko_rows
        if row.get("case_id") and core.clean(row.get("no_blanko"))
    )

    cases = core.select_all_pages(
        supabase, "etle_cases",
        "case_id,ref_number,tnkb,jenis_pelanggaran,status_etle,is_archived,"
        "missing_full_sync_count,source_missing_since,archived_at"
    )
    case_by_id = {row["case_id"]: row for row in cases if row.get("case_id")}
    case_by_ref = {
        core.clean(row.get("ref_number")): row
        for row in cases
        if core.clean(row.get("ref_number"))
    }

    restored = []
    missing = []
    would_confirm = []
    downstream_cleared = []

    # Jika data yang pernah missing muncul lagi, reset status missing/archive.
    for ref in seen_refs:
        current = case_by_ref.get(ref)
        if not current:
            continue
        if core.clean(current.get("jenis_pelanggaran")).upper() != "DAYA ANGKUT":
            continue
        old_count = int(current.get("missing_full_sync_count") or 0)
        if old_count > 0 or current.get("is_archived"):
            restored.append({
                "tnkb": current.get("tnkb"),
                "ref_number": ref,
                "old_missing_count": old_count,
            })
            if not DRY_RUN:
                core.mark_shipping_source_seen(supabase, current["case_id"])

    # Satu case cukup diperiksa sekali walau etle_shipping punya lebih dari satu row.
    by_case = {}
    for row in shipping_rows:
        by_case[row["case_id"]] = row

    for case_id, shipping in by_case.items():
        ref = core.clean(shipping.get("ref_number"))
        if not ref or ref in seen_refs:
            continue

        current = case_by_id.get(case_id)
        if not current:
            continue
        if core.clean(current.get("jenis_pelanggaran")).upper() != "DAYA ANGKUT":
            continue

        # Sudah pindah tahap, bukan Konfirmasi Daya Angkut Sosialisasi.
        if case_id in downstream:
            old_count = int(current.get("missing_full_sync_count") or 0)
            if old_count > 0 or current.get("is_archived"):
                downstream_cleared.append({
                    "tnkb": current.get("tnkb"),
                    "ref_number": ref,
                    "status_etle": current.get("status_etle"),
                    "old_missing_count": old_count,
                })
                if not DRY_RUN:
                    supabase.table("etle_cases").update({
                        "source_visible": False,
                        "source_missing_since": None,
                        "missing_full_sync_count": 0,
                        "is_archived": False,
                        "archived_at": None,
                        "archive_reason": None,
                    }).eq("case_id", case_id).execute()
            continue

        old_count = int(current.get("missing_full_sync_count") or 0)
        new_count = old_count + 1
        item = {
            "tnkb": current.get("tnkb"),
            "ref_number": ref,
            "old_missing_count": old_count,
            "new_missing_count": new_count,
            "will_confirm": new_count >= CONFIRMATION_MISSING_THRESHOLD,
        }
        missing.append(item)
        if item["will_confirm"]:
            would_confirm.append(item)

        if DRY_RUN:
            continue

        patch = {
            "source_visible": False,
            "source_missing_since": current.get("source_missing_since") or now_iso(),
            "missing_full_sync_count": new_count,
        }

        if new_count >= CONFIRMATION_MISSING_THRESHOLD:
            reason = "Konfirmasi Daya Angkut Sosialisasi"
            patch.update({
                "is_archived": True,
                "archived_at": current.get("archived_at") or now_iso(),
                "archive_reason": reason,
            })

        supabase.table("etle_cases").update(patch).eq("case_id", case_id).execute()

        if new_count >= CONFIRMATION_MISSING_THRESHOLD and not current.get("is_archived"):
            core.add_history_event(
                supabase,
                case_id,
                "SOURCE_ARCHIVED",
                now_iso(),
                "Konfirmasi Daya Angkut Sosialisasi",
                patch["archive_reason"],
                "GSMART_DAYA_ANGKUT",
            )

    result = {
        "dry_run": DRY_RUN,
        "source_shipping_found": len(rows),
        "source_refs": len(seen_refs),
        "historical_shipping_cases_checked": len(by_case),
        "restored": restored,
        "downstream_cleared": downstream_cleared,
        "missing": missing,
        "would_confirm_or_archived": would_confirm,
    }
    return result


def main():
    if not core.EMAIL_ETLE or not core.PASSWORD_ETLE:
        raise RuntimeError("EMAIL_ETLE/PASSWORD_ETLE belum tersedia")
    if not core.SUPABASE_URL or not core.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY belum tersedia")

    # Konfirmasi Daya Angkut Sosialisasi selalu memakai rentang penuh historis G-Smart.
    core.SYNC_MODE = "full"

    supabase = create_client(core.SUPABASE_URL, core.SUPABASE_SERVICE_ROLE_KEY)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = browser.new_page()
        core.login_etle(page)

        try:
            result = verify_daya_angkut_confirmations(page, supabase)
        finally:
            browser.close()

    log("=" * 72)
    log("G-SMART KONFIRMASI DAYA ANGKUT SOSIALISASI SELESAI")
    log("=" * 72)
    # Do not expose TNKB, ETLE reference numbers or personal case metadata
    # in GitHub Actions logs and downloadable artifacts.
    public_summary = {
        key: (len(value) if isinstance(value, list) else value)
        for key, value in result.items()
    }
    log(json.dumps(public_summary, ensure_ascii=False, indent=2))

    with open("daya_angkut_sosialisasi_result.json", "w", encoding="utf-8") as f:
        json.dump(public_summary, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
