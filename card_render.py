# -*- coding: utf-8 -*-
"""通用牌阵绘制：N 张牌按网格排，每张上方标位置名、下方标位置含义。

单张时牌画大、牌义写在牌内；三张及以上画小牌，牌义放在牌下，
牌位标签统一放在牌上方，像桌上的牌阵照片。
"""
from __future__ import annotations

import math
import os
import random
from datetime import datetime

from PIL import Image, ImageDraw, ImageFilter, ImageFont

PAPER = (243, 235, 217)
PAPER_DEEP = (233, 222, 199)
INK = (45, 38, 32)
INK_SOFT = (104, 92, 78)
INK_FAINT = (150, 138, 120)
CLAY = (166, 72, 56)
OLIVE = (92, 104, 70)
BRASS = (144, 114, 64)

# 牌名/标题可选字体。罗马数字不跟着换，行楷和舒体写 V、I 会歪。
FONT_STYLES = {
    "楷体": ("C:/Windows/Fonts/STKAITI.TTF", "C:/Windows/Fonts/simkai.ttf"),
    "隶书": ("C:/Windows/Fonts/SIMLI.TTF",),
    "行楷": ("C:/Windows/Fonts/STXINGKA.TTF",),
    "舒体": ("C:/Windows/Fonts/FZSTK.TTF",),
    "姚体": ("C:/Windows/Fonts/FZYTK.TTF",),
    "中宋": ("C:/Windows/Fonts/STZHONGS.TTF",),
    "新魏": ("C:/Windows/Fonts/STXINWEI.TTF",),
    "仿宋": ("C:/Windows/Fonts/STFANGSO.TTF",),
}
DEFAULT_FONT_STYLE = "舒体"
DEFAULT_SMALL_STYLE = "楷体"
_ACTIVE_KAI = FONT_STYLES[DEFAULT_FONT_STYLE]
_ACTIVE_SMALL = FONT_STYLES[DEFAULT_SMALL_STYLE]
_NUM = ("C:/Windows/Fonts/STSONG.TTF", "C:/Windows/Fonts/simsun.ttc")


def use_font_style(name: str, small: str | None = None) -> tuple[str, str]:
    """切字体。name 管大牌名和标题，small 管牌阵里的小牌名。

    认不出就各退回默认，返回实际用上的两个名字。
    """
    global _ACTIVE_KAI, _ACTIVE_SMALL
    key = (name or "").strip()
    _ACTIVE_KAI = FONT_STYLES.get(key, FONT_STYLES[DEFAULT_FONT_STYLE])
    big = key if key in FONT_STYLES else DEFAULT_FONT_STYLE

    if small is None:
        _ACTIVE_SMALL = FONT_STYLES[DEFAULT_SMALL_STYLE]
        return big, DEFAULT_SMALL_STYLE
    key2 = small.strip()
    _ACTIVE_SMALL = FONT_STYLES.get(key2, FONT_STYLES[DEFAULT_SMALL_STYLE])
    return big, (key2 if key2 in FONT_STYLES else DEFAULT_SMALL_STYLE)


_KAI = _ACTIVE_KAI
_SONG = ("C:/Windows/Fonts/STSONG.TTF", "C:/Windows/Fonts/simsun.ttc",
         "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc")


def _load_first(paths, size: int):
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return None


