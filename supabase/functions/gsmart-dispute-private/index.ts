// G-Smart private dispute evidence API.
// Firebase Auth is verified by Google Identity Toolkit. Then Firestore role
// (active ADMIN or WASATPEL) is checked independently of client-side UI.
// Gateway verify_jwt=false is required because this API authenticates Firebase
// ID tokens (not Supabase JWTs) inside the function.
import { BUCKET, GSMART_ORIGIN, safeCaseId, safeEvidencePath, mimeForPath, canReadPrivateDispute } from "./security.mjs";

const FIREBASE_API_KEY = "AIzaSyBbF1MPzFK_EdUFV9CNh2ZZfuHxRgilm6o"; // Public Firebase web key
const FIREBASE_PROJECT_ID = "g-smart-guyangan";
const cors = {
  "Access-Control-Allow-Origin": GSMART_ORIGIN,
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type",
  "Access-Control-Max-Age": "600",
  "Cache-Control": "no-store",
  "Pragma": "no-cache",
  "Vary": "Origin",
  "X-Content-Type-Options": "nosniff",
};
const str = (x: unknown, max=100) => String(x ?? "").trim().slice(0,max);
const answer = (body: unknown, status=200) => new Response(JSON.stringify(body), {
  status, headers:{...cors,"Content-Type":"application/json; charset=utf-8"},
});
function fv(doc: any, key:string) {
  const v=doc?.fields?.[key];
  if(v&&"stringValue" in v)return v.stringValue;
  if(v&&"booleanValue" in v)return v.booleanValue;
  return null;
}
async function verifyAuthorizedReader(req: Request) {
  const header=req.headers.get("Authorization") || "";
  const token=/^Bearer\s+(\S+)$/i.exec(header)?.[1];
  if(!token || token.length>8192)throw new Error("UNAUTHORIZED");
  const userResp=await fetch(
    "https://identitytoolkit.googleapis.com/v1/accounts:lookup?key="+FIREBASE_API_KEY,
    {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({idToken:token}),
      signal:AbortSignal.timeout(12000)
    }
  );
  if(!userResp.ok)throw new Error("UNAUTHORIZED");
  const user=(await userResp.json())?.users?.[0];
  if(!user?.localId)throw new Error("UNAUTHORIZED");
  const p=await fetch(
    "https://firestore.googleapis.com/v1/projects/"+FIREBASE_PROJECT_ID+
      "/databases/(default)/documents/users/"+encodeURIComponent(user.localId),
    {headers:{Authorization:"Bearer "+token},signal:AbortSignal.timeout(12000)}
  );
  if(!p.ok)throw new Error("FORBIDDEN");
  const doc=await p.json();
  if(!canReadPrivateDispute({role:fv(doc,"role"),aktif:fv(doc,"aktif")}))throw new Error("FORBIDDEN");
  return user.localId;
}
function serviceConfig() {
  const url=Deno.env.get("SUPABASE_URL") || "";
  const key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if(!/^https:\/\/[a-z0-9-]+\.supabase\.co\/?$/.test(url) || !key)throw new Error("SERVER_CONFIG");
  return {url:url.replace(/\/$/,""),key};
}
async function fetchMetadata(caseId:string) {
  const {url,key}=serviceConfig();
  const params=new URLSearchParams({
    select:"case_id,offender_data,dispute_reason,dispute_explanation,sim_object_path,document_object_path,updated_at",
    case_id:"eq."+caseId,
    limit:"1"
  });
  const resp=await fetch(url+"/rest/v1/gsmart_dispute_evidence_private?"+params.toString(),{
    headers:{apikey:key,Authorization:"Bearer "+key},
    signal:AbortSignal.timeout(12000)
  });
  if(!resp.ok)throw new Error("DATABASE_UNAVAILABLE");
  return (await resp.json())?.[0] || null;
}
async function fetchObject(caseId:string, kind:string, rawPath:unknown) {
  const path=safeEvidencePath(caseId,kind,rawPath);
  if(!path)return answer({error:"NOT_FOUND"},404);
  const {url,key}=serviceConfig();
  const encoded=path.split("/").map(encodeURIComponent).join("/");
  const response=await fetch(url+"/storage/v1/object/"+BUCKET+"/"+encoded,{
    headers:{apikey:key,Authorization:"Bearer "+key},
    signal:AbortSignal.timeout(15000)
  });
  if(!response.ok)return answer({error:"NOT_FOUND"},404);
  const expectedMime=mimeForPath(path);
  if(!expectedMime)return answer({error:"INVALID_MEDIA"},415);
  const size=Number(response.headers.get("content-length"));
  if(Number.isFinite(size)&&size>8388608)return answer({error:"INVALID_MEDIA"},415);
  // Object was uploaded by the privileged backend into an 8 MiB capped bucket.
  const contents=await response.arrayBuffer();
  if(contents.byteLength>8388608)return answer({error:"INVALID_MEDIA"},415);
  return new Response(contents,{
    status:200,
    headers:{
      ...cors,
      "Content-Type":expectedMime,
      "Content-Length":String(contents.byteLength),
      "Content-Disposition":kind==="document"&&expectedMime==="application/pdf" ? "attachment; filename=\"dokumen-sanggahan.pdf\"" : "inline",
    },
  });
}
Deno.serve(async (req:Request) => {
  if(req.method==="OPTIONS")return new Response("ok",{status:200,headers:cors});
  if(req.method!=="POST")return answer({error:"METHOD_NOT_ALLOWED"},405);
  try {
    await verifyAuthorizedReader(req);
    const body=await req.json().catch(()=>({}));
    const caseId=safeCaseId(body?.case_id);
    if(!caseId)return answer({error:"INVALID_CASE"},400);
    const action=str(body?.action,16);
    if(!["detail","media"].includes(action))return answer({error:"INVALID_ACTION"},400);
    const record=await fetchMetadata(caseId);
    if(!record)return answer({error:"NOT_FOUND"},404);
    if(action==="detail") {
      const offender=record.offender_data && typeof record.offender_data==="object"
        && !Array.isArray(record.offender_data) ? record.offender_data : {};
      return answer({
        found:true,
        case_id:caseId,
        offender,
        reason:record.dispute_reason || null,
        explanation:record.dispute_explanation || null,
        has_sim:!!safeEvidencePath(caseId,"sim",record.sim_object_path),
        has_document:!!safeEvidencePath(caseId,"document",record.document_object_path),
        updated_at:record.updated_at
      });
    }
    const kind=str(body?.kind,16);
    if(!["sim","document"].includes(kind))return answer({error:"INVALID_KIND"},400);
    return await fetchObject(caseId,kind,kind==="sim"?record.sim_object_path:record.document_object_path);
  } catch(e) {
    const type=String((e as Error)?.message || "");
    if(type==="UNAUTHORIZED")return answer({error:"UNAUTHORIZED"},401);
    if(type==="FORBIDDEN")return answer({error:"FORBIDDEN"},403);
    // Do not log tokens, user details, backend URLs, metadata or media.
    console.warn("G-Smart dispute evidence request failed: ",["SERVER_CONFIG","DATABASE_UNAVAILABLE"].includes(type)?type:"UNEXPECTED");
    return answer({error:"SERVICE_UNAVAILABLE"},503);
  }
});
