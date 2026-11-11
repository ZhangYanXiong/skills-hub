#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest.py — 把原始素材转成「可提炼」的结构化文本

为什么需要它:
    写公众号的常见起点是「用户丢来一个 PDF / 一份周报 / 一个网页，说改成文章」。
    直接让模型读原文，会跳读、漏结论、把数字写错。本脚本先把素材拆成三层：
        1. clean.txt    清洗后的正文（去页眉页脚、导航、重复空行）
        2. outline.md   结构骨架 + 统计 + 长文分块建议
        3. facts.md     候选可引用句（含数字/时间/比例的句子，带行号便于回查）
    提炼时以 facts.md 为准回查原文，能显著降低「数字被改错」的概率。

支持格式:
    .md .markdown .txt        纯文本
    .html .htm                网页正文（去脚本/样式/导航）
    .docx                     Word（段落 + 表格）
    .pptx                     幻灯片（标题 + 正文 + 备注）
    .pdf                      PDF（需要 pypdf；已 vendored 到 scripts/vendor）

依赖:
    docx → python-docx；pptx → python-pptx；pdf → pypdf；html → lxml
    缺哪个就只影响那个格式，其余照常。

用法:
    python3 scripts/ingest.py 素材.pdf
    python3 scripts/ingest.py a.docx b.pptx -o out/ingest
    python3 scripts/ingest.py 页面.html --json