def _font(size: int, kind: str = "song"):
    if kind == "kai_small":
        font = _load_first(_ACTIVE_SMALL, size)
        if font:
            return font
    if kind == "kai":
        font = _load_first(_ACTIVE_KAI, size)
        if font:
            return font
    if kind == "num":
        font = _load_first(_NUM, size)
        if font:
            return font
    if kind in ("kai", "kai_small", "num", "song"):
        font = _load_first(_SONG, size)
        if font:
            return font
    try:
        from astrbot.core.utils.t2i.local_strategy import FontManager

        return FontManager.get_font(size, bold=False)
    except Exception:
        pass
    for name in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _paper(width: int, height: int) -> Image.Image:
    """米色纸：低频色斑 + 细颗粒 + 淡霉斑 + 一道折痕。"""
    img = Image.new("RGB", (width, height), PAPER)
    small = Image.new("RGB", (max(2, width // 8), max(2, height // 8)), PAPER)
    sd = ImageDraw.Draw(small, "RGBA")
    rnd = random.Random(width * 31 + height)
    for _ in range(int(small.width * small.height / 24)):
        x, y = rnd.uniform(0, small.width), rnd.uniform(0, small.height)
        r = rnd.uniform(2, 9)
        tint = rnd.choice([(232, 220, 196), (250, 244, 228), (226, 212, 186), (246, 238, 218)])
        sd.ellipse([x - r, y - r, x + r, y + r], fill=tint + (rnd.randint(30, 90),))
    small = small.resize((width, height), Image.BICUBIC)
    small = small.filter(ImageFilter.GaussianBlur(max(2, int(width * 0.012))))
    img = Image.blend(img, small, 0.55)

    noise = Image.effect_noise((width, height), 14).convert("L")
    noise = noise.filter(ImageFilter.GaussianBlur(0.6))
    img = Image.blend(img, Image.merge("RGB", (noise, noise, noise)), 0.035)

    fox = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fox)
    for _ in range(rnd.randint(3, 6)):
        cx, cy = rnd.uniform(0, width), rnd.uniform(0, height)
        rx = rnd.uniform(width * 0.02, width * 0.06)
        ry = rx * rnd.uniform(0.5, 1.1)
        fd.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=(186, 150, 104, rnd.randint(8, 16)))
    fox = fox.filter(ImageFilter.GaussianBlur(int(width * 0.006)))
    img.paste(fox, (0, 0), fox)
    return img.convert("RGBA")


def _frame_wash(img: Image.Image) -> None:
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse([-w * 0.3, -h * 0.3, w * 1.3, h * 1.3], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(int(min(w, h) * 0.14)))
    inv = Image.eval(mask, lambda v: 255 - v)
    wash = Image.new("RGBA", (w, h), (198, 178, 144, 90))
    wash.putalpha(inv.point(lambda v: int(v * 90 / 255)))
    img.paste(wash, (0, 0), wash)


def _tokens(text: str) -> list[str]:
    out, buf = [], ""
    for ch in text:
        if ch.isascii() and (ch.isalnum() or ch in "-_./:%"):
            buf += ch
            continue
        if buf:
            out.append(buf)
            buf = ""
        out.append(ch)
    if buf:
        out.append(buf)
    return out


NO_LINE_START = "。，、；：？！）」』】…·"


def _avoid_orphan_punct(lines: list[str]) -> list[str]:
    """行首不许是标点：把那个标点挪回上一行行尾。"""
    out: list[str] = []
    for line in lines:
        if out and line and line[0] in NO_LINE_START:
            out[-1] = out[-1] + line[0]
            line = line[1:]
        if line:
            out.append(line)
    return out


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    lines: list[str] = []
    for raw in (text or "").splitlines() or [""]:
        if not raw:
            continue
        buf = ""
        for token in _tokens(raw):
            candidate = buf + token
            if draw.textlength(candidate, font=font) <= max_w or not buf:
                buf = candidate
            else:
                lines.append(buf.rstrip())
                buf = "" if token.isspace() else token
        if buf.strip():
            lines.append(buf.rstrip())
    return _avoid_orphan_punct(lines)


def _ink(d, xy, text: str, font, fill) -> None:
    x, y = xy
    d.text((x + 0.5, y + 0.5), text, font=font, fill=(fill[0], fill[1], fill[2], 40))
    d.text((x, y), text, font=font, fill=fill)


def _center(d, text: str, font, y: float, fill, width: int, soak: bool = False) -> None:
    tw = d.textlength(text, font=font)
    if soak:
        _ink(d, (width / 2 - tw / 2, y), text, font, fill)
    else:
        d.text((width / 2 - tw / 2, y), text, font=font, fill=fill)


def _center_at(d, text: str, font, cx: float, y: float, fill, soak: bool = False) -> None:
    """按给定的列中心居中，而不是整张画布的中心。"""
    tw = d.textlength(text, font=font)
    if soak:
        _ink(d, (cx - tw / 2, y), text, font, fill)
    else:
        d.text((cx - tw / 2, y), text, font=font, fill=fill)


def _spaced(d, text: str, font, y: float, fill, width: int, gap: int) -> None:
    chars = list(text)
    total = sum(d.textlength(c, font=font) for c in chars) + gap * (len(chars) - 1)
    x = width / 2 - total / 2
    for c in chars:
        d.text((x, y), c, font=font, fill=fill)
        x += d.textlength(c, font=font) + gap


def _jittered_rect(d, box, color, width: int, rnd: random.Random, wobble: float = 0.9):
    x0, y0, x1, y1 = box
    step = max(14, int((x1 - x0) / 26))

    def seg(a, b, horizontal):
        ax, ay = a
        bx, by = b
        pts = [a]
        if horizontal:
            x = ax
            while x < bx:
                x = min(bx, x + step)
                pts.append((x, ay + rnd.uniform(-wobble, wobble)))
        else:
            y = ay
            while y < by:
                y = min(by, y + step)
                pts.append((ax + rnd.uniform(-wobble, wobble), y))
        pts.append(b)
        d.line(pts, fill=color, width=width, joint="curve")

    seg((x0, y0), (x1, y0), True)
    seg((x1, y0), (x1, y1), False)
    seg((x1, y1), (x0, y1), True)
    seg((x0, y1), (x0, y0), False)


def _card_panel(size: tuple[int, int]) -> Image.Image:
    """牌面：米色纸、略不齐的边、压印双线、四角记号。"""
    w, h = size
    panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rnd = random.Random(w * 17 + h)

    body = Image.new("RGB", (w, h), PAPER_DEEP)
    grad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(h):
        gd.line([(0, y), (w, y)], fill=(120, 104, 78, int(6 + (y / max(1, h - 1)) * 10)))
    body.paste(grad, (0, 0), grad)

    noise = Image.effect_noise((w, h), 16).convert("L")
    noise = noise.filter(ImageFilter.GaussianBlur(0.6))
    body = Image.blend(body, Image.merge("RGB", (noise, noise, noise)), 0.04)

    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=5, fill=255)
    panel.paste(body, (0, 0), mask)

    d = ImageDraw.Draw(panel)
    _jittered_rect(d, (1.4, 1.4, w - 1.4, h - 1.4), INK + (255,), 2, rnd)
    _jittered_rect(d, (2.2, 2.4, w - 2.2, h - 2.0), (86, 74, 60, 60), 1, rnd)
    _jittered_rect(d, (9, 9, w - 9, h - 9), BRASS + (215,), 1, rnd, wobble=0.6)

    m, ln = 17, int(min(w, h) * 0.055)
    for sx, sy in ((m, m), (w - m, m), (m, h - m), (w - m, h - m)):
        dx = 1 if sx < w / 2 else -1
        dy = 1 if sy < h / 2 else -1
        d.line([(sx, sy + dy * ln), (sx, sy), (sx + dx * ln, sy)],
               fill=BRASS + (205,), width=1)

    stain = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stain)
    sd.rectangle([0, 0, w, h], outline=(150, 124, 88, 26), width=3)
    stain = stain.filter(ImageFilter.GaussianBlur(2))
    panel.paste(stain, (0, 0), stain)
    return panel


