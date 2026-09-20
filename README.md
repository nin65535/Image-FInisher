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

仕様と実装計画は [documents/README.md](documents/README.md) を参照してください。
