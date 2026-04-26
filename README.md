# mdconverter

**バージョン**: 0.3.0

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
- **PDF の表抽出** (オプション・実験的): 「PDFの表をMarkdown表として抽出」を
  ON にすると、PDF 内の表を `pdfplumber` で検出して Markdown 表
  (`| 列1 | 列2 |\n|---|---|\n| ... |`) として出力します（低速）
- **画像をフォルダに保存** (オプション・v0.3.0): 「画像をフォルダに保存」を
  ON にすると、Markdown 出力から画像を除外する代わりに、`<出力名>_images/`
  フォルダへ画像ファイルを書き出し、Markdown には相対パス参照
  (`![](xxx_images/image001.png)`) を残します
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

### PDF の表抽出 (オプション機能) の制約

「PDFの表をMarkdown表として抽出」オプションを ON にした場合の制約：

- 罫線のない（スペース区切りの）表は検出精度が落ちます
- 結合セルは正しく表現できない場合があります
- 表のあるページで処理が数倍遅くなります
- 大型 PDF で稀にハングする可能性があります（ページ単位で失敗時は
  通常テキスト抽出にフォールバックしますが、完全防止ではありません。
  キャンセルボタンで中断可能です）

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

### 未リリース

- **PDF の表抽出オプション** — 「PDFの表をMarkdown表として抽出」チェック
  ボックスを追加（デフォルト OFF）。`pdfplumber` で PDF 内の表を検出し、
  Markdown 表 (`| col | ... |`) として出力。表領域内のテキストは本文から
  除外し重複を防ぐ。pdfplumber は過去に大型 PDF でハングした実績がある
  ため、ページ単位で `try/except` し失敗時は pypdfium2 のテキスト抽出に
  フォールバック。設定は `~/.mdconverter.json` の `extract_tables` キー
  に永続化

### v0.3.0 (2026-04-19)

- **画像保存オプション追加** — 「画像をフォルダに保存（相対パス参照）」
  チェックボックスを追加（デフォルト OFF）。ON にすると、Markdown 出力
  から画像を削除する代わりに `<出力名>_images/` フォルダへ画像ファイル
  (PNG / JPEG / その他) を書き出し、Markdown 上は相対パス参照
  (`![](xxx_images/image001.png)`) を残す。data URI 画像は base64 を
  デコードしてファイル化、PDF 内の画像も pypdfium2 経由で抽出。OFF の
  場合は従来通り画像参照を Markdown から完全に除去
- **設定の永続化を拡張** — `~/.mdconverter.json` に `save_images` キー
  を追加し、UI の状態を記憶
- **GUI レイアウト図を更新** — README 等の補助ドキュメントを v0.3.0
  仕様に合わせて更新

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
