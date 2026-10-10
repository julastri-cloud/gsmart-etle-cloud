"""Read-only source-vs-database scope audit for five ETLE modules.
Never logs IDs, names, refs, raw records, URLs, photos, or credentials.
Runs only in a one-time manually created GitHub Actions diagnostic.
"""
import contextlib
import io
import json
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright
import sync_etle as core


def source_counts(page, date_from):
    core.DATE_FROM=date_from
    # The ETLE API may be asynchronous; all writes and notifications are forbidden.
    with contextlib.redirect_stdout(io.StringIO()):
        shipping=core.get_printed_list(page)
        blanko=core.get_blanko_list(page)
        objections=core.get_disputes(page)
        stopped=core.get_terminated(page)
    return {"shipping":shipping,"blanko":blanko,"objections":objections,"stopped":stopped}


def summarize(full,inc,stored,lookback_date):
    db={str(r.get("source_id")):r for r in stored if r.get("source_id")}
    old_total=changed_old=0
    in_full_refs=set()
    for r in full["shipping"]:
        rid=str(r.get("id") or "")
        if rid:in_full_refs.add(rid)
        original=db.get(rid)
        if not original or not original.get("printed_date") or str(original["printed_date"])>=lookback_date:
            continue
        old_total+=1
        incoming=" ".join(str(r.get("status") or "").split()).casefold()
        current=" ".join(str(original.get("status") or "").split()).casefold()
        if incoming!=current:changed_old+=1
    summary={}
    for name in ("shipping","blanko","objections","stopped"):
        full_data=full[name];inc_data=inc[name]
        summary[name]={
          "full_count":len(full_data),
          "incremental_count":len(inc_data),
          "incremental_omits_history":len(full_data)>len(inc_data)
        }
    summary["shipping"]["historical_records_checked"]=old_total
    summary["shipping"]["historical_status_mismatches"]=changed_old
    summary["shipping"]["stored_ids_missing_from_full_source"]=len(set(db)-in_full_refs)
    summary["shipping"]["stored_count"]=len(db)
    return summary


def run():
    core.validate_environment()
    sb=core.create_supabase()
    now=datetime.now(ZoneInfo("Asia/Jakarta")).date()
    lookback=(now-timedelta(days=14)).strftime("%d-%m-%Y")
    from_iso=(now-timedelta(days=14)).isoformat()
    core.SYNC_LIMIT=0
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        try:
            page=browser.new_context(viewport={"width":1920,"height":1080}).new_page()
            with contextlib.redirect_stdout(io.StringIO()):
                core.login_etle(page)
                core.open_blanko_page(page)
            inc=source_counts(page,lookback)
            full=source_counts(page,core.FULL_DATE_FROM)
        finally:
            browser.close()
    db=sb.table("etle_shipping").select("source_id,status,printed_date").range(0,999).execute().data
    if len(db)>=1000:
        raise RuntimeError("SHIPPING_DB_AUDIT_LIMIT")
    safe=summarize(full,inc,db,from_iso)
    print("AUDIT SUMBER ETLE (HANYA AGREGAT):")
    print(json.dumps(safe,sort_keys=True))
    if any(v["full_count"]<v["incremental_count"] for v in safe.values()):
        raise RuntimeError("SOURCE_WINDOW_INCONSISTENCY")


if __name__=="__main__":
    try:run()
    except Exception as exc:
        print("AUDIT SUMBER GAGAL: "+type(exc).__name__)
        raise SystemExit(1)
