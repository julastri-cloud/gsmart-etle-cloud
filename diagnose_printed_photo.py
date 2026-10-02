import os
import json
import re
import time
from html import unescape
from urllib.parse import urlencode, urljoin
from playwright.sync_api import sync_playwright

BASE = "https://etilang-djpd.kemenhub.go.id:9000/"
URL_LOGIN = urljoin(BASE, "main/")
URL_PRINTED = urljoin(BASE, "etle/admin-etle/penindakan_printed_list.php")

EMAIL_ETLE = os.getenv("EMAIL_ETLE", "").strip()
PASSWORD_ETLE = os.getenv("PASSWORD_ETLE", "").strip()
TARGET_TNKB = re.sub(r"\s+", "", os.getenv("TARGET_TNKB", "AE8768SK").upper())
DATE_FROM = os.getenv("DATE_FROM", "01-09-2026").strip()
DATE_TO = os.getenv("DATE_TO", "30-09-2026").strip()
HEADLESS = os.getenv("HEADLESS", "true").strip().lower() == "true"
DETAIL_URL = os.getenv("DETAIL_URL", "").strip()
DETAIL_NO = os.getenv("DETAIL_NO", "").strip()
DETAIL_TIME = os.getenv("DETAIL_TIME", "").strip()
DETAIL_TYPE = os.getenv("DETAIL_TYPE", "").strip()
PAGE_SIZE = 100

PRINTED_COLUMNS = [
    "inserted_date", "display_date", "ref_number", "plat_number", "alamat_regiden",
    "wilayah_satuan", "wilayah_induk", "no_resi", "pelanggaran", "validasi_date",
    "status", "aksi"
]

def log(msg):
    print(msg, flush=True)

def norm_plate(v):
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
    page.wait_for_timeout(1500)
    if "/main/" in page.url:
        raise RuntimeError("Login ETLE gagal")

