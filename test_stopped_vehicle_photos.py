import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock,patch
from sync_stopped_vehicle_photos import (
 stopped_source_id,due,sync_one,fetch_photo_bytes,PHOTO_JS
)
CID="8bb1e604-2325-4586-80fa-16787b42a57e"
NOW=datetime(2026,10,10,9,tzinfo=timezone.utc)

class StoppedVehiclePhotoTests(unittest.TestCase):
 def test_raw_source_id_for_stopped_case_without_violation_id(self):
  self.assertEqual(stopped_source_id({"raw_data":{"id":"37359"},"violation_id":None}),"37359")
  self.assertEqual(stopped_source_id({"raw_data":{"id":"37359"},"violation_id":"37359"}),"37359")
  with self.assertRaisesRegex(RuntimeError,"SOURCE_ID_CONFLICT"):
   stopped_source_id({"raw_data":{"id":"37359"},"violation_id":"37360"})
  self.assertIsNone(stopped_source_id({"raw_data":{"id":"37359&admin=true"}}))
 def test_new_and_missing_are_due_but_existing_wait_one_month(self):
  self.assertTrue(due(None,NOW))
  old={"source_checked_at":(NOW-timedelta(hours=25)).isoformat(),"vehicle_object_path":None}
  self.assertTrue(due(old,NOW))
  full={**old,"vehicle_object_path":CID+"/vehicle/test.jpg"}
  self.assertFalse(due(full,NOW))
 def test_exact_only_loaded_violation_photo_is_selected(self):
  self.assertIn('document.querySelector("#foto_bukti_frame")',PHOTO_JS)
  self.assertIn('frame?.querySelector("img")',PHOTO_JS)
  self.assertIn('naturalWidth>=800',PHOTO_JS)
  self.assertNotIn("document.body.innerText",PHOTO_JS)
  self.assertNotIn("outerHTML",PHOTO_JS)
 def test_refuse_foreign_image_origin(self):
  page=Mock()
  with self.assertRaisesRegex(RuntimeError,"UNTRUSTED_PHOTO_ORIGIN"):
   fetch_photo_bytes(page,{"available":True,"src":"https://example.com/photo.jpg"})
  page.context.request.get.assert_not_called()
 def test_empty_source_retains_existing_saved_photo(self):
  page=Mock()
  page.goto.return_value=Mock(status=200)
  page.url="https://etilang-djpd.kemenhub.go.id:9000/admin-etle/dihentikan_detail.php?violation_id=37359"
  page.evaluate.return_value={"available":False}
  page.locator.return_value.count.return_value=1
  row={"case_id":CID,"raw_data":{"id":"37359"},"violation_id":"37359"}
  old={"vehicle_object_path":CID+"/vehicle/abc.jpg"}
  with patch("sync_stopped_vehicle_photos.save_state") as save, \
       patch("sync_stopped_vehicle_photos.fetch_photo_bytes") as download:
   self.assertTrue(sync_one(page,"https://demo.supabase.co","key",row,old))
   save.assert_called_once_with("https://demo.supabase.co","key",CID,None,old)
   page.wait_for_load_state.assert_called_once_with("networkidle",timeout=18000)
   page.wait_for_function.assert_called_once()
   download.assert_not_called()

if __name__=="__main__":unittest.main()
