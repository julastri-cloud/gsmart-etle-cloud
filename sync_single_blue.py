import os, json, re
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright
from supabase import create_client

BASE = "https://etilang-djpd.kemenhub.go.id:9000"
LOGIN = BASE + "/main/"
EMAIL = os.getenv("EMAIL_ETLE", "").strip()
PASSWORD = os.getenv("PASSWORD_ETLE", "").strip()
SB_URL = os.getenv("SUPABASE_URL", "").strip()
SB_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
TNKB = os.getenv("TARGET_TNKB", "AE8768SK").replace(" ", "").upper()
DETAIL_NO = os.getenv("DETAIL_NO", "347586").strip()
DETAIL_TIME = os.getenv("DETAIL_TIME", "2026-09-12 14:17:23").strip()
DETAIL_TYPE = os.getenv("DETAIL_TYPE", "DOKUMEN").strip()
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

def log(x):
    print(x, flush=True)

def clean(v):
    if v is None:
        return None
    v = str(v).strip()
    return None if not v or v.lower() == "null" else v

def num(v):
    v = clean(v)
    if not v:
        return None
    m = re.search(r"-?[0-9]+(?:[.,][0-9]+)?", v)
    return float(m.group(0).replace(",", ".")) if m else None

def login(page):
    page.goto(LOGIN, wait_until="domcontentloaded", timeout=60000)
    page.locator('input[placeholder="Email"]').fill(EMAIL)
    page.locator('input[placeholder="Password"]').fill(PASSWORD)
    page.locator('button:has-text("Login")').click()
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    page.wait_for_timeout(1000)
    if "/main/" in page.url:
        raise RuntimeError("Login ETLE gagal")

def detail_url():
    return BASE + "/admin-etle/printed_detail.php?" + urlencode({
        "id": TNKB,
        "no": DETAIL_NO,
        "time": DETAIL_TIME,
        "type": DETAIL_TYPE,
    })

def table_map(page, selector):
    rows = page.locator(selector + " tr")
    out = {}
    for i in range(rows.count()):
        row = rows.nth(i)
        cells = row.locator("th,td")
        if cells.count() >= 3:
            key = clean(cells.nth(0).inner_text())
            val = clean(cells.nth(2).inner_text())
            if key:
                out[key] = val
    return out

def resolve_case(sb, ref):
    rows = sb.table("etle_cases").select("case_id,violation_id,ref_number,tnkb").eq("ref_number", ref).limit(2).execute().data
    if len(rows) == 1:
        return rows[0]
    rows = sb.table("etle_cases").select("case_id,violation_id,ref_number,tnkb").ilike("tnkb", "%" + TNKB[-6:] + "%").limit(50).execute().data
    rows = [r for r in rows if str(r.get("tnkb") or "").replace(" ", "").upper() == TNKB]
    if len(rows) == 1:
        return rows[0]
    raise RuntimeError("Case tidak unik atau tidak ditemukan")

def main():
    sb = create_client(SB_URL, SB_KEY)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page()
        login(page)
        log("Login ETLE berhasil.")
        page.goto(detail_url(), wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(1000)
        pel = table_map(page, "#detailPelanggaran")
        blue = table_map(page, "#informasiKendaraan")
        browser.close()

    ref = clean(pel.get("Nomor Registrasi"))
    if not ref:
        raise RuntimeError("Nomor Registrasi tidak ditemukan")
    case = resolve_case(sb, ref)

    is_daya_angkut = "DAYA ANGKUT" in DETAIL_TYPE.upper()
    row = {
        "case_id": case["case_id"],
        "violation_id": case.get("violation_id"),
        "nama_pemilik": clean(blue.get("Nama Pemilik")),
        "alamat_pemilik": clean(blue.get("Alamat")),
        "merk": clean(blue.get("Merk")),
        "tipe": clean(blue.get("Type")),
        "jenis_kendaraan": clean(blue.get("Jenis Kendaraan")),
        "no_mesin": clean(blue.get("No Mesin")),
        "no_rangka": clean(blue.get("No Rangka")),
        "masa_berlaku_kir": clean(blue.get("Masa Berlaku KIR")),
        "jbi": num(pel.get("JBI/JBKB")) if is_daya_angkut else num(blue.get("JBI/JBKB")),
        "berat_timbang": num(pel.get("Berat Timbang")) if is_daya_angkut else None,
        "berat_lebih": num(pel.get("Berat Lebih")) if is_daya_angkut else None,
    }
    row = {k: v for k, v in row.items() if v is not None}

    result = {
        "dry_run": DRY_RUN,
        "case": case,
        "nomor_registrasi": ref,
        "blue_source": blue,
        "pelanggaran_source": pel,
        "supabase_row": row,
        "weight_check": {
            "jbi": row.get("jbi"),
            "berat_timbang": row.get("berat_timbang"),
            "berat_lebih": row.get("berat_lebih"),
            "persentase_lebih": (
                round(row["berat_lebih"] / row["jbi"] * 100, 2)
                if row.get("jbi") and row.get("berat_lebih") is not None else None
            ),
        },
        "not_mapped_yet": {
            "warna_kendaraan": clean(blue.get("Warna Kendaraan")),
            "tanggal_uji_kir": clean(blue.get("Tanggal Uji KIR")),
        },
    }

    log("Case ID: " + case["case_id"])
    log("BLUE source: " + json.dumps(blue, ensure_ascii=False))
    log("Data Pelanggaran source: " + json.dumps(pel, ensure_ascii=False))
    log("Supabase row: " + json.dumps(row, ensure_ascii=False))

    if DRY_RUN:
        log("DRY_RUN=true -> Supabase tidak diubah.")
    else:
        sb.table("etle_vehicles").upsert(row, on_conflict="case_id").execute()
        log("SUCCESS: data BLUE berhasil di-upsert ke etle_vehicles.")

    with open("single_blue_sync_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
