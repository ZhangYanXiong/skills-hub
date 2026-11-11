#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check.py — 公众号发布前体检

检查四类问题:
    1. 合规风险：广告法极限词、虚假承诺、诱导关注/分享、敏感行业表述
    2. 平台硬约束：标题长度、摘要长度、外链不可点、图片域名
    3. 排版质量：段落过长、正文配图缺失
    4. HTML 安全（--html）：非内联样式、class、外链图片

重要：这是「发布提示」，不是「过审保证」。命中不等于违规，需结合语境人工判断。

依赖: 仅标准库。

用法:
    python3 check.py article.md --title "标题" --summary "摘要"
    python3 check.py article.md --html article.html --json
    python3 check.py article.md --strict      # 有高风险时退出码 1
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(HERE, "rules", "compliance.json")

if HERE not in sys.path:
    sys.path.insert(0, HERE)
import wxmeta  # noqa: E402  同目录共享工具

SEV_ORDER = {"high": 0, "medium": 1, "low": 2}
SEV_LABEL = {"high": "高风险", "medium": "中风险", "low": "提示"}
SEV_ICON = {"high": "✗", "medium": "!", "low": "·"}

REGEX_HINT = re.compile(r"[.*+?\[\](){}|\\^$]")


# ---------------------------------------------------------------- 工具

def load_rules():
    with open(RULES_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def count_chars(text: str) -> int:
    """中文按字计，英文按词计。"""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z0-9_][A-Za-z0-9_\-']*", text))
    return cjk + latin


def mask_code(md: str) -> str:
    """把代码块和行内代码替换成等长空白，行号保持不变，避免误报。"""
    return wxmeta.mask_code(md)


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def find_hits(masked: str, original: str, category: dict, exclude: list):
    """返回 [(line, matched, context)]。"""
    hits = []
    terms = list(category.get("terms", []))
    # 排除词先掩码，避免「最后」被「最」类规则误伤
    scan = masked
    for ex in exclude:
        scan = scan.replace(ex, " " * len(ex))

    def record(m):
        start = m.start()
        matched = m.group(0)
        if not matched.strip():
            return
        line = line_of(scan, start)
        src_line = original.split("\n")[line - 1] if line - 1 < len(original.split("\n")) else ""
        ctx = src_line.strip()
        if len(ctx) > 90:
            # 截取命中位置附近的上下文
            col = start - (scan.rfind("\n", 0, start) + 1)
            lo = max(0, col - 30)
            hi = min(len(src_line), col + len(matched) + 30)
            ctx = ("…" if lo > 0 else "") + src_line[lo:hi].strip() + ("…" if hi < len(src_line) else "")
        hits.append((line, matched, ctx))

    for term in terms:
        if REGEX_HINT.search(term):
            try:
                for m in re.finditer(term, scan):
                    record(m)
            except re.error:
                continue
        else:
            idx = 0
            while True:
                idx = scan.find(term, idx)
                if idx < 0:
                    break
                line = line_of(scan, idx)
                src_lines = original.split("\n")
                src_line = src_lines[line - 1] if line - 1 < len(src_lines) else ""
                ctx = src_line.strip()
                if len(ctx) > 90:
                    col = idx - (scan.rfind("\n", 0, idx) + 1)
                    lo = max(0, col - 30)
                    hi = min(len(src_line), col + len(term) + 30)
                    ctx = ("…" if lo > 0 else "") + src_line[lo:hi].strip() + ("…" if hi < len(src_line) else "")
                hits.append((line, term, ctx))
                idx += max(len(term), 1)

    for pat in category.get("patterns", []):
        try:
            for m in re.finditer(pat, scan):
                record(m)
        except re.error:
            continue
    return hits


def check_links(masked: str, original: str, rules: dict):
    """外链、图片域名、本地图片。"""
    allow = set(rules.get("link_allow_hosts", []))
    allow_img = set(rules.get("image_allow_hosts", []))
    findings = []

    for m in re.finditer(r"(?<!!)\[[^\]]*\]\((https?://[^)\s]+)", masked):
        url = m.group(1)
        host = re.sub(r"^https?://", "", url).split("/")[0].split(":")[0].lower()
        if host not in allow:
            findings.append({
                "severity": "medium",
                "category": "外链",
                "line": line_of(masked, m.start()),
                "matched": url,
                "message": "非微信域名的链接在正文里不可点击，读者点不动",
                "suggest": "改为文字说明 + 放「阅读原文」，或去掉链接只留文字",
            })

    # 裸 URL（没写成 markdown 链接的，同样不可点）
    covered = []
    for pat in (r"\[[^\]]*\]\((https?://[^)\s]+)\)", r"!\[[^\]]*\]\((https?://[^)\s]+)\)"):
        for m in re.finditer(pat, masked):
            covered.append((m.start(1), m.end(1)))
    for m in re.finditer(r"https?://[^\s<>\"'）)\]，。；、]+", masked):
        if any(a <= m.start() < b for a, b in covered):
            continue
        url = m.group(0).rstrip(".,;:!?")
        host = re.sub(r"^https?://", "", url).split("/")[0].split(":")[0].lower()
        if host in allow:
            continue
        findings.append({
            "severity": "medium",
            "category": "外链",
            "line": line_of(masked, m.start()),
            "matched": url,
            "message": "裸 URL 在公众号正文里不可点击，只会显示成一串字符",
            "suggest": "改成文字描述，或引导读者去「阅读原文」",
        })

    for m in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)", masked):
        src = m.group(1)
        line = line_of(masked, m.start())
        if src.startswith(("http://", "https://")):
            host = re.sub(r"^https?://", "", src).split("/")[0].lower()
            if host not in allow_img:
                findings.append({
                    "severity": "medium",
                    "category": "图片外链",
                    "line": line,
                    "matched": src,
                    "message": "外域图片在公众号正文会被防盗链拦截，显示为空白",
                    "suggest": "上传到微信素材库换成 mmbiz.qpic.cn 域名，或用 scripts/upload.py（L3）",
                })
        else:
            findings.append({
                "severity": "low",
                "category": "本地图片",
                "line": line,
                "matched": src,
                "message": "本地图片需先上传到微信素材库才能正常显示",
                "suggest": "粘贴不会带走本地图片：用工作台「正文图片」清单逐张复制上传"
                           "（只有 L3 素材接口能自动替换）",
            })

    return findings


