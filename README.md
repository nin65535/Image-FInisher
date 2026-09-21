# Image Finisher

Image Finisherは、生成済みPNG画像の仕上げ作業をまとめて実行するWindows向けローカルアプリです。

入力画像を変更せず、画像ごとに次の工程を選択して実行します。

1. ファイル名をグループ別の4桁連番へ整理
2. ComfyUIで4倍に拡大後、Lanczos法で50%縮小（完成寸法は縦横各2倍）
3. ComfyUI AutoMosaicでモザイク処理

処理状況と履歴はブラウザ画面で確認でき、失敗画像だけの再実行や、画像単位で完了してから停止する安全なキャンセルに対応しています。

## 動作環境

- Windows
- Python 3.12.4
- Node.js 26.9.0 / npm 11.19.1
- Google Chrome（通常起動時に自動で画面を開くために使用）
- ComfyUI（拡大またはモザイクを使用する場合）

ComfyUIは `http://127.0.0.1:8188` でAPIを利用できる状態にしてください。保存済みワークフローでは、次のモデル／カスタムノードを使用します。

- `RealESRGAN_x4plus_anime_6B.pth`
- `AutoMosaic`

## 初回セットアップ

リポジトリのルートでPowerShellを開き、Pythonとフロントエンドの依存関係をインストールします。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Set-Location frontend
npm install
Set-Location ..
.\scripts\build.ps1
```

`npm install` はロックファイルの内容を厳密に再現したい場合、`npm ci` に置き換えられます。

## 起動

エクスプローラーから [`scripts/start.cmd`](scripts/start.cmd) をダブルクリックするか、PowerShellで次を実行します。

```powershell
.\scripts\start.ps1
```

起動後、Google Chromeで <http://127.0.0.1:8000/> が自動的に開きます。Chromeが見つからない場合は、PowerShellに表示されたURLを手動で開いてください。

最後のImage Finisher画面を閉じて10秒経過すると、アプリも自動終了します。実行中、待機中、またはキャンセル要求中のジョブがある場合は、ジョブが終了するまで停止しません。

## 使い方

1. 拡大またはモザイクを使う場合は、先にComfyUIを起動します。
2. 「フォルダを選択」から入力フォルダを指定します。
3. 対象件数、完成先、命名プレビュー、事前検証結果を確認します。
4. リネーム、拡大、モザイクから必要な工程を選びます。
5. モザイクを使う場合は強度を指定し、処理を開始します。
6. 完了後に「完成フォルダを開く」から成果物を確認します。
7. BandiViewなどの画像ビューアーで、画像品質とモザイク範囲を目視検品します。

工程は常に `リネーム → 拡大 → モザイク` の順で実行されます。工程の選択状態とモザイク強度は次回起動時に復元されます。

### 入力ファイルの規則

入力フォルダ直下にあるPNGだけが対象です。サブフォルダ内の画像やPNG以外のファイルは処理しません。

ファイル名は、拡張子を除いて次の形式である必要があります。

```text
<グループ名>_<数字列>_
```

同じグループの画像を元ファイル名順に並べ、`0001` から採番します。

```text
scene01_00004_.png → scene01_0001.png
scene01_00019_.png → scene01_0002.png
```

1グループの上限は9999枚です。規則に合わないPNG、読み込めないPNG、完成名の重複、既存出力との衝突などが1件でもある場合、処理は開始されません。

### 出力先と安全性

完成画像は、入力フォルダと同じ親フォルダにある `finished` へ保存されます。

```text
C:\案件\input     ← 入力フォルダ
C:\案件\finished  ← 完成画像
```

- 入力原本は削除、移動、改名、上書きしません。
- 中間ファイルは `../.imagefinisher-tmp` 配下のジョブ専用領域だけに作成します。
- 選択した全工程と出力検証が成功した画像だけを `finished` へ確定します。
- 既存の完成画像は上書きしません。
- 一部の画像が失敗しても、成功済みの画像は保持します。

## データとバックアップ

アプリの状態は `%LOCALAPPDATA%\ImageFinisher` に保存されます。

| ファイル | 内容 |
| --- | --- |
| `jobs.sqlite3` | ジョブ、画像、工程、エラーの履歴 |
| `settings.json` | 工程の選択状態とモザイク強度 |

バックアップはアプリ停止中にフォルダごとコピーしてください。入力原本と `finished` はアプリの管理外なので、案件側の方針に従って別途保全してください。

リポジトリ内の共通設定は `app_master.json`、ComfyUI APIワークフローは `external_configs/comfyui_workflows` にあります。

## トラブルシューティング

### ComfyUIへ接続できない

ComfyUIが起動し、<http://127.0.0.1:8188> に接続できることを確認してください。必要なモデルとAutoMosaicノードも確認します。

### 起動時に `.venv` または `frontend/dist` がないと表示される

初回セットアップを実行してください。画面のビルドだけがない場合は、次を再実行します。

```powershell
.\scripts\build.ps1
```

### 画面が自動で開かない

Chromeが標準的な場所にインストールされていない可能性があります。PowerShellに表示された <http://127.0.0.1:8000/> をブラウザで開いてください。

### 異常終了したジョブを復旧したい

異常終了時に実行中だったジョブは、次回起動時に失敗として復元されます。成功済み画像は保持されるため、原因を解消してから画面の「失敗画像だけ再実行」を使用してください。

調査時は、PowerShellのエラー、画面に表示された工程別エラー、対象の元ファイル名、再現手順を記録してください。必要に応じて `jobs.sqlite3` と `settings.json` をバックアップします。SQLiteや一時フォルダを手作業で削除する前にも、必ずバックアップを取得してください。

## 開発

バックエンドとVite開発サーバーを起動します。

```powershell
.\scripts\dev.ps1
```

- 開発画面: <http://127.0.0.1:5173/>
- API: <http://127.0.0.1:8000/>
- OpenAPI UI: <http://127.0.0.1:8000/docs>

バックエンドだけを通常モードで起動する場合は、次を実行します。この方法でもビルド済み画面があれば配信され、Chromeが起動します。

```powershell
.\.venv\Scripts\python.exe -m backend.run
```

テスト、型検査、本番ビルドは各スクリプトから実行できます。

```powershell
.\scripts\test.ps1
.\scripts\build.ps1
```

`test.ps1` はPythonテストの後にTypeScriptの型検査を実行します。`build.ps1` は型検査後に `frontend/dist` を生成します。

## 構成

```text
backend/                   FastAPI、ジョブ管理、画像処理、ComfyUI連携
frontend/                  React / TypeScript / Vite UI
external_configs/          ComfyUI APIワークフロー
scripts/                   起動、開発、テスト、ビルド用スクリプト
tests/                     バックエンドテスト
documents/                 仕様書、実装ロードマップ、実装ログ
app_master.json            アプリ共通設定
```

詳しい仕様と設計判断は [documents/README.md](documents/README.md) を参照してください。
