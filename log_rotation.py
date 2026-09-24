"""Bounded UTF-8 log streams for the controller launchers."""

from __future__ import annotations

import os
import threading
from pathlib import Path

MAX_LOG_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5


class RotatingTextStream:
    def __init__(
        self,
        path: str | Path,
        *,
        max_bytes: int = MAX_LOG_BYTES,
        backup_count: int = BACKUP_COUNT,
    ) -> None:
        if max_bytes < 4:
            raise ValueError("max_bytes must be at least 4")
        if backup_count < 0:
            raise ValueError("backup_count cannot be negative")

        self.path = Path(path)
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._stream = self.path.open("ab")
        self._size = self.path.stat().st_size
        if self._size >= self.max_bytes:
            self._rollover()

    @property
    def encoding(self) -> str:
        return "utf-8"

    @property
    def errors(self) -> str:
        return "replace"

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        return False

    def write(self, text: str) -> int:
        if not isinstance(text, str):
            raise TypeError("log stream accepts text only")

        with self._lock:
            for character in text:
                encoded = character.encode(self.encoding, self.errors)
                if self._size + len(encoded) > self.max_bytes:
                    self._rollover()
                self._stream.write(encoded)
                self._size += len(encoded)
            self._stream.flush()
        return len(text)

    def flush(self) -> None:
        with self._lock:
            if not self._stream.closed:
                self._stream.flush()

    def close(self) -> None:
        with self._lock:
            if not self._stream.closed:
                self._stream.flush()
                self._stream.close()

    def _rollover(self) -> None:
        self._stream.flush()
        self._stream.close()

        prefix = f"{self.path.name}."
        for candidate in self.path.parent.iterdir():
            suffix = (
                candidate.name[len(prefix) :]
                if candidate.name.startswith(prefix)
                else ""
            )
            if suffix.isdigit() and int(suffix) > self.backup_count:
                candidate.unlink()

        if self.backup_count == 0:
            self.path.write_bytes(b"")
        else:
            oldest = self._backup_path(self.backup_count)
            if oldest.exists():
                oldest.unlink()
            for index in range(self.backup_count - 1, 0, -1):
                source = self._backup_path(index)
                if source.exists():
                    os.replace(source, self._backup_path(index + 1))
            if self.path.exists():
                os.replace(self.path, self._backup_path(1))

        self._stream = self.path.open("ab")
        self._size = 0

    def _backup_path(self, index: int) -> Path:
        return self.path.with_name(f"{self.path.name}.{index}")
