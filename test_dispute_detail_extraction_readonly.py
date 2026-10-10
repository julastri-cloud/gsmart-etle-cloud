"""Offline tests: synthetic inputs only; never use genuine ETLE personal data."""
import json
import unittest
from extract_dispute_detail_readonly import (
    EXTRACTION_JS, normalize_private_extraction, safe_etle_media_url, safe_report
)


class DisputeExtractorReadOnlyTests(unittest.TestCase):
    def test_reject_non_etle_or_unsafe_source(self):
        for raw in (
            "", "javascript:alert(1)", "data:image/png;base64,abc",
            "https://example.org/private.png",
            "https://etilang-djpd.kemenhub.go.id/private.png",
            "http://etilang-djpd.kemenhub.go.id:9000/private.png",
            "https://etilang-djpd.kemenhub.go.id:9000@evil.example/private.png",
            "//evil.example/photo.jpg",
            "blob:https://etilang-djpd.kemenhub.go.id:9000/d",
        ):
            with self.subTest(source=raw):
                self.assertIsNone(safe_etle_media_url(raw))

    def test_accept_etle_relative_and_explicit_sources(self):
        self.assertEqual(
            safe_etle_media_url("/uploads/example.png"),
            "https://etilang-djpd.kemenhub.go.id:9000/uploads/example.png"
        )
        self.assertEqual(
            safe_etle_media_url("https://etilang-djpd.kemenhub.go.id:9000/img.jpg"),
            "https://etilang-djpd.kemenhub.go.id:9000/img.jpg"
        )

    def test_extract_to_memory_and_never_expose_private_values_in_report(self):
        fake = {
            "detail_present": True,
            "offender": {
                "nama": "NAMA RAHASIA CONTOH",
                "alamat": "ALAMAT RAHASIA CONTOH",
                "no_sim": "NOMOR_SIM_RAHASIA",
                "undocumented_private_field": "DISCARD",
            },
            "reason": "ALASAN_SANGGAHAN_RAHASIA",
            "sim_candidates": [{
                "kind": "img", "reference": "/uploads/sim-test-only.jpg?token=SECRET_TEST",
                "loaded": True
            }],
            "document_candidates": [{
                "kind": "img", "reference": "/uploads/document-test-only.png",
                "loaded": True
            }],
            "vehicle_exists": True,
            "vehicle_image_loaded": False
        }
        private = normalize_private_extraction(fake)
        self.assertEqual(private["offender"]["nama"], fake["offender"]["nama"])
        self.assertEqual(len(private["sim_candidates"]), 1)
        self.assertNotIn("undocumented_private_field", private["offender"])
        report = json.dumps(safe_report(private))
        for secret in ("NAMA RAHASIA", "ALAMAT RAHASIA", "NOMOR_SIM",
                       "ALASAN_SANGGAHAN", "/uploads/", "SECRET_TEST"):
            self.assertNotIn(secret, report)
        self.assertTrue(safe_report(private)["offender_field_presence"]["nama"])
        self.assertEqual(safe_report(private)["document_media_accepted"], 1)

    def test_extraction_scope_and_no_network_writes(self):
        self.assertIn("#informasiPelanggar", EXTRACTION_JS)
        self.assertIn("#InformasiDokumenAlasan", EXTRACTION_JS)
        self.assertIn("#alasanLainnya", EXTRACTION_JS)
        self.assertIn("#foto_bukti_frame", EXTRACTION_JS)
        for unsafe in ("fetch(", "XMLHttpRequest", ".submit(", "localStorage",
                       "document.body.innerText", "outerHTML", "window.open"):
            self.assertNotIn(unsafe, EXTRACTION_JS)

    def test_empty_records_are_safe(self):
        private = normalize_private_extraction(None)
        report = safe_report(private)
        self.assertFalse(report["detail_present"])
        self.assertEqual(report["sim_images_accepted"], 0)
        self.assertFalse(report["reason_present"])


if __name__ == "__main__":
    unittest.main()
