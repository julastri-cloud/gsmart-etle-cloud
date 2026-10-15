"""Offline synthetic-only tests for automatic, historical private dispute sync."""
import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime,timezone,timedelta
from unittest.mock import Mock, patch

from extract_dispute_detail_readonly import EXTRACTION_JS
from sync_private_dispute_one import import_case_with_page, select_loaded_media
from sync_private_disputes_auto import eligible, select_batch, utc_time

A="9fe2d406-bf92-4b9e-8b0e-14e0f67320c1"
B="a82e2546-bf92-4b9e-8b0e-14e0f67320c2"
C="a82e2546-bf92-4b9e-8b0e-14e0f67320c3"
NOW=datetime(2026,10,10,9,0,tzinfo=timezone.utc)


class AutoPrivateEvidenceTests(unittest.TestCase):
    def test_backfill_includes_currently_stopped_cases_from_history(self):
        # Three historical disputes; one previously STOPPED, neither is dropped.
        ds=[
            {"case_id":A,"violation_id":"80971","terminated":False},
            {"case_id":B,"violation_id":"80123","terminated":True},
            {"case_id":C,"violation_id":"80345","terminated":True},
        ]
        result=select_batch(ds,{},NOW,10)
        self.assertEqual(len(result),3)
        self.assertEqual({d["case_id"] for d in result},{A,B,C})
        self.assertEqual(len(select_batch(ds,{},NOW,2)),2)

    def test_invalid_case_ids_do_not_trigger_authenticated_scraping(self):
        d=[{"case_id":"invalid","violation_id":"80971"},
           {"case_id":A,"violation_id":"80971?admin=true"},
           {"case_id":B,"violation_id":"80123"}]
        self.assertEqual(len(select_batch(d,{},NOW,10)),1)

    def test_missing_archive_is_immediate_and_existing_case_has_cooldown(self):
        d={"case_id":A,"violation_id":"80971"}
        self.assertTrue(eligible(d,None,NOW))
        state={
            "sim_object_path":True,
            "document_object_path":True,
            "offender_data":True,
            "dispute_reason":False,
            "source_checked_at":(NOW-timedelta(hours=12)).isoformat()
        }
        self.assertFalse(eligible(d,state,NOW))
        self.assertTrue(eligible(d,{**state,"source_checked_at":(NOW-timedelta(hours=25)).isoformat()},NOW))
        full={**state,"dispute_reason":True,"dispute_explanation":True}
        self.assertFalse(eligible(d,{**full,"source_checked_at":(NOW-timedelta(hours=100)).isoformat()},NOW))
        self.assertTrue(eligible(d,{**full,"source_checked_at":(NOW-timedelta(hours=169)).isoformat()},NOW))

    def test_force_backfill_new_text_fields_without_changing_default_cooldown(self):
        dispute={"case_id":A,"violation_id":"80971"}
        recent={
            "source_checked_at":(NOW-timedelta(hours=1)).isoformat(),
            "offender_data":True,
            "sim_object_path":True,
            "document_object_path":True,
            "dispute_reason":False,
            "dispute_explanation":False
        }
        self.assertFalse(eligible(dispute,recent,NOW))
        self.assertTrue(eligible(dispute,recent,NOW,force_missing_text=True))
        self.assertEqual(len(select_batch([dispute],{A:recent},NOW,25,force_missing_text=True)),1)
        self.assertFalse(eligible(dispute,{**recent,"dispute_reason":True,"dispute_explanation":True},NOW,force_missing_text=True))

    def test_updated_private_data_keeps_existing_images_when_source_absent(self):
        fake_page=Mock()
        fake_page.goto.return_value=Mock(status=200)
        fake_page.url="https://etilang-djpd.kemenhub.go.id:9000/admin-etle/terkonfirmasi_detail.php?id=80971"
        fake_page.evaluate.return_value={}
        raw={
          "detail_present":True,
          "offender":{"nama":"SYNTHETIC_PRIVATE_NAME"},
          "reason":"ALASAN_SANGGAHAN_UJI",
          "explanation":"KETERANGAN_SANGGAHAN_UJI",
          "sim_candidates":[],
          "document_candidates":[],
        }
        existing=[{
            "offender_data":{"alamat":"SYNTHETIC_PRIVATE_ADDRESS"},
            "dispute_reason":None,
            "dispute_explanation":None,
            "sim_object_path":A+"/sim/old.jpg",
            "document_object_path":A+"/document/old.png"
        }]
        with patch("sync_private_dispute_one.resolve_case",return_value=A), \
             patch("sync_private_dispute_one.db_get",return_value=existing), \
             patch("sync_private_dispute_one.normalize_private_extraction",return_value=raw), \
             patch("sync_private_dispute_one.upsert_private") as upsert, \
             redirect_stdout(io.StringIO()) as logs:
            result=import_case_with_page(fake_page,"https://project.supabase.co","secret","80971",A)
        written=upsert.call_args.args[-1]
        self.assertTrue(result["reason_present"])
        self.assertEqual(written["sim_object_path"],A+"/sim/old.jpg")
        self.assertEqual(written["document_object_path"],A+"/document/old.png")
        self.assertEqual(written["dispute_reason"],"ALASAN_SANGGAHAN_UJI")
        self.assertEqual(written["dispute_explanation"],"KETERANGAN_SANGGAHAN_UJI")
        self.assertNotIn("SYNTHETIC",logs.getvalue())
        self.assertNotIn("80971",logs.getvalue())

    def test_source_images_must_be_large_enough_to_be_evidence(self):
        self.assertIsNone(select_loaded_media([
            {"kind":"img","loaded":True,"width":150,"height":150,"source":"https://etle.test/logo.png"}
        ],"sim"))
        self.assertIsNone(select_loaded_media([
            {"kind":"img","loaded":False,"width":900,"height":1600,"source":"https://etle.test/missing.jpg"}
        ],"sim"))
        self.assertEqual(select_loaded_media([
            {"kind":"img","loaded":True,"width":900,"height":1600,"source":"https://etle.test/sim.jpg"}
        ],"sim")["width"],900)
        self.assertEqual(select_loaded_media([
            {"kind":"img","loaded":True,"width":745,"height":326,"source":"https://etle.test/doc.png"}
        ],"document")["width"],745)

    def test_reject_mismatched_case_association_before_reading_evidence(self):
        page=Mock()
        with patch("sync_private_dispute_one.resolve_case",return_value=B), \
             patch("sync_private_dispute_one.db_get") as db:
            with self.assertRaisesRegex(RuntimeError,"CASE_ASSOCIATION_MISMATCH"):
                import_case_with_page(page,"https://project.supabase.co","key","80971",A)
            db.assert_not_called()
            page.goto.assert_not_called()

    def test_reason_from_objection_detail_not_termination_status(self):
        self.assertIn('const reasonLabel =',EXTRACTION_JS)
        self.assertIn('#InformasiDokumenAlasan',EXTRACTION_JS)
        self.assertIn('#alasanLainnya',EXTRACTION_JS)
        self.assertNotIn("terminated_cases",EXTRACTION_JS)
        self.assertNotIn("etle_terminated_cases",EXTRACTION_JS)
        self.assertNotIn("fetch(",EXTRACTION_JS)
        self.assertNotIn("outerHTML",EXTRACTION_JS)

    def test_datetime_parser_is_safe(self):
        self.assertIsNone(utc_time("bad timestamp"))
        self.assertIsNotNone(utc_time(NOW.isoformat()))

    def test_incomplete_recent_media_can_be_forced_once(self):
        dispute={"case_id":A,"violation_id":"80971"}
        current={"source_checked_at":NOW.isoformat(),"offender_data":True,
                 "dispute_reason":True,"dispute_explanation":True,
                 "sim_object_path":False,"document_object_path":False}
        self.assertFalse(eligible(dispute,current,NOW))
        self.assertTrue(eligible(dispute,current,NOW,force_missing_media=True))
        self.assertEqual(len(select_batch([dispute],{A:current},NOW,12,force_missing_media=True)),1)
        self.assertFalse(eligible(dispute,{**current,"sim_object_path":True,"document_object_path":True},
                                  NOW,force_missing_media=True))

    def test_pdf_document_link_and_sim_label_can_be_selected(self):
        from sync_private_dispute_one import evidence_candidates
        entries=[
          {"kind":"img","loaded":True,"width":30,"height":30,"source":"https://etilang-djpd.kemenhub.go.id:9000/icon.png"},
          {"kind":"a","label":"Unduh Dokumen Sanggahan","source":"https://etilang-djpd.kemenhub.go.id:9000/document.pdf"},
          {"kind":"a","label":"Lihat Foto SIM","source":"https://etilang-djpd.kemenhub.go.id:9000/sim.jpg"},
        ]
        self.assertEqual(len(evidence_candidates(entries,"document")),2)
        self.assertEqual(len(evidence_candidates(entries,"sim")),1)
        self.assertEqual(evidence_candidates(entries,"sim")[0]["label"],"Lihat Foto SIM")

    def test_cross_origin_redirect_is_rejected_without_follow(self):
        from sync_private_dispute_one import fetch_evidence
        c=Mock()
        c.request.get.return_value=Mock(status=302,headers={"location":"https://evil.example/steal.pdf"})
        with self.assertRaisesRegex(RuntimeError,"UNSAFE_EVIDENCE_REDIRECT"):
            fetch_evidence(c,{"source":"https://etilang-djpd.kemenhub.go.id:9000/media"},"document")
        self.assertEqual(c.request.get.call_count,1)
        self.assertEqual(c.request.get.call_args.kwargs["max_redirects"],0)

    def test_scoped_pdf_redirect_download_uses_magic_bytes(self):
        from sync_private_dispute_one import fetch_evidence
        from extract_dispute_detail_readonly import safe_etle_media_url
        c=Mock()
        data=b"%PDF-1.4 synthetic document"
        response=Mock(status=200,headers={"content-length":str(len(data))})
        response.body.return_value=data
        c.request.get.side_effect=[Mock(status=302,headers={"location":"/files/document.pdf"}),response]
        res=fetch_evidence(c,{"source":"https://etilang-djpd.kemenhub.go.id:9000/redirect"},"document")
        self.assertEqual(res[1:],("pdf","application/pdf"))
        self.assertEqual(c.request.get.call_args.args[0],"https://etilang-djpd.kemenhub.go.id:9000/files/document.pdf")
        self.assertIsNone(safe_etle_media_url("//evil.example/document.pdf"))
        self.assertIn('img[data-src]',EXTRACTION_JS)
        self.assertIn('document_candidates:media(evidence)',EXTRACTION_JS)

    def test_missing_media_is_partial_even_with_successful_text(self):
        page=Mock()
        page.goto.return_value=Mock(status=200)
        page.url="https://etilang-djpd.kemenhub.go.id:9000/admin-etle/terkonfirmasi_detail.php?id=80971"
        page.evaluate.return_value={}
        raw={"detail_present":True,"offender":{"nama":"synthetic"},
             "reason":"synthetic","explanation":"synthetic","sim_candidates":[],"document_candidates":[]}
        with patch("sync_private_dispute_one.resolve_case",return_value=A),\
             patch("sync_private_dispute_one.db_get",return_value=[]),\
             patch("sync_private_dispute_one.normalize_private_extraction",return_value=raw),\
             patch("sync_private_dispute_one.upsert_private"):
            outcome=import_case_with_page(page,"https://demo.supabase.co","synthetic-key","80971",A)
        self.assertEqual(outcome["result"],"PARTIAL")
        self.assertFalse(outcome["sim_saved_private"])
        self.assertFalse(outcome["document_saved_private"])


if __name__=="__main__":
    unittest.main()
