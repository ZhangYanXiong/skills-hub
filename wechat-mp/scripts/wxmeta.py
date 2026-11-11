#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wxmeta.py — 各脚本共享的小工具

为什么单独抽一层:
    标题、摘要、短标题、作者、封面标签这些元信息，原本要分别用 --title / --summary /
    --tag / --author 重复传三遍（md2wx / cover / check 各一次），既啰嗦又容易写错。
    统一写进 Markdown 开头的 frontmatter，三个脚本都从这里读。

frontmatter 格式（放在文章最前面，用 --- 包起来）:

    ---
    title: 长标题，≤64 字
    title_short: 短标题，≤20 字，信息流展示用
    cover_title: 封面图上另写一句（省略则用 title）
    summary: 摘要，≤120 字
    author: 作者名
    tag: 封面左上角标签，2~4 字
    theme: growth
    ---

依赖: 仅标准库。
"""

import hashlib
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
THEME_DIR = os.path.join(HERE, "themes")

FM_RE = re.compile(r"^---[ \t]*\n(.*?)\n---[ \t]*(?:\n|$)", re.S)
KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")

# 默认署名：frontmatter 没写 author 时使用
DEFAULT_AUTHOR = "云光迷途"

# 生成器版本：改动渲染逻辑时手动递增，会让所有旧产物被判定为陈旧
GENERATOR_VERSION = "2.2.0"

# 已知字段，供文档与校验用
KNOWN_KEYS = ("title", "title_short", "cover_title", "summary", "author", "tag", "theme")


def parse_frontmatter(text: str):
    """返回 (meta, body)。没有 frontmatter 时 meta 为空字典，body 为原文。"""
    m = FM_RE.match(text)
    if not m:
        return {}, text

    meta = {}
    for raw in m.group(1).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        kv = KV_RE.match(line)
        if not kv:
            continue
        key, val = kv.group(1), kv.group(2).strip()
        # 去掉成对的引号
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        meta[key] = val
    return meta, text[m.end():]


def load(path: str):
    """读文件并拆出 (meta, body)。"""
    with open(path, encoding="utf-8") as fh:
        return parse_frontmatter(fh.read())


def count_words(text: str) -> int:
    """中文按字、英文按词计数，全项目统一口径。"""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z0-9_][A-Za-z0-9_\-']*", text))
    return cjk + latin


def first_h1(text: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else ""


def theme_names():
    if not os.path.isdir(THEME_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(THEME_DIR) if f.endswith(".json"))


# ---------------------------------------------------------------- Markdown 围栏（渲染与检查共用）


def fence_open(line):
    match = re.match(r'^\s*(`{3,}|~{3,})(.*)$', line)
    if not match or (match.group(1)[0] == '`' and '`' in match.group(2)):
        return None
    return match.group(1), match.group(2).strip()


def fence_closes(line, marker):
    return bool(re.fullmatch(r'\s*' + re.escape(marker[0]) + '{%d,}[ \t]*' % len(marker), line))


def mask_code(text):
    out, marker = [], None
    for line in text.split('\n'):
        if marker:
            closes = fence_closes(line, marker)
            out.append(' ' * len(line))
            if closes:
                marker = None
        else:
            opening = fence_open(line)
            if opening:
                marker = opening[0]
                out.append(' ' * len(line))
            else:
                out.append(line)
    return re.sub(r'`[^`\n]*`', lambda m: ' ' * len(m.group(0)), '\n'.join(out))


# ---------------------------------------------------------------- 构建指纹

IMAGE_REF_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)")


def local_images(md: str):
    """抽出正文里引用的本地图片路径（排除 http/https 与 data URI）。"""
    out = []
    for m in IMAGE_REF_RE.finditer(md):
        src = m.group(1).strip()
        if src.startswith(("http://", "https://", "data:")):
            continue
        out.append(src)
    return out


# 参与指纹的渲染代码：改渲染逻辑即自动让旧产物失效，不依赖人记得升版本号
_CODE_FILES = ("md2wx.py", "wxmeta.py", "wxbuild.py")


def _code_hash() -> str:
    h = hashlib.sha256()
    for name in _CODE_FILES:
        path = os.path.join(HERE, name)
        try:
            with open(path, "rb") as fh:
                h.update(fh.read())
        except OSError:
            h.update(name.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def fingerprint(md: str, theme: dict, images=None, options=None, asset_hashes=None) -> str:
    """交付物指纹：代码、源稿、有效主题/渲染参数及本地资产内容。

    为什么不用 mtime: 复制、touch、网盘同步、git checkout 都会改 mtime，
    而内容指纹只随真实输入变化。
    为什么哈希渲染代码: 否则改了渲染逻辑却忘记升 GENERATOR_VERSION，
    旧产物会被误判为「最新」。
    """
    h = hashlib.sha256()
    h.update(GENERATOR_VERSION.encode("utf-8"))
    h.update(_code_hash().encode("ascii"))
    h.update(b"\x00")
    h.update(md.encode("utf-8"))
    h.update(b"\x00")
    h.update(json.dumps(theme, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    h.update(b"\x00")
    imgs = images if images is not None else local_images(md)
    for p in sorted(set(imgs)):
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    for value in (options or {}, asset_hashes or {}):
        h.update(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8'))
        h.update(b'\x00')
    return h.hexdigest()[:12]


def extract_fingerprint(text: str):
    """从已生成的 HTML 里取回指纹；取不到返回 None。"""
    m = re.search(r'<meta name="wx-build" content="([0-9a-f]{6,40})"', text)
    if m:
        return m.group(1)
    m = re.search(r"<!--\s*wx-build:\s*([0-9a-f]{6,40})\s*-->", text)
    return m.group(1) if m else None


def resolve_author(meta: dict) -> str:
    """署名优先级：frontmatter 的 author > 默认署名。"""
    value = (meta or {}).get("author") or ""
    return value.strip() or DEFAULT_AUTHOR
