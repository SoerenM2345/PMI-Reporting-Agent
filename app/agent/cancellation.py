"""Stopping work that is already running.

`POST /api/chats/{id}/messages` was a `def`, which FastAPI runs on the
threadpool. A sync threadpool handler **cannot be cancelled**: when the client
disconnects Starlette abandons the response and the thread runs to completion,
so "Stop" could only ever have hidden a deck that was still being built and
still being paid for.

So cancellation is cooperative and checked, never a thread kill. A killed thread
mid-render leaves a half-written `.pptx` on disk and a `Deliverable` saved as a
version; a checked one stops between stages with nothing persisted. The stages
are coarse on purpose — extraction, planning, narrative, render — because those
are the boundaries where the work is genuinely abandonable and where a partial
result has no meaning.

The token is passed explicitly rather than kept in a `ContextVar`, because the
work it guards runs on the threadpool and the checks have to be legible at the
call site: an invisible cancellation point is one nobody knows to preserve.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional, Protocol

log = logging.getLogger("pmi.cancellation")


class Cancelled(Exception):
    """Raised at a checkpoint when the caller has gone away.

    Caught at the turn boundary and turned into a stopped answer — never into an
    error. The user asked for this.
    """

    def __init__(self, stage: str = ""):
        super().__init__(f"cancelled during {stage}" if stage else "cancelled")
        self.stage = stage


class Cancellation(Protocol):
    def is_set(self) -> bool: ...


class Token:
    """A cancellation signal a caller can raise and a worker can check."""

    def __init__(self, source: Optional[Callable[[], bool]] = None):
        self._source = source
        self._set = False

    def cancel(self) -> None:
        self._set = True

    def is_set(self) -> bool:
        if self._set:
            return True
        if self._source is not None and self._source():
            self._set = True
        return self._set

    def check(self, stage: str = "") -> None:
        """Raise if the caller has gone away. The one line worth copying."""
        if self.is_set():
            log.info("cancelled during %s", stage or "an unnamed stage")
            raise Cancelled(stage)


class NullToken:
    """Never cancelled. The default, so no caller is forced to care."""

    def cancel(self) -> None:                              # pragma: no cover
        return

    def is_set(self) -> bool:
        return False

    def check(self, stage: str = "") -> None:
        return


NEVER = NullToken()


def check(token: Optional[Cancellation], stage: str = "") -> None:
    """Checkpoint for callers holding an optional token."""
    if token is not None and token.is_set():
        log.info("cancelled during %s", stage or "an unnamed stage")
        raise Cancelled(stage)
