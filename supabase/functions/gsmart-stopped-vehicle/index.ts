import {BUCKET,ORIGIN,safeId,safePath,mime,allowedProfile} from "./security.mjs";
const FIREBASE_API_KEY="AIzaSyBbF1MPzFK_EdUFV9CNh2ZZfuHxRgilm6o"; // public web key
const FIREBASE_PROJECT="g-smart-guyangan";
const cors={
 "Access-Control-Allow-Origin":ORIGIN,
 "Access-Control-Allow-Methods":"POST, OPTIONS",
 "Access-Control-Allow-Headers":"authorization,apikey,content-type",
 "Cache-Control":"no-store",
 "Pragma":"no-cache",
 "Vary":"Origin",
 "X-Content-Type-Options":"nosniff"
};
function fail(code:string,status:number){
 return new Response(JSON.stringify({error:code}),{status,headers:{...cors,"Content-Type":"application/json"}});
}
function strField(doc:any,name:string){
 const v=doc?.fields?.[name];
 return v&&"stringValue" in v?v.stringValue:null;
}
function boolField(doc:any,name:string){
 const v=doc?.fields?.[name];
 return v&&"booleanValue" in v?v.booleanValue:null;
}
async function verifyActiveFirebaseUser(req:Request){
 const auth=/^Bearer\s+(\S+)$/i.exec(req.headers.get("authorization")||"")?.[1];
 if(!auth||auth.length>8192)throw Error("UNAUTHORIZED");
 const resp=await fetch("https://identitytoolkit.googleapis.com/v1/accounts:lookup?key="+FIREBASE_API_KEY,{
   method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({idToken:auth}),signal:AbortSignal.timeout(12000)});
 if(!resp.ok)throw Error("UNAUTHORIZED");
 const uid=(await resp.json())?.users?.[0]?.localId;
 if(!uid)throw Error("UNAUTHORIZED");
 const url="https://firestore.googleapis.com/v1/projects/"+FIREBASE_PROJECT+"/databases/(default)/documents/users/"+encodeURIComponent(uid);
 const profileResp=await fetch(url,{headers:{authorization:"Bearer "+auth},signal:AbortSignal.timeout(12000)});
 if(!profileResp.ok)throw Error("FORBIDDEN");
 const profile=await profileResp.json();
 if(!allowedProfile({role:strField(profile,"role"),aktif:boolField(profile,"aktif")}))throw Error("FORBIDDEN");
}
function connection(){
 const url=(Deno.env.get("SUPABASE_URL")||"").replace(/\/$/,"");
 const key=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
 if(!/^https:\/\/[a-z0-9-]+\.supabase\.co$/.test(url)||!key)throw Error("CONFIG");
 return {url,key};
}
async function getPhotoPath(cid:string){
 const {url,key}=connection();
 const params=new URLSearchParams({
   select:"vehicle_object_path",case_id:"eq."+cid,limit:"1"});
 const resp=await fetch(url+"/rest/v1/gsmart_stopped_vehicle_private?"+params,{
   headers:{apikey:key,authorization:"Bearer "+key},signal:AbortSignal.timeout(12000)});
 if(!resp.ok)throw Error("DATABASE");
 const raw=(await resp.json())?.[0]?.vehicle_object_path;
 return safePath(cid,raw);
}
async function respondPhoto(path:string){
 const {url,key}=connection();
 const res=await fetch(url+"/storage/v1/object/"+BUCKET+"/"+path.split("/").map(encodeURIComponent).join("/"),{
   headers:{apikey:key,authorization:"Bearer "+key},signal:AbortSignal.timeout(15000)});
 if(!res.ok)return fail("NOT_FOUND",404);
 const type=mime(path);
 if(!type)return fail("UNSUPPORTED",415);
 const buffer=await res.arrayBuffer();
 if(buffer.byteLength>10485760)return fail("FILE_TOO_LARGE",413);
 return new Response(buffer,{status:200,headers:{
   ...cors,
   "Content-Type":type,
   "Content-Length":String(buffer.byteLength),
   "Content-Disposition":"inline"
 }});
}
Deno.serve(async(req:Request)=>{
 if(req.method==="OPTIONS")return new Response("ok",{headers:cors});
 if(req.method!=="POST")return fail("METHOD_NOT_ALLOWED",405);
 try{
   await verifyActiveFirebaseUser(req);
   const body=await req.json().catch(()=>({}));
   const cid=safeId(body?.case_id);
   if(!cid)return fail("INVALID_CASE",400);
   const path=await getPhotoPath(cid);
   if(!path)return fail("NOT_FOUND",404);
   return await respondPhoto(path);
 }catch(err){
   const type=String((err as Error)?.message||"");
   if(type==="UNAUTHORIZED")return fail("UNAUTHORIZED",401);
   if(type==="FORBIDDEN")return fail("FORBIDDEN",403);
   // Intentionally never log personal info, authenticated URLs or tokens.
   return fail("SERVICE_UNAVAILABLE",503);
 }
});
