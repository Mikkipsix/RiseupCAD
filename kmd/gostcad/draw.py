# -*- coding: utf-8 -*-
"""Обёртки над ezdxf: текст, линейные и радиусные размеры, полки-выноски."""
import math
from ezdxf.enums import TextEntityAlignment as TA

from .style import TEXT_STYLE

DIM_LAYER = "DIMENSIONS"


def text(msp, s, x, y, h, align=TA.MIDDLE_CENTER, layer="TEXT"):
    e = msp.add_text(s, height=h,
                     dxfattribs={"layer": layer, "style": TEXT_STYLE})
    e.set_placement((x, y), align=align)
    return e


def dim_h(msp, p1, p2, y, se1=False, se2=False, style="GOST_2307"):
    """Горизонтальный размер. se1/se2 - подавить выносную линию у p1/p2.

    Подавлять нужно там, где роль выносной выполняет осевая линия или
    выносная соседнего размера, иначе получим коллинеарное наложение.
    """
    ov = {}
    if se1:
        ov["dimse1"] = 1
    if se2:
        ov["dimse2"] = 1
    d = msp.add_linear_dim(base=(p1[0], y), p1=p1, p2=p2, dimstyle=style,
                           override=ov or None,
                           dxfattribs={"layer": DIM_LAYER})
    d.render()
    return d


def dim_v(msp, p1, p2, x, se1=False, se2=False, style="GOST_2307"):
    """Вертикальный размер."""
    ov = {}
    if se1:
        ov["dimse1"] = 1
    if se2:
        ov["dimse2"] = 1
    d = msp.add_linear_dim(base=(x, p1[1]), p1=p1, p2=p2, angle=90.0,
                           dimstyle=style, override=ov or None,
                           dxfattribs={"layer": DIM_LAYER})
    d.render()
    return d


def dim_r(msp, center, radius, angle_deg, dist, text_h, style="GOST_R"):
    """Радиусный размер с выносной полкой.

    angle_deg - направление луча от центра, dist - вынос текста от центра.
    """
    a = math.radians(angle_deg)
    loc = (center[0] + dist * math.cos(a), center[1] + dist * math.sin(a))
    d = msp.add_radius_dim(
        center=center, radius=radius, location=loc, dimstyle=style,
        override={"dimtofl": 0, "dimtoh": 1, "dimtmove": 1, "dimupt": 1,
                  "dimtxt": text_h, "dimasz": text_h * 0.6, "dimpost": "R<>",
                  "dimtxsty": TEXT_STYLE, "dimdec": 0, "dimzin": 8,
                  "dimscale": 1.0},
        dxfattribs={"layer": DIM_LAYER})
    d.render()
    return d


def polka(msp, arrow, knee, label, text_h, shelf=None, left=False):
    """Выноска: стрелка -> излом -> горизонтальная полка, надпись над полкой."""
    if shelf is None:
        shelf = est_width(label, text_h) + text_h
    end = (knee[0] - shelf, knee[1]) if left else (knee[0] + shelf, knee[1])
    ldr = msp.add_leader([arrow, knee, end], dimstyle="GOST_LEADER",
                         dxfattribs={"layer": DIM_LAYER})
    ldr.dxf.has_hookline = 0
    align = TA.RIGHT if left else TA.LEFT
    dx = -text_h * 0.4 if left else text_h * 0.4
    text(msp, label, knee[0] + dx, knee[1] + text_h * 0.4, text_h, align)
    return ldr


def est_width(s, h, factor=0.55):
    """Консервативная оценка ширины строки.

    Реальный isocpeur ~0.52h на знак; берём 0.55 с запасом, чтобы проверка
    вылезания текста за границы граф срабатывала до, а не после выдачи файла.
    """
    return len(s) * h * factor