def _rule(d, cx: float, y: float, half: float, color=BRASS) -> None:
    d.line([(cx - half, y), (cx - 7, y)], fill=color + (255,), width=1)
    d.line([(cx + 7, y), (cx + half, y)], fill=color + (255,), width=1)
    d.polygon([(cx, y - 4), (cx + 4, y), (cx, y + 4), (cx - 4, y)], outline=color + (255,))


def _orientation(d, cx: float, y: float, reversed_: bool, size: int) -> None:
    label = "逆 位" if reversed_ else "正 位"
    color = CLAY if reversed_ else OLIVE
    f = _font(max(13, size), "kai_small")
    tw = d.textlength(label, font=f)
    _ink(d, (cx - tw / 2, y), label, f, color)


def _hatch(d, cx: float, cy: float, w: float, h: float, step: float, color) -> None:
    """一组斜向排线，给图形加阴影面的感觉。"""
    x = cx - w / 2
    while x < cx + w / 2:
        d.line([(x, cy - h / 2), (x + step * 1.6, cy + h / 2)], fill=color, width=1)
        x += step


ART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "art")
_ART_CACHE: dict[str, Image.Image] = {}
USE_ART = True
_SUIT_FILE = {"权杖": "wands", "圣杯": "cups", "宝剑": "swords", "星币": "pents",
              "杖": "wands", "杯": "cups", "剑": "swords", "钱": "pents"}
_RANK_FILE = {"侍从": 11, "骑士": 12, "王后": 13, "皇后": 13, "国王": 14,
              "童": 11, "骑": 12, "妃": 13, "王": 14,
              "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
              "七": 7, "八": 8, "九": 9, "十": 10}


_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def _roman_to_int(text: str) -> int:
    """XXI → 21，0 → 0。认不出返回 -1。"""
    t = (text or "").strip().upper()
    if not t:
        return -1
    if t.isdigit():
        return int(t)
    total = 0
    prev = 0
    for ch in reversed(t):
        val = _ROMAN.get(ch)
        if val is None:
            return -1
        total += -val if val < prev else val
        prev = max(prev, val)
    return total


def _art_name(card: dict) -> str:
    """牌 → 图文件名。大牌按罗马数字，小牌按花色和点数。"""
    roman = card.get("roman")
    if roman:
        num = _roman_to_int(str(roman))
        if num >= 0:
            return f"major_{num:02d}.jpg"
    suit = _SUIT_FILE.get(card.get("suit") or "")
    if not suit:
        return ""
    name = card.get("name_cn") or ""
    rank_txt = name[len(card.get("suit") or ""):]
    rank = _RANK_FILE.get(rank_txt)
    if rank is None:
        return ""
    return f"{suit}_{rank:02d}.jpg"


def use_art(enabled: bool) -> None:
    """开关牌图。"""
    global USE_ART
    USE_ART = bool(enabled)


def _trim_border(img: Image.Image, thresh: int = 200) -> Image.Image:
    """裁掉扫描件外圈的浅灰纸边：按行、列的平均亮度找内框。"""
    w, h = img.size
    rows = [img.resize((1, h), Image.BOX).getpixel((0, y)) for y in range(h)]
    cols = [img.resize((w, 1), Image.BOX).getpixel((x, 0)) for x in range(w)]

    def first(vals):
        for i, v in enumerate(vals):
            if v < thresh:
                return i
        return 0

    def last(vals):
        for i in range(len(vals) - 1, -1, -1):
            if vals[i] < thresh:
                return i
        return len(vals) - 1

    top, bottom = first(rows), last(rows)
    left, right = first(cols), last(cols)
    if right - left < 20 or bottom - top < 20:
        return img

    # 关于中心对称地裁，四边留白才会一样宽
    cx, cy = w / 2, h / 2
    half_w = int(min(right + 1 - cx, cx - left))
    half_h = int(min(bottom + 1 - cy, cy - top))
    if half_w < 20 or half_h < 20:
        return img.crop((left, top, right + 1, bottom + 1))
    return img.crop((int(cx - half_w), int(cy - half_h), int(cx + half_w), int(cy + half_h)))


