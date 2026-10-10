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


# Read-only media structure audit. It deliberately emits only fixed-category labels,
# aggregate counts and load states. No raw URLs, hrefs, HTML, field values, or text.
MEDIA_PROBE = """
() => {
  const regions = [
    ["pelanggar", "#informasiPelanggar"],
    ["identitas_pelanggar", "#identitas_pelanggar"],
    ["dokumen_sanggahan", "#InformasiDokumenAlasan"],
    ["overlay_dokumen", "#overlayInfoDokumen"],
    ["alasan", "#alasanLainnya"],
    ["kendaraan", "#informasiKendaraan"],
    ["pelanggaran", "#detailPelanggaran"]
  ];
  const regionOf = el => {
    for (const [name,selector] of regions) {
      if(el.closest(selector)) return name;
    }
    return "lainnya";
  };
  const sourceKind = raw => {
    const val = String(raw || "").trim();
    if (!val) return "kosong";
    if (/^data:/i.test(val)) return "data_inline";
    if (/^blob:/i.test(val)) return "blob";
    try {
      const dest = new URL(val, document.baseURI);
      if (!/^https?:$/i.test(dest.protocol)) return "lainnya";
      return dest.origin === location.origin ? "asal_etle" : "asal_lain";
    } catch (_) {
      return "tidak_dikenali";
    }
  };
  const formatKind = raw => {
    try {
      const path = new URL(String(raw || ""), document.baseURI).pathname.toLowerCase();
      for(const ext of ["jpg","jpeg","png","webp","gif","svg","pdf"]) {
        if(path.endsWith("."+ext)) return ext === "jpeg" ? "jpg" : ext;
      }
      return "tidak_diketahui";
    } catch (_) {return "tidak_diketahui";}
  };
  const mediaLabels = element => {
    const near = ((element.getAttribute("alt")||"")+" "+
      (element.parentElement?.textContent||"").slice(0,220)).toLowerCase();
    if (/\\bsim\\b|surat izin mengemudi/.test(near)) return "indikasi_sim";
    if (/sanggah|dokumen|bukti|lampiran/.test(near)) return "indikasi_dokumen";
    if (/kendaraan|foto etle|plat/.test(near)) return "indikasi_kendaraan";
    return "belum_terklasifikasi";
  };
  const images = [...document.images].slice(0,25).map((img,i)=>{
    const raw=img.getAttribute("src")||img.currentSrc||"";
    return {
      urutan:i+1,
      area:regionOf(img),
      label_teknis:mediaLabels(img),
      status_muat:img.complete?(img.naturalWidth>0?"berhasil":"gagal"):"menunggu",
      jenis_sumber:sourceKind(raw),
      format_sumber:formatKind(raw),
      ukuran:{lebar:img.naturalWidth||0,tinggi:img.naturalHeight||0},
      atribut_id:img.id==="foto_bukti_frame"?"foto_bukti_frame":
        img.id==="fullFrame"?"fullFrame":img.id?"lainnya":"tanpa_id"
    };
  });
  const section = selector => {
    const el=document.querySelector(selector);
    if(!el) return {ada:false};
    const photos=[...el.querySelectorAll("img")];
    const links=[...el.querySelectorAll("a[href]")];
    return {
      ada:true,
      gambar:photos.length,
      gambar_berhasil:photos.filter(x=>x.complete&&x.naturalWidth>0).length,
      tautan:links.length,
      tautan_pdf:links.filter(x=>formatKind(x.getAttribute("href"))==="pdf").length,
      jenis_sumber_tautan:[...new Set(links.map(x=>sourceKind(x.getAttribute("href"))))].sort(),
      objek:el.querySelectorAll("object,embed,iframe").length,
      tombol:el.querySelectorAll("button").length
    };
  };
  return {
    gambar:images,
    total_gambar_di_halaman:document.images.length,
    bagian:{
      informasi_pelanggar:section("#informasiPelanggar"),
      identitas_pelanggar:section("#identitas_pelanggar"),
      dokumen_sanggahan:section("#InformasiDokumenAlasan"),
      overlay_dokumen:section("#overlayInfoDokumen"),
      foto_kendaraan:section("#foto_bukti_frame"),
      alasan_lainnya:section("#alasanLainnya")
    }
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
            print("DIAGNOSTIK MEDIA (HANYA STRUKTUR, TANPA FOTO/TAUTAN/IDENTITAS):")
            print(json.dumps(page.evaluate(MEDIA_PROBE),ensure_ascii=False,indent=2,sort_keys=True),flush=True)
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