def build_url(start, draw):
    p = {
        "draw": draw,
        "order[0][column]": 0,
        "order[0][dir]": "asc",
        "start": start,
        "length": PAGE_SIZE,
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

def browser_json(page, url):
    result = page.evaluate("""async (url) => {
      const r = await fetch(url, {
        method: "GET", credentials: "include", cache: "no-store",
        headers: {"Accept":"application/json, text/javascript, */*; q=0.01",
                  "X-Requested-With":"XMLHttpRequest"}
      });
      return {status:r.status, body:await r.text()};
    }""", url)
    if result["status"] != 200:
        raise RuntimeError(f"HTTP {result['status']}")
    return json.loads(result["body"])

def find_target(page):
    start = 0
    draw = 1
    while True:
        data = browser_json(page, build_url(start, draw))
        batch = data.get("data", [])
        total = int(data.get("recordsFiltered", data.get("recordsTotal", len(batch))) or 0)
        log(f"Scan shipping: {start + len(batch)}/{total}")
        for item in batch:
            if norm_plate(item.get("plat_number")) == TARGET_TNKB:
                return item
        if not batch or start + len(batch) >= total:
            return None
        start += len(batch)
        draw += 1

def extract_detail_href(action_html):
    s = unescape(str(action_html or ""))
    patterns = [
        r'href=["\']([^"\']*printed_detail\.php[^"\']*)["\']',
        r'(https?://[^"\'\s<>]*printed_detail\.php[^"\'\s<>]*)',
        r'(["\'])([^"\']*printed_detail\.php[^"\']*)\1',
    ]
    for p in patterns:
        m = re.search(p, s, flags=re.I)
        if m:
            href = m.group(2) if len(m.groups()) >= 2 and m.group(2) else m.group(1)
            return urljoin(BASE, href)
    return None

def inspect_detail(page, detail_url):
    image_responses = []

    def on_response(response):
        try:
            ctype = (response.headers.get("content-type") or "").lower()
            if ctype.startswith("image/") or re.search(r"\.(jpg|jpeg|png|webp|gif)(\?|$)", response.url, re.I):
                image_responses.append({
                    "url": response.url,
                    "status": response.status,
                    "content_type": ctype,
                })
        except Exception:
            pass

    page.on("response", on_response)

    page.goto(detail_url, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    page.wait_for_timeout(2500)

    page.screenshot(path="printed_detail_diagnostic.png", full_page=True)
    html = page.content()
    with open("printed_detail_diagnostic.html", "w", encoding="utf-8") as f:
        f.write(html)

    images = page.evaluate("""() => Array.from(document.images).map((img, i) => ({
      index: i,
      src: img.currentSrc || img.src || "",
      dataSrc: img.getAttribute("data-src") || "",
      srcset: img.srcset || "",
      alt: img.alt || "",
      width: img.naturalWidth || img.width || 0,
      height: img.naturalHeight || img.height || 0,
      className: img.className || ""
    }))""")

    backgrounds = page.evaluate("""() => {
      const out = [];
      for (const el of Array.from(document.querySelectorAll('*'))) {
        const bg = getComputedStyle(el).backgroundImage || "";
        if (bg && bg !== "none") {
          out.push({
            tag: el.tagName,
            id: el.id || "",
            className: el.className || "",
            backgroundImage: bg
          });
        }
      }
      return out;
    }""")

    frames = page.evaluate("""() => Array.from(document.querySelectorAll('iframe')).map((x,i)=>({
      index:i, src:x.src || x.getAttribute('src') || "", title:x.title || ""
    }))""")

    canvases = page.evaluate("""() => Array.from(document.querySelectorAll('canvas')).map((x,i)=>({
      index:i, width:x.width, height:x.height, className:x.className || "", id:x.id || ""
    }))""")

    objects = page.evaluate("""() => Array.from(document.querySelectorAll('object,embed')).map((x,i)=>({
      index:i, tag:x.tagName, src:x.src || x.data || x.getAttribute('src') || x.getAttribute('data') || ""
    }))""")

    html_refs = sorted(set(re.findall(
        r'''https?://[^"'\s<>]+|(?:/|\.\./|\./)[^"'\s<>]+\.(?:jpg|jpeg|png|webp|gif)(?:\?[^"'\s<>]*)?''',
        html,
        flags=re.I
    )))[:100]

    keyword_snippets = []
    lower_html = html.lower()
    for keyword in ("foto", "photo", "image", "img", "pelanggaran"):
        pos = lower_html.find(keyword)
        if pos >= 0:
            keyword_snippets.append({
                "keyword": keyword,
                "snippet": re.sub(r"\s+", " ", html[max(0,pos-250):pos+750])
            })

    return {
        "detail_url": page.url,
        "page_title": page.title(),
        "all_image_count": len(images),
        "images": images,
        "background_count": len(backgrounds),
        "backgrounds": backgrounds[:50],
        "iframe_count": len(frames),
        "iframes": frames,
        "canvas_count": len(canvases),
        "canvases": canvases,
        "object_embed_count": len(objects),
        "objects": objects,
        "network_image_count": len(image_responses),
        "network_images": image_responses[:100],
        "html_image_refs": html_refs,
        "keyword_snippets": keyword_snippets,
    }

def main():
    if not EMAIL_ETLE or not PASSWORD_ETLE:
        raise RuntimeError("EMAIL_ETLE/PASSWORD_ETLE belum tersedia")

    report = {
        "mode": "READ_ONLY_DIAGNOSTIC",
        "target_tnkb": TARGET_TNKB,
        "date_from": DATE_FROM,
        "date_to": DATE_TO,
        "supabase_write": False,
    }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=HEADLESS, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            login(page)
            log("Login ETLE berhasil.")

            detail_url = DETAIL_URL
            if not detail_url and DETAIL_NO and DETAIL_TIME and DETAIL_TYPE:
                detail_url = BASE.rstrip("/") + "/admin-etle/printed_detail.php?" + urlencode({
                    "id": TARGET_TNKB,
                    "no": DETAIL_NO,
                    "time": DETAIL_TIME,
                    "type": DETAIL_TYPE,
                })
            item = None

            if detail_url:
                report["resolution_mode"] = "DIRECT_DETAIL_URL"
                report["found"] = True
                report["detail_url_from_input"] = detail_url
                log("Menggunakan DETAIL_URL langsung; scan shipping dilewati.")
            else:
                report["resolution_mode"] = "SHIPPING_LOOKUP"
                item = find_target(page)
                if not item:
                    report["found"] = False
                    raise RuntimeError(
                        f"TNKB {TARGET_TNKB} tidak ditemukan pada daftar shipping rentang tanggal. "
                        "Gunakan input detail_url untuk menguji halaman printed_detail.php secara langsung."
                    )

                report["found"] = True
                report["shipping"] = {
                    "plat_number": item.get("plat_number"),
                    "ref_number": item.get("ref_number"),
                    "inserted_date": item.get("inserted_date"),
                    "display_date": item.get("display_date"),
                    "pelanggaran": item.get("pelanggaran") or item.get("report_type"),
                    "source_id": item.get("id"),
                    "has_action": bool(item.get("aksi")),
                }

                detail_url = extract_detail_href(item.get("aksi"))
                report["detail_url_from_action"] = detail_url
                if not detail_url:
                    report["action_preview"] = str(item.get("aksi") or "")[:1000]
                    raise RuntimeError("URL printed_detail.php tidak ditemukan di field aksi")

            report["detail"] = inspect_detail(page, detail_url)
            browser.close()

            log(f"Detail URL: {report['detail']['detail_url']}")
            log(f"DOM images: {report['detail']['all_image_count']}")
            log(f"Network image responses: {report['detail']['network_image_count']}")
            log(f"Background images: {report['detail']['background_count']}")
            log(f"Iframes: {report['detail']['iframe_count']} | Canvas: {report['detail']['canvas_count']} | Object/Embed: {report['detail']['object_embed_count']}")
            for i, c in enumerate(report["detail"]["network_images"], 1):
                log(f"[NET IMG {i}] HTTP {c.get('status')} {c.get('content_type')} {c.get('url')}")
            for i, c in enumerate(report["detail"]["images"], 1):
                log(f"[DOM IMG {i}] {c.get('width')}x{c.get('height')} src={c.get('src')} data-src={c.get('dataSrc')}")
    finally:
        with open("photo_diagnostic.json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