def check_structure(md: str, rules: dict):
    """段落长度、配图数量。"""
    limits = rules.get("limits", {})
    max_para = limits.get("paragraph_max_chars", 260)
    findings = []

    masked = mask_code(md)
    paras = [p for p in re.split(r"\n\s*\n", masked) if p.strip()]
    for p in paras:
        if p.lstrip().startswith(("#", ">", "|", "-", "*", "!", "```")):
            continue
        n = count_chars(p)
        if n > max_para:
            line = line_of(masked, masked.find(p[:20])) if p[:20] in masked else 0
            findings.append({
                "severity": "low",
                "category": "长段落",
                "line": line,
                "matched": "%d 字" % n,
                "message": "手机端阅读单段过长，读者容易划走",
                "suggest": "拆成 2~3 段，每段控制在 3~5 行",
            })

    n_img = len(re.findall(r"!\[[^\]]*\]\(", masked))
    n_char = count_chars(masked)
    if n_img == 0 and n_char > 1200:
        findings.append({
            "severity": "low",
            "category": "配图",
            "line": 0,
            "matched": "0 张",
            "message": "长文没有配图，手机阅读容易疲劳",
            "suggest": "每 600~800 字插一张图，或加分割线/引用块换气",
        })
    return findings


def check_html(path: str):
    """校验生成的 HTML 是否满足公众号约束（只查正文片段，忽略预览页外壳）。"""
    with open(path, encoding="utf-8") as fh:
        doc = fh.read()
    findings = []

    # 预览页的 <style> 和 .wx-page 外壳不属于会被粘贴的内容，
    # 提取内层再检查，避免误报。
    m = re.search(r'<div class="wx-page"[^>]*>(.*)</div>', doc, re.S)
    target = m.group(1) if m else doc
    is_full_doc = bool(m)

    checks = [
        (r"<style[\s>]", "high", "存在 <style> 标签", "微信会整段丢弃，样式必须内联到标签上"),
        (r"<script[\s>]", "high", "存在 <script> 标签", "微信不支持脚本，会被剥离"),
        (r"\sclass\s*=", "high", "存在 class 属性", "微信会丢弃 class，依赖 class 的样式不生效"),
        (r'<img[^>]+src="https?://(?!mmbiz\.qpic\.cn|mmbiz\.qlogo\.cn|res\.wx\.qq\.com)', "medium",
         "图片使用非微信域名", "正文外域图片会被防盗链拦截"),
        (r"<div[\s>]", "low", "存在 <div> 标签", "建议统一用 <section>，微信对 div 的处理不如 section 稳定"),
    ]
    for pattern, sev, msg, suggest in checks:
        mm = re.search(pattern, target)
        if mm:
            findings.append({
                "severity": sev,
                "category": "HTML 兼容",
                "line": 0,
                "matched": mm.group(0)[:40].strip(),
                "message": msg,
                "suggest": suggest,
            })
    return findings


