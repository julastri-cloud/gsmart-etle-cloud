import os
import json
import time
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlencode

import requests

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from supabase import create_client

load_dotenv()
WIB = ZoneInfo("Asia/Jakarta")

# ============================================================
# ETLE ENDPOINTS
# ============================================================
URL_LOGIN = "https://etilang-djpd.kemenhub.go.id:9000/main/"
URL_BLANKO_PAGE = "https://etilang-djpd.kemenhub.go.id:9000/admin-etle/tertagih.php"
URL_LIST_BLANKO = "https://etilang-djpd.kemenhub.go.id:9000/etle/admin-etle/list_tertagih.php"
URL_DETAIL_BLANKO = "https://etilang-djpd.kemenhub.go.id:9000/etle/admin-etle/tertagih.php"
URL_PRINTED = "https://etilang-djpd.kemenhub.go.id:9000/etle/admin-etle/penindakan_printed_list.php"
URL_DISPUTES = "https://etilang-djpd.kemenhub.go.id:9000/etle/admin-etle/list_terkonfirmasi.php"
URL_TERMINATED = "https://etilang-djpd.kemenhub.go.id:9000/etle/admin-etle/datalisthentikanblokir.php"

# ============================================================
# ENVIRONMENT / MODE
# ============================================================
EMAIL_ETLE = os.getenv("EMAIL_ETLE", "").strip()
PASSWORD_ETLE = os.getenv("PASSWORD_ETLE", "").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
FONNTE_TOKEN = os.getenv("FONNTE_TOKEN", "").strip()
WA_TARGET = os.getenv("WA_TARGET", "").strip()

SYNC_MODE = os.getenv("SYNC_MODE", "incremental").strip().lower()
FULL_DATE_FROM = os.getenv("DATE_FROM", "01-08-2026").strip()
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "14"))
TEST_LIMIT = int(os.getenv("TEST_LIMIT", "5"))
HEADLESS = os.getenv("HEADLESS", "true").strip().lower() == "true"
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.35"))
MAX_RETRY = int(os.getenv("MAX_RETRY", "3"))
PRINTED_PAGE_SIZE = int(os.getenv("PRINTED_PAGE_SIZE", "100"))

if SYNC_MODE not in {"incremental", "full", "test"}:
    raise RuntimeError("SYNC_MODE harus incremental, full, atau test")

TODAY = datetime.now(WIB).date()
DATE_TO = TODAY.strftime("%d-%m-%Y")
if SYNC_MODE == "full":
    DATE_FROM = FULL_DATE_FROM
else:
    DATE_FROM = (TODAY - timedelta(days=LOOKBACK_DAYS)).strftime("%d-%m-%Y")

SYNC_LIMIT = TEST_LIMIT if SYNC_MODE == "test" else 0

REQUIRED_TABLES = [
    "etle_blanko_detail", "etle_cases", "etle_offenders", "etle_vehicles",
    "etle_photos", "etle_payments", "etle_shipping", "etle_disputes",
    "etle_court_info", "etle_terminated_cases", "gsmart_case_history",
    "gsmart_sync_log", "gsmart_sync_state"
]

# ============================================================
# GENERAL HELPERS
# ============================================================
def log(message):
    print(f"[{datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def clean(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def now_iso():
    return datetime.now(WIB).isoformat()


def parse_date_any(value):
    value = clean(value)
    if not value:
        return None
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def parse_datetime_any(value):
    value = clean(value)
    if not value:
        return None
    for fmt in (
        "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M"
    ):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=WIB).isoformat()
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=WIB)
        return dt.isoformat()
    except ValueError:
        return None


def numeric(value):
    value = clean(value)
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def ddmmyyyy_to_iso(value):
    return datetime.strptime(value, "%d-%m-%Y").strftime("%Y-%m-%d")


def extract_delivery_datetime(desc):
    desc = clean(desc)
    if not desc:
        return None
    m = re.search(r"\|\s*(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2})\s*\|", desc)
    return parse_datetime_any(m.group(1)) if m else None


def compact_row(row):
    return {k: v for k, v in row.items() if v is not None}

# ============================================================
# ENV / SUPABASE
# ============================================================
def validate_environment():
    missing = [k for k, v in {
        "EMAIL_ETLE": EMAIL_ETLE,
        "PASSWORD_ETLE": PASSWORD_ETLE,
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_SERVICE_ROLE_KEY": SUPABASE_SERVICE_ROLE_KEY,
    }.items() if not v]
    if missing:
        raise RuntimeError("Environment belum lengkap: " + ", ".join(missing))
    if "/rest/v1" in SUPABASE_URL:
        raise RuntimeError("SUPABASE_URL tidak boleh mengandung /rest/v1")
    if SUPABASE_SERVICE_ROLE_KEY.startswith("sb_publishable_"):
        raise RuntimeError("Backend harus memakai server/service-role key")


def create_supabase():
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def validate_tables(supabase):
    missing = []
    for table in REQUIRED_TABLES:
        try:
            supabase.table(table).select("*").limit(1).execute()
        except Exception:
            missing.append(table)
    if missing:
        raise RuntimeError("Tabel Supabase belum siap: " + ", ".join(missing))


def upsert(supabase, table, row, conflict):
    return supabase.table(table).upsert(row, on_conflict=conflict).execute().data


