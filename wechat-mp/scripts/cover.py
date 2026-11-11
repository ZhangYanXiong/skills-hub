#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cover.py — 公众号封面图生成器

为什么需要它:
    头条封面必须 900×383（2.35:1），次条封面 200×200，分享卡片用 1:1。
    大部分人卡在「找不到图 / 尺寸裁错 / 文字被裁」，本脚本按主题配色批量出图。

依赖: Pillow（python3 -c "import PIL" 需可用）

用法:
    python3 cover.py --title "别再手写 CRUD 了" --theme tech -o cover.png
    python3 cover.py --md article.md --theme growth --style minimal -o cover.png
    python3 cover.py --title "..." --theme tech --all -o covers/cover

产物（--all 时）:
    cover.png          900×383   头条封面
    cover-square.png   1080×1080 分享卡片 / 方形素材
    cover-thumb.png    200×200   次条封面
"""

import argparse
import json
import os
import re
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit(
        "需要 Pillow。请用带 Pillow 的 Python 运行，或先 pip install pillow"
    )

HERE = os.path.dirname(os.path.abspath(__file__))
THEME_DIR = os.path.join(HERE, "themes")

if HERE not in sys.path:
    sys.path.insert(0, HERE)
import wxmeta  # noqa: E402  同目录共享工具

# 中文字体候选（macOS 优先，其次 Linux/Windows 常见路径）
FONT_CANDIDATES = [
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 2, 0),  # (path, bold_index, regular_index)
    ("/System/Library/Fonts/PingFang.ttc", 4, 0),
    ("/System/Library/Fonts/STHeiti Medium.ttc", 0, 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0, 0),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", 0, 0),
    ("C:/Windows/Fonts/msyhbd.ttc", 0, 0),
]

# 尺寸预设：(宽, 高, 标题最大行数, 字号搜索区间)
SIZES = {
    "main": (900, 383, 2, (64, 58, 52, 46, 40, 34, 30)),
    "square": (1080, 1080, 3, (96, 86, 76, 66, 58, 50, 44)),
    "thumb": (200, 200, 2, (34, 30, 26, 22, 19, 16)),
}

# 不能出现在行首的标点（避头尾处理）
NO_LINE_START = "，。、；：？！）」』】》%…,.;:?!)]}"
NO_LINE_END = "（「『【《([{"

DEFAULTS = {
    "accent": "#2f6fed",
    "bg": "#101828",
    "text": "#ffffff",
    "muted": "rgba(255,255,255,0.72)",
}


# ---------------------------------------------------------------- 颜色

def hex2rgb(h: str):
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgba(h: str, alpha: int = 255):
    """支持 #rgb / #rrggbb / rgba(r,g,b,a) / rgb(r,g,b)。"""
    h = h.strip()
    m = re.match(r"rgba?\(([^)]+)\)", h)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        r, g, b = (int(float(parts[i])) for i in range(3))
        a = int(float(parts[3]) * 255) if len(parts) > 3 else alpha
        return (r, g, b, a)
    r, g, b = hex2rgb(h)
    return (r, g, b, alpha)


def mix(c1, c2, t: float):
    t = max(0.0, min(1.0, t))
    return tuple(int(round(c1[i] + (c2[i] - c1[i]) * t)) for i in range(3))


def darken(c, amount=0.35):
    return mix(c, (0, 0, 0), amount)


def lighten(c, amount=0.35):
    return mix(c, (255, 255, 255), amount)


def is_dark(c) -> bool:
    r, g, b = c[:3]
    return (0.299 * r + 0.587 * g + 0.114 * b) < 140


# ---------------------------------------------------------------- 字体

def find_font_path():
    for path, _bold, _reg in FONT_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


class Fonts:
    def __init__(self, path=None):
        self.path = path or find_font_path()
        self._cache = {}
        if not self.path:
            raise SystemExit(
                "找不到中文字体，请用 --font 指定一个 .ttf/.ttc 路径"
            )
        self.bold_index, self.reg_index = 0, 0
        for p, b, r in FONT_CANDIDATES:
            if p == self.path:
                self.bold_index, self.reg_index = b, r
                break

    def get(self, size: int, bold=True):
        key = (size, bold)
        if key in self._cache:
            return self._cache[key]
        idx = self.bold_index if bold else self.reg_index
        try:
            f = ImageFont.truetype(self.path, size, index=idx)
        except Exception:
            f = ImageFont.truetype(self.path, size)
        self._cache[key] = f
        return f


