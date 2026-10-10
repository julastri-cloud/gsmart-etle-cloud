import test from "node:test";
import assert from "node:assert/strict";
import {
  BUCKET,GSMART_ORIGIN,canReadPrivateDispute,safeCaseId,safeEvidencePath,mimeForPath
} from "./supabase/functions/gsmart-dispute-private/security.mjs";

const id="9fe2d406-bf92-4b9e-8b0e-14e0f67320c1";

test("only active ADMIN and WASATPEL roles may access private dispute evidence",()=>{
  assert.equal(canReadPrivateDispute({role:"ADMIN",aktif:true}),true);
  assert.equal(canReadPrivateDispute({role:" admin ",aktif:true}),true);
  assert.equal(canReadPrivateDispute({role:"WASATPEL",aktif:true}),true);
  assert.equal(canReadPrivateDispute({role:" wasatpel ",aktif:true}),true);
  for(const profile of [
    {role:"PETUGAS",aktif:true},
    {role:"PETUGAS ETLE",aktif:true},
    {role:"WASATPEL",aktif:false},
    {role:"WASATPEL",aktif:"true"},
    {role:"ADMIN",aktif:false},
    {role:"ADMIN",aktif:"true"},
    {role:"",aktif:true},
    null
  ])assert.equal(canReadPrivateDispute(profile),false);
});
test("case IDs must be UUIDs, not client-supplied filter expressions",()=>{
  assert.equal(safeCaseId(id),id);
  for(const raw of ["","80971","a'.or.(true)","00000000-0000-0000-0000-000000000000",null])
    assert.equal(safeCaseId(raw),null);
});
test("SIM paths are locked to matching case and kind",()=>{
  assert.equal(safeEvidencePath(id,"sim",id+"/sim/photo.jpg"),id+"/sim/photo.jpg");
  assert.equal(safeEvidencePath(id,"sim",id+"/document/photo.jpg"),null);
  assert.equal(safeEvidencePath(id,"sim",id+"/sim/file.pdf"),null);
  assert.equal(safeEvidencePath(id,"sim",id+"/sim/../../another.jpg"),null);
  assert.equal(safeEvidencePath(id,"sim","https://evil.example/photo.jpg"),null);
  assert.equal(safeEvidencePath(id,"sim",id.replace("9f","8f")+"/sim/photo.jpg"),null);
});
test("document path supports only approved media types under same case",()=>{
  assert.equal(safeEvidencePath(id,"document",id+"/document/scan.pdf"),id+"/document/scan.pdf");
  assert.equal(safeEvidencePath(id,"document",id+"/document/scan.exe"),null);
  assert.equal(safeEvidencePath(id,"document",id+"/document/scan.pdf?token=x"),null);
  assert.equal(mimeForPath("photo.webp"),"image/webp");
  assert.equal(mimeForPath("scan.pdf"),"application/pdf");
});
test("private endpoint uses distinct bucket and exact PWA origin",()=>{
  assert.equal(BUCKET,"gsmart-dispute-private");
  assert.equal(GSMART_ORIGIN,"https://uppkb-guyangan.github.io");
});
