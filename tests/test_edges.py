"""判定の端(公開前点検の 7・8・11・12・18)。Python と JavaScript で同じ答えになるかも確かめる。"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from invoicewatch import check_partners, diff_results, load_partners_csv, load_public_records  # noqa: E402
from invoicewatch.__main__ import main  # noqa: E402
from invoicewatch.watch import normalize_regno  # noqa: E402

GOOD = "T9234567890123"
# 再登録した事業者(1回目は 2024-03-31 に取消、2回目は 2025-04-01 から)
HISTORY = [
    {"registratedNumber": GOOD, "process": "04", "latest": "0", "registrationDate": "2023-10-01",
     "updateDate": "2024-04-02", "disposalDate": "2024-03-31", "expireDate": "", "name": "見本商事株式会社"},
    {"registratedNumber": GOOD, "process": "01", "latest": "1", "registrationDate": "2025-04-01",
     "updateDate": "2025-04-01", "disposalDate": "", "expireDate": "", "name": "見本商事株式会社"},
]
NO_DATES = [
    {"registratedNumber": "T9111111111111", "process": "01", "latest": "1", "name": "日付なし株式会社"},
    {"registratedNumber": "T3987654321098", "process": "04", "latest": "1", "registrationDate": "2024-04-01",
     "disposalDate": "", "name": "取消日なし合同会社"},
]
PARTNERS_EXTRA = "名前,登録番号,取引日\n東京, 見本商事,T9234567890123,2026-01-05\n"

NODE = r'''
const IW = require(process.argv[1]);
const a = JSON.parse(process.argv[2]);
const out = {};
out.history = IW.checkPartners(a.partners, IW.loadPublicRecords(JSON.stringify(a.history)), "2026-11-11");
out.nodates = IW.checkPartners(a.partners2, IW.loadPublicRecords(JSON.stringify(a.nodates)), "2026-11-11");
out.extra = IW.loadPartnersCsv(a.extra);
out.arabic = IW.normalizeRegno("T٩٢٣٤٥٦٧٨٩٠١٢٣");
out.diff = IW.diffResults(a.prev, a.cur);
process.stdout.write(JSON.stringify(out));
'''


def partners_hist():
    return [{"name": "見本商事株式会社", "registration_number": GOOD, "date": "2023-12-01"},
            {"name": "見本商事株式会社", "registration_number": GOOD, "date": "2024-12-01"},
            {"name": "見本商事株式会社", "registration_number": GOOD, "date": "2026-11-01"}]


def partners_nodate():
    return [{"name": "日付なし株式会社", "registration_number": "T9111111111111", "date": ""},
            {"name": "取消日なし合同会社", "registration_number": "T3987654321098", "date": ""}]


class TestEdges(unittest.TestCase):
    def test_non_ascii_digits_are_bad(self):  # 点検7
        self.assertIsNone(normalize_regno("T٩٢٣٤٥٦٧٨٩٠١٢٣")[0])
        self.assertEqual(normalize_regno("T９２３４５６７８９０１２３")[0], GOOD)  # 全角は NFKC で ASCII になる

    def test_extra_columns_do_not_crash(self):  # 点検8
        p = load_partners_csv(PARTNERS_EXTRA)
        self.assertEqual(len(p), 1)
        self.assertIn("列が多い", p[0]["notes"][0])
        res = check_partners(p, load_public_records({"announcement": HISTORY}), on="2026-11-11")
        self.assertIn("列が多い", res["results"][0]["notes"][0])

    def test_reregistered_history(self):  # 点検11
        res = check_partners(partners_hist(), load_public_records({"announcement": HISTORY}), on="2026-11-11")
        self.assertEqual([r["status"] for r in res["results"]], ["registered", "revoked", "registered"])

    def test_single_record_not_yet_has_note(self):  # 点検11(履歴が無いとき)
        res = check_partners([{"name": "x", "registration_number": GOOD, "date": "2024-12-01"}],
                             load_public_records({"announcement": HISTORY[1:]}), on="2026-11-11")
        self.assertEqual(res["results"][0]["status"], "not_yet")
        self.assertTrue(any("再登録" in n for n in res["results"][0]["notes"]))

    def test_missing_dates_need_check(self):  # 点検12
        res = check_partners(partners_nodate(), load_public_records({"announcement": NO_DATES}), on="2026-11-11")
        self.assertEqual([r["status"] for r in res["results"]], ["no_date", "no_date"])
        self.assertTrue(all(r["alert"] for r in res["results"]))

    def test_diff_keeps_rows_with_different_dates(self):  # 点検18
        recs = load_public_records({"announcement": HISTORY})
        prev = check_partners(partners_hist(), recs, on="2026-11-11")
        cur = json.loads(json.dumps(prev))
        cur["results"][1]["status"] = "registered"
        ch = diff_results(prev, cur)
        self.assertEqual(len(ch), 1)
        self.assertEqual(ch[0]["kind"], "status")

    def test_diff_with_old_results_without_date(self):
        recs = load_public_records({"announcement": HISTORY})
        cur = check_partners(partners_hist()[:1], recs, on="2026-11-11")
        old = json.loads(json.dumps(cur))
        for r in old["results"]:
            del r["date"]
        self.assertEqual(diff_results(old, cur), [])

    def test_exit_codes(self):  # 点検18: 0=なし 1=要確認 2=動かせない
        with tempfile.TemporaryDirectory() as d:
            pc, rc = Path(d, "p.csv"), Path(d, "r.json")
            pc.write_text("名前,登録番号\n見本商事株式会社,T9234567890123\n", encoding="utf-8")
            rc.write_text(json.dumps({"announcement": HISTORY[1:]}), encoding="utf-8")
            self.assertEqual(main([str(pc), str(rc), "--date", "2026-11-11"]), 0)
            pc.write_text("名前,登録番号\n見本商事株式会社,T123\n", encoding="utf-8")
            self.assertEqual(main([str(pc), str(rc), "--date", "2026-11-11"]), 1)
            self.assertEqual(main([str(pc), str(Path(d, "無い.json"))]), 2)
            rc.write_text("{こわれた", encoding="utf-8")
            self.assertEqual(main([str(pc), str(rc)]), 2)

    def test_headers_file(self):  # 点検18: 埋め込み防止は _headers で
        t = (ROOT / "web" / "_headers").read_text(encoding="utf-8")
        self.assertIn("frame-ancestors 'none'", t)
        self.assertIn("X-Frame-Options: DENY", t)


@unittest.skipUnless(shutil.which("node"), "node が無い")
class TestEdgesSameInJs(unittest.TestCase):
    def test_same_answers(self):
        recs = load_public_records({"announcement": HISTORY})
        prev = check_partners(partners_hist(), recs, on="2026-11-11")
        cur = json.loads(json.dumps(prev))
        cur["results"][1]["status"] = "registered"
        prev["results"][0]["public_name"] = prev["results"][0].get("public_name") or "見本商事株式会社"
        cur["results"][0]["public_name"] = ""  # ダウンロードデータで名称が空 → 名称の変更にしない(0.2.2)
        arg = {"partners": partners_hist(), "history": {"announcement": HISTORY},
               "partners2": partners_nodate(), "nodates": {"announcement": NO_DATES},
               "extra": PARTNERS_EXTRA, "prev": prev, "cur": cur}
        r = subprocess.run(["node", "-e", NODE, str(ROOT / "web" / "watch.js"), json.dumps(arg, ensure_ascii=False)],
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        js = json.loads(r.stdout)
        py_h = check_partners(partners_hist(), recs, on="2026-11-11")
        py_n = check_partners(partners_nodate(), load_public_records({"announcement": NO_DATES}), on="2026-11-11")
        for a, b in ((js["history"], py_h), (js["nodates"], py_n)):
            self.assertEqual(a["summary"], b["summary"])
            self.assertEqual([(x["status"], x["notes"], x["alert"], x["date"]) for x in a["results"]],
                             [(x["status"], x["notes"], x["alert"], x["date"]) for x in b["results"]])
        self.assertEqual(js["extra"], load_partners_csv(PARTNERS_EXTRA))
        self.assertIsNone(js["arabic"][0])
        self.assertEqual(js["diff"], diff_results(prev, cur))
        self.assertNotIn("name", [c["kind"] for c in js["diff"]])
