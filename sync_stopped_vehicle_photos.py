"""Private vehicle-photo backfill from ETLE stopped-case detail pages.

Read-only ETLE, writes ONLY to gsmart_stopped_vehicle_private and the private
bucket. No changes to etle_photos, existing status/shipping/dispute logic,
G-Smart notifications, or private SIM/document assets.
Logs contain counts only (no PII, URLs or individual case identifiers).
"""
import hashlib
import json
import os
import re
from datetime import datetime,timedelta,timezone
from urllib.parse import urlencode,quote,urlsplit

import requests
from diagnose_terminated_vehicle_photo_safe import build_detail_url,LOGIN_URL
from sync_private_dispute_one import (
    db_get,etle_login,service_headers,detect_file_type,UUID_RE
)

BUCKET="gsmart-stopped-vehicles-private"
MAX_BYTES=10*1024*1024
ID_RE=re.compile(r"^[0-9]{1,12}$")
BASE_RE=re.compile(r"^https://[a-z0-9-]+\.supabase\.co$")
PHOTO_JS=r"""
() => {
 const frame=document.querySelector("#foto_bukti_frame");
 const img=frame?.tagName==="IMG"?frame:frame?.querySelector("img");
 if(!img)return {available:false};
 const src=img.currentSrc||img.src||img.getAttribute("src")||"";
 return {
   available:img.complete&&img.naturalWidth>=800&&img.naturalHeight>=500,
   src, width:img.naturalWidth,height:img.naturalHeight
 };
}
"""

def stopped_source_id(row):
    """ETLE stopped-list id is present even if c.violation_id is NULL."""
    raw=row.get("raw_data") if isinstance(row.get("raw_data"),dict) else {}
    raw_id=str(raw.get("id") or "").strip()
    typed=str(row.get("violation_id") or "").strip()
    if not ID_RE.fullmatch(raw_id):
        return None
    if typed and typed!=raw_id:
        raise RuntimeError("SOURCE_ID_CONFLICT")
    return raw_id

def read_stopped(base,key):
    result=[]
    for offset in range(0,10000,500):
        batch=db_get(base,key,"etle_terminated_cases",{
            "select":"case_id,violation_id,raw_data",
            "limit":"500","offset":str(offset)
        })
        if not isinstance(batch,list):
            raise RuntimeError("STOPPED_LIST_INVALID")
        result.extend(batch)
        if len(batch)<500:break
    if len(result)>=10000:
        raise RuntimeError("STOPPED_LIST_TOO_LARGE")
    return result

def read_previous(base,key):
    state={}
    for offset in range(0,10000,500):
        rows=db_get(base,key,"gsmart_stopped_vehicle_private",{
            "select":"case_id,vehicle_object_path,source_checked_at",
            "limit":"500","offset":str(offset)
        })
        if not isinstance(rows,list):raise RuntimeError("PHOTO_STATE_INVALID")
        for r in rows:
            state[r["case_id"]]=r
        if len(rows)<500:break
    return state

def due(previous,now,empty_hours=24,refresh_hours=24*30):
    if not previous:return True
    timestamp=previous.get("source_checked_at")
    if not timestamp:return True
    try:checked=datetime.fromisoformat(timestamp.replace("Z","+00:00")).astimezone(timezone.utc)
    except (ValueError,TypeError):return True
    hours=refresh_hours if previous.get("vehicle_object_path") else empty_hours
    return now-checked>=timedelta(hours=hours)

def fetch_photo_bytes(page,source):
    """Download ONLY ETLE-origin loaded large photo from exact vehicle selector."""
    if not source.get("available"):
        return None
    url=str(source.get("src") or "")
    if not url or len(url)>4096:return None
    parsed=urlsplit(url)
    if parsed.scheme!="https" or parsed.hostname!="etilang-djpd.kemenhub.go.id" or parsed.port!=9000 or parsed.username or parsed.password:
        raise RuntimeError("UNTRUSTED_PHOTO_ORIGIN")
    res=page.context.request.get(url,timeout=30000,fail_on_status_code=False)
    if res.status!=200:raise RuntimeError("PHOTO_HTTP_FAILED")
    try:reported=int(res.headers.get("content-length","0"))
    except (TypeError,ValueError):reported=0
    if reported>MAX_BYTES:raise RuntimeError("PHOTO_TOO_LARGE")
    data=res.body()
    if not data or len(data)>MAX_BYTES:raise RuntimeError("PHOTO_SIZE_INVALID")
    kind=detect_file_type(data)
    if not kind or kind[0] not in ("jpg","png","webp"):raise RuntimeError("PHOTO_TYPE_INVALID")
    return data,kind[0],kind[1]