"""

import argparse
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(HERE, "vendor")
if os.path.isdir(VENDOR) and VENDOR not in sys.path:
    sys.path.insert(0, VENDOR)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import wxmeta  # noqa: E402  同目录共享工具

# 长文分块阈值（约 6000 字）
CHUNK_THRESHOLD = 6000
CHUNK_SIZE = 3000

SUPPORTED = (".md", ".markdown", ".txt", ".html", ".htm",
             ".docx", ".pptx", ".pdf")

# 数据句：数字 + 单位/百分号
NUM_UNIT_RE = re.compile(
    r"\d[\d,.]*\s*(?:%|％|万|亿|千|百|ms|毫秒|s|秒|分钟|小时|天|周|个月|月|年|"
    r"元|美元|倍|次|个|人|家|台|条|张|GB|MB|KB|TB|QPS|TPS|人天)"
)
# 指标词：紧贴在数字前面的中文（2~6 字）
# 指标词：必须以指标性后缀结尾，避免把「从」「提升到」当成指标名
METRIC_RE = re.compile(
    r"([\u4e00-\u9fff]{1,8}(?:率|量|数|耗时|时长|成本|价格|占比|次数|天数|金额|规模|时间))"
    r"[^，。；\n]{0,8}?(\d[\d,.]*)\s*(%|％|万|亿|ms|毫秒|s|秒|分钟|小时|天|元|倍|次|个)"
)

TIME_RE = re.compile(r"(?:19|20)\d{2}\s*年|Q[1-4]|\d{1,2}\s*月")
SOURCE_HINT_RE = re.compile(r"据|来源|出自|报告|统计显示|调研|官方")


# ---------------------------------------------------------------- 格式提取

def _norm(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _join(parts) -> str:
    return _norm("\n\n".join(p.strip() for p in parts if p and p.strip()))


def extract_md_txt(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    headings = []
    for line in raw.splitlines():
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if m:
            headings.append((len(m.group(1)), m.group(2)))
    return {"text": _norm(raw), "headings": headings, "meta": {}}


def extract_html(path):
    try:
        from lxml import html as LH
    except ImportError:
        raise SystemExit("解析 HTML 需要 lxml：pip install lxml")
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    tree = LH.fromstring(raw)
    for bad in tree.xpath("//script|//style|//noscript|//nav|//footer|//header|//aside"):
        try:
            bad.getparent().remove(bad)
        except Exception:
            pass

    parts, headings = [], []
    body = tree.find(".//body")
    root = body if body is not None else tree
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        if re.fullmatch(r"h[1-6]", el.tag):
            txt = " ".join(el.text_content().split())
            if txt:
                headings.append((int(el.tag[1]), txt))
                parts.append(txt)
        elif el.tag in ("p", "li", "blockquote", "pre", "td", "th"):
            txt = " ".join(el.text_content().split())
            if txt:
                parts.append(txt)
    title = tree.xpath("//title/text()")
    return {"text": _join(parts), "headings": headings,
            "meta": {"页面标题": (title[0].strip() if title else "")}}


def extract_docx(path):
    try:
        import docx
    except ImportError:
        raise SystemExit("解析 docx 需要 python-docx：pip install python-docx")
    doc = docx.Document(path)
    parts, headings = [], []
    for p in doc.paragraphs:
        txt = p.text.strip()
        if not txt:
            continue
        style = (p.style.name or "") if p.style else ""
        m = re.match(r"Heading\s*(\d+)", style, re.I)
        if m:
            lvl = int(m.group(1))
            headings.append((lvl, txt))
            parts.append(txt)
        elif style.lower().startswith("title"):
            headings.append((1, txt))
            parts.append(txt)
        else:
            parts.append(txt)

    tables = 0
    for t in doc.tables:
        tables += 1
        rows = []
        for row in t.rows:
            cells = [c.text.strip().replace("\n", " ") for c in row.cells]
            if any(cells):
                rows.append(" | ".join(cells))
        if rows:
            parts.append("【表格 %d】\n" % tables + "\n".join(rows))

    return {"text": _join(parts), "headings": headings,
            "meta": {"表格数": tables, "原始段落数": len(doc.paragraphs)}}


def extract_pptx(path):
    try:
        import pptx
    except ImportError:
        raise SystemExit("解析 pptx 需要 python-pptx：pip install python-pptx")
    prs = pptx.Presentation(path)
    parts, headings = [], []
    for i, slide in enumerate(prs.slides, 1):
        title = ""
        try:
            if slide.shapes.title is not None:
                title = slide.shapes.title.text.strip()
        except Exception:
            title = ""
        if title:
            headings.append((2, title))
            parts.append(title)

        bucket = []
        for shape in slide.shapes:
            if not getattr(shape, "has_text_frame", False):
                continue
            txt = shape.text_frame.text.strip()
            if not txt or txt == title:
                continue
            bucket.append(txt)
        if bucket:
            parts.append("\n".join(bucket))

        if slide.has_notes_slide:
            note = slide.notes_slide.notes_text_frame.text.strip()
            if note:
                parts.append("【备注】" + note)

    return {"text": _join(parts), "headings": headings,
            "meta": {"幻灯片数": len(prs.slides)}}


def extract_pdf(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise SystemExit(
            "解析 PDF 需要 pypdf。请执行：\n"
            "  python3 -m pip install pypdf --target scripts/vendor\n"
            "或用「先导出成 docx / md」的降级路径。"
        )
    reader = PdfReader(path)
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    text, headings = _rebuild_pdf_text(pages)
    return {"text": text, "headings": headings, "meta": {"页数": len(reader.pages)}}


def _looks_like_heading(line: str) -> bool:
    return 2 <= len(line) <= 24 and not re.search(r"[。！？：；，,.;:…]$", line)


def _rebuild_pdf_text(pages):
    """PDF 抽出来是「视觉行」，需要重建成段落：先去页码，再合硬折行，最后按短行切段。"""
    lines = []
    for raw in pages:
        for ln in raw.splitlines():
            ln = ln.strip()
            if re.fullmatch(r"[-–—\s]*\d{1,4}[-–—\s]*", ln):  # 纯页码
                continue
            lines.append(ln)

    merged = []
    for ln in lines:
        if not ln:
            merged.append("")
            continue
        prev = merged[-1] if merged else ""
        if (prev and len(prev) > 12
                and not re.search(r"[。！？：；.!?:;]$", prev)
                and not _looks_like_heading(ln)
                and not re.match(r"^[•·\-*]|^\d+[.、]", ln)):
            merged[-1] = prev + ln
        else:
            merged.append(ln)

    blocks, cur = [], []
    for ln in merged:
        if not ln:
            if cur:
                blocks.append("".join(cur))
                cur = []
            continue
        if _looks_like_heading(ln):
            if cur:
                blocks.append("".join(cur))
                cur = []
            blocks.append(ln)
        else:
            cur.append(ln)
    if cur:
        blocks.append("".join(cur))

    headings = [(2, b) for b in blocks if _looks_like_heading(b)][:40]
    return "\n\n".join(blocks), headings


EXTRACTORS = {
    ".md": extract_md_txt, ".markdown": extract_md_txt, ".txt": extract_md_txt,
    ".html": extract_html, ".htm": extract_html,
    ".docx": extract_docx, ".pptx": extract_pptx, ".pdf": extract_pdf,
}


# ---------------------------------------------------------------- 事实抽取

def split_sentences(text: str):
    """按中英文句末标点切句，同时记录行号。"""
    out = []
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        # 中文句末 + 英文句末（不在数字后面切，避免切坏小数）
        chunks = re.split(r"(?<=[。！？；])|(?<=[.!?])(?=\s|[A-Z\u4e00-\u9fff])", line)
        for c in chunks:
            c = c.strip()
            if len(c) >= 6:
                out.append((lineno, c))
    return out


def extract_facts(text: str, limit=None):
    """挑出候选可引用句；默认保留全部，显式 limit 才限制数量。"""
    facts, seen = [], set()
    for lineno, sent in split_sentences(text):
        score, kinds = 0, []
        if NUM_UNIT_RE.search(sent):
            score += 3
            kinds.append("数据")
        if TIME_RE.search(sent):
            score += 1
            kinds.append("时间")
        if SOURCE_HINT_RE.search(sent):
            score += 2
            kinds.append("出处")
        if score < 2:
            continue
        # 只有完整句子相同才去重；句首相同或空格不同可能代表不同数据与实体。
        if sent in seen:
            continue
        seen.add(sent)
        facts.append({"line": lineno, "kind": "+".join(kinds),
                      "score": score, "text": sent})
    facts.sort(key=lambda f: (-f["score"], f["line"]))
    return facts[:limit]


def detect_metric_values(facts):
    """同一指标出现多个数值 → 列出来让人确认口径，不自动判「冲突」。"""
    groups = {}
    for f in facts:
        for m in METRIC_RE.finditer(f["text"]):
            metric = m.group(1)
            unit = m.group(3)
            val = m.group(2).replace(",", "")
            key = (metric, unit)
            groups.setdefault(key, {}).setdefault(val, set()).add(f["line"])
    suspicious = []
    for (metric, unit), vals in groups.items():
        if len(vals) > 1:
            suspicious.append({
                "指标": metric,
                "单位": unit,
                "取值": sorted(vals.items(), key=lambda kv: kv[1]),
            })
    suspicious.sort(key=lambda x: x["指标"])
    return suspicious


def collect_values(facts):
    """把所有「数值+单位」条目摊平，供人工比对跨句/跨源口径。"""
    rows, seen = [], set()
    for f in facts:
        for m in NUM_UNIT_RE.finditer(f["text"]):
            start = m.start()
            ctx = f["text"][max(0, start - 12):m.end()].strip()
            key = (f["line"], m.group(0).strip())
            if key in seen:
                continue
            seen.add(key)
            rows.append({"line": f["line"], "raw": m.group(0).strip(), "ctx": ctx})
    return rows


# ---------------------------------------------------------------- 产出

def build_outline(ext, name, src_path):
    text = ext["text"]
    words = wxmeta.count_words(text)
    paras = [p for p in text.split("\n\n") if p.strip()]

    lines = ["# 素材结构：%s" % name, ""]
    lines.append("| 项目 | 值 |")
    lines.append("| --- | --- |")
    lines.append("| 源文件 | `%s` |" % src_path)
    for k, v in (ext.get("meta") or {}).items():
        lines.append("| %s | %s |" % (k, v))
    lines.append("| 正文字数 | %d |" % words)
    lines.append("| 段落数 | %d |" % len(paras))
    lines.append("| 句末分句数 | %d |" % len(split_sentences(text)))
    lines.append("")

    headings = ext.get("headings") or []
    if headings:
        lines.append("## 标题层级")
        lines.append("")
        for lvl, txt in headings[:60]:
            lines.append("%s %s" % ("#" * min(lvl + 1, 6), txt))
        if len(headings) > 60:
            lines.append("\n> 标题过多，仅显示前 60 个。")
    else:
        lines.append("## 标题层级")
        lines.append("")
        lines.append("未检测到标题层级（PDF/纯文本常见）。提炼时请按段落主题自行归组，")
        lines.append("并用 facts.md 的行号回查原文。")
    lines.append("")

    if words > CHUNK_THRESHOLD:
        lines.append("## 分块建议")
        lines.append("")
        lines.append("正文 %d 字，超过单次处理阈值（%d 字），建议按下列分块逐块提炼后再合并："
                     % (words, CHUNK_THRESHOLD))
        lines.append("")
        acc, idx, start = 0, 1, 1
        for i, p in enumerate(paras, 1):
            acc += wxmeta.count_words(p)
            if acc >= CHUNK_SIZE:
                lines.append("- 第 %d 块：段落 %d ~ %d（约 %d 字）" % (idx, start, i, acc))
                idx += 1
                start, acc = i + 1, 0
        if acc > 0:
            lines.append("- 第 %d 块：段落 %d ~ %d（约 %d 字）" % (idx, start, len(paras), acc))
        lines.append("")

    lines.append("## 前 600 字预览")
    lines.append("")
    preview = text[:600].replace("\n\n", "\n")
    lines.append("```text")
    lines.append(preview)
    lines.append("```")
    return "\n".join(lines)


def build_facts(facts, conflicts, name):
    lines = ["# 候选可引用句：%s" % name, ""]
    lines.append("> 这些是含数字、时间或出处提示的句子，**提炼时必须逐条回原文核对**，")
    lines.append("> 不许改写单位、口径、时间范围。行号对应 `%s.clean.txt`。" % name)
    lines.append("")

    if conflicts:
        lines.append("## ⚠ 同一指标出现多个数值（需确认口径）")
        lines.append("")
        lines.append("这**不代表数据有错**——可能是不同时间点、不同渠道、或统计口径不同。")
        lines.append("动笔前必须确认属于哪一种，**不要自行择一取用**：")
        lines.append("")
        for c in conflicts:
            parts = ["%s（L%s）" % (v, "、".join(str(x) for x in sorted(lns)))
                     for v, lns in c["取值"]]
            lines.append("- **%s**（单位 %s）：%s" % (c["指标"], c["单位"], " · ".join(parts)))
        lines.append("")

    if not facts:
        lines.append("未找到含数字的句子。可能这份素材本身以观点为主，")
        lines.append("写稿时需补充可验证的数据，或改用观点论证型结构。")
        return "\n".join(lines)

    values = collect_values(facts)
    if values:
        lines.append("## 数值清单（跨句/跨源口径需人工比对）")
        lines.append("")
        lines.append("自动检测只能覆盖「指标词与数值同句相邻」的情况；")
        lines.append("**同一指标在别处出现不同数值时，本表不会自动关联**，请逐行比对：")
        lines.append("")
        lines.append("| 数值 | 行 | 上下文 |")
        lines.append("| --- | --- | --- |")
        for v in values[:60]:
            lines.append("| `%s` | %d | %s |"
                         % (v["raw"], v["line"], v["ctx"].replace("|", "\\|")))
        if len(values) > 60:
            lines.append("")
            lines.append("> 数值过多，仅显示前 60 条。")
        lines.append("")

    by_kind = {}
    for f in facts:
        by_kind.setdefault(f["kind"], []).append(f)

    # 按条目数从多到少分组展示，组合类型（如「数据+时间+出处」）也能有位置
    for kind in sorted(by_kind, key=lambda k: (-len(by_kind[k]), k)):
        items = by_kind[kind]
        lines.append("## %s（%d 条）" % (kind, len(items)))
        lines.append("")
        lines.append("| 行 | 句子 |")
        lines.append("| --- | --- |")
        for f in items:
            lines.append("| %d | %s |" % (f["line"], f["text"].replace("|", "\\|")))
        lines.append("")

    return "\n".join(lines)


def ingest_one(path, out_dir, name=None, quiet=False):
    ext = os.path.splitext(path)[1].lower()
    if ext not in EXTRACTORS:
        raise SystemExit("不支持的格式 %r。支持：%s" % (ext, " ".join(SUPPORTED)))
    if not os.path.isfile(path):
        raise SystemExit("找不到文件: %s" % path)

    name = name or os.path.splitext(os.path.basename(path))[0]
    ext_data = EXTRACTORS[ext](path)
    text = ext_data["text"]
    if not text.strip():
        raise SystemExit(
            "%s 提取不出文本。若是扫描版 PDF（图片），需要先 OCR，本脚本不处理。"
            % os.path.basename(path)
        )

    os.makedirs(out_dir, exist_ok=True)
    clean_path = os.path.join(out_dir, name + ".clean.txt")
    outline_path = os.path.join(out_dir, name + ".outline.md")
    facts_path = os.path.join(out_dir, name + ".facts.md")

    with open(clean_path, "w", encoding="utf-8") as fh:
        fh.write(text)

    facts = extract_facts(text)
    conflicts = detect_metric_values(facts)

    with open(outline_path, "w", encoding="utf-8") as fh:
        fh.write(build_outline(ext_data, name, path))
    with open(facts_path, "w", encoding="utf-8") as fh:
        fh.write(build_facts(facts, conflicts, name))

    info = {
        "文件": path,
        "格式": ext,
        "字数": wxmeta.count_words(text),
        "段落": len([p for p in text.split("\n\n") if p.strip()]),
        "标题数": len(ext_data.get("headings") or []),
        "候选可引用句": len(facts),
        "疑似口径冲突": len(conflicts),
        "数值条目": len(collect_values(facts)),
        "产出": [clean_path, outline_path, facts_path],
    }
    if not quiet:
        print("✓ %s" % os.path.basename(path))
        print("  字数 %d · 段落 %d · 标题 %d · 可引用句 %d · 同句多值 %d"
              % (info["字数"], info["段落"], info["标题数"],
                 info["候选可引用句"], info["疑似口径冲突"]))
        for c in conflicts[:3]:
            print("  ⚠ %s（%s）%s"
                  % (c["指标"], c["单位"], " / ".join(v for v, _ in c["取值"])))
        print("  → %s" % outline_path)
        print("  → %s" % facts_path)
    return info


def output_name_key(name):
    """规范等价与大小写不同的名字，在部分文件系统中是同一个输出目标。"""
    return unicodedata.normalize("NFC", name).casefold()


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="把 PDF/docx/pptx/网页/Markdown 转成可提炼的结构化素材",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("inputs", nargs="+", help="素材文件（可多个）")
    ap.add_argument("-o", "--out", default="ingest", help="输出目录，默认 ingest/")
    ap.add_argument("--json", action="store_true", help="输出 JSON 汇总")
    args = ap.parse_args(argv)

    bases = [os.path.splitext(os.path.basename(p))[0] for p in args.inputs]
    keys = [output_name_key(b) for b in bases]
    tally = {key: keys.count(key) for key in keys}
    # 先保留自然唯一的文件名，后缀分配不能覆盖另一份输入的原名。
    used = {key for key in keys if tally[key] == 1}
    names = []
    for path, b in zip(args.inputs, bases):
        if tally[output_name_key(b)] == 1:
            name = b
        else:
            candidate = b + "_" + os.path.splitext(path)[1].lstrip(".").lower()
            name, suffix = candidate, 2
            while output_name_key(name) in used:
                name = "%s_%d" % (candidate, suffix)
                suffix += 1
            used.add(output_name_key(name))
        names.append(name)

    results = []
    for path, name in zip(args.inputs, names):
        results.append(ingest_one(path, args.out, name=name, quiet=args.json))

    if len(results) > 1:
        index_path = os.path.join(args.out, "index.md")
        lines = ["# 素材清单", "", "| 源文件 | 格式 | 字数 | 可引用句 | 冲突 |",
                 "| --- | --- | --- | --- | --- |"]
        for r in results:
            lines.append("| %s | %s | %d | %d | %d |"
                         % (r["文件"].replace("|", "\\|"), r["格式"], r["字数"],
                            r["候选可引用句"], r["疑似口径冲突"]))
        lines.append("")
        lines.append("> 多源素材先看这里：同一指标在不同来源里数值不一致时，")
        lines.append("> 按 `ingest.md` 的冲突处理规则标注并向用户确认，不要择一取用。")
        with open(index_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        if not args.json:
            print("\n✓ 素材清单: %s" % index_path)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
