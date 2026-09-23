import os
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from supabase import create_client


# ============================================================
# LOAD ENVIRONMENT
# ============================================================

load_dotenv()

WIB = ZoneInfo("Asia/Jakarta")


# ============================================================
# KONFIGURASI ETLE
# ============================================================

URL_LOGIN = (
    "https://etilang-djpd.kemenhub.go.id:9000/main/"
)

URL_BLANKO_PAGE = (
    "https://etilang-djpd.kemenhub.go.id:9000/"
    "admin-etle/tertagih.php"
)

URL_LIST_BLANKO = (
    "https://etilang-djpd.kemenhub.go.id:9000/"
    "etle/admin-etle/list_tertagih.php"
)

URL_DETAIL_BLANKO = (
    "https://etilang-djpd.kemenhub.go.id:9000/"
    "etle/admin-etle/tertagih.php"
)


# ============================================================
# ENVIRONMENT
# ============================================================

EMAIL_ETLE = os.getenv(
    "EMAIL_ETLE",
    ""
).strip()

PASSWORD_ETLE = os.getenv(
    "PASSWORD_ETLE",
    ""
).strip()

SUPABASE_URL = os.getenv(
    "SUPABASE_URL",
    ""
).strip()

SUPABASE_SERVICE_ROLE_KEY = os.getenv(
    "SUPABASE_SERVICE_ROLE_KEY",
    ""
).strip()


# ============================================================
# PENGATURAN SYNC
# ============================================================

DATE_FROM = os.getenv(
    "DATE_FROM",
    "01-08-2026"
).strip()

DATE_TO = datetime.now(WIB).strftime(
    "%d-%m-%Y"
)

# 0 = semua data
# 1 = hanya 1 data
# 5 = hanya 5 data
SYNC_LIMIT = int(
    os.getenv(
        "SYNC_LIMIT",
        "0"
    )
)

# false = browser terlihat
# true  = browser tidak terlihat
HEADLESS = (
    os.getenv(
        "HEADLESS",
        "false"
    ).strip().lower()
    == "true"
)

# Jeda antar detail supaya request tidak terlalu agresif
REQUEST_DELAY = float(
    os.getenv(
        "REQUEST_DELAY",
        "0.5"
    )
)

MAX_RETRY = 3


# ============================================================
# LOG
# ============================================================

def log(message):

    waktu = datetime.now(WIB).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    print(
        f"[{waktu}] {message}",
        flush=True
    )


# ============================================================
# VALIDASI ENVIRONMENT
# ============================================================

def validate_environment():

    missing = []

    if not EMAIL_ETLE:
        missing.append(
            "EMAIL_ETLE"
        )

    if not PASSWORD_ETLE:
        missing.append(
            "PASSWORD_ETLE"
        )

    if not SUPABASE_URL:
        missing.append(
            "SUPABASE_URL"
        )

    if not SUPABASE_SERVICE_ROLE_KEY:
        missing.append(
            "SUPABASE_SERVICE_ROLE_KEY"
        )

    if missing:

        raise RuntimeError(
            "Environment belum lengkap: "
            + ", ".join(missing)
        )

    if "/rest/v1" in SUPABASE_URL:

        raise RuntimeError(
            "SUPABASE_URL tidak boleh mengandung /rest/v1. "
            "Gunakan hanya https://xxxxx.supabase.co"
        )

    log(
        "Environment berhasil divalidasi."
    )


# ============================================================
# CLEAN VALUE
# ============================================================

def clean(value):

    if value is None:
        return None

    if isinstance(
        value,
        str
    ):

        value = value.strip()

        if not value:
            return None

        return value

    return value


# ============================================================
# SUPABASE CLIENT
# ============================================================

def create_supabase():

    log(
        "Menghubungkan ke Supabase..."
    )

    client = create_client(
        SUPABASE_URL,
        SUPABASE_SERVICE_ROLE_KEY
    )

    log(
        "Supabase siap."
    )

    return client


# ============================================================
# LOGIN ETLE
# ============================================================

