"""国税庁の公表サイトから差分データ(CSV の ZIP)を取る。毎日の見張り用。

python -m invoicewatch.nta_download 保存先フォルダ [--days 3]

- 取るのは「公表情報ダウンロード」の差分データのページと、その ZIP だけ(2026-11-16 に実物で確かめた)。
  サイト利用規約が禁止しているのは「検索機能(登録番号で事業者を表示する機能)をプログラムで取ること」で、この道具はそれをしない
- 1回に取るのは新しい順に最大 --days 個まで。もう保存してある日は取らない。1つ取るごとに間を空ける
- 取った ZIP は中に CSV があるかを確かめてから保存する(壊れたファイル・別の物を保存しない)
- 照合の本体(watch.py)は通信しない。通信するのはこのファイルだけ
"""
import argparse
import io
import re
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

BASE = "https://www.invoice-kohyo.nta.go.jp"
LIST_URL = BASE + "/download/sabun"
FILE_URL = BASE + "/download/sabun/dlfile?dlFilKanriNo={id}&type=01"   # type=01 は CSV 形式
UA = "invoice-watch/0.2 (+https://github.com/japan-ai-tools/invoice-watch; daily diff download)"
_ERA = {"令和": 2018}
_ROW = re.compile(r"<th[^>]*>\s*(令和)\s*(\d+)年\s*(\d+)月\s*(\d+)日\s*</th>\s*<td>\s*<a[^>]*doDownload\('(\d+)'\s*,\s*'01'\)", re.S)


def list_diffs(html):
    """差分のページから [(作成日 'YYYY-MM-DD', ファイルの管理番号)] を新しい順に。CSV 形式だけ"""
    out, seen = [], set()
    for era, y, m, d, fid in _ROW.findall(html):
        day = f"{_ERA[era] + int(y):04d}-{int(m):02d}-{int(d):02d}"
        if fid not in seen:
            seen.add(fid)
            out.append((day, fid))
    out.sort(reverse=True)
    return out


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _check_zip(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if not any(n.lower().endswith(".csv") for n in z.namelist()):
                raise ValueError("ZIP の中に CSV がありません")
    except zipfile.BadZipFile as e:
        raise ValueError(f"ZIP として読めません: {e}") from e


def fetch(dest, days=3, get=_get, pause=3.0):
    """新しい差分を最大 days 個保存する。戻り値: 新しく保存したファイルの一覧"""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    items = list_diffs(get(LIST_URL).decode("utf-8", "replace"))
    if not items:
        raise ValueError("差分のページからファイルを1つも見つけられませんでした(ページの形が変わった可能性があります)")
    saved = []
    for day, fid in items[:days]:
        path = dest / f"diff_{day.replace('-', '')}.zip"
        if path.exists():
            continue
        if saved and pause:
            time.sleep(pause)
        data = get(FILE_URL.format(id=fid))
        _check_zip(data)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        saved.append(path)
    return saved


def main(argv=None):
    ap = argparse.ArgumentParser(prog="invoicewatch.nta_download", description="国税庁の差分データ(CSV の ZIP)を取る")
    ap.add_argument("dest")
    ap.add_argument("--days", type=int, default=3)
    a = ap.parse_args(argv)
    try:
        saved = fetch(a.dest, days=max(1, min(a.days, 40)))
    except (OSError, ValueError) as e:
        print(f"nta_download: 取れませんでした: {e}", file=sys.stderr)
        return 2
    print(f"nta_download: 新しく保存 {len(saved)}件" + "".join(f"\n  {p.name}" for p in saved))
    return 0


if __name__ == "__main__":
    sys.exit(main())