# ---------------------------------------------------------------- 文本排版

def wrap_text(text: str, font, max_width: int, draw) -> list:
    """中英混排折行：CJK 逐字断，英文按词断，并做基本避头尾。"""
    lines, cur = [], ""
    tokens = re.findall(r"[A-Za-z0-9_\-'’]+|\s+|[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]|.", text)
    for tok in tokens:
        if tok.isspace() and not cur:
            continue
        cand = cur + tok
        if draw.textlength(cand, font=font) <= max_width:
            cur = cand
            continue
        # 需要换行
        if not cur:
            # 单个 token 就超宽，强制切字
            for ch in tok:
                if draw.textlength(cur + ch, font=font) <= max_width:
                    cur += ch
                else:
                    lines.append(cur)
                    cur = ch
            continue
        # 避头尾：当前 token 是标点 → 允许悬挂在行尾
        if tok and tok[0] in NO_LINE_START:
            lines.append(cur + tok)
            cur = ""
            continue
        # 行尾是开引号 → 挪到下一行
        if cur and cur[-1] in NO_LINE_END:
            lines.append(cur[:-1])
            cur = cur[-1] + tok
            continue
        lines.append(cur.rstrip())
        cur = tok.lstrip() if tok.isspace() else tok
    if cur.strip():
        lines.append(cur.rstrip())
    return lines


def fit_title(text, fonts, draw, max_width, max_lines, sizes):
    for size in sizes:
        font = fonts.get(size, bold=True)
        lines = wrap_text(text, font, max_width, draw)
        if len(lines) <= max_lines:
            return font, lines, size
    # 全都不够小：用最小字号并截断，末尾补省略号
    size = sizes[-1]
    font = fonts.get(size, bold=True)
    lines = wrap_text(text, font, max_width, draw)
    kept = lines[:max_lines]
    if len(lines) > max_lines and kept:
        last = kept[-1].rstrip("，。、；：,.;: ")
        while last and draw.textlength(last + "…", font=font) > max_width:
            last = last[:-1]
        kept[-1] = last + "…"
    return font, kept, size


def draw_multiline(draw, lines, font, xy, fill, line_gap=1.28):
    x, y = xy
    size = font.size
    for i, ln in enumerate(lines):
        draw.text((x, y + i * size * line_gap), ln, font=font, fill=fill)
    return y + len(lines) * size * line_gap


# ---------------------------------------------------------------- 底纹

