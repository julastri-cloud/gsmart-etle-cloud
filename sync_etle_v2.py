import os, json, time, re
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlencode
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from supabase import create_client

load_dotenv()
WIB = ZoneInfo("Asia/Jakarta")

URL_LOGIN = "https://etilang-djpd.kemenhub.go.id:9000/main/"
URL_BLANKO_PAGE = "https://etilang-djpd.kemenhub.go.id:9000/admin-etle/tertagih.php"
URL_LIST_BLANKO = "https://etilang-djpd.kemenhub.go.id:9000/etle/admin-etle/list_tertagih.php"
URL_DETAIL_BLANKO = "https://etilang-djpd.kemenhub.go.id:9000/etle/admin-etle/tertagih.php"
URL_PRINTED = "https://etilang-djpd.kemenhub.go.id:9000/etle/admin-etle/penindakan_printed_list.php"
URL_DISPUTES = "https://etilang-djpd.kemenhub.go.id:9000/etle/admin-etle/list_terkonfirmasi.php"
URL_TERMINATED = "https://etilang-djpd.kemenhub.go.id:9000/etle/admin-etle/datalisthentikanblokir.php"

EMAIL_ETLE = os.getenv("EMAIL_ETLE", "").strip()
PASSWORD_ETLE = os.getenv("PASSWORD_ETLE", "").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
DATE_FROM = os.getenv("DATE_FROM", "01-08-2026").strip()
DATE_TO = os.getenv("DATE_TO", datetime.now(WIB).strftime("%d-%m-%Y")).strip()
SYNC_LIMIT = int(os.getenv("SYNC_LIMIT", "0"))
HEADLESS = os.getenv("HEADLESS", "true").strip().lower() == "true"
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.5"))
MAX_RETRY = int(os.getenv("MAX_RETRY", "3"))
PRINTED_PAGE_SIZE = int(os.getenv("PRINTED_PAGE_SIZE", "100"))

REQUIRED_TABLES = [
    "etle_blanko_detail", "etle_cases", "etle_offenders", "etle_vehicles",
    "etle_photos", "etle_payments", "etle_shipping", "etle_disputes",
    "etle_court_info", "etle_terminated_cases", "gsmart_case_history",
    "gsmart_sync_log"
]

