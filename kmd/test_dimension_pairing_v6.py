from types import SimpleNamespace
from vector.solve import Num, build_dims


def seg(x1, y1, x2, y2, kind):
    return SimpleNamespace(x1=x1, y1=y1, x2=x2, y2=y2, kind=kind)


def test_small_dimensions_follow_large_dimension_scale():
    # Vertical dimension numbers pair with horizontal extension lines.
    # Large dimensions establish ~12.8 mm/px, then 500/100 use that scale.
    segs = [
        seg(600, 100, 800, 100, "h"),
        seg(600, 1274, 800, 1274, "h"),
        seg(350, 200, 520, 200, "h"),
        seg(350, 668, 520, 668, "h"),
        seg(300, 300, 340, 300, "h"),
        seg(300, 339, 340, 339, "h"),
        seg(495, 500, 515, 500, "h"),
        seg(495, 508, 515, 508, "h"),
        # tempting neighboring long candidates
        seg(600, 300, 800, 300, "h"),
        seg(600, 535, 800, 535, "h"),
    ]
    numbers = [
        Num(15000, 687, 100, 28, 60, 90, True),
        Num(6000, 434, 200, 28, 60, 90, True),
        Num(500, 319.5, 300, 28, 43, 90, True),
        Num(100, 504, 500, 28, 43, 90, True),
    ]

    dims = build_dims(numbers, segs)
    got = {d.value: round(d.b - d.a, 1) for d in dims}

    assert abs(got[15000] - 1174) <= 1
    assert abs(got[6000] - 468) <= 1
    assert abs(got[500] - 39) <= 1
    assert abs(got[100] - 8) <= 1


def test_diagnostics_keep_candidate_pairs():
    segs = [seg(100, 0, 200, 0, "h"), seg(100, 39, 200, 39, "h"),
            seg(100, 200, 200, 200, "h"), seg(100, 500, 200, 500, "h")]
    dims = build_dims([Num(500, 119, 50, 20, 30, 90, True)], segs)
    assert dims
    meta = dims[0].meta
    assert meta["candidate_count"] >= 2
    assert meta["selected"]["span_px"] == 39
    assert meta["candidates"]
