"""CustomTkinter GUI for the mdconverter tool.

Layout (single resizable window):

    ┌──────────────────────────────────────────────────────────────┐
    │  [ ファイル/フォルダ ] [ URL / YouTube ]            ← tabs    │
    ├──────────────────────────────────────────────────────────────┤
    │  <drop zone + selected list>                                 │
    │  [ ファイル追加 ] [ フォルダ追加 ] [ クリア ]                 │
    ├──────────────────────────────────────────────────────────────┤
    │  出力先: [________________________] [ 参照 ]                 │
    ├──────────────────────────────────────────────────────────────┤
    │  [ 変換開始 ]  [ キャンセル ]                                │
    ├──────────────────────────────────────────────────────────────┤
    │  全体:   ▓▓▓▓▓▓▓░░░░░  2 / 5 件                               │
    │  ファイル: ▓▓▓▓░░░░░░░   4.2 / 12.8 MB                        │
    ├──────────────────────────────────────────────────────────────┤
    │  <log textbox>                                                │
    └──────────────────────────────────────────────────────────────┘

All conversion work runs on a :class:`ConversionWorker` background thread;
the GUI polls its event queue every 50ms via :meth:`after` and updates
widgets on the Tk main loop.
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import List, Optional

import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD

from .converter import Converter
from .worker import (
    Cancelled,
    ConversionWorker,
    Failed,
    FileProgress,
    Finished,
    ItemFinished,
    ItemStarted,
    LogMessage,
    OverallProgress,
    drain_events,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tk root that combines CustomTkinter's CTk with TkinterDnD's DnDWrapper.


class _DnDCTk(ctk.CTk, TkinterDnD.DnDWrapper):
    """CTk root that has tkdnd loaded so children can drop_target_register()."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        try:
            self.TkdndVersion = TkinterDnD._require(self)
        except Exception as exc:  # noqa: BLE001 - GUI should still launch
            log.warning("tkdnd load failed, drag-and-drop disabled: %s", exc)
            self.TkdndVersion = None


# ---------------------------------------------------------------------------
# Main application


