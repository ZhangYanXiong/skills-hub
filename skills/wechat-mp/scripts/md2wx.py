#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
md2wx.py — Markdown → 微信公众号可用 HTML（纯内联样式）

为什么需要它:
    微信编辑器只保留元素的 style 属性，会丢弃 <style> / class / 外部 CSS。
    所以排版必须把样式全部内联到每个标签上，本脚本负责这件事。

依赖: 仅标准库。

用法:
    python3 md2wx.py article.md -t tech -o article.html
    python3 md2wx.py article.md -t growth --no-body
    python3 md2wx.py article.md --list-themes

产物:
    article.html        完整页面（浏览器打开 → 全选复制 → 粘贴进公众号编辑器）
    article.body.html   纯正文片段（给 L3 草稿箱 API 用，或粘进第三方编辑器）

支持的 Markdown 子集:
    标题 # ~ ######、段落、**粗体**、*斜体*、`行内代码`、~~删除线~~、==高亮==
    [链接](url)、![图片](src "可选标题")、有序/无序列表（可嵌套）、引用、分割线
    ``` 代码块、GFM 表格、> [!NOTE] 提示框（NOTE/TIP/WARNING/IMPORTANT）
    行尾两个空格 → 换行
"""

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
THEME_DIR = os.path.join(HERE, "themes")

if HERE not in sys.path:
    sys.path.insert(0, HERE)
import wxmeta  # noqa: E402  同目录共享工具
import wxbuild  # noqa: E402  生成与校验共用构建上下文

# 微信正文区最大宽度（PC 端阅读页内容区约 677px）
CONTENT_WIDTH = "677px"

# 提示框类型 → 在主题里取色的键名
CALLOUT_TYPES = {
    "NOTE": "note",
    "TIP": "tip",
    "WARNING": "warning",
    "IMPORTANT": "important",
    "CAUTION": "warning",
}


# ---------------------------------------------------------------- 样式工具

def to_kebab(name: str) -> str:
    """camelCase → kebab-case，同时兼容已经写成 kebab 的键。"""
    if "-" in name:
        return name
    return re.sub(r"[A-Z]", lambda m: "-" + m.group(0).lower(), name)


def S(styles) -> str:
    """把样式字典序列化成 style="..." 的属性值。"""
    if not styles:
        return ""
    parts = []
    for k, v in styles.items():
        if v is None or v == "":
            continue
        parts.append("%s:%s" % (to_kebab(k), v))
    return ";".join(parts)


def tag(name: str, styles, inner: str = "") -> str:
    """生成带内联样式的标签。"""
    s = S(styles)
    attr = ' style="%s"' % s if s else ""
    if name in ("img", "br", "hr"):
        return "<%s%s>" % (name, attr)
    return "<%s%s>%s</%s>" % (name, attr, inner, name)


# ---------------------------------------------------------------- 主题加载

def load_theme(name: str) -> dict:
    path = os.path.join(THEME_DIR, name + ".json")
    if not os.path.isfile(path):
        available = sorted(
            f[:-5] for f in os.listdir(THEME_DIR) if f.endswith(".json")
        )
        raise SystemExit(
            "找不到主题 %r。可用主题: %s" % (name, ", ".join(available) or "（无）")
        )
    with open(path, encoding="utf-8") as fh:
        theme = json.load(fh)

    # 允许主题只写增量：父主题合并
    parent = theme.get("extends")
    if parent:
        base = load_theme(parent)
        merged = deep_merge(base, theme)
        merged.pop("extends", None)
        theme = merged
    return theme


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Renderer:
    def __init__(self, theme: dict):
        self.t = theme
        st = theme.get("styles", {})
        self.st = st
        self.body = st.get("body", {})
        self.p = st.get("p", {})
        self.colors = theme.get("colors", {})

    # -- 取样式块
    def s(self, key: str) -> dict:
        return dict(self.st.get(key, {}) or {})

    def merge(self, key: str, extra: dict) -> dict:
        d = self.s(key)
        d.update(extra or {})
        return d

    # ------------------------------------------------------ 块级渲染
    def paragraph(self, text: str) -> str:
        inner = self.inline(text)
        return tag("section", self.p, inner)

    def heading(self, level: int, text: str) -> str:
        key = "h%d" % level
        styles = self.s(key)
        decoration = styles.pop("decoration", None)
        inner = self.inline(text)

        if decoration == "bar":
            styles.setdefault("borderLeft", "%s solid %s" % (
                styles.pop("barWidth", "4px"),
                self.colors.get("accent", "#333"),
            ))
            styles.setdefault("paddingLeft", "10px")
        elif decoration == "underline":
            styles.setdefault("borderBottom", "2px solid %s" % self.colors.get("accent", "#333"))
            styles.setdefault("paddingBottom", "4px")
            styles.setdefault("display", "inline-block")
        elif decoration == "pill":
            styles.setdefault("backgroundColor", self.colors.get("accentSoft", "#eef2ff"))
            styles.setdefault("padding", "3px 12px")
            styles.setdefault("borderRadius", "6px")
            styles.setdefault("display", "inline-block")

        return tag("section", styles, inner)

    def quote(self, lines) -> str:
        # 先判断是不是 GitHub 风格提示框 > [!NOTE]
        head = lines[0].strip() if lines else ""
        m = re.match(r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(.*)$", head, re.I)
        if m:
            kind = CALLOUT_TYPES[m.group(1).upper()]
            title = m.group(2).strip()
            body_lines = [ln for ln in lines[1:]]
            return self.callout(kind, title, body_lines)

        styles = self.s("quote")
        inner = []
        # 引用内允许空行分段
        for chunk in split_blank(lines):
            if not chunk:
                continue
            inner.append(tag("section", self.s("quoteP"), self.inline("\n".join(chunk))))
        return tag("section", styles, "".join(inner))

    def callout(self, kind: str, title: str, lines) -> str:
        base = self.s("callout")
        border = self.colors.get(kind, self.colors.get("accent", "#3b82f6"))
        soft = self.colors.get(kind + "Soft", self.colors.get("accentSoft", "#eff6ff"))
        base.setdefault("borderLeft", "3px solid %s" % border)
        base.setdefault("backgroundColor", soft)

        parts = []
        if title:
            parts.append(tag("section", self.merge("calloutTitle", {"color": border}), self.inline(title)))
        for chunk in split_blank(lines):
            if not chunk:
                continue
            parts.append(tag("section", self.s("calloutBody"), self.inline("\n".join(chunk))))
        return tag("section", base, "".join(parts))

    def code_block(self, code: str, lang: str) -> str:
        base = self.s("codeBlock")
        pre = self.s("pre")
        pre_code = self.s("preCode")
        body = escape_for_code(code)
        code_html = tag("code", pre_code, body)
        parts = []
        if lang and self.t.get("showCodeLang", True):
            label = tag("section", self.s("codeLang"), html.escape(lang))
            parts.append(label)
        parts.append(tag("pre", pre, code_html))
        return tag("section", base, "".join(parts))

    def list_block(self, items, ordered: bool) -> str:
        """items: [(depth, text)]，自绘项目符号以获得稳定的悬挂缩进。"""
        out = []
        bullet_key = "olNumber" if ordered else "bullet"
        item_key = "olItem" if ordered else "ulItem"
        counters = {}

        for depth, text in items:
            counters[depth] = counters.get(depth, 0) + 1
            # 回到较浅层级时重置更深层计数
            for d in list(counters):
                if d > depth:
                    del counters[d]

            indent = 1.5 + depth * 1.5
            styles = self.merge(item_key, {
                "paddingLeft": "%sem" % indent,
                "textIndent": "-1.5em",
            })

            if ordered:
                marker = "%d." % counters[depth]
                # 两位以上数字收窄字距，避免数字挤压正文
                marker_styles = self.merge(bullet_key, {"paddingRight": "0.35em"})
            else:
                marker = "•"
                marker_styles = self.merge(bullet_key, {"paddingRight": "0.35em"})

            marker_html = tag("span", marker_styles, marker)
            content = self.inline(text)
            out.append(tag("section", styles, marker_html + content))
        return "".join(out)

    def table(self, rows, aligns) -> str:
        wrap = self.s("tableWrap")
        tbl = self.s("table")
        th = self.s("th")
        td = self.s("td")

        ncol = len(rows[0]) if rows else 0
        head = rows[0]
        body = rows[1:]

        def cell(txt, i, styles, is_head):
            st = dict(styles)
            a = aligns[i] if i < len(aligns) else "left"
            if a != "left":
                st.setdefault("textAlign", a)
            if is_head:
                st.pop("textAlign", None)
                st["textAlign"] = "left"
            return tag("th" if is_head else "td", st, self.inline(txt))

        html_parts = []
        # 手写 table 结构以获得完全控制
        parts = []
        parts.append("<table")
        ts = S(tbl)
        if ts:
            parts.append(' style="%s"' % ts)
        parts.append(">")

        if head:
            parts.append("<thead><tr>")
            for i in range(ncol):
                txt = head[i] if i < len(head) else ""
                parts.append(cell(txt, i, th, True))
            parts.append("</tr></thead>")

        parts.append("<tbody>")
        for row in body:
            parts.append("<tr>")
            for i in range(ncol):
                txt = row[i] if i < len(row) else ""
                parts.append(cell(txt, i, td, False))
            parts.append("</tr>")
        parts.append("</tbody></table>")

        return tag("section", wrap, "".join(parts))

    def image(self, src: str, alt: str, title: str) -> str:
        img_styles = self.s("img")
        caption = title or alt
        fig = self.s("figure")
        inner = '<img src="%s" alt="%s"%s>' % (
            html.escape(src, quote=True),
            html.escape(alt, quote=True),
            (' style="%s"' % S(img_styles)) if img_styles else "",
        )
        if caption:
            cap = tag("section", self.s("figcaption"), self.inline(caption))
            inner += cap
        return tag("section", fig, inner)

    def hr(self) -> str:
        return tag("section", self.s("hr"), html.escape(self.t.get("hrGlyph", "· · ·")))

    def blank(self) -> str:
        return ""

    # ------------------------------------------------------ 行内渲染
    def inline(self, text: str) -> str:
        # 1) 先保护行内代码，避免内部 * _ 被当格式
        slots = []

        def stash(m):
            slots.append(m.group(1))
            return "\x00%d\x00" % (len(slots) - 1)

        text = re.sub(r"`([^`\n]+)`", stash, text)

        # 2) HTML 转义（此时残留的是纯文本 + markdown 标记）
        text = html.escape(text, quote=True)
        # 换行必须在转义之后插入 <br>，否则会被当成普通字符转义掉
        text = text.replace("\n", "<br>")

        # 3) 图片必须在链接之前处理
        text = re.sub(
            r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;([^&]*)&quot;)?\)",
            lambda m: self._img_token(m.group(1), m.group(2), m.group(3) or ""),
            text,
        )
        # 4) 链接
        text = re.sub(
            r"\[([^\]]+)\]\(([^)\s]+)\)",
            lambda m: self._link_token(m.group(1), m.group(2)),
            text,
        )
        # 5) 删除线 → 6) 高亮 → 7) 粗体 → 8) 斜体
        text = re.sub(r"~~([^~]+)~~", lambda m: tag("span", self.s("strike"), m.group(1)), text)
        text = re.sub(r"==([^=]+)==", lambda m: tag("span", self.s("mark"), m.group(1)), text)
        text = re.sub(r"\*\*([^\n]+?)\*\*", lambda m: tag("strong", self.s("strong"), m.group(1)), text)
        text = re.sub(r"(?<![\*\w])\*([^\*\n]+?)\*(?![\*\w])", lambda m: tag("em", self.s("em"), m.group(1)), text)
        text = re.sub(r"__([^\n]+?)__", lambda m: tag("strong", self.s("strong"), m.group(1)), text)

        # 9) 还原行内代码
        def restore(m):
            code = slots[int(m.group(1))]
            return tag("code", self.s("code"), html.escape(code))

        text = re.sub(r"\x00(\d+)\x00", restore, text)
        return text

    def _img_token(self, alt: str, src: str, title: str) -> str:
        return self.image(html.unescape(src), html.unescape(alt), html.unescape(title))

    def _link_token(self, label: str, href: str) -> str:
        styles = self.s("link")
        st = S(styles)
        attr = ' style="%s"' % st if st else ""
        return '<a href="%s"%s>%s</a>' % (html.escape(html.unescape(href), quote=True), attr, label)


