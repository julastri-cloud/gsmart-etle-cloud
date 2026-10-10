"""Offline-only regression tests for the ETLE stopped-case history window."""
import ast
import unittest
from pathlib import Path
from urllib.parse import parse_qs,urlparse,urlencode
from unittest.mock import Mock


class StoppedWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=Path("sync_etle.py").read_text(encoding="utf-8")
        cls.ast=ast.parse(cls.source)
        fn=next(n for n in cls.ast.body if isinstance(n,ast.FunctionDef) and n.name=="get_terminated")
        cls.fn=compile(ast.Module(body=[fn],type_ignores=[]),"<safe-stopped-slice>","exec")

    def call_source(self,date_from="26-09-2026",full_from="01-08-2026"):
        received=[]
        def fetch(_page,url):
            received.append(url)
            return {"data":[{"synthetic":1}]}
        from datetime import datetime
        namespace={
            "DATE_FROM":date_from,
            "FULL_DATE_FROM":full_from,
            "DATE_TO":"10-10-2026",
            "DATE_TO_NEXT":"11-10-2026",
            "URL_TERMINATED":"https://etle.example.test/terminated",
            "SYNC_LIMIT":0,"time":Mock(time=lambda:123),
            "urlencode":urlencode,
            "browser_fetch":fetch,
            "ddmmyyyy_to_iso":lambda x:datetime.strptime(x,"%d-%m-%Y").strftime("%Y-%m-%d")
        }
        exec(self.fn,namespace)
        rows=namespace["get_terminated"](None)
        return parse_qs(urlparse(received[0]).query),rows

    def test_incremental_uses_historical_start_not_14_day_lookback(self):
        query,rows=self.call_source()
        self.assertEqual(query["dateFrom"],["2026-08-01"])
        self.assertEqual(query["dateTo"],["11-10-2026"])
        self.assertEqual(len(rows),1)

    def test_full_history_start_is_configurable(self):
        query,_=self.call_source(full_from="15-08-2026")
        self.assertEqual(query["dateFrom"],["2026-08-15"])

    def test_other_etle_modules_and_notification_flow_are_unchanged(self):
        self.assertIn("def get_disputes(page):",self.source)
        self.assertIn('p = {"dateFrom": f"{DATE_FROM} 00:00", "dateTo": f"{DATE_TO_NEXT} 00:00"',self.source)
        self.assertIn('summaries["shipping"] = sync_shipping(page, supabase)',self.source)
        self.assertIn('summaries["terminated"] = sync_terminated(page, supabase)',self.source)
        self.assertIn('send_sync_fcm_notifications(summaries)',self.source)

if __name__=="__main__":unittest.main()
