/* 取引先インボイス見張り — 画面の動き。通信しない(fetch も外部の読み込みも使わない)。 */
(function () {
  "use strict";
  var IW = window.InvoiceWatch;
  var SAMPLE_PARTNERS = "名前,登録番号,取引日\n見本商事株式会社,T9234567890123,\n(株)見本工業,T9111111111111,\n見本運輸合同会社,Ｔ３９８７６５４３２１０９８,\n見本デザイン(個人),T9555555555555,\n番号まちがい株式会社,T123,\n載っていない株式会社,T1234567890123,\n";
  var SAMPLE_RECORDS = {"lastUpdateDate": "2026-11-10", "count": "5", "divideNumber": "1", "divideSize": "1", "announcement": [{"sequenceNumber": "1", "registratedNumber": "T9234567890123", "process": "01", "correct": "0", "kind": "2", "country": "1", "latest": "1", "registrationDate": "2023-10-01", "updateDate": "2023-10-01", "disposalDate": "", "expireDate": "", "name": "見本商事株式会社"}, {"sequenceNumber": "2", "registratedNumber": "T9111111111111", "process": "04", "correct": "0", "kind": "2", "country": "1", "latest": "1", "registrationDate": "2023-10-01", "updateDate": "2026-11-05", "disposalDate": "2026-11-01", "expireDate": "", "name": "株式会社見本工業"}, {"sequenceNumber": "3", "registratedNumber": "T3987654321098", "process": "02", "correct": "0", "kind": "2", "country": "1", "latest": "1", "registrationDate": "2024-04-01", "updateDate": "2026-10-20", "disposalDate": "", "expireDate": "", "name": "新見本ロジスティクス合同会社"}, {"sequenceNumber": "4", "registratedNumber": "T9555555555555", "process": "01", "correct": "0", "kind": "1", "country": "1", "latest": "1", "registrationDate": "2023-10-01", "updateDate": "2023-10-01", "disposalDate": "", "expireDate": "2026-06-30", "name": ""}]};
  var STORE_KEY = "invoice-watch:last";
  var $ = function (id) { return document.getElementById(id); };
  var last = null;

  $("freeLimit").textContent = IW.FREE_LIMIT;
  $("attribution").textContent = IW.ATTRIBUTION_DOWNLOAD + "。Web-API の結果を使うとき: " + IW.ATTRIBUTION_API + "。";
  var t = new Date();
  $("onDate").value = t.getFullYear() + "-" + String(t.getMonth() + 1).padStart(2, "0") + "-" + String(t.getDate()).padStart(2, "0");

  function stored() { try { var s = localStorage.getItem(STORE_KEY); return s ? JSON.parse(s) : null; } catch (e) { return null; } }
  function store(res) { try { localStorage.setItem(STORE_KEY, JSON.stringify(res)); } catch (e) { /* 保存できなくても動く */ } }
  if (stored()) $("usePrevBtn").disabled = false;

  function readFile(input, cb) {
    var f = input.files && input.files[0];
    if (!f) return;
    var rd = new FileReader();
    rd.onload = function () { cb(String(rd.result)); };
    rd.readAsText(f, "utf-8");
  }
  $("partnersFile").addEventListener("change", function () { readFile(this, function (s) { $("partnersText").value = s; }); });
  $("recordsFile").addEventListener("change", function () { readFile(this, function (s) { $("recordsText").value = s; }); });
  var prev = null;
  $("prevFile").addEventListener("change", function () {
    readFile(this, function (s) { try { prev = JSON.parse(s); $("msg").textContent = ""; } catch (e) { prev = null; $("msg").textContent = "前回の結果の JSON が読めません"; } });
  });
  $("usePrevBtn").addEventListener("click", function () { prev = stored(); $("msg").textContent = prev ? "" : "この端末に前回の結果がありません"; this.textContent = "この端末の前回を使います"; });
  $("sampleBtn").addEventListener("click", function () {
    $("partnersText").value = SAMPLE_PARTNERS;
    $("recordsText").value = JSON.stringify(SAMPLE_RECORDS, null, 1);
    $("onDate").value = "2026-11-11";
  });

  function el(tag, text, cls) { var e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; }

  function render(res, changes) {
    $("resultCard").hidden = false;
    $("resultOn").textContent = "(" + res.on + " の時点)";
    var sm = $("summary"); sm.textContent = "";
    sm.appendChild(el("span", "要確認 " + res.alerts + " 件", "pill" + (res.alerts ? " alert" : "")));
    Object.keys(IW.STATUS_JA).forEach(function (k) {
      if (res.summary[k]) sm.appendChild(el("span", IW.STATUS_JA[k] + " " + res.summary[k], "pill"));
    });
    var tb = $("rows"); tb.textContent = "";
    res.results.forEach(function (r) {
      var tr = el("tr", null, r.alert ? "alert" : "okrow");
      tr.appendChild(el("td", r.name));
      tr.appendChild(el("td", r.number || r.input));
      tr.appendChild(el("td", (r.alert ? "要確認・" : "") + r.status_ja, "st"));
      tr.appendChild(el("td", r.public_name));
      tr.appendChild(el("td", r.notes.join(" / ")));
      tb.appendChild(tr);
    });
    $("skipped").textContent = res.skipped ? ("無料の版は先頭の " + IW.FREE_LIMIT + " 件まで。残り " + res.skipped + " 件は確かめていません。") : "";
    var cb = $("changesBox"), ul = $("changes"); ul.textContent = "";
    if (changes) {
      cb.hidden = false;
      if (!changes.length) ul.appendChild(el("li", "変わった取引先はありません"));
      changes.forEach(function (c) {
        var s = c.name + "(" + (c.number || "番号なし") + "): ";
        if (c.kind === "new") s += "今回から加わった(" + c.now + ")";
        else if (c.kind === "removed") s += "一覧から外れた(前回 " + c.before + ")";
        else if (c.kind === "name") s += "公表の名称が「" + c.before + "」→「" + c.now + "」";
        else s += c.before + " → " + c.now;
        ul.appendChild(el("li", s));
      });
    } else cb.hidden = true;
  }

  $("runBtn").addEventListener("click", function () {
    $("msg").textContent = "";
    try {
      var partners = IW.loadPartnersCsv($("partnersText").value);
      if (!partners.length) throw new Error("取引先の一覧が空です(1行目は見出し: 名前,登録番号,取引日)");
      if (!$("recordsText").value.trim()) throw new Error("国税庁の公表データを入れてください");
      var records = IW.loadPublicRecords($("recordsText").value);
      var res = IW.checkPartners(partners, records, $("onDate").value, IW.FREE_LIMIT);
      var changes = prev ? IW.diffResults(prev, res) : null;
      last = res; store(res); $("usePrevBtn").disabled = false;
      render(res, changes);
    } catch (e) { $("msg").textContent = e.message || String(e); }
  });

  function download(name, text, type) {
    var b = new Blob([text], { type: type });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(b); a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }
  $("csvBtn").addEventListener("click", function () { if (last) download("取引先の確認_" + last.on + ".csv", "﻿" + IW.resultsToCsv(last), "text/csv"); });
  $("jsonBtn").addEventListener("click", function () { if (last) download("取引先の確認_" + last.on + ".json", JSON.stringify(last, null, 1), "application/json"); });
})();