# ---------------------------------------------------------------- 解析工具

def split_blank(lines):
    """按空行切块。"""
    chunks, cur = [], []
    for ln in lines:
        if ln.strip() == "":
            if cur:
                chunks.append(cur)
                cur = []
        else:
            cur.append(ln)
    if cur:
        chunks.append(cur)
    return chunks


def escape_for_code(code: str) -> str:
    return html.escape(code)


def count_words(text: str) -> int:
    """中文按字、英文按词计数，与 check.py 口径一致。"""
    return wxmeta.count_words(text)


def count_indent(line: str) -> int:
    m = re.match(r"^(\s*)", line)
    return len(m.group(1).replace("\t", "    "))


def split_row(line: str):
    """拆表格行，忽略被转义的 \\|。"""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    cells, cur, esc = [], "", False
    for ch in s:
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == "|":
            cells.append(cur.strip())
            cur = ""
        else:
            cur += ch
    cells.append(cur.strip())
    return cells


SEP_RE = re.compile(r"^\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?$")


def is_table_start(lines, i) -> bool:
    if i + 1 >= len(lines):
        return False
    if "|" not in lines[i]:
        return False
    sep = lines[i + 1].strip()
    if not sep or "|" not in sep and not SEP_RE.match(sep):
        return False
    return bool(SEP_RE.match(sep)) and "-" in sep