def update_sync_state(supabase, module, status="SUCCESS"):
    upsert(supabase, "gsmart_sync_state", {
        "module": module,
        "last_success_at": now_iso() if status == "SUCCESS" else None,
        "last_date_from": ddmmyyyy_to_iso(DATE_FROM),
        "last_date_to": ddmmyyyy_to_iso(DATE_TO),
        "updated_at": now_iso(),
    }, "module")


def write_sync_log(supabase, module, started_at, status, found=0, updated=0, failed=0, error=None):
    try:
        supabase.table("gsmart_sync_log").insert({
            "module": module,
            "started_at": started_at,
            "finished_at": now_iso(),
            "status": status,
            "rows_found": found,
            "rows_inserted": 0,
            "rows_updated": updated,
            "rows_failed": failed,
            "error_message": clean(error),
            "created_at": now_iso(),
        }).execute()
    except Exception as exc:
        log(f"Gagal menulis sync log {module}: {exc}")

# ============================================================
# ETLE LOGIN / FETCH
# ============================================================
def login_etle(page):
    log("Login ETLE...")
    page.goto(URL_LOGIN, wait_until="domcontentloaded", timeout=60000)
    email = page.locator('input[placeholder="Email"]')
    password = page.locator('input[placeholder="Password"]')
    email.wait_for(state="visible", timeout=30000)
    password.wait_for(state="visible", timeout=30000)
    email.fill(EMAIL_ETLE)
    password.fill(PASSWORD_ETLE)
    page.locator('button:has-text("Login")').click()
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    page.wait_for_timeout(1500)
    if "/main/" in page.url:
        raise RuntimeError("Login ETLE gagal")
    log("Login ETLE berhasil.")


def open_blanko_page(page):
    page.goto(URL_BLANKO_PAGE, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1200)
    if "/main/" in page.url:
        raise RuntimeError("Session ETLE tidak aktif")


def browser_fetch(page, url):
    result = page.evaluate("""async (url) => {
      try {
        const r = await fetch(url, {
          method: "GET", credentials: "include", cache: "no-store",
          headers: {"Accept":"application/json, text/javascript, */*; q=0.01", "X-Requested-With":"XMLHttpRequest"}
        });
        return {ok:true,status:r.status,body:await r.text()};
      } catch(e) { return {ok:false,status:0,body:"",error:String(e)}; }
    }""", url)
    if not result.get("ok"):
        raise RuntimeError("Fetch gagal: " + result.get("error", "unknown"))
    if result.get("status") != 200:
        raise RuntimeError(f"HTTP {result.get('status')}: {result.get('body','')[:500]}")
    body = result.get("body", "")
    if not body.strip():
        raise RuntimeError("Response API kosong")
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Response bukan JSON valid: {exc}; {body[:500]}")


# ============================================================
# WHATSAPP / FONNTE
# ============================================================
def wa_enabled():
    return bool(FONNTE_TOKEN and WA_TARGET)


def send_fonnte_message(message):
    """
    Kirim satu pesan WhatsApp melalui Fonnte.
    Kegagalan WA tidak boleh menggagalkan sinkronisasi ETLE/Supabase.
    """
    if not wa_enabled():
        log("WA Blast dilewati: FONNTE_TOKEN/WA_TARGET belum tersedia.")
        return False

    try:
        response = requests.post(
            "https://api.fonnte.com/send",
            headers={"Authorization": FONNTE_TOKEN},
            data={
                "target": WA_TARGET,
                "message": message,
            },
            timeout=30,
        )
        response.raise_for_status()

        # Fonnte umumnya mengembalikan JSON. Tetap toleran jika respons bukan JSON.
        try:
            payload = response.json()
        except Exception:
            payload = {"raw": response.text[:500]}

        # HTTP 2xx belum tentu berarti provider menerima request secara logis.
        if isinstance(payload, dict):
            status_value = payload.get("status")
            if status_value is False or str(status_value).lower() == "false":
                log(f"WA Blast gagal menurut respons Fonnte: {payload}")
                return False

        log(f"WA Blast berhasil dikirim ke target grup. Respons: {payload}")
        return True
    except Exception as exc:
        log(f"WA Blast gagal, tetapi sync tetap dilanjutkan: {exc}")
        return False


def build_wa_notification(new_blanko, new_disputes):
    """
    Bangun satu rangkuman per run.
    Hanya Blanko baru dan Tersanggah baru yang masuk notifikasi.
    """
    if not new_blanko and not new_disputes:
        return None

    lines = [
        "📢 *G-SMART ETLE*",
        "",
        "Terdapat pembaruan data ETLE:",
    ]

    if new_blanko:
        lines += [
            "",
            f"📄 *Blanko Tilang Baru: {len(new_blanko)}*",
        ]
        for row in new_blanko[:5]:
            label = row.get("ref_number") or row.get("no_blanko") or row.get("violation_id") or "-"
            tnkb = row.get("tnkb")
            lines.append(f"• {label}" + (f" | {tnkb}" if tnkb else ""))
        if len(new_blanko) > 5:
            lines.append(f"• ... dan {len(new_blanko) - 5} data lainnya")

    if new_disputes:
        lines += [
            "",
            f"⚠️ *Pelanggaran Tersanggah Baru: {len(new_disputes)}*",
        ]
        for row in new_disputes[:5]:
            label = row.get("ref_number") or row.get("violation_id") or "-"
            tnkb = row.get("tnkb")
            lines.append(f"• {label}" + (f" | {tnkb}" if tnkb else ""))
        if len(new_disputes) > 5:
            lines.append(f"• ... dan {len(new_disputes) - 5} data lainnya")

    lines += [
        "",
        "Silakan buka aplikasi *G-SMART* untuk melihat detail.",
        "",
        "_Notifikasi otomatis G-SMART UPPKB Guyangan_",
    ]
    return "\n".join(lines)


