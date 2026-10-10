"""Offline checks for the read-only ETLE dispute detail probe."""
import unittest
from urllib.parse import urlparse,parse_qs
from diagnose_dispute_detail_safe import detail_url,DOM_PROBE,SAFE_DETAIL_ID,detail_report_ok


class SafeDisputeProbeTests(unittest.TestCase):
    def test_known_etle_url_and_fixed_status(self):
        url=detail_url("80971")
        p=urlparse(url)
        self.assertEqual(p.scheme,"https")
        self.assertEqual(p.hostname,"etilang-djpd.kemenhub.go.id")
        self.assertEqual(p.port,9000)
        self.assertEqual(p.path,"/admin-etle/terkonfirmasi_detail.php")
        self.assertEqual(parse_qs(p.query),{"id":["80971"],"status_konfirmasi":["Tersanggah"]})

    def test_id_input_cannot_inject_urls_or_query_options(self):
        for value in ["","../main","80971&status_konfirmasi=Other","https://example.com","x12","0123456789012"]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    detail_url(value)

    def test_detail_result_valid_even_with_hidden_login_markup(self):
        # ETLE detail includes an input[type=password] inside an unrelated
        # hidden element; an authenticated page is determined by detail DOM.
        report={
            "http_status":200,
            "on_expected_detail_path":True,
            "probe":{"detail_sections_present":True,"page_has_login_input":True}
        }
        self.assertTrue(detail_report_ok(report))

    def test_missing_detail_structure_or_redirect_is_rejected(self):
        for status,path,sections in [
            (403,True,True),
            (200,False,True),
            (200,True,False),
        ]:
            with self.subTest(status=status,path=path,sections=sections):
                self.assertFalse(detail_report_ok({
                    "http_status":status,
                    "on_expected_detail_path":path,
                    "probe":{"detail_sections_present":sections},
                }))

    def test_safe_dom_probe_returns_only_fixed_labels_and_structural_counts(self):
        self.assertIn("sections:",DOM_PROBE)
        self.assertIn("detail_sections_present",DOM_PROBE)
        self.assertIn("element_counts:",DOM_PROBE)
        self.assertNotIn("outerHTML",DOM_PROBE)
        self.assertNotIn("document.cookie",DOM_PROBE)
        self.assertNotIn("img.src",DOM_PROBE)
        self.assertNotIn("a.href",DOM_PROBE)


if __name__=="__main__":
    unittest.main()
