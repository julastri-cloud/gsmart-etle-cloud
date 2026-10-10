export const BUCKET="gsmart-stopped-vehicles-private";
export const ORIGIN="https://uppkb-guyangan.github.io";
export const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export function safeId(x){return typeof x==="string"&&UUID.test(x.trim())?x.trim().toLowerCase():null}
export function allowedProfile(profile){return profile?.aktif===true && typeof profile?.role==="string"&&profile.role.trim().length>0}
export function safePath(cid,raw){
  const id=safeId(cid);
  if(!id||typeof raw!=="string")return null;
  return new RegExp("^"+id+"/vehicle/[a-f0-9]{24}[.](jpg|png|webp)$").test(raw)?raw:null;
}
export function mime(path){
 const ext=String(path||"").split(".").pop();
 return ({jpg:"image/jpeg",png:"image/png",webp:"image/webp"})[ext]||null;
}
