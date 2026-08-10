from types import SimpleNamespace

from vector.solve import Dim, calibrate


def dim(value, a, b, vertical=False, line=0.0):
    return Dim(value, vertical, a, b, line, SimpleNamespace(
        x=(a + b) / 2, y=line, w=20, h=20, conf=95,
    ))


def test_calibration_keeps_repeated_physical_dimensions():
    # Three distinct 6000 dimensions plus one 15000 anchor.  The second
    # calibration pass must not collapse repeated 6000 values merely because
    # a smaller provisional cluster had a slightly lower RMS.
    dims = [
        dim(6000, 438.6, 905.8, line=1561.5),
        dim(6000, 349.9, 819.7, vertical=True, line=349.5),
        dim(6000, 438.6, 905.8, line=1264.5),
        dim(15000, 344.9, 1519.0, vertical=True, line=285.5),
        # False-positive small dimensions must not become calibration anchors.
        dim(3000, 580.0, 815.1, vertical=True, line=350.0),
        dim(500, 466.0, 505.4, line=1584.5),
    ]

    cal = calibrate(dims)
    assert cal is not None
    assert cal["n"] == 4
    assert sorted(m["value"] for m in cal["matches"]) == [6000, 6000, 6000, 15000]
    assert cal["policy"] == "anchor-repeat-large"
