# ihcimen Android クライアント

「今日のページ」をローカルに保持しつつバックグラウンドで同期し、ホーム画面ウィジェットの
「+」ボタンからすぐメモを書けるようにする Android アプリ (Kotlin + Jetpack Compose)。

Web アプリ本体 ([../index.html](../index.html)) や macOS の TodayH1
([../macapp/TodayH1](../macapp/TodayH1)) とはブラウザ/Xcodeを介さず、同じ同期サーバー
(`/api/pull`, `/api/push`) に対して直接 pull → 復号 → 反映 / 編集 → 暗号化 → push を行う、
「もう1台の同期デバイス」として動作します。暗号方式・sync_idの導出は、Webアプリの実装
(index.htmlの`deriveSyncId`/`deriveAesKey`)とTodayH1の実装
(Crypto.swift)をそのまま踏襲しています ([SyncCrypto.kt](app/src/main/java/com/ihcimen/android/crypto/SyncCrypto.kt))。

## できること (MVP スコープ)

- 今日のページの閲覧・編集(見出し `# ` / 箇条書き `- ` の自動継続つき)
- 直近14日分の一覧・編集
- ホーム画面ウィジェットの「+」ボタン → 見出しをすぐ書いて保存 → 今日のページの先頭に挿入
  (TodayH1のCmd2回押しキャプチャと同じ体験。オフライン時は保留し、次のバックグラウンド同期時に
  自動で再送)
- バックグラウンド定期同期 (WorkManager, 30分間隔 + 編集直後・キャプチャ直後は即時実行)
- 同期シードの手動貼り付けによる有効化 (QRコード・6桁コードハンドオフは未実装)

**対象外 (今回のスコープ外)**: カレンダー同期チャンネル(日/週メモ・セル色分け・ICS購読)、
QRコード/6桁コードによるシード導入、Alt+↑/↓の行入れ替え。

## ビルド

Android Studio (Meerkat以降推奨) でこの `android/` ディレクトリを開いてください。
Gradle wrapper のjarはリポジトリに含めていないため、初回は Android Studio が
「Gradle wrapper を生成しますか」等を提案するはずです。手元に Gradle が入っていれば
以下でも生成できます。

```bash
gradle wrapper --gradle-version 8.9
```

その後は通常通り Sync → Run で、エミュレータ/実機にインストールできます。

このプロジェクトの作成時点では手元にJavaランタイムが動作する状態で用意されていなかったため、
`./gradlew` によるビルド確認はできていません。依存バージョンは(2026年時点での最新ではなく)
広く実績のある安定版に意図的に固定しています。Android Studio がプラグイン/依存関係の
アップグレードを提案してきたら、素直に受け入れて構いません。

とくに `widget/TodayWidget.kt` (Glance) は API の変遷が激しいライブラリなので、
インポートやシグネチャの軽微な修正が必要になる可能性が最も高い箇所です。

## 初回セットアップ

1. アプリを起動し、下部の「設定」タブを開く。
2. Webアプリ側の「設定 > 同期」パネルに表示されているシード文字列をコピーし、
   「同期シード」欄に貼り付けて保存する(同期が未設定なら、先にWebアプリ側で同期をONに
   してください)。API URLはデフォルトで `https://ihcimen.vercel.app` になっています。
3. ホーム画面を長押し→ウィジェット→「Daily Notes」の「今日のページ」ウィジェットを追加。

## 動作確認のしかた

1. Webアプリ側で「今日のページ」に何か書いて保存 → Androidアプリの「今日」タブで
   同期後に同じ内容が表示されることを確認。
2. ホーム画面のウィジェットの「+」→ 見出しを入力して保存 → オンライン状態なら数秒〜次回
   同期のタイミングでWebアプリ側の「今日のページ」の先頭に同じH1ブロックが追加されることを
   確認。
3. 機内モードでウィジェットからキャプチャ → オンライン復帰後、保留分が自動的に送信される
   ことを確認。
4. `app/src/test/java/com/ihcimen/android/crypto/SyncCryptoTest.kt` は
   `deriveSyncId`/`deriveAesKey` の出力を、Python標準ライブラリ(hashlib/hmac)で
   独立に計算した値と突き合わせています。Android Studio か
   `./gradlew testDebugUnitTest` で実行できます。

## 同期の仕組み(実装メモ)

- 「entries」チャンネル(本文)のみ対応。全体を1つの暗号化blobとして last-write-wins で
  同期する点はWebアプリと同じで、フィールド単位のマージはしません
  ([SyncManager.kt](app/src/main/java/com/ihcimen/android/sync/SyncManager.kt))。
- ウィジェットのキャプチャは、ローカルキャッシュではなく毎回サーバーの最新状態を
  pullしてから今日のキーの先頭に追記してpushします(TodayH1の`prependToday`と同じ設計)。
  他デバイスの新しい変更を上書きしてしまうのを避けるためです。
- push が拒否された(サーバー側に新しい変更がある)場合、中身が実質同じなら黙って
  タイムスタンプだけ合わせ、実際に食い違っていれば「この端末を優先/サーバーを優先」を
  選ぶ画面を出します。Webアプリの同期競合ダイアログと同じ選択肢です。
