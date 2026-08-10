# -*- coding: utf-8 -*-
"""Adapter from current raster/OCR result to DrawingModel."""
from __future__ import annotations
from typing import Any, Iterable
from .semantic import DrawingModel, CadObject


def _cad_y(y_px, height_px, scale):
    return ((height_px - float(y_px)) if height_px is not None else float(y_px)) * scale


def _line(seg, scale, height_px):
    return CadObject("LINE", "GEOMETRY", float(getattr(seg, "conf", 0.8)),
        {"detector": "segment", "coordinate_system": "image_px"},
        {"start": [float(seg.x1)*scale, _cad_y(seg.y1,height_px,scale)],
         "end": [float(seg.x2)*scale, _cad_y(seg.y2,height_px,scale)]})


def _arc(a, scale, height_px):
    d = {"center": [float(a.cx)*scale, _cad_y(a.cy,height_px,scale)], "radius": float(a.r)*scale}
    for n in ("start_angle","end_angle","a0","a1"):
        if hasattr(a,n): d[n] = float(getattr(a,n))
    return CadObject("ARC", "GEOMETRY", float(getattr(a,"conf",0.8)), {"detector":"arc"}, d)


def _circle(c, scale, height_px):
    return CadObject("CIRCLE", "GEOMETRY", float(getattr(c,"conf",0.8)), {"detector":"circle"},
        {"center":[float(c.cx)*scale, _cad_y(c.cy,height_px,scale)], "radius":float(c.r)*scale})


def _dimension(d, scale, height_px):
    if d.vertical:
        x = float(d.line)*scale
        p1 = [x, _cad_y(d.a,height_px,scale)]
        p2 = [x, _cad_y(d.b,height_px,scale)]
        orientation = "vertical"
    else:
        y = _cad_y(d.line,height_px,scale)
        p1 = [float(d.a)*scale, y]
        p2 = [float(d.b)*scale, y]
        orientation = "horizontal"
    conf = float(getattr(d.num,"conf",80.0))/100.0 if getattr(d,"num",None) else 0.8
    return CadObject("DIMENSION", "DIMENSIONS", conf, {"detector":"dimension"},
        {"value":float(d.value), "p1":p1, "p2":p2, "orientation":orientation,
         "meta":dict(getattr(d,"meta",{}) or {})})


def _text(n, scale, height_px):
    return CadObject("TEXT", "TEXT", float(getattr(n,"conf",80.0))/100.0, {"detector":"ocr"},
        {"text":str(n.value), "position":[float(n.x)*scale,_cad_y(n.y,height_px,scale)],
         "height":max(1.0, float(max(n.w,n.h))*scale)})


def build_model(result: dict[str, Any], dims: Iterable[Any]=(), scale: float|None=None,
                include_ocr_text: bool=False) -> DrawingModel:
    gray = result.get("gray")
    height = int(gray.shape[0]) if gray is not None and hasattr(gray,"shape") else None
    width = int(gray.shape[1]) if gray is not None and hasattr(gray,"shape") else None
    model = DrawingModel(scale=float(scale) if scale and scale>0 else None,
                         width_px=width, height_px=height,
                         metadata={"coordinate_system":"CAD_Y_UP","source":"raster_pipeline"})
    s = float(scale) if scale and scale>0 else 1.0
    if model.scale is None: model.metadata["unscaled_geometry"] = True
    for seg in result.get("segments",[]) or []: model.add(_line(seg,s,height))
    for a in result.get("arcs",[]) or []:
        try: model.add(_arc(a,s,height))
        except AttributeError: pass
    for c in result.get("circles",[]) or []:
        try: model.add(_circle(c,s,height))
        except AttributeError: pass
    for d in dims: model.add(_dimension(d,s,height))
    if include_ocr_text:
        for n in result.get("numbers", result.get("ocr_numbers", [])) or []: model.add(_text(n,s,height))
    return model
