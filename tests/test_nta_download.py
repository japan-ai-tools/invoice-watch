"""差分データを取る部分(通信は差し替えて試す。本物のサイトにはつながない)。"""
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from invoicewatch import nta_download as nd  # noqa: E402

# 2026-11-16 に確かめたページの形(行の作り)
PAGE = """<table><tr><th scope="col">ファイル作成日</th><th>ダウンロードファイル</th></tr>
<tr class="bgwhite csv_history_rowgroup1"> <th scope="row" rowspan="1">令和8年11月13日</th> <td><a href="#" onclick="return doDownload('5328','01');"> zip 11KB </a></td></tr>
<tr class="bggray csv_history_rowgroup1"> <th scope="row" rowspan="1">令和8年11月12日</th> <td><a href="#" onclick="return doDownload('5325','01');"> zip 45KB </a></td></tr>
<tr> <th scope="row">令和8年11月11日</th> <td><a href="#" onclick="return doDownload('5322','01');"> zip 31KB </a></td></tr>
</table><table><tr><th scope="row">令和8年11月13日</th><td><a href="#" onclick="return doDownload('5329','11');">zip</a></td></tr></table>"""


def zbytes(csv=True):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("diff_x.csv" if csv else "x.txt", "1,\"T9234567890123\"\n")
    return b.getvalue()


class TestNtaDownload(unittest.TestCase):
    def test_list_only_csv_newest_first(self):
        self.assertEqual(nd.list_diffs(PAGE), [("2026-11-13", "5328"), ("2026-11-12", "5325"), ("2026-11-11", "5322")])

    def test_fetch_saves_new_and_skips_existing(self):
        calls = []

        def get(url):
            calls.append(url)
            return PAGE.encode() if url == nd.LIST_URL else zbytes()
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "diff_20261113.zip").write_bytes(b"old")
            saved = nd.fetch(d, days=2, get=get, pause=0)
            self.assertEqual([p.name for p in saved], ["diff_20261112.zip"])
            self.assertEqual(calls[1:], [nd.FILE_URL.format(id="5325")])
            self.assertTrue(all("sabun" in u for u in calls))      # 検索機能には触らない

    def test_bad_zip_is_not_saved(self):
        def get(url):
            return PAGE.encode() if url == nd.LIST_URL else zbytes(csv=False)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                nd.fetch(d, days=1, get=get, pause=0)
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_changed_page_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                nd.fetch(d, get=lambda u: b"<html>maintenance</html>", pause=0)


if __name__ == "__main__":
    unittest.main()
