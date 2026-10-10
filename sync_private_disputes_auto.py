"""Safe, additive, automatic ETLE dispute evidence sync.

Works for both currently-active and previously-terminated disputes because
selection is from etle_disputes history, never only from active statuses.
Writes only gsmart_dispute_evidence_private + gsmart-dispute-private bucket.
Does not modify normal ETLE sync, etle_photos, notifications or case statuses.
No personal values, violation IDs, media URLs or paths are printed.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

from sync_private_dispute_one import (
    ID_RE, UUID_RE, db_get, etle_login, import_case_with_page,
)

HOST_RE=re.compile(r"^https://[a-z0-9-]+\.supabase\.co$")
MAX_DISCOVERY=10000
PAGE_SIZE=500


def utc_time(value):
    if not isinstance(value,str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z","+00:00")).astimezone(timezone.utc)
    except (ValueError,TypeError):
        return None


def eligible(dispute, archive, now, missing_hours=24, full_hours=168, force_missing_text=False):
    """Backfill missing cases ASAP; recheck incompletes daily and full weekly."""
    case_id=str(dispute.get("case_id") or "")
    violation_id=str(dispute.get("violation_id") or "")
    if not UUID_RE.fullmatch(case_id) or not ID_RE.fullmatch(violation_id):
        return False
    if not archive:
        return True
    if force_missing_text and (not archive.get("dispute_reason") or not archive.get("dispute_explanation")):
        return True
    checked=utc_time(archive.get("source_checked_at"))
    if not checked:
        return True
    has_sim=bool(archive.get("sim_object_path"))
    has_doc=bool(archive.get("document_object_path"))
    has_offender=bool(archive.get("offender_data"))
    has_reason=bool(archive.get("dispute_reason"))
    has_explanation=bool(archive.get("dispute_explanation"))
    is_incomplete=not (has_sim and has_doc and has_offender and has_reason and has_explanation)
    hours=missing_hours if is_incomplete else full_hours
    return (now-checked)>=timedelta(hours=hours)


def list_disputes(base,key):
    results=[]
    for offset in range(0,MAX_DISCOVERY,PAGE_SIZE):
        page=db_get(base,key,"etle_disputes",{
            "select":"case_id,violation_id,confirmation_date",
            "order":"confirmation_date.desc.nullslast",
            "limit":str(PAGE_SIZE),
            "offset":str(offset),
        })
        if not isinstance(page,list):
            raise RuntimeError("DISPUTE_LIST_INVALID")
        results.extend(page)
        if len(page)<PAGE_SIZE:
            break
    if len(results)==MAX_DISCOVERY:
        raise RuntimeError("DISPUTE_LIST_TOO_LARGE")
    return results


def list_private_state(base,key):
    """Retrieve only non-sensitive completeness metadata; no offender fields."""
    result={}
    for offset in range(0,MAX_DISCOVERY,PAGE_SIZE):
        page=db_get(base,key,"gsmart_dispute_evidence_private",{
            "select":"case_id,sim_object_path,document_object_path,source_checked_at,dispute_reason,dispute_explanation,offender_data",
            "limit":str(PAGE_SIZE),"offset":str(offset),
        })
        if not isinstance(page,list):
            raise RuntimeError("PRIVATE_STATE_INVALID")
        for row in page:
            if UUID_RE.fullmatch(str(row.get("case_id") or "")):
                # Only retain fixed booleans. The source values are never logged.
                result[row["case_id"]]={
                    "source_checked_at":row.get("source_checked_at"),
                    "sim_object_path":bool(row.get("sim_object_path")),
                    "document_object_path":bool(row.get("document_object_path")),
                    "dispute_reason":bool(row.get("dispute_reason")),
                    "dispute_explanation":bool(row.get("dispute_explanation")),
                    "offender_data":bool(row.get("offender_data")),
                }
        if len(page)<PAGE_SIZE:
            break
    return result


def select_batch(disputes,archive,now,limit,missing_hours=24,full_hours=168,force_missing_text=False):
    # No removal from etle_disputes when a case is terminated. Backfills five
    # historical stopped cases just like two active ones, anchored to case_id.
    seen=set()
    selected=[]
    for d in disputes:
        cid=d.get("case_id")
        if cid in seen:continue
        seen.add(cid)
        if eligible(d,archive.get(cid),now,missing_hours,full_hours,force_missing_text):
            selected.append(d)
    return selected[:limit]


def run():
    from playwright.sync_api import sync_playwright
    base=os.getenv("SUPABASE_URL","").strip().rstrip("/")
    key=os.getenv("SUPABASE_SERVICE_ROLE_KEY","").strip()
    email=os.getenv("EMAIL_ETLE","").strip()
    passwd=os.getenv("PASSWORD_ETLE","").strip()
    if not HOST_RE.fullmatch(base) or not all((key,email,passwd)):
        raise RuntimeError("CONFIG_MISSING")
    limit=max(1,min(int(os.getenv("AUTO_PRIVATE_MAX_CASES","12")),30))
    missing_hours=max(1,min(int(os.getenv("AUTO_PRIVATE_MISSING_RECHECK_HOURS","24")),720))
    full_hours=max(24,min(int(os.getenv("AUTO_PRIVATE_FULL_RECHECK_HOURS","168")),2160))
    disputes=list_disputes(base,key)
    state=list_private_state(base,key)
    force_text=os.getenv("AUTO_PRIVATE_FORCE_TEXT_BACKFILL","").strip().lower()=="true"
    pending=select_batch(disputes,state,datetime.now(timezone.utc),limit,missing_hours,full_hours,force_text)
    counters={
        "all_historical_disputes":len(disputes),
        "previously_imported":len(state),
        "selected":len(pending),
        "successful":0,
        "partial":0,
        "failed":0,
        "sim_saved":0,
        "document_saved":0,
        "reason_available":0,
        "explanation_available":0,
    }
    if pending:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                page=browser.new_page(viewport={"width":1365,"height":900})
                etle_login(page,email,passwd)
                for d in pending:
                    try:
                        result=import_case_with_page(
                            page,base,key,str(d["violation_id"]),
                            expected_case_id=str(d["case_id"])
                        )
                        status="partial" if result.get("result")=="PARTIAL" else "successful"
                        counters[status]+=1
                        counters["sim_saved"]+=int(result["sim_saved_private"])
                        counters["document_saved"]+=int(result["document_saved_private"])
                        counters["reason_available"]+=int(result["reason_present"])
                        counters["explanation_available"]+=int(result["explanation_present"])
                    except Exception:
                        # No exception content: request errors can contain tokens,
                        # authenticated URLs or DOM/identity data.
                        counters["failed"]+=1
            finally:
                browser.close()
    print("G-SMART PRIVAT OTOMATIS (HANYA HITUNGAN):")
    print(json.dumps(counters,sort_keys=True))
    if counters["failed"] or counters["partial"]:
        print("WARNING: Ada perkara dengan bukti yang belum lengkap. Perkara lain tetap diproses.")
    # This is a best-effort dependent job. Existing sync / FCM / WhatsApp is
    # unaffected by unavailable historic detail pages or unsupported media.
    return counters


if __name__=="__main__":
    try:
        run()
    except Exception as exc:
        print("PRIVATE AUTO SYNC FAILED: "+type(exc).__name__+" (tanpa identitas/URL).")
        raise SystemExit(1)
