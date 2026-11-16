"""python -m invoicewatch 取引先.csv 公表データ [公表データ ...] [--source download|api] [--prev 前回.json] [--date 2026-11-11] [--out 今回.json]

公表データは古い順にいくつでも渡せる(例: 全件の ZIP → 差分の ZIP を日付順)。後のものが前のものに重なる。

終了コード: 0 = 要確認なし / 1 = 要確認あり(知らせる) / 2 = 動かせなかった(ファイルが無い・読めない・形が違う)。
定期実行では 2 を「見張りが止まった」として別に扱える。
"""
import argparse
import json
import sys
import zipfile
from pathlib import Path

from .watch import (ATTRIBUTION_API, ATTRIBUTION_DOWNLOAD, check_partners, count_records, decode_text, diff_results,
                    load_partners_csv, load_public_records, merge_records)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="invoicewatch", description="取引先の登録番号を国税庁の公表データと照らす(通信しない)")
    ap.add_argument("partners")
    ap.add_argument("records", nargs="+", help="公表データ(ダウンロードの ZIP・CSV、Web-API の JSON)。古い順")
    ap.add_argument("--source", choices=("download", "api"), default="download",
                    help="公表データの出どころ(取得元の表示が変わる)。既定は download(公表サイトのダウンロード)")
    ap.add_argument("--prev")
    ap.add_argument("--date")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        partners = load_partners_csv(decode_text(Path(a.partners).read_bytes()))
        records = merge_records(*(load_public_records(Path(f).read_bytes()) for f in a.records))
        n = count_records(records)
        print(f"invoicewatch: 公表データを読みました(登録番号 {n['numbers']}件・記録 {n['records']}件・ファイル {len(a.records)}つ)", file=sys.stderr)
        res = check_partners(partners, records, on=a.date)
        if a.prev:
            res["changes"] = diff_results(json.loads(Path(a.prev).read_text(encoding="utf-8")), res)
    except (OSError, ValueError, UnicodeDecodeError, zipfile.BadZipFile) as e:  # json.JSONDecodeError は ValueError の仲間
        print(f"invoicewatch: 動かせませんでした: {e}", file=sys.stderr)
        return 2
    res["attribution"] = ATTRIBUTION_API if a.source == "api" else ATTRIBUTION_DOWNLOAD
    text = json.dumps(res, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    print(text)
    return 1 if res["alerts"] else 0


if __name__ == "__main__":
    sys.exit(main())
