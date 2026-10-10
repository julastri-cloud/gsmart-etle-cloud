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


def select_loaded_media(items, kind):
    """Reject icon/placeholder images; source must already be ETLE-allowlisted."""
    if kind not in ("sim","document"):
        raise ValueError("INVALID_MEDIA_KIND")
    for item in (items or []):
        if item.get("kind")!="img" or item.get("loaded") is not True:
            continue
        width, height=int(item.get("width") or 0), int(item.get("height") or 0)
        if width < 260 or height < 120:
            continue
        if not item.get("source"):
            continue
        return item
    return None


def import_case_with_page(page, base, key, violation_id, expected_case_id=None):
    """Use an already authenticated ETLE browser for one verified dispute.

    No personal data appears in the returned summary; all sensitive values
    remain in-memory and are written only to the protected Supabase resources.
    """
    if not ID_RE.fullmatch(str(violation_id or "")):
        raise ValueError("INVALID_VIOLATION_ID")
    case_id=resolve_case(base,key,str(violation_id))
    if expected_case_id is not None and case_id!=expected_case_id:
        raise RuntimeError("CASE_ASSOCIATION_MISMATCH")
    old_rows=db_get(base,key,"gsmart_dispute_evidence_private",{
        "select":"case_id,offender_data,dispute_reason,dispute_explanation,sim_object_path,document_object_path",
        "case_id":"eq."+case_id, "limit":"1",
    })
    old=old_rows[0] if old_rows else {}

    response=page.goto(detail_url(violation_id),wait_until="domcontentloaded",timeout=60000)
    page.wait_for_timeout(2100)
    if (
        not response or response.status!=200
        or "/terkonfirmasi_detail.php" not in page.url
        or "/main/" in page.url
    ):
        raise RuntimeError("DETAIL_NOT_AVAILABLE")
    private=normalize_private_extraction(page.evaluate(EXTRACTION_JS))
    if not private["detail_present"]:
        raise RuntimeError("DETAIL_STRUCTURE_INVALID")

    sim_candidate=select_loaded_media(private["sim_candidates"],"sim")
    doc_candidate=select_loaded_media(private["document_candidates"],"document")
    if not sim_candidate and not doc_candidate and not private["offender"] and not private["reason"] and not private.get("explanation"):
        if not old:
            raise RuntimeError("NO_EVIDENCE_DATA")

    media_errors=0
    extracted={}
    for kind,candidate in (("sim",sim_candidate),("document",doc_candidate)):
        if candidate:
            try:
                data=fetch_evidence(page.context,candidate,kind)
                extracted[kind]=upload_private(base,key,case_id,kind,data)
            except Exception:
                # One unavailable document must not destroy an existing saved
                # SIM or cause other valid evidence to be dropped.
                media_errors+=1

    now=datetime.now(timezone.utc).isoformat()
    record={
        "case_id":case_id,
        "violation_id":str(violation_id),
        "etle_detail_id":str(violation_id),
        "offender_data":{**(old.get("offender_data") or {}),**private["offender"]},
        "dispute_reason":private["reason"] or old.get("dispute_reason"),
        "dispute_explanation":private["explanation"] or old.get("dispute_explanation"),
        "sim_object_path":extracted.get("sim") or old.get("sim_object_path"),
        "document_object_path":extracted.get("document") or old.get("document_object_path"),
        "source_checked_at":now,
        "updated_at":now,
    }
    if not (record["offender_data"] or record["dispute_reason"] or record["dispute_explanation"] or
            record["sim_object_path"] or record["document_object_path"]):
        raise RuntimeError("NO_EVIDENCE_DATA")
    upsert_private(base,key,record)
    return {
        "result":"PARTIAL" if media_errors else "SUCCESS",
        "media_errors":media_errors,
        "field_count":len(record["offender_data"]),
        "reason_present":bool(record["dispute_reason"]),
        "explanation_present":bool(record["dispute_explanation"]),
        "sim_saved_private":bool(record["sim_object_path"]),
        "document_saved_private":bool(record["document_object_path"]),
        "source_case_link_verified":True,
        "photo_vehicle_pipeline_changed":False,
    }


def etle_login(page,email,password):
    page.goto(LOGIN_URL,wait_until="domcontentloaded",timeout=60000)
    page.locator('input[placeholder="Email"]').fill(email,timeout=30000)
    page.locator('input[placeholder="Password"]').fill(password,timeout=30000)
    page.locator('button:has-text("Login")').click(timeout=30000)
    try:
        page.wait_for_load_state("networkidle",timeout=30000)
    except Exception:
        pass
    page.wait_for_timeout(1500)
    if "/main/" in page.url:
        raise RuntimeError("LOGIN_FAILED")


def run(violation_id, confirm):
    from playwright.sync_api import sync_playwright
    if not ID_RE.fullmatch(violation_id or ""):
        raise ValueError("INVALID_VIOLATION_ID")
    if confirm!="YES":
        raise ValueError("IMPORT_REQUIRES_EXPLICIT_YES")
    base=os.getenv("SUPABASE_URL","").strip().rstrip("/")
    key=os.getenv("SUPABASE_SERVICE_ROLE_KEY","").strip()
    email=os.getenv("EMAIL_ETLE","").strip()
    passwd=os.getenv("PASSWORD_ETLE","").strip()
    if not re.fullmatch(r"https://[a-z0-9-]+\.supabase\.co",base) or not all((key,email,passwd)):
        raise RuntimeError("CONFIG_MISSING")
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        try:
            page=browser.new_page(viewport={"width":1365,"height":900})
            etle_login(page,email,passwd)
            summary=import_case_with_page(page,base,key,violation_id)
        finally:
            browser.close()
    print("SINKRONISASI PRIVAT SATU PERKARA:")
    print(json.dumps(summary,sort_keys=True))


if __name__=="__main__":
    try:
        run(os.getenv("VIOLATION_ID",""),os.getenv("SYNC_PRIVATE_CONFIRM",""))
    except Exception as exc:
        # Raw network errors / HTML / authenticated URLs may include private data.
        print("PRIVATE SYNC FAILED: "+type(exc).__name__+"; no sensitive details logged.")
        raise SystemExit(1)
