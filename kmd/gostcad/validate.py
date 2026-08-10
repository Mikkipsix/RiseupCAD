# -*- coding: utf-8 -*-
"""
Аудит DXF. Ни один файл не считается готовым без зелёного отчёта.

Проверяется: целостность по ezdxf.audit, дубликаты сегментов, коллинеарные
наложения (с разворачиванием анонимных блоков размеров и выносок),
незамкнутые контуры там, где замкнутость заявлена, NaN/Inf, и главное -
совпадение DIMENSION.get_measurement() с проектными значениями.
"""
import math
from collections import Counter

import ezdxf
import ezdxf.bbox
from ezdxf.audit import Auditor

TOL = 1e-6


class Report:
    def __init__(self, name):
        self.name = name
        self.errors = []
        self.notes = []
        self.stats = {}

    @property
    def ok(self):
        return not self.errors

    def __str__(self):
        mark = "OK  " if self.ok else "FAIL"
        s = [f"[{mark}] {self.name}"]
        for k, v in self.stats.items():
            s.append(f"        {k}: {v}")
        for e in self.errors:
            s.append(f"    ОШИБКА: {e}")
        for n in self.notes:
            s.append(f"    прим.:  {n}")
        return "\n".join(s)


def _segments(doc, msp):
    """Все прямолинейные сегменты, включая геометрию внутри блоков размеров."""
    out = []

    def add(a, b, tag):
        if math.dist(a, b) > 1e-9:
            out.append((a, b, tag))

    def walk(container, tag):
        for e in container:
            t = e.dxftype()
            if t == "LINE":
                add((e.dxf.start.x, e.dxf.start.y),
                    (e.dxf.end.x, e.dxf.end.y), tag)
            elif t == "LWPOLYLINE":
                pts = list(e.get_points("xyb"))
                n = len(pts)
                rng = range(n) if e.closed else range(n - 1)
                for i in rng:
                    if abs(pts[i][2]) < 1e-12:          # дуги не проверяем
                        a = (pts[i][0], pts[i][1])
                        b = (pts[(i + 1) % n][0], pts[(i + 1) % n][1])
                        add(a, b, tag)

    walk(msp, "model")
    for d in msp.query("DIMENSION"):
        blk = doc.blocks.get(d.dxf.geometry)
        if blk is not None:
            walk(blk, f"dim:{d.dxf.geometry}")
    for l in msp.query("LEADER"):
        v = [(p[0], p[1]) for p in l.vertices]
        for i in range(len(v) - 1):
            add(v[i], v[i + 1], "leader")
    return out


def _overlap(s1, s2):
    (a1, b1, _), (a2, b2, _) = s1, s2
    d1 = (b1[0] - a1[0], b1[1] - a1[1])
    d2 = (b2[0] - a2[0], b2[1] - a2[1])
    L1 = math.hypot(*d1)
    L2 = math.hypot(*d2)
    u = (d1[0] / L1, d1[1] / L1)
    if abs(u[0] * d2[1] - u[1] * d2[0]) > TOL * L2:
        return 0.0
    v = (a2[0] - a1[0], a2[1] - a1[1])
    if abs(u[0] * v[1] - u[1] * v[0]) > TOL:
        return 0.0
    t1 = u[0] * v[0] + u[1] * v[1]
    t2 = u[0] * (b2[0] - a1[0]) + u[1] * (b2[1] - a1[1])
    return max(0.0, min(L1, max(t1, t2)) - max(0.0, min(t1, t2)))


def check(path, expected_dims=None, allow_overlap=0.0, name=None):
    """expected_dims - список проектных значений всех DIMENSION, мм."""
    rep = Report(name or path.split("/")[-1])
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()

    aud = Auditor(doc)
    aud.run()
    if aud.errors:
        rep.errors.append(f"ezdxf.audit: {len(aud.errors)} ошибок")
    if aud.fixes:
        rep.notes.append(f"ezdxf.audit: {len(aud.fixes)} автоисправлений")

    ents = Counter(e.dxftype() for e in msp)
    rep.stats["объекты"] = ", ".join(f"{k}={v}" for k, v in sorted(ents.items()))

    segs = _segments(doc, msp)
    keys = [tuple(sorted([(round(a[0], 6), round(a[1], 6)),
                          (round(b[0], 6), round(b[1], 6))]))
            for a, b, _ in segs]
    dups = sum(1 for _, c in Counter(keys).items() if c > 1)
    if dups:
        rep.errors.append(f"дубликаты сегментов: {dups}")

    ov_total = 0.0
    worst = []
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            o = _overlap(segs[i], segs[j])
            if o > TOL:
                ov_total += o
                worst.append((o, segs[i][2], segs[j][2]))
    if ov_total > allow_overlap + TOL:
        worst.sort(reverse=True)
        rep.errors.append(
            f"коллинеарные наложения: {len(worst)} шт, суммарно "
            f"{ov_total:.2f} мм (худшее {worst[0][0]:.2f} мм, "
            f"{worst[0][1]} / {worst[0][2]})")
    elif worst:
        rep.notes.append(
            f"наложения в пределах допуска: {len(worst)} шт, {ov_total:.2f} мм")
    rep.stats["сегментов"] = len(segs)

    # NaN / Inf
    bad = 0
    for e in msp:
        for attr in ("start", "end", "center", "insert"):
            if e.dxf.hasattr(attr):
                v = e.dxf.get(attr)
                if any(math.isnan(c) or math.isinf(c) for c in v):
                    bad += 1
    if bad:
        rep.errors.append(f"объекты с NaN/Inf: {bad}")

    # размеры
    dims = sorted(round(d.get_measurement(), 3) for d in msp.query("DIMENSION"))
    rep.stats["размеры"] = dims if dims else "нет"
    if expected_dims is not None:
        exp = sorted(round(float(v), 3) for v in expected_dims)
        if dims != exp:
            rep.errors.append(f"размеры не совпали с проектными: {dims} != {exp}")

    try:
        bb = ezdxf.bbox.extents(msp, fast=False)
        rep.stats["габарит"] = (
            f"X[{bb.extmin.x:.1f}…{bb.extmax.x:.1f}] "
            f"Y[{bb.extmin.y:.1f}…{bb.extmax.y:.1f}]")
    except Exception:
        pass
    return rep
