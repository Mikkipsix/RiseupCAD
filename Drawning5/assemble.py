# -*- coding: utf-8 -*-
"""
Сборка распознанного в модель чертежа и вывод в DXF.

Здесь растровые пиксели превращаются в инженерный чертёж: координаты
притягиваются к проектным значениям, контуры замыкаются в полилинии,
размеры выходят настоящими объектами DIMENSION, а не нарисованными
линиями, и всё раскладывается по слоям.
"""
import math
import os
import sys

from . import solve

ROLE_LAYER = {"contour": "OUTLINE", "thin": "THIN", "center": "CENTER",
              "leader": "THIN"}


class Model:
    def __init__(self):
        self.lines = []        # (x1, y1, x2, y2, layer)
        self.polys = []        # ([(x, y), ...], layer)
        self.circles = []      # (cx, cy, r, layer)
        self.arcs = []         # (cx, cy, r, начало, конец, layer) - градусы
        self.dims = []         # (p1, p2, base, angle, value)
        self.texts = []        # (s, x, y, h)
        self.notes = []


# =====================================================================
#  Притягивание координат к проектным значениям
# =====================================================================
def regularize(segs, circles, dims, scale, H, tol=5.0):
    """Возвращает функции X(px)->мм и Y(px)->мм плюс отчёт о невязках."""
    xs = [s.x1 for s in segs if s.kind == "v"]
    ys = [s.y1 for s in segs if s.kind == "h"]
    cx, _ = solve.cluster(xs, tol)
    cy, _ = solve.cluster(ys, tol)

    con_x, con_y, unmatched = [], [], []
    for d in dims:
        centers = cy if d.vertical else cx
        ia = solve.nearest(centers, d.a, tol * 1.6)
        ib = solve.nearest(centers, d.b, tol * 1.6)
        if ia < 0 or ib < 0 or ia == ib:
            unmatched.append(d.value)
            continue
        d.ia, d.ib = ia, ib
        (con_y if d.vertical else con_x).append((ia, ib, float(d.value)))

    sol_x, res_x = solve.solve_axis(cx, con_x, scale)
    sol_y, res_y = solve.solve_axis(cy, con_y, scale)

    def X(v):
        i = solve.nearest(cx, v, tol)
        return sol_x[i] if i >= 0 else v * scale

    def Y(v):
        i = solve.nearest(cy, v, tol)
        base = sol_y[i] if i >= 0 else v * scale
        return H * scale - base          # растр считает сверху, чертёж снизу

    report = {"clusters_x": len(cx), "clusters_y": len(cy),
              "constraints": len(con_x) + len(con_y),
              "resid": [r for r in res_x + res_y],
              "unmatched": unmatched}
    return X, Y, cx, cy, report


# =====================================================================
#  Замыкание контуров
# =====================================================================
def _resweep(c, p, q, sw):
    """Пересчитывает размах дуги после переноса её конца."""
    ap = math.atan2(p[1] - c[1], p[0] - c[0])
    aq = math.atan2(q[1] - c[1], q[0] - c[0])
    if sw > 0:
        return (aq - ap) % (2 * math.pi)
    return -((ap - aq) % (2 * math.pi))


def _tangent_points(arc, ed, tol_tan, reach):
    """Точки касания прямых к окружности дуги."""
    cxm, cym = arc["c"]
    R = arc["r"]
    out = []
    for e in ed:
        (x1, y1), (x2, y2) = e[0], e[1]
        horiz = abs(y2 - y1) <= abs(x2 - x1)
        if horiz:
            d, T = abs(cym - y1), (cxm, y1)
            lo, hi = sorted((x1, x2))
            inside = lo - reach <= cxm <= hi + reach
        else:
            d, T = abs(cxm - x1), (x1, cym)
            lo, hi = sorted((y1, y2))
            inside = lo - reach <= cym <= hi + reach
        if abs(d - R) <= tol_tan and inside:
            out.append((T, e))
    return out


