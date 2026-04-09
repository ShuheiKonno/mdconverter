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
            )

        dst.write_text(result.text_content or "", encoding="utf-8")

        # Ensure the final progress reaches 100% even if markitdown stopped
        # reading before the end of the stream.
        if progress_cb is not None:
            progress_cb(size, size)
        return dst

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

        result = self._md.convert_uri(uri)

        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("conversion cancelled by user")

        dst = _unique_path(out_dir / (_slug_from_uri(uri) + ".md"))
        dst.write_text(result.text_content or "", encoding="utf-8")

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
                        Path(item), out_dir, file_cb, cancel_event
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