# ---------------------------------------------------------------- 主解析

FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([\w+#.-]*)\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
HR_RE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
UL_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
OL_RE = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")


def parse(md: str, r: Renderer):
    """返回 (fragment, toc)。"""
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out = []
    toc = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        # --- 空行
        if line.strip() == "":
            i += 1
            continue

        # --- 代码块
        fm = wxmeta.fence_open(line)
        if fm:
            fence, info = fm
            lang = re.match(r'[\w+#.-]*', info).group(0)
            i += 1
            buf = []
            while i < n and not wxmeta.fence_closes(lines[i], fence):
                buf.append(lines[i])
                i += 1
            i += 1  # 跳过结束围栏
            out.append(r.code_block("\n".join(buf), lang))
            continue

        # --- 标题
        hm = HEADING_RE.match(line)
        if hm:
            level = len(hm.group(1))
            text = hm.group(2)
            if level <= 3:
                toc.append((level, text))
            out.append(r.heading(level, text))
            i += 1
            continue

        # --- 分割线
        if HR_RE.match(line):
            out.append(r.hr())
            i += 1
            continue

        # --- 引用
        qm = QUOTE_RE.match(line)
        if qm:
            buf = []
            while i < n:
                m2 = QUOTE_RE.match(lines[i])
                if m2:
                    buf.append(m2.group(1))
                    i += 1
                elif lines[i].strip() == "":
                    # 引用内允许空行，但后面必须还是引用
                    j = i + 1
                    if j < n and QUOTE_RE.match(lines[j]):
                        buf.append("")
                        i += 1
                    else:
                        break
                else:
                    break
            out.append(r.quote(buf))
            continue

        # --- 表格
        if is_table_start(lines, i):
            header = split_row(lines[i])
            aligns = []
            for c in split_row(lines[i + 1]):
                c = c.strip()
                if c.startswith(":") and c.endswith(":"):
                    aligns.append("center")
                elif c.endswith(":"):
                    aligns.append("right")
                else:
                    aligns.append("left")
            i += 2
            rows = [header]
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(split_row(lines[i]))
                i += 1
            out.append(r.table(rows, aligns))
            continue

        # --- 列表（连续行，支持空行分隔的松散列表）
        list_match = UL_RE.match(line) or OL_RE.match(line)
        if list_match:
            ordered = bool(OL_RE.match(line)) and not UL_RE.match(line)
            items = []
            while i < n:
                m_ul = UL_RE.match(lines[i])
                m_ol = OL_RE.match(lines[i])
                if m_ul:
                    depth = min(count_indent(lines[i]) // 2, 4)
                    items.append((depth, m_ul.group(2)))
                    i += 1
                elif m_ol:
                    depth = min(count_indent(lines[i]) // 2, 4)
                    items.append((depth, m_ol.group(3)))
                    i += 1
                elif lines[i].strip() == "":
                    # 空行后仍可能续列表
                    j = i + 1
                    if j < n and (UL_RE.match(lines[j]) or OL_RE.match(lines[j])):
                        i += 1
                        continue
                    break
                else:
                    break
            out.append(r.list_block(items, ordered))
            continue

        # --- 段落
        buf = [line]
        i += 1
        while i < n:
            nxt = lines[i]
            if nxt.strip() == "":
                break
            if (wxmeta.fence_open(nxt) or HEADING_RE.match(nxt) or HR_RE.match(nxt)
                    or QUOTE_RE.match(nxt) or UL_RE.match(nxt) or OL_RE.match(nxt)):
                break
            if is_table_start(lines, i):
                break
            buf.append(nxt)
            i += 1
        out.append(r.paragraph("\n".join(buf)))

    return "".join(out), toc


# ---------------------------------------------------------------- 输出

def build_document(fragment: str, title: str, theme: dict, build_fp: str = "") -> str:
    body_css = S(theme.get("page", {}))
    wrap = dict(theme.get("wrapper", {}) or {})
    width = wrap.pop("maxWidth", None) or CONTENT_WIDTH
    wrap_s = S(wrap)

    style_block = (
        "html{-webkit-text-size-adjust:100%;}"
        "body{margin:0;padding:0;" + body_css + "}"
        ".wx-page{max-width:" + width + ";margin:0 auto;padding:24px 20px;}"
    )

    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
%s<title>%s</title>
<style>%s</style>
</head>
<body>
<div class="wx-page"%s>
%s
</div>
</body>
</html>
""" % ((' <meta name="wx-build" content="%s">\n' % build_fp) if build_fp else "",
       html.escape(title), style_block, (' style="%s"' % wrap_s) if wrap_s else "", fragment)


# ---------------------------------------------------------------- 发布工作台

SHEET_CSS = """
*{box-sizing:border-box}
body{margin:0;padding:24px;background:#eef1f5;color:#1f2328;
     font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif;
     font-size:14px;-webkit-font-smoothing:antialiased}
.wrap{max-width:1120px;margin:0 auto;display:grid;grid-template-columns:minmax(0,400px) minmax(0,1fr);gap:18px;align-items:start}
@media(max-width:880px){.wrap{grid-template-columns:1fr}}
.card{background:#fff;border-radius:12px;padding:18px 20px;margin-bottom:14px;
      box-shadow:0 1px 3px rgba(16,24,40,.07),0 1px 2px rgba(16,24,40,.04)}
h1{font-size:17px;margin:0 0 4px}
.sub{color:#7a8494;font-size:12.5px;margin-bottom:16px}
.field{margin-bottom:15px}
.label{font-size:12px;color:#7a8494;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center;gap:8px}
.value{font-size:14px;line-height:1.7;background:#f6f8fa;border:1px solid #e9edf2;border-radius:8px;
       padding:10px 12px;word-break:break-word;white-space:pre-wrap}
.row{display:flex;gap:8px;align-items:center}
button{cursor:pointer;border:1px solid #d8dee6;background:#fff;border-radius:7px;padding:5px 11px;
       font-size:12px;color:#374151;font-family:inherit;transition:background .15s,border-color .15s}
button:hover{background:#f3f5f8}
button:active{transform:translateY(1px)}
button.primary{background:#2f6fed;color:#fff;border-color:#2f6fed}
button.primary:hover{background:#255ccf}
.covers{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.cover{width:100%;border-radius:8px;border:1px solid #e5e9ef;display:block}
.cover-label{font-size:11.5px;color:#7a8494;margin-top:5px}
.check{font-size:13px;line-height:2;color:#374151}
.check input{margin-right:7px;vertical-align:middle}
#article-body{max-height:72vh;overflow:auto;border:1px solid #e5e9ef;border-radius:8px;padding:16px;background:#fff}
.hint{font-size:12px;color:#8a94a0;margin-top:9px;line-height:1.65}
.tag{display:inline-block;font-size:11px;background:#eef3ff;color:#2f6fed;border-radius:999px;padding:2px 9px;margin-left:6px}
.warn{background:#fff8ec;border:1px solid #f3dfbc;border-radius:8px;padding:10px 12px;font-size:12.5px;
      line-height:1.7;color:#7a5a1e;margin-top:10px}
.ok{color:#0d9488;font-size:11.5px;min-width:44px}
"""

SHEET_JS = """
function flash(btn,text,ms){var o=btn.textContent;btn.textContent=text;
  setTimeout(function(){btn.textContent=o;},ms||1500);}
function copyText(btn,id){
  var el=document.getElementById(id);
  var t=el.innerText;
  var ta=document.createElement('textarea');
  ta.value=t;ta.style.position='fixed';ta.style.top='-9999px';ta.style.opacity='0';
  document.body.appendChild(ta);ta.focus();ta.select();
  var ok=false;
  try{ok=document.execCommand('copy');}catch(e){ok=false;}
  document.body.removeChild(ta);
  if(ok){flash(btn,'已复制');return;}
  // 失败时退回「选中原文，让用户手动 Cmd+C」
  var r=document.createRange();r.selectNodeContents(el);
  var sel=window.getSelection();sel.removeAllRanges();sel.addRange(r);
  flash(btn,'已选中，请按 Cmd+C',2600);
}
async function copyImg(btn,src){
  try{
    var resp=await fetch(src);
    if(!resp.ok) throw new Error('fetch failed');
    var blob=await resp.blob();
    await navigator.clipboard.write([new ClipboardItem({'image/png':blob})]);
    flash(btn,'已复制图片',1800);return;
  }catch(e){}
  window.open(src,'_blank');
  flash(btn,'已打开，右键复制',2600);
}
function copyBody(btn){
  var el=document.getElementById('article-body');
  var r=document.createRange();r.selectNodeContents(el);
  var sel=window.getSelection();sel.removeAllRanges();sel.addRange(r);
  var ok=false;
  try{ok=document.execCommand('copy');}catch(e){ok=false;}
  if(ok){flash(btn,'已复制正文');sel.removeAllRanges();return;}
  flash(btn,'已选中正文，请按 Cmd+C',2600);
}
"""


IMG_TAG_RE = re.compile(r'<img\s+src="([^"]*)"(?:\s+alt="([^"]*)")?')


def _body_images(fragment, out_dir):
    """抽出正文里的图片，生成「必须逐张上传」的清单数据。"""
    found = []
    for m in IMG_TAG_RE.finditer(fragment):
        src, alt = m.group(1), (m.group(2) or "")
        if src.startswith("data:"):
            kind = "data"
        elif src.startswith(("http://", "https://")):
            kind = "remote"
        else:
            kind = "local"
        exists = kind != "local" or os.path.isfile(os.path.join(out_dir, src))
        found.append({"src": src, "alt": alt, "kind": kind, "exists": exists})
    return found


def _body_images_card(fragment, out_dir):
    """正文图片清单：微信粘贴不会带走本地图片，必须逐张上传。"""
    images = _body_images(fragment, out_dir)
    if not images:
        return ""

    rows = []
    for i, im in enumerate(images, 1):
        if im["kind"] == "remote":
            status = '<span style="color:#b45309">外链图片会被防盗链拦截，先下载再上传</span>'
        elif im["kind"] == "data":
            status = '<span style="color:#b45309">内嵌图片，微信编辑器可能不认</span>'
        elif not im["exists"]:
            status = '<span style="color:#b91c1c">文件不存在，先生成图片</span>'
        else:
            status = '<span style="color:#0d9488">本地文件，需手动上传</span>'

        rows.append(
            '<div style="display:flex;gap:10px;align-items:center;padding:9px 0;'
            'border-bottom:1px solid #eef1f5">'
            '<img src="%s" alt="" style="width:96px;height:auto;border-radius:6px;'
            'border:1px solid #e5e9ef;flex:none">'
            '<div style="min-width:0;flex:1">'
            '<div style="font-size:12.5px;line-height:1.6"><b>第 %d 张</b> · %s</div>'
            '<div style="font-size:11.5px;color:#8a94a0;line-height:1.6">%s</div>'
            '<div style="font-size:11.5px;margin-top:3px">%s</div>'
            '<div style="margin-top:6px;display:flex;gap:8px;align-items:center">'
            "<button onclick=\"copyImg(this,'%s')\">复制图片</button>"
            '<a href="%s" target="_blank" style="font-size:11.5px;color:#2f6fed;'
            'text-decoration:none">打开原图</a>'
            "</div></div></div>"
            % (
                html.escape(im["src"]),
                i,
                html.escape(os.path.basename(im["src"])),
                html.escape(im["alt"] or "（无说明）"),
                status,
                im["src"],
                html.escape(im["src"]),
            )
        )

    return (
        '<div class="card"><div class="label"><span>正文图片（%d 张，必须逐张上传）</span>'
        "</div>"
        '<div class="hint" style="margin:0 0 6px">复制正文只带走文字和样式，'
        "<b>图片不会被带过去</b>。按顺序：点「复制图片」→ 到编辑器对应位置 Cmd+V；"
        "复制不了的，点「打开原图」后右键复制图片。</div>%s</div>"
        % (len(images), "".join(rows))
    )


def build_sheet(meta, theme, fragment, fallback_title, out_dir, words, imgs,
                build_fp="", built_at=""):
    """生成「发布工作台」单页：元信息一键复制 + 正文富文本一键复制。"""
    title_long = meta.get("title") or fallback_title
    title_short = meta.get("title_short", "")
    summary = meta.get("summary", "")
    author = wxmeta.resolve_author(meta)
    author_is_default = not (meta.get("author") or "").strip()
    tag = meta.get("tag", "")

    covers = []
    for fname, label in (("cover.png", "头条封面 900×383"),
                         ("cover-square.png", "方形 1080×1080"),
                         ("cover-thumb.png", "次条 200×200")):
        if os.path.isfile(os.path.join(out_dir, fname)):
            covers.append((fname, label))

    def field(name, label, value, hint="", big=False):
        if not value:
            return ""
        return (
            '<div class="field">'
            '<div class="label"><span>%s</span>'
            '<button onclick="copyText(this,\'f-%s\')">复制</button></div>'
            '<div class="value" id="f-%s">%s</div>%s</div>'
            % (
                label,
                name,
                name,
                html.escape(value),
                ('<div class="hint">%s</div>' % hint) if hint else "",
            )
        )

    fields = (
        field("title", "① 标题（长）<span class='tag'>%d 字 / 上限 64</span>" % len(title_long), title_long)
        + field("short", "② 短标题（信息流展示用）<span class='tag'>%d 字</span>" % len(title_short),
                title_short, "公众号后台只填一个标题；短标题供你检查前 20 字是否说得清。")
        + field("summary", "③ 摘要<span class='tag'>%d 字 / 上限 120</span>" % len(summary), summary)
        + field("author", "④ 作者（后台作者字段）", author,
                hint="来自默认署名；要换名字在 frontmatter 写 author: 你的名字"
                if author_is_default else "")
    )

    cover_html = ""
    if covers:
        cells = "".join(
            '<div><img class="cover" src="%s" alt="%s"><div class="cover-label">%s</div></div>'
            % (f, label, label) for f, label in covers
        )
        cover_html = (
            '<div class="card"><div class="label"><span>封面图</span></div>'
            '<div class="covers">%s</div>'
            '<div class="hint">上传时选 <b>cover.png</b> 作头条封面；次条用 cover-thumb.png。</div></div>'
            % cells
        )
    else:
        cover_html = (
            '<div class="card"><div class="label"><span>封面图</span></div>'
            '<div class="hint">还没生成封面。需要封面时，请先把 cover.png 等图片生成到工作台同目录，'
            '再用原稿及原参数重新运行 md2wx.py --sheet。'
            '刷新浏览器不会重新生成工作台；仅排版任务可以不生成封面。</div></div>'
        )

    checklist = [
        "标题、摘要已填入后台（不是正文里）",
        "封面图已上传，头条用 cover.png",
        "正文里的图片已在编辑器里逐张上传（本地图片不会自动带过去）",
        "文末「阅读原文」链接已设置（如需要）",
        "留言、打赏、原创声明按要求开启",
        "通读一遍手机预览，重点看表格和代码块",
    ]
    check_html = "".join(
        '<div><input type="checkbox">%s</div>' % item for item in checklist
    )

    theme_label = "%s · %s" % (theme.get("label", ""), meta.get("theme") or "tech")

    out = (
        '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        "<title>发布工作台 · %s</title>\n<style>%s</style>\n</head>\n<body>\n"
        '<div class="wrap">\n<div>\n'
        '<div class="card">\n<h1>发布工作台</h1>\n'
        '<div class="sub">%s · %d 字 · %d 张图</div>\n%s\n</div>\n'
        "%s\n"
        "%s\n"
        '<div class="card"><div class="label"><span>发布前清单</span></div>'
        '<div class="check">%s</div></div>\n'
        "</div>\n<div>\n"
        '<div class="card">\n'
        '<div class="row" style="justify-content:space-between;margin-bottom:11px">'
        '<b style="font-size:14px">正文</b>'
        '<button class="primary" onclick="copyBody(this)">复制正文</button></div>\n'
        '<div id="article-body">%s</div>\n'
        '<div class="warn">按钮复制的是<b>富文本</b>（保留内联样式），粘贴到公众号编辑区格式不会散。'
        "但<b>图片不会被带过去</b>——按左侧「正文图片」清单逐张上传。</div>\n"
        "</div>\n</div>\n</div>\n<script>%s</script>\n</body>\n</html>\n"
        % (
            html.escape(title_short or title_long),
            SHEET_CSS,
            html.escape(theme_label),
            words,
            imgs,
            fields,
            cover_html,
            _body_images_card(fragment, out_dir),
            check_html,
            fragment,
            SHEET_JS,
        )
    )

    if build_fp:
        footer = (
            '<div class="hint" style="margin-top:14px;padding-top:12px;'
            'border-top:1px solid #eef1f5">构建指纹 <code>%s</code> · 生成于 %s'
            "<br>工作台是生成时的快照：改了正文、元信息或主题，必须重跑 "
            "<code>md2wx.py --sheet</code>，否则提交的是旧版本。</div>"
            % (build_fp, built_at or "—")
        )
        out = out.replace("<title>",
                          '<meta name="wx-build" content="%s">\n<title>' % build_fp, 1)
        out = out.replace("<script>", footer + "<script>", 1)
    return out


def _out_dir(args, out_path):
    if args.out_dir:
        return os.path.abspath(args.out_dir)
    if out_path:
        return os.path.dirname(os.path.abspath(out_path))
    return os.path.abspath(".")


def list_builds(out_dir):
    root = os.path.join(out_dir, ".builds")
    if os.path.islink(root):
        raise ValueError('快照目录不能是符号链接')
    if not os.path.isdir(root):
        print("还没有构建快照（生成时加 --snapshot）")
        return 0
    rows, failed = [], False
    for name in sorted(os.listdir(root)):
        if not re.fullmatch(r'[0-9a-f]{12,40}', name):
            continue
        snap = os.path.join(root, name)
        try:
            if os.path.islink(snap):
                raise ValueError('快照不能是符号链接')
            info = wxbuild.load_manifest(os.path.join(snap, 'build.json'))
            if not isinstance(info.get('source'), str):
                raise ValueError('清单源稿路径必须是字符串')
            rows.append((info.get('generated_at', '?'), name, info['source']))
        except (ValueError, OSError, TypeError) as exc:
            failed = True
            print('快照 %s 清单无效: %s' % (name, exc), file=sys.stderr)
    if rows:
        # 指纹放第一列：它是用户要复制的内容。
        print("%-14s %-26s %s" % ("指纹", "生成时间", "源稿"))
        for when, fp, src in rows:
            print("%-14s %-26s %s" % (fp, when, os.path.basename(src)))
    elif not failed:
        print("还没有构建快照")
    return 1 if failed else 0


def rollback_build(out_dir, fp):
    info, restored = wxbuild.rollback(out_dir, fp)
    print("✓ 已回退到 %s，恢复文件: %s" % (fp, ", ".join(restored)))
    print("  已恢复源稿: %s" % info['source'])
    print("  提示: 回退会恢复源稿和本地资产；交付前仍需双重体检与人工确认")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Markdown → 微信公众号内联样式 HTML",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("input", nargs="?", help="Markdown 文件路径（- 表示 stdin）")
    ap.add_argument("-o", "--out", help="输出 HTML 路径（默认同目录同名 .html）")
    ap.add_argument("-t", "--theme",
                    help="主题名（默认取 frontmatter 的 theme，否则 tech）")
    ap.add_argument("--title", help="页面标题（默认取 frontmatter title / 第一个 H1 / 文件名）")
    ap.add_argument("--author", help="覆盖署名（默认取 frontmatter author，否则默认署名）")
    ap.add_argument("--no-body", action="store_true", help="不输出 .body.html 片段")
    ap.add_argument("--sheet", action="store_true",
                    help="额外生成 sheet.html 发布工作台（元信息+正文一键复制）")
    ap.add_argument("--list-themes", action="store_true", help="列出所有可用主题")
    ap.add_argument("--check", action="store_true", help="只做统计，不写文件")
    ap.add_argument("--snapshot", action="store_true",
                    help="把本次产物快照到 out/.builds/<指纹>/，支持之后回退")
    ap.add_argument("--list-builds", action="store_true", help="列出历史构建快照")
    ap.add_argument("--rollback", metavar="指纹",
                    help="把指定指纹的快照恢复到输出目录")
    ap.add_argument("--out-dir", help="配合 --list-builds / --rollback 指定输出目录")
    args = ap.parse_args(argv)

    if args.list_builds or args.rollback:
        try:
            if args.list_builds:
                return list_builds(_out_dir(args, args.out))
            return rollback_build(_out_dir(args, args.out), args.rollback)
        except (ValueError, OSError, TypeError) as exc:
            raise SystemExit('构建操作失败: %s' % exc)
    if args.out_dir:
        ap.error('--out-dir 只用于 --list-builds / --rollback；渲染请使用 -o')

    if args.list_themes:
        if not os.path.isdir(THEME_DIR):
            print("没有 themes 目录")
            return 0
        for f in sorted(os.listdir(THEME_DIR)):
            if not f.endswith(".json"):
                continue
            try:
                t = load_theme(f[:-5])
                print("%-10s %s" % (f[:-5], t.get("label", "")))
            except Exception as e:  # noqa: BLE001
                print("%-10s <加载失败: %s>" % (f[:-5], e))
        return 0

    if not args.input:
        ap.print_help()
        return 2

    if args.input == "-":
        raw = sys.stdin.read()
        base = "stdin"
    else:
        if not os.path.isfile(args.input):
            raise SystemExit("找不到输入文件: %s" % args.input)
        with open(args.input, encoding="utf-8") as fh:
            raw = fh.read()
        base = os.path.splitext(os.path.basename(args.input))[0]

    meta, md = wxmeta.parse_frontmatter(raw)
    if args.author:
        meta = dict(meta)
        meta["author"] = args.author
    theme_name = args.theme or meta.get("theme") or "tech"
    theme = load_theme(theme_name)
    renderer = Renderer(theme)
    fragment, toc = parse(md, renderer)
    # 根 section 承载基础样式（字体/字号/行距/颜色），
    # 子元素靠继承生效——这是公众号排版的标准做法，
    # 也保证「复制正文片段」到编辑器后不会掉字体。
    fragment = tag("section", theme.get("styles", {}).get("body", {}), fragment)

    title = args.title or meta.get("title") or wxmeta.first_h1(md) or base

    stats = {
        "主题": "%s (%s)" % (theme.get("name", theme_name), theme.get("label", "")),
        "正文字数": count_words(md),
        "段落块": fragment.count("<section"),
        "图片": fragment.count("<img"),
        "标题层级": [(lvl, txt[:24]) for lvl, txt in toc],
    }
    if args.check:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0

    out_path = args.out or (base + '.html')
    out_dir = os.path.dirname(os.path.abspath(out_path))
    body_path = None if args.no_body else re.sub(r'\.html?$', '', out_path) + '.body.html'
    sheet_path = os.path.join(out_dir, 'sheet.html') if args.sheet else None
    outputs = {role: os.path.relpath(os.path.abspath(path), out_dir)
               for role, path in (('html', out_path), ('body', body_path), ('sheet', sheet_path)) if path}
    render = {'theme': theme_name, 'title': title,
              'author': wxmeta.resolve_author(meta), 'author_override': args.author is not None,
              'theme_override': args.theme is not None, 'title_override': args.title is not None,
              'source': os.path.abspath(args.input) if args.input != '-' else 'stdin',
              'html': outputs['html'], 'body': not args.no_body, 'sheet': args.sheet}
    try:
        if len(set(outputs.values())) != len(outputs):
            raise ValueError('输出路径相互覆盖，请不要将 -o 命名为 sheet.html')
        for name in outputs.values():
            wxbuild.safe_path(out_dir, name)
        if os.path.islink(os.path.join(out_dir, 'build.json')):
            raise ValueError('构建清单不能是符号链接')
        build_fp, assets = wxbuild.context(raw, theme, render, out_dir, fragment)
        if set(outputs.values()) & set(assets):
            raise ValueError('输出路径与本地图片冲突')
        wxbuild.preflight(out_dir, outputs, assets, render['source'], args.snapshot, build_fp)
    except (ValueError, OSError) as exc:
        raise SystemExit('构建失败: %s' % exc)
    built_at = datetime.now().astimezone().isoformat(timespec='seconds')
    doc = build_document(fragment, title, theme, build_fp)
    contents = {outputs['html']: doc.encode('utf-8')}
    if body_path:
        contents[outputs['body']] = fragment.encode('utf-8')
    if sheet_path:
        contents[outputs['sheet']] = build_sheet(meta, theme, fragment, title, out_dir,
                                                stats['正文字数'], stats['图片'],
                                                build_fp=build_fp, built_at=built_at).encode('utf-8')
    try:
        manifest = wxbuild.make_manifest(raw, theme, render, out_dir, outputs,
                                         built_at, stats['正文字数'], fragment, contents)
        if manifest['fingerprint'] != build_fp:
            raise ValueError('生成期间输入/资产发生变化，请重新运行')
        wxbuild.commit_build(out_dir, manifest, contents)
        if args.snapshot:
            snap = wxbuild.save_snapshot(out_dir, manifest, raw)
            print('✓ 完整构建快照: %s' % snap)
    except (ValueError, OSError, TypeError) as exc:
        raise SystemExit('构建清单/快照失败: %s' % exc)
    print('✓ 完整页面: %s' % out_path)
    if body_path:
        print('✓ 正文片段: %s' % body_path)
    if sheet_path:
        print('✓ 发布工作台: %s' % sheet_path)

    print("  主题 %s / 字数 %s / 图片 %s"
          % (stats["主题"], stats["正文字数"], stats["图片"]))
    print("  构建指纹: %s" % build_fp)
    if stats["标题层级"]:
        print("  大纲: " + " / ".join("%s%s" % ("#" * l, t) for l, t in toc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
