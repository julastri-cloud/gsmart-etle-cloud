import test from "node:test";
import assert from "node:assert/strict";
import {BUCKET,ORIGIN,safeId,safePath,mime,allowedProfile} from "./supabase/functions/gsmart-stopped-vehicle/security.mjs";
const cid="8bb1e604-2325-4586-80fa-16787b42a57e";
test("only signed-in active roles are authorized; anonymous and disabled refused",()=>{
 assert.equal(allowedProfile({role:"ADMIN",aktif:true}),true);
 assert.equal(allowedProfile({role:"WASATPEL",aktif:true}),true);
 assert.equal(allowedProfile({role:"PETUGAS",aktif:true}),true);
 for(const p of [null,{role:"ADMIN",aktif:false},{role:"",aktif:true},{role:"PETUGAS",aktif:"true"}])
  assert.equal(allowedProfile(p),false);
});
test("paths must match exact UUID of requested stopped case",()=>{
 assert.equal(safeId(cid),cid);
 const good=cid+"/vehicle/"+"a".repeat(24)+".jpg";
 assert.equal(safePath(cid,good),good);
 for(const p of ["https://evil.test/x.jpg",cid+"/../photo.jpg",cid+"/sim/"+"a".repeat(24)+".jpg",cid+"/vehicle/"+"b".repeat(24)+".pdf"])
  assert.equal(safePath(cid,p),null);
});
test("restrict media and private bucket",()=>{
 assert.equal(BUCKET,"gsmart-stopped-vehicles-private");
 assert.equal(ORIGIN,"https://uppkb-guyangan.github.io");
 assert.equal(mime("x.jpg"),"image/jpeg");
 assert.equal(mime("x.pdf"),null);
});
