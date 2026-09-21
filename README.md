# Image Finisher

生成済みPNG画像のリネーム、2倍化、モザイク処理をまとめて行う、Windows向けローカル工程管理アプリです。

## 開発環境

- Python 3.12.4
- Node.js 26.9.0 / npm 11.19.1

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Set-Location frontend
npm install
```

## コマンド

```powershell
.\scripts\dev.ps1
.\scripts\test.ps1
.\scripts\build.ps1
```

API単体は `.\.venv\Scripts\python.exe -m backend.run` で起動できます。開発画面は `http://127.0.0.1:5173`、APIドキュメントは `http://127.0.0.1:8000/docs` です。

## 日常運用

初回セットアップ後に本番画面をビルドし、起動します。

```powershell
.\scripts\build.ps1
.\scripts\start.ps1
```

起動完了後、Google Chromeで `http://127.0.0.1:8000/` が自動的に開きます。画面を開いている間はアプリが動作し、最後のImage Finisher画面を閉じて10秒が経過すると自動終了します。処理中のジョブがある場合は、画面を閉じてもジョブが完了または停止するまで終了しません。Chromeが見つからない場合は表示されたURLを手動で開いてください。

ComfyUIを先に起動してから、入力フォルダの選択、工程確認、実行、完成フォルダを開く、BandiViewで目視検品、の順に操作します。入力原本は変更されず、完成画像は入力フォルダと同じ親にある `finished` へ保存されます。

## バックアップ

日常的に保全する対象は `%LOCALAPPDATA%\ImageFinisher\jobs.sqlite3`（ジョブ履歴）と `%LOCALAPPDATA%\ImageFinisher\settings.json`（個人設定）です。アプリ停止中にフォルダごとコピーしてください。入力原本と `finished` はアプリ管理外の成果物として、案件側のバックアップ方針に従って別途保全します。リポジトリ内では `app_master.json` と `external_configs\comfyui_workflows` が共通設定です。

## 障害調査

1. ComfyUIが起動し、`http://127.0.0.1:8188` に接続できることを確認します。
2. PowerShellに表示されたImage Finisherのエラーと、画面のジョブ・画像・工程別エラーを記録します。
3. `%LOCALAPPDATA%\ImageFinisher\jobs.sqlite3`、`settings.json`、対象の元ファイル名、再現手順を保全します。画像自体を共有できない場合は寸法とファイル名だけを記録します。
4. 起動できない場合は `.venv\Scripts\python.exe -m backend.run` を実行し、表示されるエラーを確認します。本番画面がない場合は `.\scripts\build.ps1` を再実行します。

異常終了時に実行中だったジョブは次回起動時に失敗として復元されます。完成済み画像は保持されるため、原因を解消してから「失敗画像だけ再実行」を使用してください。SQLiteや一時フォルダを手作業で削除する前にバックアップを取得してください。

仕様と実装計画は [documents/README.md](documents/README.md) を参照してください。
