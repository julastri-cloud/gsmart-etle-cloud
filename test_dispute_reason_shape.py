"""Offline safety tests for the reason-structure audit (no ETLE access)."""
import unittest
from diagnose_dispute_reason_shape import REASON_SHAPE_JS


class ReasonShapeSafeTests(unittest.TestCase):
    def test_no_real_identity_or_text_in_audit_output(self):
        self.assertIn("reason_label_cells_value_nonempty",REASON_SHAPE_JS)
        self.assertIn("reason_named_controls_nonempty",REASON_SHAPE_JS)
        self.assertIn("reason_text_inline_detected",REASON_SHAPE_JS)
        self.assertIn("objection_section_images",REASON_SHAPE_JS)
        for banned in ("console.log","outerHTML","innerHTML","document.cookie",
                       "XMLHttpRequest","fetch(","window.open","document.body.innerText"):
            self.assertNotIn(banned,REASON_SHAPE_JS)

    def test_only_known_etle_form_scopes_are_inspected(self):
        self.assertIn("#InformasiDokumenAlasan",REASON_SHAPE_JS)
        self.assertIn("#informasiPelanggar",REASON_SHAPE_JS)
        self.assertIn("#detailPelanggaran",REASON_SHAPE_JS)
        self.assertIn("#alasanLainnya",REASON_SHAPE_JS)


if __name__=="__main__":
    unittest.main()