def send_sync_wa_notification(new_blanko, new_disputes):
    message = build_wa_notification(new_blanko, new_disputes)
    if not message:
        log("WA Blast: tidak ada Blanko/Tersanggah baru.")
        return False
    return send_fonnte_message(message)

# ============================================================
# CASE RESOLUTION
# ============================================================
def get_case_by_ref(supabase, ref_number):
    ref_number = clean(ref_number)
    if not ref_number:
        return None
    data = supabase.table("etle_cases").select("case_id,violation_id,ref_number,tnkb").eq("ref_number", ref_number).limit(1).execute().data
    return data[0] if data else None


def get_case_by_violation(supabase, violation_id):
    violation_id = clean(violation_id)
    if not violation_id:
        return None
    data = supabase.table("etle_cases").select("case_id,violation_id,ref_number,tnkb").eq("violation_id", str(violation_id)).limit(1).execute().data
    return data[0] if data else None


def update_case(supabase, case_id, row):
    row = compact_row(row)
    row["last_sync_at"] = now_iso()
    supabase.table("etle_cases").update(row).eq("case_id", case_id).execute()
    return supabase.table("etle_cases").select("case_id,violation_id,ref_number,tnkb").eq("case_id", case_id).limit(1).execute().data[0]


def ensure_case(supabase, *, ref_number=None, violation_id=None, tnkb=None,
                jenis_pelanggaran=None, lokasi=None, tanggal_pelanggaran=None,
                nama_pemilik=None, status_etle=None, raw_data=None):
    ref_number = clean(ref_number)
    violation_id = clean(violation_id)

    # 1) ref_number adalah penghubung lintas proses utama.
    case = get_case_by_ref(supabase, ref_number) if ref_number else None
    # 2) Jika ref belum ada, gunakan violation_id ketika tersedia.
    if not case and violation_id:
        case = get_case_by_violation(supabase, violation_id)

    patch = {
        "ref_number": ref_number,
        "violation_id": str(violation_id) if violation_id else None,
        "tnkb": clean(tnkb),
        "jenis_pelanggaran": clean(jenis_pelanggaran),
        "lokasi": clean(lokasi),
        "tanggal_pelanggaran": parse_datetime_any(tanggal_pelanggaran),
        "nama_pemilik": clean(nama_pemilik),
        "status_etle": clean(status_etle),
        "raw_data": raw_data,
    }

    if case:
        # Jangan menimpa violation_id yang sudah terisi dengan NULL.
        return update_case(supabase, case["case_id"], patch)

    insert_row = compact_row(patch)
    insert_row["first_seen_at"] = now_iso()
    insert_row["last_sync_at"] = now_iso()

    # Case baru bisa lahir dari Shipping/Dihentikan tanpa violation_id.
    if ref_number:
        upsert(supabase, "etle_cases", insert_row, "ref_number")
        return get_case_by_ref(supabase, ref_number)
    if violation_id:
        upsert(supabase, "etle_cases", insert_row, "violation_id")
        return get_case_by_violation(supabase, violation_id)
    raise RuntimeError("Tidak bisa membuat case tanpa ref_number/violation_id")

# ============================================================
# HISTORY
# ============================================================
def history_exists(supabase, case_id, event_type, event_time, source):
    q = supabase.table("gsmart_case_history").select("history_id").eq("case_id", case_id).eq("event_type", event_type).eq("source", source)
    if event_time:
        q = q.eq("event_time", event_time)
    return bool(q.limit(1).execute().data)


def add_history_event(supabase, case_id, event_type, event_time, title, description=None, source="ETLE"):
    if not case_id or not event_time:
        return False
    if history_exists(supabase, case_id, event_type, event_time, source):
        return False
    supabase.table("gsmart_case_history").insert({
        "case_id": case_id,
        "event_type": event_type,
        "event_time": event_time,
        "title": title,
        "description": clean(description),
        "source": source,
        "created_at": now_iso(),
    }).execute()
    return True

# ============================================================
# SHIPPING
# ============================================================
PRINTED_COLUMNS = [
    "inserted_date", "display_date", "ref_number", "plat_number", "alamat_regiden",
    "wilayah_satuan", "wilayah_induk", "no_resi", "pelanggaran", "validasi_date",
    "status", "aksi"
]


def build_printed_url(start, length, draw):
    p = {
        "draw": draw,
        "order[0][column]": 0,
        "order[0][dir]": "asc",
        "start": start,
        "length": length,
        "search[value]": "",
        "search[regex]": "false",
        "date": f"{DATE_FROM} 00:00",
        "date1": f"{DATE_TO} 23:59",
        "selectAll": "no",
        "provinsi": "",
        "status": "Sudah_Dicetak",
        "_": int(time.time() * 1000),
    }
    for i, field in enumerate(PRINTED_COLUMNS):
        p[f"columns[{i}][data]"] = field
        p[f"columns[{i}][name]"] = ""
        p[f"columns[{i}][searchable]"] = "true"
        p[f"columns[{i}][orderable]"] = "true"
        p[f"columns[{i}][search][value]"] = ""
        p[f"columns[{i}][search][regex]"] = "false"
    return URL_PRINTED + "?" + urlencode(p)


