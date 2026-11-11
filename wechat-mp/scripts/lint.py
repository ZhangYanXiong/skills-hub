#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lint.py — 写作环节的确定性校验（把文档里的纪律变成能跑挂的闸门）

为什么需要它:
    check.py 只管「发布合规」，管不了「论点有没有依据」「数字从哪来」。
    而后者恰恰是 AI 写稿最容易翻车的地方：文档里写一百遍「不许编造」，
    不如让脚本在正文出现无出处数字时直接报错。

校验三类对象:

    1. 素材卡（--cards）
       - 编号唯一
       - D 数据卡必须有行号/页码出处
       - 类型只能是 F / D / O / ?

    2. 大纲（--outline）
       - 每条「支撑」必须挂 ≥1 个 [F]/[D] 编号
       - 主论点必须是可被反驳的判断句（不能是短语）
       - 必须有缺口清单

    3. 正文（必填）
       - 引用的编号必须存在于素材卡（否则是空引用）
       - ? 存疑卡不得进正文
       - O 观点卡不得当主论据（提示需注明「某人认为」）
       - 正文里的每个「数字+单位」必须能在有出处的 F/D 卡找到
       - 未传卡片则降级为提示；显式传卡但解析为空仍作为错误

依赖: 仅标准库。

用法:
    python3 scripts/lint.py article.md
    python3 scripts/lint.py article.md --cards 素材卡.md --outline 大纲.md
    python3 scripts/lint.py article.md --cards 素材卡.md --strict
