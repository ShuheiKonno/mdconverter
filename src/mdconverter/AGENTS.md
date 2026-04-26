<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-15 | Updated: 2026-04-18 -->

# mdconverter

## Purpose
markdownconverter のメインパッケージ。`microsoft/markitdown` をラップして任意の文書を Markdown に変換する GUI アプリを提供する。`python -m mdconverter` で GUI を起動し、変換処理はバックグラウンドスレッドで実行して GUI をブロックしない。

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | パッケージ初期化、`__version__ = "0.1.0"` を公開 |
| `__main__.py` | `python -m mdconverter` のエントリ。`app.launch()` を呼ぶだけ（CLI 引数なし） |
| `app.py` | CustomTkinter + tkinterdnd2 による GUI 本体（単一ウィンドウ、タブ切替、D&D、進捗バー 2 本、ログ） |
| `converter.py` | `markitdown.MarkItDown` ラッパ。ファイル/ディレクトリ/URL を受けて Markdown を出力。バイト/バッチ両方の進捗コールバックを発火 |
| `worker.py` | `ConversionWorker(threading.Thread)` と `WorkerEvent`／`drain_events`。変換進捗を `queue.Queue` 経由で GUI に通知 |
| `progress_stream.py` | `read()` ごとにコールバックで進捗通知する file-like ラッパ。キャンセル時は `CancelledError` を raise |
| `__pycache__/` | Python バイトコードキャッシュ（gitignore） |

## Subdirectories

なし

## For AI Agents

### Working In This Directory
- **起動**: `python -m mdconverter` で GUI のみ起動。CLI モードは未実装
- **変換ソース追加**: `converter.py` の `Converter` クラスに新メソッドを足し、`app.py` のタブ／ハンドラから呼び出す
- **進捗の流れ**: `ProgressStream.read()` → `ByteProgressCallback` → `ConversionWorker` が `FileProgress` イベントを enqueue → GUI が 50ms 間隔で `drain_events` → プログレスバー更新
- **キャンセル**: GUI が `worker.cancel()` → `threading.Event` が立つ → `ProgressStream` が次回 `read()` で `CancelledError` → `converter` がループを抜けて `Cancelled` イベントを enqueue

### Testing Requirements
- テストは未整備。追加する場合は `converter.py` を対象に、小さな HTML/DOCX サンプルを `tmp_path` に書き出して変換を走らせるのが取り回しやすい
- GUI は手動テスト（D&D、キャンセル、URL タブ、大きめファイルでの進捗の滑らかさ）

### Common Patterns
- **スレッド分離**: 変換は `threading.Thread`（multiprocessing ではない）。GUI は `tk.after(50, ...)` で `queue.Queue` を poll
- **イベント駆動**: `WorkerEvent` を dataclass で型定義（`OverallProgress` / `FileProgress` / `ItemStarted` / `ItemFinished` / `Finished` / `Failed` / `Cancelled` / `LogMessage`）
- **エラー伝播**: worker 内の例外 → `Failed` イベントにラップ → GUI 側でログ + ダイアログ表示
- **進捗の二階建て**: 全体（`done / total` 件）とファイル内（`bytes_read / total_bytes`）を別プログレスバーで描画

## Dependencies

### Internal
- `__main__.py` → `app.launch()` → `ConversionWorker` (worker.py) → `Converter` (converter.py) → `ProgressStream` (progress_stream.py)

### External
- `markitdown` — 変換の実体。`MarkItDown.convert_stream` / `convert_uri` を使用
- `customtkinter` — ダークテーマ対応 Tk ツールキット
- `tkinterdnd2` — D&D（ネイティブ tkdnd DLL に依存）
- `threading`, `queue`, `dataclasses`, `pathlib`, `urllib.parse` — 標準ライブラリ

## 注意事項
- 変換は **スレッド** ベース（`threading.Thread` + `threading.Event`）。`multiprocessing.freeze_support` や pickling 制約は関係しない
- PyInstaller でバンドルする際は `build/mdconverter.spec` が `collect_all("markitdown")` と多数の optional 依存を拾っている。依存追加時は spec の `hiddenimports` 側にも載せる必要があるケースが多い
- `__main__.py` は PyInstaller で絶対 import（`from mdconverter.app import launch`）である必要がある（相対 import だとバンドル後にクラッシュする — コミット `18cdd2e` 参照）
- **PDF 表抽出は opt-in**（`extract_tables=True`）。`Converter._convert_pdf_with_pages` 内で `pdfplumber` を追加で開き、表 bbox を使って本文と表を分離。ページ単位の `try/except` で失敗時は pypdfium2 のテキスト抽出にフォールバック。デフォルト OFF

<!-- MANUAL: -->