def get_printed_list(page):
    rows, start, draw = [], 0, 1
    while True:
        parsed = browser_fetch(page, build_printed_url(start, PRINTED_PAGE_SIZE, draw))
        batch = parsed.get("data", [])
        total = int(parsed.get("recordsFiltered", parsed.get("recordsTotal", len(batch))) or 0)
        if not isinstance(batch, list):
            raise RuntimeError("JSON Surat Dicetak tidak dikenali")
        rows.extend(batch)
        log(f"Shipping API: {len(rows)}/{total}")
        if not batch or len(rows) >= total:
            break
        start += len(batch)
        draw += 1
    return rows[:SYNC_LIMIT] if SYNC_LIMIT > 0 else rows


def sync_shipping(page, supabase):
    started = now_iso(); found = ok = failed = 0
    try:
        rows = get_printed_list(page); found = len(rows)
        for i, item in enumerate(rows, 1):
            try:
                ref = clean(item.get("ref_number"))
                if not ref:
                    raise RuntimeError("ref_number kosong")
                case = ensure_case(
                    supabase,
                    ref_number=ref,
                    tnkb=item.get("plat_number"),
                    jenis_pelanggaran=item.get("pelanggaran") or item.get("report_type"),
                    lokasi=item.get("lokasi_cam"),
                    tanggal_pelanggaran=item.get("inserted_date"),
                    nama_pemilik=item.get("nama_pemilik"),
                    status_etle="SURAT_DICETAK",
                    raw_data=item,
                )
                printed_date = parse_date_any(item.get("printed_date") or item.get("display_date"))
                delivered = extract_delivery_datetime(item.get("desc_terakhir"))
                status = clean(item.get("status"))
                shipping_row = {
                    "source_id": str(item.get("id")),
                    "case_id": case["case_id"],
                    "violation_id": case.get("violation_id"),
                    "ref_number": ref,
                    "tnkb": clean(item.get("plat_number")),
                    "nama_pemilik": clean(item.get("nama_pemilik")),
                    "alamat_pemilik": clean(item.get("alamat_regiden")),
                    "wilayah_satuan": clean(item.get("wilayah_satuan")),
                    "wilayah_induk": clean(item.get("wilayah_induk")),
                    "jenis_pelanggaran": clean(item.get("pelanggaran") or item.get("report_type")),
                    "tanggal_pelanggaran": parse_datetime_any(item.get("inserted_date")),
                    "printed_date": printed_date,
                    "validasi_date": parse_date_any(item.get("validasi_date")),
                    "tracking_number": clean(item.get("no_resi")),
                    "courier": "JNE" if clean(item.get("no_resi")) else None,
                    "status": status,
                    "status_description": clean(item.get("desc_terakhir")),
                    "printed_at": f"{printed_date}T00:00:00+07:00" if printed_date else None,
                    "delivered_at": delivered if status and status.lower() == "terkirim" else None,
                    "last_event_at": delivered,
                    "raw_data": item,
                    "updated_at": now_iso(),
                }
                upsert(supabase, "etle_shipping", compact_row(shipping_row), "source_id")
                if shipping_row.get("printed_at"):
                    add_history_event(supabase, case["case_id"], "LETTER_PRINTED", shipping_row["printed_at"], "Surat tilang dicetak", f"TNKB {shipping_row.get('tnkb')}", "ETLE_SHIPPING")
                if shipping_row.get("delivered_at"):
                    add_history_event(supabase, case["case_id"], "LETTER_DELIVERED", shipping_row["delivered_at"], "Surat diterima", shipping_row.get("status_description"), "ETLE_SHIPPING")
                ok += 1
                log(f"[SHIPPING {i}/{found}] {ref} -> OK")
            except Exception as exc:
                failed += 1; log(f"[SHIPPING {i}/{found}] GAGAL: {exc}")
        status = "SUCCESS" if failed == 0 else "PARTIAL"
        write_sync_log(supabase, "SHIPPING", started, status, found, ok, failed)
        if failed == 0: update_sync_state(supabase, "SHIPPING")
        return {"found": found, "success": ok, "failed": failed}
    except Exception as exc:
        write_sync_log(supabase, "SHIPPING", started, "FAILED", found, ok, failed, str(exc)); raise

# ============================================================
# BLANKO + DETAIL
# ============================================================
def get_blanko_list(page):
    url = f"{URL_LIST_BLANKO}?dateFrom={DATE_FROM}&dateTo={DATE_TO}&status=&_={int(time.time()*1000)}"
    parsed = browser_fetch(page, url)
    if isinstance(parsed, list):
        rows = parsed
    elif isinstance(parsed, dict):
        rows = next((parsed[k] for k in ("data", "rows", "result", "aaData") if isinstance(parsed.get(k), list)), None)
        if rows is None:
            raise RuntimeError("JSON daftar Blanko tidak dikenali")
    else:
        raise RuntimeError("JSON daftar Blanko tidak dikenali")
    return rows[:SYNC_LIMIT] if SYNC_LIMIT > 0 else rows


def get_blanko_detail(page, violation_id):
    parsed = browser_fetch(page, f"{URL_DETAIL_BLANKO}?violation_id={violation_id}")
    if isinstance(parsed, list):
        if not parsed: raise RuntimeError("Detail Blanko kosong")
        return parsed[0]
    if isinstance(parsed, dict):
        if isinstance(parsed.get("data"), list):
            if not parsed["data"]: raise RuntimeError("Detail Blanko kosong")
            return parsed["data"][0]
        if isinstance(parsed.get("data"), dict):
            return parsed["data"]
        return parsed
    raise RuntimeError("JSON detail Blanko tidak dikenali")


