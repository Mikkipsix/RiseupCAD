from types import SimpleNamespace
from vector.solve import Num, build_dims


def seg(x1, y1, x2, y2, kind):
    return SimpleNamespace(x1=x1, y1=y1, x2=x2, y2=y2, kind=kind)


def test_small_dimensions_follow_large_dimension_scale():
    # One large 15000 span and one large 6000 span establish ~12.8 mm/px.
    # Small dimensions then have intentionally tempting longer neighboring
    # pairs. The correct choice is the pair matching the inferred scale.
    segs = [
        # horizontal extension candidates for vertical dimensions
        seg(100, 100, 100, 1274, "v"),       # 1174 px -> 15000
        seg(1274, 100, 1274, 1274, "v"),
        seg(200, 200, 200, 668, "v"),         # 468 px -> 6000
        seg(668, 200, 668, 668, "v"),
        seg(300, 300, 300, 339, "v"),         # 39 px -> 500
        seg(339, 300, 339, 339, "v"),
        seg(500, 500, 500, 508, "v"),         # 8 px -> 100
        seg(508, 500, 508, 508, "v"),
        # tempting neighboring long candidates covering the same dimension line
        seg(535, 300, 535, 535, "v"),
        seg(770, 300, 770, 535, "v"),
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
    segs = [seg(100, 0, 100, 100, "v"), seg(139, 0, 139, 100, "v"),
            seg(300, 0, 300, 100, "v"), seg(500, 0, 500, 100, "v")]
    dims = build_dims([Num(500, 119, 50, 20, 30, 90, True)], segs)
    assert dims
    meta = dims[0].meta
    assert meta["candidate_count"] >= 2
    assert meta["selected"]["span_px"] == 39
    assert meta["candidates"]
