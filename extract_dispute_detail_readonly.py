"""Read-only, in-memory extraction prototype for ETLE sanggahan.

The workflow prints ONLY a strictly allowlisted aggregate report.
Private fields and URLs are never printed, persisted, or sent to Supabase.
This module does not alter existing vehicle-photo collection or sync scripts.
"""
import json
import os
from urllib.parse import urljoin, urlsplit

from diagnose_dispute_detail_safe import DETAIL_URL, LOGIN_URL, detail_url

ALLOWED_MEDIA_HOST = "etilang-djpd.kemenhub.go.id"
ALLOWED_MEDIA_PORT = 9000
MAX_MEDIA = 8

# Extract values ONLY from fixed ETLE sections; do not read entire body/HTML.
# All data remains in the browser/Python process and is immediately discarded.
# No network fetch or write calls are performed by this JavaScript.
EXTRACTION_JS = r"""
() => {
  const clean = value => String(value == null ? "" : value)
    .replace(/\s+/g," ").trim().slice(0,500);
  const fieldMatchers = [
    ["nama", /^(nama|nama pelanggar)$/i],
    ["alamat", /^(alamat|alamat pelanggar)$/i],
    ["email", /^e-?mail$/i],
    ["no_telp", /^(no\.?\s*(telepon|telp|hp|handphone)|nomor (telepon|hp))$/i],
    ["no_ktp", /^(no\.?\s*ktp|nik)$/i],
    ["no_sim", /^(no\.?\s*sim|nomor sim)$/i],
    ["golongan_sim", /^(golongan sim|sim)$/i],
    ["masa_berlaku_sim", /^masa berlaku sim$/i],
    ["tempat_lahir", /^tempat lahir$/i],
    ["tanggal_lahir", /^tanggal lahir$/i],
    ["ttl", /^ttl$/i],
    ["pekerjaan", /^pekerjaan$/i]
  ];
  const fields = {};
  const add = (label,value) => {
    const key = fieldMatchers.find(pair=>pair[1].test(clean(label).replace(/:$/,"")))?.[0];
    const v = clean(value);
    if (key && v && v !== ":" && v !== "-" && !(key in fields)) fields[key] = v;
  };
  const root = document.querySelector("#informasiPelanggar");
  if (root) {
    for (const tr of root.querySelectorAll("tr")) {
      const cells = [...tr.querySelectorAll("th,td")].map(c=>clean(c.innerText || c.textContent));
      if (cells.length >= 2) add(cells[0],cells.slice(1).filter(v=>v!==":").join(" "));
      else if (cells.length === 1 && cells[0].includes(":")) {
        const i=cells[0].indexOf(":");add(cells[0].slice(0,i),cells[0].slice(i+1));
      }
    }
    for (const dt of root.querySelectorAll("dt")) add(dt.innerText,dt.nextElementSibling?.innerText);
    for (const label of root.querySelectorAll("label")) {
      const target = label.getAttribute("for") ? document.getElementById(label.getAttribute("for")) : null;
      add(label.innerText, target?.value || label.nextElementSibling?.value || label.nextElementSibling?.innerText);
    }
  }
  const evidence = document.querySelector("#InformasiDokumenAlasan");
  // Use only explicitly labelled objection-reason fields. An unrelated
  // "alasan_lainnya" field in a later TERMINATED record is NOT a dispute reason.
  const reasonLabel = /^(alasan(?: sanggahan| keberatan| pelanggar)?|jenis sanggahan|keterangan sanggahan|alasan lainnya)$/i;
  const normalizeReason = text => {
    const value = clean(text);
    if (!value || /^(-|tidak ada|pilih|pilih alasan|select|\W+)$/i.test(value)
      || /^https?:\/\//i.test(value) || value.length>500) return "";
    return value;
  };
  const candidates = [];
  const explicit = document.querySelector("#alasanLainnya");
  if(explicit){
    candidates.push(explicit.value || (explicit.matches("input,textarea,select") ? "" : explicit.innerText));
  }
  for(const section of ["#InformasiDokumenAlasan","#informasiPelanggar","#detailPelanggaran"]){
    const root=document.querySelector(section);
    if(!root)continue;
    for(const row of root.querySelectorAll("tr")){
      const cells=[...row.querySelectorAll(":scope > td,:scope > th")];
      if(cells.length>=2 && reasonLabel.test(clean(cells[0].innerText).replace(/:$/,""))){
        candidates.push(cells.slice(1).map(el=>el.innerText).join(" ").replace(/^\s*:\s*/,""));
      }
    }
    for(const el of root.querySelectorAll("textarea,input,select")){
      if(el.type==="hidden"||el.type==="password")continue;
      const ident=clean((el.name||"")+" "+(el.id||""));
      const associated=el.id ? root.querySelector('label[for="'+CSS.escape(el.id)+'"]') : null;
      const label=clean(associated?.innerText || el.closest("label")?.innerText || "");
      if(/alasan|sanggahan|keberatan/i.test(ident) || reasonLabel.test(label.replace(/:$/,""))){
        const value=el.matches("select")?el.selectedOptions?.[0]?.textContent:
          (el.type==="radio"||el.type==="checkbox")?(el.checked?(label||el.value):""):el.value;
        candidates.push(value);
      }
    }
  }
  const reason=candidates.map(normalizeReason).find(Boolean)||"";
  const media = node => {
    if (!node) return [];
    const nodes=[...node.querySelectorAll("img[src],a[href],object[data],embed[src],iframe[src]")].slice(0,8);
    return nodes.map(el => ({
      kind:el.tagName.toLowerCase(),
      reference:el.getAttribute("src") || el.getAttribute("href") || el.getAttribute("data") || "",
      loaded:el.tagName.toLowerCase() === "img" ? (el.complete && el.naturalWidth > 0) : null,
      width:el.tagName.toLowerCase() === "img" ? el.naturalWidth : 0,
      height:el.tagName.toLowerCase() === "img" ? el.naturalHeight : 0
    }));
  };
  const vehicle = document.querySelector("#foto_bukti_frame");
  return {
    detail_present:!!document.querySelector("#detailPelanggaran") && !!root,
    offender:fields,
    reason,
    sim_candidates:media(root).filter(x=>x.kind==="img"),
    document_candidates:media(evidence),
    vehicle_exists:!!vehicle,
    vehicle_image_loaded:vehicle?.tagName?.toLowerCase()==="img" ? (vehicle.complete && vehicle.naturalWidth > 0) : null
  };
}
"""


