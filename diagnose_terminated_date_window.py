"""Read-only ETLE source date-range probe, count/boolean output only.

Does not write Supabase, change ETLE, upload artifacts, or print case data.
"""
import json
import os
import re
from datetime import datetime,timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright
from sync_private_dispute_one import etle_login

ETLE_BASE="https://etilang-djpd.kemenhub.go.id:9000"
TERMINATED_API=ETLE_BASE+"/etle/admin-etle/datalisthentikanblokir.php"
WIB=ZoneInfo("Asia/Jakarta")
JS = r"""async ({url,target})=>{
  try{
    const r=await fetch(url,{method:"GET",credentials:"include",cache:"no-store",
      headers:{"Accept":"application/json, text/javascript, */*; q=0.01","X-Requested-With":"XMLHttpRequest"}});
    if(r.status!==200)return {http_ok:false,valid_json:false,rows:null,target_present:false};
    const obj=await r.json();
    if(!Array.isArray(obj?.data))return {http_ok:true,valid_json:false,rows:null,target_present:false};
    const normalized=s=>String(s||"").toUpperCase().replace(/[^A-Z0-9]/g,"");
    return {http_ok:true,valid_json:true,rows:obj.data.length,
      target_present:obj.data.some(x=>
        normalized(x.plat_number)===normalized(target))};
  }catch(_){return{http_ok:false,valid_json:false,rows:null,target_present:false}}
}"""

def test_ranges(today):
    prev=today-timedelta(days=14)
    end=today+timedelta(days=1)
    return [
        ("incremental_current",prev.strftime("%Y-%m-%d"),today.strftime("%d-%m-%Y")),
        ("incremental_next_day",prev.strftime("%Y-%m-%d"),end.strftime("%d-%m-%Y")),
        ("full_current","2026-08-01",today.strftime("%d-%m-%Y")),
        ("full_next_day","2026-08-01",end.strftime("%d-%m-%Y"))
    ]

def run():
    email=os.getenv("EMAIL_ETLE","").strip()
    password=os.getenv("PASSWORD_ETLE","").strip()
    target=os.getenv("TARGET_TNKB","").strip()
    if not email or not password or not re.fullmatch("[A-Z]{1,2}[0-9]{1,4}[A-Z]{1,3}",target):
        raise RuntimeError("MISSING_REQUIRED_CONFIG")
    today=datetime.now(WIB).date()
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        try:
            page=browser.new_page()
            etle_login(page,email,password)
            page.goto(ETLE_BASE+"/admin-etle/tertagih.php",
                      wait_until="domcontentloaded",timeout=60000)
            output={}
            for label,date_from,date_to in test_ranges(today):
                url=TERMINATED_API+"?"+urlencode({"dateFrom":date_from,"dateTo":date_to,"_":0})
                output[label]=page.evaluate(JS,{"url":url,"target":target})
            print("DIAGNOSTIK RENTANG TANGGAL DIHENTIKAN (HITUNGAN SAJA):")
            print(json.dumps(output,sort_keys=True))
            if not all(x["http_ok"] and x["valid_json"] for x in output.values()):
                raise RuntimeError("ETLE_API_RESPONSE_NOT_VALID")
        finally:
            browser.close()

if __name__=="__main__":
    try:run()
    except Exception as e:
        print("DIAGNOSTIK GAGAL: "+type(e).__name__)
        raise SystemExit(1)