def _art_image(card: dict, box_w: int, box_h: int):
    """取牌图，等比缩到框内。没有图返回 None。"""
    if not USE_ART:
        return None
    fname = _art_name(card)
    if not fname:
        return None
    if fname not in _ART_CACHE:
        path = os.path.join(ART_DIR, fname)
        if not os.path.exists(path):
            _ART_CACHE[fname] = None
            return None
        try:
            raw = Image.open(path).convert("L")
            raw = raw  # 纸边靠透明度处理，不裁
            # 墨印：纸（>205）完全透明，线（<60）全墨，中间线性过渡
            alpha = raw.point(lambda v: 0 if v >= 214 else min(255, int((214 - v) * 255 / 154)))
            # 浅灰（扫描阴影）一律不要，只保留真正的墨
            alpha = alpha.point(lambda a: 0 if a < 70 else min(255, int((a - 70) * 255 / 185)))
            _ART_CACHE[fname] = alpha
        except Exception:
            _ART_CACHE[fname] = None
            return None
    src = _ART_CACHE[fname]
    if src is None:
        return None
    scale = min(box_w / src.width, box_h / src.height)
    size = (max(1, int(src.width * scale)), max(1, int(src.height * scale)))
    art = src.resize(size, Image.LANCZOS)
    # 压一点对比，让它像印在纸上，不是贴上去的照片
    art = art.filter(ImageFilter.GaussianBlur(0.3))
    ink = Image.new("RGBA", size, (56, 47, 39, 255))
    ink.putalpha(art)

    return ink


def _suit_icon(d, cx: float, cy: float, size: float, suit: str, color=BRASS) -> None:
    """画花色：杖、杯、剑、币。先垫一层浅色阴影，再画主体，像刻进纸里。"""
    half = size / 2
    _suit_shape(d, cx + size * 0.012, cy + size * 0.018, size, suit,
                (255, 252, 244))
    _suit_shape(d, cx, cy, size, suit, color)

    # 排线只压在左下角一小块，做出受光的方向
    shade = (color[0], color[1], color[2], 46) if size >= 46 else None
    step = max(2.0, size * 0.055)
    if shade is None:
        return
    if suit == "圣杯":
        _hatch(d, cx - half * 0.30, cy - half * 0.25, half * 0.40, half * 0.42, step, shade)
    elif suit == "星币":
        _hatch(d, cx - half * 0.24, cy + half * 0.06, half * 0.44, half * 0.46, step, shade)
    elif suit == "权杖":
        _hatch(d, cx - half * 0.16, cy + half * 0.10, half * 0.28, half * 0.62, step, shade)
    elif suit == "宝剑":
        _hatch(d, cx - half * 0.14, cy - half * 0.55, half * 0.20, half * 0.9, step, shade)


def _suit_shape(d, cx: float, cy: float, size: float, suit: str, color) -> None:
    """花色本体。线宽按尺寸走，小牌上也不至于细成一根头发。"""
    half = size / 2
    w = max(1, int(round(size * 0.075)))
    if suit == "权杖":
        d.line([(cx, cy - half), (cx, cy + half)], fill=color, width=w)
        # 三对分枝
        for t in (-0.30, 0.02, 0.34):
            y = cy + half * t
            d.line([(cx, y), (cx - half * 0.34, y - half * 0.18)], fill=color, width=max(1, w - 1))
            d.line([(cx, y), (cx + half * 0.34, y - half * 0.18)], fill=color, width=max(1, w - 1))
    elif suit == "圣杯":
        bowl = [cx - half * 0.52, cy - half * 0.62, cx + half * 0.52, cy + half * 0.10]
        d.pieslice(bowl, 0, 180, fill=None, outline=color, width=w)
        d.line([(cx - half * 0.52, cy - half * 0.30), (cx + half * 0.52, cy - half * 0.30)],
               fill=color, width=w)
        d.line([(cx, cy + half * 0.10), (cx, cy + half * 0.52)], fill=color, width=w)
        d.line([(cx - half * 0.30, cy + half * 0.58), (cx + half * 0.30, cy + half * 0.58)],
               fill=color, width=w)
    elif suit == "宝剑":
        d.polygon([(cx, cy - half), (cx + half * 0.10, cy + half * 0.16),
                   (cx - half * 0.10, cy + half * 0.16)], outline=color, fill=None)
        d.line([(cx, cy - half * 0.95), (cx, cy + half * 0.16)], fill=color, width=w)
        d.line([(cx - half * 0.42, cy + half * 0.24), (cx + half * 0.42, cy + half * 0.24)],
               fill=color, width=w)
        d.line([(cx, cy + half * 0.24), (cx, cy + half * 0.58)], fill=color, width=w)
        d.ellipse([cx - half * 0.10, cy + half * 0.54, cx + half * 0.10, cy + half * 0.74],
                  outline=color, width=w)
    elif suit == "星币":
        d.ellipse([cx - half * 0.62, cy - half * 0.62, cx + half * 0.62, cy + half * 0.62],
                  outline=color, width=w)
        # 五角星
        pts = []
        for i in range(10):
            ang = -math.pi / 2 + i * math.pi / 5
            rad = half * 0.44 if i % 2 == 0 else half * 0.20
            pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
        d.polygon(pts, outline=color)


def _star4(d, cx: float, cy: float, r: float, color, inner: float = 0.34) -> None:
    pts = []
    for i in range(8):
        ang = -math.pi / 2 + i * math.pi / 4
        rad = r if i % 2 == 0 else r * inner
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    d.polygon(pts, fill=color)


_RANK_SHORT = {"侍从": "侍", "骑士": "骑", "皇后": "后", "国王": "王"}


def _has_art(card: dict) -> bool:
    """这张牌有没有图。没有图就别跟着转，字会倒过来。"""
    return _art_image(card, 2, 2) is not None


