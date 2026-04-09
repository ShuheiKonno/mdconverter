# mdconverter

ローカルで動くシンプルな Markdown 変換ソフトです。
[microsoft/markitdown](https://github.com/microsoft/markitdown) をコアに、
PDF / Office / HTML / 画像 / 音声 / EPub / URL / YouTube などを
Markdown に変換します。

最終成果物は Windows 用の単一実行ファイル (`mdconverter.exe`) として
配布できます。

## 主な機能

- **豊富な対応形式**: `markitdown[all]` で PDF / DOCX / PPTX / XLSX /
  HTML / CSV / JSON / XML / 画像 / 音声 / ZIP / EPub / URL / YouTube
- **GUI (CustomTkinter)**: モダンな外観・ダークモード対応・ドラッグ&ドロップ
- **容量制限なし**: ローカル実行なのでサイズ上限はありません
  (markitdown / 依存ライブラリの仕様上限のみ)
- **2段プログレスバー**: 全体進捗 + 現在ファイルのバイト単位進捗。
  URL/YouTube のように総量が不明な場合はアニメーション表示に切り替わります
- **キャンセル対応**: 変換中にキャンセルボタンで安全に中断
- **バッチ処理**: 複数ファイル / フォルダ (再帰) / URL の混在を一括変換

## 動作要件

- **OS**: Windows 10 / 11 (配布バイナリ)。開発時は macOS / Linux でも起動可
- **Python** (開発時のみ): 3.10 以上 (3.11 推奨)

## 使い方 (配布バイナリ)

1. Releases から `mdconverter.exe` をダウンロード
2. ダブルクリックで起動
3. ファイル/フォルダをウィンドウにドラッグ&ドロップするか「ファイル追加」
   から選択
4. 出力先フォルダを指定し、「変換開始」をクリック
5. 完了後、出力先に `.md` ファイルが生成されます

URL や YouTube を変換する場合は上部タブを「URL / YouTube」に切り替えて
URL を貼り付けてください。

## 開発 (ソースから起動)

```bash
# 1. 仮想環境
python -m venv .venv
source .venv/bin/activate            # Windows は .\.venv\Scripts\Activate.ps1

# 2. 依存インストール
pip install -e ".[build]"

# 3. 起動
python -m mdconverter
```

## Windows 用 .exe のビルド

詳細は [`BUILD_WINDOWS.md`](./BUILD_WINDOWS.md) を参照してください。
要約:

```powershell
pip install -e ".[build]"
pyinstaller build/mdconverter.spec --clean --noconfirm
# => dist\mdconverter.exe
```

## プロジェクト構成

```
mdconverter/
├── src/mdconverter/
│   ├── __init__.py
│   ├── __main__.py         # `python -m mdconverter` エントリ
│   ├── app.py              # CustomTkinter GUI
│   ├── converter.py        # markitdown ラッパ (進捗 + バッチ + キャンセル)
│   ├── progress_stream.py  # file-like ラッパ (read 毎に進捗通知)
│   └── worker.py           # バックグラウンドスレッド + イベントキュー
├── build/
│   └── mdconverter.spec    # PyInstaller 設定
├── pyproject.toml
├── requirements.txt
├── README.md
└── BUILD_WINDOWS.md        # VS Code (Windows) 向けビルド指示書
```

## ライセンス

MIT。依存ライブラリはそれぞれのライセンスに従います
(markitdown: MIT, CustomTkinter: MIT, tkinterdnd2: MIT 等)。
