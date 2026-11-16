"""取引先インボイス見張り(invoice-watch): 取引先の登録番号を国税庁の公表データと照らし、変わった取引先だけを返す。標準ライブラリだけ・通信しない。"""
from .watch import (ATTRIBUTION_API, ATTRIBUTION_DOWNLOAD, DOWNLOAD_COLUMNS, check_partners, count_records, decode_text,
                    diff_results, load_partners_csv, load_public_records, merge_records, normalize_regno, read_download_zip,
                    status_on)

__version__ = "0.2.1"
__all__ = ["ATTRIBUTION_API", "ATTRIBUTION_DOWNLOAD", "DOWNLOAD_COLUMNS", "check_partners", "count_records", "decode_text",
           "diff_results", "load_partners_csv", "load_public_records", "merge_records", "normalize_regno",
           "read_download_zip", "status_on", "__version__"]