def log(message):
    print(f"[{datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)

def clean(value):
    if value is None: return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value

def now_iso():
    return datetime.now(WIB).isoformat()

def parse_date_any(value):
    value = clean(value)
    if not value: return None
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try: return datetime.strptime(value, fmt).date().isoformat()
        except ValueError: pass
    return None

def parse_datetime_any(value):
    value = clean(value)
    if not value: return None
    for fmt in ("%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M"):
        try: return datetime.strptime(value, fmt).replace(tzinfo=WIB).isoformat()
        except ValueError: pass
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None: dt = dt.replace(tzinfo=WIB)
        return dt.isoformat()
    except ValueError:
        return None

def numeric(value):
    value = clean(value)
    if value is None: return None
    try: return float(str(value).replace(",", ""))
    except (TypeError, ValueError): return None

def ddmmyyyy_to_iso(value):
    value = clean(value)
    if not value: return None
    try: return datetime.strptime(value, "%d-%m-%Y").strftime("%Y-%m-%d")
    except ValueError: return value

def extract_delivery_datetime(desc):
    desc = clean(desc)
    if not desc: return None
    m = re.search(r"\|\s*(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2})\s*\|", desc)
    return parse_datetime_any(m.group(1)) if m else None

def validate_environment():
    missing = [k for k,v in {
        "EMAIL_ETLE": EMAIL_ETLE, "PASSWORD_ETLE": PASSWORD_ETLE,
        "SUPABASE_URL": SUPABASE_URL, "SUPABASE_SERVICE_ROLE_KEY": SUPABASE_SERVICE_ROLE_KEY
    }.items() if not v]
    if missing: raise RuntimeError("Environment belum lengkap: " + ", ".join(missing))
    if "/rest/v1" in SUPABASE_URL: raise RuntimeError("SUPABASE_URL tidak boleh mengandung /rest/v1.")
    if SUPABASE_SERVICE_ROLE_KEY.startswith("sb_publishable_"):
        raise RuntimeError("Backend sync harus memakai server/service-role key, bukan publishable key.")
    log("Environment berhasil divalidasi.")

def create_supabase():
    log("Menghubungkan ke Supabase...")
    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    log("Supabase siap.")
    return client

def validate_tables(supabase):
    missing = []
    for table_name in REQUIRED_TABLES:
        try: supabase.table(table_name).select("*").limit(1).execute()
        except Exception: missing.append(table_name)
    if missing: raise RuntimeError("Tabel Supabase belum siap/tidak ditemukan: " + ", ".join(missing))
    log("Semua tabel utama tersedia.")

def login_etle(page):
    log("Membuka halaman login ETLE...")
    page.goto(URL_LOGIN, wait_until="domcontentloaded", timeout=60000)
    email = page.locator('input[placeholder="Email"]')
    password = page.locator('input[placeholder="Password"]')
    email.wait_for(state="visible", timeout=30000)
    password.wait_for(state="visible", timeout=30000)
    email.fill(EMAIL_ETLE); password.fill(PASSWORD_ETLE)
    page.locator('button:has-text("Login")').click()
    try: page.wait_for_load_state("networkidle", timeout=30000)
    except Exception: pass
    page.wait_for_timeout(2000)
    if "/main/" in page.url: raise RuntimeError("Login ETLE gagal.")
    log("Login ETLE berhasil.")

def open_blanko_page(page):
    page.goto(URL_BLANKO_PAGE, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1500)
    if "/main/" in page.url: raise RuntimeError("Session ETLE tidak aktif.")

def browser_fetch(page, url):
    result = page.evaluate("""async (url) => {
      try {
        const r = await fetch(url,{method:"GET",credentials:"include",cache:"no-store",
          headers:{"Accept":"application/json, text/javascript, */*; q=0.01","X-Requested-With":"XMLHttpRequest"}});
        return {ok:true,status:r.status,body:await r.text()};
      } catch(e) { return {ok:false,status:0,body:"",error:String(e)}; }
    }""", url)
    if not result.get("ok"): raise RuntimeError("Fetch gagal: " + result.get("error","unknown"))
    if result.get("status") != 200: raise RuntimeError(f"HTTP {result.get('status')}: {result.get('body','')[:500]}")
    body = result.get("body","")
    if not body.strip(): raise RuntimeError("Response API kosong.")
    try: return json.loads(body)
    except json.JSONDecodeError as e: raise RuntimeError(f"Response bukan JSON valid: {e}. {body[:500]}")

def upsert(supabase, table, row, conflict):
    return supabase.table(table).upsert(row, on_conflict=conflict).execute().data

def get_case_by_violation(supabase, violation_id):
    if not clean(violation_id): return None
    data = supabase.table("etle_cases").select("case_id,violation_id,ref_number").eq("violation_id", str(violation_id)).limit(1).execute().data
    return data[0] if data else None

def get_case_by_ref(supabase, ref_number):
    if not clean(ref_number): return None
    data = supabase.table("etle_cases").select("case_id,violation_id,ref_number").eq("ref_number", clean(ref_number)).limit(1).execute().data
    return data[0] if data else None

def ensure_minimal_case(supabase, item):
    row = {
        "violation_id": str(item["violation_id"]),
        "ref_number": clean(item.get("ref_number")),
        "tnkb": clean(item.get("plat_number")),
        "no_registrasi": clean(item.get("ref_number")),
        "jenis_pelanggaran": clean(item.get("pelanggaran")),
        "lokasi": clean(item.get("lokasi")),
        "tanggal_pelanggaran": parse_datetime_any(item.get("vl_inserted_date")),
        "status_etle": "TERSANGGAH",
        "last_sync_at": now_iso(),
    }
    row = {k:v for k,v in row.items() if v is not None}
    upsert(supabase, "etle_cases", row, "violation_id")
    return get_case_by_violation(supabase, item["violation_id"])

def history_exists(supabase, case_id, event_type, event_time, source):
    q = supabase.table("gsmart_case_history").select("history_id").eq("case_id", case_id).eq("event_type", event_type).eq("source", source)
    if event_time: q = q.eq("event_time", event_time)
    return bool(q.limit(1).execute().data)

def add_history_event(supabase, case_id, event_type, event_time, title, description=None, source="ETLE"):
    if not case_id or not event_time: return False
    if history_exists(supabase, case_id, event_type, event_time, source): return False
    supabase.table("gsmart_case_history").insert({
        "case_id": case_id, "event_type": event_type, "event_time": event_time,
        "title": title, "description": clean(description), "source": source,
        "created_at": now_iso()
    }).execute()
    return True

def write_sync_log(supabase, module, started_at, status, found=0, updated=0, failed=0, error=None):
    try:
        supabase.table("gsmart_sync_log").insert({
            "module": module, "started_at": started_at, "finished_at": now_iso(),
            "status": status, "rows_found": found, "rows_inserted": 0,
            "rows_updated": updated, "rows_failed": failed,
            "error_message": clean(error), "created_at": now_iso()
        }).execute()
    except Exception as e:
        log(f"Gagal menulis sync log {module}: {e}")

PRINTED_COLUMNS = ["inserted_date","display_date","ref_number","plat_number","alamat_regiden",
                   "wilayah_satuan","wilayah_induk","no_resi","pelanggaran","validasi_date","status","aksi"]

def build_printed_url(start, length, draw):
    p = {"draw":draw,"order[0][column]":0,"order[0][dir]":"asc","start":start,"length":length,
         "search[value]":"","search[regex]":"false","date":f"{DATE_FROM} 00:00","date1":f"{DATE_TO} 00:00",
         "selectAll":"no","provinsi":"","status":"Sudah_Dicetak","_":int(time.time()*1000)}
    for i,f in enumerate(PRINTED_COLUMNS):
        p[f"columns[{i}][data]"]=f; p[f"columns[{i}][name]"]=""
        p[f"columns[{i}][searchable]"]="true"; p[f"columns[{i}][orderable]"]="true"
        p[f"columns[{i}][search][value]"]=""; p[f"columns[{i}][search][regex]"]="false"
    return URL_PRINTED + "?" + urlencode(p)

def get_printed_list(page):
    rows=[]; start=0; draw=1
    while True:
        parsed = browser_fetch(page, build_printed_url(start, PRINTED_PAGE_SIZE, draw))
        page_rows = parsed.get("data", [])
        if not isinstance(page_rows, list): raise RuntimeError("JSON Surat Dicetak tidak dikenali.")
        total = int(parsed.get("recordsFiltered", parsed.get("recordsTotal", len(page_rows))) or 0)
        rows.extend(page_rows)
        log(f"Surat Dicetak: {len(rows)}/{total}")
        if not page_rows or len(rows) >= total: break
        start += len(page_rows); draw += 1
    return rows[:SYNC_LIMIT] if SYNC_LIMIT>0 else rows

def sync_shipping(page, supabase):
    started=now_iso(); found=ok=failed=0
    try:
        rows=get_printed_list(page); found=len(rows)
        for i,item in enumerate(rows,1):
            try:
                printed_date=parse_date_any(item.get("printed_date") or item.get("display_date"))
                delivered_at=extract_delivery_datetime(item.get("desc_terakhir"))
                row={
                    "source_id": str(item.get("id")), "ref_number":clean(item.get("ref_number")),
                    "tnkb":clean(item.get("plat_number")), "nama_pemilik":clean(item.get("nama_pemilik")),
                    "alamat_pemilik":clean(item.get("alamat_regiden")), "wilayah_satuan":clean(item.get("wilayah_satuan")),
                    "wilayah_induk":clean(item.get("wilayah_induk")), "jenis_pelanggaran":clean(item.get("pelanggaran")),
                    "tanggal_pelanggaran":parse_datetime_any(item.get("inserted_date")),
                    "printed_date":printed_date, "validasi_date":parse_date_any(item.get("validasi_date")),
                    "tracking_number":clean(item.get("no_resi")), "courier":"JNE" if clean(item.get("no_resi")) else None,
                    "status":clean(item.get("status")), "status_description":clean(item.get("desc_terakhir")),
                    "printed_at":f"{printed_date}T00:00:00+07:00" if printed_date else None,
                    "delivered_at":delivered_at, "last_event_at":delivered_at, "raw_data":item, "updated_at":now_iso()
                }
                case=get_case_by_ref(supabase,row["ref_number"])
                if case:
                    row["case_id"]=case["case_id"]; row["violation_id"]=case["violation_id"]
                upsert(supabase,"etle_shipping",row,"source_id")
                ok+=1; log(f"[SHIPPING {i}/{found}] {row['tnkb']} | {row['status']} -> OK")
            except Exception as e:
                failed+=1; log(f"[SHIPPING {i}/{found}] GAGAL: {e}")
        write_sync_log(supabase,"SHIPPING",started,"SUCCESS" if failed==0 else "PARTIAL",found,ok,failed)
        return {"found":found,"success":ok,"failed":failed}
    except Exception as e:
        write_sync_log(supabase,"SHIPPING",started,"FAILED",found,ok,failed,str(e)); raise

def get_blanko_list(page):
    url=f"{URL_LIST_BLANKO}?dateFrom={DATE_FROM}&dateTo={DATE_TO}&status=&_={int(time.time()*1000)}"
    parsed=browser_fetch(page,url)
    if isinstance(parsed,list): rows=parsed
    elif isinstance(parsed,dict):
        rows=next((parsed.get(k) for k in ("data","rows","result","aaData") if isinstance(parsed.get(k),list)),None)
        if rows is None: raise RuntimeError("JSON Blanko tidak dikenali.")
    else: raise RuntimeError("JSON Blanko tidak dikenali.")
    return rows[:SYNC_LIMIT] if SYNC_LIMIT>0 else rows

def get_blanko_detail(page, violation_id):
    parsed=browser_fetch(page,f"{URL_DETAIL_BLANKO}?violation_id={violation_id}")
    if isinstance(parsed,list):
        if not parsed: raise RuntimeError("Detail kosong.")
        return parsed[0]
    if isinstance(parsed,dict):
        if isinstance(parsed.get("data"),list):
            if not parsed["data"]: raise RuntimeError("Detail kosong.")
            return parsed["data"][0]
        if isinstance(parsed.get("data"),dict): return parsed["data"]
        return parsed
    raise RuntimeError("JSON detail tidak dikenali.")

def sanitize_detail(detail):
    out=dict(detail); out.pop("json_response",None); out.pop("jsonResponse",None); return out

def build_legacy_row(item, d):
    violation_id=clean(d.get("violation_id") or item.get("violation_id"))
    if not violation_id: raise RuntimeError("violation_id kosong.")
    row={
        "violation_id":str(violation_id),
        "ref_number":clean(d.get("ref_number") or d.get("pelanggar_ref_number") or item.get("ref_number")),
        "plat_number":clean(d.get("plat_number") or d.get("no_registrasi_kendaraan") or item.get("plat_number")),
        "no_briva":clean(d.get("no_briva") or item.get("no_briva")),
        "no_blanko":clean(d.get("blanko_no") or item.get("blanko_no")),
        "status":clean(d.get("status") or d.get("status_bayar") or item.get("status_bayar") or item.get("status")),
        "pelanggaran":clean(d.get("pelanggaran") or d.get("report_type") or item.get("report_type")),
        "tanggal_pelanggaran":clean(d.get("inserted_date_vl") or d.get("validasi_date") or item.get("inserted_date_vl")),
        "tanggal_tagih":clean(d.get("tertagih_date_date") or d.get("tertagih_date") or item.get("blanko_date")),
        "tanggal_sidang":clean(d.get("tanggal_sidang_etle") or d.get("tanggal_sidang_kejaksaan")),
        "nama_pemilik":clean(d.get("pemilik_stnk") or d.get("nama_pemilik")),
        "alamat_pemilik":clean(d.get("alamat_pemilik")),
        "jenis_kendaraan":clean(d.get("jenis_kendaraan")),
        "merk":clean(d.get("merk") or d.get("merk_kendaraan")),
        "tipe":clean(d.get("tipe")),
        "masa_berlaku_kir":clean(d.get("masa_berlaku_kir") or d.get("masa_berlaku")),
        "foto_kendaraan":clean(d.get("foto_kendaraan") or d.get("foto")),
        "foto_plat":clean(d.get("foto_plat")),
        "raw_data":{"list_data":item,"detail_data":sanitize_detail(d)},
        "last_sync_at":now_iso()
    }
    return row

def sync_normalized_blanko(supabase,item,d,legacy):
    vid=legacy["violation_id"]
    case_row={
        "violation_id":vid,"ref_number":legacy.get("ref_number"),"tnkb":legacy.get("plat_number"),
        "no_registrasi":clean(d.get("nomor_registrasi") or legacy.get("ref_number")),
        "jenis_pelanggaran":clean(d.get("report_type") or d.get("pelanggaran") or legacy.get("pelanggaran")),
        "pasal":clean(d.get("pasal")),"lokasi":clean(d.get("lokasi") or item.get("lokasi")),
        "tanggal_pelanggaran":parse_datetime_any(d.get("inserted_date_vl") or item.get("inserted_date_vl")),
        "status_etle":clean(d.get("status") or legacy.get("status")),
        "status_bayar":clean(item.get("status_bayar") or d.get("status") or legacy.get("status")),
        "no_blanko":legacy.get("no_blanko"),"no_briva":legacy.get("no_briva"),
        "tanggal_blanko":parse_date_any(d.get("blanko_date") or item.get("blanko_date")),
        "tanggal_sidang":parse_date_any(d.get("tanggal_sidang_etle") or legacy.get("tanggal_sidang")),
        "nama_pemilik":clean(d.get("nama_pemilik") or d.get("pemilik_stnk") or legacy.get("nama_pemilik")),
        "raw_data":legacy["raw_data"],"last_sync_at":now_iso()
    }
    case_row={k:v for k,v in case_row.items() if v is not None}
    upsert(supabase,"etle_cases",case_row,"violation_id")
    case=get_case_by_violation(supabase,vid)
    if not case: raise RuntimeError(f"case_id tidak ditemukan untuk {vid}")
    cid=case["case_id"]

    upsert(supabase,"etle_offenders",{
        "case_id":cid,"violation_id":vid,"nama":clean(d.get("pelanggar_nama")),
        "alamat":clean(d.get("pelanggar_alamat")),"no_telp":clean(d.get("pelanggar_notel") or d.get("notel")),
        "email":clean(d.get("pelanggar_email")),"no_ktp":clean(d.get("no_ktp")),"no_sim":clean(d.get("no_sim")),
        "golongan_sim":clean(d.get("golongan_sim")),"masa_berlaku_sim":parse_date_any(d.get("masa_berlaku_sim")),
        "tempat_lahir":clean(d.get("tempat_lahir")),"tanggal_lahir":parse_date_any(d.get("ttl")),
        "jenis_kelamin":clean(d.get("jenis_kelamin")),"pekerjaan":clean(d.get("pekerjaan")),
        "satpas_penerbit":clean(d.get("satpas_penerbit")),"updated_at":now_iso()
    },"case_id")

    upsert(supabase,"etle_vehicles",{
        "case_id":cid,"violation_id":vid,"nama_pemilik":clean(d.get("nama_pemilik") or d.get("pemilik_stnk")),
        "alamat_pemilik":clean(d.get("alamat_pemilik")),"merk":clean(d.get("merk") or d.get("merk_kendaraan")),
        "tipe":clean(d.get("tipe")),"jenis_kendaraan":clean(d.get("jenis_kendaraan")),
        "tahun_rakit":clean(d.get("tahun_rakit")),"bahan_bakar":clean(d.get("bahan_bakar")),
        "no_rangka":clean(d.get("no_rangka")),"no_mesin":clean(d.get("no_mesin")),"no_uji":clean(d.get("nouji")),
        "masa_berlaku_kir":parse_date_any(d.get("masa_berlaku_kir") or d.get("masa_berlaku")),
        "jbb":numeric(d.get("jbb")),"jbi":numeric(d.get("jbi")),"berat_kosong":numeric(d.get("berat_kosong")),
        "berat_timbang":numeric(d.get("berat_timbang")),"berat_lebih":numeric(d.get("berat_lebih")),
        "panjang_kendaraan":numeric(d.get("panjang_kendaraan")),"lebar_kendaraan":numeric(d.get("lebar_kendaraan")),
        "tinggi_kendaraan":numeric(d.get("tinggi_kendaraan")),"updated_at":now_iso()
    },"case_id")

    upsert(supabase,"etle_payments",{
        "case_id":cid,"violation_id":vid,"no_briva":clean(d.get("no_briva") or item.get("no_briva")),
        "status_bayar":clean(item.get("status_bayar") or d.get("status")),"titipan":numeric(item.get("titipan")),
        "denda_maksimum":numeric(d.get("denda_maksimum")),"denda_pengadilan":numeric(d.get("denda_pengadilan")),
        "biaya_perkara":numeric(d.get("biaya_perkara")),"total_amount":numeric(d.get("total_amount")),
        "paid_amount":numeric(d.get("denda_bayar")),"nominal_sisa":numeric(d.get("nominal_sisa")),
        "paid_at":parse_datetime_any(d.get("paid_date")),"payment_at":parse_datetime_any(d.get("payment_at")),
        "updated_at":now_iso()
    },"case_id")

    court_date=parse_date_any(d.get("tanggal_sidang_etle") or d.get("tanggal_sidang_kejaksaan"))
    upsert(supabase,"etle_court_info",{
        "case_id":cid,"violation_id":vid,"tanggal_sidang":court_date,"lokasi_sidang":clean(d.get("lokasi_sidang")),
        "pengadilan":clean(d.get("court_place")),"pengadilan_id":clean(d.get("pengadilan_id")),
        "kejaksaan":clean(d.get("lokasi_kejaksaan")),"kejaksaan_id":clean(d.get("kejaksaan_id")),
        "hakim":clean(d.get("hakim")),"panitera":clean(d.get("panitera")),
        "no_amar_putusan":clean(d.get("no_amar_putusan")),"denda_putusan":numeric(d.get("denda_pengadilan")),
        "biaya_perkara":numeric(d.get("biaya_perkara")),
        "status_sidang":"COMPLETED" if clean(d.get("no_amar_putusan")) else ("SCHEDULED" if court_date else None),
        "updated_at":now_iso()
    },"case_id")

    for ptype,purl,desc,order in [
        ("VEHICLE",clean(d.get("foto_kendaraan") or d.get("foto")),"Foto kendaraan pelanggaran",1),
        ("PLATE",clean(d.get("foto_plat")),"Foto plat nomor kendaraan",2)
    ]:
        if purl:
            upsert(supabase,"etle_photos",{
                "case_id":cid,"violation_id":vid,"photo_type":ptype,"photo_url":purl,
                "description":desc,"sort_order":order,"updated_at":now_iso()
            },"case_id,photo_type,photo_url")

    blanko_date=parse_date_any(d.get("blanko_date") or item.get("blanko_date"))
    if blanko_date:
        add_history_event(supabase,cid,"BLANKO_ISSUED",f"{blanko_date}T00:00:00+07:00",
                          "Blanko tilang diterbitkan",
                          f"Blanko {legacy.get('no_blanko')}" if legacy.get("no_blanko") else None,
                          "ETLE_BLANKO")
    paid_at=parse_datetime_any(d.get("paid_date"))
    if paid_at:
        add_history_event(supabase,cid,"PAYMENT_RECEIVED",paid_at,"Pembayaran diterima",
                          f"Status pembayaran: {item.get('status_bayar') or d.get('status')}","ETLE_BLANKO")
    if court_date:
        add_history_event(supabase,cid,"COURT_SCHEDULED",f"{court_date}T00:00:00+07:00",
                          "Sidang terjadwal",clean(d.get("court_place")),"ETLE_BLANKO")

def sync_blanko(page,supabase):
    started=now_iso(); found=ok=failed=0
    try:
        rows=get_blanko_list(page); found=len(rows); log(f"Blanko: {found} record.")
        for i,item in enumerate(rows,1):
            vid=clean(item.get("violation_id"))
            if not vid:
                failed+=1; continue
            last=None
            for attempt in range(1,MAX_RETRY+1):
                try:
                    d=get_blanko_detail(page,vid); legacy=build_legacy_row(item,d)
                    upsert(supabase,"etle_blanko_detail",legacy,"violation_id")
                    sync_normalized_blanko(supabase,item,d,legacy)
                    ok+=1; last=None; log(f"[BLANKO {i}/{found}] {vid} | {legacy.get('plat_number')} -> OK"); break
                except Exception as e:
                    last=e; log(f"[BLANKO {i}/{found}] retry {attempt}/{MAX_RETRY}: {e}")
                    if attempt<MAX_RETRY: page.wait_for_timeout(attempt*2000)
            if last is not None: failed+=1
            if REQUEST_DELAY>0: page.wait_for_timeout(int(REQUEST_DELAY*1000))
        write_sync_log(supabase,"BLANKO",started,"SUCCESS" if failed==0 else "PARTIAL",found,ok,failed)
        return {"found":found,"success":ok,"failed":failed}
    except Exception as e:
        write_sync_log(supabase,"BLANKO",started,"FAILED",found,ok,failed,str(e)); raise

def get_disputes(page):
    p={"dateFrom":f"{DATE_FROM} 00:00","dateTo":f"{DATE_TO} 00:00","status":"Tersanggah","_":int(time.time()*1000)}
    parsed=browser_fetch(page,URL_DISPUTES+"?"+urlencode(p))
    rows=parsed.get("data",[])
    if not isinstance(rows,list): raise RuntimeError("JSON Tersanggah tidak dikenali.")
    return rows[:SYNC_LIMIT] if SYNC_LIMIT>0 else rows

def sync_disputes(page,supabase):
    started=now_iso(); found=ok=failed=0
    try:
        rows=get_disputes(page); found=len(rows)
        for i,item in enumerate(rows,1):
            try:
                if not clean(item.get("violation_id")): raise RuntimeError("violation_id kosong.")
                case=ensure_minimal_case(supabase,item); cid=case["case_id"]
                conf=parse_datetime_any(item.get("confirmation_date"))
                upsert(supabase,"etle_disputes",{
                    "case_id":cid,"violation_id":str(item["violation_id"]),"status":"TERSANGGAH",
                    "confirmation_type":clean(item.get("confirmation_type")),"confirmation_date":conf,
                    "reason":None,"result":clean(item.get("litsus_code")),"terkonfirmasi_type":None,
                    "updated_at":now_iso()
                },"case_id")
                if conf:
                    add_history_event(supabase,cid,"DISPUTE_RECEIVED",conf,"Pelanggaran disanggah",
                                      f"TNKB {item.get('plat_number')} | {item.get('pelanggaran')}","ETLE_TERSANGGAH")
                ok+=1; log(f"[TERSANGGAH {i}/{found}] {item['violation_id']} | {item.get('plat_number')} -> OK")
            except Exception as e:
                failed+=1; log(f"[TERSANGGAH {i}/{found}] GAGAL: {e}")
        write_sync_log(supabase,"DISPUTES",started,"SUCCESS" if failed==0 else "PARTIAL",found,ok,failed)
        return {"found":found,"success":ok,"failed":failed}
    except Exception as e:
        write_sync_log(supabase,"DISPUTES",started,"FAILED",found,ok,failed,str(e)); raise

def get_terminated(page):
    p={"dateFrom":ddmmyyyy_to_iso(DATE_FROM),"dateTo":ddmmyyyy_to_iso(DATE_TO),"_":int(time.time()*1000)}
    parsed=browser_fetch(page,URL_TERMINATED+"?"+urlencode(p))
    rows=parsed.get("data",[])
    if not isinstance(rows,list): raise RuntimeError("JSON Dihentikan tidak dikenali.")
    return rows[:SYNC_LIMIT] if SYNC_LIMIT>0 else rows

def sync_terminated(page,supabase):
    started=now_iso(); found=ok=failed=0
    try:
        rows=get_terminated(page); found=len(rows)
        for i,item in enumerate(rows,1):
            try:
                ref=clean(item.get("ref_number"))
                if not ref: raise RuntimeError("ref_number kosong.")
                case=get_case_by_ref(supabase,ref); term=parse_date_any(item.get("dihentikan_date"))
                row={"ref_number":ref,"tnkb":clean(item.get("plat_number")),"lokasi":clean(item.get("lokasi")),
                     "status":clean(item.get("blokirnya") or "Dihentikan"),"reason":clean(item.get("alasan_lainnya")),
                     "officer_name":clean(item.get("nama_user")),"terminated_at":term,"raw_data":item,"updated_at":now_iso()}
                if case:
                    row["case_id"]=case["case_id"]; row["violation_id"]=case["violation_id"]
                upsert(supabase,"etle_terminated_cases",row,"ref_number")
                if case and term:
                    add_history_event(supabase,case["case_id"],"CASE_STOPPED",f"{term}T00:00:00+07:00",
                                      "Perkara dihentikan",clean(item.get("alasan_lainnya")),"ETLE_DIHENTIKAN")
                ok+=1; log(f"[DIHENTIKAN {i}/{found}] {item.get('plat_number')} -> OK")
            except Exception as e:
                failed+=1; log(f"[DIHENTIKAN {i}/{found}] GAGAL: {e}")
        write_sync_log(supabase,"TERMINATED",started,"SUCCESS" if failed==0 else "PARTIAL",found,ok,failed)
        return {"found":found,"success":ok,"failed":failed}
    except Exception as e:
        write_sync_log(supabase,"TERMINATED",started,"FAILED",found,ok,failed,str(e)); raise

def link_orphans_and_history(supabase):
    started=now_iso(); linked=failed=0
    try:
        shipping=supabase.table("etle_shipping").select("shipping_id,ref_number").is_("case_id","null").execute().data
        for r in shipping:
            try:
                case=get_case_by_ref(supabase,r.get("ref_number"))
                if case:
                    supabase.table("etle_shipping").update({"case_id":case["case_id"],"violation_id":case["violation_id"],"updated_at":now_iso()}).eq("shipping_id",r["shipping_id"]).execute()
                    linked+=1
            except Exception as e:
                failed+=1; log(f"Gagal link shipping: {e}")
        term=supabase.table("etle_terminated_cases").select("terminated_id,ref_number").is_("case_id","null").execute().data
        for r in term:
            try:
                case=get_case_by_ref(supabase,r.get("ref_number"))
                if case:
                    supabase.table("etle_terminated_cases").update({"case_id":case["case_id"],"violation_id":case["violation_id"],"updated_at":now_iso()}).eq("terminated_id",r["terminated_id"]).execute()
                    linked+=1
            except Exception as e:
                failed+=1; log(f"Gagal link terminated: {e}")

        rows=supabase.table("etle_shipping").select("case_id,status,status_description,printed_at,delivered_at,tnkb").not_.is_("case_id","null").execute().data
        for r in rows:
            if r.get("printed_at"):
                add_history_event(supabase,r["case_id"],"LETTER_PRINTED",r["printed_at"],"Surat tilang dicetak",
                                  f"TNKB {r.get('tnkb')}" if r.get("tnkb") else None,"ETLE_SHIPPING")
            if clean(r.get("status")) and r["status"].lower()=="terkirim" and r.get("delivered_at"):
                add_history_event(supabase,r["case_id"],"LETTER_DELIVERED",r["delivered_at"],"Surat diterima",
                                  r.get("status_description"),"ETLE_SHIPPING")

        rows=supabase.table("etle_terminated_cases").select("case_id,terminated_at,reason").not_.is_("case_id","null").execute().data
        for r in rows:
            if r.get("terminated_at"):
                add_history_event(supabase,r["case_id"],"CASE_STOPPED",f"{r['terminated_at']}T00:00:00+07:00",
                                  "Perkara dihentikan",r.get("reason"),"ETLE_DIHENTIKAN")

        write_sync_log(supabase,"LINK_HISTORY",started,"SUCCESS" if failed==0 else "PARTIAL",linked,linked,failed)
        return {"linked":linked,"failed":failed}
    except Exception as e:
        write_sync_log(supabase,"LINK_HISTORY",started,"FAILED",0,linked,failed,str(e)); raise

def main():
    print("="*72)
    print("G-SMART ETLE MULTI-MODULE SYNC V2 -> SUPABASE")
    print("="*72)
    log(f"Tanggal API     : {DATE_FROM} s/d {DATE_TO}")
    log(f"Headless        : {HEADLESS}")
    log(f"Sync limit      : {SYNC_LIMIT}")
    validate_environment()
    supabase=create_supabase()
    validate_tables(supabase)
    summaries={}
    with sync_playwright() as pw:
        browser=None
        try:
            browser=pw.chromium.launch(headless=HEADLESS,args=["--no-sandbox","--disable-setuid-sandbox","--disable-dev-shm-usage","--disable-gpu"])
            page=browser.new_context(viewport={"width":1920,"height":1080}).new_page()
            login_etle(page)
            open_blanko_page(page)
            summaries["shipping"]=sync_shipping(page,supabase)
            summaries["disputes"]=sync_disputes(page,supabase)
            summaries["blanko"]=sync_blanko(page,supabase)
            summaries["terminated"]=sync_terminated(page,supabase)
            summaries["link_history"]=link_orphans_and_history(supabase)
        finally:
            if browser:
                try: browser.close(); log("Browser ditutup.")
                except Exception: pass
    print("\n"+"="*72+"\nSYNC V2 SELESAI\n"+"="*72)
    for module,summary in summaries.items():
        print(f"{module:14s}: {json.dumps(summary, ensure_ascii=False)}")
    print("="*72)

if __name__=="__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Proses dihentikan oleh pengguna.")
    except Exception as e:
        print("\n"+"="*72+"\n[ERROR]\n"+"="*72)
        print(str(e))
        print("="*72)
        raise