def sanitize_detail(detail):
    result = dict(detail)
    result.pop("json_response", None)
    result.pop("jsonResponse", None)
    # Jangan menyimpan credential-like field ke raw_data baru.
    for key in ("password", "passwd", "token", "access_token", "refresh_token"):
        result.pop(key, None)
    return result


def build_legacy_row(item, detail):
    vid = clean(detail.get("violation_id") or item.get("violation_id"))
    if not vid: raise RuntimeError("violation_id kosong")
    ref = clean(detail.get("ref_number") or detail.get("pelanggar_ref_number") or item.get("ref_number"))
    plat = clean(detail.get("plat_number") or detail.get("no_registrasi_kendaraan") or item.get("plat_number"))
    row = {
        "violation_id": str(vid),
        "ref_number": ref,
        "plat_number": plat,
        "no_briva": clean(detail.get("no_briva") or item.get("no_briva")),
        "no_blanko": clean(detail.get("blanko_no") or item.get("blanko_no")),
        "status": clean(detail.get("status") or detail.get("status_bayar") or item.get("status_bayar") or item.get("status")),
        "pelanggaran": clean(detail.get("pelanggaran") or detail.get("report_type") or item.get("report_type")),
        "tanggal_pelanggaran": clean(detail.get("inserted_date_vl") or detail.get("validasi_date") or item.get("inserted_date_vl")),
        "tanggal_tagih": clean(detail.get("tertagih_date_date") or detail.get("tertagih_date") or item.get("blanko_date")),
        "tanggal_sidang": clean(detail.get("tanggal_sidang_etle") or detail.get("tanggal_sidang_kejaksaan")),
        "nama_pemilik": clean(detail.get("pemilik_stnk") or detail.get("nama_pemilik")),
        "alamat_pemilik": clean(detail.get("alamat_pemilik")),
        "jenis_kendaraan": clean(detail.get("jenis_kendaraan")),
        "merk": clean(detail.get("merk") or detail.get("merk_kendaraan")),
        "tipe": clean(detail.get("tipe")),
        "masa_berlaku_kir": clean(detail.get("masa_berlaku_kir") or detail.get("masa_berlaku")),
        "foto_kendaraan": clean(detail.get("foto_kendaraan") or detail.get("foto")),
        "foto_plat": clean(detail.get("foto_plat")),
        "raw_data": {"list_data": item, "detail_data": sanitize_detail(detail)},
        "last_sync_at": now_iso(),
    }
    return row


