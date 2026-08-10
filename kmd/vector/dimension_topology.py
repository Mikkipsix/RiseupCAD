# -*- coding: utf-8 -*-
"""Explain which geometry supports each recognised DIMENSION.

The topology layer is diagnostic only. It does not change pairing or
calibration. It links a refined Dim to the most plausible witness segments
using orientation, endpoint position and span consistency.
"""
from __future__ import annotations


def _coord_span(seg, vertical):
    if vertical:
        return float(seg.x1), min(float(seg.y1), float(seg.y2)), max(float(seg.y1), float(seg.y2))
    return float(seg.y1), min(float(seg.x1), float(seg.x2)), max(float(seg.x1), float(seg.x2))


def _near(value, target, tol):
    return abs(float(value) - float(target)) <= tol


def build_dimension_topology(dims, segs, scale=1.0, position_tol=6.0, span_tol=12.0):
    """Return one diagnostic record per refined dimension.

    ``object_a`` and ``object_b`` are segment indices in ``segs``.  A segment
    is considered a witness when it has the required orientation, reaches the
    dimension line, and its coordinate is close to one of the dimension ends.
    """
    out = []
    for di, d in enumerate(dims):
        vertical_dim = bool(d.vertical)
        want = "v" if vertical_dim else "h"
        line = float(d.line)
        a, b = sorted((float(d.a), float(d.b)))
        target = float(d.value) / float(scale) if scale else None
        candidates = []
        for si, s in enumerate(segs):
            if getattr(s, "kind", None) != want:
                continue
            pos, lo, hi = _coord_span(s, vertical_dim)
            if not (lo - position_tol <= line <= hi + position_tol):
                continue
            da = abs(pos - a)
            db = abs(pos - b)
            end_error = min(da, db)
            if end_error > span_tol:
                continue
            candidates.append({
                "segment": si,
                "position": round(pos, 2),
                "range": [round(lo, 2), round(hi, 2)],
                "end_error": round(end_error, 2),
                "role": getattr(s, "role", ""),
                "length": round(float(getattr(s, "length", 0.0)), 2),
            })
        candidates.sort(key=lambda x: (x["end_error"], 0 if x["role"] == "leader" else 1))
        selected = []
        used = set()
        for c in candidates:
            endpoint = "a" if abs(c["position"] - a) <= abs(c["position"] - b) else "b"
            if endpoint in used:
                continue
            used.add(endpoint)
            selected.append((endpoint, c))
            if len(selected) == 2:
                break
        object_a = next((c["segment"] for e, c in selected if e == "a"), None)
        object_b = next((c["segment"] for e, c in selected if e == "b"), None)
        span = b - a
        span_error = abs(span - target) if target is not None else None
        confidence = 0.0
        if object_a is not None:
            confidence += 0.35
        if object_b is not None:
            confidence += 0.35
        if target and target > 0:
            confidence += 0.30 * max(0.0, 1.0 - (span_error / max(target, 1e-6)))
        out.append({
            "dimension_index": di,
            "value": int(d.value),
            "orientation": "vertical" if vertical_dim else "horizontal",
            "text": {
                "x": round(float(d.num.x), 2) if d.num else None,
                "y": round(float(d.num.y), 2) if d.num else None,
                "w": round(float(d.num.w), 2) if d.num else None,
                "h": round(float(d.num.h), 2) if d.num else None,
                "confidence": round(float(d.num.conf), 1) if d.num else None,
            },
            "span_px": round(span, 2),
            "target_px": round(target, 2) if target is not None else None,
            "span_error_px": round(span_error, 2) if span_error is not None else None,
            "object_a": object_a,
            "object_b": object_b,
            "witness_candidates": candidates[:12],
            "confidence": round(confidence, 3),
        })
    return out
