"""Synthetic-only tests for 5-module ETLE sync reliability and archive safety."""
import unittest
from datetime import datetime
from urllib.parse import urlparse,parse_qs
from unittest.mock import Mock,patch
import sync_etle as core
from daya_angkut_sosialisasi import source_shipping_snapshot_is_complete


class HistoricalWindowAuditTests(unittest.TestCase):
    def test_blanko_request_checks_old_cases_and_next_day_boundary(self):
        f=Mock(return_value={"data":[{"violation_id":"synthetic"}]})
        with patch.object(core,"browser_fetch",f),patch.object(core,"DATE_FROM","26-09-2026"),\
             patch.object(core,"FULL_DATE_FROM","01-08-2026"),patch.object(core,"DATE_TO_NEXT","11-10-2026"):
            rows=core.get_blanko_list(None)
        url=f.call_args.args[1]
        qs=parse_qs(urlparse(url).query)
        self.assertEqual(qs["dateFrom"],["01-08-2026"])
        self.assertEqual(qs["dateTo"],["11-10-2026"])
        self.assertEqual(len(rows),1)

    def test_disputes_request_checks_old_cases_and_next_day_boundary(self):
        f=Mock(return_value={"data":[{"violation_id":"synthetic"}]})
        with patch.object(core,"browser_fetch",f),patch.object(core,"DATE_FROM","26-09-2026"),\
             patch.object(core,"FULL_DATE_FROM","01-08-2026"),patch.object(core,"DATE_TO_NEXT","11-10-2026"):
            rows=core.get_disputes(None)
        url=f.call_args.args[1]
        qs=parse_qs(urlparse(url).query)
        self.assertEqual(qs["dateFrom"],["01-08-2026 00:00"])
        self.assertEqual(qs["dateTo"],["11-10-2026 00:00"])
        self.assertEqual(qs["status"],["Tersanggah"])
        self.assertEqual(len(rows),1)

    def test_lifecycle_priority_keeps_later_stages_and_raw_data(self):
        base={"status_etle":"SURAT_DICETAK","raw_data":{"source":"shipping"},"tnkb":"AB0000"}
        stopped=core.protect_case_lifecycle("DIHENTIKAN",base)
        self.assertEqual(stopped,{"tnkb":"AB0000"})
        disputed=core.protect_case_lifecycle("TERSANGGAH",base)
        self.assertEqual(disputed,{"tnkb":"AB0000"})
        promoted=core.protect_case_lifecycle("SURAT_DICETAK",
                              {"status_etle":"TERSANGGAH","raw_data":{"stage":"dispute"}})
        self.assertEqual(promoted["status_etle"],"TERSANGGAH")

    def test_historical_shipping_planner_is_idempotent_and_ignores_recent_rows(self):
        old={"source_id":"A","printed_date":"2026-08-14","status":"Tercetak",
             "status_description":"old","tracking_number":"A1","case_id":"synthetic"}
        recent={"source_id":"B","printed_date":"2026-10-04","status":"Tercetak"}
        source=[
            {"id":"A","status":"Terkirim","desc_terakhir":"Delivered","no_resi":"A1"},
            {"id":"A","status":"Terkirim","desc_terakhir":"Delivered","no_resi":"A1"},
            {"id":"B","status":"Terkirim"}
        ]
        changes,checked,unknown=core.plan_historical_shipping_updates(source,[old,recent],"2026-09-26")
        self.assertEqual(len(changes),1)
        self.assertEqual(checked,1)
        self.assertEqual(unknown,0)
        self.assertEqual(changes[0][3]["status"],"Terkirim")
        self.assertNotIn("tracking_number",changes[0][3])
        same={**old,"status":"Terkirim","status_description":"Delivered"}
        next_plan,_,_=core.plan_historical_shipping_updates(source,[same,recent],"2026-09-26")
        self.assertEqual(next_plan,[])

    def test_planner_does_not_blank_existing_tracking_or_status(self):
        saved={"source_id":"A","printed_date":"2026-08-14",
               "status":"Terkirim","tracking_number":"JNE123",
               "status_description":"Terkirim"}
        plans,_,_=core.plan_historical_shipping_updates(
           [{"id":"A","status":"","no_resi":"","desc_terakhir":""}],[saved],"2026-09-26")
        self.assertEqual(plans,[])

    def test_shipping_api_cannot_end_pagination_early(self):
        with patch.object(core,"browser_fetch",return_value={"recordsFiltered":9,"data":[]}):
            with self.assertRaisesRegex(RuntimeError,"pagination"):
                core.get_printed_list(None)

    def test_no_unintended_blankos_or_disputes_from_empty_list(self):
        with patch.object(core,"browser_fetch",return_value={"data":[]}):
            with patch.object(core,"FULL_DATE_FROM","01-08-2026"):
                self.assertEqual(core.get_disputes(None),[])
                self.assertEqual(core.get_blanko_list(None),[])


class ArchiveProtectionTests(unittest.TestCase):
    def test_socialization_guards_source_outage_and_partial_snapshot(self):
        refs={"S"+str(i) for i in range(100)}
        self.assertFalse(source_shipping_snapshot_is_complete([],set(),refs))
        self.assertFalse(source_shipping_snapshot_is_complete([{}]*11,set(list(refs)[:11]),refs))
        self.assertTrue(source_shipping_snapshot_is_complete([{}]*90,set(list(refs)[:90]),refs))

    def test_full_sync_reconciliation_skips_truncated_source(self):
        refs={"R"+str(i) for i in range(100)}
        shipping=[{"case_id":"synthetic"+str(i),"ref_number":"R"+str(i),"printed_date":"2026-08-12"} for i in range(100)]
        sb=Mock()
        sb.table.return_value.select.return_value.execute.return_value.data=[]
        def pages(_sb,table,fields,**kwargs):
            if table=="etle_shipping":
                return shipping
            return []
        with patch.object(core,"select_all_pages",side_effect=pages),\
             patch.object(core,"SYNC_MODE","full"),patch.object(core,"DATE_FROM","01-08-2026"):
            result=core.reconcile_shipping_archives(sb,set(list(refs)[:10]))
        self.assertEqual(result["skipped"],"source_snapshot_incomplete")
        self.assertEqual(result["archived"],0)
        sb.table.return_value.update.assert_not_called()

    def test_socialization_output_logs_only_counts(self):
        from pathlib import Path
        code=Path("daya_angkut_sosialisasi.py").read_text()
        self.assertIn('if not source_shipping_snapshot_is_complete',code)
        self.assertIn('public_summary',code)
        self.assertIn('json.dump(public_summary',code)
        self.assertNotIn('log(json.dumps(result',code)


if __name__=="__main__":unittest.main()