def _card_tag(card: dict) -> str:
    """左上角那个标记：大牌用罗马数字，小牌用点数或位阶。"""
    if card.get("roman"):
        return card["roman"]
    name = card.get("name_cn") or ""
    suit = card.get("suit") or ""
    rank = name[len(suit):] if suit and name.startswith(suit) else name
    if not rank:
        return suit
    return _RANK_SHORT.get(rank, rank)


def _cn_face(card: dict, rev: bool, w: int, h: int) -> Image.Image:
    """没有牌图时的牌面：纸、墨线、居中的字。不套任何装饰。"""
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    panel = _card_panel((w, h))
    tile.paste(panel, (0, 0), panel)
    d = ImageDraw.Draw(tile, "RGBA")

    name = card["name_cn"]
    tag = _card_tag(card)
    small = w < 190

    if small:
        f_tag = _font(int(w * 0.10), "num")
        f_name = _font(int(w * 0.125), "kai_small")
        _center_at(d, str(tag), f_tag, w / 2, int(h * 0.12), BRASS)
        _center_at(d, name, f_name, w / 2, int(h * 0.46), INK, soak=True)
        _orientation(d, w / 2, int(h * 0.74), rev, int(w * 0.075))
        return tile

    f_tag = _font(int(w * 0.085), "num")
    f_name = _font(int(w * 0.135), "kai")
    f_en = _font(int(w * 0.038), "song")
    f_kw = _font(int(w * 0.043), "song")

    _center_at(d, str(tag), f_tag, w / 2, int(h * 0.18), BRASS)
    _rule(d, w / 2, int(h * 0.33), int(w * 0.22))
    _center_at(d, name, f_name, w / 2, int(h * 0.40), INK, soak=True)
    _center_at(d, (card.get("name_en") or "").upper(), f_en, w / 2, int(h * 0.56), INK_FAINT)
    _orientation(d, w / 2, int(h * 0.64), rev, int(w * 0.048))
    if card.get("keywords"):
        _center_at(d, " · ".join(card["keywords"]), f_kw, w / 2, int(h * 0.75), BRASS)
    return tile


def _paint_face(tile, card: dict, rev: bool, w: int, h: int,
                name_font, label_size: int) -> bool:
    """有牌图时把图贴上去，牌名放图下面。没有图返回 False，调用方自己画。"""
    art = _art_image(card, int(w * 0.84), int(h * 0.62))
    if art is None:
        return False
    d = ImageDraw.Draw(tile, "RGBA")
    tile.paste(art, (int(w / 2 - art.width / 2), int(h * 0.10)), art)
    _center_at(d, card["name_cn"], name_font, w / 2, int(h * 0.76), INK, soak=True)
    _orientation(d, w / 2, int(h * 0.89), rev, label_size)
    return True


def render_cross(items: list, out_path: str, title: str,
                 question: str = "", footer: str = "",
                 width: int = 1000) -> str:
    """五张十字：中间一张大的，四张卫星围绕，牌义列在下面。

    items 顺序：0 现状（中）、1 阻碍（左）、2 潜在（右）、3 建议（上）、4 结果（下）。
    """
    W = max(860, min(1300, int(width)))
    f_title = _font(int(W * 0.026), "kai")
    f_en = _font(int(W * 0.014), "song")
    f_pos = _font(int(W * 0.017), "kai_small")
    f_cn = _font(int(W * 0.020), "kai_small")
    f_orient = _font(int(W * 0.015), "kai_small")
    f_list = _font(int(W * 0.017), "song")
    f_small = _font(int(W * 0.015), "song")

    head = int(W * 0.085)
    mid_card_w = int(W * 0.24)
    mid_card_h = int(mid_card_w * 1.36)
    sat_card_w = int(W * 0.17)
    sat_card_h = int(sat_card_w * 1.36)
    gap = int(W * 0.035)

    center_cx = W / 2
    center_cy = head + int(W * 0.055) + max(sat_card_h + int(W * 0.030), mid_card_h / 2) + mid_card_h / 2
    top_y = center_cy - mid_card_h / 2 - gap - sat_card_h
    bottom_y = center_cy + mid_card_h / 2 + gap

    list_h = int(W * 0.036) * len(items) + int(W * 0.02)
    H = int(max(bottom_y + sat_card_h, center_cy + mid_card_h / 2) + int(W * 0.045) + list_h
            + int(W * 0.060) + (int(W * 0.026) if question else 0))

    img = _paper(W, H)
    d = ImageDraw.Draw(img, "RGBA")
    _spaced(d, title, f_title, int(W * 0.024), INK, W, int(W * 0.012))
    _center(d, "T A R O T", f_en, int(W * 0.062), INK_FAINT, W)

    def tile(card, rev, w, h, name_font, label_font, show_en=True):
        panel = _card_panel((w, h))
        t = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        t.paste(panel, (0, 0), panel)
        if not _paint_face(t, card, rev, w, h, name_font, int(w * 0.070)):
            t.paste(_cn_face(card, rev, w, h), (0, 0))
        if rev and _has_art(card):
            t = t.rotate(180)
        return t

    def place(card, rev, pos, cx, cy, w, h, name_font, show_en=True):
        _center_at(d, pos, f_pos, cx, cy - h / 2 - int(W * 0.034), INK_SOFT, soak=True)
        t = tile(card, rev, w, h, name_font, f_orient, show_en)
        img.paste(t, (int(cx - w / 2), int(cy - h / 2)), t)

    order = [(items[0], center_cx, center_cy, mid_card_w, mid_card_h)]
    if len(items) > 1:
        order.append((items[1], center_cx - mid_card_w / 2 - gap - sat_card_w / 2,
                      center_cy, sat_card_w, sat_card_h))
    if len(items) > 2:
        order.append((items[2], center_cx + mid_card_w / 2 + gap + sat_card_w / 2,
                      center_cy, sat_card_w, sat_card_h))
    if len(items) > 3:
        order.append((items[3], center_cx, top_y + sat_card_h / 2, sat_card_w, sat_card_h))
    if len(items) > 4:
        order.append((items[4], center_cx, bottom_y + sat_card_h / 2, sat_card_w, sat_card_h))

    for entry, cx, cy, w, h in order:
        card, rev, pos, _mean = entry
        place(card, rev, pos, cx, cy, int(w), int(h), f_cn if h == mid_card_h else f_cn)

    d = ImageDraw.Draw(img, "RGBA")
    ly = H - list_h - int(W * 0.060)
    marks = "①②③④⑤⑥"
    for i, (card, rev, pos, mean) in enumerate(items):
        state = "逆" if rev else "正"
        num = f" · {card['roman']}" if card.get("roman") else ""
        line = f"{marks[i]} {pos}：{card['name_cn']}{num}（{state}）— {mean}"
        if len(line) > 42:
            line = line[:42] + "…"
        _ink(d, (int(W * 0.06), ly), line, f_list, INK)
        ly += int(W * 0.036)

    if question:
        q = "问：" + (question if len(question) <= 26 else question[:26] + "…")
        _center(d, q, f_small, H - int(W * 0.052), INK_SOFT, W)

    foot = footer or datetime.now().strftime("%Y-%m-%d")
    _center(d, foot, f_small, H - int(W * 0.028), INK_FAINT, W)

    _frame_wash(img)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    rgb = img.convert("RGB")
    if out_path.lower().endswith((".jpg", ".jpeg")):
        rgb.save(out_path, "JPEG", quality=92, optimize=True, subsampling=0)
    else:
        rgb.save(out_path, "PNG", optimize=True)
    return out_path


