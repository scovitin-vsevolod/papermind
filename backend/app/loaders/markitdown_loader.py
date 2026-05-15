"""Thin wrapper around the markitdown library.

Why a wrapper:
- pins the public surface to ``to_markdown(bytes, filename) -> str``,
  so the rest of the codebase never imports markitdown directly;
- lets us swap or stack a different parser later (e.g. unstructured.io
  for harder PDFs) without touching call sites;
- centralises error handling — markitdown can raise a zoo of
  exceptions per format; we collapse them into ``LoaderError``.
"""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import PurePosixPath

from markitdown import MarkItDown, StreamInfo


class LoaderError(RuntimeError):
    """Raised when a document cannot be parsed into markdown."""


@lru_cache(maxsize=1)
def _md() -> MarkItDown:
    return MarkItDown()


def to_markdown(content: bytes, filename: str) -> str:
    """Convert raw bytes of a document into markdown text.

    The extension in ``filename`` is what markitdown uses to pick a
    converter — pass the original filename, not a sanitised one.
    """
    extension = PurePosixPath(filename).suffix.lower()
    if not extension:
        raise LoaderError(f"cannot determine format for {filename!r} — missing extension")

    stream = io.BytesIO(content)
    try:
        result = _md().convert_stream(
            stream,
            stream_info=StreamInfo(extension=extension, filename=filename),
        )
    except Exception as exc:
        raise LoaderError(f"failed to parse {filename!r}: {exc}") from exc

    text = (result.text_content or "").strip()
    if not text:
        raise LoaderError(f"{filename!r} parsed but produced empty text")
    return text