def login_etle(page):

    log(
        "Membuka halaman login ETLE..."
    )

    page.goto(
        URL_LOGIN,
        wait_until="domcontentloaded",
        timeout=60000
    )

    email_input = page.locator(
        'input[placeholder="Email"]'
    )

    password_input = page.locator(
        'input[placeholder="Password"]'
    )

    email_input.wait_for(
        state="visible",
        timeout=30000
    )

    password_input.wait_for(
        state="visible",
        timeout=30000
    )

    email_input.fill(
        EMAIL_ETLE
    )

    password_input.fill(
        PASSWORD_ETLE
    )

    log(
        "Email dan password ETLE diisi."
    )

    login_button = page.locator(
        'button:has-text("Login")'
    )

    login_button.click()

    log(
        "Tombol Login ditekan."
    )

    try:

        page.wait_for_load_state(
            "networkidle",
            timeout=30000
        )

    except Exception:

        log(
            "Networkidle timeout. "
            "Melanjutkan verifikasi login."
        )

    page.wait_for_timeout(
        2000
    )

    log(
        f"URL setelah login: {page.url}"
    )

    if "/main/" in page.url:

        raise RuntimeError(
            "Login ETLE gagal. "
            "Masih berada di halaman login."
        )

    log(
        "Login ETLE berhasil."
    )


# ============================================================
# BUKA HALAMAN BLANKO
# ============================================================

