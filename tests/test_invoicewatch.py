import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from invoicewatch import (ATTRIBUTION_API, ATTRIBUTION_DOWNLOAD, decode_text, check_partners, diff_results, load_partners_csv,  # noqa: E402
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

    def test_headerless_csv_with_wrong_columns_refused(self):
        # ダウンロードの CSV の形(番号・T+13桁で始まる)なのに列が24でなければ、形が変わったとして止める
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
        # 既定はダウンロードデータ。Web-API の文言は出さない(事実と違う表示にしない)
        self.assertEqual(data["attribution"], ATTRIBUTION_DOWNLOAD)
        self.assertIn("（国税庁）", data["attribution"])

    def test_cli_api_source(self):
        out = subprocess.run([sys.executable, "-m", "invoicewatch", str(EX / "partners.csv"), str(EX / "public_records.json"),
                              "--date", "2026-11-11", "--source", "api"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        data = json.loads(out.stdout)
        self.assertEqual(data["attribution"], ATTRIBUTION_API)
        self.assertIn("国税庁によって保証されたものではない", data["attribution"])

    def test_cli_reads_shift_jis_csv(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "sjis.csv"
            f.write_bytes((EX / "partners.csv").read_text(encoding="utf-8-sig").encode("cp932"))
            out = subprocess.run([sys.executable, "-m", "invoicewatch", str(f), str(EX / "public_records.json"),
                                  "--date", "2026-11-11"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertIn(out.returncode, (0, 1), out.stderr)
        self.assertTrue(json.loads(out.stdout)["results"])


class TestInputEdges(unittest.TestCase):
    def test_decode_text(self):
        self.assertEqual(decode_text("名前".encode("cp932")), "名前")
        self.assertEqual(decode_text("\ufeff名前".encode("utf-8")), "名前")

    def test_japanese_and_wareki_dates(self):
        from datetime import date
        from invoicewatch.watch import _to_date
        for s in ("2026年10月31日", "令和8年10月31日", "R8.10.31", "Ｒ８．１０．３１", "2026/10/31", "20261031"):
            self.assertEqual(_to_date(s), date(2026, 10, 31), s)
        self.assertEqual(_to_date("令和元年5月1日"), date(2019, 5, 1))
        for s in ("2026/13/01", "あした", "٢٠٢٦-١٠-٣١"):
            self.assertIsNone(_to_date(s), s)

    def test_unreadable_date_is_flagged(self):
        p, r = sample()
        one = [dict(p[0], date="2026/13/01")]
        res = check_partners(one, r, on="2026-11-11")
        item = res["results"][0]
        self.assertTrue(item["alert"])
        self.assertTrue(item.get("date_unreadable"))
        self.assertTrue(any("取引日「2026/13/01」が読めません" in n for n in item["notes"]))


if __name__ == "__main__":
    unittest.main()


# 公表サイトのダウンロードの CSV(見出しなし・24列)。2026-11-16 に実物(diff_20261113.csv)で確かめた並びの見本(番号・名前は架空)
def dl_row(seq, num, process, kind="2", latest="1", reg="2023-10-01", upd="2026-11-12", dis="", exp="", name="見本商事株式会社",
           addr="兵庫県芦屋市見本町１－１"):
    cols = [str(seq), num, process, "0", kind, "1", latest, reg, upd, dis, exp, addr, "28", "206",
            "", "", "", "", name, "", "", "", "", ""]
    return ",".join(f'"{c}"' if i in (1, 11, 14, 17, 18, 19, 22, 23) else c for i, c in enumerate(cols))


class TestDownload(unittest.TestCase):
    def test_reads_real_layout_and_status(self):
        text = "\n".join([
            dl_row(1, "T9234567890123", "03", exp="2026-11-01"),
            dl_row(2, "T1234567890124", "01", reg="2026-11-12"),
            dl_row(3, "T2234567890125", "99"),
            dl_row(4, "T3234567890126", "01", kind="1", name=""),
        ]) + "\n"
        recs = load_public_records(text)
        self.assertEqual(len(recs), 4)
        r = recs["T9234567890123"][0]
        self.assertEqual((r["process"], r["expireDate"], r["name"]), ("03", "2026-11-01", "見本商事株式会社"))
        res = check_partners([{"name": "見本商事株式会社", "registration_number": "T9234567890123"},
                              {"name": "b", "registration_number": "T2234567890125"},
                              {"name": "個人", "registration_number": "T3234567890126"}], recs, on="2026-11-16")["results"]
        self.assertEqual([x["status"] for x in res], ["expired", "deleted", "registered"])
        self.assertTrue(any("目で確かめて" in n for n in res[2]["notes"]))   # 個人事業者は名前が空

    def test_name_with_comma_in_quotes(self):
        recs = load_public_records(dl_row(1, "T9234567890123", "01", name="見本,商事株式会社") + "\n")
        self.assertEqual(recs["T9234567890123"][0]["name"], "見本,商事株式会社")

    def test_zip_and_merge_full_then_diff(self):
        import io
        import zipfile
        from invoicewatch import count_records, merge_records

        def z(name, text):
            b = io.BytesIO()
            with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as f:
                f.writestr(name, text)
                f.writestr(name + ".asc", "-----BEGIN PGP SIGNATURE-----")
            return b.getvalue()
        full = z("h_all_20261101_005.csv", dl_row(1, "T9234567890123", "01", upd="2026-10-01") + "\n")
        diff = z("diff_20261113.csv", dl_row(1, "T9234567890123", "03", upd="2026-11-12", exp="2026-11-13") + "\n")
        recs = merge_records(load_public_records(full), load_public_records(diff))
        self.assertEqual(count_records(recs), {"numbers": 1, "records": 2})
        x = check_partners([{"name": "見本商事株式会社", "registration_number": "T9234567890123"}], recs, on="2026-11-16")["results"][0]
        self.assertEqual(x["status"], "expired")            # 差分(新しい)が全件(古い)に勝つ

    def test_zero_records_is_an_error_not_ok(self):
        with self.assertRaises(ValueError):
            load_public_records("[]")
        with self.assertRaises(ValueError):
            load_public_records({"announcement": []})

    def test_cli_with_zip_files(self):
        import io
        import tempfile
        import zipfile
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            b = io.BytesIO()
            with zipfile.ZipFile(b, "w") as f:
                f.writestr("diff_20261113.csv", dl_row(1, "T9234567890123", "03", exp="2026-11-13") + "\n")
            (d / "diff.zip").write_bytes(b.getvalue())
            (d / "p.csv").write_text("名前,登録番号\n見本商事株式会社,T9234567890123\n", encoding="utf-8")
            r = subprocess.run([sys.executable, "-m", "invoicewatch", str(d / "p.csv"), str(d / "diff.zip"), "--date", "2026-11-16"],
                               cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertIn("登録番号 1件", r.stderr)
            self.assertEqual(json.loads(r.stdout)["results"][0]["status"], "expired")
