"""Read-only ETLE stopped-case vehicle-photo source probe.

Logs ONLY fixed-schema structural metadata, no identifiers, HTML, URLs,
file contents, or sensitive images. No Supabase write and no artifacts.
"""
import json
import os
import re
from urllib.parse import urlencode
from diagnose_dispute_detail_safe import LOGIN_URL

BASE = "https://etilang-djpd.kemenhub.go.id:9000"
DETAIL_PATH = "/admin-etle/dihentikan_detail.php"
VALID_ID = re.compile(r"^[0-9]{1,12}$")

def build_detail_url(violation_id):
    if not VALID_ID.fullmatch(str(violation_id or "")):
        raise ValueError("INVALID_DETAIL_ID")
    return BASE + DETAIL_PATH + "?" + urlencode({"violation_id": str(violation_id)})

MEDIA_STRUCTURE_JS = r"""
() => {
  const areas = [
    ["main_full_frame", "#fullFrame"],
    ["foto_bukti_frame", "#foto_bukti_frame"],
    ["foto_bukti_frame_clone", "#foto_bukti_frame_clone"],
    ["detail_pelanggaran", "#detailPelanggaran"],
    ["informasi_kendaraan", "#informasiKendaraan"]
  ];
  const seen=new Set();
  const sourceType=(raw)=>{
    if(!raw)return "empty";
    if(raw.startsWith("data:"))return "inline";
    if(raw.startsWith("blob:"))return "blob";
    try {
      const u=new URL(raw,document.baseURI);
      return u.protocol==="https:" && u.hostname==="etilang-djpd.kemenhub.go.id"
        ? "etle_https" : "external_or_other";
    }catch(_){return "invalid";}
  };
  const format=(raw)=>{
    try {
      const p=new URL(raw||"",document.baseURI).pathname.toLowerCase();
      for(const ext of ["jpg","jpeg","png","webp","svg","gif"]){
        if(p.endsWith("."+ext))return ext;
      }
    }catch(_){}
    return "other";
  };
  const summarize=(img)=>{
    const source=img.getAttribute("src")||img.currentSrc||"";
    return {
      loaded:img.complete && img.naturalWidth>0,
      complete:img.complete,
      width:img.naturalWidth||0,
      height:img.naturalHeight||0,
      source_type:sourceType(source),
      source_format:format(source)
    };
  };
  const samples={};
  for(const [name,selector] of areas){
    const node=document.querySelector(selector);
    if(!node){samples[name]={present:false,image_count:0,images:[]};continue;}
    const images=(node.tagName==="IMG"?[node]:[...node.querySelectorAll("img")]).slice(0,4);
    for(const img of images)seen.add(img);
    samples[name]={present:true,image_count:images.length,images:images.map(summarize)};
  }
  const rest=[...document.querySelectorAll("img")].filter(img=>!seen.has(img));
  const large=rest.filter(img=>img.naturalWidth>=500 && img.naturalHeight>=300);
  return {
    page_has_detail:!!document.querySelector("#detailPelanggaran"),
    page_has_vehicle:!!document.querySelector("#informasiKendaraan"),
    scanned:{...samples},
    other_images_count:rest.length,
    other_loaded_large_image_count:large.length,
    other_loaded_large_sources:large.slice(0,3).map(summarize),
    canvas_count:document.querySelectorAll("canvas").length,
    iframe_count:document.querySelectorAll("iframe").length
  };
}
"""

def run(detail_id):
    from playwright.sync_api import sync_playwright
    email=os.getenv("EMAIL_ETLE","").strip()
    password=os.getenv("PASSWORD_ETLE","").strip()
    if not email or not password:raise RuntimeError("ETLE_CREDENTIALS_MISSING")
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        try:
            page=browser.new_page(viewport={"width":1365,"height":900})
            page.goto(LOGIN_URL,wait_until="domcontentloaded",timeout=60000)
            page.locator('input[placeholder="Email"]').fill(email,timeout=30000)
            page.locator('input[placeholder="Password"]').fill(password,timeout=30000)
            page.locator('button:has-text("Login")').click(timeout=30000)
            try:page.wait_for_load_state("networkidle",timeout=20000)
            except Exception:pass
            page.wait_for_timeout(1300)
            if "/main/" in page.url:raise RuntimeError("ETLE_LOGIN_FAILED")
            response=page.goto(build_detail_url(detail_id),wait_until="domcontentloaded",timeout=60000)
            try:page.wait_for_load_state("networkidle",timeout=15000)
            except Exception:pass
            page.wait_for_timeout(2200)
            result={
                "http_status":response.status if response else None,
                "expected_detail_path":DETAIL_PATH in page.url,
                "redirected_to_login":"/main/" in page.url,
                "media":page.evaluate(MEDIA_STRUCTURE_JS)
            }
            print("DIAGNOSTIK FOTO PERKARA DIHENTIKAN (TANPA DATA PRIBADI):")
            print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2))
            if result["http_status"]!=200 or not result["expected_detail_path"] or result["redirected_to_login"]:
                raise RuntimeError("ETLE_DETAIL_UNAVAILABLE")
        finally:browser.close()

if __name__=="__main__":
    try:run(os.getenv("VIOLATION_ID","37359"))
    except Exception as exc:
        print("DIAGNOSTIK GAGAL: "+type(exc).__name__+" (tanpa data pribadi).")
        raise SystemExit(1)