def gradient_bg(w, h, c1, c2):
    img = Image.new("RGBA", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        d.line([(0, y), (w, y)], fill=mix(c1, c2, y / max(h - 1, 1)) + (255,))
    return img


def pick_size_profile(w, h):
    """按画幅选择标题风格档位：缩略图 / 方形 / 横版。"""
    if min(w, h) <= 260:
        return SIZES["thumb"]
    if h >= 800:
        return SIZES["square"]
    return SIZES["main"]


def profile(w, h):
    """返回 (标题最大行数, 字号候选档位)。"""
    _, _, max_lines, sizes = pick_size_profile(w, h)
    return max_lines, sizes


def add_decor(img, accent, dark_base: bool):
    """右上角同心圆，制造层次，别太抢。"""
    w, h = img.size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = int(w * 0.92), int(-h * 0.18)
    for i, r in enumerate([int(h * 1.15), int(h * 0.9), int(h * 0.66)]):
        a = (26, 20, 14)[i] if dark_base else (30, 24, 18)[i]
        d.ellipse([cx - r, cy - r, cx + r, cy + r],
                  outline=accent + (a,), width=max(2, int(h * 0.008)))
    return Image.alpha_composite(img.convert("RGBA"), layer)


def finish(img, out_path):
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    img.convert("RGB").save(out_path, "PNG", optimize=True)
    return out_path


# ---------------------------------------------------------------- 模板

def style_gradient(w, h, title, subtitle, tag, author, accent, fonts):
    a = hex2rgb(accent)
    base = darken(a, 0.55)
    mid = darken(a, 0.28)
    img = gradient_bg(w, h, base, mid)
    img = add_decor(img, a, dark_base=True)
    d = ImageDraw.Draw(img)

    pad = int(w * 0.062)
    side_reserve = int(w * 0.16)  # 右侧留给装饰圆

    y = pad
    if tag:
        f = fonts.get(max(13, int(h * 0.042)), bold=False)
        tw = d.textlength(tag, font=f)
        chip = [pad, y, pad + tw + int(h * 0.07), y + int(h * 0.075)]
        d.rounded_rectangle(chip, radius=int(h * 0.037), fill=a + (56,))
        d.text((pad + int(h * 0.035), y + int(h * 0.012)), tag, font=f,
               fill=rgba("#ffffff", 235))
        y = chip[3] + int(h * 0.045)

    max_w = w - pad * 2 - side_reserve
    font, lines, size = fit_title(title, fonts, d, max_w, *profile(w, h))
    bottom_of_title = draw_multiline(d, lines, font, (pad, y), rgba("#ffffff"))

    if subtitle:
        fs = max(13, int(size * 0.34))
        sf = fonts.get(fs, bold=False)
        sub_lines = wrap_text(subtitle, sf, max_w, d)[:2]
        draw_multiline(d, sub_lines, sf,
                       (pad, bottom_of_title + int(h * 0.02)),
                       rgba("#ffffff", 200), line_gap=1.4)

    if author:
        af = fonts.get(max(12, int(h * 0.038)), bold=False)
        d.text((pad, h - pad - int(h * 0.05)), author, font=af,
               fill=rgba("#ffffff", 175))
    return img


def style_minimal(w, h, title, subtitle, tag, author, accent, fonts):
    a = hex2rgb(accent)
    img = Image.new("RGBA", (w, h), (252, 252, 250, 255))
    d = ImageDraw.Draw(img)

    pad = int(w * 0.062)
    bar_w = max(6, int(w * 0.012))
    x = pad + bar_w + int(w * 0.028)
    max_w = w - x - pad - int(w * 0.04)
    y = int(h * 0.17)

    # 先量文字，再画竖条，保证竖条与文字块高度贴合
    tag_h = int(h * 0.075) if tag else 0
    if tag:
        tf = fonts.get(max(13, int(h * 0.042)), bold=False)
        d.text((x, y - tag_h), tag.upper(), font=tf, fill=a + (255,))

    font, lines, size = fit_title(title, fonts, d, max_w, *profile(w, h))
    text_h = len(lines) * size * 1.28
    block_end = y + text_h

    if subtitle:
        fs = max(13, int(size * 0.34))
        sf = fonts.get(fs, bold=False)
        sub_lines = wrap_text(subtitle, sf, max_w, d)[:2]
        block_end += int(h * 0.018) + len(sub_lines) * fs * 1.4

    d.rectangle([pad, y, pad + bar_w, int(block_end)], fill=a + (255,))

    bottom = draw_multiline(d, lines, font, (x, y), hex2rgb("#16181d"))

    if subtitle:
        draw_multiline(d, sub_lines, sf,
                       (x, bottom + int(h * 0.018)), hex2rgb("#6b7280"), line_gap=1.4)

    if author:
        af = fonts.get(max(12, int(h * 0.038)), bold=False)
        d.text((x, h - pad - int(h * 0.05)), author, font=af, fill=hex2rgb("#9aa1ab"))
    return img


def style_band(w, h, title, subtitle, tag, author, accent, fonts):
    a = hex2rgb(accent)
    base = darken(a, 0.62)
    img = Image.new("RGBA", (w, h), base + (255,))
    d = ImageDraw.Draw(img)

    # 底部色带 + 顶部细线
    band_h = int(h * 0.1)
    d.rectangle([0, h - band_h, w, h], fill=a + (255,))
    d.rectangle([0, 0, w, max(3, int(h * 0.012))], fill=a + (255,))

    pad = int(w * 0.062)
    y = int(h * 0.16)

    if tag:
        tf = fonts.get(max(13, int(h * 0.042)), bold=False)
        d.text((pad, y - int(h * 0.045)), tag.upper(), font=tf, fill=lighten(a, 0.35) + (255,))
        y += int(h * 0.01)

    max_w = w - pad * 2
    font, lines, size = fit_title(title, fonts, d, max_w, *profile(w, h))
    bottom = draw_multiline(d, lines, font, (pad, y), rgba("#ffffff"))

    if subtitle:
        fs = max(13, int(size * 0.34))
        sf = fonts.get(fs, bold=False)
        draw_multiline(d, wrap_text(subtitle, sf, max_w, d)[:2], sf,
                       (pad, bottom + int(h * 0.02)), rgba("#ffffff", 190), line_gap=1.4)

    if author:
        af = fonts.get(max(12, int(h * 0.038)), bold=False)
        d.text((pad, h - band_h + int(band_h * 0.28)), author, font=af,
               fill=rgba("#ffffff", 235))
    return img


STYLES = {
    "gradient": style_gradient,
    "minimal": style_minimal,
    "band": style_band,
}


# ---------------------------------------------------------------- 主流程

def load_theme_colors(name: str):
    path = os.path.join(THEME_DIR, name + ".json")
    if not os.path.isfile(path):
        return DEFAULTS
    with open(path, encoding="utf-8") as fh:
        theme = json.load(fh)
    colors = dict(DEFAULTS)
    colors["accent"] = theme.get("colors", {}).get("accent", DEFAULTS["accent"])
    return colors


def get_title_from_md(path: str):
    with open(path, encoding="utf-8") as fh:
        md = fh.read()
    m = re.search(r"^#\s+(.+)$", md, re.M)
    if m:
        return m.group(1).strip()
    for ln in md.splitlines():
        if ln.strip() and not ln.startswith((">", "|", "#", "-", "*")):
            return ln.strip()[:40]
    return ""


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="公众号封面图生成（900×383 / 1080×1080 / 200×200）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--title", help="封面主标题")
    ap.add_argument("--md", help="从 Markdown 文件取 H1 作为标题")
    ap.add_argument("--subtitle", default="", help="副标题（可选）")
    ap.add_argument("--tag", default="", help="左上角标签，如「技术拆解」")
    ap.add_argument("--author", default="", help="底部作者/品牌名")
    ap.add_argument("--theme", help="取色主题（默认取 frontmatter 的 theme，否则 tech）")
    ap.add_argument("--style", default="gradient", choices=sorted(STYLES),
                    help="版式：gradient / minimal / band")
    ap.add_argument("-o", "--out", default="cover.png", help="输出路径（--all 时为前缀）")
    ap.add_argument("--all", action="store_true", help="同时输出 square 和 thumb")
    ap.add_argument("--size", default="main", choices=sorted(SIZES),
                    help="只出一张时选尺寸，默认 main")
    ap.add_argument("--font", help="指定中文字体路径（.ttf/.ttc）")
    args = ap.parse_args(argv)

    # 优先命令行，其次 markdown 的 frontmatter，最后取 H1
    meta = {}
    if args.md and os.path.isfile(args.md):
        meta, body = wxmeta.load(args.md)
        if body.strip():
            meta.setdefault("_h1", wxmeta.first_h1(body))

    # 封面用长标题（钩子更足）；确认想换文字时用 frontmatter 的 cover_title 覆盖
    title = (args.title or meta.get("cover_title") or meta.get("title")
             or meta.get("title_short") or meta.get("_h1"))
    if not title:
        raise SystemExit("缺少标题：用 --title 或 --md 指定")

    tag = args.tag or meta.get("tag", "")
    author = args.author or wxmeta.resolve_author(meta)
    theme_name = args.theme or meta.get("theme") or "tech"

    colors = load_theme_colors(theme_name)
    accent = colors["accent"]
    fonts = Fonts(args.font)
    style_fn = STYLES[args.style]

    def render(size_key, out_path):
        w, h, _max_lines, _sizes = SIZES[size_key]
        img = style_fn(w, h, title, args.subtitle, tag, author, accent, fonts)
        finish(img, out_path)
        print("✓ %-24s %dx%d" % (out_path, w, h))

    if args.all:
        prefix = re.sub(r"\.png$", "", args.out)
        render("main", prefix + ".png")
        render("square", prefix + "-square.png")
        render("thumb", prefix + "-thumb.png")
    else:
        render(args.size, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
