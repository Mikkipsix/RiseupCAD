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
    """Require each distinct expected value, but tolerate OCR noise/count drift.

    OCR on a real drawing may duplicate one label, miss another duplicate, or
    produce unrelated numeric text.  Dimension pairing/calibration is the
    authoritative stage for accepting dimension instances, so raw OCR QA only
    verifies that every distinct expected value is detectable.
    """
    got=Counter(int(n.value) for n in numbers)
    want=sorted({int(v) for v in expected})
    missing=[v for v in want if got[v] == 0]
    if missing:
        return [f"OCR missing expected values: got={dict(got)} expected={want} missing={missing}"]
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