# ---------------------------------------------------------------- 报告

def check_metadata(meta, limits):
    """必填与长度校验进入 findings，不能只在报告里显示一个指标。"""
    findings = []
    unsupported = set()
    for field in wxmeta.KNOWN_KEYS:
        value = meta.get(field, "") or ""
        # 拒绝块标记的注释、缩进与保留换行变体，也检查可选字段。
        if re.fullmatch(r"[|>](?:[+-][1-9]?|[1-9][+-]?)?(?:[ \t]+#.*)?", value.strip()):
            unsupported.add(field)
            findings.append({
                "severity": "high", "category": "元信息", "field": field,
                "line": 0, "matched": value,
                "message": "%s使用了不支持的 YAML 多行标记" % field,
                "suggest": "本工具仅支持 key: value 单行字段，请写成一行实际文本",
            })
    required = (
        ("title", "标题", limits.get("title_max_chars", 64)),
        ("title_short", "短标题", limits.get("title_feed_display", 20)),
        ("summary", "摘要", limits.get("summary_max_chars", 120)),
    )
    for field, label, maximum in required:
        if field in unsupported:
            continue
        value = meta.get(field, "") or ""
        if not value.strip():
            message = "%s缺失或为空" % label
            suggest = "在 frontmatter 中补充 %s" % field
        elif len(value) > maximum:
            message = "%s有 %d 字，超过上限 %d 字" % (label, len(value), maximum)
            suggest = "缩短 %s，保留事实、口径与必要限定条件" % field
        else:
            continue
        findings.append({
            "severity": "high", "category": "元信息", "field": field,
            "line": 0, "matched": value or "（未提供）",
            "message": message, "suggest": suggest,
        })
    return findings


