"""照合の本体。

入力1: 取引先の一覧(名前・登録番号・取引日は任意)
入力2: 国税庁の公表データ(公表サイトのダウンロードの CSV・その ZIP、Web-API の JSON、見出し行つきの CSV)。
       全件データ(毎月)の上に差分データ(日次)を重ねて読める(merge_records)
出力: 取引先ごとの状態(登録中・取消・失効・登録前・見つからない・削除・形の誤り)と名称の食い違い。
     前回の結果を渡すと、変わった取引先だけを返す。

通信はしない。データを取るのは呼び出す側(所有者のアプリケーションIDで Web-API、または人がダウンロード)。
項目名はリソース定義書 1.5版(https://www.invoice-kohyo.nta.go.jp/files/k-resource-dl.pdf)の別紙1による。
"""
import csv
import io
import json
import re
import unicodedata
import zipfile
from datetime import date

# Web-API機能利用規約 第6条の文言(そのまま。変えない)
ATTRIBUTION_API = ("このサービスは、適格請求書発行事業者公表システムWeb-API機能を利用して取得した情報をもとに作成しているが、"
                   "サービスの内容は国税庁によって保証されたものではない")
# サイト利用規約の出典の書き方(ダウンロードデータを使うとき)。加工した旨も書く
ATTRIBUTION_DOWNLOAD = ("出典：国税庁適格請求書発行事業者公表サイト（国税庁）（https://www.invoice-kohyo.nta.go.jp/download/index.html）"
                        "をもとに、取引先の一覧と照らすため加工して作成")

STATUS_JA = {
    "registered": "登録中",
    "revoked": "取消",
    "expired": "失効",
    "not_yet": "登録日より前",
    "not_found": "公表データに見つからない",
    "deleted": "公表データから削除",
    "bad_number": "登録番号の形の誤り",
    "no_date": "日付が無く判定できない",
}
ALERT = {"revoked", "expired", "not_found", "deleted", "bad_number", "not_yet", "no_date"}

_NUM_KEYS = ("registratedNumber", "registrationNumber", "registration_number", "number", "登録番号")
_KEYMAP = {
    "registrationDate": ("registrationDate", "登録年月日", "registration_date"),
    "updateDate": ("updateDate", "更新年月日", "update_date"),
    "disposalDate": ("disposalDate", "取消年月日", "disposal_date"),
    "expireDate": ("expireDate", "失効年月日", "expire_date"),
    "process": ("process", "事業者処理区分"),
    "latest": ("latest", "最新履歴"),
    "kind": ("kind", "人格区分"),
    "name": ("name", "氏名又は名称", "名称"),
}


# 公表サイトのダウンロードの CSV(全件・差分)は見出しの行が無く、1行24列。並びは Web-API の項目の順(リソース定義書)。
# 2026-11-16 に差分データ(diff_20261113.csv・463行)の実物で確かめた: 2列目が T+13桁、3列目の処理区分は 01/02/03/99、
# 失効(03)の行は11列目(失効年月日)が必ず入る、8・9列目は全行が日付、19列目の名称は個人事業者(5列目=1)では空。
DOWNLOAD_COLUMNS = (
    "sequenceNumber", "registratedNumber", "process", "correct", "kind", "country", "latest",
    "registrationDate", "updateDate", "disposalDate", "expireDate",
    "address", "addressPrefectureCode", "addressCityCode",
    "addressRequest", "addressRequestPrefectureCode", "addressRequestCityCode",
    "kana", "name", "addressInside", "addressInsidePrefectureCode", "addressInsideCityCode",
    "tradeName", "popularName_previousName",
)
_DL_ROW = re.compile(r"^\s*\d+\s*,\s*\"?T\d{13}")


def _download_rows(text):
    """見出しの無いダウンロード CSV を、項目名つきの行に。列の数が違う行があれば形が違うので止める"""
    rows = []
    for i, cols in enumerate(csv.reader(io.StringIO(text)), 1):
        if not cols or not any(c.strip() for c in cols):
            continue
        if len(cols) != len(DOWNLOAD_COLUMNS):
            raise ValueError(f"ダウンロードの CSV の {i}行目が {len(cols)}列です(24列のはず)。国税庁のファイルの形が変わった可能性があります")
        rows.append(dict(zip(DOWNLOAD_COLUMNS, cols)))
    return rows


