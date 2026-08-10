# -*- coding: utf-8 -*-
"""
Подвеска из круглой стали: три гиба на 180 градусов.
Контур - одна замкнутая LWPOLYLINE с bulge = +-1 (точные полуокружности).
"""
from ezdxf.enums import TextEntityAlignment as TA

from gostcad import new_doc
from gostcad.calc import hook_development
from gostcad.draw import dim_h, dim_v, dim_r, polka, text

TH = 10.0


def build(spec, path, title):
    d = float(spec["bar"]["d"])
    H = float(spec["height"])
    leg = float(spec["leg"])
    r_ax = float(spec["r_axis"])

    r = d / 2.0
    r_in = r_ax - r
    r_out = r_ax + r
    step = 2.0 * r_ax                  # шаг между осями смежных ветвей

    # опорные координаты: (0,0) - нижняя левая точка габарита
    yb = r_out
    yt = H - r_out
    y_end = yb + leg
    xa = r
    xbl = xa + r_ax
    xb = xbl + r_ax
    xt = xb + r_ax
    xc = xt + r_ax
    xbr = xc + r_ax
    xd = xbr + r_ax
    W = xd + r

    doc = new_doc(text_h=TH, ltscale=6.0)
    msp = doc.modelspace()

    CCW, CW = 1.0, -1.0
    msp.add_lwpolyline([
        (xa - r, y_end, 0.0), (xa - r, yb, CCW),      # наружная дуга левого гиба
        (xb + r, yb, 0.0), (xb + r, yt, CW),          # внутренняя дуга верхнего
        (xc - r, yt, 0.0), (xc - r, yb, CCW),         # наружная дуга правого
        (xd + r, yb, 0.0), (xd + r, y_end, 0.0),
        (xd - r, y_end, 0.0), (xd - r, yb, CW),       # внутренняя правого
        (xc + r, yb, 0.0), (xc + r, yt, CCW),         # наружная верхнего
        (xb - r, yt, 0.0), (xb - r, yb, CW),          # внутренняя левого
        (xa + r, yb, 0.0), (xa + r, y_end, 0.0),
    ], format="xyb", close=True, dxfattribs={"layer": "OUTLINE"})

    OV = 15.0
    x_dim_leg = xd + r + 45.0
    # осевая нижних гибов доведена за размерную линию: служит выносной
    msp.add_line((xa - r - OV, yb), (x_dim_leg + 5.0, yb),
                 dxfattribs={"layer": "CENTER"})
    msp.add_line((xb - r - OV, yt), (xc + r + OV, yt),
                 dxfattribs={"layer": "CENTER"})
    for xg, y1, y2 in ((xbl, yb - r_out - OV, y_end + OV),
                       (xbr, yb - r_out - OV, y_end + OV),
                       (xt, yt - r_ax - OV, yt + r_out + OV)):
        msp.add_line((xg, y1), (xg, y2), dxfattribs={"layer": "CENTER"})

    dim_v(msp, (xt, H), (xt, 0.0), xd + r + 90.0)
    dim_v(msp, (xbr, yb), (xd + r, y_end), x_dim_leg, se1=True)
    dim_h(msp, (0.0, 0.0), (W, 0.0), -55.0)
    dim_r(msp, (xt, yt), r_in, 55.0, 145.0, TH)
    dim_r(msp, (xbl, yb), r_in, 215.0, 145.0, TH)
    expected = sorted([H, leg, W, r_in, r_in])

    b = spec["bar"]
    polka(msp, (xb - r, H * 0.6), (xb - r - 70.0, H * 0.7),
          f'{b["d"]:g}{b["cls"]}', TH, left=True)
    text(msp, title, W / 2.0, H + 45.0, 20.0, TA.MIDDLE_CENTER)

    doc.set_modelspace_vport(height=H * 1.5, center=(W / 2, H / 2))
    doc.saveas(path)

    return expected, hook_development(H, leg, r_ax, d), step