def safe_etle_media_url(reference):
    """Resolve only authenticated ETLE-origin HTTPS URLs; reject arbitrary hosts."""
    if not isinstance(reference, str) or not reference.strip():
        return None
    if len(reference) > 4096:
        return None
    try:
        url = urljoin(DETAIL_URL, reference.strip())
        p = urlsplit(url)
        if (
            p.scheme != "https"
            or p.hostname != ALLOWED_MEDIA_HOST
            or p.port != ALLOWED_MEDIA_PORT
            or p.username is not None
            or p.password is not None
        ):
            return None
        return url
    except (ValueError, TypeError):
        return None


def normalize_private_extraction(raw):
    """Create the in-memory handoff object; never print or serialize this object."""
    raw = raw if isinstance(raw, dict) else {}
    fields = raw.get("offender")
    fields = fields if isinstance(fields, dict) else {}
    allowed_fields = (
        "nama", "alamat", "email", "no_telp", "no_ktp", "no_sim",
        "golongan_sim", "masa_berlaku_sim", "tempat_lahir", "tanggal_lahir",
        "ttl", "pekerjaan"
    )
    offender = {key: str(fields[key]).strip()[:500]
                for key in allowed_fields
                if isinstance(fields.get(key), str) and fields[key].strip()}
    def media(items):
        return [
            {"kind": item.get("kind"), "source": url, "loaded": item.get("loaded"),
             "width": int(item.get("width") or 0), "height": int(item.get("height") or 0)}
            for item in (items if isinstance(items,list) else [])[:MAX_MEDIA]
            if isinstance(item,dict)
            if (url := safe_etle_media_url(item.get("reference"))) is not None
        ]
    return {
        "detail_present": raw.get("detail_present") is True,
        "offender": offender,
        "reason": str(raw.get("reason") or "").strip()[:500],
        "sim_candidates": media(raw.get("sim_candidates")),
        "document_candidates": media(raw.get("document_candidates")),
        "vehicle_exists": raw.get("vehicle_exists") is True,
        "vehicle_image_loaded": raw.get("vehicle_image_loaded") is True,
    }


def safe_report(private):
    """Fixed-schema flags and counts ONLY. Never emit contents, URLs or PII."""
    fields = private.get("offender") or {}
    return {
        "detail_present": private.get("detail_present") is True,
        "offender_field_presence": {
            name: bool(fields.get(name))
            for name in ("nama", "alamat", "email", "no_telp", "no_ktp",
                         "no_sim", "golongan_sim", "masa_berlaku_sim",
                         "tempat_lahir", "tanggal_lahir", "ttl", "pekerjaan")
        },
        "reason_present": bool(private.get("reason")),
        "sim_images_accepted": len(private.get("sim_candidates") or []),
        "sim_images_loaded": sum(x.get("loaded") is True for x in (private.get("sim_candidates") or [])),
        "document_media_accepted": len(private.get("document_candidates") or []),
        "document_images_loaded": sum(x.get("loaded") is True for x in (private.get("document_candidates") or [])),
        "vehicle_element_present": private.get("vehicle_exists") is True,
        "vehicle_image_loaded": private.get("vehicle_image_loaded") is True,
        "note": "Kandidat SIM/dokumen dipilih dari bagian halaman, isi belum diverifikasi."
    }


def run(detail_id):
    from playwright.sync_api import sync_playwright
    email = os.getenv("EMAIL_ETLE", "").strip()
    password = os.getenv("PASSWORD_ETLE", "").strip()
    if not email or not password:
        raise RuntimeError("Missing ETLE credentials")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1365, "height": 900})
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            page.locator('input[placeholder="Email"]').fill(email, timeout=30000)
            page.locator('input[placeholder="Password"]').fill(password, timeout=30000)
            page.locator('button:has-text("Login")').click(timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                pass
            page.wait_for_timeout(1500)
            if "/main/" in page.url:
                raise RuntimeError("ETLE login failed")
            resp = page.goto(detail_url(detail_id), wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            if (
                resp is None or resp.status != 200
                or "/terkonfirmasi_detail.php" not in page.url
                or "/main/" in page.url
            ):
                raise RuntimeError("Unexpected ETLE detail response")
            private = normalize_private_extraction(page.evaluate(EXTRACTION_JS))
            if not private["detail_present"]:
                raise RuntimeError("ETLE detail structure not found")
            # Only this safe summary goes to GitHub Actions logs.
            print("HASIL EKSTRAKSI SANGGAHAN (TANPA DATA PRIBADI):")
            print(json.dumps(safe_report(private),ensure_ascii=False,indent=2,sort_keys=True))
        finally:
            browser.close()


if __name__ == "__main__":
    try:
        run(os.getenv("DETAIL_ID", ""))
    except Exception as exc:
        # Never print the exception: Playwright errors may contain page content.
        print("Ekstraksi uji gagal: "+type(exc).__name__+" (tanpa detail sensitif).")
        raise SystemExit(1)