def read_download_zip(data):
    """公表サイトの ZIP(全件・差分)の中の CSV を全部読んで1つの文字にする。署名のファイル(.asc)は読まない"""
    texts = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for n in sorted(z.namelist()):
            if n.lower().endswith(".csv"):
                texts.append(z.read(n).decode("utf-8-sig"))
    if not texts:
        raise ValueError("ZIP の中に CSV がありません(CSV 形式のファイルを選んでください)")
    return "\n".join(t.rstrip("\n") for t in texts) + "\n"


def corporate_check_digit(base12):
    """法人番号の検査用数字(下12桁から)。JP Invoice Check と同じ計算。"""
    digits = [int(c) for c in base12][::-1]
    s = sum(d * (1 if i % 2 == 0 else 2) for i, d in enumerate(digits))
    return 9 - s % 9


def normalize_regno(value):
    """'T' + 13桁に整える。返り値 (整えた番号 or None, 注意の一覧)。"""
    notes = []
    if value is None or str(value).strip() == "":
        return None, ["登録番号がありません"]
    n = unicodedata.normalize("NFKC", str(value))
    n = re.sub(r"[\s\-‐−ー―]", "", n)
    if n[:1] == "t":
        n = "T" + n[1:]
    if re.fullmatch(r"[0-9]{13}", n):
        n = "T" + n
        notes.append("先頭の T を補いました")
    if not re.fullmatch(r"T[0-9]{13}", n):
        return None, [f"登録番号は「T+13桁の数字」です(入力: {value})"]
    if n != str(value) and not notes:
        notes.append(f"{n} に整えました")
    if int(n[1]) != corporate_check_digit(n[2:]):
        notes.append("法人番号の検査用数字と合いません(法人なら番号の誤り。個人事業者の番号はこの検査の対象外)")
    return n, notes


def _norm_name(s):
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"[\s・.,、。]", "", s)
    for a, b in (("(株)", "株式会社"), ("(有)", "有限会社"), ("(同)", "合同会社"), ("(合)", "合同会社"),
                 ("㈱", "株式会社"), ("㈲", "有限会社")):
        s = s.replace(a, b)
    return s


def _get(rec, keys):
    for k in keys:
        if k in rec and rec[k] not in (None, ""):
            return rec[k]
    return ""


# 和暦の元年(西暦では「元年-1」を足す)。R8 = 2018+8 = 2026
_ERA = {"令和": 2018, "R": 2018, "平成": 1988, "H": 1988, "昭和": 1925, "S": 1925}


def _to_date(s):
    """「2026-11-01」「2026/11/1」「20261101」「2026年11月1日」「令和8年11月1日」「R8.11.1」を日付に。読めなければ None"""
    s = unicodedata.normalize("NFKC", str(s or "")).strip().upper().replace("元年", "1年")
    if not s:
        return None
    y = None
    m = re.fullmatch(r"([0-9]{4})(?:[-/.]|年)?([0-9]{1,2})(?:[-/.]|月)?([0-9]{1,2})日?", s, re.ASCII)
    if m:
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    else:
        m = re.fullmatch(r"(令和|平成|昭和|R|H|S)\s*([0-9]{1,2})(?:[-/.]|年)([0-9]{1,2})(?:[-/.]|月)([0-9]{1,2})日?", s, re.ASCII)
        if m:
            y, mo, d = _ERA[m[1]] + int(m[2]), int(m[3]), int(m[4])
    if y is None:
        return None
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def decode_text(data):
    """ファイルの中身(bytes)を文字に。UTF-8(BOMつきも)で読めなければ、ExcelのCSVの Shift_JIS(cp932)で読む"""
    if isinstance(data, str):
        return data
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp932")


def _record(raw):
    num, _ = normalize_regno(_get(raw, _NUM_KEYS))
    if not num:
        return None
    r = {"number": num}
    for k, keys in _KEYMAP.items():
        r[k] = str(_get(raw, keys)).strip()
    return r


