# Windows 用 `.exe` ビルド手順書 (VS Code 引き継ぎ用)

この文書は **Windows マシン上の VS Code** で `mdconverter` を
単一実行ファイル (`mdconverter.exe`) にビルドするための手順です。

> 現在のリポジトリ (`src/mdconverter/*`, `build/mdconverter.spec`)
> の状態でそのままビルドできます。

---

## 0. 前提環境

| 項目 | 推奨 | 備考 |
|---|---|---|
| OS | Windows 10 / 11 (x64) | ARM64 も可 |
| Python | 3.11.x (3.10–3.12 いずれでも可) | [python.org](https://www.python.org/downloads/) から MSI インストール。インストール時に **Add python.exe to PATH** を必ずチェック |
| Git | 任意 | `git clone` 用 |
| VS Code | 最新 | 拡張: "Python", "Pylance" |
| ディスク空き | 3 GB 以上 | markitdown[all] + PyInstaller bundle 用 |

---

## 1. リポジトリの取得

```powershell
# お好みの作業フォルダで
git clone <REPO_URL> mdconverter
cd mdconverter
git checkout claude/markdown-converter-tool-cyOzw
code .   # VS Code で開く
```

---

## 2. Python 仮想環境の作成と有効化

VS Code の統合ターミナル (PowerShell) で:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip wheel setuptools
```

> **PowerShell の実行ポリシーで弾かれた場合**
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`
> を一度だけ実行してください。

VS Code 左下のインタープリタ表示が `.venv` になっていることを確認。

---

## 3. 依存パッケージのインストール

```powershell
pip install -e ".[build]"
```

これで次のパッケージがまとめて入ります:

- `markitdown[all]` (PDF / Office / 画像 / 音声 / YouTube など一式)
- `customtkinter`, `tkinterdnd2` (GUI)
- `pyinstaller` (ビルド用)

> インストールは数分〜10分程度かかることがあります
> (`torch` 等の大きめ依存が含まれる場合)。

---

## 4. 動作確認 (ビルド前に必ず実行)

```powershell
python -m mdconverter
```

- ウィンドウが開けば OK
- 小さめの HTML や DOCX をドラッグ&ドロップし、出力先を指定して
  「変換開始」→ `.md` が生成されることを確認
- 大きめのファイル (数十 MB) で進捗バーが滑らかに進むことを確認
- URL タブで何かサイトを貼り付けて変換が走ることを確認

ここで例外が出る場合は GUI のまま修正 → 再実行してから次に進みます。
(ビルド後にエラーを追うより先に source で直すほうが圧倒的に速いです)

---

## 5. `.exe` のビルド

リポジトリルートで (重要: `build\` の中ではなく **ルート** から実行):

```powershell
pyinstaller build\mdconverter.spec --clean --noconfirm
```

成功すると以下が生成されます:

```
dist\mdconverter.exe        ← 配布物 (単一ファイル)
build\mdconverter\          ← 中間生成物 (無視して可)
```

---

## 6. 生成された `.exe` の確認

```powershell
.\dist\mdconverter.exe
```

- 別の Windows マシン (Python 未インストール) でも動くかを確認すると
  なお安心です
- コマンドプロンプトが一瞬でも開いてしまう場合は
  `build/mdconverter.spec` の `console=False` が効いているか再確認

---

## 7. トラブルシューティング

### 7.1 `ModuleNotFoundError: No module named 'xxxx'` が起動時に出る

PyInstaller が隠れた import を拾えていません。
`build/mdconverter.spec` の末尾付近の `hiddenimports` リストに追加:

```python
hiddenimports += ["xxxx", "xxxx.submodule"]
```

その後もう一度 `pyinstaller build\mdconverter.spec --clean --noconfirm`。

### 7.2 customtkinter のテーマが真っ黒/崩れる

```python
datas += collect_data_files("customtkinter")
```
が効いているかを確認。spec にはすでに含まれています。
それでもダメなら `pyinstaller --collect-data customtkinter …` を追加。

### 7.3 ドラッグ&ドロップが効かない

`tkinterdnd2` のネイティブ `tkdnd` DLL が同梱されていない可能性。
spec では `collect_data_files("tkinterdnd2", include_py_files=False)` で
取得しています。うまく拾われない場合は手動で:

```python
datas += [
    (
        r".\.venv\Lib\site-packages\tkinterdnd2\tkdnd",
        r"tkinterdnd2\tkdnd",
    ),
]
```

を `datas` に追記してください (venv パスは環境に合わせて調整)。

### 7.4 音声ファイルを変換したい (`.mp3` / `.wav` など)

`markitdown` の音声変換は内部的に [FFmpeg](https://ffmpeg.org/) を使います。
ビルド後の `.exe` と一緒に `ffmpeg.exe` を配置し、PATH を通すか、
`.exe` と同じフォルダに置いてください。

より堅牢にしたい場合は spec の `binaries` に `ffmpeg.exe` を同梱します:

```python
binaries += [(r"C:\path\to\ffmpeg.exe", ".")]
```

### 7.5 PDF 変換で PdfMiner のエラー

`pdfminer.six` が `collect_all("pdfminer")` で拾われているか確認。
明示的に以下を spec の `hiddenimports` に足してもよい:

```python
hiddenimports += [
    "pdfminer", "pdfminer.high_level", "pdfminer.layout",
    "pdfminer.pdfparser", "pdfminer.pdfdocument",
]
```

### 7.6 アンチウィルスに誤検知される

PyInstaller で作った `.exe` は署名が無いと Windows Defender /
SmartScreen に止められることがあります。配布時は:

- コード署名証明書で署名する (推奨)
- もしくは配布先にスクリーンショット付きで手順を添える

### 7.7 ビルドが終わらない / 巨大になる

`markitdown[all]` は多くのオプション依存を引き込むため、用途に応じて
`pyproject.toml` の依存を絞ると軽くなります。例:

```toml
dependencies = [
    "markitdown[pdf,docx,pptx,xlsx]>=0.1.5",
    "customtkinter>=5.2.2",
    "tkinterdnd2>=0.4.2",
]
```

---

## 8. 配布

`dist\mdconverter.exe` を ZIP に入れて配布するか、GitHub Releases
にアップロードします。単一ファイルなのでインストーラは不要です。

```powershell
Compress-Archive -Path dist\mdconverter.exe -DestinationPath mdconverter-win-x64.zip
```

---

## 付録: よく使うコマンドまとめ

```powershell
# 仮想環境
.\.venv\Scripts\Activate.ps1

# 依存再インストール
pip install -e ".[build]"

# 開発実行
python -m mdconverter

# クリーンビルド
pyinstaller build\mdconverter.spec --clean --noconfirm

# キャッシュも含めて完全クリーン
Remove-Item -Recurse -Force build\build, build\mdconverter, dist -ErrorAction SilentlyContinue
pyinstaller build\mdconverter.spec --clean --noconfirm
```