"""

import argparse
import hashlib
import json
import os
import re
import sys
from decimal import Decimal, localcontext

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import wxmeta  # noqa: E402

SEV_ORDER = {"high": 0, "medium": 1, "low": 2}
SEV_LABEL = {"high": "必须修", "medium": "应确认", "low": "提示"}
SEV_ICON = {"high": "✗", "medium": "!", "low": "·"}

# 素材卡编号：[F1] [D2] [O3] [?4]
REF_RE = re.compile(r"\[([FDO?])(\d+)\]")
# 完整数量：保留符号、复合单位；支持常用中文整数/小数及「百分之」。
CN_DIGITS = "零〇一二两三四五六七八九"
CN_NUMBER = r"[零〇一二两三四五六七八九十百千万亿]+(?:点[零〇一二两三四五六七八九]+)?"
NUMBER = r"(?:\d[\d,]*(?:\.\d+)?|" + CN_NUMBER + r")"
BASE_UNIT = r"(?:个百分点|%|％|ms|毫秒|分钟|小时|个月|美元|秒|s|天|周|月|元|倍|次|个|人|家|台|条|张)"
NUM_UNIT_RE = re.compile(
    r"(?:(?P<sign>[+\-−负正])\s*)?(?:百分之\s*(?P<percent>" + NUMBER + r")|"
    r"(?P<number>" + NUMBER + r")\s*(?P<unit>(?:[万亿千百]" + BASE_UNIT + r"|"
    + BASE_UNIT + r"|万|亿)))"
)
CARD_TYPES = {"F": "F", "事实": "F", "D": "D", "数据": "D",
              "O": "O", "观点": "O", "?": "?", "存疑": "?"}
# 主论点常见的「短语式」失败
PHRASEY_RE = re.compile(
    r"(很重要|非常重要|十分重要|极其重要|至关重要|要重视|值得关注|"
    r"非常关键|意义重大|势在必行|大有裨益)$"
)
# 出处里算「有行号」的形式
SOURCE_OK_RE = re.compile(r"(L\s*\d+|第\s*\d+\s*[页节]|P\s*\d+|\d+\s*页)", re.I)


# ---------------------------------------------------------------- 解析

def chinese_number(value: str) -> Decimal:
    """常用中文整数（十/百/千/万/亿）与「点」小数，非口语省略写法。"""
    integer, _, fraction = value.partition("点")
    digits = dict(zip(CN_DIGITS, (0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9)))
    if all(ch in digits for ch in integer):
        result = int("".join(str(digits[ch]) for ch in integer))
    else:
        total, section, digit = 0, 0, 0
        for ch in integer:
            if ch in digits:
                digit = digits[ch]
            elif ch in "十百千":
                section += (digit or 1) * {"十": 10, "百": 100, "千": 1000}[ch]
                digit = 0
            elif ch == "万":
                total += (section + digit) * 10000
                section, digit = 0, 0
            elif ch == "亿":
                total = (total + section + digit) * 100000000
                section, digit = 0, 0
        result = total + section + digit
    suffix = "." + "".join(str(digits[ch]) for ch in fraction) if fraction else ""
    return Decimal(str(result) + suffix)


def normalize_num(s: str) -> str:
    match = NUM_UNIT_RE.fullmatch(s.strip())
    if not match:
        return s
    number = match.group("percent") or match.group("number")
    unit = "%" if match.group("percent") else match.group("unit")
    value = (Decimal(number.replace(",", "")) if number[0].isdigit()
             else chinese_number(number))
    # Decimal 默认精度为 28，按输入长度扩展，避免长数字被静默四舍五入。
    with localcontext() as ctx:
        ctx.prec = max(28, len(number) + 16)
        if len(unit) > 1 and unit[0] in "万亿千百":
            value *= {"万": 10000, "亿": 100000000, "千": 1000, "百": 100}[unit[0]]
            unit = unit[1:]
        if match.group("sign") in ("-", "−", "负"):
            value = -value
        canonical = format(value, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    return canonical + unit.replace("％", "%").replace("毫秒", "ms")


def number_matches(text):
    for match in NUM_UNIT_RE.finditer(text):
        # 「千万不要/千万别」是副词警示，不是数量；「千万用户」仍是数量。
        if (match.group(0).strip() == '千万'
                and re.match(r'(?:不要|不能|不可|别|莫|勿|要|注意|记住|小心)', text[match.end():].lstrip())):
            continue
        yield match


def strip_code(text: str) -> str:
    return wxmeta.mask_code(text)


def split_cells(line: str):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def clean_cell(c: str) -> str:
    return re.sub(r"[*`_]", "", c).strip()


def parse_cards(path: str):
    """返回 {编号: {type, content, source, note, line}}，以及原始行。"""
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")

    cards, order = {}, []
    header = None
    for lineno, line in enumerate(lines, 1):
        if not line.strip().startswith("|"):
            header = None
            continue
        cells = [clean_cell(c) for c in split_cells(line)]
        if not cells:
            continue
        if re.fullmatch(r"[-:\s]+", cells[0]):
            continue
        if "编号" in cells:
            header = cells
            continue
        lookup = ({h: (cells[i] if i < len(cells) else "")
                   for i, h in enumerate(header)} if header else {})
        identifier = lookup.get("编号", cells[0])
        m = re.fullmatch(r"([FDO?])(\d+)", identifier)
        if not m:
            continue
        cid = m.group(1) + m.group(2)

        def field(name, position):
            # 表头存在时只按列名取值；空字段或缺列不能拿别的列顶替。
            return lookup.get(name, "") if header else (cells[position] if len(cells) > position else "")

        cards[cid] = {
            "type": m.group(1),
            "declared_type": field("类型", 1),
            "content": field("内容", 2),
            "source": field("出处", 3),
            "note": field("备注", 4),
            "line": lineno,
        }
        order.append(cid)
    return cards, order


def parse_outline(path: str):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    def clean_outline_line(line):
        return re.sub(r"[*`_]", "", line).strip().lstrip("#> ").strip()

    main = ""
    lines = strip_code(text).split("\n")
    for i, ln in enumerate(lines):
        cleaned = clean_outline_line(ln)
        if "主论点" not in cleaned:
            continue
        after = re.sub(r".*?主论点\s*[：:]?", "", cleaned).strip()
        if not after:
            # 先清除加粗/标题标记，再判断是否需要读取下一段。
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    if re.match(r"\s*(?:#|[-*]\s|[├└│])", nxt):
                        break
                    after = clean_outline_line(nxt)
                    break
        main = after.strip("「」")
        if main:
            break

    supports = []
    for lineno, line in enumerate(lines, 1):
        s = line.strip()
        if not s:
            continue
        is_support = ("支撑" in s and (s.startswith(("├", "└", "│", "-", "*"))
                                       or "支撑" in s[:6]))
        if not is_support:
            continue
        if re.search(r"支撑\s*(?:\d+|[一二三四五六七八九十百]+)\s*[：:]", s) or s.startswith(("├", "└", "│")):
            supports.append({"line": lineno, "text": s})
    return {"main": main, "supports": supports,
            "has_gap": bool(re.search(r"缺口", text)),
            "text": text}


# ---------------------------------------------------------------- 校验

def lint_cards(cards, order):
    findings = []
    if not cards:
        findings.append({
            "severity": "high", "category": "素材卡", "line": 0, "matched": "0 张卡",
            "message": "素材卡文件里没解析出任何卡片",
            "suggest": "检查表格第一列是否为 F1 / D2 / O3 / ?4 这样的编号格式",
        })
        return findings

    seen = {}
    for cid in order:
        seen[cid] = seen.get(cid, 0) + 1
    for cid, n in seen.items():
        if n > 1:
            findings.append({
                "severity": "high", "category": "素材卡", "line": cards[cid]["line"],
                "matched": cid, "message": "编号重复 %d 次" % n,
                "suggest": "重新编号；正文引用会指向不确定的卡片",
            })

    for cid, c in cards.items():
        declared = c.get("declared_type", "")
        if declared and CARD_TYPES.get(declared) != c["type"]:
            findings.append({
                "severity": "high", "category": "素材卡", "line": c["line"],
                "matched": cid + " 类型 " + declared,
                "message": "类型列与编号矛盾，或类型无法识别",
                "suggest": "统一编号与类型（F/事实、D/数据、O/观点、?/存疑）",
            })
        if c["type"] == "D":
            if not c["source"] or c["source"] in ("—", "-", ""):
                findings.append({
                    "severity": "high", "category": "素材卡", "line": c["line"],
                    "matched": cid + " 缺出处", "message": "数据卡没有出处，无法回查",
                    "suggest": "补行号/页码（如 L21、第 3 页）",
                })
            elif not SOURCE_OK_RE.search(c["source"]):
                findings.append({
                    "severity": "low", "category": "素材卡", "line": c["line"],
                    "matched": c["source"],
                    "message": "出处里没有可定位的行号/页码",
                    "suggest": "写成 L21 或「第 3 页」，否则等于没出处",
                })
        if c["type"] == "F" and c["content"] and c["content"].endswith(("可能", "也许", "大概")):
            findings.append({
                "severity": "medium", "category": "素材卡", "line": c["line"],
                "matched": cid, "message": "标成「事实」但内容是推测口吻",
                "suggest": "改成 O（观点）卡",
            })
    return findings


def lint_outline(outline, cards, cards_provided=False):
    findings = []
    main, supports = outline["main"], outline["supports"]

    if not main:
        findings.append({
            "severity": "high", "category": "大纲", "line": 0, "matched": "无主论点",
            "message": "没找到「主论点：」",
            "suggest": "按 topic-expand.md §3.2 模板补上",
        })
    else:
        core = re.sub(r"[「」\"'（）()\s]", "", main).rstrip("。！？.!?；;，,")
        # 长度只是话题式短语的线索，不能把短而明确的判断句一律判死。
        judgment = re.search(r".{2,}(?:能|可以|会|导致|降低|提高|减少|增加|缩短|延长|优于|不如|是).{2,}", core)
        if len(core) < 10 and not judgment:
            findings.append({
                "severity": "high", "category": "大纲", "line": 0, "matched": main,
                "message": "主论点太短，更像话题而不是判断句",
                "suggest": "写成「主语 + 判断 + 条件」的可反驳句",
            })
        if PHRASEY_RE.search(core):
            findings.append({
                "severity": "medium", "category": "大纲", "line": 0, "matched": main,
                "message": "主论点落在套话上，不可反驳",
                "suggest": "换成一个能被反对的具体判断",
            })

    if not supports:
        findings.append({
            "severity": "low", "category": "大纲", "line": 0, "matched": "无可识别支撑",
            "message": "没解析到论点树里的支撑行",
            "suggest": "用「├─ 支撑 1：...」格式写，并挂 [F1] 这类编号",
        })

    for s in supports:
        refs = REF_RE.findall(s["text"])
        usable = [r for r in refs if r[0] in ("F", "D")]
        if not usable:
            findings.append({
                "severity": "high", "category": "大纲", "line": s["line"],
                "matched": s["text"][:60],
                "message": "这条支撑没有挂 [F]/[D] 素材编号",
                "suggest": "挂上编号；挂不上就删掉这条支撑（topic-expand.md §4.2）",
            })
        if cards or cards_provided:
            for t, n in refs:
                if (t + n) not in cards:
                    findings.append({
                        "severity": "high", "category": "大纲", "line": s["line"],
                        "matched": "[%s%s]" % (t, n),
                        "message": "引用的素材卡不存在",
                        "suggest": "补卡或改编号",
                    })

    if not outline["has_gap"]:
        findings.append({
            "severity": "low", "category": "大纲", "line": 0, "matched": "无缺口清单",
            "message": "大纲里没有缺口清单",
            "suggest": "补 P0/P1/P2 缺口（topic-expand.md §5.1）",
        })
    return findings


def lint_article(body, cards, cards_provided=False):
    findings = []
    masked = strip_code(body)

    refs = {}
    for m in REF_RE.finditer(masked):
        cid = m.group(1) + m.group(2)
        line = masked.count("\n", 0, m.start()) + 1
        refs.setdefault(cid, line)

    # 编号存在性
    if cards or cards_provided:
        for cid, line in refs.items():
            if cid not in cards:
                findings.append({
                    "severity": "high", "category": "正文引用", "line": line,
                    "matched": "[%s]" % cid,
                    "message": ("引用的素材卡不存在（空引用）；存疑卡不得进正文"
                                if cid.startswith("?") else "引用的素材卡不存在（空引用）"),
                    "suggest": "补卡或删掉该引用",
                })
            if cid in cards and cards[cid]["type"] == "?":
                findings.append({
                    "severity": "high", "category": "正文引用", "line": line,
                    "matched": "[%s]" % cid,
                    "message": "存疑卡不得进正文",
                    "suggest": "核实后转成 F/D 卡，否则删掉相关表述",
                })
            elif cid in cards and cards[cid]["type"] == "O":
                findings.append({
                    "severity": "medium", "category": "正文引用", "line": line,
                    "matched": "[%s]" % cid,
                    "message": "观点卡被引用，需确认没有当主论据",
                    "suggest": "写成「原文作者认为…」，不要写成人人都认同的事实",
                })

    # 数字 → D 卡
    nums = []
    for m in number_matches(masked):
        raw = normalize_num(m.group(0))
        line = masked.count("\n", 0, m.start()) + 1
        nums.append((raw, line, m.group(0).strip()))

    if not nums:
        return findings

    if not cards and not cards_provided:
        uniq = []
        seen = set()
        for raw, line, disp in nums:
            if raw in seen:
                continue
            seen.add(raw)
            uniq.append((line, disp))
        if uniq:
            findings.append({
                "severity": "low", "category": "数据来源", "line": 0,
                "matched": "%d 个带单位数字" % len(uniq),
                "message": "没有提供素材卡，正文里的数字无法校验出处",
                "suggest": "有素材就传 --cards；纯观点稿请确认这些数字是否必须保留",
            })
            for line, disp in uniq:
                findings.append({
                    "severity": "low", "category": "数据来源", "line": line,
                    "matched": disp, "message": "该数字没有材料支撑",
                    "suggest": "删掉、改成定性表述，或补素材卡",
                })
        return findings

    # 有卡：逐个数字回查「带出处的卡」（D 数据卡 + F 事实卡）
    dcache = {}
    for cid, c in cards.items():
        declared = c.get("declared_type", "")
        if (c["type"] not in ("D", "F")
                or not c["source"].strip() or c["source"].strip() in ("—", "-")
                or (declared and CARD_TYPES.get(declared) != c["type"])):
            continue
        blob = c["content"] + " " + c["note"]
        for m in number_matches(blob):
            dcache.setdefault(normalize_num(m.group(0)), cid)

    for raw, line, disp in nums:
        if raw in dcache:
            continue
        findings.append({
            "severity": "high", "category": "数据来源", "line": line,
            "matched": disp,
            "message": "这个数字在素材卡里找不到出处",
            "suggest": "补 D 卡并标明行号，或删掉这个数字",
        })
    return findings


# 正文片段保持纯净；所有产物使用 wxbuild 的清单和摘要校验。
def resolve_theme(meta):
    name = meta.get("theme") or "tech"
    try:
        import md2wx
        return md2wx.load_theme(name), name
    except SystemExit:
        return {"name": name}, name


def _wxbuild():
    import wxbuild
    return wxbuild


def lint_artifacts(out_dir, raw, meta, require_covers=False):
    """交付物完整性校验，委托给 wxbuild（唯一算法来源）。

    这里不再自己算指纹/摘要：md2wx 用 wxbuild.context 产出，
    lint 必须用同一套逻辑验证，否则会出现「刚生成就判旧」的自相矛盾。
    """
    if not os.path.isdir(out_dir):
        return [{
            "severity": "high", "category": "产物版本", "line": 0,
            "matched": out_dir,
            "message": "输出目录不存在",
            "suggest": "检查 --out 参数，或先运行 md2wx.py",
        }]
    try:
        issues = _wxbuild().validate_artifacts(out_dir, raw, meta)
        issues += _wxbuild().validate_covers(out_dir, require=require_covers)
        return issues
    except Exception as exc:  # 校验器自身异常也要变成 finding，不能抛栈
        return [{
            "severity": "high", "category": "产物版本", "line": 0,
            "matched": "wxbuild",
            "message": "产物校验失败: %s" % exc,
            "suggest": "检查 build.json 是否完整，或重新渲染",
        }]


def display_fingerprint(raw, meta, out_dir):
    """报告头展示的指纹：有有效清单时用真实构建指纹，否则退回环境指纹。"""
    if out_dir and os.path.isdir(out_dir) and os.path.isfile(os.path.join(out_dir, "build.json")):
        try:
            return _wxbuild().current_fingerprint(raw, meta, out_dir)
        except Exception:
            return "（清单无效，无法计算）"
    return wxmeta.fingerprint(raw, resolve_theme(meta)[0])


# ---------------------------------------------------------------- 报告

def build_report(article_path, cards_path, outline_path, out_dir=None,
                 require_covers=False):
    with open(article_path, encoding="utf-8") as fh:
        raw = fh.read()
    meta, body = wxmeta.parse_frontmatter(raw)

    cards, order = ({}, [])
    if cards_path:
        if not os.path.isfile(cards_path):
            raise SystemExit("找不到素材卡文件: %s" % cards_path)
        cards, order = parse_cards(cards_path)

    outline = None
    if outline_path:
        if not os.path.isfile(outline_path):
            raise SystemExit("找不到大纲文件: %s" % outline_path)
        outline = parse_outline(outline_path)

    findings = []
    if cards_path:
        for f in lint_cards(cards, order):
            f["file"] = "素材卡"
            findings.append(f)
    if outline:
        for f in lint_outline(outline, cards, cards_provided=bool(cards_path)):
            f["file"] = "大纲"
            findings.append(f)
    for f in lint_article(body, cards, cards_provided=bool(cards_path)):
        f["file"] = "正文"
        findings.append(f)

    if out_dir:
        if not os.path.isdir(out_dir):
            findings.append({
                "severity": "high", "category": "产物版本", "line": 0,
                "matched": out_dir, "file": "产物",
                "message": "输出目录不存在",
                "suggest": "检查 --out 参数，或先运行 md2wx.py",
            })
        else:
            for f in lint_artifacts(out_dir, raw, meta, require_covers):
                f["file"] = "产物"
                findings.append(f)

    seen, uniq = set(), []
    for f in findings:
        key = (f["severity"], f["category"], f["matched"], f["line"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(f)
    uniq.sort(key=lambda f: (SEV_ORDER.get(f["severity"], 9), f["line"]))

    return {
        "指标": {
            "标题": meta.get("title", "（未提供）"),
            "正文字数": wxmeta.count_words(body),
            "素材卡": len(cards) if cards_path else 0,
            "大纲支撑": len(outline["supports"]) if outline else 0,
            "正文引用编号": len(REF_RE.findall(strip_code(body))),
            "构建指纹": display_fingerprint(raw, meta, out_dir),
        },
        "findings": uniq,
        "counts": {k: sum(1 for f in uniq if f["severity"] == k)
                   for k in ("high", "medium", "low")},
    }


def print_report(report):
    m = report["指标"]
    print("写作闸门校验")
    print("=" * 52)
    print("标题      %s" % m["标题"])
    print("正文      %d 字 · 引用编号 %d 处" % (m["正文字数"], m["正文引用编号"]))
    print("指纹      %s（当前源稿应产出这个值）" % m["构建指纹"])
    if m["素材卡"]:
        print("素材卡    %d 张 · 大纲支撑 %d 条" % (m["素材卡"], m["大纲支撑"]))
    else:
        print("素材卡    ——未提供，数据来源无法校验")
    print()

    if not report["findings"]:
        print("未发现需要修的问题。")
        return

    cur = None
    for f in report["findings"]:
        if f["severity"] != cur:
            cur = f["severity"]
            print("【%s】" % SEV_LABEL.get(cur, cur))
        if not f["line"]:
            loc = "     "
        elif f.get("file") == "正文":
            loc = "L%-4d" % f["line"]
        else:
            loc = "%sL%-3d" % (f.get("file", ""), f["line"])
        print("  %s %s %s" % (loc, SEV_ICON.get(f["severity"], "·"), f["category"]))
        print("       命中: %s" % (f["matched"][:80] if f["matched"] else "—"))
        if f["message"] and f["message"] != f["matched"]:
            print("       问题: %s" % f["message"][:100])
        if f["suggest"]:
            print("       建议: %s" % f["suggest"][:110])
        print()

    c = report["counts"]
    print("-" * 52)
    print("必须修 %d · 应确认 %d · 提示 %d" % (c["high"], c["medium"], c["low"]))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="正文 / 大纲 / 素材卡的一致性校验（写作环节的闸门）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("article", help="正文 Markdown")
    ap.add_argument("--cards", help="素材卡文件（含 F/D/O/? 编号表格）")
    ap.add_argument("--outline", help="大纲文件（含主论点与论点树）")
    ap.add_argument("--out", help="产物目录；校验交付物是否为当前源稿版本")
    ap.add_argument("--publish", action="store_true",
                    help="配合 --out 按发布就绪范围校验本项目三档封面的存在与 PNG 头尺寸")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--strict", action="store_true", help="存在「必须修」时退出码 1")
    args = ap.parse_args(argv)
    if args.publish and not args.out:
        ap.error('--publish 必须配合 --out 指定待验收产物目录')

    if not os.path.isfile(args.article):
        raise SystemExit("找不到正文: %s" % args.article)

    report = build_report(args.article, args.cards, args.outline, args.out,
                          args.publish)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)

    if args.strict and report["counts"]["high"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
