# -*- coding: utf-8 -*-
"""Robust calibration policy for dimension pairing.

The pairing stage may start with an imperfect provisional scale. Calibration
therefore bootstraps from coherent large/repeated dimension anchors. Small
one-off OCR values can be geometrically plausible and even lie on the same
scale, but they must not be allowed to define the final calibration cluster.
"""
from __future__ import annotations

import math
from collections import Counter


def _dedupe_dims(dims):
    """Collapse repeated OCR detections of the same dimension label."""
    out = []
    for d in dims:
        if d.num is None:
            out.append(d)
            continue
        duplicate = False
        for prev in out:
            if prev.num is None:
                continue
            if int(prev.value) != int(d.value) or bool(prev.vertical) != bool(d.vertical):
                continue
            dx = float(prev.num.x) - float(d.num.x)
            dy = float(prev.num.y) - float(d.num.y)
            distance = math.hypot(dx, dy)
            if distance <= max(20.0, 0.45 * max(prev.num.w, prev.num.h, d.num.w, d.num.h)):
                duplicate = True
                break
        if not duplicate:
            out.append(d)
    return out


def calibrate_with_repeat_support(solve_module, dims, rel_tol=0.05, allow_single=True):
    """Calibrate from repeated/large anchors, not every plausible OCR value.

    A real drawing may contain a false OCR value whose paired span happens to
    produce exactly the same mm/px ratio as the real dimensions.  Treating
    every inlier equally therefore lets a one-off false positive become part
    of the calibration cluster. Repeated dimension values are stronger
    evidence; the largest dimension is retained as a second anchor when it
    is unique.
    """
    if not dims:
        return None
    if len(dims) == 1:
        return solve_module.calibrate(dims, rel_tol=rel_tol, allow_single=allow_single)

    work = _dedupe_dims(dims)
    ratios = [(d, d.value / (d.b - d.a)) for d in work if d.b > d.a]
    if not ratios:
        return None

    counts = Counter(int(d.value) for d, _ in ratios)
    repeated_values = {value for value, count in counts.items() if count >= 2}
    max_value = max(int(d.value) for d, _ in ratios)
    anchor_values = repeated_values | {max_value}

    best = None
    for _, k0 in ratios:
        inl = [(d, k) for d, k in ratios
               if abs(k - k0) <= max(k0 * rel_tol, 0.15)]
        if len(inl) < 2:
            continue
        anchors = [(d, k) for d, k in inl if int(d.value) in anchor_values]
        if len(anchors) < 2:
            continue
        # Anchor support is primary. Total inliers are only a secondary
        # criterion because small one-off false positives can be in-scale.
        anchor_log = sum(math.log1p(max(1, int(d.value))) for d, _ in anchors)
        total_log = sum(math.log1p(max(1, int(d.value))) for d, _ in inl)
        score = (len(anchors), anchor_log, len(inl), total_log, max(int(d.value) for d, _ in anchors))
        if best is None or score > best[0]:
            best = (score, anchors, inl)

    if best is None:
        return None

    anchors = best[1]
    num = sum(d.value * (d.b - d.a) for d, _ in anchors)
    den = sum((d.b - d.a) ** 2 for d, _ in anchors)
    if not den:
        return None
    scale = num / den

    matches = [
        {
            "value": d.value,
            "px": round(d.b - d.a, 1),
            "mm": round((d.b - d.a) * scale, 1),
            "resid": round((d.b - d.a) * scale - d.value, 1),
        }
        for d, _ in anchors
    ]
    matches.sort(key=lambda m: (-m["value"], m["px"]))
    rms = math.sqrt(sum(m["resid"] ** 2 for m in matches) / len(matches))
    used = {id(d) for d, _ in anchors}
    return {
        "scale": scale,
        "matches": matches,
        "rms": round(rms, 2),
        "n": len(matches),
        "used": used,
        "rejected": sorted({d.value for d in dims if id(d) not in used}),
        "policy": "anchor-repeat-large",
    }


def install(solve_module):
    """Install the policy without changing the public solve.calibrate API."""
    if getattr(solve_module, "_dense_policy_installed", False):
        return
    original = solve_module.calibrate

    def calibrate(dims, rel_tol=0.05, allow_single=True):
        if len(dims) <= 1:
            return original(dims, rel_tol=rel_tol, allow_single=allow_single)
        return calibrate_with_repeat_support(
            solve_module, dims, rel_tol=rel_tol, allow_single=allow_single
        )

    solve_module.calibrate = calibrate
    solve_module._dense_policy_installed = True