def build_report(md, title, summary, rules, html_path=None, meta=None):
    masked = mask_code(md)
    metadata = dict(meta or {})
    # CLI 覆盖值才是最终要发布的标题与摘要，不能仍检查旧 frontmatter。
    metadata.update(title=title, summary=summary)
    limits = rules.get("limits", {})
    findings = check_metadata(metadata, limits)

    # 元信息不是代码，反引号不能让标题、摘要或封面文案绕过扫描。
    sources = [("body", masked, md)]
    for field in ("title", "title_short", "summary", "cover_title", "author", "tag"):
        value = metadata.get(field, "") or ""
        if value:
            sources.append((field, value, value))
    for field, scan, original in sources:
        for cat in rules.get("categories", []):
            for line, matched, ctx in find_hits(scan, original, cat, rules.get("exclude_from_scan", [])):
                findings.append({
                    "severity": cat.get("severity", "medium"),
                    "category": cat.get("label", cat.get("id", "")),
                    "field": field,
                    "line": line if field == "body" else 0,
                    "matched": matched,
                    "message": ctx,
                    "suggest": cat.get("suggest", ""),
                })

    # 2) 链接与图片
    findings += check_links(masked, md, rules)

    # 3) 结构
    findings += check_structure(md, rules)

    # 4) HTML
    if html_path:
        if os.path.isfile(html_path):
            for finding in check_html(html_path):
                finding["field"] = "html"
                findings.append(finding)
        else:
            findings.append({
                "severity": "high", "category": "HTML 兼容", "field": "html", "line": 0,
                "matched": str(html_path), "message": "HTML 文件不存在", "suggest": "先跑 md2wx.py",
            })

    # 同一风险词在不同字段必须分别报告，避免漏掉摘要或封面文案。
    seen, uniq = set(), []
    for f in findings:
        f.setdefault("field", "body")
        key = (f["severity"], f["category"], f["field"], f["matched"], f["line"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(f)

    uniq.sort(key=lambda f: (SEV_ORDER.get(f["severity"], 9), f["line"]))

    n_char = count_chars(md)  # 与 md2wx.py 口径一致：含代码块
    n_img = len(re.findall(r"!\[[^\]]*\]\(", masked))
    minutes = max(1, round(n_char / max(limits.get("reading_chars_per_minute", 400), 1)))

    return {
        "指标": {
            "标题": title or "（未提供）",
            "标题字数": len(title) if title else 0,
            "标题上限": limits.get("title_max_chars", 64),
            "短标题": metadata.get("title_short") or "（未提供）",
            "短标题字数": len(metadata.get("title_short") or ""),
            "短标题上限": limits.get("title_feed_display", 20),
            "摘要": summary or "（未提供）",
            "摘要字数": len(summary) if summary else 0,
            "摘要上限": limits.get("summary_max_chars", 120),
            "正文字数": n_char,
            "预计阅读": "%d 分钟" % minutes,
            "配图数量": n_img,
        },
        "findings": uniq,
        "counts": {
            "high": sum(1 for f in uniq if f["severity"] == "high"),
            "medium": sum(1 for f in uniq if f["severity"] == "medium"),
            "low": sum(1 for f in uniq if f["severity"] == "low"),
        },
    }


def print_report(report):
    m = report["指标"]
    limits = {"title_max_chars": m["标题上限"], "summary_max_chars": m["摘要上限"]}

    print("公众号发布体检")
    print("=" * 52)
    print("标题      %s" % m["标题"])
    flag = "✗ 缺失" if not m["标题字数"] else ("✓" if m["标题字数"] <= limits["title_max_chars"] else "✗ 超长")
    extra = ""
    if m["标题字数"] > 20:
        extra = "（请人工检查实际发布标题的关键开头信息）"
    print("           %d / %d 字 %s%s" % (m["标题字数"], limits["title_max_chars"], flag, extra))
    for label, size, maximum in (
        ("短标题", m["短标题字数"], m["短标题上限"]),
        ("摘要", m["摘要字数"], limits["summary_max_chars"]),
    ):
        flag = "✗ 缺失" if not size else ("✓" if size <= maximum else "✗ 超长")
        print("%-8s  %d / %d 字 %s" % (label, size, maximum, flag))
    print("正文      %s 字 · 预计阅读 %s · 配图 %s 张"
          % (m["正文字数"], m["预计阅读"], m["配图数量"]))
    print()

    if not report["findings"]:
        print("未发现需要提示的问题。")
        return

    cur = None
    for f in report["findings"]:
        if f["severity"] != cur:
            cur = f["severity"]
            print("【%s】" % SEV_LABEL.get(cur, cur))
        field = f.get("field", "body")
        loc = ("L%-4d" % f["line"]) if field == "body" and f["line"] else field
        print("  %s %s %s" % (loc, SEV_ICON.get(f["severity"], "·"), f["category"]))
        print("       命中: %s" % (f["matched"][:80] if f["matched"] else "—"))
        if f["message"] and f["message"] != f["matched"]:
            print("       位置: %s" % f["message"][:100])
        if f["suggest"]:
            print("       建议: %s" % f["suggest"][:120])
        print()

    c = report["counts"]
    print("-" * 52)
    print("高风险 %d · 中风险 %d · 提示 %d" % (c["high"], c["medium"], c["low"]))
    print("提醒：本报告是发布前提示，不是过审保证；命中不等于违规，请结合语境人工判断。")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="公众号发布前体检（合规词 / 平台约束 / 排版 / HTML 兼容）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("input", help="Markdown 文件")
    ap.add_argument("--title", help="最终标题，覆盖 frontmatter 并检查长度与风险")
    ap.add_argument("--summary", help="最终摘要，覆盖 frontmatter 并检查长度与风险")
    ap.add_argument("--html", help="同时校验生成的 HTML 文件")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--strict", action="store_true", help="存在高风险时退出码为 1")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.input):
        raise SystemExit("找不到文件: %s" % args.input)
    with open(args.input, encoding="utf-8") as fh:
        raw = fh.read()
    meta, md = wxmeta.parse_frontmatter(raw)

    # 标题/摘要优先命令行，其次 frontmatter
    title = args.title if args.title is not None else meta.get("title", "")
    summary = args.summary if args.summary is not None else meta.get("summary", "")

    rules = load_rules()
    report = build_report(md, title, summary, rules, args.html, meta=meta)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)

    if args.strict and report["counts"]["high"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
