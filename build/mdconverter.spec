# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for mdconverter.
#
# Run from the repo root (NOT from inside the `build/` directory):
#
#     pyinstaller build/mdconverter.spec --clean --noconfirm --distpath .
#
# Output: ./mdconverter.exe (Windows) — the `--distpath .` flag redirects
# PyInstaller's default `dist/` directory to the project root so we never
# create a `dist/` folder.
#
# Notes
# -----
# * ``--onefile`` + ``--windowed`` (console=False) are configured below so the
#   generated .exe is a single file with no background console window.
# * We use ``collect_all`` / ``collect_submodules`` / ``collect_data_files``
#   from PyInstaller's hook helpers to bundle every piece markitdown and its
#   optional format plugins need at runtime. Without this, converters for
#   PDF, DOCX, PPTX, audio, etc. silently fail to load.
# * ``tkinterdnd2`` ships a native ``tkdnd`` library in a platform-specific
#   subdirectory that must be bundled as data.
# * customtkinter needs its theme JSON assets bundled.

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
)

# ---------------------------------------------------------------------- paths
# __file__ is not defined for .spec files; use SPECPATH which PyInstaller
# sets automatically.
SPEC_DIR = Path(SPECPATH).resolve()            # .../mdconverter/build
PROJECT_ROOT = SPEC_DIR.parent                  # .../mdconverter
ENTRY = str(PROJECT_ROOT / "src" / "mdconverter" / "__main__.py")
ICON = str(SPEC_DIR / "app.ico") if (SPEC_DIR / "app.ico").exists() else None

# ---------------------------------------------------------------------- data
datas = []
binaries = []
hiddenimports = []


def _extend(res):
    d, b, h = res
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)


# markitdown + optional extras
_extend(collect_all("markitdown"))

# Optional dependency packages that markitdown only imports lazily and may not
# be picked up by PyInstaller's static analysis. Add only the ones installed
# via `pip install 'markitdown[all]'`.
for pkg in (
    "magika",
    "charset_normalizer",
    "pdfminer",
    "pdfminer.six",
    "pdfplumber",
    "pypdfium2",
    "mammoth",
    "python_pptx",
    "pptx",
    "openpyxl",
    "xlrd",
    "pandas",
    "lxml",
    "bs4",
    "beautifulsoup4",
    "markdownify",
    "defusedxml",
    "olefile",
    "extract_msg",
    "speech_recognition",
    "pydub",
    "youtube_transcript_api",
    "azure.ai.documentintelligence",
    "azure.identity",
):
    try:
        _extend(collect_all(pkg))
    except Exception:
        # Not installed / not needed — skip quietly.
        pass

# GUI stack
datas += collect_data_files("customtkinter")
hiddenimports += collect_submodules("customtkinter")

datas += collect_data_files("tkinterdnd2", include_py_files=False)
# The native tkdnd library lives under tkinterdnd2/tkdnd/<platform>/*.dll|so
hiddenimports += ["tkinterdnd2", "tkinterdnd2.TkinterDnD"]

# ---------------------------------------------------------------------- build

block_cipher = None

a = Analysis(
    [ENTRY],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="mdconverter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,       # --windowed: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)
