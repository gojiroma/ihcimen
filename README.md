# ihcimen (Daily Notes)

日々のメモと下段カレンダーを一体化した、シングルページの日誌アプリ。本体はビルド不要の
単一HTMLファイル([index.html](index.html))で、Markdown風の記法で書ける本文欄、
日/週/年でメモを付けられるカレンダー、複数端末間のエンドツーエンド暗号化同期を持つ。
PWAとしてホーム画面に追加でき、Vercel + Neon(Postgres)上で動作する。

## 主な機能

- **本文欄**: `# 見出し` 単位でブロック化されるメモ欄。見出し・箇条書きの自動継続、
  チェックボックス、優先度(`!`)付き見出し、Markdownプレビュー、編集履歴(バージョン管理)。
- **下段カレンダー**: 日付ごとの予定メモ・色分け。展開すると全画面表示になり、前後複数年を
  スクロールでき、曜日・毎月同日・平日/休日での絞り込みができる。
- **Week pane**: 週ごとのメモ・色分け。年の区切りにも書き込み可能なメモ欄がある。
- **検索**: 本文・カレンダーの予定メモを横断検索。見出し辞書順一覧も表示できる。
- **ICS連携**: 外部ICSカレンダーの購読(下段カレンダーに予定表示)、日/週カレンダーの
  ICS公開URL発行(標準カレンダーアプリから購読可能)。
- **同期**: シード文字列(QRコード・6桁コード・URL経由)で複数端末に同じ日誌を同期。
  内容は送信前に端末上でAES-GCM暗号化され、サーバーは暗号文しか保持しない。
- **一時共有**: 日誌を1回だけ読める使い捨てリンクとして共有(タブを閉じると失効)。
- **バックアップ**: 全データをJSONでエクスポート/インポート。同期未使用時も端末内に
  保存され続ける。
- **PWA**: オフライン対応のService Worker([sw.js](sw.js))、ホーム画面追加、
  ダークモード対応。

## 構成

```
index.html      フロントエンド本体(単一HTMLファイル、ビルド不要)
sw.js           PWAのService Worker
manifest.json   PWA manifest
api/index.py    バックエンドAPI(Flask、Vercelのサーバーレス関数として動作)
schema.sql      DBスキーマの参考コピー(実際はAPI側が起動時に自動作成する)
vercel.json     Vercelのルーティング・cron設定
requirements.txt  バックエンドのPython依存(Flask, psycopg2-binary)
android/        Android版クライアント(Kotlin + Jetpack Compose)。詳細は android/README.md
macapp/TodayH1  macOS用メニューバーアプリ(Cmd2回押しで即メモ)。詳細は macapp/TodayH1/README.md
```

`index.html` はこのアプリの中心で、UI・状態管理・暗号化・同期ロジックまで全てを含む
(ビルドステップなし、依存はCDN経由の `marked`/`qrcode`/`jsQR` のみ)。

## 同期の仕組み

- 本文とカレンダー(予定メモ・色分け・ICS購読)は、それぞれ独立したチャンネルとして
  暗号化・同期される(SYNC_CHANNELS)。
- 同期IDは、端末が持つシードから `SHA-256` などで導出され、サーバーには生のシードも
  復号済み内容も送られない(`sync_blobs` テーブルにはAES-GCM暗号文のみ保存)。
- 「どちらが新しいか」の判定は各チャンネルの実編集時刻(contentKey)基準で行い、
  競合時はユーザーに選択させる。
- 7日間同期が行われなかったデータはサーバー側から自動削除される
  (`vercel.json` の cron が毎日 `/api/cleanup` を叩く)。削除後もローカルのデータは
  端末に残っており、次にオンラインになったタイミングで自動的に再アップロードされる。
- シードの端末間引き継ぎは、QRコード表示・6桁コード(10分間有効)・一時共有リンクの
  3通り。詳細は [schema.sql](schema.sql) と [api/index.py](api/index.py) を参照。

## デプロイ

Vercel + Neon(Postgres)を想定した構成。

1. Vercelにこのリポジトリを接続し、Neon integration を有効化する
   (`DATABASE_URL` または `POSTGRES_URL` 環境変数が自動設定される)。
2. DBスキーマは初回リクエスト時にAPI側が自動作成する(`ensure_schema()`)。
   [schema.sql](schema.sql) は手動実行用ではなく参考コピー。
3. `vercel.json` の cron (`/api/cleanup` を毎日3時に実行)が有効な状態でデプロイする。

## ローカル開発

フロントエンドはビルド不要なので、`index.html` を任意の静的サーバーで配信するだけで
動作を確認できる(同期・ICS連携などAPIを使う機能を試すにはバックエンドも別途起動する)。

```bash
python3 -m http.server 8080
```

バックエンドは Flask アプリとしてローカルでも起動できる(要 `DATABASE_URL`)。

```bash
pip install -r requirements.txt
DATABASE_URL=postgres://... FLASK_APP=api/index.py flask run
```

## 関連クライアント

同じ同期サーバー(`/api/pull` / `/api/push`)に対して、ブラウザを介さず直接
pull→復号→編集→暗号化→pushを行う「もう1台の同期デバイス」として、Web本体とは別に
2つのネイティブクライアントがある。

- **[android/](android/)** — ホーム画面ウィジェットの「+」から即メモ、バックグラウンド定期同期。
- **[macapp/TodayH1/](macapp/TodayH1/)** — Cmdキー2回押しでどこからでも見出しブロックを追記。

## セキュリティ・プライバシー

- 同期データはすべて端末上でAES-GCM暗号化してから送信され、サーバーは暗号文しか
  保持しない(シード自体もサーバーには送られない)。
- 例外は「ICS公開URL」機能のみ:標準カレンダークライアントがJS無しで直接GETできる
  必要があるため、公開したICSテキストは意図的に平文で保存される
  (ユーザーが明示的に有効化した場合のみ)。
