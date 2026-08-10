"""Scale-aware global assignment for dimension candidates.

The earlier selector chose the best pair independently for each OCR number. That
can reuse the same witness-line pair and can leave a valid repeated dimension
unassigned. v10 keeps the candidate generation but assigns pairs globally.
"""
from __future__ import annotations


def install(solve):
    original_refine = solve.refine_dims
    original_calibrate = solve.calibrate

    def refine_dims(numbers, segs, scale, rel_tol=0.04, reach=9.0):
        # Build every candidate first. Small dimensions are allowed; the scale
        # score decides whether they are plausible.
        entries = []
        for ni, nb in enumerate(numbers):
            cands = solve._candidates(nb, segs, reach)
            target = nb.value / scale
            ranked = []
            for ci, c in enumerate(cands):
                err = abs(c["span_px"] - target) / max(target, 1e-9)
                if err <= rel_tol:
                    ranked.append((err, c["center_error_px"], 0 if c["inside"] else 1,
                                   c["symmetry"], c["span_px"], ci, c))
            ranked.sort(key=lambda x: x[:5])
            if ranked:
                entries.append((ni, nb, ranked))

        # Greedy global matching by normalized scale error. A candidate pair
        # may be consumed only once, while equal OCR values remain independent.
        proposals = []
        for ni, nb, ranked in entries:
            for rank, item in enumerate(ranked[:20]):
                proposals.append((item[0], item[1], item[2], item[3],
                                   rank, ni, nb, item[6]))
        proposals.sort(key=lambda x: x[:5])
        used_pairs = set()
        assigned = {}
        for err, center, outside, symmetry, rank, ni, nb, c in proposals:
            pair = (round(c["a"], 1), round(c["b"], 1),
                    round(c["line"], 1), bool(nb.vertical))
            if ni in assigned or pair in used_pairs:
                continue
            assigned[ni] = c
            used_pairs.add(pair)

        out = []
        for ni, nb, ranked in entries:
            best = assigned.get(ni)
            if best is None:
                continue
            target = nb.value / scale
            meta_candidates = []
            for item in ranked[:12]:
                c = dict(item[6])
                c["target_error"] = item[0]
                meta_candidates.append(c)
            out.append(solve.Dim(
                nb.value, nb.vertical, best["a"], best["b"], best["line"], nb,
                meta={
                    "scale_used": scale,
                    "target_px": target,
                    "candidate_count": len(solve._candidates(nb, segs, reach)),
                    "selected": best,
                    "candidates": meta_candidates,
                    "assignment_unique": True,
                },
            ))
        return out

    def calibrate(dims, rel_tol=0.05, allow_single=True):
        # Calibration should be driven by dimensions large enough to be robust
        # against pixel quantisation. Small dimensions remain available to the
        # final model but do not get to distort the global sheet scale when
        # larger repeated constraints exist.
        large = [d for d in dims if d.value >= 1000]
        pool = large if len(large) >= 2 else dims
        return original_calibrate(pool, rel_tol=rel_tol, allow_single=allow_single)

    solve.refine_dims = refine_dims
    solve.calibrate = calibrate
