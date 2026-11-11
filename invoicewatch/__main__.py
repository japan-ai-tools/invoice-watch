"""python -m invoicewatch 取引先.csv 公表データ.json [--prev 前回.json] [--date 2026-11-11] [--out 今回.json]"""
import argparse
import json
import sys
from pathlib import Path

from .watch import ATTRIBUTION_API, check_partners, diff_results, load_partners_csv, load_public_records


def main(argv=None):
    ap = argparse.ArgumentParser(prog="invoicewatch", description="取引先の登録番号を国税庁の公表データと照らす(通信しない)")
    ap.add_argument("partners")
    ap.add_argument("records")
    ap.add_argument("--prev")
    ap.add_argument("--date")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    partners = load_partners_csv(Path(a.partners).read_text(encoding="utf-8-sig"))
    records = load_public_records(Path(a.records).read_text(encoding="utf-8-sig"))
    res = check_partners(partners, records, on=a.date)
    if a.prev:
        res["changes"] = diff_results(json.loads(Path(a.prev).read_text(encoding="utf-8")), res)
    res["attribution"] = ATTRIBUTION_API
    text = json.dumps(res, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    print(text)
    return 1 if res["alerts"] else 0


if __name__ == "__main__":
    sys.exit(main())