class MdConverterApp:
    POLL_INTERVAL_MS = 50

    def __init__(self) -> None:
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.root = _DnDCTk()
        self.root.title("mdconverter - Markdown Converter")
        self.root.geometry("820x640")
        self.root.minsize(720, 540)

        self.converter = Converter()
        self.worker: Optional[ConversionWorker] = None

        self._sources: List[str] = []
        self._output_dir: Path = Path.home() / "mdconverter_output"

        self._build_ui()
        self._register_drop_targets()
        self._refresh_source_list()
        self._set_running(False)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = self.root
        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(5, weight=1)

        # --- Tabs --------------------------------------------------------
        self.tabs = ctk.CTkTabview(root, height=230)
        self.tabs.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 6))
        self.tabs.add("ファイル / フォルダ")
        self.tabs.add("URL / YouTube")

        self._build_file_tab(self.tabs.tab("ファイル / フォルダ"))
        self._build_url_tab(self.tabs.tab("URL / YouTube"))

        # --- Output dir --------------------------------------------------
        out_frame = ctk.CTkFrame(root)
        out_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        out_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(out_frame, text="出力先:").grid(
            row=0, column=0, padx=(12, 6), pady=10
        )
        self.out_entry = ctk.CTkEntry(out_frame)
        self.out_entry.grid(row=0, column=1, sticky="ew", padx=6, pady=10)
        self.out_entry.insert(0, str(self._output_dir))
        ctk.CTkButton(
            out_frame, text="参照", width=80, command=self._on_pick_output
        ).grid(row=0, column=2, padx=(6, 12), pady=10)

        # --- Buttons -----------------------------------------------------
        btn_frame = ctk.CTkFrame(root, fg_color="transparent")
        btn_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 6))
        btn_frame.grid_columnconfigure(2, weight=1)

        self.start_btn = ctk.CTkButton(
            btn_frame, text="変換開始", width=140, command=self._on_start
        )
        self.start_btn.grid(row=0, column=0, padx=(0, 8))

        self.cancel_btn = ctk.CTkButton(
            btn_frame,
            text="キャンセル",
            width=120,
            fg_color="#b23a3a",
            hover_color="#8a2a2a",
            command=self._on_cancel,
        )
        self.cancel_btn.grid(row=0, column=1, padx=(0, 8))

        self.status_label = ctk.CTkLabel(btn_frame, text="待機中", anchor="w")
        self.status_label.grid(row=0, column=2, sticky="ew", padx=(8, 0))

        # --- Progress ----------------------------------------------------
        prog_frame = ctk.CTkFrame(root)
        prog_frame.grid(row=3, column=0, sticky="ew", padx=12, pady=6)
        prog_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(prog_frame, text="全体:", width=70, anchor="e").grid(
            row=0, column=0, padx=(12, 6), pady=(10, 4)
        )
        self.overall_bar = ctk.CTkProgressBar(prog_frame)
        self.overall_bar.grid(row=0, column=1, sticky="ew", padx=6, pady=(10, 4))
        self.overall_bar.set(0)
        self.overall_label = ctk.CTkLabel(prog_frame, text="0 / 0", width=120)
        self.overall_label.grid(row=0, column=2, padx=(6, 12), pady=(10, 4))

        ctk.CTkLabel(prog_frame, text="ファイル:", width=70, anchor="e").grid(
            row=1, column=0, padx=(12, 6), pady=(4, 10)
        )
        self.file_bar = ctk.CTkProgressBar(prog_frame)
        self.file_bar.grid(row=1, column=1, sticky="ew", padx=6, pady=(4, 10))
        self.file_bar.set(0)
        self.file_label = ctk.CTkLabel(prog_frame, text="-", width=120)
        self.file_label.grid(row=1, column=2, padx=(6, 12), pady=(4, 10))

        # --- Log ---------------------------------------------------------
        ctk.CTkLabel(root, text="ログ:", anchor="w").grid(
            row=4, column=0, sticky="w", padx=16, pady=(6, 0)
        )
        self.log_box = ctk.CTkTextbox(root, height=160)
        self.log_box.grid(row=5, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.log_box.configure(state="disabled")

    def _build_file_tab(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        self.source_box = ctk.CTkTextbox(
            parent,
            wrap="none",
            activate_scrollbars=True,
            fg_color=("#f4f4f4", "#2b2b2b"),
        )
        self.source_box.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.source_box.configure(state="disabled")

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        row.grid_columnconfigure(3, weight=1)

        ctk.CTkButton(
            row, text="ファイル追加", width=120, command=self._on_add_files
        ).grid(row=0, column=0, padx=(0, 6))
        ctk.CTkButton(
            row, text="フォルダ追加", width=120, command=self._on_add_folder
        ).grid(row=0, column=1, padx=(0, 6))
        ctk.CTkButton(
            row, text="クリア", width=80, command=self._on_clear_sources
        ).grid(row=0, column=2, padx=(0, 6))

        self.drop_hint = ctk.CTkLabel(
            row,
            text="  (ここにファイル/フォルダをドラッグ&ドロップ可)",
            anchor="w",
            text_color=("gray40", "gray70"),
        )
        self.drop_hint.grid(row=0, column=3, sticky="ew", padx=(6, 0))

    def _build_url_tab(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            parent,
            text="変換するURLまたはYouTubeリンクを入力してください:",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(16, 6))

        self.url_entry = ctk.CTkEntry(
            parent, placeholder_text="https://example.com/article"
        )
        self.url_entry.grid(row=1, column=0, sticky="ew", padx=12, pady=6)

        ctk.CTkLabel(
            parent,
            text="※ URL変換中はバイト進捗が取得できないため、進捗バーはアニメーション表示になります。",
            anchor="w",
            text_color=("gray40", "gray70"),
        ).grid(row=2, column=0, sticky="ew", padx=12, pady=(12, 6))

    # ----------------------------------------------------------- drop targets

    def _register_drop_targets(self) -> None:
        if getattr(self.root, "TkdndVersion", None) is None:
            return
        # Register on the root window so drops anywhere are accepted.
        try:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)
        except Exception as exc:  # noqa: BLE001
            log.warning("failed to register drop target: %s", exc)

    def _on_drop(self, event) -> None:
        # event.data is a Tcl list of file paths; parse via tk.splitlist.
        try:
            paths = self.root.tk.splitlist(event.data)
        except Exception:
            paths = [p.strip("{}") for p in str(event.data).split()]
        added = 0
        for p in paths:
            if p and p not in self._sources:
                self._sources.append(p)
                added += 1
        if added:
            self._refresh_source_list()
            self._log_info(f"{added} 件追加しました (ドラッグ&ドロップ)")
            # Switch to the file tab so the user can see the result.
            try:
                self.tabs.set("ファイル / フォルダ")
            except Exception:
                pass

    # -------------------------------------------------------------- actions

    def _on_add_files(self) -> None:
        paths = filedialog.askopenfilenames(title="変換するファイルを選択")
        for p in paths:
            if p not in self._sources:
                self._sources.append(p)
        self._refresh_source_list()

    def _on_add_folder(self) -> None:
        path = filedialog.askdirectory(title="変換するフォルダを選択")
        if path and path not in self._sources:
            self._sources.append(path)
            self._refresh_source_list()

    def _on_clear_sources(self) -> None:
        self._sources.clear()
        self._refresh_source_list()

    def _on_pick_output(self) -> None:
        path = filedialog.askdirectory(title="出力先フォルダを選択")
        if path:
            self._output_dir = Path(path)
            self.out_entry.delete(0, "end")
            self.out_entry.insert(0, str(self._output_dir))

    def _on_start(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            return

        out_dir_text = self.out_entry.get().strip()
        if not out_dir_text:
            messagebox.showwarning("出力先未指定", "出力先フォルダを指定してください。")
            return
        out_dir = Path(os.path.expanduser(out_dir_text))

        # Collect sources depending on the active tab.
        sources: List[str] = []
        current_tab = self.tabs.get()
        if current_tab.startswith("URL"):
            url = self.url_entry.get().strip()
            if not url:
                messagebox.showwarning("URL未入力", "URLを入力してください。")
                return
            sources = [url]
        else:
            sources = list(self._sources)
            if not sources:
                messagebox.showwarning(
                    "入力なし",
                    "変換するファイル・フォルダを追加してください。",
                )
                return

        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(
                "出力先エラー", f"出力先を作成できません:\n{exc}"
            )
            return

        self._reset_progress()
        self._log_info(f"変換を開始します ({len(sources)} 件)")
        self.worker = ConversionWorker(self.converter, sources, out_dir)
        self.worker.start()
        self._set_running(True)
        self.root.after(self.POLL_INTERVAL_MS, self._poll_worker)

    def _on_cancel(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            self.worker.cancel()
            self._log_warn("キャンセル要求を送信しました")
            self.status_label.configure(text="キャンセル中…")

    # --------------------------------------------------------------- polling

    def _poll_worker(self) -> None:
        worker = self.worker
        if worker is None:
            return
        drain_events(worker, self._handle_event)
        if worker.is_alive():
            self.root.after(self.POLL_INTERVAL_MS, self._poll_worker)
        else:
            # Drain any final events that arrived after the last tick.
            drain_events(worker, self._handle_event)
            self._set_running(False)
            self.worker = None

    def _handle_event(self, event) -> None:
        if isinstance(event, OverallProgress):
            self._on_overall(event.done, event.total)
        elif isinstance(event, FileProgress):
            self._on_file_progress(event.bytes_read, event.total)
        elif isinstance(event, ItemStarted):
            self.status_label.configure(
                text=f"変換中: {_shorten(event.source)}"
            )
        elif isinstance(event, ItemFinished):
            pass  # handled via LogMessage emitted by worker
        elif isinstance(event, LogMessage):
            if event.level == "error":
                self._log_error(event.text)
            elif event.level == "warning":
                self._log_warn(event.text)
            else:
                self._log_info(event.text)
        elif isinstance(event, Finished):
            batch = event.batch
            self.status_label.configure(
                text=f"完了 ({batch.success_count} 成功 / {batch.failure_count} 失敗)"
            )
            self._log_info(
                f"=== 変換完了: {batch.success_count} 件成功, "
                f"{batch.failure_count} 件失敗 ==="
            )
            try:
                self.file_bar.stop()
            except Exception:
                pass
            self.file_bar.configure(mode="determinate")
            self.file_bar.set(1.0)
        elif isinstance(event, Cancelled):
            self.status_label.configure(text="キャンセルされました")
            self._log_warn("変換がキャンセルされました")
            try:
                self.file_bar.stop()
            except Exception:
                pass
        elif isinstance(event, Failed):
            self.status_label.configure(text="エラー")
            self._log_error(f"変換失敗: {event.error}")
            try:
                self.file_bar.stop()
            except Exception:
                pass

    # ------------------------------------------------------------- progress

    def _reset_progress(self) -> None:
        self.overall_bar.configure(mode="determinate")
        self.overall_bar.set(0)
        self.overall_label.configure(text="0 / 0")
        try:
            self.file_bar.stop()
        except Exception:
            pass
        self.file_bar.configure(mode="determinate")
        self.file_bar.set(0)
        self.file_label.configure(text="-")

    def _on_overall(self, done: int, total: int) -> None:
        frac = (done / total) if total else 0
        self.overall_bar.set(max(0.0, min(1.0, frac)))
        self.overall_label.configure(text=f"{done} / {total} 件")

    def _on_file_progress(self, read: int, total: int) -> None:
        if total <= 0:
            # Indeterminate mode (URL/YouTube or unknown total)
            try:
                if str(self.file_bar.cget("mode")) != "indeterminate":
                    self.file_bar.configure(mode="indeterminate")
                    self.file_bar.start()
            except Exception:
                self.file_bar.configure(mode="indeterminate")
                self.file_bar.start()
            self.file_label.configure(text="処理中…")
            return

        # Determinate mode — switch back if we were pulsing.
        try:
            if str(self.file_bar.cget("mode")) != "determinate":
                self.file_bar.stop()
                self.file_bar.configure(mode="determinate")
        except Exception:
            self.file_bar.configure(mode="determinate")

        frac = read / total if total else 0
        self.file_bar.set(max(0.0, min(1.0, frac)))
        self.file_label.configure(
            text=f"{_fmt_size(read)} / {_fmt_size(total)}"
        )

    # ------------------------------------------------------------- helpers

    def _set_running(self, running: bool) -> None:
        if running:
            self.start_btn.configure(state="disabled")
            self.cancel_btn.configure(state="normal")
        else:
            self.start_btn.configure(state="normal")
            self.cancel_btn.configure(state="disabled")

    def _refresh_source_list(self) -> None:
        self.source_box.configure(state="normal")
        self.source_box.delete("1.0", "end")
        if not self._sources:
            self.source_box.insert(
                "1.0",
                "ここにファイルやフォルダをドラッグ&ドロップ、\n"
                "または下のボタンから追加してください。\n",
            )
        else:
            for i, src in enumerate(self._sources, 1):
                self.source_box.insert("end", f"{i}. {src}\n")
        self.source_box.configure(state="disabled")

    def _log(self, tag: str, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{tag}] {text}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _log_info(self, text: str) -> None:
        self._log("INFO", text)

    def _log_warn(self, text: str) -> None:
        self._log("WARN", text)

    def _log_error(self, text: str) -> None:
        self._log("ERROR", text)

    # ------------------------------------------------------------------ run

    def run(self) -> None:
        self.root.mainloop()


# ---------------------------------------------------------------------------
# Formatting helpers


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            if unit == "B":
                return f"{n} {unit}"
            return f"{n:.1f} {unit}"
        n = n / 1024  # type: ignore[assignment]
    return f"{n} B"


def _shorten(text: str, width: int = 60) -> str:
    if len(text) <= width:
        return text
    return "…" + text[-(width - 1):]


# ---------------------------------------------------------------------------
# Entry point


def launch() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        app = MdConverterApp()
        app.run()
        return 0
    except Exception:  # noqa: BLE001 - top-level guard
        traceback.print_exc()
        try:
            messagebox.showerror(
                "起動エラー",
                "mdconverter の起動に失敗しました。\n詳細はコンソールを確認してください。",
            )
        except Exception:
            pass
        return 1
