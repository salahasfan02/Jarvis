"""Exact text extraction using Apple's Vision framework (VNRecognizeTextRequest).

This is the same OCR engine behind macOS Live Text — far more precise for
reading screen text than describing images with a multimodal LLM.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from ..ui_bridge import is_overlay_text


def _recognize(path: str) -> list[str]:
    import Quartz
    import Vision
    from Foundation import NSURL

    url = NSURL.fileURLWithPath_(path)
    source = Quartz.CGImageSourceCreateWithURL(url, None)
    if source is None:
        raise RuntimeError("could not open image")
    cg_image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    if cg_image is None:
        raise RuntimeError("could not decode image")

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(True)

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
        cg_image, None)
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(f"Vision request failed: {error}")

    lines: list[str] = []
    for observation in request.results() or []:
        candidate = observation.topCandidates_(1)
        if candidate and len(candidate) > 0:
            line = str(candidate[0].string())
            if not is_overlay_text(line):   # Jarvis's own "reading your screen" frame
                lines.append(line)
    return lines


def text_boxes(cg_image, target: str = "") -> list[tuple[str, tuple[float, float, float, float]]]:
    """OCR a CGImage, returning (line text, box) pairs. Boxes are normalized
    (x, y, w, h) with the origin at the TOP-left. When `target` appears inside
    a longer line, its box is narrowed to just those characters, so a click
    lands on "Sign in" rather than the middle of the whole toolbar line."""
    import Vision

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(False)   # UI labels aren't prose
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(f"Vision request failed: {error}")

    out = []
    want = target.lower().strip()
    for observation in request.results() or []:
        candidates = observation.topCandidates_(1)
        if not candidates:
            continue
        cand = candidates[0]
        text = str(cand.string())
        if is_overlay_text(text):
            continue
        box = observation.boundingBox()
        at = text.lower().find(want) if want else -1
        if at >= 0 and len(want) < len(text):
            sub, _ = cand.boundingBoxForRange_error_((at, len(want)), None)
            if sub is not None:
                box = sub.boundingBox()
        x, y, w, h = box.origin.x, box.origin.y, box.size.width, box.size.height
        out.append((text, (x, 1.0 - y - h, w, h)))
    return out


async def ocr_file(path: str | Path) -> str:
    """OCR an image file, returning the recognized lines joined by newlines."""
    lines = await asyncio.to_thread(_recognize, str(path))
    return "\n".join(lines)