def sync_normalized_blanko(supabase, item, d, legacy):
    vid = legacy["violation_id"]
    ref = legacy.get("ref_number")
    case = ensure_case(
        supabase,
        ref_number=ref,
        violation_id=vid,
        tnkb=legacy.get("plat_number"),
        jenis_pelanggaran=d.get("report_type") or d.get("pelanggaran") or legacy.get("pelanggaran"),
        lokasi=d.get("lokasi") or item.get("lokasi"),
        tanggal_pelanggaran=d.get("inserted_date_vl") or item.get("inserted_date_vl"),
        nama_pemilik=d.get("nama_pemilik") or d.get("pemilik_stnk") or legacy.get("nama_pemilik"),
        status_etle="BLANKO_TERBIT",
        raw_data=legacy.get("raw_data"),
    )
    cid = case["case_id"]

    # Lengkapi kolom case spesifik blanko tanpa menghapus nilai lama.
    update_case(supabase, cid, {
        "no_registrasi": clean(d.get("nomor_registrasi") or ref),
        "pasal": clean(d.get("pasal")),
        "status_bayar": clean(item.get("status_bayar") or d.get("status")),
        "no_blanko": legacy.get("no_blanko"),
        "no_briva": legacy.get("no_briva"),
        "tanggal_blanko": parse_date_any(d.get("blanko_date") or item.get("blanko_date")),
        "tanggal_sidang": parse_date_any(d.get("tanggal_sidang_etle") or legacy.get("tanggal_sidang")),
    })

    upsert(supabase, "etle_offenders", compact_row({
        "case_id": cid, "violation_id": vid,
        "nama": clean(d.get("pelanggar_nama")),
        "alamat": clean(d.get("pelanggar_alamat")),
        "no_telp": clean(d.get("pelanggar_notel") or d.get("notel")),
        "email": clean(d.get("pelanggar_email")),
        "no_ktp": clean(d.get("no_ktp")),
        "no_sim": clean(d.get("no_sim")),
        "golongan_sim": clean(d.get("golongan_sim")),
        "masa_berlaku_sim": parse_date_any(d.get("masa_berlaku_sim")),
        "tempat_lahir": clean(d.get("tempat_lahir")),
        "tanggal_lahir": parse_date_any(d.get("ttl")),
        "jenis_kelamin": clean(d.get("jenis_kelamin")),
        "pekerjaan": clean(d.get("pekerjaan")),
        "satpas_penerbit": clean(d.get("satpas_penerbit")),
        "updated_at": now_iso(),
    }), "case_id")

    upsert(supabase, "etle_vehicles", compact_row({
        "case_id": cid, "violation_id": vid,
        "nama_pemilik": clean(d.get("nama_pemilik") or d.get("pemilik_stnk")),
        "alamat_pemilik": clean(d.get("alamat_pemilik")),
        "merk": clean(d.get("merk") or d.get("merk_kendaraan")),
        "tipe": clean(d.get("tipe")),
        "jenis_kendaraan": clean(d.get("jenis_kendaraan")),
        "tahun_rakit": clean(d.get("tahun_rakit")),
        "bahan_bakar": clean(d.get("bahan_bakar")),
        "no_rangka": clean(d.get("no_rangka")),
        "no_mesin": clean(d.get("no_mesin")),
        "no_uji": clean(d.get("nouji")),
        "masa_berlaku_kir": parse_date_any(d.get("masa_berlaku_kir") or d.get("masa_berlaku")),
        "jbb": numeric(d.get("jbb")), "jbi": numeric(d.get("jbi")),
        "berat_kosong": numeric(d.get("berat_kosong")),
        "berat_timbang": numeric(d.get("berat_timbang")),
        "berat_lebih": numeric(d.get("berat_lebih")),
        "panjang_kendaraan": numeric(d.get("panjang_kendaraan")),
        "lebar_kendaraan": numeric(d.get("lebar_kendaraan")),
        "tinggi_kendaraan": numeric(d.get("tinggi_kendaraan")),
        "updated_at": now_iso(),
    }), "case_id")

    upsert(supabase, "etle_payments", compact_row({
        "case_id": cid, "violation_id": vid,
        "no_briva": clean(d.get("no_briva") or item.get("no_briva")),
        "status_bayar": clean(item.get("status_bayar") or d.get("status")),
        "titipan": numeric(item.get("titipan")),
        "denda_maksimum": numeric(d.get("denda_maksimum")),
        "denda_pengadilan": numeric(d.get("denda_pengadilan")),
        "biaya_perkara": numeric(d.get("biaya_perkara")),
        "total_amount": numeric(d.get("total_amount")),
        "paid_amount": numeric(d.get("denda_bayar")),
        "nominal_sisa": numeric(d.get("nominal_sisa")),
        "paid_at": parse_datetime_any(d.get("paid_date")),
        "payment_at": parse_datetime_any(d.get("payment_at")),
        "updated_at": now_iso(),
    }), "case_id")

    court_date = parse_date_any(d.get("tanggal_sidang_etle") or d.get("tanggal_sidang_kejaksaan"))
    upsert(supabase, "etle_court_info", compact_row({
        "case_id": cid, "violation_id": vid,
        "tanggal_sidang": court_date,
        "lokasi_sidang": clean(d.get("lokasi_sidang")),
        "pengadilan": clean(d.get("court_place")),
        "pengadilan_id": clean(d.get("pengadilan_id")),
        "kejaksaan": clean(d.get("lokasi_kejaksaan")),
        "kejaksaan_id": clean(d.get("kejaksaan_id")),
        "hakim": clean(d.get("hakim")),
        "panitera": clean(d.get("panitera")),
        "no_amar_putusan": clean(d.get("no_amar_putusan")),
        "denda_putusan": numeric(d.get("denda_pengadilan")),
        "biaya_perkara": numeric(d.get("biaya_perkara")),
        "status_sidang": "COMPLETED" if clean(d.get("no_amar_putusan")) else ("SCHEDULED" if court_date else None),
        "updated_at": now_iso(),
    }), "case_id")

    for ptype, purl, desc, order in [
        ("VEHICLE", clean(d.get("foto_kendaraan") or d.get("foto")), "Foto kendaraan pelanggaran", 1),
        ("PLATE", clean(d.get("foto_plat")), "Foto plat nomor", 2),
    ]:
        if purl:
            upsert(supabase, "etle_photos", {
                "case_id": cid, "violation_id": vid, "photo_type": ptype,
                "photo_url": purl, "description": desc, "sort_order": order,
                "updated_at": now_iso(),
            }, "case_id,photo_type,photo_url")

    blanko_date = parse_date_any(d.get("blanko_date") or item.get("blanko_date"))
    if blanko_date:
        add_history_event(supabase, cid, "BLANKO_ISSUED", f"{blanko_date}T00:00:00+07:00", "Blanko tilang diterbitkan", f"Blanko {legacy.get('no_blanko')}" if legacy.get("no_blanko") else None, "ETLE_BLANKO")
    paid_at = parse_datetime_any(d.get("paid_date"))
    if paid_at:
        add_history_event(supabase, cid, "PAYMENT_RECEIVED", paid_at, "Pembayaran diterima", clean(item.get("status_bayar") or d.get("status")), "ETLE_BLANKO")
    if court_date:
        add_history_event(supabase, cid, "COURT_SCHEDULED", f"{court_date}T00:00:00+07:00", "Sidang terjadwal", clean(d.get("court_place")), "ETLE_BLANKO")


