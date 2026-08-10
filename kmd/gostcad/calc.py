# -*- coding: utf-8 -*-
"""
Развёртки и массы. Единственное место, где эти числа вычисляются:
в спецификацию и ведомость они попадают отсюда, а не переписываются руками.
"""
import math

RHO = 7850.0e-9      # кг/мм3, сталь


def bar_mass(d, length, n=1):
    """Масса стержня круглого сечения, кг."""
    return math.pi * d * d / 4.0 * length * RHO * n


def plate_mass(t, b, length, holes=(), n=1):
    """Масса полосы/листа с учётом отверстий, кг."""
    v = t * b * length
    for hd in holes:
        v -= math.pi * hd * hd / 4.0 * t
    return v * RHO * n


def hoop_development(a, b):
    """Квадратный хомут: две грани по a, две по b (с нахлёстом концов)."""
    return 2.0 * a + 2.0 * b


def bent_development(segments):
    """Развёртка гнутого элемента как сумма прямых участков."""
    return float(sum(segments))


def hook_development(height, leg, r_axis, d):
    """Развёртка подвески: три полуокружности и прямые участки.

    height - габарит по наружным точкам, leg - свес свободного конца
    выше центра гиба, r_axis - радиус гиба по оси стержня.
    """
    dy = height - 2.0 * (r_axis + d / 2.0)      # между центрами гибов
    return 2.0 * leg + 2.0 * dy + 3.0 * math.pi * r_axis


def fmt_kg(x):
    """Масса в формате спецификации: запятая, два знака (кг)."""
    return f"{x:.2f}".replace(".", ",")
