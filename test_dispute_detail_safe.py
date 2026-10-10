"""Offline checks for the read-only ETLE dispute detail probe."""
import unittest
from urllib.parse import urlparse,parse_qs
from diagnose_dispute_detail_safe import detail_url,DOM_PROBE,SAFE_DETAIL_ID


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

    def test_safe_dom_probe_returns_only_fixed_labels_and_structural_counts(self):
        self.assertIn("sections:",DOM_PROBE)
        self.assertIn("element_counts:",DOM_PROBE)
        self.assertNotIn("outerHTML",DOM_PROBE)
        self.assertNotIn("document.cookie",DOM_PROBE)
        self.assertNotIn("img.src",DOM_PROBE)
        self.assertNotIn("a.href",DOM_PROBE)


if __name__=="__main__":
    unittest.main()
