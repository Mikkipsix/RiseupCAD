from types import SimpleNamespace

from vector.pipeline import _calibration_dims
from vector.solve import Dim


def dim(value, a, b, vertical=False, line=0.0):
    return Dim(
        value,
        vertical,
        a,
        b,
        line,
        SimpleNamespace(x=(a + b) / 2, y=line, w=20, h=20, conf=95),
    )


def test_repeated_value_selects_dimension_with_calibrated_span():
    false_positive = dim(6000, 100.0, 335.0, line=900.0)
    real_anchor = dim(6000, 438.6, 905.8, line=1561.5)
    other_anchor = dim(15000, 344.9, 1519.0, vertical=True, line=285.5)

    selected = _calibration_dims(
        [false_positive, real_anchor, other_anchor],
        {
            "matches": [
                {"value": 6000, "px": 467.2},
                {"value": 15000, "px": 1174.1},
            ]
        },
    )

    assert selected == [real_anchor, other_anchor]


def test_duplicate_calibration_matches_consume_distinct_dimensions():
    first = dim(6000, 0.0, 468.0, line=100.0)
    second = dim(6000, 10.0, 478.0, line=200.0)

    selected = _calibration_dims(
        [second, first],
        {
            "matches": [
                {"value": 6000, "px": 468.0, "line": 100.0},
                {"value": 6000, "px": 468.0, "line": 200.0},
            ]
        },
    )

    assert selected == [first, second]
