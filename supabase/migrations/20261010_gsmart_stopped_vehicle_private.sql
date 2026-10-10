-- Additive, service-role-only storage for vehicle violation photographs
-- from etle/admin-etle/dihentikan_detail.php. Do not modify etle_photos
-- or public photo policies; do not store SIM/objection documents here.
CREATE TABLE IF NOT EXISTS public.gsmart_stopped_vehicle_private (
  case_id uuid PRIMARY KEY REFERENCES public.etle_cases(case_id) ON DELETE RESTRICT,
  vehicle_object_path text,
  source_checked_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT gsmart_stopped_vehicle_path_check CHECK (
    vehicle_object_path IS NULL OR vehicle_object_path ~
    ('^' || case_id::text || '/vehicle/[a-f0-9]{24}[.](jpg|png|webp)$')
  )
);
ALTER TABLE public.gsmart_stopped_vehicle_private ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.gsmart_stopped_vehicle_private FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.gsmart_stopped_vehicle_private TO service_role;
-- Intentionally NO authenticated RLS policies.

INSERT INTO storage.buckets (id,name,public,file_size_limit,allowed_mime_types)
VALUES (
  'gsmart-stopped-vehicles-private',
  'gsmart-stopped-vehicles-private',
  false,10485760,
  ARRAY['image/jpeg','image/png','image/webp']
) ON CONFLICT(id) DO NOTHING;
-- Private storage.objects has no authenticated SELECT policies.
