"""File-like wrapper that reports read progress and supports cancellation.

markitdown performs synchronous conversion and does not expose any progress
callbacks. To provide meaningful progress for large files, we wrap the source
file in this class and pass it to ``MarkItDown.convert_stream``. Every ``read``
call updates a progress counter and invokes the caller's callback.

The progress is reported as the *maximum* byte position ever reached, which
means the progress bar stays monotonic even if markitdown (or its file-type
detector ``magika``) seeks backwards to try multiple parsers.

Implementation note: ``magika.identify_stream`` validates the input with
``isinstance(stream, io.BufferedIOBase)``, so this class subclasses
``io.BufferedIOBase`` and implements the buffered binary I/O interface.
"""

from __future__ import annotations

import io
import threading
from typing import BinaryIO, Callable, Optional


class CancelledError(Exception):
    """Raised from within :class:`ProgressStream` when the user cancels."""


ProgressCallback = Callable[[int, int], None]


class ProgressStream(io.BufferedIOBase):
    """Wrap a binary file-like object and emit progress on every ``read``.

    Parameters
    ----------
    fileobj:
        The underlying binary stream. Must support ``read``, ``seek``,
        ``tell`` and ``close``.
    total_size:
        Total size in bytes. Used as the denominator for progress.
    callback:
        Invoked as ``callback(bytes_read, total_size)`` whenever progress
        advances. May be ``None`` to disable reporting.
    cancel_event:
        Optional :class:`threading.Event`. When set, the next ``read`` call
        raises :class:`CancelledError` to abort the conversion.
    """

    def __init__(
        self,
        fileobj: BinaryIO,
        total_size: int,
        callback: Optional[ProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        super().__init__()
        self._f = fileobj
        self._total = max(int(total_size), 0)
        self._cb = callback
        self._cancel = cancel_event
        self._max_pos = 0

    # ------------------------------------------------------------------ core

    def _check_cancel(self) -> None:
        if self._cancel is not None and self._cancel.is_set():
            raise CancelledError("conversion cancelled by user")

    def _emit(self) -> None:
        if self._cb is None:
            return
        try:
            pos = self._f.tell()
        except (OSError, ValueError):
            pos = self._max_pos
        if pos > self._max_pos:
            self._max_pos = pos
        self._cb(self._max_pos, self._total)

    def read(self, size: Optional[int] = -1) -> bytes:
        self._check_cancel()
        if size is None:
            data = self._f.read()
        else:
            data = self._f.read(size)
        self._emit()
        return data

    def read1(self, size: int = -1) -> bytes:
        self._check_cancel()
        if hasattr(self._f, "read1"):
            data = self._f.read1(size)  # type: ignore[attr-defined]
        else:
            data = self._f.read(size)
        self._emit()
        return data

    def readinto(self, b) -> int:  # type: ignore[override]
        self._check_cancel()
        if hasattr(self._f, "readinto"):
            n = self._f.readinto(b)  # type: ignore[attr-defined]
        else:
            chunk = self._f.read(len(b))
            n = len(chunk)
            b[:n] = chunk
        self._emit()
        return n

    def readinto1(self, b) -> int:  # type: ignore[override]
        self._check_cancel()
        if hasattr(self._f, "readinto1"):
            n = self._f.readinto1(b)  # type: ignore[attr-defined]
        elif hasattr(self._f, "readinto"):
            n = self._f.readinto(b)  # type: ignore[attr-defined]
        else:
            chunk = self._f.read(len(b))
            n = len(chunk)
            b[:n] = chunk
        self._emit()
        return n

    # -------------------------------------------------------------- forwards

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        # Seeks should not regress the monotonic progress bar, so we
        # deliberately do not emit a progress event here.
        return self._f.seek(offset, whence)

    def tell(self) -> int:
        return self._f.tell()

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        try:
            return self._f.seekable()
        except Exception:
            return False

    def writable(self) -> bool:
        return False

    def close(self) -> None:
        # We intentionally do NOT close the underlying file here; the caller
        # (``Converter.convert_file``) opens it with a ``with`` block and
        # remains responsible for its lifetime. We only flip our own
        # ``closed`` flag via the base class so that further reads raise.
        try:
            super().close()
        except Exception:
            pass
