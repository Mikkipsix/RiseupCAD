# -*- coding: utf-8 -*-
"""Scale-aware candidate generation for short and repeated dimensions."""
from __future__ import annotations


def _candidates_v9(nb, segs, reach=9.0, min_span=4.0):
    """Return plausible dimension-line pairs, including short spans.

    The previous hard 8 px cutoff discarded genuine 100 mm dimensions whose
    expected span is about 7.8 px at the drawing's calibrated scale.  The
    minimum is deliberately small, while the later scale-aware scoring remains
    responsible for rejecting unrelated pairs.
    """
    want = "h" if nb.vertical else "v"
    if want == "h":
        cur = nb.y
        line = nb.x
    else:
        cur = nb.x
        line = nb.y

    reach_n = max(reach, 1.6 * (nb.w if nb.vertical else nb.h))
    positions = []
    for s in segs:
        if getattr(s, "kind", None) != want:
            continue
        if want == "v":
            pos, a0, a1 = s.x1, min(s.y1, s.y2), max(s.y1, s.y2)
        else:
            pos, a0, a1 = s.y1, min(s.x1, s.x2), max(s.x1, s.x2)
        if a1 - a0 < 6 or not (a0 - reach_n <= line <= a1 + reach_n):
            continue
        positions.append(round(float(pos), 1))

    positions = sorted(set(positions))
    out = []
    for i, p in enumerate(positions):
        for q in positions[i + 1:]:
            span = q - p
            if span < min_span:
                continue
            center = (p + q) / 2
            out.append({
                "a": p,
                "b": q,
                "span_px": span,
                "symmetry": abs(cur - center) / max(span, 1e-6),
                "inside": bool(p - 2 <= cur <= q + 2),
                "center_error_px": abs(cur - center),
                "line": line,
            })
    return out


def install(solve_module):
    """Replace only candidate generation; keep build/refine/calibration APIs."""
    solve_module._candidates = _candidates_v9
    solve_module.DIMENSION_SELECTION_VERSION = "v9-short-span-scale-aware"
