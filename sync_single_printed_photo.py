import os
import re
import json
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright
from supabase import create_client

BASE = "https://etilang-djpd.kemenhub.go.id:9000"
URL_LOGIN = BASE + "/main/"

EMAIL_ETLE = os.getenv("EMAIL_ETLE", "").strip()
PASSWORD_ETLE = os.getenv("PASSWORD_ETLE", "").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

TARGET_TNKB = re.sub(r"\s+", "", os.getenv("TARGET_TNKB", "AE8768SK").upper())
DETAIL_NO = os.getenv("DETAIL_NO", "347586").strip()
DETAIL_TIME = os.getenv("DETAIL_TIME", "2026-09-12 14:17:23").strip()
DETAIL_TYPE = os.getenv("DETAIL_TYPE", "DOKUMEN").strip()
DRY_RUN = os.getenv("DRY_RUN", "true").strip().lower() == "true"

def log(msg):
    print(msg, flush=True)

def norm(v):
    return re.sub(r"\s+", "", str(v or "").upper())

def login(page):
    page.goto(URL_LOGIN, wait_until="domcontentloaded", timeout=60000)
    page.locator('input[placeholder="Email"]').wait_for(state="visible", timeout=30000)
    page.locator('input[placeholder="Email"]').fill(EMAIL_ETLE)
    page.locator('input[placeholder="Password"]').fill(PASSWORD_ETLE)
    page.locator('button:has-text("Login")').click()
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    page.wait_for_timeout(1200)
    if "/main/" in page.url:
        raise RuntimeError("Login ETLE gagal")

def detail_url():
    return BASE + "/admin-etle/printed_detail.php?" + urlencode({
        "id": TARGET_TNKB,
        "no": DETAIL_NO,
        "time": DETAIL_TIME,
        "type": DETAIL_TYPE,
    })

def extract_detail(page):
    image_responses = []

    def on_response(response):
        try:
            ctype = (response.headers.get("content-type") or "").lower()
            if ctype.startswith("image/"):
                image_responses.append({
                    "url": response.url,
                    "status": response.status,
                    "content_type": ctype,
                })
        except Exception:
            pass

    page.on("response", on_response)
    url = detail_url()
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    page.wait_for_timeout(1800)

    body_text = page.locator("body").inner_text()

    images = page.evaluate("""() => Array.from(document.images).map(img => ({
      src: img.currentSrc || img.src || "",
      width: img.naturalWidth || img.width || 0,
      height: img.naturalHeight || img.height || 0,
      alt: img.alt || ""
    }))""")

    candidates = []
    for img in images:
        src = img.get("src") or ""
        if not src:
            continue
        if img.get("width", 0) >= 800 or img.get("height", 0) >= 600:
            candidates.append(img)

    if not candidates:
        for r in image_responses:
            u = r.get("url") or ""
            if r.get("status") == 200 and re.search(r"\.(png|jpg|jpeg|webp)(\?|$)", u, re.I):
                if "loading.svg" not in u and "dharma" not in u.lower():
                    candidates.append({"src": u, "width": 0, "height": 0, "alt": ""})

    if not candidates:
        raise RuntimeError("Foto kendaraan tidak ditemukan pada halaman detail.")

    # Pilih gambar terbesar bila dimensi tersedia.
    candidates.sort(key=lambda x: (x.get("width", 0) * x.get("height", 0)), reverse=True)
    photo_url = candidates[0]["src"]

    ref_match = re.search(r"Nomor\s*Registrasi\s*:?\s*([A-Z0-9-]+)", body_text, re.I)
    tnkb_match = re.search(r"TNKB\s*:?\s*([A-Z]{1,2}\s*\d{1,4}\s*[A-Z]{0,3})", body_text, re.I)

    return {
        "detail_url": page.url,
        "photo_url": photo_url,
        "ref_number": ref_match.group(1).strip() if ref_match else None,
        "tnkb_text": tnkb_match.group(1).strip() if tnkb_match else None,
        "body_preview": re.sub(r"\s+", " ", body_text)[:1200],
    }

def resolve_case(supabase, detail):
    ref = detail.get("ref_number")
    if ref:
        rows = (
            supabase.table("etle_cases")
            .select("case_id,violation_id,ref_number,tnkb,tanggal_pelanggaran,jenis_pelanggaran")
            .eq("ref_number", ref)
            .limit(5)
            .execute()
            .data
        )
        if rows:
            return rows[0], "ref_number"

    # Fallback TNKB + jenis. Ambil kandidat lalu pilih tanggal paling cocok secara string prefix hari.
    rows = (
        supabase.table("etle_cases")
        .select("case_id,violation_id,ref_number,tnkb,tanggal_pelanggaran,jenis_pelanggaran")
        .ilike("tnkb", f"%{TARGET_TNKB[-6:]}%")
        .limit(50)
        .execute()
        .data
    )

    normalized = [r for r in rows if norm(r.get("tnkb")) == TARGET_TNKB]
    if DETAIL_TYPE:
        typed = [r for r in normalized if str(r.get("jenis_pelanggaran") or "").strip().upper() == DETAIL_TYPE.upper()]
        if typed:
            normalized = typed

    date_prefix = DETAIL_TIME[:10]
    dated = [r for r in normalized if str(r.get("tanggal_pelanggaran") or "").startswith(date_prefix)]
    if len(dated) == 1:
        return dated[0], "tnkb+type+date"
    if len(normalized) == 1:
        return normalized[0], "tnkb+type"
    if len(dated) > 1:
        raise RuntimeError(f"Case ambigu: {len(dated)} kandidat untuk TNKB/tanggal yang sama.")
    if len(normalized) > 1:
        raise RuntimeError(f"Case ambigu: {len(normalized)} kandidat TNKB/type. Perlu ref_number.")
    raise RuntimeError("Case di Supabase tidak ditemukan.")

def main():
    required = {
        "EMAIL_ETLE": EMAIL_ETLE,
        "PASSWORD_ETLE": PASSWORD_ETLE,
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_SERVICE_ROLE_KEY": SUPABASE_SERVICE_ROLE_KEY,
    }
    missing = [k for k,v in required.items() if not v]
    if missing:
        raise RuntimeError("Environment belum lengkap: " + ", ".join(missing))

    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        login(page)
        log("Login ETLE berhasil.")

        detail = extract_detail(page)
        browser.close()

    case, matched_by = resolve_case(supabase, detail)

    result = {
        "dry_run": DRY_RUN,
        "matched_by": matched_by,
        "case": case,
        "detail": {
            "detail_url": detail["detail_url"],
            "ref_number": detail.get("ref_number"),
            "tnkb_text": detail.get("tnkb_text"),
            "photo_url": detail["photo_url"],
        }
    }

    log(f"Matched by: {matched_by}")
    log(f"Case ID: {case['case_id']}")
    log(f"Ref: {case.get('ref_number')}")
    log(f"TNKB: {case.get('tnkb')}")
    log(f"Photo URL: {detail['photo_url']}")

    if DRY_RUN:
        log("DRY_RUN=true -> Supabase tidak diubah.")
    else:
        row = {
            "case_id": case["case_id"],
            "violation_id": case.get("violation_id"),
            "photo_type": "VEHICLE",
            "photo_url": detail["photo_url"],
            "description": "Foto kendaraan pelanggaran dari printed_detail.php",
            "sort_order": 1,
        }
        supabase.table("etle_photos").upsert(
            row,
            on_conflict="case_id,photo_type,photo_url"
        ).execute()
        log("SUCCESS: foto berhasil di-upsert ke etle_photos.")

    with open("single_photo_sync_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
