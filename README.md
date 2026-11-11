# 取引先インボイス見張り(invoice-watch) 0.1.0

取引先の一覧(名前・登録番号)を、国税庁の適格請求書発行事業者の公表データと照らして、
**登録中・取消・失効・登録日より前・見つからない・形の誤り** と **名称の食い違い** を返します。
前回の結果を渡すと **変わった取引先だけ** を返します(毎日の見張り用)。

- 標準ライブラリだけ(Python 3.9 以上)。**通信しません**。公表データは呼び出す側が用意します
- 取引日を入れると、その日の時点で登録されていたかで判定します(取消・失効の日付で判断。公表データには取消・失効の後も7年載るため「載っている=登録中」ではありません)
- 法人の登録番号は、法人番号の検査用数字も確かめます(個人事業者の番号はこの検査の対象外)
- 個人事業者は、国税庁のダウンロードデータでは氏名が空です。その場合は「名称は目で確かめてください」と出します

## 使い方
```
python -m invoicewatch examples/partners.csv examples/public_records.json --date 2026-11-11 --out 今回.json
python -m invoicewatch 取引先.csv 公表データ.json --prev 前回.json   # 変わった取引先だけ changes に出る
```
知らせることがあると終了コード 1 を返します(定期実行で使えます)。

取引先の CSV の見出し: `名前`(または 取引先名・name)、`登録番号`(または registration_number・T番号)、`取引日`(任意)。

```python
from invoicewatch import load_partners_csv, load_public_records, check_partners, diff_results
res = check_partners(partners, records, on="2026-11-11")
changes = diff_results(prev, res)
```

## ブラウザの画面(web/)
`web/index.html` を開くと、取引先の一覧(CSV)と公表データ(JSON か見出しつき CSV)を入れて確かめられます。スマホでも使えます。
- 通信しません(Content-Security-Policy で `connect-src 'none'`。外のスクリプトも読みません)。データは端末の中だけで扱います
- 無料の版は先頭の10件まで。結果は CSV(Excel で開ける)と、次回の比較用の JSON に書き出せます。前回の結果と比べて「変わった取引先」だけを出します
- 照合の決まりは `web/watch.js`(Python の本体と同じ答えになることをテスト `tests/test_web.py` で確かめています)
- 利用規約・プライバシーポリシーの案: `web/terms.html`・`web/privacy.html`。特定商取引法の表記は有料を始める前に所有者が埋めます(`docs/特定商取引法の表記_案.md`)
- 置き場の予定: Cloudflare Pages(`web/` をそのまま置く。ビルド不要)

## 公表データの用意(国税庁の決まりどおりに)
| 取り方 | 申請 | メモ |
|---|---|---|
| Web-API(num・diff・valid) | アプリケーションID(発行無料・届出と審査)が必要 | JSON(type=21)をそのまま `load_public_records` に渡せます |
| ダウンロード(全件=毎月・差分=日次で過去40日分) | 不要 | JSON 形式を使ってください。**見出しの無い CSV はまだ受け付けません**(列の並びを実物で確かめてから対応) |

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
