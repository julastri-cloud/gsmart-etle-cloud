"""Offline DOM-shape simulation; never uses live ETLE or personal data."""
import json
import subprocess
import unittest
from extract_dispute_detail_readonly import (
    EXTRACTION_JS, normalize_private_extraction, safe_report
)


def simulate_table(rows):
    script = """
const vm = require("node:vm");
const code = %s;
const pairs = %s;
const cell = text => ({matches:()=>true, innerText:text});
const root = { querySelectorAll:()=>[] };
const rows = pairs.map(line=>({children:line.map(cell)}));
const document = {
  querySelector: selector =>
    ["#detailPelanggaran","#informasiPelanggar","#InformasiDokumenAlasan"].includes(selector)
    ? root : null,
  querySelectorAll: selector => selector==="tr" ? rows : []
};
const result=vm.runInNewContext("("+code+")()",{document});
process.stdout.write(JSON.stringify(result));
""" % (json.dumps(EXTRACTION_JS),json.dumps(rows))
    proc=subprocess.run(["node","-e",script],text=True,capture_output=True,timeout=15,check=True)
    return json.loads(proc.stdout)


class DisputeLabelExtractionTests(unittest.TestCase):
    def test_real_etle_label_shapes_are_parsed_separately(self):
        raw=simulate_table([
            ["Alasan Disanggah",": KATEGORI_UJI"],
            ["Keterangan Sanggahan",": PENJELASAN_UJI_DENGAN_BUKTI"],
            ["Alasan Dihentikan",": ALASAN_PENGHENTIAN_BERBEDA"],
        ])
        private=normalize_private_extraction(raw)
        self.assertTrue(private["detail_present"])
        self.assertEqual(private["reason"],"KATEGORI_UJI")
        self.assertEqual(private["explanation"],"PENJELASAN_UJI_DENGAN_BUKTI")
        reported=json.dumps(safe_report(private))
        for value in ("KATEGORI_UJI","PENJELASAN_UJI","ALASAN_PENGHENTIAN"):
            self.assertNotIn(value,reported)
        self.assertTrue(safe_report(private)["reason_present"])
        self.assertTrue(safe_report(private)["explanation_present"])

    def test_missing_labels_are_not_filled_from_unrelated_fields(self):
        raw=simulate_table([
            ["Alasan Dihentikan",": TIDAK_DITERIMA"],
            ["Status Sanggahan",": TERSANGGAH"],
        ])
        private=normalize_private_extraction(raw)
        self.assertFalse(private["reason"])
        self.assertFalse(private["explanation"])

    def test_same_row_with_separate_colon_keeps_full_description(self):
        raw=simulate_table([
            ["Alasan Disanggah",":","KLASIFIKASI"],
            ["Keterangan Sanggahan",":","Uraian bukti kendaraan dan nota penjualan"]
        ])
        private=normalize_private_extraction(raw)
        self.assertEqual(private["reason"],"KLASIFIKASI")
        self.assertEqual(private["explanation"],"Uraian bukti kendaraan dan nota penjualan")


if __name__=="__main__":
    unittest.main()