def render_celtic(items: list, out_path: str, title: str,
                  question: str = "", footer: str = "",
                  width: int = 1200) -> str:
    """凯尔特十字：左边十字六张，右边竖排四张，牌义按 ①～⑩ 列在下面。"""
    W = max(1000, min(1500, int(width)))
    n = len(items)

    f_title = _font(int(W * 0.024), "kai")
    f_en = _font(int(W * 0.013), "song")
    f_pos = _font(int(W * 0.014), "kai_small")
    f_cn = _font(int(W * 0.016), "kai_small")
    f_list = _font(int(W * 0.016), "song")
    f_small = _font(int(W * 0.014), "song")

    head = int(W * 0.105)
    card_w = int(W * 0.108)
    card_h = int(card_w * 1.67)
    gap = int(W * 0.030)

    # 上臂中心先定，再据此推十字中心，保证标题不被上臂压住
    top_center = head + int(W * 0.030) + card_h / 2
    cross_cx = W * 0.32
    cross_cy = top_center + card_h + gap

    staff_x = W * 0.72
    staff_w = int(card_w * 0.86)
    staff_h = int(staff_w * 1.67)
    staff_gap = int(W * 0.030)
    # 右侧一列以十字中心为中线上下对齐，避免下面拖出一大片空白
    staff_top = cross_cy - (staff_h * 4 + staff_gap * 3) / 2

    bottom_most = cross_cy + card_h + gap + card_h
    staff_bottom = staff_top + staff_h * 4 + staff_gap * 3
    list_h = int(W * 0.030) * n + int(W * 0.02)
    H = int(max(bottom_most, staff_bottom) + int(W * 0.035) + list_h
            + int(W * 0.060) + (int(W * 0.026) if question else 0))

    img = _paper(W, H)
    d = ImageDraw.Draw(img, "RGBA")
    _spaced(d, title, f_title, int(W * 0.022), INK, W, int(W * 0.010))
    _center(d, "C E L T I C   C R O S S", f_en, int(W * 0.050), INK_FAINT, W)

    def tile(card, rev, w, h, rotate=0):
        panel = _card_panel((w, h))
        t = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        t.paste(panel, (0, 0), panel)
        if not _paint_face(t, card, rev, w, h, f_cn, int(w * 0.075)):
            t.paste(_cn_face(card, rev, w, h), (0, 0))
        if rev and _has_art(card):
            t = t.rotate(180)
        if rotate:
            t = t.rotate(rotate, expand=True)
        return t

    def label(pos, cx, y):
        _center_at(d, pos, f_pos, cx, y, INK_SOFT, soak=True)

    def put(entry, cx, cy, w, h, above=True):
        card, rev, pos, _mean = entry
        t = tile(card, rev, w, h)
        img.paste(t, (int(cx - t.width / 2), int(cy - t.height / 2)), t)
        if above:
            label(pos, cx, cy - h / 2 - int(W * 0.030))
        else:
            label(pos, cx, cy + h / 2 + int(W * 0.008))

    # 中心牌（现状）与横压的挑战牌：两张会互相遮挡，
    # 所以不放牌上标签，统一在十字下面写一行「现状 / 挑战」
    if n > 0:
        t0 = tile(items[0][0], items[0][1], card_w, card_h)
        img.paste(t0, (int(cross_cx - t0.width / 2), int(cross_cy - t0.height / 2)), t0)
    if n > 1:
        t1 = tile(items[1][0], items[1][1], card_w, card_h, rotate=90)
        img.paste(t1, (int(cross_cx - t1.width / 2), int(cross_cy - t1.height / 2)), t1)

    pairs = []
    if n > 0:
        pairs.append(f"{items[0][2]}·{items[0][0]['name_cn']}")
    if n > 1:
        pairs.append(f"{items[1][2]}·{items[1][0]['name_cn']}")
    if pairs:
        _center_at(d, "    ".join(pairs), f_pos, cross_cx,
                   cross_cy + card_h / 2 + int(W * 0.010), INK_SOFT, soak=True)

    # 四条臂：下、左、上、右
    if n > 2:
        put(items[2], cross_cx, cross_cy + card_h + gap + card_h / 2, card_w, card_h, above=False)
    if n > 3:
        put(items[3], cross_cx - card_w - gap, cross_cy, card_w, card_h)
    if n > 4:
        put(items[4], cross_cx, cross_cy - card_h - gap, card_w, card_h)
    if n > 5:
        put(items[5], cross_cx + card_w + gap, cross_cy, card_w, card_h)

    # 右边竖排四张
    for i in range(6, min(10, n)):
        cy = staff_top + staff_h / 2 + (staff_h + staff_gap) * (i - 6)
        put(items[i], staff_x, cy, staff_w, staff_h)

    # 牌义列表
    ly = H - list_h - int(W * 0.050)
    marks = "①②③④⑤⑥⑦⑧⑨⑩"
    for i, (card, rev, pos, mean) in enumerate(items):
        state = "逆" if rev else "正"
        num = f" · {card['roman']}" if card.get("roman") else ""
        line = f"{marks[i]} {pos}：{card['name_cn']}{num}（{state}）— {mean}"
        if len(line) > 46:
            line = line[:46] + "…"
        _ink(d, (int(W * 0.05), ly), line, f_list, INK)
        ly += int(W * 0.030)

    if question:
        q = "问：" + (question if len(question) <= 26 else question[:26] + "…")
        _center(d, q, f_small, H - int(W * 0.046), INK_SOFT, W)

    foot = footer or datetime.now().strftime("%Y-%m-%d")
    _center(d, foot, f_small, H - int(W * 0.024), INK_FAINT, W)

    _frame_wash(img)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    rgb = img.convert("RGB")
    if out_path.lower().endswith((".jpg", ".jpeg")):
        rgb.save(out_path, "JPEG", quality=92, optimize=True, subsampling=0)
    else:
        rgb.save(out_path, "PNG", optimize=True)
    return out_path


