"""One-time privacy-safe reason-structure audit across historical disputes.

Logs only aggregate counts/booleans; never identity, reason text, HTML,
media URLs, DOM IDs, or violation identifiers. No database writes.
"""
import json
import os
import re

from sync_private_disputes_auto import HOST_RE, list_disputes
from sync_private_dispute_one import db_get, etle_login, ID_RE
from diagnose_dispute_detail_safe import detail_url
from extract_dispute_detail_readonly import EXTRACTION_JS

REASON_SHAPE_JS = r"""
() => {
  const clean = x => String(x == null ? "" : x).replace(/\s+/g," ").trim();
  const isReasonLabel = v => /^(alasan(?: sanggahan| keberatan| pelanggar)?|jenis sanggahan|keterangan sanggahan|alasan lainnya)$/i.test(clean(v).replace(/:$/,""));
  const sections = ["#InformasiDokumenAlasan","#informasiPelanggar","#detailPelanggaran"];
  const result = {
    explicit_reason_container_present:!!document.querySelector("#alasanLainnya"),
    explicit_reason_container_nonempty:false,
    reason_named_controls:0,
    reason_named_controls_nonempty:0,
    reason_label_cells:0,
    reason_label_cells_value_nonempty:0,
    reason_label_nodes:0,
    reason_label_nodes_next_nonempty:0,
    reason_text_inline_detected:false,
    checked_reason_controls:0,
    objection_section_images:document.querySelectorAll("#InformasiDokumenAlasan img").length
  };
  const explicit=document.querySelector("#alasanLainnya");
  result.explicit_reason_container_nonempty=!!clean(explicit?.value || explicit?.innerText);
  for(const selector of sections){
    const root=document.querySelector(selector);
    if(!root)continue;
    const raw=root.innerText||"";
    result.reason_text_inline_detected ||= /(?:^|\n)\s*(?:alasan(?:\s+sanggahan|\s+keberatan|\s+pelanggar)?|jenis sanggahan)\s*:\s*\S{4,}/im.test(raw);
    for(const row of root.querySelectorAll("tr")){
      const cells=[...row.querySelectorAll(":scope > td, :scope > th")];
      if(cells.length>=2&&isReasonLabel(cells[0].innerText)){
        result.reason_label_cells++;
        if(clean(cells.slice(1).map(el=>el.innerText).join(" ").replace(/^\s*:/,"")))
          result.reason_label_cells_value_nonempty++;
      }
    }
    for(const el of root.querySelectorAll("dt,label")){
      if(!isReasonLabel(el.innerText))continue;
      result.reason_label_nodes++;
      const next=el.nextElementSibling || el.parentElement?.nextElementSibling;
      if(next&&clean(next.innerText||next.value))result.reason_label_nodes_next_nonempty++;
    }
    for(const el of root.querySelectorAll("textarea,input,select")){
      if(el.type==="password"||el.type==="hidden")continue;
      const id=clean((el.getAttribute("name")||"")+" "+(el.id||""));
      if(!/alasan|sanggahan|keberatan/i.test(id))continue;
      result.reason_named_controls++;
      const value=el.matches("select")?el.selectedOptions?.[0]?.textContent : el.value;
      if(clean(value))result.reason_named_controls_nonempty++;
      if((el.type==="radio"||el.type==="checkbox")&&el.checked)result.checked_reason_controls++;
    }
  }
  return result;
}
"""

def run():
    from playwright.sync_api import sync_playwright
    base=os.getenv("SUPABASE_URL","").strip().rstrip("/")
    key=os.getenv("SUPABASE_SERVICE_ROLE_KEY","").strip()
    email=os.getenv("EMAIL_ETLE","").strip()
    passwd=os.getenv("PASSWORD_ETLE","").strip()
    if not HOST_RE.fullmatch(base) or not all((key,email,passwd)):
        raise RuntimeError("CONFIG_MISSING")
    disputes=list_disputes(base,key)
    audit={
        "historical_disputes":len(disputes),
        "details_ok":0, "details_unavailable":0,
        "reason_current_extractor_found":0,
        "reason_explicit_nonempty":0,
        "reason_named_controls":0,
        "reason_named_nonempty":0,
        "reason_table_value_nonempty":0,
        "reason_label_next_nonempty":0,
        "reason_inline_text":0,
        "reason_checked_controls":0,
        "document_sections_with_images":0
    }
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        try:
            page=browser.new_page(viewport={"width":1365,"height":900})
            etle_login(page,email,passwd)
            for item in disputes[:20]:
                try:
                    violation_id=str(item.get("violation_id") or "")
                    if not ID_RE.fullmatch(violation_id):
                        audit["details_unavailable"]+=1;continue
                    response=page.goto(detail_url(violation_id),wait_until="domcontentloaded",timeout=60000)
                    page.wait_for_timeout(1300)
                    if not response or response.status!=200 or "/terkonfirmasi_detail.php" not in page.url:
                        audit["details_unavailable"]+=1;continue
                    parsed=page.evaluate(EXTRACTION_JS)
                    if not parsed.get("detail_present"):
                        audit["details_unavailable"]+=1;continue
                    shape=page.evaluate(REASON_SHAPE_JS)
                    audit["details_ok"]+=1
                    audit["reason_current_extractor_found"]+=int(bool(parsed.get("reason")))
                    audit["reason_explicit_nonempty"]+=int(shape["explicit_reason_container_nonempty"])
                    audit["reason_named_controls"]+=int(shape["reason_named_controls"]>0)
                    audit["reason_named_nonempty"]+=int(shape["reason_named_controls_nonempty"]>0)
                    audit["reason_table_value_nonempty"]+=int(shape["reason_label_cells_value_nonempty"]>0)
                    audit["reason_label_next_nonempty"]+=int(shape["reason_label_nodes_next_nonempty"]>0)
                    audit["reason_inline_text"]+=int(shape["reason_text_inline_detected"])
                    audit["reason_checked_controls"]+=int(shape["checked_reason_controls"]>0)
                    audit["document_sections_with_images"]+=int(shape["objection_section_images"]>0)
                except Exception:
                    audit["details_unavailable"]+=1
        finally:
            browser.close()
    print("AUDIT ALASAN SANGGAHAN (HANYA JUMLAH / TANPA ISI):")
    print(json.dumps(audit,sort_keys=True))


if __name__=="__main__":
    try:run()
    except Exception as exc:
        print("REASON AUDIT FAILED: "+type(exc).__name__+" (tanpa data pribadi).")
        raise SystemExit(1)
