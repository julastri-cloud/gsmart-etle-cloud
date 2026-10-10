"""One-case ETLE dispute private evidence importer.

Manual-only workflow. Requires explicit SYNC_PRIVATE_CONFIRM=YES.
Sensitive documents remain in memory and are uploaded ONLY to the locked
gsmart-dispute-private bucket; values never appear in GitHub logs.
Existing ETLE photos and sync_etle.py remain untouched.
"""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

import requests
from diagnose_dispute_detail_safe import LOGIN_URL, detail_url
from extract_dispute_detail_readonly import (
    EXTRACTION_JS, normalize_private_extraction,
)

BUCKET = "gsmart-dispute-private"
MAX_BYTES = 8 * 1024 * 1024
ID_RE = re.compile(r"^[0-9]{1,12}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)


def detect_file_type(data):
    if data[:3] == bytes.fromhex("ffd8ff"):
        return "jpg", "image/jpeg"
    if data[:8] == bytes.fromhex("89504e470d0a1a0a"):
        return "png", "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    if data[:5] == b"%PDF-":
        return "pdf", "application/pdf"
    return None


def object_path(case_id, kind, data, ext):
    assert UUID_RE.fullmatch(case_id)
    assert kind in ("sim", "document")
    assert ext in ("jpg", "png", "webp", "pdf")
    if kind == "sim" and ext == "pdf":
        raise ValueError("SIM candidate cannot be PDF")
    digest = hashlib.sha256(data).hexdigest()[:24]
    return f"{case_id}/{kind}/{digest}.{ext}"


def service_headers(key):
    return {"apikey": key, "Authorization": "Bearer " + key}


def db_get(base, key, table, params):
    r = requests.get(base + "/rest/v1/" + table,
                     params=params, headers=service_headers(key),timeout=30)
    if not r.ok:
        raise RuntimeError("DATABASE_READ_FAILED")
    return r.json()


def resolve_case(base, key, violation_id):
    cases = db_get(base,key,"etle_cases",{
        "select":"case_id,violation_id",
        "violation_id":"eq."+violation_id,
        "limit":"2",
    })
    if len(cases) != 1:
        raise RuntimeError("CASE_NOT_UNIQUE")
    case_id=cases[0]["case_id"]
    if not UUID_RE.fullmatch(case_id):
        raise RuntimeError("INVALID_CASE_ID")
    disputes = db_get(base,key,"etle_disputes",{
        "select":"case_id",
        "case_id":"eq."+case_id,
        "limit":"1",
    })
    if not disputes:
        raise RuntimeError("CASE_HAS_NO_DISPUTE")
    return case_id


def fetch_evidence(context, candidate, kind):
    # Note: source URL was allowlisted by normalize_private_extraction.
    if not candidate or not candidate.get("source"):
        return None
    url=candidate["source"]
    p=urlsplit(url)
    if p.scheme!="https" or p.hostname!="etilang-djpd.kemenhub.go.id" or p.port!=9000:
        raise RuntimeError("UNSAFE_MEDIA_ORIGIN")
    response=context.request.get(url,timeout=30000,fail_on_status_code=False)
    if response.status != 200:
        raise RuntimeError("EVIDENCE_HTTP_FAILED")
    try:
        reported_size=int(response.headers.get("content-length","0"))
    except (TypeError,ValueError):
        reported_size=0
    if reported_size>MAX_BYTES:
        raise RuntimeError("EVIDENCE_SIZE_INVALID")
    data=response.body()
    if not data or len(data)>MAX_BYTES:
        raise RuntimeError("EVIDENCE_SIZE_INVALID")
    recognized=detect_file_type(data)
    if not recognized:
        raise RuntimeError("EVIDENCE_FORMAT_UNKNOWN")
    ext,mime=recognized
    if kind=="sim" and mime=="application/pdf":
        raise RuntimeError("UNEXPECTED_SIM_FORMAT")
    return data,ext,mime


def upload_private(base,key,case_id,kind,evidence):
    if not evidence:
        return None
    data,ext,mime=evidence
    path=object_path(case_id,kind,data,ext)
    url=base+"/storage/v1/object/"+BUCKET+"/"+"/".join(map(quote,path.split("/")))
    resp=requests.post(url,headers={
        **service_headers(key),
        "Content-Type":mime,
        "x-upsert":"true"
    },data=data,timeout=60)
    if not resp.ok:
        raise RuntimeError("PRIVATE_STORAGE_WRITE_FAILED")
    return path


def upsert_private(base,key,record):
    r=requests.post(base+"/rest/v1/gsmart_dispute_evidence_private",
        params={"on_conflict":"case_id"},
        headers={
            **service_headers(key),
            "Content-Type":"application/json",
            "Prefer":"resolution=merge-duplicates,return=minimal",
        },
        data=json.dumps(record),
        timeout=30)
    if not r.ok:
        raise RuntimeError("PRIVATE_METADATA_WRITE_FAILED")


def run(violation_id, confirm):
    from playwright.sync_api import sync_playwright
    if not ID_RE.fullmatch(violation_id or ""):
        raise ValueError("INVALID_VIOLATION_ID")
    if confirm != "YES":
        raise ValueError("IMPORT_REQUIRES_EXPLICIT_YES")
    base=os.getenv("SUPABASE_URL","").strip().rstrip("/")
    key=os.getenv("SUPABASE_SERVICE_ROLE_KEY","").strip()
    email=os.getenv("EMAIL_ETLE","").strip()
    passwd=os.getenv("PASSWORD_ETLE","").strip()
    if not re.fullmatch(r"https://[a-z0-9-]+\.supabase\.co",base) or not all((key,email,passwd)):
        raise RuntimeError("CONFIG_MISSING")
    case_id=resolve_case(base,key,violation_id)
    existing=db_get(base,key,"gsmart_dispute_evidence_private",{
        "select":"case_id,offender_data,dispute_reason,sim_object_path,document_object_path",
        "case_id":"eq."+case_id,"limit":"1",
    })
    old=existing[0] if existing else {}

    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        try:
            page=browser.new_page(viewport={"width":1365,"height":900})
            page.goto(LOGIN_URL,wait_until="domcontentloaded",timeout=60000)
            page.locator('input[placeholder="Email"]').fill(email,timeout=30000)
            page.locator('input[placeholder="Password"]').fill(passwd,timeout=30000)
            page.locator('button:has-text("Login")').click(timeout=30000)
            try: page.wait_for_load_state("networkidle",timeout=30000)
            except Exception: pass
            page.wait_for_timeout(1500)
            if "/main/" in page.url: raise RuntimeError("LOGIN_FAILED")
            response=page.goto(detail_url(violation_id),wait_until="domcontentloaded",timeout=60000)
            page.wait_for_timeout(2500)
            if not response or response.status!=200 or "/terkonfirmasi_detail.php" not in page.url:
                raise RuntimeError("DETAIL_NOT_FOUND")
            private=normalize_private_extraction(page.evaluate(EXTRACTION_JS))
            if not private["detail_present"]:
                raise RuntimeError("DETAIL_STRUCTURE_INVALID")
            sim_candidate=next((x for x in private["sim_candidates"] if x["loaded"] is True),None)
            doc_candidate=next((x for x in private["document_candidates"] if x["loaded"] is True),None)
            if not sim_candidate and not doc_candidate and not private["offender"]:
                raise RuntimeError("NO_EVIDENCE_DATA")
            sim_bytes=fetch_evidence(page.context,sim_candidate,"sim") if sim_candidate else None
            doc_bytes=fetch_evidence(page.context,doc_candidate,"document") if doc_candidate else None
        finally:
            browser.close()

    # Upload only after confirmed row association with an existing dispute case.
    sim_path=upload_private(base,key,case_id,"sim",sim_bytes) if sim_bytes else None
    doc_path=upload_private(base,key,case_id,"document",doc_bytes) if doc_bytes else None
    record={
        "case_id":case_id,
        "violation_id":violation_id,
        "etle_detail_id":violation_id,
        "offender_data":{**(old.get("offender_data") or {}),**private["offender"]},
        "dispute_reason":private["reason"] or old.get("dispute_reason"),
        "sim_object_path":sim_path or old.get("sim_object_path"),
        "document_object_path":doc_path or old.get("document_object_path"),
        "source_checked_at":datetime.now(timezone.utc).isoformat(),
        "updated_at":datetime.now(timezone.utc).isoformat(),
    }
    upsert_private(base,key,record)
    # No PII, URLs, object paths or even source case IDs are printed.
    print("SINKRONISASI PRIVAT SATU PERKARA:")
    print(json.dumps({
        "result":"SUCCESS",
        "field_count":len(record["offender_data"]),
        "reason_present":bool(record["dispute_reason"]),
        "sim_saved_private":bool(record["sim_object_path"]),
        "document_saved_private":bool(record["document_object_path"]),
        "source_case_link_verified":True,
        "photo_vehicle_pipeline_changed":False
    },sort_keys=True))


if __name__=="__main__":
    try:
        run(os.getenv("VIOLATION_ID",""),os.getenv("SYNC_PRIVATE_CONFIRM",""))
    except Exception as exc:
        # Raw network errors / HTML / authenticated URLs may include private data.
        print("PRIVATE SYNC FAILED: "+type(exc).__name__+"; no sensitive details logged.")
        raise SystemExit(1)