def render_spread(items: list, out_path: str, title: str,
                  question: str = "", footer: str = "",
                  width: int = 900) -> str:
    """把牌阵画成一张图。

    items: [(card, reversed, position_label, position_meaning), ...]
    一张：牌画大、牌义在牌内；多张：网格排布，每列各自居中。
    """
    n = max(1, len(items))
    single = n == 1
    W = max(760, min(1500, int(width if single else width * 1.25)))
    cols = 1 if single else min(3, n)
    rows = 1 if single else (n + cols - 1) // cols

    f_title = _font(int(W * (0.040 if single else 0.026)), "kai")
    f_title_en = _font(int(W * 0.015), "song")
    small_kind = "kai" if single else "kai_small"
    f_pos = _font(int(W * (0.026 if single else 0.019)), small_kind)
    f_pmean = _font(int(W * (0.013 if single else 0.012)), "song")
    f_cn = _font(int(W * (0.076 if single else 0.031)), small_kind)
    f_kw = _font(int(W * (0.023 if single else 0.015)), "song")
    f_body = _font(int(W * (0.028 if single else 0.016)), "song")
    f_small = _font(int(W * 0.020), "song")

    margin = int(W * (0.085 if single else 0.040))
    inner_w = W - margin * 2
    col_w = inner_w / cols

    if single:
        card_w = int(inner_w * 0.84)
        card_h = int(card_w * 1.18)
    else:
        card_w = int(col_w * 0.72)
        card_h = int(card_w * 1.67)

    label_h = int(W * (0.052 if single else 0.058))
    gap_after_card = int(W * (0.050 if single else 0.028))
    body_line_h = int(W * (0.044 if single else 0.026))
    body_lines = 4 if single else 3
    kw_h = int(W * (0.010 if single else 0.026))
    row_h = label_h + card_h + gap_after_card + body_line_h * body_lines + kw_h

    head_h = int(W * (0.125 if single else 0.100))
    foot_h = int(W * 0.060)
    q_h = int(W * 0.030) if question else 0
    H = int(head_h + row_h * rows + q_h + foot_h)

    img = _paper(W, H)
    d = ImageDraw.Draw(img, "RGBA")
    _spaced(d, title, f_title, int(W * 0.026), INK, W, int(W * 0.012))
    _center(d, "T A R O T", f_title_en, int(W * (0.086 if single else 0.072)), INK_FAINT, W)

    for idx, (card, rev, pos_label, pos_meaning) in enumerate(items):
        r, c = divmod(idx, cols)
        # 末行不足 cols 张时整体居中
        in_row = min(cols, n - r * cols)
        offset = (cols - in_row) * col_w / 2
        cx = margin + offset + col_w * (c + 0.5)
        row_top = head_h + r * row_h

        if pos_label:
            _center_at(d, pos_label, f_pos, cx, row_top, INK_SOFT, soak=True)
        if not single and pos_meaning:
            pm = pos_meaning if len(pos_meaning) <= 13 else pos_meaning[:13] + "…"
            _center_at(d, pm, f_pmean, cx, row_top + int(W * 0.024), INK_FAINT)

        card_y = row_top + label_h
        x0 = int(cx - card_w / 2)
        panel = _card_panel((card_w, card_h))

        # 牌内容画在独立小图上，逆位时整张转 180° 再贴
        tile = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
        tile.paste(panel, (0, 0), panel)
        td_ = ImageDraw.Draw(tile, "RGBA")

        art = _art_image(card, int(card_w * 0.86), int(card_h * 0.64))
        if art is not None:
            # 有牌图：图上自带罗马数字和画面，不用再画一遍
            art_y = int(card_h * 0.10)
            tile.paste(art, (int(card_w / 2 - art.width / 2), art_y), art)
            name_y = int(card_h * 0.76)
            _center_at(td_, card["name_cn"], f_cn, card_w / 2, name_y, INK, soak=True)
            _orientation(td_, card_w / 2, int(card_h * 0.88), rev, int(card_w * 0.045))
        else:
            tile.paste(_cn_face(card, rev, card_w, card_h), (0, 0))

        if rev and not single and _has_art(card):
            tile = tile.rotate(180)
        img.paste(tile, (x0, card_y), tile)
        d = ImageDraw.Draw(img, "RGBA")

        by = card_y + card_h + gap_after_card
        meaning = card["reversed"] if rev else card["upright"]
        max_w = card_w - int(W * 0.10) if single else int(col_w * 0.84)
        for line in _wrap(d, meaning, f_body, max_w)[:body_lines]:
            _center_at(d, line, f_body, cx, by, INK, soak=single)
            by += body_line_h
        if not single and card.get("keywords"):
            _center_at(d, " · ".join(card["keywords"]), f_kw, cx,
                       by + int(W * 0.004), BRASS)

    if question:
        q = "问：" + (question if len(question) <= 26 else question[:26] + "…")
        _center(d, q, f_small, H - foot_h - q_h + int(W * 0.004), INK_SOFT, W)

    foot = footer or datetime.now().strftime("%Y-%m-%d")
    _center(d, foot, f_small, H - int(W * 0.042), INK_FAINT, W)

    _frame_wash(img)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    rgb = img.convert("RGB")
    if out_path.lower().endswith((".jpg", ".jpeg")):
        rgb.save(out_path, "JPEG", quality=92, optimize=True, subsampling=0)
    else:
        rgb.save(out_path, "PNG", optimize=True)
    return out_path


