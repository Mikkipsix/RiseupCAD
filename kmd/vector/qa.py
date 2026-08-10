# -*- coding: utf-8 -*-
from __future__ import annotations
from collections import Counter
from math import isfinite


def object_counts(model): return dict(Counter(o.type for o in model.objects))


def check_model(model):
    errors=[]
    if model.scale is not None and (not isfinite(float(model.scale)) or float(model.scale)<=0): errors.append("invalid scale")
    for o in model.objects:
        try: o.validate()
        except Exception as e: errors.append(f"{o.type}: {e}")
    return errors


def check_ocr(numbers, expected):
    """Require every expected OCR value, but tolerate extra OCR detections.

    OCR is intentionally noisy on real drawings.  False-positive labels are
    allowed at the raw OCR layer because dimension pairing/calibration is the
    stage responsible for deciding which numbers are actual dimensions.
    """
    got=Counter(int(n.value) for n in numbers)
    want=Counter(int(v) for v in expected)
    missing=want-got
    if missing:
        return [f"OCR missing expected values: got={dict(got)} expected={dict(want)} missing={dict(missing)}"]
    return []


def check_dimensions(model, expected):
    got=Counter(round(float(o.data["value"])) for o in model.by_type("DIMENSION")); want=Counter(int(v) for v in expected)
    missing=want-got
    return [] if not missing else [f"missing dimensions: {dict(missing)}; got={dict(got)}"]


def report(model,numbers=(),expected_numbers=(),expected_dimensions=()):
    errors=check_model(model)
    if expected_numbers: errors += check_ocr(numbers,expected_numbers)
    if expected_dimensions: errors += check_dimensions(model,expected_dimensions)
    return {"ok":not errors,"errors":errors,"scale":model.scale,"object_counts":object_counts(model),"layers":model.layers,"mean_confidence":model.confidence()}
