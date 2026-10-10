-- G-Smart private dispute evidence foundation.
-- This is ADDITIVE: existing ETLE cases, photos and pipelines are unchanged.
-- Private metadata is not readable from ordinary REST with anon/authenticated keys.
create table if not exists public.gsmart_dispute_evidence_private (
  case_id uuid primary key references public.etle_cases(case_id) on delete restrict,
  violation_id text,
  etle_detail_id text,
  offender_data jsonb not null default '{}'::jsonb,
  dispute_reason text,
  sim_object_path text,
  document_object_path text,
  source_checked_at timestamptz,
  updated_at timestamptz not null default now(),
  constraint gsmart_private_sim_path_chk check (
    sim_object_path is null or
    (sim_object_path ~ ('^' || case_id::text || '/sim/[A-Za-z0-9_.-]{1,100}\\.(jpg|jpeg|png|webp)$'))
  ),
  constraint gsmart_private_doc_path_chk check (
    document_object_path is null or
    (document_object_path ~ ('^' || case_id::text || '/document/[A-Za-z0-9_.-]{1,100}\\.(jpg|jpeg|png|webp|pdf)$'))
  )
);
alter table public.gsmart_dispute_evidence_private enable row level security;
revoke all on table public.gsmart_dispute_evidence_private from PUBLIC, anon, authenticated;
grant all on table public.gsmart_dispute_evidence_private to service_role;
-- Intentionally no policy for anon or authenticated: service-role only.

insert into storage.buckets (id,name,public,file_size_limit,allowed_mime_types)
values (
  'gsmart-dispute-private',
  'gsmart-dispute-private',
  false,
  8388608,
  array['image/jpeg','image/png','image/webp','application/pdf']
)
on conflict(id) do nothing;
-- Do not modify storage.objects policies; no public/authenticated access granted.
-- Private bucket + no object-level SELECT policies means service-role reads only.
