# -*- coding: utf-8 -*-
"""
Детектор примитивов.

В отличие от голого Хафа здесь каждый отрезок дополнительно измеряется по
растру: толщина штриха и доля заливки вдоль оси. Это и даёт разделение на
основную линию, тонкую (размерную/выносную) и осевую штрихпунктирную -
то, без чего чертёж нельзя разложить по слоям.
"""
import math
from dataclasses import dataclass, field

from .page import hough_rows

import cv2
import numpy as np


@dataclass
class Seg:
    x1: float
    y1: float
    x2: float
    y2: float
    kind: str                 # 'h' | 'v' | 'o'
    width: float = 0.0        # толщина штриха, px
    fill: float = 1.0         # доля закрашенности вдоль оси
    role: str = "?"           # contour | thin | center | leader
    meta: dict = field(default_factory=dict)

    @property
    def length(self):
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)

    def pos(self):
        """Координата оси: y для горизонтали, x для вертикали."""
        return self.y1 if self.kind == "h" else self.x1

    def span(self):
        return ((self.x1, self.x2) if self.kind == "h"
                else (self.y1, self.y2))


@dataclass
class Circ:
    cx: float
    cy: float
    r: float
    score: float = 0.0


# =====================================================================
#  Отрезки
# =====================================================================
def detect_segments(bw, min_len=25, max_gap=5, snap_deg=2.0, merge_gap=4.0):
    lines = cv2.HoughLinesP(bw, 1, np.pi / 1440, threshold=40,
                            minLineLength=min_len, maxLineGap=max_gap)
    raw = []
    for x1, y1, x2, y2 in hough_rows(lines, 4):
        a = math.degrees(math.atan2(y2 - y1, x2 - x1))
        if abs(a) < snap_deg or abs(abs(a) - 180) < snap_deg:
            y = (y1 + y2) / 2.0
            raw.append(Seg(min(x1, x2), y, max(x1, x2), y, "h"))
        elif abs(abs(a) - 90) < snap_deg:
            x = (x1 + x2) / 2.0
            raw.append(Seg(x, min(y1, y2), x, max(y1, y2), "v"))
        else:
            raw.append(Seg(float(x1), float(y1), float(x2), float(y2), "o"))
    segs = _merge(raw, tol=3.0, gap=merge_gap)
    for s in segs:
        _measure(s, bw)
        _role(s)
    segs = _fuse_edges(segs)
    return segs


def _fuse_edges(segs):
    """Толстый штрих даёт Хафу две линии - по своим краям. Их надо слить
    в одну осевую, иначе контур удваивается и не замыкается."""
    out = list(segs)
    for kind in ("h", "v"):
        group = [s for s in out if s.kind == kind]
        group.sort(key=lambda s: s.pos())
        dead = set()
        for i, s in enumerate(group):
            if id(s) in dead:
                continue
            for t in group[i + 1:]:
                if id(t) in dead:
                    continue
                gap = t.pos() - s.pos()
                if gap > max(s.width, t.width) + 1.5:
                    break
                a0, a1 = sorted(s.span())
                b0, b1 = sorted(t.span())
                ov = min(a1, b1) - max(a0, b0)
                # сливать только почти совпадающие линии: иначе кромка
                # детали срастается со своей выносной в один длинный
                # отрезок и перестаёт быть кромкой
                if ov < 0.7 * max(a1 - a0, b1 - b0):
                    continue
                mid = (s.pos() + t.pos()) / 2.0
                lo, hi = min(a0, b0), max(a1, b1)
                if kind == "h":
                    s.x1, s.x2, s.y1, s.y2 = lo, hi, mid, mid
                else:
                    s.y1, s.y2, s.x1, s.x2 = lo, hi, mid, mid
                s.width = max(s.width, t.width)
                s.fill = max(s.fill, t.fill)
                dead.add(id(t))
        out = [s for s in out if id(s) not in dead]
    return out


def _merge(segs, tol, gap):
    out = []
    for kind in ("h", "v"):
        buckets = {}
        for s in segs:
            if s.kind != kind:
                continue
            buckets.setdefault(round(s.pos() / tol), []).append(s)
        for items in buckets.values():
            axis = float(np.mean([s.pos() for s in items]))
            spans = sorted(tuple(sorted(s.span())) for s in items)
            cur = list(spans[0])
            merged = []
            for a, b in spans[1:]:
                if a <= cur[1] + gap:
                    cur[1] = max(cur[1], b)
                else:
                    merged.append(tuple(cur))
                    cur = [a, b]
            merged.append(tuple(cur))
            for a, b in merged:
                out.append(Seg(a, axis, b, axis, "h") if kind == "h"
                           else Seg(axis, a, axis, b, "v"))
    out += [s for s in segs if s.kind == "o"]
    return out


