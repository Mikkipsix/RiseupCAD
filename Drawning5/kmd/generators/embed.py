# -*- coding: utf-8 -*-
"""Закладная деталь: полоса в двух видах + перпендикулярные анкеры."""
from ezdxf.enums import TextEntityAlignment as TA

from gostcad import new_doc
from gostcad.draw import dim_h, dim_v, polka, text

TH = 5.0
GAP = 100.0


def build(plate, anchor, path, title, weld_gost="ГОСТ 14098-2014"):
    L = float(plate["length"])
    B = float(plate["strip"]["b"])
    T = float(plate["strip"]["t"])
    D = float(anchor["bar"]["d"])
    LA = float(anchor["length"])
    E = float(anchor["edge"])

    ya1, ya2 = L - E, E
    xa = B / 2.0
    x2 = B + GAP            # тыльная грань полосы на виде сбоку
    xf = x2 + T             # лицевая грань
    xe = xf + LA            # торец анкера

    doc = new_doc(text_h=TH, ltscale=2.0)
    msp = doc.modelspace()

    # ---- вид спереди ----
    msp.add_lwpolyline([(0, 0), (B, 0), (B, L), (0, L)],
                       format="xy", close=True, dxfattribs={"layer": "OUTLINE"})
    for ya in (ya1, ya2):
        msp.add_circle((xa, ya), D / 2, dxfattribs={"layer": "OUTLINE"})
        # осевая доведена до размерной линии: служит выносной
        msp.add_line((-30, ya), (B + 8, ya), dxfattribs={"layer": "CENTER"})
    msp.add_line((xa, ya1 - 12), (xa, ya1 + 12), dxfattribs={"layer": "CENTER"})
    msp.add_line((xa, -30), (xa, ya2 + 12), dxfattribs={"layer": "CENTER"})

    # ---- вид сбоку ----
    msp.add_lwpolyline([(x2, 0), (xf, 0), (xf, L), (x2, L)],
                       format="xy", close=True, dxfattribs={"layer": "OUTLINE"})
    for ya in (ya1, ya2):
        msp.add_lwpolyline(
            [(xf, ya + D / 2), (xe, ya + D / 2), (xe, ya - D / 2),
             (xf, ya - D / 2)],
            format="xy", close=False, dxfattribs={"layer": "OUTLINE"})

    # ---- размеры ----
    dim_v(msp, (0, L), (0, 0), -45.0)                                  # L
    dim_v(msp, (0, L), (xa, ya1), -25.0, se1=True, se2=True)           # E
    dim_v(msp, (xa, ya1), (xa, ya2), -25.0, se1=True, se2=True)        # шаг
    dim_h(msp, (0, 0), (xa, ya2), -25.0, se1=True, se2=True)           # xa
    dim_h(msp, (0, 0), (B, 0), -45.0)                                  # B
    dim_h(msp, (x2, 0), (xe, 0), -45.0)                                # глубина
    expected = sorted([L, E, ya1 - ya2, xa, B, T + LA])

    # ---- выноски ----
    polka(msp, (18.0, L - 15.0), (40.0, L + 30.0), "15", TH)
    polka(msp, (xf + 1.5, ya2 + D / 2), (x2 + 35.0, L * 0.38), weld_gost, TH)
    polka(msp, (xf + LA * 0.42, ya2), (xf + LA * 0.6, L * 0.25), "16", TH)

    text(msp, title, (B + xe) / 2, L + 55.0, 10.0, TA.MIDDLE_CENTER)

    doc.set_modelspace_vport(height=L * 1.9, center=((B + xe) / 2, L / 2))
    doc.saveas(path)
    return expected