def sync_blanko(page, supabase):
    started = now_iso(); found = ok = failed = 0
    new_items = []
    try:
        rows = get_blanko_list(page); found = len(rows)
        for i, item in enumerate(rows, 1):
            vid = clean(item.get("violation_id"))
            if not vid:
                failed += 1; continue

            # "Baru" = violation_id belum ada di etle_blanko_detail SEBELUM upsert.
            existing = (
                supabase.table("etle_blanko_detail")
                .select("violation_id")
                .eq("violation_id", str(vid))
                .limit(1)
                .execute()
                .data
            )
            is_new = not bool(existing)

            last = None
            for attempt in range(1, MAX_RETRY + 1):
                try:
                    d = get_blanko_detail(page, vid)
                    legacy = build_legacy_row(item, d)
                    upsert(supabase, "etle_blanko_detail", legacy, "violation_id")
                    sync_normalized_blanko(supabase, item, d, legacy)

                    # Catat sebagai baru HANYA setelah seluruh proses record berhasil.
                    if is_new:
                        new_items.append({
                            "violation_id": str(vid),
                            "ref_number": legacy.get("ref_number"),
                            "no_blanko": legacy.get("no_blanko"),
                            "tnkb": legacy.get("plat_number"),
                        })

                    ok += 1; last = None
                    log(f"[BLANKO {i}/{found}] {vid} -> OK" + (" [BARU]" if is_new else ""))
                    break
                except Exception as exc:
                    last = exc; log(f"[BLANKO {i}/{found}] retry {attempt}/{MAX_RETRY}: {exc}")
                    if attempt < MAX_RETRY:
                        page.wait_for_timeout(attempt * 2000)
            if last is not None:
                failed += 1
            if REQUEST_DELAY > 0:
                page.wait_for_timeout(int(REQUEST_DELAY * 1000))

        status = "SUCCESS" if failed == 0 else "PARTIAL"
        write_sync_log(supabase, "BLANKO", started, status, found, ok, failed)
        if failed == 0: update_sync_state(supabase, "BLANKO")
        return {"found": found, "success": ok, "failed": failed, "new": len(new_items), "new_items": new_items}
    except Exception as exc:
        write_sync_log(supabase, "BLANKO", started, "FAILED", found, ok, failed, str(exc)); raise


# ============================================================
# DISPUTES
# ============================================================
def get_disputes(page):
    p = {"dateFrom": f"{DATE_FROM} 00:00", "dateTo": f"{DATE_TO} 23:59", "status": "Tersanggah", "_": int(time.time() * 1000)}
    parsed = browser_fetch(page, URL_DISPUTES + "?" + urlencode(p))
    rows = parsed.get("data", [])
    if not isinstance(rows, list): raise RuntimeError("JSON Tersanggah tidak dikenali")
    return rows[:SYNC_LIMIT] if SYNC_LIMIT > 0 else rows


def sync_disputes(page, supabase):
    started = now_iso(); found = ok = failed = 0
    new_items = []
    try:
        rows = get_disputes(page); found = len(rows)
        for i, item in enumerate(rows, 1):
            try:
                vid = clean(item.get("violation_id"))
                if not vid: raise RuntimeError("violation_id kosong")
                case = ensure_case(
                    supabase,
                    ref_number=item.get("ref_number"), violation_id=vid,
                    tnkb=item.get("plat_number"), jenis_pelanggaran=item.get("pelanggaran"),
                    lokasi=item.get("lokasi"), tanggal_pelanggaran=item.get("vl_inserted_date"),
                    status_etle="TERSANGGAH", raw_data=item,
                )

                # "Baru" = case_id belum ada di etle_disputes SEBELUM upsert.
                existing = (
                    supabase.table("etle_disputes")
                    .select("case_id")
                    .eq("case_id", case["case_id"])
                    .limit(1)
                    .execute()
                    .data
                )
                is_new = not bool(existing)

                conf = parse_datetime_any(item.get("confirmation_date"))
                upsert(supabase, "etle_disputes", compact_row({
                    "case_id": case["case_id"], "violation_id": vid,
                    "status": "TERSANGGAH",
                    "confirmation_type": clean(item.get("confirmation_type")),
                    "confirmation_date": conf,
                    "result": clean(item.get("litsus_code")),
                    "updated_at": now_iso(),
                }), "case_id")
                if conf:
                    add_history_event(
                        supabase, case["case_id"], "DISPUTE_RECEIVED", conf,
                        "Pelanggaran disanggah",
                        f"TNKB {item.get('plat_number')} | {item.get('pelanggaran')}",
                        "ETLE_TERSANGGAH"
                    )

                # Catat sebagai baru HANYA setelah upsert berhasil.
                if is_new:
                    new_items.append({
                        "case_id": case["case_id"],
                        "violation_id": str(vid),
                        "ref_number": clean(item.get("ref_number")) or case.get("ref_number"),
                        "tnkb": clean(item.get("plat_number")) or case.get("tnkb"),
                    })

                ok += 1
                log(f"[TERSANGGAH {i}/{found}] {vid} -> OK" + (" [BARU]" if is_new else ""))
            except Exception as exc:
                failed += 1; log(f"[TERSANGGAH {i}/{found}] GAGAL: {exc}")

        status = "SUCCESS" if failed == 0 else "PARTIAL"
        write_sync_log(supabase, "DISPUTES", started, status, found, ok, failed)
        if failed == 0: update_sync_state(supabase, "DISPUTES")
        return {"found": found, "success": ok, "failed": failed, "new": len(new_items), "new_items": new_items}
    except Exception as exc:
        write_sync_log(supabase, "DISPUTES", started, "FAILED", found, ok, failed, str(exc)); raise


# ============================================================
# TERMINATED
# ============================================================
def get_terminated(page):
    # Endpoint ini memang memakai format campuran:
    # dateFrom=YYYY-MM-DD, dateTo=DD-MM-YYYY
    p = {"dateFrom": ddmmyyyy_to_iso(DATE_FROM), "dateTo": DATE_TO, "_": int(time.time() * 1000)}
    parsed = browser_fetch(page, URL_TERMINATED + "?" + urlencode(p))
    rows = parsed.get("data", [])
    if not isinstance(rows, list): raise RuntimeError("JSON Dihentikan tidak dikenali")
    return rows[:SYNC_LIMIT] if SYNC_LIMIT > 0 else rows


