<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-15 | Updated: 2026-04-18 -->

# src

## Purpose
markdownconverter のソースコードルート。src レイアウトを採用し、`pyproject.toml` の `[tool.setuptools.packages.find] where = ["src"]` で `mdconverter` パッケージが検出される。

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `mdconverter/` | メインパッケージ（GUI・変換ロジック・ワーカースレッド） — `mdconverter/AGENTS.md` 参照 |
| `mdconverter.egg-info/` | `pip install -e .` 時に自動生成される egg-info（gitignore） |

## For AI Agents

### Working In This Directory
- **src レイアウトの意味**: カレントディレクトリから直接 import されるのを防ぎ、インストール済みパッケージと同じ経路でテストできるようにする
- **インストール**: プロジェクトルートで `pip install -e .` → `from mdconverter import ...` で利用可能
- **egg-info**: 手動編集不要（`pip install -e` で再生成される）

### Testing Requirements
- テストスイートは未整備。`pytest` を追加する場合はプロジェクトルートで実行する
- `pyproject.toml` の optional-dependencies には現状 `build`（pyinstaller のみ）しかない。開発用依存を追加する場合は `[project.optional-dependencies]` に `dev` を新設する

### Common Patterns
- **パッケージ探索**: setuptools が `src/` 配下を自動探索（`where = ["src"]`）
- **バージョン**: `mdconverter/__init__.py` に `__version__` を定義

## Dependencies

### Internal
- `mdconverter/` — 本体

### External
- `setuptools>=68`, `wheel`（ビルド時のみ）

## 注意事項
- src レイアウト採用のため、`src/` を `sys.path` に追加しない（editable install 経由でのみ import する）
- `mdconverter.egg-info/` は gitignore 対象

<!-- MANUAL: -->