def open_blanko_page(page):

    log(
        "Membuka halaman Blanko "
        "untuk membentuk konteks session..."
    )

    page.goto(
        URL_BLANKO_PAGE,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(
        1500
    )

    if "/main/" in page.url:

        raise RuntimeError(
            "Session ETLE tidak aktif. "
            "Halaman Blanko kembali ke login."
        )


# ============================================================
# FETCH DARI DALAM BROWSER
# ============================================================

def browser_fetch(page, url):

    result = page.evaluate(
        """
        async (url) => {

            try {

                const response = await fetch(
                    url,
                    {
                        method: "GET",

                        credentials: "include",

                        cache: "no-store",

                        headers: {

                            "Accept":
                                "application/json, "
                                + "text/javascript, "
                                + "*/*; q=0.01",

                            "X-Requested-With":
                                "XMLHttpRequest"
                        }
                    }
                );

                const text =
                    await response.text();

                return {

                    success: true,

                    status:
                        response.status,

                    contentType:
                        response.headers.get(
                            "content-type"
                        ) || "",

                    body:
                        text
                };

            }

            catch (error) {

                return {

                    success: false,

                    status: 0,

                    contentType: "",

                    body: "",

                    error:
                        String(error)
                };
            }
        }
        """,
        url
    )

    if not result.get(
        "success"
    ):

        raise RuntimeError(
            "Fetch gagal: "
            + result.get(
                "error",
                "unknown"
            )
        )

    status = result.get(
        "status"
    )

    body = result.get(
        "body",
        ""
    )

    if status != 200:

        raise RuntimeError(
            f"HTTP {status}. "
            f"Response: {body[:500]}"
        )

    if not body.strip():

        raise RuntimeError(
            "Response API kosong."
        )

    try:

        return json.loads(
            body
        )

    except json.JSONDecodeError as error:

        raise RuntimeError(
            "Response bukan JSON valid. "
            f"{error}. "
            f"Response awal: {body[:500]}"
        )


# ============================================================
# AMBIL DAFTAR BLANKO
# ============================================================

def get_blanko_list(page):

    timestamp = int(
        time.time() * 1000
    )

    api_url = (
        f"{URL_LIST_BLANKO}"
        f"?dateFrom={DATE_FROM}"
        f"&dateTo={DATE_TO}"
        f"&status="
        f"&_={timestamp}"
    )

    log(
        "Mengambil daftar Blanko "
        f"{DATE_FROM} s/d {DATE_TO}..."
    )

    parsed = browser_fetch(
        page,
        api_url
    )

    if isinstance(
        parsed,
        list
    ):

        return parsed

    if isinstance(
        parsed,
        dict
    ):

        possible_keys = [
            "data",
            "rows",
            "result",
            "aaData"
        ]

        for key in possible_keys:

            value = parsed.get(
                key
            )

            if isinstance(
                value,
                list
            ):

                return value

    raise RuntimeError(
        "Struktur JSON daftar Blanko "
        "tidak dikenali."
    )


# ============================================================
# AMBIL DETAIL PER VIOLATION ID
# ============================================================

def get_blanko_detail(
    page,
    violation_id
):

    api_url = (
        f"{URL_DETAIL_BLANKO}"
        f"?violation_id={violation_id}"
    )

    parsed = browser_fetch(
        page,
        api_url
    )

    # Biasanya response:
    #
    # [
    #   {
    #       "violation_id": "...",
    #       ...
    #   }
    # ]

    if isinstance(
        parsed,
        list
    ):

        if not parsed:

            raise RuntimeError(
                "Detail kosong."
            )

        detail = parsed[0]

    elif isinstance(
        parsed,
        dict
    ):

        if (
            "data" in parsed
            and isinstance(
                parsed["data"],
                list
            )
        ):

            if not parsed["data"]:

                raise RuntimeError(
                    "Detail kosong."
                )

            detail = parsed[
                "data"
            ][0]

        elif (
            "data" in parsed
            and isinstance(
                parsed["data"],
                dict
            )
        ):

            detail = parsed[
                "data"
            ]

        else:

            detail = parsed

    else:

        raise RuntimeError(
            "Struktur JSON detail "
            "tidak dikenali."
        )

    if not isinstance(
        detail,
        dict
    ):

        raise RuntimeError(
            "Detail bukan object JSON."
        )

    return detail


# ============================================================
# HAPUS DATA BASE64 BESAR
# ============================================================

def sanitize_detail(detail):

    result = dict(
        detail
    )

    # json_response menyimpan salinan data KIR
    # dengan gambar Base64 sangat besar.
    #
    # Kita tidak membutuhkannya karena field utama
    # dan URL foto sudah tersedia secara terpisah.

    result.pop(
        "json_response",
        None
    )

    result.pop(
        "jsonResponse",
        None
    )

    return result


# ============================================================
# MAPPING DATA ETLE -> SUPABASE
# ============================================================

def build_supabase_row(
    list_item,
    detail
):

    violation_id = clean(
        detail.get(
            "violation_id"
        )
        or list_item.get(
            "violation_id"
        )
    )

    if not violation_id:

        raise RuntimeError(
            "violation_id kosong."
        )

    ref_number = clean(
        detail.get(
            "ref_number"
        )
        or detail.get(
            "pelanggar_ref_number"
        )
        or list_item.get(
            "ref_number"
        )
    )

    plat_number = clean(
        detail.get(
            "plat_number"
        )
        or detail.get(
            "no_registrasi_kendaraan"
        )
        or list_item.get(
            "plat_number"
        )
    )

    no_briva = clean(
        detail.get(
            "no_briva"
        )
        or list_item.get(
            "no_briva"
        )
    )

    no_blanko = clean(
        detail.get(
            "blanko_no"
        )
        or list_item.get(
            "blanko_no"
        )
    )

    status = clean(
        detail.get(
            "status"
        )
        or detail.get(
            "status_bayar"
        )
        or list_item.get(
            "status_bayar"
        )
        or list_item.get(
            "status"
        )
    )

    pelanggaran = clean(
        detail.get(
            "pelanggaran"
        )
        or detail.get(
            "report_type"
        )
        or list_item.get(
            "report_type"
        )
    )

    tanggal_pelanggaran = clean(
        detail.get(
            "inserted_date_vl"
        )
        or detail.get(
            "validasi_date"
        )
        or list_item.get(
            "inserted_date_vl"
        )
    )

    tanggal_tagih = clean(
        detail.get(
            "tertagih_date_date"
        )
        or detail.get(
            "tertagih_date"
        )
        or list_item.get(
            "blanko_date"
        )
    )

    tanggal_sidang = clean(
        detail.get(
            "tanggal_sidang_etle"
        )
        or detail.get(
            "tanggal_sidang_kejaksaan"
        )
    )

    nama_pemilik = clean(
        detail.get(
            "pemilik_stnk"
        )
        or detail.get(
            "nama_pemilik"
        )
    )

    alamat_pemilik = clean(
        detail.get(
            "alamat_pemilik"
        )
    )

    jenis_kendaraan = clean(
        detail.get(
            "jenis_kendaraan"
        )
    )

    merk = clean(
        detail.get(
            "merk"
        )
        or detail.get(
            "merk_kendaraan"
        )
    )

    tipe = clean(
        detail.get(
            "tipe"
        )
    )

    masa_berlaku_kir = clean(
        detail.get(
            "masa_berlaku_kir"
        )
        or detail.get(
            "masa_berlaku"
        )
    )

    foto_kendaraan = clean(
        detail.get(
            "foto_kendaraan"
        )
        or detail.get(
            "foto"
        )
    )

    foto_plat = clean(
        detail.get(
            "foto_plat"
        )
    )

    detail_clean = sanitize_detail(
        detail
    )

    raw_data = {

        "list_data":
            list_item,

        "detail_data":
            detail_clean
    }

    return {

        "violation_id":
            str(
                violation_id
            ),

        "ref_number":
            ref_number,

        "plat_number":
            plat_number,

        "no_briva":
            no_briva,

        "no_blanko":
            no_blanko,

        "status":
            status,

        "pelanggaran":
            pelanggaran,

        "tanggal_pelanggaran":
            tanggal_pelanggaran,

        "tanggal_tagih":
            tanggal_tagih,

        "tanggal_sidang":
            tanggal_sidang,

        "nama_pemilik":
            nama_pemilik,

        "alamat_pemilik":
            alamat_pemilik,

        "jenis_kendaraan":
            jenis_kendaraan,

        "merk":
            merk,

        "tipe":
            tipe,

        "masa_berlaku_kir":
            masa_berlaku_kir,

        "foto_kendaraan":
            foto_kendaraan,

        "foto_plat":
            foto_plat,

        "raw_data":
            raw_data,

        "last_sync_at":
            datetime.now(
                WIB
            ).isoformat()
    }


# ============================================================
# UPSERT SUPABASE
# ============================================================

def upsert_supabase(
    supabase,
    row
):

    response = (
        supabase
        .table(
            "etle_blanko_detail"
        )
        .upsert(
            row,
            on_conflict="violation_id"
        )
        .execute()
    )

    return response.data


# ============================================================
# PROSES SEMUA DATA
# ============================================================

def process_data(
    page,
    supabase,
    data
):

    total_data = len(
        data
    )

    if SYNC_LIMIT > 0:

        selected_data = data[
            :SYNC_LIMIT
        ]

        log(
            f"MODE UJI: dibatasi "
            f"{len(selected_data)} record."
        )

    else:

        selected_data = data

        log(
            "MODE PENUH: semua record "
            "akan diproses."
        )

    total_selected = len(
        selected_data
    )

    berhasil = 0
    gagal = 0
    dilewati = 0

    for index, item in enumerate(
        selected_data,
        start=1
    ):

        if not isinstance(
            item,
            dict
        ):

            log(
                f"[{index}/{total_selected}] "
                "Data bukan object. Dilewati."
            )

            dilewati += 1

            continue

        violation_id = clean(
            item.get(
                "violation_id"
            )
        )

        if not violation_id:

            log(
                f"[{index}/{total_selected}] "
                "violation_id kosong. Dilewati."
            )

            dilewati += 1

            continue

        log(
            f"[{index}/{total_selected}] "
            f"Mengambil detail "
            f"violation_id={violation_id}..."
        )

        last_error = None

        for attempt in range(
            1,
            MAX_RETRY + 1
        ):

            try:

                detail = get_blanko_detail(
                    page,
                    violation_id
                )

                row = build_supabase_row(
                    item,
                    detail
                )

                upsert_supabase(
                    supabase,
                    row
                )

                berhasil += 1

                log(
                    f"[{index}/{total_selected}] "
                    f"{violation_id} -> BERHASIL "
                    f"| TNKB={row.get('plat_number')} "
                    f"| STATUS={row.get('status')}"
                )

                last_error = None

                break

            except Exception as error:

                last_error = error

                log(
                    f"[{index}/{total_selected}] "
                    f"Percobaan "
                    f"{attempt}/{MAX_RETRY} gagal: "
                    f"{error}"
                )

                if attempt < MAX_RETRY:

                    wait_time = (
                        attempt * 2
                    )

                    log(
                        f"Retry dalam "
                        f"{wait_time} detik..."
                    )

                    page.wait_for_timeout(
                        wait_time * 1000
                    )

        if last_error is not None:

            gagal += 1

            log(
                f"[{index}/{total_selected}] "
                f"{violation_id} -> GAGAL"
            )

        if REQUEST_DELAY > 0:

            page.wait_for_timeout(
                int(
                    REQUEST_DELAY
                    * 1000
                )
            )

    return {

        "total_api":
            total_data,

        "diproses":
            total_selected,

        "berhasil":
            berhasil,

        "gagal":
            gagal,

        "dilewati":
            dilewati
    }


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 70
    )

    print(
        "G-SMART SYNC ETLE BLANKO -> SUPABASE"
    )

    print(
        "=" * 70
    )

    log(
        "Waktu WIB       : "
        + datetime.now(
            WIB
        ).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    log(
        f"Tanggal API     : "
        f"{DATE_FROM} s/d {DATE_TO}"
    )

    log(
        f"Headless        : "
        f"{HEADLESS}"
    )

    log(
        f"Sync limit      : "
        f"{SYNC_LIMIT}"
    )

    validate_environment()

    supabase = create_supabase()

    summary = None

    with sync_playwright() as playwright:

        browser = None

        try:

            log(
                "Menjalankan Chromium "
                f"(headless={HEADLESS})..."
            )

            browser = (
                playwright
                .chromium
                .launch(
                    headless=HEADLESS,

                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu"
                    ]
                )
            )

            context = (
                browser
                .new_context(
                    viewport={
                        "width": 1920,
                        "height": 1080
                    }
                )
            )

            page = (
                context
                .new_page()
            )

            # ==================================================
            # LOGIN
            # ==================================================

            login_etle(
                page
            )

            # ==================================================
            # BUKA HALAMAN BLANKO
            # ==================================================

            open_blanko_page(
                page
            )

            # ==================================================
            # AMBIL LIST
            # ==================================================

            data = get_blanko_list(
                page
            )

            log(
                f"Daftar Blanko ditemukan: "
                f"{len(data)} record."
            )

            if not data:

                log(
                    "Tidak ada data Blanko."
                )

                summary = {

                    "total_api": 0,
                    "diproses": 0,
                    "berhasil": 0,
                    "gagal": 0,
                    "dilewati": 0
                }

                return

            # ==================================================
            # PROSES DETAIL + SUPABASE
            # ==================================================

            summary = process_data(
                page,
                supabase,
                data
            )

        finally:

            if browser:

                try:

                    browser.close()

                    log(
                        "Browser ditutup."
                    )

                except Exception:

                    pass

    # ============================================================
    # HASIL
    # ============================================================

    if summary:

        print()

        print(
            "=" * 70
        )

        print(
            "SYNC SELESAI"
        )

        print(
            "=" * 70
        )

        print(
            f"Data API   : "
            f"{summary['total_api']}"
        )

        print(
            f"Diproses   : "
            f"{summary['diproses']}"
        )

        print(
            f"Berhasil   : "
            f"{summary['berhasil']}"
        )

        print(
            f"Gagal      : "
            f"{summary['gagal']}"
        )

        print(
            f"Dilewati   : "
            f"{summary['dilewati']}"
        )

        print(
            "=" * 70
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print()

        log(
            "Proses dihentikan oleh pengguna."
        )

    except Exception as error:

        print()

        print(
            "=" * 70
        )

        print(
            "[ERROR]"
        )

        print(
            "=" * 70
        )

        print(
            str(error)
        )

        print(
            "=" * 70
        )

        raise