def _join_arcs(edges, arcs_m, tol_tan=5.0, reach=60.0):
    """Сводит прямые и дуги в общую точку касания.

    Хаф обрывает прямую, не доводя до касания, а дуга наоборот часто
    заезжает за него - размах выходит больше 180°. Ни подтягивание
    прямой к концу дуги, ни обратное по отдельности не помогают. Точка
    касания считается геометрически: это основание перпендикуляра из
    центра дуги на прямую. Туда сводятся оба конца.
    """
    ed = [[list(p), list(q), src] for p, q, src in edges]
    for arc in arcs_m:
        cands = _tangent_points(arc, ed, tol_tan, reach)
        if not cands:
            continue
        old = (tuple(arc["p"]), tuple(arc["q"]), arc["sw"])
        moved = []
        for key in ("p", "q"):
            other = arc["q"] if key == "p" else arc["p"]
            best = None
            for T, e in cands:
                if math.dist(T, other) < 1.0:
                    continue                 # тот же конец
                d = math.dist(arc[key], T)
                if d <= reach and (best is None or d < best[0]):
                    best = (d, T, e)
            if best:
                _, T, e = best
                arc[key] = tuple(T)
                moved.append((e, T))
        if not moved:
            continue
        arc["sw"] = _resweep(arc["c"], arc["p"], arc["q"], old[2])
        deg = abs(math.degrees(arc["sw"]))
        if deg < 20.0 or deg > 300.0:
            arc["p"], arc["q"], arc["sw"] = old   # перенос всё испортил
            continue
        for e, T in moved:                        # прямую тянем к касанию
            k = 0 if math.dist(e[0], T) <= math.dist(e[1], T) else 1
            if math.dist(e[k], T) <= reach:
                e[k] = list(T)
    return [(tuple(p), tuple(q), src) for p, q, src in ed]


def build_contours(segs, X, Y, snap=2.5, min_area=20.0, serves=None,
                   arcs_m=None):
    """Отрезки и дуги собираются в замкнутые полилинии обходом граней.

    Контур определяется структурно, а не по толщине штриха: на ксерокопии
    основная линия и размерная бывают одной толщины, но контур замкнут.
    Простой обход «по степени 2» не годится - к углам детали примыкают
    выносные линии, поэтому используется обход граней: в каждом узле
    следующее ребро выбирается ближайшим по часовой стрелке.
    """
    arcs_m = arcs_m or []
    raw = []
    for s in segs:
        p = (X(s.x1), Y(s.y1))
        q = (X(s.x2), Y(s.y2))
        if math.dist(p, q) > 1e-6:
            raw.append((p, q, s))
    raw = _join_arcs(raw, arcs_m)

    # разбиение в Т-образных примыканиях: без этого граф не планарный и
    # грань не замыкается - кромка детали проходит «мимо» узла, в который
    # упирается соседняя линия
    ends = [pt for p, q, _ in raw for pt in (p, q)]
    ends += [tuple(a[k]) for a in arcs_m for k in ("p", "q")]
    pieces = []
    for p, q, src in raw:
        cuts = [0.0, 1.0]
        dx, dy = q[0] - p[0], q[1] - p[1]
        L2 = dx * dx + dy * dy
        for e in ends:
            t = ((e[0] - p[0]) * dx + (e[1] - p[1]) * dy) / L2
            if 0.02 < t < 0.98:
                px, py = p[0] + t * dx, p[1] + t * dy
                if math.dist((px, py), e) <= snap:
                    cuts.append(t)
        cuts = sorted(set(round(c, 5) for c in cuts))
        for i in range(len(cuts) - 1):
            t0, t1 = cuts[i], cuts[i + 1]
            a_ = (p[0] + t0 * dx, p[1] + t0 * dy)
            b_ = (p[0] + t1 * dx, p[1] + t1 * dy)
            if math.dist(a_, b_) > snap:
                pieces.append((a_, b_, src, 0.0))

    for idx, a in enumerate(arcs_m):
        pieces.append((tuple(a["p"]), tuple(a["q"]), ("arc", idx), a["sw"]))

    nodes, graph, srcmap, bulge = [], {}, {}, {}

    def node(pt):
        for i, n in enumerate(nodes):
            if math.dist(pt, n) <= snap:
                return i
        nodes.append(pt)
        return len(nodes) - 1

    for p, q, src, sw in pieces:
        a_, b_ = node(p), node(q)
        if a_ == b_:
            continue
        graph.setdefault(a_, set()).add(b_)
        graph.setdefault(b_, set()).add(a_)
        srcmap[(a_, b_)] = src
        srcmap[(b_, a_)] = src
        if sw:
            bulge[(a_, b_)] = math.tan(sw / 4.0)
            bulge[(b_, a_)] = math.tan(-sw / 4.0)

    order = {}
    for u, nbrs in graph.items():
        order[u] = sorted(nbrs, key=lambda v: math.atan2(
            nodes[v][1] - nodes[u][1], nodes[v][0] - nodes[u][0]))

    faces, seen = [], set()
    for u in graph:
        for v in graph[u]:
            if (u, v) in seen:
                continue
            face, cu, cv = [u], u, v
            ok = True
            for _ in range(300):
                seen.add((cu, cv))
                face.append(cv)
                ring = order[cv]
                i = ring.index(cu)
                nxt = ring[(i - 1) % len(ring)]      # по часовой стрелке
                cu, cv = cv, nxt
                if (cu, cv) == (u, v):
                    break
            else:
                ok = False
            if ok and len(face) >= 4:
                faces.append(face[:-1])

    serves = serves or set()
    polys, inloop, used_arcs = [], set(), set()
    for f in faces:
        srcs = [srcmap.get((f[i], f[(i + 1) % len(f)])) for i in range(len(f))]
        n_serv = sum(1 for e in srcs
                     if e is not None and not isinstance(e, tuple)
                     and id(e) in serves)
        if n_serv > 0.4 * len(srcs):
            continue          # грань собрана из размерных и выносных линий
        pts = []
        area = 0.0
        for i in range(len(f)):
            x1, y1 = nodes[f[i]]
            x2, y2 = nodes[f[(i + 1) % len(f)]]
            area += x1 * y2 - x2 * y1
            pts.append((x1, y1, bulge.get((f[i], f[(i + 1) % len(f)]), 0.0)))
        if area / 2.0 <= min_area:        # внешняя грань имеет обратный знак
            continue
        polys.append(pts)
        for e in srcs:
            if e is None:
                continue
            if isinstance(e, tuple) and e and e[0] == "arc":
                used_arcs.add(e[1])
            else:
                inloop.add(id(e))
    uniq, seen_key = [], set()
    for p in sorted(polys, key=lambda p: -len(p)):
        key = tuple(sorted((round(x, 1), round(y, 1)) for x, y, _ in p))
        if key in seen_key:
            continue
        seen_key.add(key)
        uniq.append(p)
    return uniq, inloop, used_arcs


