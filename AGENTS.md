<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-15 | Updated: 2026-04-18 -->

# markdownconverter

## Purpose
ローカル GUI で任意の文書を Markdown に変換するツール。Microsoft の [markitdown](https://github.com/microsoft/markitdown) をラップし、CustomTkinter + tkinterdnd2 で D&D 対応の単一ウィンドウ UI を提供する。PyInstaller で単一 `.exe` にビルドして配布できる（Windows）。

## Key Files

| File | Description |
|------|-------------|
| `pyproject.toml` | パッケージメタデータ（PEP 621）／依存・optional `build` extras |
| `requirements.txt` | pin された依存リスト（pyproject と併用） |
| `README.md` | 使い方・機能説明 |
| `BUILD_WINDOWS.md` | Windows 用 `.exe` ビルド手順（PyInstaller） |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `src/mdconverter/` | メインパッケージ（GUI・変換ロジック・ワーカースレッド） — `src/AGENTS.md` 参照 |
| `build/` | PyInstaller spec（`mdconverter.spec`）と中間生成物（中間生成物は gitignore） |
| `.claude-octopus/` | Claude 関連の補助設定 — `.claude-octopus/AGENTS.md` 参照 |

配布用の `.exe` は PyInstaller が **プロジェクトルート直下** に出力します（`dist/` は使いません）。

## For AI Agents

### Working In This Directory
- **セットアップ（開発）**: `pip install -e .`（ビルド時は `pip install -e ".[build]"` で pyinstaller も入る）
- **依存インストール（pinned）**: `pip install -r requirements.txt`
- **実行**: `python -m mdconverter` — `__main__.main()` が `app.launch()` を呼び出して GUI を起動（引数なし）
- **Windows ビルド**: `pyinstaller build/mdconverter.spec --clean --noconfirm --distpath .` → `./mdconverter.exe`
- **クリーン**: `build/mdconverter/`, `mdconverter.exe` を削除してから再ビルド

### Testing Requirements
- テストスイートは未整備。追加する場合は `pytest` を想定し、変換パスは一時ディレクトリへ出力する
- GUI は手動テスト（D&D、ファイル/フォルダ/URL の各タブ、キャンセル挙動、進捗バー）
- ビルド後は別 Windows マシン（Python 未インストール）での起動確認推奨

### Common Patterns
- **GUI エントリ**: `python -m mdconverter` のみ。CLI 引数パースは持たない（CLI モードは未実装）
- **変換エンジン**: `markitdown.MarkItDown` をラップし、ファイル系は `convert_stream` + `ProgressStream` でバイト単位の進捗を取得、URL/YouTube は `convert_uri` で不定進捗
- **スレッド分離**: 変換は `ConversionWorker(threading.Thread)` が実行、GUI は `queue.Queue` を 50ms 間隔で poll して描画更新
- **キャンセル**: `threading.Event` を立て、`ProgressStream` 側が `CancelledError` を raise

## Dependencies

### Internal
- `src/mdconverter/` — 本体パッケージ

### External
- `markitdown[all]>=0.1.5` — PDF / Office / 画像 / 音声 / YouTube 等の変換を提供する本体ライブラリ
- `customtkinter>=5.2.2` — ダークテーマ対応の Tk ベース GUI ツールキット
- `tkinterdnd2>=0.4.2` — D&D 対応（ネイティブ tkdnd DLL を同梱）
- `pyinstaller>=6.6.0`（optional `[build]`） — 単一実行ファイル化

## 注意事項
- `pyproject.toml` と `requirements.txt` が並存：pyproject を正、requirements は pinned lock として扱う
- 音声変換（`.mp3`/`.wav` 等）は markitdown が内部で FFmpeg を呼ぶため、`.exe` と同じフォルダに `ffmpeg.exe` を配置するか PATH を通す必要がある
- PyInstaller ビルドではホスト Python が不要になる代わり、markitdown の隠れ import を `build/mdconverter.spec` の `hiddenimports` / `collect_all` で拾い切る必要がある（`BUILD_WINDOWS.md` §7 参照）

<!-- MANUAL: -->
