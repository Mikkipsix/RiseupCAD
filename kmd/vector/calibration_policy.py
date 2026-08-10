# -*- coding: utf-8 -*-
"""Calibration policy used by the raster vectorization package.

The raw pairing stage can produce plausible false dimensions. Calibration
should prefer a coherent scale supported by substantial dimensional evidence,
while repeated values remain a useful tie-breaker rather than the primary
criterion.
"""
from __future__ import annotations

import math
from collections import Counter
from statistics import median


def calibrate_with_repeat_support(solve_module, dims, rel_tol=0.05, allow_single=True):
    """Calibrate using coherent ratio clusters with robust size support.

    A cluster is evaluated by its median dimension value first, then by the
    number of supporting measurements and repeated-value evidence. This avoids
    letting three identical tiny OCR dimensions determine the global scale when
    several much larger dimensions independently support another coherent scale.
    No drawing-specific dimension values are embedded here.
    """
    if not dims:
        return None
    if len(dims) == 1:
        return solve_module.calibrate(dims, rel_tol=rel_tol, allow_single=allow_single)

    ks = [(d, d.value / (d.b - d.a)) for d in dims if d.b > d.a]
    if not ks:
        return None

    best = None
    for _, k0 in ks:
        inl = [(d, k) for d, k in ks if abs(k - k0) <= k0 * rel_tol]
        if len(inl) < 2:
            continue
        values = [float(d.value) for d, _ in inl]
        counts = Counter(int(d.value) for d, _ in inl)
        repeated = sum(max(0, n - 1) for n in counts.values())
        # Robustly prefer clusters representing the larger drawing geometry.
        # Median avoids one isolated huge OCR value dominating the decision.
        median_value = median(values)
        total_log = sum(math.log1p(v) for v in values)
        score = (median_value, len(inl), repeated, total_log)
        if best is None or score > best[0]:
            best = (score, inl)

    if best is None:
        return None

    inl = best[1]
    num = sum(d.value * (d.b - d.a) for d, _ in inl)
    den = sum((d.b - d.a) ** 2 for d, _ in inl)
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
        for d, _ in inl
    ]
    matches.sort(key=lambda m: -m["value"])
    rms = math.sqrt(sum(m["resid"] ** 2 for m in matches) / len(matches))
    used = {id(d) for d, _ in inl}
    return {
        "scale": scale,
        "matches": matches,
        "rms": round(rms, 2),
        "n": len(matches),
        "used": used,
        "rejected": sorted({d.value for d in dims if id(d) not in used}),
        "policy": "repeat-supported-cluster",
    }


def install(solve_module):
    """Install the policy without changing the public solve.calibrate API."""
    if getattr(solve_module, "_repeat_policy_installed", False):
        return
    original = solve_module.calibrate

    def calibrate(dims, rel_tol=0.05, allow_single=True):
        if len(dims) <= 1:
            return original(dims, rel_tol=rel_tol, allow_single=allow_single)
        return calibrate_with_repeat_support(
            solve_module, dims, rel_tol=rel_tol, allow_single=allow_single
        )

    solve_module.calibrate = calibrate
    solve_module._repeat_policy_installed = True
