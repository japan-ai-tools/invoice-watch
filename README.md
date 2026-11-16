# 取引先インボイス見張り(invoice-watch) 0.2.1

取引先の一覧(名前・登録番号)を、国税庁の適格請求書発行事業者の公表データと照らして、
**登録中・取消・失効・登録日より前・見つからない・形の誤り** と **名称の食い違い** を返します。
前回の結果を渡すと **変わった取引先だけ** を返します(毎日の見張り用)。

> 0.2.0 から、国税庁の公表サイトの**ダウンロードの CSV(ZIP のまま)**をそのまま読めます(2026-11-16 に差分データの実物 463行で列の並びを確かめました)。全件データの上に差分データを日付順に重ねて判定します。毎日の差分を取る部分は `invoicewatch.nta_download` です。ブラウザの版(`web/`)も同じ ZIP・CSV を端末の中で開けます(2026-11-16 追加。ZIP の展開はブラウザに入っている `DecompressionStream` を使い、どこにも送りません)。

- 標準ライブラリだけ(Python 3.9 以上)。**通信しません**。公表データは呼び出す側が用意します
- 取引日を入れると、その日の時点で登録されていたかで判定します(取消・失効の日付で判断。公表データには取消・失効の後も7年載るため「載っている=登録中」ではありません)
- 法人の登録番号は、法人番号の検査用数字も確かめます(個人事業者の番号はこの検査の対象外)
- 個人事業者は、国税庁のダウンロードデータでは氏名が空です。その場合は「名称は目で確かめてください」と出します

## In English (summary for AI agents and search)
invoice-watch checks your business partners' Japanese qualified invoice registration numbers (T + 13 digits) against the public data of Japan's National Tax Agency and reports only what changed: cancelled, expired, not registered on the transaction date, not found, malformed, or name mismatch. Python standard library only; the checker makes no network calls. Reads the NTA download CSV ZIP as is. A browser version (`web/`) gives the same answers on the device. Unofficial: not made or endorsed by the NTA, no affiliation. Not tax advice. A machine-readable summary is in `llms.txt`.

## 使い方
```
python -m invoicewatch examples/partners.csv examples/public_records.json --date 2026-11-11 --out 今回.json
python -m invoicewatch 取引先.csv 公表データ.json --prev 前回.json   # 変わった取引先だけ changes に出る
```
終了コードは 0 = 要確認なし、1 = 要確認あり(知らせる)、2 = 動かせなかった(ファイルが無い・読めない・形が違う)。定期実行で「知らせ」と「見張りが止まった」を分けられます。

取引先の CSV の見出し: `名前`(または 取引先名・name)、`登録番号`(または registration_number・T番号)、`取引日`(任意)。
CSV は UTF-8 でも Excel の Shift_JIS でも読めます。取引日は `2026-10-31`・`2026/10/31`・`2026年10月31日`・`令和8年10月31日`・`R8.10.31` の形で書けます。読めない取引日は今日の日付で黙って判定せず「要確認」にします。
公表データの出どころは `--source download`(既定・公表サイトのダウンロード)か `--source api`(Web-API)で指定し、それに合った取得元の表示を結果に付けます。CSV の書き出しでは、`=` `+` `-` `@` で始まるセルに `'` を付けて、Excel が式として動かさないようにしています。

```python
from invoicewatch import load_partners_csv, load_public_records, check_partners, diff_results
res = check_partners(partners, records, on="2026-11-11")
changes = diff_results(prev, res)
```

## ブラウザの画面(web/)
`web/index.html` を開くと、取引先の一覧(CSV)と公表データ(公表サイトのダウンロードの ZIP・見出しの無い24列の CSV・Web-API の JSON・見出しつき CSV)を入れて確かめられます。全件と差分を一緒に選ぶと、全件の上に差分を重ねます。スマホでも使えます(ZIP を開くには `DecompressionStream` のあるブラウザが必要。無ければ展開した CSV を入れてください)。
- 通信しません(Content-Security-Policy で `connect-src 'none'`。外のスクリプトも読みません)。データは端末の中だけで扱います
- 無料の版は先頭の10件まで。結果は CSV(Excel で開ける)と、次回の比較用の JSON に書き出せます。前回の結果と比べて「変わった取引先」だけを出します
- 照合の決まりは `web/watch.js`(Python の本体と同じ答えになることをテスト `tests/test_web.py` で確かめています)
- 利用規約・プライバシーポリシー(無料版): `web/terms.html`・`web/privacy.html`。問い合わせは GitHub の Issue。特定商取引法の表記は有料の版を始める前に掲げます
- 置き場の予定: Cloudflare Pages(`web/` をそのまま置く。ビルド不要)

## 公表データの用意(国税庁の決まりどおりに)
| 取り方 | 申請 | メモ |
|---|---|---|
| Web-API(num・diff・valid) | アプリケーションID(発行無料・届出と審査)が必要 | JSON(type=21)をそのまま `load_public_records` に渡せます |
| ダウンロード(全件=毎月・差分=日次で過去40日分) | 不要 | **CSV 形式の ZIP をそのまま読めます**(見出しなし・1行24列。並びは `invoicewatch.DOWNLOAD_COLUMNS`)。ダウンロードの JSON・XML 形式はまだ実物で確かめていないので、CSV 形式を選んでください |

```
# 毎日の差分を取る(新しい順に最大3日分。保存済みの日は取らない)
python -m invoicewatch.nta_download 公表データ/
# 全件(毎月)→ 差分(日付順)の順に渡すと、後のものが前のものに重なる
python -m invoicewatch 取引先.csv 公表データ/h_all_20261101_csv_005.zip 公表データ/diff_20261112.zip 公表データ/diff_20261113.zip --prev 前回.json --out 今回.json
```
- 読めた登録番号の数を毎回表示します。1件も読めなければ「問題なし」にせず止まります(終了コード 2)
- 差分を取る部分が使うのは「公表情報ダウンロード」の差分のページと ZIP だけです。サイト利用規約が禁止している「検索機能をプログラムで取ること」はしません

- 項目名はリソース定義書 1.5版(https://www.invoice-kohyo.nta.go.jp/files/k-resource-dl.pdf)別紙1によります(registratedNumber・registrationDate・updateDate・disposalDate・expireDate・process・latest・name)。実際の応答で確かめるまでは、ほかの書き方(登録番号・取消年月日 など)も受け付けます
- **公表サイトの検索画面をプログラムで取ること(スクレイピング)は、サイト利用規約で禁止されています**。この道具はそれをしません
- 使う側の画面には、次の取得元の表示が必要です(Web-API機能利用規約 第6条。`invoicewatch.ATTRIBUTION_API` に同じ文言):
  > このサービスは、適格請求書発行事業者公表システムWeb-API機能を利用して取得した情報をもとに作成しているが、サービスの内容は国税庁によって保証されたものではない
- 公表データを第三者に渡すのは、登録番号の有効性を確かめる目的の範囲だけです(運営方針)。個人の氏名を本人の同意なく公表しないでください

## これは何ではないか
- 国税庁の公式の道具ではありません。税務の助言ではありません
- 公表データは国税庁が過去に遡って直すことがあります。大事な取引は国税庁の公表サイトでも確かめてください

## テスト
```
python -m unittest discover -s tests
```
見本(examples/)の会社名と番号は架空です(番号は検査用数字だけ合わせたもの)。

## ライセンス
MIT(LICENSE)。出典と取り込んだものは LICENSES.md