def load_public_records(data):
    """公表データを読む。ダウンロードの CSV(見出しなし・24列)とその ZIP、dict(Web-API の {"announcement": [...]})、
    list、JSON の文字列、見出し行つき CSV の文字列。

    返り値: {登録番号: [記録, ...]}(同じ番号の履歴を全部)。1件も読めなければ ValueError(黙って0件で「問題なし」にしない)
    """
    rows = None
    if isinstance(data, (bytes, bytearray)):
        data = read_download_zip(bytes(data)) if bytes(data[:2]) == b"PK" else decode_text(bytes(data))
    if isinstance(data, str):
        t = data.lstrip("﻿").strip()
        if t[:1] in "[{":
            data = json.loads(t)
        elif _DL_ROW.match(t):
            rows = _download_rows(t)
        else:
            reader = csv.DictReader(io.StringIO(t))
            heads = set(reader.fieldnames or [])
            if not heads & set(_NUM_KEYS):
                raise ValueError("公表データの CSV の形が分かりません(1行目に「登録番号」の見出しも、ダウンロードの CSV の形もありません)")
            rows = list(reader)
    if rows is None:
        if isinstance(data, dict):
            rows = data.get("announcement") or data.get("announcements") or data.get("records") or []
        elif isinstance(data, list):
            rows = data
        else:
            raise ValueError("公表データの形が分かりません")
    out = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        r = _record(raw)
        if r:
            out.setdefault(r["number"], []).append(r)
    if not out:
        raise ValueError("公表データから登録番号を1件も読めませんでした。ファイルの中身と形を確かめてください")
    return out


def merge_records(*parts):
    """全件データの上に差分データを重ねる(古い順に渡す)。同じ番号の記録は履歴として全部残し、
    判定では最新(最新履歴=1・更新年月日の新しいもの)を使う"""
    out = {}
    for part in parts:
        for num, recs in (part or {}).items():
            out.setdefault(num, []).extend(recs)
    return out


def count_records(records):
    """読めた登録番号の数と記録の数(画面と記録に出す)"""
    return {"numbers": len(records), "records": sum(len(v) for v in records.values())}


def _pick(records):
    """最新の記録を1つ選ぶ(latest=1 を優先、次に更新年月日の新しいもの)。"""
    def key(r):
        return (r.get("latest") == "1", _to_date(r.get("updateDate")) or date.min)
    return max(records, key=key)


def status_on(rec, on):
    """1件の記録の、ある日(on)の状態。

    日付が無くて決められないときは「登録中」にせず no_date(要確認)にする:
    登録日が空・処理区分が取消(04)なのに取消日が空・失効(03)なのに失効日が空。
    """
    if rec.get("process") == "99":
        return "deleted"
    reg = _to_date(rec.get("registrationDate"))
    dis = _to_date(rec.get("disposalDate"))
    exp = _to_date(rec.get("expireDate"))
    if (rec.get("process") == "04" and not dis) or (rec.get("process") == "03" and not exp):
        return "no_date"
    if dis and dis <= on:
        return "revoked"
    if exp and exp <= on:
        return "expired"
    if not reg:
        return "no_date"
    if reg > on:
        return "not_yet"
    return "registered"


def _choose(records, day, by_date):
    """判定に使う記録を選ぶ。取引日があり履歴が複数なら、その日に登録中だった期間の記録を優先する(再登録した事業者)。"""
    if by_date and len(records) > 1:
        hits = [r for r in records if status_on(r, day) == "registered"]
        if hits:
            return _pick(hits)
        # どの期間にも入らない日は、その日より前に始まった一番新しい期間(取消・失効した前の登録)で判定する
        before = [r for r in records if _to_date(r.get("registrationDate")) and _to_date(r.get("registrationDate")) <= day]
        if before:
            return max(before, key=lambda r: _to_date(r.get("registrationDate")))
    return _pick(records)


def load_partners_csv(text):
    """取引先の一覧(CSV)。見出しは「名前/取引先名/name」「登録番号/registration_number」「取引日/date」(取引日は任意)。"""
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    name_k = ("名前", "取引先名", "取引先", "name")
    num_k = ("登録番号", "registration_number", "number", "T番号")
    day_k = ("取引日", "date")
    out = []
    for row in reader:
        extra = row.pop(None, None)  # 見出しより列が多い行(名前に引用符なしのカンマ など)
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items() if isinstance(v, (str, type(None)))}
        nm, no, dy = _get(row, name_k), _get(row, num_k), _get(row, day_k)
        if not (nm or no):
            continue
        p = {"name": nm, "registration_number": no, "date": dy}
        if extra:
            p["notes"] = [f"{reader.line_num}行目は見出しより列が多いので、余った列は使っていません(名前にカンマがあるなら \"\" で囲んでください)"]
        out.append(p)
    return out


