export const BUCKET = "gsmart-dispute-private";
export const GSMART_ORIGIN = "https://uppkb-guyangan.github.io";
export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export function normalizeRole(value) {
  return String(value ?? "").trim().toUpperCase();
}
export function canReadPrivateDispute(profile) {
  const role = normalizeRole(profile?.role);
  return profile?.aktif === true && (role === "ADMIN" || role === "WASATPEL");
}
export function safeCaseId(value) {
  return typeof value === "string" && UUID_RE.test(value.trim()) ? value.trim().toLowerCase() : null;
}
export function safeEvidencePath(caseId, kind, raw) {
  const cid = safeCaseId(caseId);
  if (!cid || !["sim","document"].includes(kind) || typeof raw !== "string") return null;
  const extensions = kind === "sim" ? "(jpg|jpeg|png|webp)" : "(jpg|jpeg|png|webp|pdf)";
  const re = new RegExp("^" + cid + "/" + kind + "/[A-Za-z0-9_.-]{1,100}\\." + extensions + "$","i");
  return re.test(raw) ? raw : null;
}
export function mimeForPath(path) {
  const ext = String(path||"").split(".").at(-1)?.toLowerCase();
  return ({jpg:"image/jpeg",jpeg:"image/jpeg",png:"image/png",webp:"image/webp",pdf:"application/pdf"})[ext] || null;
}