def sync_terminated(page, supabase):
    started = now_iso(); found = ok = failed = 0
    try:
        rows = get_terminated(page); found = len(rows)
        for i, item in enumerate(rows, 1):
            try:
                ref = clean(item.get("ref_number"))
                if not ref: raise RuntimeError("ref_number kosong")
                case = ensure_case(
                    supabase,
                    ref_number=ref, tnkb=item.get("plat_number"), lokasi=item.get("lokasi"),
                    status_etle="DIHENTIKAN", raw_data=item,
                )
                term = parse_date_any(item.get("dihentikan_date"))
                upsert(supabase, "etle_terminated_cases", compact_row({
                    "case_id": case["case_id"], "violation_id": case.get("violation_id"),
                    "ref_number": ref, "tnkb": clean(item.get("plat_number")),
                    "lokasi": clean(item.get("lokasi")),
                    "status": clean(item.get("blokirnya") or "Dihentikan"),
                    "reason": clean(item.get("alasan_lainnya")),
                    "officer_name": clean(item.get("nama_user")),
                    "terminated_at": term, "raw_data": item, "updated_at": now_iso(),
                }), "ref_number")
                if term:
                    add_history_event(supabase, case["case_id"], "CASE_STOPPED", f"{term}T00:00:00+07:00", "Perkara dihentikan", clean(item.get("alasan_lainnya")), "ETLE_DIHENTIKAN")
                ok += 1; log(f"[DIHENTIKAN {i}/{found}] {ref} -> OK")
            except Exception as exc:
                failed += 1; log(f"[DIHENTIKAN {i}/{found}] GAGAL: {exc}")
        status = "SUCCESS" if failed == 0 else "PARTIAL"
        write_sync_log(supabase, "TERMINATED", started, status, found, ok, failed)
        if failed == 0: update_sync_state(supabase, "TERMINATED")
        return {"found": found, "success": ok, "failed": failed}
    except Exception as exc:
        write_sync_log(supabase, "TERMINATED", started, "FAILED", found, ok, failed, str(exc)); raise

# ============================================================
# FINAL LINK REPAIR (safety net only)
# ============================================================
def repair_links(supabase):
    started = now_iso(); linked = failed = 0
    try:
        for table, idcol in (("etle_shipping", "shipping_id"), ("etle_terminated_cases", "terminated_id")):
            rows = supabase.table(table).select(f"{idcol},ref_number").is_("case_id", "null").execute().data
            for row in rows:
                try:
                    case = get_case_by_ref(supabase, row.get("ref_number"))
                    if case:
                        supabase.table(table).update({
                            "case_id": case["case_id"],
                            "violation_id": case.get("violation_id"),
                            "updated_at": now_iso(),
                        }).eq(idcol, row[idcol]).execute()
                        linked += 1
                except Exception as exc:
                    failed += 1; log(f"Repair link {table} gagal: {exc}")
        status = "SUCCESS" if failed == 0 else "PARTIAL"
        write_sync_log(supabase, "LINK_REPAIR", started, status, linked, linked, failed)
        return {"linked": linked, "failed": failed}
    except Exception as exc:
        write_sync_log(supabase, "LINK_REPAIR", started, "FAILED", 0, linked, failed, str(exc)); raise

# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 76)
    print("G-SMART ETLE SYNC V3 - INCREMENTAL / FULL / TEST")
    print("=" * 76)
    log(f"Mode            : {SYNC_MODE}")
    log(f"Rentang API     : {DATE_FROM} s/d {DATE_TO}")
    log(f"Lookback        : {LOOKBACK_DAYS} hari")
    log(f"Test limit      : {SYNC_LIMIT}")

    validate_environment()
    supabase = create_supabase()
    validate_tables(supabase)

    summaries = {}
    with sync_playwright() as pw:
        browser = None
        try:
            browser = pw.chromium.launch(
                headless=HEADLESS,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            page = browser.new_context(viewport={"width": 1920, "height": 1080}).new_page()
            login_etle(page)
            open_blanko_page(page)

            # Satu login, empat sumber.
            summaries["shipping"] = sync_shipping(page, supabase)
            summaries["disputes"] = sync_disputes(page, supabase)
            summaries["blanko"] = sync_blanko(page, supabase)
            summaries["terminated"] = sync_terminated(page, supabase)
            summaries["link_repair"] = repair_links(supabase)

            # WA hanya untuk Blanko baru + Tersanggah baru.
            # Kegagalan WA tidak menggagalkan sync.
            send_sync_wa_notification(
                summaries["blanko"].get("new_items", []),
                summaries["disputes"].get("new_items", []),
            )
        finally:
            if browser:
                try:
                    browser.close(); log("Browser ditutup.")
                except Exception:
                    pass

    print("\n" + "=" * 76)
    print("SYNC V3 SELESAI")
    print("=" * 76)
    for module, summary in summaries.items():
        print(f"{module:14s}: {json.dumps(summary, ensure_ascii=False)}")
    print("=" * 76)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Proses dihentikan oleh pengguna")
    except Exception as exc:
        print("\n" + "=" * 76 + "\n[ERROR]\n" + "=" * 76)
        print(str(exc))
        print("=" * 76)
        raise
