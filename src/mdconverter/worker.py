"""Background conversion worker and GUI-safe event queue.

The GUI runs on the Tk main loop and must never block. All conversion work
runs on a :class:`ConversionWorker` thread, which reports progress by pushing
:class:`WorkerEvent` objects onto a :class:`queue.Queue`. The GUI polls the
queue with ``after(50, ...)`` and updates widgets on the Tk thread.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Union

from .converter import BatchResult, ConversionItemResult, Converter
from .progress_stream import CancelledError


# ---------------------------------------------------------------------------
# Event types pushed onto the queue


@dataclass
class OverallProgress:
    done: int
    total: int


@dataclass
class FileProgress:
    """Byte-level progress for the file currently being converted.

    When ``total`` is 0 the UI should switch to an indeterminate animation
    (used for URL / YouTube inputs whose size is unknown).
    """

    bytes_read: int
    total: int


@dataclass
class ItemStarted:
    source: str


@dataclass
class ItemFinished:
    result: ConversionItemResult


@dataclass
class LogMessage:
    level: str  # "info", "warning", "error"
    text: str


@dataclass
class Finished:
    batch: BatchResult


@dataclass
class Cancelled:
    pass


@dataclass
class Failed:
    error: str


WorkerEvent = Union[
    OverallProgress,
    FileProgress,
    ItemStarted,
    ItemFinished,
    LogMessage,
    Finished,
    Cancelled,
    Failed,
]


# ---------------------------------------------------------------------------
# Worker thread


class ConversionWorker(threading.Thread):
    """Run a batch conversion on a background thread.

    The worker owns a :class:`threading.Event` used for cancellation and a
    :class:`queue.Queue` used for GUI event delivery. Both are exposed so the
    GUI can call :meth:`cancel` and drain the queue from the Tk main loop.
    """

    def __init__(
        self,
        converter: Converter,
        sources: Sequence[Union[str, Path]],
        out_dir: Path,
    ) -> None:
        super().__init__(daemon=True, name="mdconverter-worker")
        self._converter = converter
        self._sources = list(sources)
        self._out_dir = Path(out_dir)
        self.events: "queue.Queue[WorkerEvent]" = queue.Queue()
        self.cancel_event = threading.Event()

    # ---- public control

    def cancel(self) -> None:
        self.cancel_event.set()

    # ---- thread entry point

    def run(self) -> None:
        try:
            batch = self._converter.convert_batch(
                self._sources,
                self._out_dir,
                overall_cb=self._emit_overall,
                file_cb=self._emit_file,
                on_item_start=self._emit_item_started,
                on_item_done=self._emit_item_done,
                cancel_event=self.cancel_event,
            )
        except CancelledError:
            self.events.put(Cancelled())
            return
        except Exception as exc:  # noqa: BLE001 - worker boundary
            self.events.put(
                Failed(error=f"{type(exc).__name__}: {exc}")
            )
            return

        self.events.put(Finished(batch=batch))

    # ---- callbacks (called from worker thread, forwarded via queue)

    def _emit_overall(self, done: int, total: int) -> None:
        self.events.put(OverallProgress(done=done, total=total))

    def _emit_file(self, read: int, total: int) -> None:
        self.events.put(FileProgress(bytes_read=read, total=total))

    def _emit_item_started(self, source: str) -> None:
        self.events.put(ItemStarted(source=source))
        self.events.put(
            LogMessage(level="info", text=f"変換中: {source}")
        )

    def _emit_item_done(self, result: ConversionItemResult) -> None:
        self.events.put(ItemFinished(result=result))
        if result.success:
            self.events.put(
                LogMessage(
                    level="info",
                    text=f"完了: {result.source} → {result.destination}",
                )
            )
        else:
            self.events.put(
                LogMessage(
                    level="error",
                    text=f"失敗: {result.source} ({result.error})",
                )
            )


# ---------------------------------------------------------------------------
# Queue drain helper used by the GUI


def drain_events(
    worker: ConversionWorker,
    handler: Callable[[WorkerEvent], None],
    max_per_tick: int = 64,
) -> List[WorkerEvent]:
    """Pull up to ``max_per_tick`` events off the worker queue and dispatch.

    Returns the list of events processed (useful in tests).
    """
    processed: List[WorkerEvent] = []
    for _ in range(max_per_tick):
        try:
            ev = worker.events.get_nowait()
        except queue.Empty:
            break
        handler(ev)
        processed.append(ev)
    return processed
