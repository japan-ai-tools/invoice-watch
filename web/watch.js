/* 取引先インボイス見張り — 照合の本体(ブラウザ版)。invoicewatch/watch.py と同じ決まり。
 * 通信しない。取引先の一覧と国税庁の公表データ(人が入れたもの)を照らすだけ。
 * 項目名はリソース定義書 1.5版(https://www.invoice-kohyo.nta.go.jp/files/k-resource-dl.pdf)の別紙1による。
 * ブラウザでは window.InvoiceWatch、node では module.exports。
 */
(function (root) {
  "use strict";

  // Web-API機能利用規約 第6条の文言(そのまま。変えない)
  var ATTRIBUTION_API = "このサービスは、適格請求書発行事業者公表システムWeb-API機能を利用して取得した情報をもとに作成しているが、" +
    "サービスの内容は国税庁によって保証されたものではない";
  var ATTRIBUTION_DOWNLOAD = "出典：国税庁適格請求書発行事業者公表サイト(国税庁)(https://www.invoice-kohyo.nta.go.jp/download/index.html)" +
    "をもとに、取引先の一覧と照らすため加工して作成";

  var FREE_LIMIT = 10; // 無料の版で確かめる取引先の数(SALES_PAGE.md)

  var STATUS_JA = {
    registered: "登録中",
    revoked: "取消",
    expired: "失効",
    not_yet: "登録日より前",
    not_found: "公表データに見つからない",
    deleted: "公表データから削除",
    bad_number: "登録番号の形の誤り"
  };
  var ALERT = { revoked: 1, expired: 1, not_found: 1, deleted: 1, bad_number: 1, not_yet: 1 };

  var NUM_KEYS = ["registratedNumber", "registrationNumber", "registration_number", "number", "登録番号"];
  var KEYMAP = {
    registrationDate: ["registrationDate", "登録年月日", "registration_date"],
    updateDate: ["updateDate", "更新年月日", "update_date"],
    disposalDate: ["disposalDate", "取消年月日", "disposal_date"],
    expireDate: ["expireDate", "失効年月日", "expire_date"],
    process: ["process", "事業者処理区分"],
    latest: ["latest", "最新履歴"],
    kind: ["kind", "人格区分"],
    name: ["name", "氏名又は名称", "名称"]
  };

  function nfkc(s) { return String(s == null ? "" : s).normalize("NFKC"); }

  function corporateCheckDigit(base12) {
    var d = base12.split("").map(Number).reverse();
    var s = 0;
    for (var i = 0; i < d.length; i++) s += d[i] * (i % 2 === 0 ? 1 : 2);
    return 9 - (s % 9);
  }

  function normalizeRegno(value) {
    var notes = [];
    if (value == null || String(value).trim() === "") return [null, ["登録番号がありません"]];
    var n = nfkc(value).replace(/[\s\-‐−ー―]/g, "");
    if (n.charAt(0) === "t") n = "T" + n.slice(1);
    if (/^\d{13}$/.test(n)) { n = "T" + n; notes.push("先頭の T を補いました"); }
    if (!/^T\d{13}$/.test(n)) return [null, ["登録番号は「T+13桁の数字」です(入力: " + value + ")"]];
    if (n !== String(value) && notes.length === 0) notes.push(n + " に整えました");
    if (Number(n.charAt(1)) !== corporateCheckDigit(n.slice(2))) {
      notes.push("法人番号の検査用数字と合いません(法人なら番号の誤り。個人事業者の番号はこの検査の対象外)");
    }
    return [n, notes];
  }

  function normName(s) {
    s = nfkc(s).replace(/[\s・.,、。]/g, "");
    var pairs = [["(株)", "株式会社"], ["(有)", "有限会社"], ["(同)", "合同会社"], ["(合)", "合同会社"],
      ["㈱", "株式会社"], ["㈲", "有限会社"]];
    for (var i = 0; i < pairs.length; i++) s = s.split(pairs[i][0]).join(pairs[i][1]);
    return s;
  }

  function get(rec, keys) {
    for (var i = 0; i < keys.length; i++) {
      var v = rec[keys[i]];
      if (v !== undefined && v !== null && v !== "") return v;
    }
    return "";
  }

  // "2026-11-01" などを "20261101" の数の文字にそろえる(比べるため)。正しくない日付は null
  function toDate(s) {
    s = String(s == null ? "" : s).trim();
    var m = /^(\d{4})[-\/]?(\d{1,2})[-\/]?(\d{1,2})$/.exec(s);
    if (!m) return null;
    var y = +m[1], mo = +m[2], d = +m[3];
    var t = new Date(Date.UTC(y, mo - 1, d));
    if (t.getUTCFullYear() !== y || t.getUTCMonth() !== mo - 1 || t.getUTCDate() !== d) return null;
    return y + "-" + (mo < 10 ? "0" : "") + mo + "-" + (d < 10 ? "0" : "") + d;
  }

  function today() {
    var t = new Date();
    return toDate(t.getFullYear() + "-" + (t.getMonth() + 1) + "-" + t.getDate());
  }

  // CSV(RFC 4180 の引用符つきも)を行の配列に
  function parseCsv(text) {
    text = String(text).replace(/^﻿/, "");
    var rows = [], row = [], f = "", q = false;
    for (var i = 0; i < text.length; i++) {
      var c = text.charAt(i);
      if (q) {
        if (c === '"') { if (text.charAt(i + 1) === '"') { f += '"'; i++; } else q = false; }
        else f += c;
      } else if (c === '"') q = true;
      else if (c === ",") { row.push(f); f = ""; }
      else if (c === "\n" || c === "\r") {
        if (c === "\r" && text.charAt(i + 1) === "\n") i++;
        row.push(f); rows.push(row); row = []; f = "";
      } else f += c;
    }
    if (f !== "" || row.length) { row.push(f); rows.push(row); }
    return rows.filter(function (r) { return !(r.length === 1 && r[0].trim() === ""); });
  }

  function csvDicts(text) {
    var rows = parseCsv(text);
    if (!rows.length) return { heads: [], items: [] };
    var heads = rows[0].map(function (h) { return h.trim(); });
    var items = rows.slice(1).map(function (r) {
      var o = {};
      heads.forEach(function (h, i) { o[h] = (r[i] || "").trim(); });
      return o;
    });
    return { heads: heads, items: items };
  }

  function record(raw) {
    var num = normalizeRegno(get(raw, NUM_KEYS))[0];
    if (!num) return null;
    var r = { number: num };
    Object.keys(KEYMAP).forEach(function (k) { r[k] = String(get(raw, KEYMAP[k])).trim(); });
    return r;
  }

  function loadPublicRecords(data) {
    var rows = null;
    if (typeof data === "string") {
      var t = data.replace(/^﻿/, "").trim();
      if (t.charAt(0) === "[" || t.charAt(0) === "{") data = JSON.parse(t);
      else {
        var c = csvDicts(t);
        var ok = c.heads.some(function (h) { return NUM_KEYS.indexOf(h) >= 0; });
        if (!ok) throw new Error("CSV の1行目に見出し(登録番号 など)がありません。見出しの無いダウンロードCSVは未対応です。JSON 形式を使ってください");
        rows = c.items;
      }
    }
    if (rows === null) {
      if (Array.isArray(data)) rows = data;
      else if (data && typeof data === "object") rows = data.announcement || data.announcements || data.records || [];
      else throw new Error("公表データの形が分かりません");
    }
    var out = {};
    rows.forEach(function (raw) {
      if (!raw || typeof raw !== "object") return;
      var r = record(raw);
      if (r) (out[r.number] = out[r.number] || []).push(r);
    });
    return out;
  }

  function pick(records) {
    var best = null;
    records.forEach(function (r) {
      var k = [r.latest === "1" ? 1 : 0, toDate(r.updateDate) || "0000-00-00"];
      if (!best || k[0] > best.k[0] || (k[0] === best.k[0] && k[1] > best.k[1])) best = { r: r, k: k };
    });
    return best.r;
  }

  function statusOn(rec, on) {
    if (rec.process === "99") return "deleted";
    var reg = toDate(rec.registrationDate), dis = toDate(rec.disposalDate), exp = toDate(rec.expireDate);
    if (dis && dis <= on) return "revoked";
    if (exp && exp <= on) return "expired";
    if (reg && reg > on) return "not_yet";
    return "registered";
  }

  function loadPartnersCsv(text) {
    var c = csvDicts(text);
    var nameK = ["名前", "取引先名", "取引先", "name"], numK = ["登録番号", "registration_number", "number", "T番号"], dayK = ["取引日", "date"];
    var out = [];
    c.items.forEach(function (row) {
      var nm = get(row, nameK), no = get(row, numK), dy = get(row, dayK);
      if (!(nm || no)) return;
      out.push({ name: nm, registration_number: no, date: dy });
    });
    return out;
  }

  function checkPartners(partners, records, on, limit) {
    on = toDate(on) || today();
    var results = [], skipped = 0;
    partners.forEach(function (p, i) {
      if (limit != null && i >= limit) { skipped++; return; }
      var nr = normalizeRegno(p.registration_number), num = nr[0];
      var item = { name: p.name || "", input: p.registration_number || "", number: num, notes: nr[1].slice(),
        status: null, public_name: "", name_match: null, registration_date: "", disposal_date: "", expire_date: "" };
      if (!num) item.status = "bad_number";
      else if (!records[num]) item.status = "not_found";
      else {
        var rec = pick(records[num]);
        var pd = toDate(p.date), day = pd || on;
        item.status = statusOn(rec, day);
        if (p.date && pd) item.notes.push("取引日 " + day + " の時点で判定");
        item.public_name = rec.name || "";
        item.registration_date = rec.registrationDate || "";
        item.disposal_date = rec.disposalDate || "";
        item.expire_date = rec.expireDate || "";
        if (item.public_name && item.name) {
          item.name_match = normName(item.public_name) === normName(item.name);
          if (!item.name_match) item.notes.push("公表の名称は「" + item.public_name + "」です。取引先の名前と違います(番号の取り違えか名称の変更)");
        } else if (!item.public_name) {
          item.notes.push("公表データに名称がありません(個人事業者はダウンロードデータで氏名が空)。名称は目で確かめてください");
        }
      }
      item.status_ja = STATUS_JA[item.status];
      item.alert = !!ALERT[item.status] || item.name_match === false;
      results.push(item);
    });
    var summary = {};
    Object.keys(STATUS_JA).forEach(function (s) {
      summary[s] = results.filter(function (r) { return r.status === s; }).length;
    });
    return { on: on, results: results, skipped: skipped, summary: summary,
      alerts: results.filter(function (r) { return r.alert; }).length };
  }

  function diffResults(prev, cur) {
    function index(res) {
      var rows = (res && res.results) || res || [];
      var m = {};
      rows.forEach(function (r) { m[(r.number || r.input) + "\u0000" + r.name] = r; });
      return m;
    }
    var a = index(prev || { results: [] }), b = index(cur), changes = [];
    Object.keys(b).forEach(function (k) {
      var r = b[k], o = a[k];
      if (!o) { changes.push({ kind: "new", name: r.name, number: r.number, now: r.status_ja }); return; }
      if (o.status !== r.status) changes.push({ kind: "status", name: r.name, number: r.number, before: STATUS_JA[o.status] || o.status, now: r.status_ja });
      if ((o.public_name || "") !== (r.public_name || "") && o.public_name) changes.push({ kind: "name", name: r.name, number: r.number, before: o.public_name, now: r.public_name });
    });
    Object.keys(a).forEach(function (k) {
      if (!b[k]) { var o = a[k]; changes.push({ kind: "removed", name: o.name, number: o.number, before: STATUS_JA[o.status] || o.status }); }
    });
    return changes;
  }

  // 結果を CSV に(Excel で開けるよう BOM は呼び出し側でつける)
  function resultsToCsv(res) {
    function cell(v) { v = v == null ? "" : String(v); return /[",\r\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }
    var head = ["名前", "登録番号", "状態", "公表の名称", "名称の一致", "登録年月日", "取消年月日", "失効年月日", "要確認", "メモ"];
    var lines = [head.join(",")];
    res.results.forEach(function (r) {
      lines.push([r.name, r.number || r.input, r.status_ja, r.public_name,
        r.name_match === null ? "" : (r.name_match ? "一致" : "違う"),
        r.registration_date, r.disposal_date, r.expire_date, r.alert ? "要確認" : "", r.notes.join(" / ")].map(cell).join(","));
    });
    return lines.join("\r\n") + "\r\n";
  }

  var api = { ATTRIBUTION_API: ATTRIBUTION_API, ATTRIBUTION_DOWNLOAD: ATTRIBUTION_DOWNLOAD, FREE_LIMIT: FREE_LIMIT,
    STATUS_JA: STATUS_JA, normalizeRegno: normalizeRegno, loadPublicRecords: loadPublicRecords,
    loadPartnersCsv: loadPartnersCsv, checkPartners: checkPartners, diffResults: diffResults,
    resultsToCsv: resultsToCsv, parseCsv: parseCsv };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.InvoiceWatch = api;
})(typeof window !== "undefined" ? window : this);
