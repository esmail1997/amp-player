"""يولّد أيقونة البرنامج بملف ICO متعدد الأحجام.

لا يعتمد على Pillow ولا على أي صورة جاهزة: الشكل محسوب رياضياً (دوال
مسافة SDF) ثم يُعالَج بتنعيم الحواف، فيصلح من 16 إلى 256 بكسل.

الشكل: مثلث تشغيل أبيض + ثلاثة أقواس صوت إلى يمينه، على خلفية خضراء
مائلة للتركوازي مع تدرّج.

التشغيل:  python tools/make_icon.py
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

OUT = Path(__file__).resolve().parent / "amp_player.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)

# ---------------------------------------------------------------- الألوان
BG_TOP = (18, 184, 134)      # #12B886
BG_BOTTOM = (11, 114, 133)   # #0B7285
FG = (255, 255, 255)         # المثلث والأقواس
FG_DIM = (210, 245, 235)


def _sdf_round_rect(x: float, y: float, hw: float, hh: float, r: float) -> float:
    """مسافة تقريبية لمستطيل بزوايا دائرية (المركز 0,0)."""
    qx = abs(x) - (hw - r)
    qy = abs(y) - (hh - r)
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    inside = min(max(qx, qy), 0.0)
    return outside + inside - r


def _sdf_triangle(px: float, py: float, ax: float, ay: float,
                  bx: float, by: float, cx: float, cy: float) -> float:
    """مسافة تقريبية لنقطة داخل/خارج مثلث."""
    def edge(ex, ey, fx, fy):
        return (px - fx) * (ey - fy) - (py - fy) * (ex - fx)

    e1, e2, e3 = edge(ax, ay, bx, by), edge(bx, by, cx, cy), edge(cx, cy, ax, ay)
    if (e1 >= 0 and e2 >= 0 and e3 >= 0) or (e1 <= 0 and e2 <= 0 and e3 <= 0):
        # داخل المثلث: نرجع أقل مسافة سالبة تقريباً إلى أحد الأضلاع
        def dist(ex, ey, fx, fy):
            vx, vy = fx - ex, fy - ey
            wx, wy = px - ex, py - ey
            t = 0.0 if vx * vx + vy * vy == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / (vx * vx + vy * vy)))
            return math.hypot(wx - t * vx, wy - t * vy)
        return -min(dist(ax, ay, bx, by), dist(bx, by, cx, cy), dist(cx, cy, ax, ay))

    def dist(ex, ey, fx, fy):
        vx, vy = fx - ex, fy - ey
        wx, wy = px - ex, py - ey
        t = 0.0 if vx * vx + vy * vy == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / (vx * vx + vy * vy)))
        return math.hypot(wx - t * vx, wy - t * vy)

    return min(dist(ax, ay, bx, by), dist(bx, by, cx, cy), dist(cx, cy, ax, ay))


def _cover(d: float, px: float) -> float:
    """تحويل مسافة إلى تغطية (تنعيم حافّة بعرض بكسل واحد)."""
    return max(0.0, min(1.0, 0.5 - d / px))


def render(size: int) -> bytes:
    """يعيد بايتات RGBA لصورة حجمها size×size."""
    px = 1.0 / size
    half = 0.5
    radius = 0.215          # نصف قطر زوايا الخلفية
    # مثلث التشغيل
    tri = (-0.14, -0.20, -0.14, 0.20, 0.24, 0.0)
    # مركز وأقواس الصوت (أقواس مفتوحة نصف دائرة نحو اليمين)
    arcs = [(0.26, 0.115), (0.385, 0.155), (0.51, 0.195)]  # (نصف قطر، سماكة)

    buf = bytearray(size * size * 4)
    for j in range(size):
        y = -half + (j + 0.5) * px          # من الأعلى
        for i in range(size):
            x = -half + (i + 0.5) * px
            bg_cov = _cover(_sdf_round_rect(x, y, half, half, radius), px)
            if bg_cov <= 0.0:
                continue                     # شفاف تماماً (خارج الأيقونة)

            # تدرّج الخلفية
            t = max(0.0, min(1.0, (y + half) / (2 * half)))
            r0 = BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t
            g0 = BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t
            b0 = BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t

            # قوس مفتوح: نرسم نصف الدائرة اليمنى فقط (زاوية من -80° إلى +80°)
            fg_a = 0.0
            for cx, w in arcs:
                dist_ring = abs(math.hypot(x - cx, y) - w)
                ang = math.degrees(math.atan2(y, x - cx))
                if -78.0 <= ang <= 78.0:
                    fg_a = max(fg_a, _cover(dist_ring - w * 0.42, px))

            # مثلث التشغيل
            d_tri = _sdf_triangle(x, y, *tri)
            tri_cov = _cover(d_tri, px)
            fg_a = max(fg_a, tri_cov * 1.0)

            # دمج الطبقة الأمامية على الخلفية
            r1 = r0 + (FG[0] - r0) * fg_a
            g1 = g0 + (FG[1] - g0) * fg_a
            b1 = b0 + (FG[2] - b0) * fg_a

            idx = (j * size + i) * 4
            buf[idx] = int(b1 + 0.5)
            buf[idx + 1] = int(g1 + 0.5)
            buf[idx + 2] = int(r1 + 0.5)
            buf[idx + 3] = int(255 * bg_cov + 0.5)
    return bytes(buf)


def to_bmp(rgba: bytes, size: int) -> bytes:
    """يحوّل RGBA إلى تنسيق BMP داخل ICO (رأس + بيانات + قناع AND)."""
    header = struct.pack(
        "<IiiHHIIiiII",
        40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0,
    )
    rows = []
    for y in range(size - 1, -1, -1):        # من الأسفل لأعلى كما يتطلّب BMP
        start = y * size * 4
        row = bytearray()
        for x in range(size):
            o = start + x * 4
            row += bytes((rgba[o], rgba[o + 1], rgba[o + 2], rgba[o + 3]))
        rows.append(bytes(row))
    # قناع AND: نصف الدقيقة لكل بكسل، مصطفّ إلى 4 بايت
    mask_row_bytes = ((size + 31) // 32) * 4
    masks = []
    for y in range(size - 1, -1, -1):
        bits = bytearray(mask_row_bytes)
        for x in range(size):
            a = rgba[(y * size + x) * 4 + 3]
            if a < 128:
                bits[x // 8] |= 0x80 >> (x % 8)
        masks.append(bytes(bits))
    return header + b"".join(rows) + b"".join(masks)


def build() -> Path:
    images = []
    for s in SIZES:
        images.append(to_bmp(render(s), s))
    count = len(SIZES)
    out = bytearray(struct.pack("<HHH", 0, 1, count))
    offset = 6 + 16 * count
    for s, img in zip(SIZES, images):
        b = 0 if s >= 256 else s
        out += struct.pack(
            "<BBBBHHII", b, b, 0, 0, 1, 32, len(img), offset
        )
        offset += len(img)
    for img in images:
        out += img
    OUT.write_bytes(bytes(out))
    return OUT


if __name__ == "__main__":
    p = build()
    print(f"{p} ({p.stat().st_size} bytes)")
