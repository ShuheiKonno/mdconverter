"""High-level conversion API wrapping :mod:`markitdown`.

This module defines :class:`Converter`, a thin orchestrator that:

* opens a source file, wraps it in :class:`ProgressStream`, and calls
  ``MarkItDown.convert_stream`` so the caller can display byte-level progress;
* supports URL / YouTube inputs via ``MarkItDown.convert_uri``, reporting
  indeterminate progress (byte totals are not known up-front);
* expands directories into a flat list of files and runs a batch conversion,
  reporting both per-file and overall progress.

All callbacks are plain Python callables invoked from the worker thread;
the GUI is responsible for marshalling them back to the Tk main loop.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import threading
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Union

from markitdown import MarkItDown

from .progress_stream import CancelledError, ProgressStream

log = logging.getLogger(__name__)

# Progress callback contract:
#   bytes_read:   int  — number of bytes consumed so far (0 if unknown)
#   total_bytes:  int  — total size in bytes, or 0 for indeterminate
ByteProgressCallback = Callable[[int, int], None]

# Batch callback contract:
#   done:  int — number of files finished (success or failure)
#   total: int — total number of files in this batch
BatchProgressCallback = Callable[[int, int], None]

# Log callback contract:
#   level: str — "info", "warning", or "error"
#   text:  str — human-readable message to surface in the GUI log pane.
LogCallback = Callable[[str, str], None]


# ---------------------------------------------------------------------------
# Results


@dataclass
class ConversionItemResult:
    """Outcome for a single item in a batch."""

    source: str
    destination: Optional[Path]
    success: bool
    error: Optional[str] = None


@dataclass
class BatchResult:
    items: List[ConversionItemResult] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return sum(1 for i in self.items if i.success)

    @property
    def failure_count(self) -> int:
        return sum(1 for i in self.items if not i.success)


# ---------------------------------------------------------------------------
# Main converter


class Converter:
    """Wraps :class:`markitdown.MarkItDown` with progress + cancellation."""

    def __init__(self) -> None:
        # ``enable_plugins=False`` keeps behaviour deterministic across
        # machines; users can opt-in to plugins later if desired.
        self._md = MarkItDown(enable_builtins=True, enable_plugins=False)

    # --------------------------------------------------------------- single

    def convert_file(
        self,
        src: Path,
        out_dir: Path,
        progress_cb: Optional[ByteProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
        log_cb: Optional[LogCallback] = None,
        save_images: bool = False,
        extract_tables: bool = False,
        compress_table_blanks: bool = False,
    ) -> Path:
        """Convert one local file and write the result as ``<stem>.md``.

        Returns the path of the written Markdown file. Raises
        :class:`CancelledError` if the user cancels, or any exception raised
        by markitdown on conversion failure.
        """
        src = Path(src)
        if not src.is_file():
            raise FileNotFoundError(f"file not found: {src}")

        out_dir.mkdir(parents=True, exist_ok=True)
        dst = _unique_path(out_dir / (src.stem + ".md"))

        size = src.stat().st_size
        # Signal 0/size immediately so the UI can switch to determinate mode.
        if progress_cb is not None:
            progress_cb(0, size)

        images_stem = dst.stem + "_images"
        images_dir = out_dir / images_stem

        if src.suffix.lower() == ".pdf":
            # PDFs get a custom page-by-page extraction so the output has
            # explicit "## ページ N" section markers. markitdown's built-in
            # PDF converter flattens pages into a single blob, losing the
            # only structural signal PDFs reliably carry.
            text_content = self._convert_pdf_with_pages(
                src, progress_cb, cancel_event, log_cb,
                save_images=save_images,
                images_dir=images_dir,
                images_stem=images_stem,
                extract_tables=extract_tables,
            )
        else:
            with src.open("rb") as raw:
                stream = ProgressStream(
                    raw,
                    total_size=size,
                    callback=progress_cb,
                    cancel_event=cancel_event,
                )
                result = self._md.convert_stream(
                    stream,
                    file_extension=src.suffix or None,
                    keep_data_uris=save_images,
                )
            if save_images:
                text_content = _save_images_to_folder(
                    result.text_content or "",
                    images_dir,
                    images_stem,
                )
            else:
                text_content = _strip_image_references(result.text_content or "")

            if compress_table_blanks and src.suffix.lower() in {".xlsx", ".xls", ".csv"}:
                text_content = _compress_table_blanks(text_content)

        dst.write_text(text_content, encoding="utf-8")

        # Ensure the final progress reaches 100% even if markitdown stopped
        # reading before the end of the stream.
        if progress_cb is not None:
            progress_cb(size, size)
        return dst

    # ---------------------------------------------------------------- pdf

    def _convert_pdf_with_pages(
        self,
        src: Path,
        progress_cb: Optional[ByteProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
        log_cb: Optional[LogCallback] = None,
        save_images: bool = False,
        images_dir: Optional[Path] = None,
        images_stem: Optional[str] = None,
        extract_tables: bool = False,
    ) -> str:
        """Extract a PDF page-by-page and emit ``## ページ N`` markers.

        Unlike markitdown's built-in PDF converter, which concatenates all
        page text into a single flat blob, this keeps page boundaries as
        Markdown headings so downstream consumers can see the document's
        only reliable structural signal.

        Uses ``pypdfium2`` (Google PDFium, the engine behind Chrome) because
        pdfplumber is prone to hanging on complex pages — we previously saw
        a 311-page PDF stall indefinitely mid-extraction. PDFium is an
        order of magnitude faster and far more robust on malformed content
        streams. ``log_cb`` receives per-page progress so the user can tell
        the process is alive.

        When ``extract_tables=True`` (opt-in), each page is also processed
        with pdfplumber to detect tables and emit them as Markdown tables.
        Per-page failures fall back to the pypdfium2 text path so a single
        problematic page can't take the whole document down.
        """
        # Lazy import: pypdfium2 carries a native library and we only want
        # to pay the load cost when a PDF is actually converted.
        import pypdfium2 as pdfium
        import pypdfium2.raw as pdfium_c
        from io import BytesIO

        size = src.stat().st_size

        with src.open("rb") as raw:
            # PDFium needs the whole file buffered. PDFs are typically a few
            # MB — negligible for desktop use. Progress for this phase is
            # intentionally silent (see Phase 2 for the per-page updates).
            stream = ProgressStream(
                raw,
                total_size=size,
                callback=None,
                cancel_event=cancel_event,
            )
            data = stream.read()

        plumber_pdf = None
        if extract_tables:
            try:
                import pdfplumber
                plumber_pdf = pdfplumber.open(BytesIO(data))
            except Exception as exc:  # noqa: BLE001
                if log_cb is not None:
                    log_cb(
                        "warning",
                        f"PDF: 表抽出の初期化に失敗 ({exc}) — 通常テキスト抽出のみ実行します",
                    )
                plumber_pdf = None

        chunks: List[str] = []
        img_counter = 0
        pdf = pdfium.PdfDocument(data)
        try:
            total_pages = len(pdf)
            if log_cb is not None:
                msg = f"PDF: {total_pages} ページを解析します ({src.name})"
                if plumber_pdf is not None:
                    msg += " [表抽出モード]"
                log_cb("info", msg)
            for i in range(total_pages):
                if cancel_event is not None and cancel_event.is_set():
                    raise CancelledError("conversion cancelled by user")
                if log_cb is not None:
                    log_cb(
                        "info",
                        f"  ページ {i + 1}/{total_pages} を処理中...",
                    )

                table_md_blocks: List[str] = []
                exclude_text_via_tables = False
                if plumber_pdf is not None:
                    try:
                        text_outside, table_md_blocks = _extract_page_text_and_tables(
                            plumber_pdf, i
                        )
                        exclude_text_via_tables = True
                    except Exception as exc:  # noqa: BLE001
                        if log_cb is not None:
                            log_cb(
                                "warning",
                                f"  ページ {i + 1}: 表抽出失敗 ({exc}) — テキスト抽出にフォールバック",
                            )
                        text_outside = ""
                        table_md_blocks = []
                        exclude_text_via_tables = False

                page = pdf[i]
                try:
                    if exclude_text_via_tables:
                        # pdfplumber でテキスト抽出済みのため、pypdfium2 の
                        # textpage 呼び出しは省略する
                        text = (text_outside or "").strip()
                    else:
                        textpage = page.get_textpage()
                        try:
                            text = (textpage.get_text_bounded() or "").strip()
                        finally:
                            textpage.close()

                    img_refs: List[str] = []
                    if save_images and images_dir is not None and images_stem is not None:
                        for obj in page.get_objects(
                            filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE]
                        ):
                            buf = BytesIO()
                            try:
                                obj.extract(buf, fb_format="png")
                                raw = buf.getvalue()
                                # JPEG は fb_format に関わらずそのまま返るため
                                # マジックバイトで実際のフォーマットを判定する
                                ext = "jpg" if raw[:3] == b"\xff\xd8\xff" else "png"
                                img_counter += 1
                                filename = f"image{img_counter:03d}.{ext}"
                                images_dir.mkdir(parents=True, exist_ok=True)
                                (images_dir / filename).write_bytes(raw)
                                img_refs.append(f"![]({images_stem}/{filename})")
                            except Exception:
                                pass
                finally:
                    page.close()

                page_chunk = f"## ページ {i + 1}\n\n{text}\n" if text else f"## ページ {i + 1}\n\n"
                if table_md_blocks:
                    page_chunk = (
                        page_chunk.rstrip("\n")
                        + "\n\n"
                        + "\n\n".join(table_md_blocks)
                        + "\n"
                    )
                if img_refs:
                    page_chunk = page_chunk.rstrip("\n") + "\n\n" + "\n".join(img_refs) + "\n"
                chunks.append(page_chunk)
                if progress_cb is not None and total_pages > 0:
                    progress_cb(int(size * (i + 1) / total_pages), size)
        finally:
            pdf.close()
            if plumber_pdf is not None:
                try:
                    plumber_pdf.close()
                except Exception:
                    pass

        if log_cb is not None:
            log_cb("info", f"PDF: 全 {total_pages} ページ解析完了")
        return "\n".join(chunks).rstrip() + "\n"

    # ---------------------------------------------------------------- uri

    def convert_uri(
        self,
        uri: str,
        out_dir: Path,
        progress_cb: Optional[ByteProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> Path:
        """Convert a URL / YouTube link. Progress is indeterminate."""
        out_dir.mkdir(parents=True, exist_ok=True)

        # Indeterminate: report (0, 0) so the UI flips to pulsing mode.
        if progress_cb is not None:
            progress_cb(0, 0)

        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("conversion cancelled by user")

        result = self._md.convert_uri(uri, keep_data_uris=False)

        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("conversion cancelled by user")

        dst = _unique_path(out_dir / (_slug_from_uri(uri) + ".md"))
        dst.write_text(
            _strip_image_references(result.text_content or ""),
            encoding="utf-8",
        )

        if progress_cb is not None:
            progress_cb(1, 1)
        return dst

    # ---------------------------------------------------------------- batch

    def convert_batch(
        self,
        sources: Sequence[Union[str, Path]],
        out_dir: Path,
        overall_cb: Optional[BatchProgressCallback] = None,
        file_cb: Optional[ByteProgressCallback] = None,
        on_item_start: Optional[Callable[[str], None]] = None,
        on_item_done: Optional[Callable[[ConversionItemResult], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        log_cb: Optional[LogCallback] = None,
        save_images: bool = False,
        extract_tables: bool = False,
        compress_table_blanks: bool = False,
    ) -> BatchResult:
        """Convert a mixed list of files, directories and URLs.

        Directories are expanded recursively. Each item is converted
        independently: per-item failures are recorded in the returned
        :class:`BatchResult` but do not abort the batch.
        """
        items = list(_expand_sources(sources))
        total = len(items)
        batch = BatchResult()
        done = 0

        if overall_cb is not None:
            overall_cb(0, total)

        for item in items:
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError("conversion cancelled by user")

            label = str(item)
            if on_item_start is not None:
                on_item_start(label)

            try:
                if _is_uri(item):
                    dst = self.convert_uri(
                        str(item), out_dir, file_cb, cancel_event
                    )
                else:
                    dst = self.convert_file(
                        Path(item),
                        out_dir,
                        file_cb,
                        cancel_event,
                        log_cb,
                        save_images=save_images,
                        extract_tables=extract_tables,
                        compress_table_blanks=compress_table_blanks,
                    )
                result = ConversionItemResult(
                    source=label, destination=dst, success=True
                )
            except CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - report and continue
                log.exception("conversion failed for %s", label)
                result = ConversionItemResult(
                    source=label,
                    destination=None,
                    success=False,
                    error=f"{type(exc).__name__}: {exc}",
                )

            batch.items.append(result)
            done += 1
            if overall_cb is not None:
                overall_cb(done, total)
            if on_item_done is not None:
                on_item_done(result)

        return batch


# ---------------------------------------------------------------------------
# Helpers


_URI_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")

# Matches Markdown image references that embed data URIs, whether the URI is
# the full base64 payload or the truncated placeholder markitdown produces
# with ``keep_data_uris=False`` (e.g. ``data:image/png;base64...``).
_DATA_URI_IMG_RE = re.compile(r"!\[[^\]]*\]\(\s*data:[^)]*\)")
# Matches Markdown image references whose target looks like an image file —
# either a bare placeholder emitted by markitdown (``![](Picture1.jpg)``) or
# an actual HTTP URL ending in an image extension. Both forms are useless to
# the AI-service consumers this tool targets: local placeholders are dangling
# (the image file isn't shipped alongside the .md), and remote URLs are
# ignored by Claude / ChatGPT / NotebookLM when embedded in Markdown.
# We deliberately do NOT touch regular Markdown links (``[text](url)``
# without the leading ``!``), only image references.
_FILE_IMG_RE = re.compile(
    r"!\[[^\]]*\]\([^)]*\.(?:jpg|jpeg|png|gif|webp|svg|bmp|tiff?|ico|heic)"
    r"[^)]*\)",
    re.IGNORECASE,
)
# Collapse 3+ consecutive blank lines left behind by the stripping, keeping
# the output tidy without disturbing legitimate paragraph breaks.
_EXTRA_BLANKS_RE = re.compile(r"\n{3,}")


_EXTRACT_DATA_URI_RE = re.compile(
    r"!\[([^\]]*)\]\(\s*data:([^;]+);base64,([A-Za-z0-9+/=\s]+)\)",
    re.DOTALL,
)
_MIME_TO_EXT: dict = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
    "image/bmp": "bmp",
}


def _save_images_to_folder(text: str, images_dir: Path, rel_prefix: str) -> str:
    """data URI 画像をファイルとして保存し、相対パス参照に置換する。"""
    if not text:
        return text
    counter = 0

    def replacer(m: re.Match) -> str:
        nonlocal counter
        alt, mime, data_b64 = m.group(1), m.group(2), m.group(3)
        ext = _MIME_TO_EXT.get(mime.strip().lower(), "bin")
        counter += 1
        filename = f"image{counter:03d}.{ext}"
        images_dir.mkdir(parents=True, exist_ok=True)
        try:
            (images_dir / filename).write_bytes(base64.b64decode(data_b64))
        except Exception:
            return ""
        return f"![{alt}]({rel_prefix}/{filename})"

    # 先にファイル参照プレースホルダ（Picture1.jpg等）を除去してから
    # data URI を置換する（逆順にすると新しい相対パス参照まで除去される）
    cleaned = _FILE_IMG_RE.sub("", text)
    result = _EXTRACT_DATA_URI_RE.sub(replacer, cleaned)
    return _EXTRA_BLANKS_RE.sub("\n\n", result)


def _strip_image_references(text: str) -> str:
    """Remove Markdown image markup from *text*.

    Strips both data-URI images and image-file references (local
    placeholders like ``![](Picture1.jpg)`` and remote URLs ending in an
    image extension). See the regex docstrings above for the rationale.
    """
    if not text:
        return text
    stripped = _DATA_URI_IMG_RE.sub("", text)
    stripped = _FILE_IMG_RE.sub("", stripped)
    return _EXTRA_BLANKS_RE.sub("\n\n", stripped)


# Pandas to_html() with na_rep="NaN" (default) emits literal "NaN" for empty
# cells in Excel output. Lookbehind/ahead on `|` so consecutive
# `|NaN|NaN|NaN|` sequences all match without the shared pipe blocking us.
_TABLE_NAN_CELL_RE = re.compile(r"(?<=\|)\s*NaN\s*(?=\|)")
# Blank Markdown table row: only pipes and whitespace, e.g. `|  |  |  |`.
# Requires 2+ pipes so a stray single `|` line cannot match.
_BLANK_TABLE_ROW_RE = re.compile(r"^\s*\|(?:\s*\|)+\s*$")


def _compress_table_blanks(text: str) -> str:
    """Strip ``NaN`` cells and collapse runs of blank rows in Markdown tables.

    Excel sheets imported through pandas render empty cells as the string
    ``NaN`` and frequently contain wide stretches of fully-empty rows. Both
    are pure noise for the AI consumers this tool targets and inflate token
    counts measurably on sparse spreadsheets.

    The transform is two-step:
      1. Replace any cell whose entire content is ``NaN`` with an empty cell.
      2. Walk lines and keep only the first row of each consecutive blank-row
         run.

    The header separator ``| --- | --- |`` is preserved (contains ``---``,
    not whitespace). A cell containing a substring like ``Total: NaN`` is
    untouched because the regex requires the entire cell to be ``NaN``.

    .. warning::
       This is a destructive transform: a cell whose entire value is
       literally the string ``NaN`` (e.g. scientific data, lab results) is
       indistinguishable from a pandas-emitted blank in the rendered
       Markdown and will also be cleared. The feature is therefore opt-in
       (default ``False``); callers must explicitly request it.
    """
    if not text:
        return text
    text = _TABLE_NAN_CELL_RE.sub(" ", text)
    lines = text.split("\n")
    out: List[str] = []
    in_blank_run = False
    for line in lines:
        if _BLANK_TABLE_ROW_RE.match(line):
            if in_blank_run:
                continue
            in_blank_run = True
            out.append(line)
        else:
            in_blank_run = False
            out.append(line)
    return "\n".join(out)


def _is_uri(value: Union[str, Path]) -> bool:
    if isinstance(value, Path):
        return False
    return bool(_URI_RE.match(value))


def _expand_sources(
    sources: Iterable[Union[str, Path]],
) -> Iterable[Union[str, Path]]:
    """Expand directories into individual files; pass through URLs/files."""
    for src in sources:
        if isinstance(src, str) and _is_uri(src):
            yield src
            continue
        p = Path(src)
        if p.is_dir():
            for sub in sorted(p.rglob("*")):
                if sub.is_file() and not sub.name.startswith("."):
                    yield sub
        elif p.exists():
            yield p
        else:
            # Not a file, not a directory, not a URI — forward anyway so the
            # converter can raise a clear FileNotFoundError for the batch log.
            yield p


_SLUG_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _slug_from_uri(uri: str) -> str:
    parsed = urllib.parse.urlparse(uri)
    host = (parsed.netloc or "uri").replace("www.", "")
    path = parsed.path.strip("/").replace("/", "_") or "index"
    query = parsed.query
    slug = f"{host}_{path}"
    if query:
        slug = f"{slug}_{query}"
    slug = _SLUG_SAFE.sub("-", slug).strip("-.")
    return slug[:120] or "download"


def _unique_path(path: Path) -> Path:
    """Return ``path`` unchanged, or append ``-1``, ``-2`` … until unique."""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    parent = path.parent
    i = 1
    while True:
        candidate = parent / f"{stem}-{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


# ---------------------------------------------------------------------------
# pdfplumber-based table extraction (opt-in)


def _extract_page_text_and_tables(plumber_pdf, index: int):
    """Run pdfplumber on one page and return ``(text_outside_tables, table_md_blocks)``.

    Tables are returned as Markdown strings ordered by their top-Y (reading
    order). Text inside table bounding boxes is excluded from the returned
    text so the same content is not emitted twice.
    """
    page = plumber_pdf.pages[index]
    tables = page.find_tables() or []

    if not tables:
        text = page.extract_text() or ""
        return text, []

    # bbox は (x0, top, x1, bottom)
    table_bboxes = [tuple(t.bbox) for t in tables]

    def _outside_all_tables(obj) -> bool:
        # 文字オブジェクトの中心座標で判定する。中心が表 bbox に入る文字は
        # 表セル経由で別途出力されるため、本文からは除く。
        try:
            cx = (obj["x0"] + obj["x1"]) / 2
            cy = (obj["top"] + obj["bottom"]) / 2
        except (KeyError, TypeError):
            return True
        for x0, top, x1, bottom in table_bboxes:
            if x0 <= cx <= x1 and top <= cy <= bottom:
                return False
        return True

    try:
        filtered = page.filter(_outside_all_tables)
        text_outside = filtered.extract_text() or ""
    except Exception:
        # filter がうまく動かない PDF があれば全文を残す
        text_outside = page.extract_text() or ""

    # 上から下の読み順で並べる
    sorted_tables = sorted(tables, key=lambda t: t.bbox[1])
    table_md_blocks: List[str] = []
    for t in sorted_tables:
        try:
            rows = t.extract()
        except Exception:
            continue
        md = _format_markdown_table(rows)
        if md:
            table_md_blocks.append(md)

    return text_outside, table_md_blocks


def _format_markdown_table(rows) -> str:
    """Convert a 2D list of cells (from pdfplumber ``Table.extract``) to Markdown.

    The first row is used as the header; if the table only has one row it is
    still rendered with that row as the header. ``None`` cells become empty,
    pipe characters are escaped, and embedded newlines become ``<br>``.
    """
    if not rows:
        return ""

    cleaned: List[List[str]] = []
    for row in rows:
        if row is None:
            continue
        cleaned.append([_format_table_cell(c) for c in row])

    cleaned = [r for r in cleaned if any(cell.strip() for cell in r)]
    if not cleaned:
        return ""

    n_cols = max(len(r) for r in cleaned)
    if n_cols == 0:
        return ""
    for r in cleaned:
        if len(r) < n_cols:
            r.extend([""] * (n_cols - len(r)))

    header = cleaned[0]
    body = cleaned[1:]

    lines = []
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * n_cols) + " |")
    for r in body:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def _format_table_cell(cell) -> str:
    if cell is None:
        return ""
    # 改行を <br> に変換する前に strip する。後でやると先頭/末尾の改行が
    # `<br>` になって取り除けない。
    text = str(cell).replace("\r\n", "\n").replace("\r", "\n").strip()
    text = text.replace("|", r"\|").replace("\n", "<br>")
    return text