# =====================================================================
#  Сборка модели
# =====================================================================
def build_model(segs, circles, dims, numbers, scale, H, put_text=True,
                arcs=None):
    X, Y, cx, cy, rep = regularize(segs, circles, dims, scale, H)
    m = Model()
    m.notes.append(rep)

    # В поиске контура участвуют все сплошные линии: кромка детали часто
    # слита Хафом со своей выносной в один отрезок, и отбрасывать её
    # заранее нельзя. Грани, собранные преимущественно из оформления,
    # отсеиваются уже после обхода.
    cand = [s for s in segs if s.role in ("contour", "thin")]
    serves = {id(s) for s in cand if _serves_dim(s, dims)}

    # дуги переводятся без притягивания к кластерам: их концы не лежат на
    # размерных линиях, привязка идёт через общий узел с прямыми
    def M(px, py):
        return (px * scale, H * scale - py * scale)

    arcs_m = []
    for a in arcs or ():
        arcs_m.append({"p": M(*a.start()), "q": M(*a.end()),
                       "sw": -a.sweep(), "c": M(a.cx, a.cy),
                       "r": a.r * scale})

    polys, inloop, in_poly_arcs = build_contours(cand, X, Y, serves=serves,
                                                 arcs_m=arcs_m)
    for p in polys:
        m.polys.append((p, "OUTLINE"))

    for s in segs:
        if id(s) in inloop:
            continue                        # уже вошёл в замкнутый контур
        if _serves_dim(s, dims):
            continue                        # заменяется объектом DIMENSION
        layer = "OUTLINE" if s.role == "contour" else ROLE_LAYER.get(s.role,
                                                                     "THIN")
        m.lines.append((X(s.x1), Y(s.y1), X(s.x2), Y(s.y2), layer))

    for c in circles:
        m.circles.append((X(c.cx), Y(c.cy), c.r * scale, "OUTLINE"))

    for i, a in enumerate(arcs or ()):
        if i in in_poly_arcs:
            continue          # дуга уже вошла в замкнутую полилинию
        # ось Y на чертеже направлена вверх, поэтому углы меняют знак,
        # а направление обхода - на противоположное
        d0, d1 = -math.degrees(a.a0), -math.degrees(a.a1)
        start, end = (d1, d0) if a.sweep() > 0 else (d0, d1)
        m.arcs.append((X(a.cx), Y(a.cy), a.r * scale,
                       start % 360.0, end % 360.0, "OUTLINE"))

    for d in dims:
        if d.vertical:
            x = X(d.line)
            p1 = (x, Y(d.a))
            p2 = (x, Y(d.b))
            m.dims.append((p1, p2, (x, p1[1]), 90.0, d.value))
        else:
            y = Y(d.line)
            p1 = (X(d.a), y)
            p2 = (X(d.b), y)
            m.dims.append((p1, p2, (p1[0], y), 0.0, d.value))

    if put_text:
        used = {id(d.num) for d in dims if d.num is not None}
        for nb in numbers:
            if id(nb) in used:
                continue           # это число уже стало объектом DIMENSION
            m.texts.append((str(nb.value), X(nb.x), Y(nb.y),
                            max(2.0, nb.h * scale * 0.9)))
    return m


