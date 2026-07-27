"""Atomic writes and a per-project lock (correction #8).

A knowledge rebuild reads the current version, derives the next one, and writes it.
Two of those interleaving would either clobber each other's write or mint the same
version number twice. For a single-process prototype an in-process lock would do,
but uvicorn's `--reload` and any future second worker make that a false sense of
safety, so the lock is on the filesystem (`fcntl.flock`) and works across processes
on the one host this runs on.

Writes themselves are made atomic with `os.replace`: the payload is written to a
temp file in the same directory and then renamed over the target, which is atomic
on POSIX. A crash mid-write therefore leaves the previous good file intact rather
than a half-written `current.json`.

`fcntl` is POSIX-only, which matches the deployment (macOS dev, Linux container).
No third-party dependency: `filelock` is not installed, and adding it would
invalidate the pip layer (see CLAUDE.md) for a lock stdlib already provides.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def project_lock(lock_file: Path) -> Iterator[None]:
    """Exclusive, cross-process lock held for the duration of the block.

    Blocking on purpose: a concurrent rebuild should wait its turn and then see the
    version the first one wrote (and, via `save_next`'s version check, re-plan on
    top of it) rather than fail. The lock file is created if missing and left in
    place — it is a rendezvous point, not data.
    """
    import fcntl

    lock_file.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_file, "w", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def atomic_write_text(path: Path, text: str) -> None:
    """Write `text` to `path` atomically via a same-directory temp + `os.replace`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def atomic_write_json(path: Path, payload) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, default=str))
