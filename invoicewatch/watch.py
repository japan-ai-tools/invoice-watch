"""照合の本体。

入力1: 取引先の一覧(名前・登録番号・取引日は任意)
入力2: 国税庁の公表データ(Web-API の JSON、ダウンロードの JSON、見出し行つきの CSV)
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
from datetime import date

# Web-API機能利用規約 第6条の文言(そのまま。変えない)
ATTRIBUTION_API = ("このサービスは、適格請求書発行事業者公表システムWeb-API機能を利用して取得した情報をもとに作成しているが、"
                   "サービスの内容は国税庁によって保証されたものではない")
# サイト利用規約の出典の書き方(ダウンロードデータを使うとき)。加工した旨も書く
ATTRIBUTION_DOWNLOAD = ("出典：国税庁適格請求書発行事業者公表サイト(国税庁)(https://www.invoice-kohyo.nta.go.jp/download/index.html)"
                        "をもとに、取引先の一覧と照らすため加工して作成")

STATUS_JA = {
    "registered": "登録中",
    "revoked": "取消",
    "expired": "失効",
    "not_yet": "登録日より前",
    "not_found": "公表データに見つからない",
    "deleted": "公表データから削除",
    "bad_number": "登録番号の形の誤り",
}
ALERT = {"revoked", "expired", "not_found", "deleted", "bad_number", "not_yet"}

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
    if re.fullmatch(r"\d{13}", n):
        n = "T" + n
        notes.append("先頭の T を補いました")
    if not re.fullmatch(r"T\d{13}", n):
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


def _to_date(s):
    s = str(s or "").strip()
    if not s:
        return None
    m = re.fullmatch(r"(\d{4})[-/]?(\d{1,2})[-/]?(\d{1,2})", s)
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def _record(raw):
    num, _ = normalize_regno(_get(raw, _NUM_KEYS))
    if not num:
        return None
    r = {"number": num}
    for k, keys in _KEYMAP.items():
        r[k] = str(_get(raw, keys)).strip()
    return r


def load_public_records(data):
    """公表データを読む。dict(Web-API の {"announcement": [...]})、list、JSON の文字列、見出し行つき CSV の文字列。

    見出しの無い CSV(ダウンロードの CSV)は列の並びをまだ実物で確かめていないので受け付けない(ValueError)。
    返り値: {登録番号: [記録, ...]}(同じ番号の履歴を全部)
    """
    rows = None
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8-sig")
    if isinstance(data, str):
        t = data.lstrip("﻿").strip()
        if t[:1] in "[{":
            data = json.loads(t)
        else:
            reader = csv.DictReader(io.StringIO(t))
            heads = set(reader.fieldnames or [])
            if not heads & set(_NUM_KEYS):
                raise ValueError("CSV の1行目に見出し(登録番号 など)がありません。見出しの無いダウンロードCSVは未対応です。JSON 形式を使ってください")
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
    return out


def _pick(records):
    """最新の記録を1つ選ぶ(latest=1 を優先、次に更新年月日の新しいもの)。"""
    def key(r):
        return (r.get("latest") == "1", _to_date(r.get("updateDate")) or date.min)
    return max(records, key=key)


def status_on(rec, on):
    """1件の記録の、ある日(on)の状態。"""
    if rec.get("process") == "99":
        return "deleted"
    reg = _to_date(rec.get("registrationDate"))
    dis = _to_date(rec.get("disposalDate"))
    exp = _to_date(rec.get("expireDate"))
    if dis and dis <= on:
        return "revoked"
    if exp and exp <= on:
        return "expired"
    if reg and reg > on:
        return "not_yet"
    return "registered"


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
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        nm, no, dy = _get(row, name_k), _get(row, num_k), _get(row, day_k)
        if not (nm or no):
            continue
        out.append({"name": nm, "registration_number": no, "date": dy})
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
                "notes": list(notes), "status": None, "public_name": "", "name_match": None,
                "registration_date": "", "disposal_date": "", "expire_date": ""}
        if not num:
            item["status"] = "bad_number"
        elif num not in records:
            item["status"] = "not_found"
        else:
            rec = _pick(records[num])
            day = _to_date(p.get("date")) or on
            item["status"] = status_on(rec, day)
            if p.get("date") and _to_date(p.get("date")):
                item["notes"].append(f"取引日 {day.isoformat()} の時点で判定")
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
        item["alert"] = item["status"] in ALERT or item["name_match"] is False
        results.append(item)
    return {"on": on.isoformat(), "results": results, "skipped": skipped,
            "summary": {s: sum(1 for r in results if r["status"] == s) for s in STATUS_JA},
            "alerts": sum(1 for r in results if r["alert"])}


def diff_results(prev, cur):
    """前回と今回の結果を比べ、変わった取引先だけを返す(毎日の見張り)。"""
    def index(res):
        rows = res.get("results", res) if isinstance(res, dict) else res
        return {(r.get("number") or r.get("input"), r.get("name")): r for r in rows}
    a, b = index(prev or {"results": []}), index(cur)
    changes = []
    for k, r in b.items():
        o = a.get(k)
        if o is None:
            changes.append({"kind": "new", "name": r["name"], "number": r["number"], "now": r["status_ja"]})
            continue
        if o.get("status") != r.get("status"):
            changes.append({"kind": "status", "name": r["name"], "number": r["number"],
                            "before": STATUS_JA.get(o.get("status"), o.get("status")), "now": r["status_ja"]})
        if (o.get("public_name") or "") != (r.get("public_name") or "") and o.get("public_name"):
            changes.append({"kind": "name", "name": r["name"], "number": r["number"],
                            "before": o.get("public_name"), "now": r.get("public_name")})
    for k, o in a.items():
        if k not in b:
            changes.append({"kind": "removed", "name": o.get("name"), "number": o.get("number"),
                            "before": STATUS_JA.get(o.get("status"), o.get("status"))})
    return changes
