"""Synthetic-only tests for the private evidence importer."""
import hashlib
import unittest

from sync_private_dispute_one import detect_file_type, object_path, MAX_BYTES

CASE_ID="9fe2d406-bf92-4b9e-8b0e-14e0f67320c1"


class PrivateDisputeImporterTests(unittest.TestCase):
    def test_magic_bytes_only_allow_approved_images_and_pdf(self):
        self.assertEqual(detect_file_type(bytes.fromhex("ffd8ff") + b"test"),("jpg","image/jpeg"))
        self.assertEqual(detect_file_type(bytes.fromhex("89504e470d0a1a0a") + b"x"),("png","image/png"))
        self.assertEqual(detect_file_type(b"RIFF1234WEBPxxxx"),("webp","image/webp"))
        self.assertEqual(detect_file_type(b"%PDF-1.4 synthetic"),("pdf","application/pdf"))
        self.assertIsNone(detect_file_type(b"<html>not a real image</html>"))
        self.assertIsNone(detect_file_type(b"MZsampleexe"))

    def test_object_path_binds_evidence_to_single_case(self):
        blob=b"synthetic example, not real SIM"
        digest=hashlib.sha256(blob).hexdigest()[:24]
        path=object_path(CASE_ID,"sim",blob,"jpg")
        self.assertEqual(path,CASE_ID+"/sim/"+digest+".jpg")
        self.assertNotIn("example",path)
        self.assertEqual(object_path(CASE_ID,"document",blob,"pdf"),CASE_ID+"/document/"+digest+".pdf")
        with self.assertRaises(ValueError):
            object_path(CASE_ID,"sim",blob,"pdf")
        with self.assertRaises(AssertionError):
            object_path("not-a-uuid","sim",blob,"jpg")
        with self.assertRaises(AssertionError):
            object_path(CASE_ID,"../sim",blob,"jpg")

    def test_evidence_size_limit(self):
        self.assertEqual(MAX_BYTES,8*1024*1024)


if __name__=="__main__":
    unittest.main()
