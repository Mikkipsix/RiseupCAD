# -*- coding: utf-8 -*-
"""
Табличный движок для спецификаций и ведомостей по ГОСТ 21.101.

Строки нумеруются с 1 сверху. Поддерживаются:
  - объединение ячеек по вертикали внутри одной графы;
  - дробные ячейки (сортамент над маркой стали), где линией дроби может
    служить сама межстрочная граница;
  - подчёркивание наименований разделов.
"""
from ezdxf.enums import TextEntityAlignment as TA

from .draw import text, est_width


class Table:
    def __init__(self, cols, n_rows, row_h=8.0, head_h=16.0, text_h=3.5,
                 origin=(0.0, 0.0)):
        """cols - список (ширина, заголовок) или (ширина, [строка1, строка2])."""
        self.widths = [c[0] for c in cols]
        self.titles = [c[1] for c in cols]
        self.n = n_rows
        self.row_h = row_h
        self.head_h = head_h
        self.th = text_h
        self.ox, self.oy = origin

        self.x = [0.0]
        for w in self.widths:
            self.x.append(self.x[-1] + w)
        self.w = self.x[-1]
        self.h = head_h + n_rows * row_h

        self._cells = []        # (row, col, text, align)
        self._merged = []       # (col, r1, r2)
        self._under = []        # (row, col, text)
        self._extra = []        # callables(msp) для произвольной геометрии
        self.warnings = []

    # ---------- система координат ----------
    def col_x(self, k):
        return self.ox + self.x[k]

    def col_mid(self, k):
        return self.ox + (self.x[k] + self.x[k + 1]) / 2.0

    def top(self):
        return self.oy + self.h

    def head_bottom(self):
        return self.top() - self.head_h

    def row_top(self, r):
        return self.head_bottom() - (r - 1) * self.row_h

    def row_mid(self, r):
        return self.row_top(r) - self.row_h / 2.0

    def row_bound(self, r):
        """Граница между строкой r и r+1."""
        return self.row_top(r) - self.row_h

    def cell_box(self, r, k):
        return (self.col_x(k), self.row_top(r) - self.row_h,
                self.col_x(k + 1), self.row_top(r))

    # ---------- наполнение ----------
    def cell(self, r, k, s, align="c"):
        self._cells.append((r, k, s, align))
        return self

    def row(self, r, values):
        """values - словарь {номер графы: текст}."""
        for k, s in values.items():
            self.cell(r, k, s)
        return self

    def merge(self, k, r1, r2):
        self._merged.append((k, r1, r2))
        return self

    def underline(self, r, k, s):
        self.cell(r, k, s)
        self._under.append((r, k, s))
        return self

    def merged_text(self, k, r1, r2, lines):
        """Текст по центру объединённой ячейки, одна или несколько строк."""
        self.merge(k, r1, r2)
        yc = (self.row_top(r1) + self.row_bound(r2)) / 2.0
        n = len(lines)
        for i, s in enumerate(lines):
            y = yc + (n - 1 - 2 * i) * self.th * 0.85
            self._extra.append(
                lambda msp, s=s, k=k, y=y: text(msp, s, self.col_mid(k), y,
                                                self.th))
        return self

    def fraction(self, k, r, top, bottom, prefix=None, suffix=None,
                 bar=None, merge_cell=True):
        """Дробная ячейка на границе строк r / r+1.

        bar = (x0, x1) в локальных координатах графы - рисуется своя короткая
        линия дроби; bar=None - линией дроби служит межстрочная граница
        (тогда merge_cell=False, чтобы граница осталась на месте).
        """
        if merge_cell:
            self.merge(k, r, r + 1)
        y = self.row_bound(r)
        x0 = self.col_x(k)
        cw = self.widths[k]

        def draw(msp, y=y, x0=x0, cw=cw, k=k):
            xl = x0 + 2.0
            if prefix:
                text(msp, prefix, xl, y, self.th, TA.MIDDLE_LEFT)
                xl += est_width(prefix, self.th) + 2.0
            if bar is not None:
                b0, b1 = x0 + bar[0], x0 + bar[1]
                msp.add_line((b0, y), (b1, y), dxfattribs={"layer": "TABLE"})
                xf = (b0 + b1) / 2.0
                xr = b1 + 3.0
            else:
                xr = x0 + cw - 2.0
                xf = (xl + xr) / 2.0
            text(msp, top, xf, y + self.th * 0.4, self.th, TA.BOTTOM_CENTER)
            text(msp, bottom, xf, y - self.th * 0.4, self.th, TA.TOP_CENTER)
            if suffix:
                text(msp, suffix, xr, y, self.th, TA.MIDDLE_LEFT)

        self._extra.append(draw)
        self._check(top, cw)
        self._check(bottom, cw)
        return self

    def custom(self, fn):
        self._extra.append(fn)
        return self

    # ---------- отрисовка ----------
    def _check(self, s, cw):
        if est_width(s, self.th) > cw - 2.0:
            self.warnings.append(
                f'текст "{s}" ~{est_width(s, self.th):.0f} мм при графе {cw:.0f} мм')

    def render(self, msp):
        x0, y0 = self.ox, self.oy
        # рамка
        msp.add_lwpolyline(
            [(x0, y0), (x0 + self.w, y0), (x0 + self.w, y0 + self.h),
             (x0, y0 + self.h)],
            format="xy", close=True, dxfattribs={"layer": "TABLE"})
        # вертикальные разделители
        for k in range(1, len(self.widths)):
            msp.add_line((self.col_x(k), y0), (self.col_x(k), y0 + self.h),
                         dxfattribs={"layer": "TABLE"})
        # низ шапки
        yh = self.head_bottom()
        msp.add_line((x0, yh), (x0 + self.w, yh), dxfattribs={"layer": "TABLE"})

        # межстрочные границы с учётом объединений
        ncol = len(self.widths)
        for r in range(1, self.n):
            y = self.row_bound(r)
            skip = {k for k, r1, r2 in self._merged if r1 <= r < r2}
            k = 0
            while k < ncol:
                if k in skip:
                    k += 1
                    continue
                j = k
                while j + 1 < ncol and (j + 1) not in skip:
                    j += 1
                msp.add_line((self.col_x(k), y), (self.col_x(j + 1), y),
                             dxfattribs={"layer": "TABLE"})
                k = j + 1

        # шапка
        for k, t in enumerate(self.titles):
            lines = t if isinstance(t, (list, tuple)) else [t]
            n = len(lines)
            for i, s in enumerate(lines):
                y = (self.top() - self.head_h / 2.0
                     + (n - 1 - 2 * i) * self.th * 0.85)
                text(msp, s, self.col_mid(k), y, self.th)
                self._check(s, self.widths[k])

        # содержание
        al = {"c": TA.MIDDLE_CENTER, "l": TA.MIDDLE_LEFT, "r": TA.MIDDLE_RIGHT}
        for r, k, s, a in self._cells:
            xk = {"c": self.col_mid(k), "l": self.col_x(k) + 2.0,
                  "r": self.col_x(k + 1) - 2.0}[a]
            text(msp, s, xk, self.row_mid(r), self.th, al[a])
            self._check(s, self.widths[k])

        # подчёркивание разделов
        for r, k, s in self._under:
            half = est_width(s, self.th) / 2.0 + 1.0
            y = self.row_mid(r) - self.th * 0.85
            msp.add_line((self.col_mid(k) - half, y),
                         (self.col_mid(k) + half, y),
                         dxfattribs={"layer": "TABLE"})

        for fn in self._extra:
            fn(msp)
        return self
