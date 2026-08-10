# -*- coding: utf-8 -*-
"""DXF writer consuming only DrawingModel."""
from __future__ import annotations
from pathlib import Path
import ezdxf


def _layer(doc, name):
    if name not in doc.layers: doc.layers.add(name)


def _dimension(msp, obj):
    d=obj.data; p1=tuple(d["p1"]); p2=tuple(d["p2"]); value=float(d["value"])
    try:
        base=((p1[0]+p2[0])/2,(p1[1]+p2[1])/2)
        angle=90 if d.get("orientation")=="vertical" else 0
        dim=msp.add_linear_dim(base=base,p1=p1,p2=p2,angle=angle,dxfattribs={"layer":obj.layer})
        dim.set_text(str(int(value) if value.is_integer() else value)); dim.render(); return
    except Exception:
        msp.add_line(p1,p2,dxfattribs={"layer":obj.layer})
        msp.add_text(str(int(value) if value.is_integer() else value),dxfattribs={"layer":obj.layer,"height":2.5}).set_placement(((p1[0]+p2[0])/2,(p1[1]+p2[1])/2))


def write_dxf(model, path: str|Path):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    doc=ezdxf.new("R2018",setup=True); msp=doc.modelspace()
    for layer in model.layers: _layer(doc,layer)
    for o in model.objects:
        d=o.data
        if o.type=="LINE": msp.add_line(tuple(d["start"]),tuple(d["end"]),dxfattribs={"layer":o.layer})
        elif o.type=="POLYLINE":
            pts=[tuple(p) for p in d.get("points",[])];
            if len(pts)>=2: msp.add_lwpolyline(pts,close=bool(d.get("closed")),dxfattribs={"layer":o.layer})
        elif o.type=="CIRCLE": msp.add_circle(tuple(d["center"]),float(d["radius"]),dxfattribs={"layer":o.layer})
        elif o.type=="ARC": msp.add_arc(tuple(d["center"]),float(d["radius"]),float(d.get("start_angle",d.get("a0",0))),float(d.get("end_angle",d.get("a1",360))),dxfattribs={"layer":o.layer})
        elif o.type=="TEXT": msp.add_text(str(d.get("text","")),dxfattribs={"layer":o.layer,"height":float(d.get("height",2.5))}).set_placement(tuple(d.get("position",[0,0])))
        elif o.type=="DIMENSION": _dimension(msp,o)
    doc.saveas(path); return path
