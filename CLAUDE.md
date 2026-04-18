# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 言語

すべての応答は日本語で行うこと。

## プロジェクト概要

`mdconverter` — `microsoft/markitdown` をラップし、CustomTkinter + tkinterdnd2 で GUI を提供するローカル Markdown 変換ツール。PyInstaller で単一 `mdconverter.exe`（Windows 配布物）にビルドする。開発時は macOS / Linux でも起動可能。

補足ドキュメント:
- [README.md](README.md) — 使い方・機能概要
- [BUILD_WINDOWS.md](BUILD_WINDOWS.md) — `.exe` ビルド手順と PyInstaller トラブルシュート
- [AGENTS.md](AGENTS.md) / [src/mdconverter/AGENTS.md](src/mdconverter/AGENTS.md) — AI エージェント向けの詳細ガイド

## よく使うコマンド

```bash
# 開発セットアップ（build extras で pyinstaller も入る）
python -m venv .venv
source .venv/Scripts/activate   # Git Bash on Windows
pip install -e ".[build]"

# GUI 起動（CLI 引数なし）
python -m mdconverter

# Windows .exe ビルド（リポジトリルートから実行。--distpath . で dist/ を作らずルートに出力）
pyinstaller build/mdconverter.spec --clean --noconfirm --distpath .

# フルクリーンビルド
rm -rf build/build build/mdconverter mdconverter.exe
pyinstaller build/mdconverter.spec --clean --noconfirm --distpath .
```

テストスイートは未整備。追加する場合は `pytest` 前提で `converter.py` を `tmp_path` ベースで叩く。GUI とビルド後 `.exe` は手動テスト（D&D、URL タブ、キャンセル、進捗バー、Python 未導入マシンでの起動）。

CI は [.github/workflows/build-windows.yml](.github/workflows/build-windows.yml) で `claude/markdown-converter-tool-cyOzw` / `main` ブランチ push 時に Windows ビルド → `mdconverter.exe` を artifact としてアップロード。

## アーキテクチャ

**3 層構造**（理解には複数ファイルの読解が必要）:

1. **GUI 層** — [src/mdconverter/app.py](src/mdconverter/app.py)
   CustomTkinter + tkinterdnd2。`_DnDCTk` は `ctk.CTk` と `TkinterDnD.DnDWrapper` を多重継承して D&D 対応の Tk ルートを作る。タブ（ファイル/フォルダ・URL/YouTube）、2 段プログレスバー（全体件数 + 現ファイルのバイト）、ログ textbox を持つ単一ウィンドウ。`POLL_INTERVAL_MS = 50` で worker のイベントキューを `after()` ポーリングする。

2. **ワーカー層** — [src/mdconverter/worker.py](src/mdconverter/worker.py)
   `ConversionWorker(threading.Thread, daemon=True)` が `Converter.convert_batch` を実行。GUI との通信は `queue.Queue[WorkerEvent]` のみで、`WorkerEvent` は dataclass の Union（`OverallProgress` / `FileProgress` / `ItemStarted` / `ItemFinished` / `LogMessage` / `Finished` / `Cancelled` / `Failed`）。キャンセルは `threading.Event` で伝播。`drain_events` が 1 tick あたり最大 64 件を処理する。

3. **変換層** — [src/mdconverter/converter.py](src/mdconverter/converter.py) + [src/mdconverter/progress_stream.py](src/mdconverter/progress_stream.py)
   `Converter` は `MarkItDown(enable_builtins=True, enable_plugins=False)` をラップ。ファイルは `convert_stream` + `ProgressStream` でバイト単位進捗、URL/YouTube は `convert_uri` で不定進捗（`(0, 0)` を投げて UI をパルスモードへ）。バッチは `_expand_sources` でディレクトリを再帰展開し、個別失敗は `ConversionItemResult` に記録してバッチ全体は止めない。

**進捗フロー**: `ProgressStream.read()` → `ByteProgressCallback` → worker が `FileProgress` を enqueue → GUI が 50ms 後に `drain_events` で取り出し描画更新。

**キャンセルフロー**: GUI の `worker.cancel()` → `threading.Event.set()` → 次の `ProgressStream.read()` で `CancelledError` → `Converter` がループを抜けて `Cancelled` イベントを enqueue。

## 実装上の重要な制約

- **`__main__.py` は絶対 import 必須**: `from mdconverter.app import launch` と書く。相対 import に戻すと PyInstaller バンドル後にクラッシュする（コミット `18cdd2e` 参照）。
- **スレッドベースのみ**: 変換は `threading.Thread`（multiprocessing ではない）。`freeze_support` や pickling 制約は関係しない。
- **`ProgressStream` は `io.BufferedIOBase` を継承**: markitdown 内部の `magika.identify_stream` が `isinstance(stream, io.BufferedIOBase)` でバリデートするため。`read` / `read1` / `readinto` / `readinto1` すべてに cancel チェックと progress emit を挟む。進捗は monotonic（seek で後退しない）。
- **画像は出力から除外**: `convert_stream` / `convert_uri` は `keep_data_uris=False` で呼び、さらに `_strip_image_references` で `![...](data:...)` と `![...](Picture1.jpg)` / `![...](https://.../chart.png)` 系（拡張子が画像のもの）を正規表現剥離する。理由は本ツールの主要消費者（Claude Projects / ChatGPT / NotebookLM / RAG）が data URI 画像を無視するかトークンを浪費するだけで実益が無いため。画像込みで AI に読ませたいなら元の PDF/PPTX を直接投入するのが正解（README 「制限事項 > 画像データの扱い」参照）。旧コミット `8577767` は `keep_data_uris=True` で画像を保持していたが方針転換。
- **出力先は常にプロジェクトルート**: `.exe` ビルドは `--distpath .` で `dist/` を作らずルート直下に出す。`.gitignore` も `/mdconverter.exe` をルート直下想定で書いてある。
- **PyInstaller spec の hiddenimports**: [build/mdconverter.spec](build/mdconverter.spec) は `collect_all("markitdown")` に加え、markitdown が遅延 import する optional 依存（`pdfminer`, `mammoth`, `pptx`, `openpyxl`, `magika`, `speech_recognition`, `youtube_transcript_api` 等）を個別に `collect_all` で拾う。新しい変換フォーマットの依存を追加したら spec にも追記が要る。
- **FFmpeg は同梱していない**: 音声変換（`.mp3` / `.wav`）は markitdown が内部で FFmpeg を呼ぶため、`.exe` と同フォルダに `ffmpeg.exe` を置くか PATH を通す。spec の `binaries` に同梱する選択肢もある（BUILD_WINDOWS.md §7.4）。
- **`pyproject.toml` を正、`requirements.txt` は pinned lock として併存**。