def render_single(card: dict, reversed_: bool, out_path: str,
                  question: str = "", footer: str = "", width: int = 900) -> str:
    """兼容旧接口：单张牌。"""
    return render_spread([(card, reversed_, "此 刻", "此刻最要紧的状态")],
                         out_path, "塔 罗", question, footer, width)


def render_three(draws: list, out_path: str, question: str = "",
                 footer: str = "", width: int = 1400) -> str:
    """兼容旧接口：三张牌（过去 / 现在 / 未来）。"""
    items = []
    for i, item in enumerate(draws):
        card, rev = item[0], item[1]
        label = item[2] if len(item) > 2 else ("过去", "现在", "未来")[i % 3]
        items.append((card, rev, label, ""))
    return render_spread(items, out_path, "三 张 牌", question, footer, width)


def render_logo(out_path: str, size: int = 512) -> str:
    """Logo：米色纸上一张小牌，墨线与赭红。"""
    S = size
    img = _paper(S, S)
    d = ImageDraw.Draw(img, "RGBA")

    cx, cy, cr = int(S * 0.80), int(S * 0.19), int(S * 0.105)
    d.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], outline=(198, 182, 152), width=2)
    d.ellipse([cx - cr * 0.62, cy - cr * 0.62, cx + cr * 0.62, cy + cr * 0.62],
              outline=(206, 190, 160), width=1)
    for k in range(8):
        ang = k * math.pi / 4
        d.line([(cx + cr * 0.78 * math.cos(ang), cy + cr * 0.78 * math.sin(ang)),
                (cx + cr * 1.02 * math.cos(ang), cy + cr * 1.02 * math.sin(ang))],
               fill=(190, 174, 144), width=1)

    cw, ch = int(S * 0.48), int(S * 0.66)
    x, y = (S - cw) // 2, int(S * 0.16)
    panel = _card_panel((cw, ch))
    img.paste(panel, (x, y), panel)
    dd = ImageDraw.Draw(img, "RGBA")

    _star4(dd, S // 2, y + int(ch * 0.22), S * 0.040, CLAY)
    _rule(dd, S // 2, y + int(ch * 0.40), int(cw * 0.26))
    f_txt = _font(int(S * 0.085), "kai")
    _center(dd, "塔罗", f_txt, y + int(ch * 0.50), INK, S, soak=True)
    f_sub = _font(int(S * 0.030), "song")
    _center(dd, "T A R O T", f_sub, y + int(ch * 0.67), INK_FAINT, S)

    _star4(dd, int(S * 0.14), int(S * 0.16), S * 0.022, BRASS)
    _star4(dd, int(S * 0.87), int(S * 0.73), S * 0.016, BRASS)

    _frame_wash(img)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.convert("RGB").save(out_path, "PNG", optimize=True)
    return out_path
