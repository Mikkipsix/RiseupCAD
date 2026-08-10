"""Geometry-aware OCR deduplication for repeated Tesseract detections."""
from __future__ import annotations


def _bbox(n):
    return (float(n.x - n.w / 2.0), float(n.y - n.h / 2.0),
            float(n.x + n.w / 2.0), float(n.y + n.h / 2.0))


def _duplicate(a, b, center_tol=20.0):
    if int(a.value) != int(b.value) or bool(a.vertical) != bool(b.vertical):
        return False
    ax0, ay0, ax1, ay1 = _bbox(a)
    bx0, by0, bx1, by1 = _bbox(b)
    ix = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0.0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    area_a = max(1.0, (ax1 - ax0) * (ay1 - ay0))
    area_b = max(1.0, (bx1 - bx0) * (by1 - by0))
    if inter / max(area_a + area_b - inter, 1.0) >= 0.20:
        return True
    dx = abs(float(a.x) - float(b.x))
    dy = abs(float(a.y) - float(b.y))
    tol_x = max(center_tol, 0.45 * max(float(a.w), float(b.w)))
    tol_y = max(center_tol, 0.45 * max(float(a.h), float(b.h)))
    return dx <= tol_x and dy <= tol_y


def dedup_numbers(numbers):
    """Keep the highest-confidence detection for each physical OCR label."""
    kept = []
    for n in sorted(numbers, key=lambda item: (-float(item.conf), float(item.y), float(item.x))):
        if any(_duplicate(n, old) for old in kept):
            continue
        kept.append(n)
    return kept
