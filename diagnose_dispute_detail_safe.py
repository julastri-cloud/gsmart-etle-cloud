"""Read-only structural probe for ETLE Hub dispute detail.
Never logs names, SIM photos, documents, page HTML, direct resource URLs or tokens.
No Supabase write/read, no file artifacts, no ETLE status changes.
"""
import json
import os
import re
from urllib.parse import urlencode

LOGIN_URL = "https://etilang-djpd.kemenhub.go.id:9000/main/"
DETAIL_URL = "https://etilang-djpd.kemenhub.go.id:9000/admin-etle/terkonfirmasi_detail.php"
SAFE_DETAIL_ID = re.compile(r"^[0-9]{1,12}$")


def detail_url(detail_id):
    detail_id = str(detail_id or "").strip()
    if not SAFE_DETAIL_ID.fullmatch(detail_id):
        raise ValueError("ID detail harus angka 1–12 digit.")
    return DETAIL_URL + "?" + urlencode({"id": detail_id, "status_konfirmasi": "Tersanggah"})


# One-way summary: JavaScript returns only structural attributes and booleans.
# HTML, innerText values, image/src hrefs, and resources are never returned.
DOM_PROBE = """
() => {
  const text=(document.body?.innerText||"").toLowerCase();
  const ids=[...document.querySelectorAll("[id]")].map(el=>el.id)
    .filter(id=>/^(?!.*\\s)[a-zA-Z][a-zA-Z0-9_-]{0,79}$/.test(id))
    .filter(id=>/sanggah|sim|pelanggar|dokumen|alasan|kendaraan|foto/i.test(id))
    .slice(0,30);
  const images=[...document.querySelectorAll("img")];
  const imgClasses=images.reduce((out,img)=>{
    const parent=img.closest("section,.card,.panel,.row,.col,.tab-pane,td,figure")||img.parentElement;
    const hint=((img.alt||"")+" "+(parent?.className?.toString()||"")).toLowerCase();
    const kind=/sim|license/.test(hint)?"sim":/sanggah|dokumen|bukti/.test(hint)?"document":"other";
    out[kind]++;
    return out;
  },{sim:0,document:0,other:0});
  const loaded=images.filter(img=>img.complete&&img.naturalWidth>0).length;
  return {
    sections:{
      pelanggar:/informasi pelanggar|data pelanggar/.test(text),
      kendaraan:/data kendaraan/.test(text),
      alasan:/alasan pelanggar|alasan sanggahan/.test(text),
      dokumen_sanggahan:/dokumen sanggahan/.test(text),
      foto_sim:/foto sim|golongan sim|masa berlaku sim/.test(text)
    },
    element_counts:{
      images:images.length,
      loaded_images:loaded,
      image_roles_from_markup:imgClasses,
      iframes:document.querySelectorAll("iframe").length,
      links:document.querySelectorAll("a").length,
      videos:document.querySelectorAll("video").length
    },
    structural_ids:ids,
    detail_sections_present:!!document.querySelector("#detailPelanggaran") && !!document.querySelector("#informasiPelanggar")
  };
}
"""


def detail_report_ok(result):
    """Accept an authenticated detail page based on its expected content, not on
    the presence of a password input that may belong to a hidden modal."""
    probe = result.get("probe") or {}
    return (
        result.get("http_status") == 200
        and result.get("on_expected_detail_path") is True
        and probe.get("detail_sections_present") is True
    )


def run(detail_id):
    from playwright.sync_api import sync_playwright

    email = os.getenv("EMAIL_ETLE", "").strip()
    password = os.getenv("PASSWORD_ETLE", "").strip()
    if not email or not password:
        raise RuntimeError("Secret EMAIL_ETLE atau PASSWORD_ETLE belum tersedia.")

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
                raise RuntimeError("Sesi login ETLE tidak berhasil.")
            print("ETLE login: berhasil (tanpa informasi akun).", flush=True)
            response=page.goto(detail_url(detail_id),wait_until="domcontentloaded",timeout=60000)
            page.wait_for_timeout(2500)
            if "/main/" in page.url:
                raise RuntimeError("Halaman detail meminta login ulang.")
            result={
                "http_status":response.status if response else None,
                "on_expected_detail_path": "/terkonfirmasi_detail.php" in page.url,
                "has_sensitive_page_content": True,  # never included in logs
                "probe":page.evaluate(DOM_PROBE)
            }
            # No raw HTML, personal identifiers, files, screenshots, URLs or resource bodies.
            del result["has_sensitive_page_content"]
            print("LAPORAN STRUKTUR (TANPA DATA PRIBADI):")
            print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True),flush=True)
            if not detail_report_ok(result):
                raise RuntimeError("Detail ETLE tidak terbaca sebagai halaman yang diharapkan.")
        finally:
            browser.close()


if __name__=="__main__":
    try:
        run(os.getenv("DETAIL_ID",""))
    except Exception as error:
        # Intentionally do not stringify exception: Playwright errors can contain
        # URLs and DOM attributes from authenticated pages.
        print("DIAGNOSTIK GAGAL: "+type(error).__name__+". Periksa login atau akses detail.",flush=True)
        raise SystemExit(1)
