# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import json
from .model_builder import build_model
from .dxf_writer import write_dxf
from .qa import report


def export_recognition(result, output_dir, dims=(), scale=None, include_ocr_text=False,
                       expected_numbers=(), expected_dimensions=()):
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    model=build_model(result,dims=dims,scale=scale,include_ocr_text=include_ocr_text)
    model.save_json(out/"geometry.json")
    qa=report(model,numbers=result.get("numbers",result.get("ocr_numbers",[])),expected_numbers=expected_numbers,expected_dimensions=expected_dimensions)
    (out/"qa_report.json").write_text(json.dumps(qa,ensure_ascii=False,indent=2),encoding="utf-8")
    write_dxf(model,out/"output.dxf")
    return model,qa
