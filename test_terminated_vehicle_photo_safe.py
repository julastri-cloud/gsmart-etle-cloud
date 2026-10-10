import unittest
from urllib.parse import urlparse,parse_qs
from diagnose_terminated_vehicle_photo_safe import build_detail_url,MEDIA_STRUCTURE_JS

class PhotoSourceSafeTest(unittest.TestCase):
    def test_known_stopped_case_url_only(self):
        result=urlparse(build_detail_url("37359"))
        self.assertEqual(result.scheme,"https")
        self.assertEqual(result.hostname,"etilang-djpd.kemenhub.go.id")
        self.assertEqual(result.port,9000)
        self.assertEqual(result.path,"/admin-etle/dihentikan_detail.php")
        self.assertEqual(parse_qs(result.query),{"violation_id":["37359"]})
    def test_reject_external_urls_and_query_injection(self):
        for x in ["","37359&anything=1","https://evil.example","../37","37/59"]:
            with self.subTest(x=x):
                with self.assertRaises(ValueError):build_detail_url(x)
    def test_only_metadata_and_nothing_sensitive_is_emitted(self):
        for required in ("#fullFrame","#foto_bukti_frame","#detailPelanggaran","#informasiKendaraan","naturalWidth","source_type"):
            self.assertIn(required,MEDIA_STRUCTURE_JS)
        for banned in ("console.log","outerHTML","innerHTML","document.body.innerText","response.text","XMLHttpRequest","fetch("):
            self.assertNotIn(banned,MEDIA_STRUCTURE_JS)

if __name__=="__main__":unittest.main()
