"""Цвет: разбор записи, разница так, как её видит глаз, и семейство для группировки.

Разница — CIEDE2000, стандарт для «насколько два цвета отличаются на вид». Простая евклидова
разница в Lab (ΔE76) в насыщенных синих и пурпурных завышает расстояние в разы, и «почти
токен» там превращался бы в «мимо системы».

Ориентиры для CIEDE2000: до 1 — глазом не отличить, 1–2 — отличает внимательный глаз
рядом, 2–3,5 — заметно при сравнении, больше 5 — это другой цвет.
"""

from __future__ import annotations

import colorsys
import math
import re

# Порог «почти токен»: заметно только при сравнении бок о бок, в макете — тот же цвет.
NEAR_DE = 3.0
# Насколько может отличаться прозрачность, чтобы цвет всё ещё считался почти токеном.
NEAR_ALPHA = 5

_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_RGBA = re.compile(r"^rgba?\(\s*([\d.]+)%?\s*[, ]\s*([\d.]+)%?\s*[, ]\s*([\d.]+)%?\s*(?:[,/]\s*([\d.]+%?)\s*)?\)$", re.I)


def parse(value) -> tuple[str, int] | None:
    """«#RRGGBB», «#RGB», «#RRGGBBAA», «rgba(…)» → (RRGGBB, непрозрачность 0–100). Иначе None."""
    s = str(value or "").strip()
    m = _HEX.match(s)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        alpha = round(int(h[6:8], 16) / 255 * 100) if len(h) == 8 else 100
        return h[:6].upper(), alpha
    m = _RGBA.match(s)
    if m:
        r, g, b = (max(0, min(255, round(float(x)))) for x in m.group(1, 2, 3))
        a = m.group(4)
        if a is None:
            alpha = 100
        elif a.endswith("%"):
            alpha = round(float(a[:-1]))
        else:
            alpha = round(float(a) * 100)
        return "%02X%02X%02X" % (r, g, b), max(0, min(100, alpha))
    return None


def label(color: str, alpha: int) -> str:
    """Как цвет показывается человеку: #RRGGBB или #RRGGBB · 40%."""
    return f"#{color}" if alpha >= 100 else f"#{color} · {alpha}%"


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lab(color: str) -> tuple[float, float, float]:
    r, g, b = (_lin(int(color[i:i + 2], 16) / 255) for i in (0, 2, 4))
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * b)
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def de2000(lab1, lab2) -> float:
    """Разница двух цветов в Lab по CIEDE2000."""
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    cm = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(cm ** 7 / (cm ** 7 + 25 ** 7)))
    a1p, a2p = a1 * (1 + g), a2 * (1 + g)
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360
    dlp = l2 - l1
    dcp = c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    else:
        dh = h2p - h1p
        if dh > 180:
            dh -= 360
        elif dh < -180:
            dh += 360
        dhp = dh
    dHp = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp) / 2)
    lpm = (l1 + l2) / 2
    cpm = (c1p + c2p) / 2
    if c1p * c2p == 0:
        hpm = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hpm = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hpm = (h1p + h2p + 360) / 2
    else:
        hpm = (h1p + h2p - 360) / 2
    t = (1 - 0.17 * math.cos(math.radians(hpm - 30)) + 0.24 * math.cos(math.radians(2 * hpm))
         + 0.32 * math.cos(math.radians(3 * hpm + 6)) - 0.20 * math.cos(math.radians(4 * hpm - 63)))
    dtheta = 30 * math.exp(-(((hpm - 275) / 25) ** 2))
    rc = 2 * math.sqrt(cpm ** 7 / (cpm ** 7 + 25 ** 7))
    sl = 1 + 0.015 * (lpm - 50) ** 2 / math.sqrt(20 + (lpm - 50) ** 2)
    sc = 1 + 0.045 * cpm
    sh = 1 + 0.015 * cpm * t
    rt = -math.sin(math.radians(2 * dtheta)) * rc
    return math.sqrt((dlp / sl) ** 2 + (dcp / sc) ** 2 + (dHp / sh) ** 2 + rt * (dcp / sc) * (dHp / sh))


def family(color: str) -> str:
    """Семейство для группировки в списке: White, Black, Neutral или оттенок."""
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    h *= 360
    if s <= 0.08:
        if l >= 0.93:
            return "White"
        if l <= 0.12:
            return "Black"
        return "Neutral"
    for hi, name in ((14, "Red"), (42, "Orange"), (70, "Yellow"), (157, "Green"), (196, "Teal"),
                     (248, "Blue"), (288, "Purple"), (330, "Magenta")):
        if h < hi:
            return name
    return "Red"
