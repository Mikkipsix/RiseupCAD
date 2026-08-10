# -*- coding: utf-8 -*-
"""End-to-end smoke test for the real RiseupCAD recognition pipeline."""
from __future__ import annotations
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
KMD = ROOT / "kmd"
TEST_IMAGE = ROOT / "testdata" / "riseupcad_test_01.jpeg"
OUT = ROOT / "out_e2e"
EXPECTED_NUMBERS = [100, 100, 500, 500, 6000, 6000, 6000, 15000]
EXPECTED_DIMS = [6000, 6000, 6000, 15000]


def _jsonable_dims(dims):
    rows = []
    for d in dims:
        rows.append({
            "value": int(d.value),
            "vertical": bool(d.vertical),
            "a": float(d.a),
            "b": float(d.b),
            "span_px": float(d.b - d.a),
            "line": float(d.line),
            "num": {
                "x": float(d.num.x), "y": float(d.num.y),
                "w": float(d.num.w), "h": float(d.num.h),
                "conf": float(d.num.conf),
            } if d.num is not None else None,
            "meta": d.meta,
        })
    return rows


def _jsonable_segments(segs):
    return [
        {
            "x1": float(s.x1), "y1": float(s.y1),
            "x2": float(s.x2), "y2": float(s.y2),
            "kind": s.kind,
            "width": float(s.width),
            "fill": float(s.fill),
            "role": s.role,
        }
        for s in segs
    ]


def main():
    if not TEST_IMAGE.exists():
        raise SystemExit(f"Missing test fixture: {TEST_IMAGE}")
    sys.path.insert(0, str(KMD))
    from vector.pipeline import vectorize
    from vector.integration import export_recognition

    OUT.mkdir(parents=True, exist_ok=True)
    result = vectorize(str(TEST_IMAGE), dpi=300, do_ocr=True)
    numbers = result.get("numbers", [])
    got = sorted(int(n.value) for n in numbers)
    print("OCR raw:", got)

    # Always persist diagnostics before assertions so a failed E2E still
    # leaves the candidate pairs and calibration inputs available as an artifact.
    debug = {
        "ocr": [
            {"value": int(n.value), "x": float(n.x), "y": float(n.y),
             "w": float(n.w), "h": float(n.h), "conf": float(n.conf),
             "vertical": bool(n.vertical)}
            for n in numbers
        ],
        "segments": _jsonable_segments(result.get("segments", [])),
        "dims": _jsonable_dims(result.get("dims", [])),
        "all_dims": _jsonable_dims(result.get("all_dims", [])),
        "used_dims": _jsonable_dims(result.get("used_dims", [])),
        "calib": result.get("calib"),
        "scale": result.get("scale"),
        "scale_source": result.get("scale_source"),
    }
    # Calibration contains Python id() values in some branches, so strip the
    # non-serializable `used` set while retaining every numerical diagnostic.
    if isinstance(debug["calib"], dict):
        debug["calib"] = {k: v for k, v in debug["calib"].items() if k != "used"}
    (OUT / "recognition_debug.json").write_text(
        json.dumps(debug, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    # OCR is intentionally allowed to return false positives. The real
    # contract is that dimension pairing/geometry must reject them rather
    # than making the whole pipeline fail before it reaches that stage.
    missing_expected = sorted(set(EXPECTED_NUMBERS) - set(got))
    if missing_expected:
        raise AssertionError(
            f"OCR missed expected values: {missing_expected}; got {got}"
        )

    used_dims = result.get("used_dims", [])
    used_values = sorted(int(d.value) for d in used_dims)
    if used_values != sorted(EXPECTED_DIMS):
        raise AssertionError(
            f"Dimension mismatch: {used_values} != {sorted(EXPECTED_DIMS)}"
        )

    model, qa = export_recognition(
        result,
        OUT,
        dims=used_dims,
        scale=result.get("scale"),
        include_ocr_text=True,
        expected_numbers=EXPECTED_NUMBERS,
        expected_dimensions=EXPECTED_DIMS,
    )
    print("QA:", qa)
    print("OCR:", got)
    print("Dimensions:", used_values)
    print("Objects:", len(model.objects))
    print("Output:", OUT / "output.dxf")
    if not qa["ok"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