def _measure(s, bw, samples=41, probe=9):
    """Толщина штриха и заливка вдоль оси - по перпендикулярным срезам."""
    H, W = bw.shape
    n = max(7, min(samples, int(s.length // 3)))
    widths, hits = [], 0
    for i in range(n):
        t = (i + 0.5) / n
        x = s.x1 + (s.x2 - s.x1) * t
        y = s.y1 + (s.y2 - s.y1) * t
        if s.kind == "h":
            xi = int(round(x))
            col = [int(round(y)) + d for d in range(-probe, probe + 1)]
            vals = [bw[c, xi] > 0 for c in col if 0 <= c < H and 0 <= xi < W]
        else:
            yi = int(round(y))
            row = [int(round(x)) + d for d in range(-probe, probe + 1)]
            vals = [bw[yi, c] > 0 for c in row if 0 <= c < W and 0 <= yi < H]
        if not vals:
            continue
        mid = len(vals) // 2
        if not any(vals[max(0, mid - 1):mid + 2]):
            continue
        hits += 1
        k = mid
        while k > 0 and vals[k - 1]:
            k -= 1
        j = mid
        while j < len(vals) - 1 and vals[j + 1]:
            j += 1
        widths.append(j - k + 1)
    s.fill = hits / float(n)
    s.width = float(np.median(widths)) if widths else 0.0


def _role(s):
    if s.kind == "o":
        s.role = "leader"
    elif s.fill < 0.88:
        s.role = "center"          # штрихпунктир: линия рвётся
    else:
        s.role = "solid"           # окончательно решится по толщине


def split_by_weight(segs):
    """Разделение сплошных на основные и тонкие по толщине штриха.

    Порог не задаётся константой: берётся середина между двумя модами
    распределения толщин, потому что толщина зависит от разрешения скана.
    """
    ws = [s.width for s in segs if s.role == "solid" and s.width > 0]
    if len(ws) < 6:
        thr = 3.0
    else:
        a = np.array(ws, dtype=float)
        lo, hi = a.min(), a.max()
        if hi - lo < 1.2:
            thr = hi + 1.0                   # всё одной толщины
        else:
            # одномерный k-means на 2 кластера
            c1, c2 = lo, hi
            for _ in range(30):
                m = (c1 + c2) / 2.0
                g1, g2 = a[a <= m], a[a > m]
                if len(g1) == 0 or len(g2) == 0:
                    break
                c1, c2 = g1.mean(), g2.mean()
            thr = (c1 + c2) / 2.0
    for s in segs:
        if s.role == "solid":
            s.role = "contour" if s.width > thr else "thin"
    return thr


# =====================================================================
#  Окружности: поиск по центровым крестам
# =====================================================================
def _crosses(segs, margin=14.0):
    """Точки пересечения горизонтали и вертикали внутри обеих линий.

    По ГОСТ 2.307 центр отверстия обозначается пересечением центровых
    линий, поэтому искать отверстия надо именно там, а не Хафом по всему
    листу - иначе буквы «О» и «Ф» дают десятки ложных срабатываний.
    """
    hs = [s for s in segs if s.kind == "h" and s.role in ("center", "thin",
                                                          "contour")]
    vs = [s for s in segs if s.kind == "v" and s.role in ("center", "thin",
                                                          "contour")]
    pts = []
    for h in hs:
        hx0, hx1 = sorted((h.x1, h.x2))
        for v in vs:
            vy0, vy1 = sorted((v.y1, v.y2))
            x, y = v.x1, h.y1
            if not (hx0 - margin <= x <= hx1 + margin):
                continue
            if not (vy0 - margin <= y <= vy1 + margin):
                continue
            # осевая часто прервана самим отверстием, поэтому пересечение
            # ищется с запасом; окончательно решает радиальный профиль
            din = min(x - hx0, hx1 - x, y - vy0, vy1 - y)
            pts.append((x, y, din))
    # склеить близкие
    keep = []
    for x, y, d in sorted(pts, key=lambda t: -t[2]):
        if any(math.hypot(x - k[0], y - k[1]) < 6 for k in keep):
            continue
        keep.append((x, y, d))
    return [(x, y) for x, y, _ in keep]


def _radial_profile(bw, cx, cy, rmax, n_ang=48):
    """Доля закрашенных направлений на каждом радиусе."""
    H, W = bw.shape
    prof = []
    for r in range(2, int(rmax) + 1):
        hit = 0
        for i in range(n_ang):
            a = 2 * math.pi * i / n_ang
            x = int(round(cx + r * math.cos(a)))
            y = int(round(cy + r * math.sin(a)))
            if 0 <= x < W and 0 <= y < H and bw[y, x] > 0:
                hit += 1
        prof.append(hit / float(n_ang))
    return prof


def circles_at_crosses(bw, segs, rmax=60, min_ring=0.75, max_inner=0.45):
    """Отверстия: кольцо тушью вокруг центрового креста при пустой середине."""
    out = []
    for cx, cy in _crosses(segs):
        prof = _radial_profile(bw, cx, cy, rmax)
        if not prof:
            continue
        best = None
        for i in range(1, len(prof) - 4):
            v = prof[i]
            if i + 2 < 3 or v < min_ring:
                continue
            # признак отверстия - ПИК профиля: тушь нарастает к кольцу,
            # держится на его толщине и резко пропадает снаружи. У
            # пересечения линий профиль монотонно спадает от центра.
            if v <= prof[i - 1] * 1.15:
                continue
            j = i
            while j + 1 < len(prof) and prof[j + 1] >= 0.6 * v:
                j += 1
            if j - i + 1 > 6:                  # слишком толсто для контура
                continue
            tail = prof[j + 1: j + 4]
            if not tail or max(tail) >= 0.6 * v:
                continue
            r = (i + 2 + j + 2) / 2.0          # середина кольца
            if best is None or v > best[1]:
                best = (r, v)
        if best:
            out.append(Circ(float(cx), float(cy), float(best[0]),
                            round(best[1], 3)))
    keep = []
    for c in sorted(out, key=lambda c: -c.score):
        if any(math.hypot(c.cx - k.cx, c.cy - k.cy) < max(4, 0.5 * k.r)
               for k in keep):
            continue
        keep.append(c)
    return keep


# =====================================================================
#  Окружности
# =====================================================================
def detect_circles(bw, rmin=4, rmax=80, ring_tol=2, min_score=0.72):
    """Хаф плюс обязательная проверка кольца по растру.

    Голый HoughCircles на чертежах даёт десятки ложных срабатываний на
    пересечениях линий; проверка требует, чтобы тушь реально шла по всей
    окружности.
    """
    inv = 255 - bw
    c = cv2.HoughCircles(inv, cv2.HOUGH_GRADIENT, dp=1, minDist=10,
                         param1=120, param2=16, minRadius=rmin,
                         maxRadius=rmax)
    H, W = bw.shape
    out = []
    for cx, cy, r in hough_rows(c, 3):
        n = max(24, int(2 * math.pi * r))
        hit = 0
        for i in range(n):
            a = 2 * math.pi * i / n
            ok = False
            for dr in range(-ring_tol, ring_tol + 1):
                x = int(round(cx + (r + dr) * math.cos(a)))
                y = int(round(cy + (r + dr) * math.sin(a)))
                if 0 <= x < W and 0 <= y < H and bw[y, x] > 0:
                    ok = True
                    break
            hit += ok
        score = hit / float(n)
        if score >= min_score:
            out.append(Circ(float(cx), float(cy), float(r), round(score, 3)))
    # снять вложенные дубли одного и того же круга
    out.sort(key=lambda c: (-c.score, c.r))
    keep = []
    for c in out:
        if any(math.hypot(c.cx - k.cx, c.cy - k.cy) < max(3, 0.3 * k.r)
               and abs(c.r - k.r) < max(3, 0.25 * k.r) for k in keep):
            continue
        keep.append(c)
    return keep


# =====================================================================
#  Текстовые области
# =====================================================================
def text_boxes(bw, scale=2, pad=16, min_conf=25):
    """Прямоугольники любых надписей.

    Нужны, чтобы не принимать буквы «О», «Ф», «0» и цифру «8» за отверстия:
    Хаф на них срабатывает уверенно, отличить их от отверстия по форме
    нельзя, а по принадлежности к строке текста - можно.
    """
    from .solve import HAS_OCR, pytesseract
    if not HAS_OCR:
        return []
    img = cv2.resize(255 - bw, None, fx=scale, fy=scale,
                     interpolation=cv2.INTER_CUBIC)
    img = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT,
                             value=255)
    boxes = []
    for cfg in ("--psm 11", "--psm 6"):
        try:
            d = pytesseract.image_to_data(
                img, config=cfg, output_type=pytesseract.Output.DICT)
        except Exception:
            continue
        for i in range(len(d["text"])):
            if not d["text"][i].strip():
                continue
            try:
                conf = float(d["conf"][i])
            except (TypeError, ValueError):
                continue
            if conf < min_conf:
                continue
            boxes.append((
                (d["left"][i] - pad) / scale, (d["top"][i] - pad) / scale,
                d["width"][i] / scale, d["height"][i] / scale))
    return boxes


def drop_text_circles(circles, boxes, grow=3.0):
    """Убирает окружности, центр которых попал в надпись."""
    out = []
    for c in circles:
        inside = any(bx - grow <= c.cx <= bx + bw_ + grow
                     and by - grow <= c.cy <= by + bh + grow
                     for bx, by, bw_, bh in boxes)
        if not inside:
            out.append(c)
    return out


def circles_on_geometry(circles, segs, max_dist=None):
    """Оставляет окружности, привязанные к геометрии.

    Отверстие на чертеже всегда лежит на осевой линии или внутри контура;
    одинокий кружок посреди пустого поля - почти всегда мусор.
    """
    out = []
    for c in circles:
        lim = max_dist if max_dist else max(12.0, c.r * 3.0)
        near = False
        for s in segs:
            if s.role not in ("center", "contour"):
                continue
            if s.kind == "h":
                a, b = sorted((s.x1, s.x2))
                d = abs(c.cy - s.y1) if a - lim <= c.cx <= b + lim else 1e9
            elif s.kind == "v":
                a, b = sorted((s.y1, s.y2))
                d = abs(c.cx - s.x1) if a - lim <= c.cy <= b + lim else 1e9
            else:
                continue
            if d <= lim:
                near = True
                break
        if near:
            out.append(c)
    return out


# =====================================================================
#  Дуги
# =====================================================================
@dataclass
class Arc:
    cx: float
    cy: float
    r: float
    a0: float                 # начальный угол, рад
    a1: float                 # конечный угол, рад
    ccw: bool = True
    rms: float = 0.0

    def start(self):
        return (self.cx + self.r * math.cos(self.a0),
                self.cy + self.r * math.sin(self.a0))

    def end(self):
        return (self.cx + self.r * math.cos(self.a1),
                self.cy + self.r * math.sin(self.a1))

    def sweep(self):
        d = (self.a1 - self.a0) % (2 * math.pi)
        return d if self.ccw else d - 2 * math.pi


def _fit_circle(pts):
    """Алгебраическая подгонка окружности (Каса). Возвращает cx, cy, r, RMS."""
    p = np.asarray(pts, dtype=float)
    x, y = p[:, 0], p[:, 1]
    A = np.column_stack([2 * x, 2 * y, np.ones(len(p))])
    b = x * x + y * y
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy, c = sol
    r2 = c + cx * cx + cy * cy
    if r2 <= 0:
        return None
    r = math.sqrt(r2)
    d = np.hypot(x - cx, y - cy) - r
    return float(cx), float(cy), float(r), float(np.sqrt(np.mean(d * d)))


def detect_arcs(bw, rmin=10.0, rmax=400.0, win=9, min_sweep_deg=30.0,
                max_rms=1.6, min_pts=22, gap_pts=6, boxes=None):
    """Дуги по контурам туши через локальную кривизну.

    Вычитать прямые из растра и искать дуги в остатке бесполезно: Хаф
    забирает пологие части дуги себе, и она рассыпается на огрызки.
    Поэтому работа идёт от границы туши: в каждой точке по трём отсчётам
    строится окружность, участки с устойчивым радиусом объединяются
    и подгоняются методом наименьших квадратов.
    """
    cnts, _ = cv2.findContours(bw, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    arcs = []
    for c in cnts:
        pts = c[:, 0, :].astype(float)
        n = len(pts)
        if n < max(min_pts, 3 * win):
            continue
        rad = np.full(n, np.nan)
        for i in range(n):
            a, b, d = pts[(i - win) % n], pts[i], pts[(i + win) % n]
            fit = _fit_circle([a, b, d])
            if fit and rmin <= fit[2] <= rmax:
                rad[i] = fit[2]
        good = ~np.isnan(rad)
        if good.sum() < min_pts:
            continue
        # участки с устойчивым радиусом; сравнение идёт с медианой уже
        # набранного участка, а короткие сбои пропускаются - иначе дуга
        # рассыпается на огрызки от единичных выбросов
        runs, cur, miss = [], [], 0
        ref = None
        order = list(range(n)) + list(range(win))      # контур замкнут
        for i in order:
            ok = good[i] and (ref is None
                              or abs(rad[i] - ref) <= 0.30 * ref + 2.5)
            if ok:
                cur.append(i)
                miss = 0
                ref = float(np.median(rad[cur[-25:]]))
            else:
                miss += 1
                if miss <= gap_pts and cur:
                    continue
                if len(cur) >= min_pts:
                    runs.append(cur)
                cur, ref, miss = [], None, 0
        if len(cur) >= min_pts:
            runs.append(cur)

        for run in runs:
            sub = pts[run]
            fit = _fit_circle(sub)
            if not fit:
                continue
            cx, cy, r, rms = fit
            if not (rmin <= r <= rmax) or rms > max_rms:
                continue
            ang = np.unwrap(np.arctan2(sub[:, 1] - cy, sub[:, 0] - cx))
            sweep = float(ang[-1] - ang[0])
            deg = abs(math.degrees(sweep))
            if deg < min_sweep_deg or deg > 300.0:
                # почти полный круг - это буква «О», «0» или «8»;
                # настоящие отверстия ищутся отдельно, по центровым крестам
                continue
            if boxes and _in_box(cx, cy, boxes):
                continue                      # дуга внутри надписи - буква
            arcs.append(Arc(cx, cy, r,
                            float(ang[0]) % (2 * math.pi),
                            float(ang[-1]) % (2 * math.pi),
                            sweep > 0, round(rms, 2)))
    return _dedupe_arcs(arcs)


def _in_box(x, y, boxes, grow=4.0):
    for bx, by, bw_, bh in boxes:
        if bx - grow <= x <= bx + bw_ + grow and by - grow <= y <= by + bh + grow:
            return True
    return False


def _dedupe_arcs(arcs, tol=4.0):
    """Объединяет куски одной дуги вместо их выбрасывания.

    Дуга гиба часто распадается на две половины: устойчивость радиуса
    рвётся в середине. У половин одинаковые центр и радиус, поэтому
    простое удаление дубликатов оставляло от гиба половину и контур не
    замыкался. Здесь куски одной окружности сливаются по углу.
    """
    groups = []
    for a in sorted(arcs, key=lambda a: (-abs(a.sweep()), a.rms)):
        put = False
        for g in groups:
            k = g[0]
            if (math.hypot(a.cx - k.cx, a.cy - k.cy) < tol
                    and abs(a.r - k.r) < tol):
                g.append(a)
                put = True
                break
        if not put:
            groups.append([a])

    out = []
    for g in groups:
        if len(g) == 1:
            out.append(g[0])
            continue
        # центр и радиус берутся у самого длинного куска: усреднение с
        # короткими обрывками смещает радиус на несколько миллиметров
        lead = max(g, key=lambda a: (abs(a.sweep()), -a.rms))
        cx, cy, r = lead.cx, lead.cy, lead.r
        # объединяем угловые интервалы каждого куска
        spans = []
        for a in g:
            s0 = a.a0
            sw = a.sweep()
            spans.append((s0, s0 + sw) if sw > 0 else (s0 + sw, s0))
        spans = [(lo % (2 * math.pi), (lo % (2 * math.pi)) + (hi - lo))
                 for lo, hi in spans]
        spans.sort()
        merged = [list(spans[0])]
        for lo, hi in spans[1:]:
            if lo <= merged[-1][1] + math.radians(25):
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi])
        # склейка через ноль
        if len(merged) > 1 and merged[0][0] + 2 * math.pi <= merged[-1][1] + \
                math.radians(25):
            merged[0][0] = merged[-1][0] - 2 * math.pi
            merged.pop()
        for lo, hi in merged:
            if math.degrees(hi - lo) < 20 or math.degrees(hi - lo) > 300:
                continue
            out.append(Arc(cx, cy, r, lo % (2 * math.pi), hi % (2 * math.pi),
                           True, min(a.rms for a in g)))
    return out


def detect_arcs_vote(bw, rmin=10.0, rmax=200.0, win=9, cell=4.0,
                     min_votes=18, min_sweep_deg=30.0, ring_tol=2.0,
                     min_cover=0.55, gap_deg=40.0, boxes=None):
    """Дуги через голосование за центр кривизны.

    Обход контура по порядку ненадёжен: там, где к гибу примыкает выноска
    или осевая, цепочка уходит в сторону и дуга рвётся на куски. Здесь
    порядок не важен - каждая точка границы туши голосует за свой центр
    кривизны, а дуга собирается из всех точек, лежащих на найденной
    окружности, независимо от того, одной ли они цепочки.
    """
    cnts, _ = cv2.findContours(bw, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    pts, votes = [], {}
    for c in cnts:
        p = c[:, 0, :].astype(float)
        n = len(p)
        if n < 3 * win:
            continue
        for i in range(n):
            fit = _fit_circle([p[(i - win) % n], p[i], p[(i + win) % n]])
            if not fit:
                continue
            cx, cy, r, _ = fit
            if not (rmin <= r <= rmax):
                continue
            pts.append((p[i][0], p[i][1]))
            key = (int(cx / cell), int(cy / cell))
            votes.setdefault(key, []).append((cx, cy, r))
    if not pts:
        return []
    P = np.asarray(pts)

    peaks = []
    for key, vs in votes.items():
        if len(vs) < min_votes:
            continue
        a = np.asarray(vs)
        peaks.append((len(vs), float(np.median(a[:, 0])),
                      float(np.median(a[:, 1])), float(np.median(a[:, 2]))))
    peaks.sort(reverse=True)

    out = []
    for _cnt, cx, cy, r0 in peaks:
        if boxes and _in_box(cx, cy, boxes):
            continue
        if any(math.hypot(cx - a.cx, cy - a.cy) < cell * 1.5
               and abs(r0 - a.r) < 3.0 for a in out):
            continue
        d = np.hypot(P[:, 0] - cx, P[:, 1] - cy)
        sel = P[np.abs(d - r0) <= ring_tol]
        if len(sel) < min_votes:
            continue
        r = float(np.median(np.hypot(sel[:, 0] - cx, sel[:, 1] - cy)))
        ang = np.sort(np.arctan2(sel[:, 1] - cy, sel[:, 0] - cx) %
                      (2 * math.pi))
        # непрерывные угловые участки
        step = max(math.radians(8.0), 2.5 / max(r, 1.0))
        runs, cur = [], [ang[0]]
        for t in ang[1:]:
            if t - cur[-1] <= step:
                cur.append(t)
            else:
                runs.append(cur)
                cur = [t]
        runs.append(cur)
        if len(runs) > 1 and (ang[0] + 2 * math.pi) - runs[-1][-1] <= step:
            runs[0] = runs[-1] + [t + 2 * math.pi for t in runs[0]]
            runs.pop()
        # сшить участки, разорванные выноской или осевой, пересекающей гиб
        merged = [runs[0]]
        for run in runs[1:]:
            gap_ok = run[0] - merged[-1][-1] <= math.radians(gap_deg)
            # склеивать только до полуокружности с запасом: иначе разрыв
            # замыкается «через всю окружность» и дуга теряется целиком
            span_ok = run[-1] - merged[-1][0] <= math.radians(200.0)
            if gap_ok and span_ok:
                merged[-1] = merged[-1] + run
            else:
                merged.append(run)
        runs = merged
        for run in runs:
            sweep = run[-1] - run[0]
            deg = math.degrees(sweep)
            if deg < min_sweep_deg or deg > 300.0:
                continue
            # доля дуги, реально закрытая тушью
            need = max(6, int(abs(sweep) * r / 3.0))
            if len(run) < need * min_cover:
                continue
            out.append(Arc(cx, cy, r, run[0] % (2 * math.pi),
                           run[-1] % (2 * math.pi), True, 0.0))
    return out


def detect_arcs_all(bw, boxes=None, **kw):
    """Оба детектора вместе: обход контура и голосование за центр.

    Они ошибаются по-разному. Обход цепочки точнее по радиусу, но рвётся
    там, где к дуге примыкает выноска; голосование не зависит от
    связности, но чаще дробит дугу на участки. Объединение угловых
    интервалов на общей окружности берёт лучшее от обоих.
    """
    a = detect_arcs(bw, boxes=boxes)
    b = detect_arcs_vote(bw, boxes=boxes)
    out = []
    for arc in _dedupe_arcs(a + b, tol=6.0):
        sw = abs(arc.sweep())
        # стрелка прогиба: слегка выгнутая прямая на скане тоже даёт
        # «дугу» огромного радиуса, но почти нулевой стрелкой
        sag = arc.r * (1.0 - math.cos(sw / 2.0))
        if math.degrees(sw) < 40.0 or sag < 4.0:
            continue
        out.append(arc)
    return out