def store_photo(base,key,cid,payload):
    data,ext,mime=payload
    digest=hashlib.sha256(data).hexdigest()[:24]
    path=f"{cid}/vehicle/{digest}.{ext}"
    endpoint=base+"/storage/v1/object/"+BUCKET+"/"+"/".join(map(quote,path.split("/")))
    r=requests.post(endpoint,headers={
        **service_headers(key),"Content-Type":mime,"x-upsert":"true"
    },data=data,timeout=60)
    if not r.ok:raise RuntimeError("PRIVATE_PHOTO_UPLOAD_FAILED")
    return path

def save_state(base,key,cid,path,old=None):
    now=datetime.now(timezone.utc).isoformat()
    entry={
        "case_id":cid,
        "vehicle_object_path":path or (old or {}).get("vehicle_object_path"),
        "source_checked_at":now,"updated_at":now
    }
    r=requests.post(base+"/rest/v1/gsmart_stopped_vehicle_private",
        params={"on_conflict":"case_id"},
        headers={**service_headers(key),"Content-Type":"application/json",
                 "Prefer":"resolution=merge-duplicates,return=minimal"},
        data=json.dumps(entry),timeout=30)
    if not r.ok:raise RuntimeError("PHOTO_STATE_WRITE_FAILED")

def sync_one(page,base,key,record,old=None):
    cid=str(record.get("case_id") or "")
    if not UUID_RE.fullmatch(cid):
        raise RuntimeError("INVALID_CASE_ID")
    source_id=stopped_source_id(record)
    if not source_id:
        raise RuntimeError("SOURCE_ID_UNAVAILABLE")
    resp=page.goto(build_detail_url(source_id),wait_until="domcontentloaded",timeout=60000)
    page.wait_for_timeout(2000)
    if not resp or resp.status!=200 or "/dihentikan_detail.php" not in page.url or "/main/" in page.url:
        raise RuntimeError("STOPPED_DETAIL_UNAVAILABLE")
    photo=page.evaluate(PHOTO_JS)
    if not page.locator("#detailPelanggaran").count():
        raise RuntimeError("DETAIL_STRUCTURE_MISSING")
    saved=None
    if photo.get("available"):
        data=fetch_photo_bytes(page,photo)
        if data:saved=store_photo(base,key,cid,data)
    save_state(base,key,cid,saved,old)
    return bool(saved or (old or {}).get("vehicle_object_path"))

def run():
    from playwright.sync_api import sync_playwright
    base=os.getenv("SUPABASE_URL","").strip().rstrip("/")
    key=os.getenv("SUPABASE_SERVICE_ROLE_KEY","").strip()
    email=os.getenv("EMAIL_ETLE","").strip()
    password=os.getenv("PASSWORD_ETLE","").strip()
    if not BASE_RE.fullmatch(base) or not all((key,email,password)):
        raise RuntimeError("CONFIG_MISSING")
    limit=max(1,min(int(os.getenv("STOPPED_PHOTO_MAX_CASES","20")),40))
    records=read_stopped(base,key)
    old_state=read_previous(base,key)
    now=datetime.now(timezone.utc)
    force_recheck=os.getenv("STOPPED_PHOTO_FORCE","false").strip().lower()=="true"
    candidates=[r for r in records
                if r.get("case_id") and (force_recheck or due(old_state.get(r["case_id"]),now))][:limit]
    metrics={"stopped_records":len(records),"already_checked":len(old_state),
             "selected":len(candidates),"photo_available":0,"photo_unavailable":0,"failed":0}
    if candidates:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                page=browser.new_page(viewport={"width":1365,"height":900})
                etle_login(page,email,password)
                for r in candidates:
                    try:
                        got=sync_one(page,base,key,r,old_state.get(r["case_id"]))
                        metrics["photo_available" if got else "photo_unavailable"]+=1
                    except Exception:
                        metrics["failed"]+=1
            finally:browser.close()
    print("ARSIP FOTO KENDARAAN DIHENTIKAN (HANYA JUMLAH):")
    print(json.dumps(metrics,sort_keys=True))
    return metrics

if __name__=="__main__":
    try:run()
    except Exception as e:
        print("SYNC FOTO DIHENTIKAN GAGAL: "+type(e).__name__+" (tanpa data pribadi).")
        raise SystemExit(1)
