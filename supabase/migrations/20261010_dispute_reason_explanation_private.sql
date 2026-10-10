-- Separate free-text objection explanation from the categorical reason.
-- Private case-linked table: no change to public etle_disputes or etle_photos.
ALTER TABLE public.gsmart_dispute_evidence_private
  ADD COLUMN IF NOT EXISTS dispute_explanation text;
COMMENT ON COLUMN public.gsmart_dispute_evidence_private.dispute_reason IS
  'ETLE Hub Data Sanggahan > Alasan Disanggah (category)';
COMMENT ON COLUMN public.gsmart_dispute_evidence_private.dispute_explanation IS
  'ETLE Hub Data Sanggahan > Keterangan Sanggahan (free-text explanation)';
