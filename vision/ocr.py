"""Read on-screen text with the Windows built-in OCR engine (no model download, no network).

Blender's UI font is small, so the frame is upscaled before recognition and the boxes are mapped
back to frame pixels. Imports are lazy: off Windows, or without the `winrt-*` packages, calling
`read_text` raises `OcrUnavailable` and the rest of `vision` still works.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from shared.grounding import Rect

DEFAULT_SCALE = 2.0


class OcrUnavailable(RuntimeError):
    """Windows OCR (or its Python bindings) is not available here."""


@dataclass(frozen=True)
class Word:
    text: str
    rect: Rect          # frame pixels
    line: int           # index of the OCR line it belongs to


async def _recognize(png: bytes):
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise OcrUnavailable("no OCR language pack installed (Settings > Time & language > Language)")
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(png)
    await writer.store_async()
    await writer.flush_async()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    return await engine.recognize_async(bitmap)


def read_text(bgr, scale: float = DEFAULT_SCALE) -> list[Word]:
    """All words OCR finds in a BGR frame, with boxes in that frame's pixel coordinates."""
    try:
        import cv2
        result = asyncio.run(_recognize(cv2.imencode(
            ".png", cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC))[1].tobytes()))
    except ImportError as e:
        raise OcrUnavailable(str(e)) from e
    words: list[Word] = []
    for li, line in enumerate(result.lines):
        for w in line.words:
            b = w.bounding_rect
            words.append(Word(w.text, Rect(round(b.x / scale), round(b.y / scale),
                                           round(b.width / scale), round(b.height / scale)), li))
    return words
