import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from invoicewatch import (ATTRIBUTION_API, check_partners, diff_results, load_partners_csv,  # noqa: E402
                          load_public_records, normalize_regno)

EX = ROOT / "examples"


def sample():
    p = load_partners_csv((EX / "partners.csv").read_text(encoding="utf-8"))
    r = load_public_records((EX / "public_records.json").read_text(encoding="utf-8"))
    return p, r


class TestNumber(unittest.TestCase):
    def test_fullwidth_and_hyphen(self):
        n, _ = normalize_regno("Ｔ３９８７-６５４３-２１０９８")
        self.assertEqual(n, "T3987654321098")

    def test_add_t(self):
        n, notes = normalize_regno("9234567890123")
        self.assertEqual(n, "T9234567890123")
        self.assertTrue(any("T を補いました" in x for x in notes))

    def test_bad(self):
        self.assertIsNone(normalize_regno("T123")[0])
        self.assertIsNone(normalize_regno("")[0])

    def test_check_digit_note(self):
        _, notes = normalize_regno("T1234567890123")
        self.assertTrue(any("検査用数字" in x for x in notes))


class TestCheck(unittest.TestCase):
    def setUp(self):
        self.p, self.r = sample()
        self.res = check_partners(self.p, self.r, on="2026-11-11")
        self.by = {x["name"]: x for x in self.res["results"]}

    def test_registered(self):
        x = self.by["見本商事株式会社"]
        self.assertEqual(x["status"], "registered")
        self.assertTrue(x["name_match"])
        self.assertFalse(x["alert"])

    def test_revoked_and_kabu(self):
        x = self.by["(株)見本工業"]
        self.assertEqual(x["status"], "revoked")
        self.assertEqual(x["status_ja"], "取消")
        self.assertTrue(x["name_match"])  # (株) と 株式会社 は同じとみなす

    def test_name_change(self):
        x = self.by["見本運輸合同会社"]
        self.assertEqual(x["status"], "registered")
        self.assertFalse(x["name_match"])
        self.assertTrue(x["alert"])

    def test_expired_individual_without_name(self):
        x = self.by["見本デザイン(個人)"]
        self.assertEqual(x["status"], "expired")
        self.assertIsNone(x["name_match"])
        self.assertTrue(any("目で確かめて" in n for n in x["notes"]))

    def test_bad_and_not_found(self):
        self.assertEqual(self.by["番号まちがい株式会社"]["status"], "bad_number")
        self.assertEqual(self.by["載っていない株式会社"]["status"], "not_found")

    def test_transaction_date_before_revocation(self):
        p = [{"name": "(株)見本工業", "registration_number": "T9111111111111", "date": "2026-10-15"}]
        x = check_partners(p, self.r, on="2026-11-11")["results"][0]
        self.assertEqual(x["status"], "registered")

    def test_not_yet(self):
        p = [{"name": "見本運輸合同会社", "registration_number": "T3987654321098", "date": "2024-03-31"}]
        self.assertEqual(check_partners(p, self.r)["results"][0]["status"], "not_yet")

    def test_limit(self):
        res = check_partners(self.p, self.r, on="2026-11-11", limit=2)
        self.assertEqual(len(res["results"]), 2)
        self.assertEqual(res["skipped"], len(self.p) - 2)

    def test_summary(self):
        self.assertEqual(self.res["summary"]["registered"], 2)
        self.assertEqual(self.res["alerts"], 5)


class TestRecords(unittest.TestCase):
    def test_latest_wins(self):
        recs = load_public_records([
            {"registratedNumber": "T9234567890123", "latest": "0", "updateDate": "2026-01-01", "registrationDate": "2023-10-01", "name": "旧名"},
            {"registratedNumber": "T9234567890123", "latest": "1", "updateDate": "2025-01-01", "registrationDate": "2023-10-01", "disposalDate": "2026-02-01", "name": "新名"},
        ])
        x = check_partners([{"name": "新名", "registration_number": "T9234567890123"}], recs, on="2026-11-11")["results"][0]
        self.assertEqual(x["status"], "revoked")

    def test_deleted(self):
        recs = load_public_records([{"registratedNumber": "T9234567890123", "process": "99", "latest": "1"}])
        x = check_partners([{"name": "a", "registration_number": "T9234567890123"}], recs)["results"][0]
        self.assertEqual(x["status"], "deleted")

    def test_header_csv(self):
        recs = load_public_records("登録番号,登録年月日,取消年月日,失効年月日,氏名又は名称\nT9234567890123,2023-10-01,,,見本商事株式会社\n")
        self.assertIn("T9234567890123", recs)

    def test_headerless_csv_refused(self):
        with self.assertRaises(ValueError):
            load_public_records("1,T9234567890123,01,0,2,1,1,2023-10-01\n")


class TestDiff(unittest.TestCase):
    def test_only_changes(self):
        p, r = sample()
        before = check_partners(p, r, on="2026-10-15")
        after = check_partners(p, r, on="2026-11-11")
        ch = diff_results(before, after)
        names = {(c["name"], c["kind"]) for c in ch}
        self.assertIn(("(株)見本工業", "status"), names)
        self.assertNotIn(("見本商事株式会社", "status"), names)
        self.assertEqual(diff_results(after, after), [])

    def test_new_and_removed(self):
        p, r = sample()
        a = check_partners(p[:2], r, on="2026-11-11")
        b = check_partners(p[1:3], r, on="2026-11-11")
        kinds = sorted(c["kind"] for c in diff_results(a, b))
        self.assertEqual(kinds, ["new", "removed"])


class TestCli(unittest.TestCase):
    def test_cli_and_attribution(self):
        out = subprocess.run([sys.executable, "-m", "invoicewatch", str(EX / "partners.csv"), str(EX / "public_records.json"),
                              "--date", "2026-11-11"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(out.returncode, 1)
        data = json.loads(out.stdout)
        self.assertEqual(data["attribution"], ATTRIBUTION_API)
        self.assertIn("国税庁によって保証されたものではない", data["attribution"])


if __name__ == "__main__":
    unittest.main()
