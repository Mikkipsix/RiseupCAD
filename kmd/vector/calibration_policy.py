# -*- coding: utf-8 -*-
"""Robust calibration policy for dimension pairing.

The pairing stage may start with an imperfect provisional scale. Calibration
therefore bootstraps from a dense cluster of value/span ratios. Repetition and
large dimensions are tie-breakers, not the primary criterion.
"""
from __future__ import annotations

import math
from collections import Counter


def calibrate_with_repeat_support(solve_module, dims, rel_tol=0.05, allow_single=True):
    """Bootstrap calibration from the densest coherent value/span cluster."""
    if not dims:
        return None
    if len(dims) == 1:
        return solve_module.calibrate(dims, rel_tol=rel_tol, allow_single=allow_single)

    ratios = [(d, d.value / (d.b - d.a)) for d in dims if d.b > d.a]
    if not ratios:
        return None

    best = None
    for _, k0 in ratios:
        inl = [(d, k) for d, k in ratios if abs(k - k0) <= max(k0 * rel_tol, 0.15)]
        if len(inl) < 2:
            continue
        values = [int(d.value) for d, _ in inl]
        counts = Counter(values)
        repeated = sum(max(0, n - 1) for n in counts.values())
        # Primary criterion: how many independent measurements support this
        # scale. Only then use dimensional magnitude/repetition as tie-breakers.
        total_log = sum(math.log1p(max(1, v)) for v in values)
        max_value = max(values)
        score = (len(inl), total_log, max_value, repeated)
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
    matches.sort(key=lambda m: (-m["value"], m["px"]))
    rms = math.sqrt(sum(m["resid"] ** 2 for m in matches) / len(matches))
    used = {id(d) for d, _ in inl}
    return {
        "scale": scale,
        "matches": matches,
        "rms": round(rms, 2),
        "n": len(matches),
        "used": used,
        "rejected": sorted({d.value for d in dims if id(d) not in used}),
        "policy": "dense-scale-cluster",
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