def _serves_dim(s, dims, tol=6.0, reach=10.0):
    """Отрезок является размерной или выносной линией.

    Кромку детали от выносной линии отличает то, что выносная доходит до
    размерной линии, а кромка - нет. Без этого различения контур детали
    выбрасывается вместе с оформлением: ведь размеры как раз и берутся
    от кромок.
    """
    for d in dims:
        if d.vertical:
            # размерная линия вертикальна и стоит на уровне d.line
            if s.kind == "v" and abs(s.x1 - d.line) < tol:
                lo, hi = sorted((s.y1, s.y2))
                if lo - reach <= d.a and d.b <= hi + reach:
                    return True
            # выносные горизонтальны и дотягиваются до размерной линии
            if s.kind == "h" and (abs(s.y1 - d.a) < tol or abs(s.y1 - d.b) < tol):
                lo, hi = sorted((s.x1, s.x2))
                if lo - reach <= d.line <= hi + reach:
                    return True
        else:
            if s.kind == "h" and abs(s.y1 - d.line) < tol:
                lo, hi = sorted((s.x1, s.x2))
                if lo - reach <= d.a and d.b <= hi + reach:
                    return True
            if s.kind == "v" and (abs(s.x1 - d.a) < tol or abs(s.x1 - d.b) < tol):
                lo, hi = sorted((s.y1, s.y2))
                if lo - reach <= d.line <= hi + reach:
                    return True
    return False


# =====================================================================
#  Вывод DXF
# =====================================================================
def to_dxf(model, path, text_h=3.5):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from gostcad import new_doc
    from gostcad.draw import dim_h, dim_v, text as put

    doc = new_doc(text_h=text_h, ltscale=2.0)
    msp = doc.modelspace()

    for pts, layer in model.polys:
        fmt = "xyb" if pts and len(pts[0]) == 3 else "xy"
        msp.add_lwpolyline(pts, format=fmt, close=True,
                           dxfattribs={"layer": layer})
    for x1, y1, x2, y2, layer in model.lines:
        if math.dist((x1, y1), (x2, y2)) < 0.05:
            continue
        msp.add_line((x1, y1), (x2, y2), dxfattribs={"layer": layer})
    for cx, cy, r, layer in model.circles:
        msp.add_circle((cx, cy), r, dxfattribs={"layer": layer})
    for cx, cy, r, s0, s1, layer in model.arcs:
        msp.add_arc((cx, cy), r, s0, s1, dxfattribs={"layer": layer})
    for p1, p2, base, ang, _v in model.dims:
        if ang == 90.0:
            dim_v(msp, p1, p2, base[0])
        else:
            dim_h(msp, p1, p2, base[1])
    for s, x, y, h in model.texts:
        put(msp, s, x, y, h)

    doc.saveas(path)
    return path