def check_partners(partners, records, on=None, limit=None):
    """取引先ごとの状態を返す。on: 判定する日(既定は今日)。limit: 確かめる件数の上限(無料の版で使う)。"""
    on = on or date.today()
    if isinstance(on, str):
        on = _to_date(on) or date.today()
    results, skipped = [], 0
    for i, p in enumerate(partners):
        if limit is not None and i >= limit:
            skipped += 1
            continue
        num, notes = normalize_regno(p.get("registration_number"))
        item = {"name": p.get("name", ""), "input": p.get("registration_number", ""), "number": num,
                "date": p.get("date", "") or "", "notes": list(p.get("notes") or []) + list(notes), "status": None, "public_name": "", "name_match": None,
                "registration_date": "", "disposal_date": "", "expire_date": ""}
        if not num:
            item["status"] = "bad_number"
        elif num not in records:
            item["status"] = "not_found"
        else:
            pd = _to_date(p.get("date"))
            day = pd or on
            rec = _choose(records[num], day, bool(pd))
            item["status"] = status_on(rec, day)
            if item["status"] == "not_yet" and len(records[num]) == 1:
                item["notes"].append("このデータには今の登録期間しかありません。前に登録していた期間(再登録)の取引かどうかは、履歴つきのデータで確かめてください")
            elif item["status"] == "no_date":
                item["notes"].append("公表データの記録に登録日(取消・失効なら その日付)が無く、判定できません。公表サイトで確かめてください")
            if pd:
                item["notes"].append(f"取引日 {day.isoformat()} の時点で判定")
            elif str(p.get("date") or "").strip():
                item["date_unreadable"] = True
                item["notes"].append(f"取引日「{p.get('date')}」が読めません。{on.isoformat()} の時点で仮に判定したので、取引日を直して確かめてください")
            item["public_name"] = rec.get("name", "")
            item["registration_date"] = rec.get("registrationDate", "")
            item["disposal_date"] = rec.get("disposalDate", "")
            item["expire_date"] = rec.get("expireDate", "")
            if item["public_name"] and item["name"]:
                item["name_match"] = _norm_name(item["public_name"]) == _norm_name(item["name"])
                if not item["name_match"]:
                    item["notes"].append(f"公表の名称は「{item['public_name']}」です。取引先の名前と違います(番号の取り違えか名称の変更)")
            elif not item["public_name"]:
                item["notes"].append("公表データに名称がありません(個人事業者はダウンロードデータで氏名が空)。名称は目で確かめてください")
        item["status_ja"] = STATUS_JA[item["status"]]
        item["alert"] = item["status"] in ALERT or item["name_match"] is False or bool(item.get("date_unreadable"))
        results.append(item)
    return {"on": on.isoformat(), "results": results, "skipped": skipped,
            "summary": {s: sum(1 for r in results if r["status"] == s) for s in STATUS_JA},
            "alerts": sum(1 for r in results if r["alert"])}


def diff_results(prev, cur):
    """前回と今回の結果を比べ、変わった取引先だけを返す(毎日の見張り)。"""
    def rows_of(res):
        return res.get("results", res) if isinstance(res, dict) else res

    # 同じ名前・番号で取引日だけ違う行を別々に比べる。取引日を持たない古い版の結果と比べるときは、取引日を見ない
    old_rows = rows_of(prev or {"results": []})
    use_date = all("date" in r for r in old_rows)

    def index(rows):
        return {(r.get("number") or r.get("input"), r.get("name")) + ((r.get("date") or "",) if use_date else ()): r
                for r in rows}
    a, b = index(old_rows), index(rows_of(cur))
    changes = []
    for k, r in b.items():
        o = a.get(k)
        if o is None:
            changes.append({"kind": "new", "name": r["name"], "number": r["number"], "now": r["status_ja"]})
            continue
        if o.get("status") != r.get("status"):
            changes.append({"kind": "status", "name": r["name"], "number": r["number"],
                            "before": STATUS_JA.get(o.get("status"), o.get("status")), "now": r["status_ja"]})
        # 今回の名称が空なのは「変わった」ではなく「載っていない」(個人事業者の氏名はダウンロードデータから削除される。
        # 公表サイト よくある質問 3-3・3-5)。Web-API の結果からダウンロードに切り替えた日に、名称の変更と誤って知らせない
        if o.get("public_name") and r.get("public_name") and o.get("public_name") != r.get("public_name"):
            changes.append({"kind": "name", "name": r["name"], "number": r["number"],
                            "before": o.get("public_name"), "now": r.get("public_name")})
    for k, o in a.items():
        if k not in b:
            changes.append({"kind": "removed", "name": o.get("name"), "number": o.get("number"),
                            "before": STATUS_JA.get(o.get("status"), o.get("status"))})
    return changes
