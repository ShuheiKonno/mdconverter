# mdconverter

**バージョン**: 0.2.0

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
- **PDF のページ構造化** (v0.2.0): PDF は各ページ先頭に `## ページ N` の
  見出しを付けて出力し、論理構造を Markdown 上に残します
- **出力先フォルダ記憶** (v0.2.0): 前回指定した出力先を `~/.mdconverter.json`
  に保存し、次回起動時に自動で復元
- **エクスプローラで開く** (v0.2.0): 出力先フォルダを OS のファイル
  マネージャ (Windows: エクスプローラ / macOS: Finder / Linux: xdg-open) で
  ワンクリックで開ける

## 想定ユースケース

本ツールは、手元の PDF / Office ファイルを **LLM が扱いやすい Markdown**
に変換することを主眼にしています。とりわけ以下の用途に向いています。

- **各種 AI サービスのプロジェクトファイルとして投入**
  - Claude Projects / ChatGPT Projects / Gemini Gems / NotebookLM 等の
    コンテキストに Markdown を追加することで、PDF を直接アップロードする
    より **トークン消費が少なく、見出し・段落・表・リストの構造を正確に
    モデルに伝えられます**
  - v0.2.0 から PDF は `## ページ N` 見出しで区切られるため、モデルが
    「◯◯ページを引用して」といった指示に応えやすくなります
- **RAG (Retrieval-Augmented Generation) のソースデータ**
  - ベクトル DB へのインデックス前処理として、社内文書・マニュアル・
    論文 PDF を Markdown 化すると、チャンク分割 (ヘディングやページ単位)
    と埋め込み精度が向上します
  - Markdown のプレーンテキスト性は、LangChain / LlamaIndex 等の
    ドキュメントローダーとの相性も良好です
- **ローカル処理のみ** — 変換はすべて手元の PC で行うため、機密情報を
  含むドキュメントを外部サービスにアップロードすることなく下処理できます

## 制限事項

### 画像データの扱い

**本ツールは Markdown 出力から画像を除外します。** 変換結果はテキスト
構造（見出し・段落・表・リスト）のみで構成され、画像参照
(`![...](data:image/png;base64,...)` や `![...](Picture1.jpg)`) は削除
されます。これは主要な利用シーン（AI サービスへの投入 / RAG インデックス）
では画像参照がトークンを無駄に消費するだけで実益がないためです。

- **画像の内容を LLM に理解させたい場合** は、本ツールを経由せず
  **元の PDF / PPTX をそのまま** AI サービスにアップロードしてください
  (Claude / ChatGPT / Gemini / NotebookLM はいずれも PDF / PPTX の
  画像を内部的に解析します)
- **スキャン PDF (画像としての PDF) はテキスト抽出できません**
  - pypdfium2 で抽出できるのは埋め込みテキストのみ。OCR は行わないため、
    スキャン PDF を Markdown 化する場合は別途 OCR ツール
    (`ocrmypdf` など) での前処理が必要です

その他、音声ファイルの文字起こし精度は `SpeechRecognition` 依存、
YouTube 字幕は `youtube-transcript-api` の取得可否に依存します。

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
pyinstaller build/mdconverter.spec --clean --noconfirm --distpath .
# => mdconverter.exe (プロジェクトルート直下)
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

## 更新履歴

### v0.2.0 (2026-04-18)

- **PDF をページ毎に構造化** — 各ページ先頭に `## ページ N` 見出しを
  挿入。`markitdown` が平文として結合していた PDF 出力を、論理構造を
  保った Markdown に変更
- **画像データを Markdown から除外** — 従来は base64 data URI として
  埋め込んでいたが、AI サービス (Claude / ChatGPT / NotebookLM) や
  RAG パイプラインでは data URI 画像が無視されトークンを無駄にする
  だけだったため廃止。`.md` はテキスト構造のみに整理される
- **PDF バックエンドを pypdfium2 に変更** — Google PDFium (Chrome の
  PDF エンジン) の Python バインディングを採用。複雑な PDF で
  `pdfplumber` が無限ループ / ハングする問題を回避し、抽出速度も
  1〜2 桁向上
- **大容量 PDF (~300 ページ超) で GUI が固まる問題を修正** — ワーカー
  スレッド終了時にイベントキューを完全にドレインしないバグ
  ([app.py `_poll_worker`](src/mdconverter/app.py)) を修正
- **出力先フォルダの永続化** — 参照ボタンや変換開始時に
  `~/.mdconverter.json` へ保存し、次回起動時に自動で復元
- **「開く」ボタン追加** — 出力先フォルダを OS ファイルマネージャで
  開く（Windows / macOS / Linux 対応）
- **バージョン表示** — タイトルバーとウィンドウ下部にバージョン番号を
  明示
- 変換中ログにページ毎の進捗 (`ページ N/M を処理中...`) を表示するよう
  にして、重い PDF でも処理が生きていることを可視化

### v0.1.0

- 初版リリース
- markitdown ラッパ + CustomTkinter GUI + PyInstaller 配布 (.exe)

## ライセンス

MIT。依存ライブラリはそれぞれのライセンスに従います
(markitdown: MIT, CustomTkinter: MIT, tkinterdnd2: MIT 等)。
