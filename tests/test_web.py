"""画面(web/)のテスト。JavaScript の照合が Python の本体と同じ答えを出すか、外へ通信しないかを確かめる。"""
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from invoicewatch import check_partners, diff_results, load_partners_csv, load_public_records  # noqa: E402

WEB = ROOT / "web"
EX = ROOT / "examples"

NODE_RUN = r'''
const IW = require(process.argv[1]);
const fs = require('fs');
const p = IW.loadPartnersCsv(fs.readFileSync(process.argv[2], 'utf8'));
const r = IW.loadPublicRecords(fs.readFileSync(process.argv[3], 'utf8'));
const on = process.argv[4];
const res = IW.checkPartners(p, r, on, process.argv[5] === '-' ? null : Number(process.argv[5]));
const prev = JSON.parse(JSON.stringify(res));
prev.results[0].status = 'revoked';
prev.results[1].public_name = '旧名';
process.stdout.write(JSON.stringify({res, diff: IW.diffResults(prev, res), csv: IW.resultsToCsv(res),
  quoted: IW.parseCsv('名前,登録番号\n"見本, ""株""",T9234567890123\n')}));
'''


def run_node(on="2026-11-11", limit="-"):
    r = subprocess.run(["node", "-e", NODE_RUN, str(WEB / "watch.js"), str(EX / "partners.csv"),
                        str(EX / "public_records.json"), on, limit],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


KEYS = ("name", "input", "number", "notes", "status", "status_ja", "public_name", "name_match",
        "registration_date", "disposal_date", "expire_date", "alert")


@unittest.skipUnless(shutil.which("node"), "node が無い")
class TestSameAsPython(unittest.TestCase):
    def py(self, on="2026-11-11", limit=None):
        p = load_partners_csv((EX / "partners.csv").read_text(encoding="utf-8"))
        r = load_public_records((EX / "public_records.json").read_text(encoding="utf-8"))
        return check_partners(p, r, on=on, limit=limit)

    def test_results_match(self):
        for on in ("2026-11-11", "2026-10-31", "2023-09-30"):
            js = run_node(on)["res"]
            py = self.py(on)
            self.assertEqual(js["on"], py["on"])
            self.assertEqual(js["alerts"], py["alerts"], on)
            self.assertEqual(js["summary"], py["summary"], on)
            for a, b in zip(js["results"], py["results"]):
                self.assertEqual({k: a[k] for k in KEYS}, {k: b[k] for k in KEYS}, on)

    def test_free_limit(self):
        js = run_node(limit="3")["res"]
        py = self.py(limit=3)
        self.assertEqual(js["skipped"], py["skipped"])
        self.assertEqual(len(js["results"]), 3)

    def test_diff_match(self):
        out = run_node()
        py = self.py()
        prev = json.loads(json.dumps(py))
        prev["results"][0]["status"] = "revoked"
        prev["results"][1]["public_name"] = "旧名"
        self.assertEqual(out["diff"], diff_results(prev, py))

    def test_csv_export_and_quotes(self):
        out = run_node()
        self.assertTrue(out["csv"].startswith("名前,登録番号,状態"))
        self.assertIn("要確認", out["csv"])
        self.assertEqual(out["quoted"][1][0], '見本, "株"')


class TestNoNetwork(unittest.TestCase):
    def test_csp_blocks_connections(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn("connect-src 'none'", html)
        for src in re.findall(r'<script[^>]*src="([^"]+)"', html):
            self.assertNotIn("//", src, "外のスクリプトを読まない")

    def test_js_does_not_send(self):
        for f in ("watch.js", "app.js"):
            t = (WEB / f).read_text(encoding="utf-8")
            for bad in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "import("):
                self.assertNotIn(bad, t, f)

    def test_attribution_text_kept(self):
        t = (WEB / "watch.js").read_text(encoding="utf-8")
        from invoicewatch import ATTRIBUTION_API
        self.assertIn(ATTRIBUTION_API.split("、")[0], t)
        self.assertIn("サービスの内容は国税庁によって保証されたものではない", t)

    def test_legal_pages(self):
        for f in ("terms.html", "privacy.html"):
            self.assertTrue((WEB / f).exists(), f)


if __name__ == "__main__":
    unittest.main()
