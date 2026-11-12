"""lint.py 写作闸门规则与交付物版本校验的回归测试。

覆盖三层：
  1. 素材卡规则（编号唯一、D 卡出处、F 卡数字）
  2. 大纲规则（支撑挂编号、主论点质量、缺口清单）
  3. 正文规则（空引用 / 存疑卡 / 观点卡 / 数字回查）
  4. 交付物版本校验（--out，指纹与 build.json 旁路）
  5. CLI 契约（--strict 返回码、--json 结构、错误路径）

既有测试的写法约定见 test_check.py：临时目录 + 真实 CLI，必要时直接调 build_report。
"""

import json
import unittest

from support import SKILL_ROOT, WorkspaceTest
import lint


CARD_HEADER = (
    "| 编号 | 类型 | 内容 | 出处 | 备注 |\n"
    "| --- | --- | --- | --- | --- |\n"
)

BASE_CARDS = (
    "| F1 | 事实 | 缓存可以降低延迟 | 官方文档 | 已验证 |",
    "| D1 | 数据 | 转化率 30% | L21 | 2024 年数据 |",
    "| O1 | 观点 | 缓存是性能优化的核心 | 某博客 | 作者个人看法 |",
    "| ?1 | 存疑 | 缓存能降低一半成本 | 未证实 | 待核实 |",
)

# 一份「干净」的源稿：无编号引用、无带单位数字、无图片，便于隔离产品版本问题。
CLEAN_ARTICLE = (
    "---\n"
    "title: 一篇普通文章\n"
    "theme: tech\n"
    "---\n"
    "\n"
    "# 一篇普通文章\n"
    "\n"
    "这是已经定稿的正文。\n"
)


def cards_table(*rows):
    return CARD_HEADER + "\n".join(rows) + "\n"


class LintContractTest(WorkspaceTest):
    """lint.py 测试共用的夹具与断言。"""

    def write_article(self, body="这是已经定稿的正文。\n"):
        text = "---\ntitle: 一篇普通文章\ntheme: tech\n---\n\n# 普通文章\n\n" + body
        return self.write("article.md", text)

    def write_cards(self, *rows, name="cards.md"):
        return self.write(name, cards_table(*rows))

    def write_outline(self, main="缓存命中率提升会显著降低后端响应延迟",
                      supports=("- 支撑 1：缓存能省成本 [F1]",), gap=True):
        lines = ["## 主论点：" + main, ""]
        lines.extend(supports)
        if gap:
            lines.extend(["", "## 缺口清单", "- P0 暂无"])
        return self.write("outline.md", "\n".join(lines) + "\n")

    def report(self, *args):
        """跑 CLI 拿 --json 报告，并确认返回码只可能是 0/1。"""
        proc = self.run_script("lint.py", *args, "--json")
        self.assertIn(proc.returncode, (0, 1), proc.stderr)
        return proc, json.loads(proc.stdout)

    @staticmethod
    def find(report, severity=None, category=None):
        return [f for f in report["findings"]
                if (severity is None or f["severity"] == severity)
                and (category is None or f["category"] == category)]

    def assert_finding(self, report, severity, category, matched=None):
        hits = self.find(report, severity, category)
        if matched is not None:
            hits = [f for f in hits if matched in f["matched"]]
        self.assertTrue(hits, report)
        return hits[0]


# ---------------------------------------------------------------- 素材卡

class CardRuleTests(LintContractTest):
    def test_duplicate_card_number_is_high(self):
        article = self.write_article()
        cards = self.write_cards(
            "| F1 | 事实 | 缓存可以降低延迟 | 官方文档 | 已验证 |",
            "| F1 | 事实 | 重复编号的卡 | 官方文档 | 无 |",
        )
        _, report = self.report(article, "--cards", cards)
        hit = self.assert_finding(report, "high", "素材卡", "F1")
        self.assertIn("编号重复", hit["message"])

    def test_unique_card_numbers_are_not_flagged(self):
        article = self.write_article()
        cards = self.write_cards(*BASE_CARDS)
        _, report = self.report(article, "--cards", cards)
        self.assertEqual(self.find(report, None, "素材卡"), [])

    def test_data_card_with_blank_or_dash_source_is_high(self):
        for source in ("—", "-", ""):
            with self.subTest(source=source):
                article = self.write_article()
                cards = self.write_cards(
                    "| D2 | 数据 | 转化率 30%% | %s | 无 |" % source
                )
                _, report = self.report(article, "--cards", cards)
                hit = self.assert_finding(report, "high", "素材卡", "D2 缺出处")
                self.assertIn("没有出处", hit["message"])

    def test_data_card_with_locator_source_is_accepted(self):
        for source in ("L21", "第 3 页", "P7", "12 页"):
            with self.subTest(source=source):
                article = self.write_article()
                cards = self.write_cards(
                    "| D2 | 数据 | 转化率 30%% | %s | 无 |" % source
                )
                _, report = self.report(article, "--cards", cards)
                self.assertEqual(self.find(report, None, "素材卡"), [])

    def test_data_card_source_without_locator_is_low(self):
        article = self.write_article()
        cards = self.write_cards("| D2 | 数据 | 转化率 30% | 原文 | 无 |")
        _, report = self.report(article, "--cards", cards)
        hit = self.assert_finding(report, "low", "素材卡", "原文")
        self.assertIn("行号", hit["message"])
        self.assertEqual(self.find(report, "high", "素材卡"), [])

    def test_cards_file_without_parsable_table_is_high(self):
        article = self.write_article()
        cards = self.write("empty-cards.md", "# 素材卡\n\n这里没有编号表格。\n")
        _, report = self.report(article, "--cards", cards)
        hit = self.assert_finding(report, "high", "素材卡", "0 张卡")
        self.assertIn("没解析出任何卡片", hit["message"])


# ---------------------------------------------------------------- 正文引用

class ArticleReferenceTests(LintContractTest):
    def test_unknown_reference_is_high(self):
        article = self.write_article("缓存确实有效 [F9]。\n")
        cards = self.write_cards(*BASE_CARDS)
        _, report = self.report(article, "--cards", cards)
        hit = self.assert_finding(report, "high", "正文引用", "[F9]")
        self.assertIn("空引用", hit["message"])

    def test_known_reference_is_not_flagged(self):
        article = self.write_article("缓存确实有效 [F1]。\n")
        cards = self.write_cards(*BASE_CARDS)
        _, report = self.report(article, "--cards", cards)
        self.assertEqual(self.find(report, None, "正文引用"), [])

    def test_doubtful_card_reference_is_high(self):
        article = self.write_article("据说不确定 [?1]。\n")
        cards = self.write_cards(*BASE_CARDS)
        _, report = self.report(article, "--cards", cards)
        hit = self.assert_finding(report, "high", "正文引用", "[?1]")
        self.assertIn("存疑卡", hit["message"])

    def test_opinion_card_reference_is_medium(self):
        article = self.write_article("有人认为缓存最好 [O1]。\n")
        cards = self.write_cards(*BASE_CARDS)
        _, report = self.report(article, "--cards", cards)
        hit = self.assert_finding(report, "medium", "正文引用", "[O1]")
        self.assertIn("观点卡", hit["message"])
        self.assertEqual(self.find(report, "high", "正文引用"), [])

    def test_unknown_reference_reports_body_line(self):
        article = self.write_article("第一段没有引用。\n\n第二段引用 [F9]。\n")
        cards = self.write_cards(*BASE_CARDS)
        _, report = self.report(article, "--cards", cards)
        hit = self.assert_finding(report, "high", "正文引用", "[F9]")
        self.assertEqual(hit["line"], 6)
        self.assertEqual(hit["file"], "正文")

    def test_code_block_references_are_masked(self):
        article = self.write_article("```\n[F9]\n```\n\n正文没有引用。\n")
        cards = self.write_cards(*BASE_CARDS)
        _, report = self.report(article, "--cards", cards)
        self.assertEqual(self.find(report, None, "正文引用"), [])

    def test_references_need_cards_to_be_checked(self):
        # 不传素材卡时无从比对编号，不应报空引用（降级在数据来源测试里覆盖）。
        article = self.write_article("缓存确实有效 [F9]。\n")
        _, report = self.report(article)
        self.assertEqual(self.find(report, "high", "正文引用"), [])


# ---------------------------------------------------------------- 数据来源

class DataSourceTests(LintContractTest):
    def test_number_missing_from_all_cards_is_high(self):
        article = self.write_article("用户增长了 42%。\n")
        cards = self.write_cards("| D1 | 数据 | 转化率 30% | L21 | 数据 |")
        _, report = self.report(article, "--cards", cards)
        hit = self.assert_finding(report, "high", "数据来源", "42%")
        self.assertIn("找不到出处", hit["message"])

    def test_number_found_in_data_card_passes(self):
        article = self.write_article("转化率达到了 30%。\n")
        cards = self.write_cards("| D1 | 数据 | 转化率 30% | L21 | 数据 |")
        _, report = self.report(article, "--cards", cards)
        self.assertEqual(self.find(report, "high", "数据来源"), [])

    def test_number_found_in_fact_card_passes(self):
        # 曾经修过的 bug：数字只回查 D 卡，F 卡里的数字被误报为无出处。
        article = self.write_article("官方称缓存命中率可达 98% [F1]。\n")
        cards = self.write_cards("| F1 | 事实 | 官方称缓存命中率可达 98% | 官方文档 | 已验证 |")
        _, report = self.report(article, "--cards", cards)
        self.assertEqual(self.find(report, "high", "数据来源"), [])

    def test_number_absent_even_from_fact_card_is_still_high(self):
        article = self.write_article("另一份材料说命中率 99% [F1]。\n")
        cards = self.write_cards("| F1 | 事实 | 官方称缓存命中率可达 98% | 官方文档 | 已验证 |")
        _, report = self.report(article, "--cards", cards)
        self.assert_finding(report, "high", "数据来源", "99%")

    def test_missing_cards_degrades_numbers_to_low(self):
        article = self.write_article("用户增长了 35%，耗时降低到 200ms。\n")
        _, report = self.report(article)
        self.assertEqual(report["counts"]["high"], 0)
        data_findings = self.find(report, None, "数据来源")
        self.assertTrue(data_findings, report)
        self.assertTrue(all(f["severity"] == "low" for f in data_findings), report)
        self.assertTrue(any("没有提供素材卡" in f["message"] for f in data_findings))
        matched = {f["matched"] for f in data_findings}
        self.assertIn("35%", matched)
        self.assertIn("200ms", matched)


# ---------------------------------------------------------------- 大纲

class OutlineRuleTests(LintContractTest):
    def test_support_without_card_reference_is_high(self):
        article = self.write_article()
        outline = self.write_outline(supports=("- 支撑 1：缓存能省成本",))
        _, report = self.report(article, "--outline", outline)
        hit = self.assert_finding(report, "high", "大纲", "支撑 1")
        self.assertIn("没有挂 [F]/[D]", hit["message"])

    def test_support_with_card_reference_passes(self):
        article = self.write_article()
        cards = self.write_cards(*BASE_CARDS)
        outline = self.write_outline(
            supports=("- 支撑 1：缓存能省成本 [F1]",
                      "└─ 支撑 2：转化率有数据支撑 [D1]"),
        )
        _, report = self.report(article, "--cards", cards, "--outline", outline)
        self.assertEqual(self.find(report, "high", "大纲"), [])
        self.assertEqual(report["指标"]["大纲支撑"], 2)

    def test_tree_prefixed_support_lines_are_parsed(self):
        article = self.write_article()
        outline = self.write_outline(
            supports=("├─ 支撑 1：缓存能省成本 [F1]",
                      "└─ 支撑 2：响应更快 [D1]"),
        )
        _, report = self.report(article, "--outline", outline)
        self.assertEqual(report["指标"]["大纲支撑"], 2)
        self.assertFalse(any(f["matched"] == "无可识别支撑"
                             for f in self.find(report, None, "大纲")))

    def test_support_referencing_missing_card_is_high(self):
        article = self.write_article()
        cards = self.write_cards("| F1 | 事实 | 缓存可以降低延迟 | 官方文档 | 已验证 |")
        outline = self.write_outline(supports=("- 支撑 1：引用不存在的卡 [F9]",))
        _, report = self.report(article, "--cards", cards, "--outline", outline)
        hit = self.assert_finding(report, "high", "大纲", "[F9]")
        self.assertIn("不存在", hit["message"])

    def test_short_main_claim_is_high(self):
        article = self.write_article()
        outline = self.write_outline(main="缓存很重要")
        _, report = self.report(article, "--outline", outline)
        hit = self.assert_finding(report, "high", "大纲", "缓存很重要")
        self.assertIn("主论点太短", hit["message"])

    def test_phrasey_main_claim_is_medium(self):
        article = self.write_article()
        outline = self.write_outline(main="缓存命中率提升非常关键")
        _, report = self.report(article, "--outline", outline)
        hit = self.assert_finding(report, "medium", "大纲", "非常关键")
        self.assertIn("套话", hit["message"])
        self.assertEqual(report["counts"]["high"], 0)

    def test_phrasey_main_claim_ending_with_very_important_is_medium(self):
        article = self.write_article()
        outline = self.write_outline(main="缓存命中率提升非常重要")
        _, report = self.report(article, "--outline", outline)
        hit = self.assert_finding(report, "medium", "大纲", "非常重要")
        self.assertIn("套话", hit["message"])

    def test_missing_gap_list_is_low(self):
        article = self.write_article()
        outline = self.write_outline(gap=False)
        _, report = self.report(article, "--outline", outline)
        hit = self.assert_finding(report, "low", "大纲", "无缺口清单")
        self.assertIn("没有缺口清单", hit["message"])

    def test_gap_list_suppresses_low(self):
        article = self.write_article()
        outline = self.write_outline(gap=True)
        _, report = self.report(article, "--outline", outline)
        self.assertEqual(self.find(report, "low", "大纲"), [])

    def test_missing_main_claim_is_high(self):
        article = self.write_article()
        outline = self.write(
            "outline.md",
            "# 大纲\n\n- 支撑 1：缓存能省成本 [F1]\n\n## 缺口清单\n- P0 暂无\n",
        )
        _, report = self.report(article, "--outline", outline)
        hit = self.assert_finding(report, "high", "大纲", "无主论点")
        self.assertIn("没找到", hit["message"])


# ---------------------------------------------------------------- 写作解析边界（临时目录 + 真实 CLI）

class WritingParsingRegressionTests(LintContractTest):
    def test_compound_units_and_signs_are_not_conflated(self):
        for body, fact in (("30万人", "30万元"), ("30万元", "30万人"),
                           ("-30%", "30%"), ("30%", "-30%"),
                           ("30个百分点", "30%")):
            with self.subTest(body=body, fact=fact):
                article = self.write_article("变化为 " + body + "。\n")
                cards = self.write_cards("| D1 | 数据 | " + fact + " | L1 | |")
                proc, report = self.report(article, "--cards", cards, "--strict")
                self.assertEqual(proc.returncode, 1, report)
                hit = self.assert_finding(report, "high", "数据来源", body)
                self.assertEqual(hit["matched"], body)
                self.assertEqual(hit["line"], 4)

    def test_equivalent_decimal_percentages_pass(self):
        for body, fact in (("30.0%", "30%"), ("30%", "30.00％"),
                           ("-30.0%", "-30%"), ("1,200.00人", "1200人"),
                           ("-0.0%", "0%"), ("+30.0%", "30%"),
                           ("−30.0%", "-30%"),
                           ("123456789012345678901234567890.0人",
                            "123456789012345678901234567890人")):
            with self.subTest(body=body, fact=fact):
                article = self.write_article("测得 " + body + "。\n")
                cards = self.write_cards("| D1 | 数据 | " + fact + " | L1 | |")
                proc, report = self.report(article, "--cards", cards, "--strict")
                self.assertEqual(proc.returncode, 0, report)
                self.assertEqual(self.find(report, None, "数据来源"), [])

    def test_chinese_quantities_have_verified_equivalences(self):
        pairs = (("三十万人", "30万人"), ("三十万元", "30万元"),
                 ("百分之三十", "30%"), ("三十个百分点", "30个百分点"),
                 ("三点五个百分点", "3.5个百分点"),
                 ("一百二十人", "120人"), ("两百人", "200人"),
                 ("负百分之三十", "-30%"), ("三亿两千万人", "320000000人"))
        for body, fact in pairs:
            with self.subTest(body=body):
                article = self.write_article("测得 " + body + "。\n")
                cards = self.write_cards("| D1 | 数据 | " + fact + " | L1 | |")
                proc, report = self.report(article, "--cards", cards, "--strict")
                self.assertEqual(proc.returncode, 0, report)
                self.assertEqual(self.find(report, None, "数据来源"), [])

    def test_chinese_quantities_without_support_are_high(self):
        for quantity in ("三十万人", "百分之三十", "三点五个百分点"):
            with self.subTest(quantity=quantity):
                article = self.write_article("测得 " + quantity + "。\n")
                cards = self.write_cards(*BASE_CARDS[:1])
                proc, report = self.report(article, "--cards", cards, "--strict")
                self.assertEqual(proc.returncode, 1, report)
                self.assert_finding(report, "high", "数据来源", quantity)

    def test_explicit_empty_cards_check_references_and_numbers(self):
        article = self.write_article("有 [F9] 和 [?1]，增幅 30%。\n")
        cards = self.write("empty-cards.md", "无卡片表格\n")
        outline = self.write_outline(supports=("- 支撑 1：证据 [F9]",))
        proc, report = self.report(article, "--cards", cards, "--outline", outline,
                                   "--strict")
        self.assertEqual(proc.returncode, 1, report)
        self.assert_finding(report, "high", "素材卡", "0 张卡")
        self.assert_finding(report, "high", "正文引用", "[F9]")
        self.assert_finding(report, "high", "正文引用", "[?1]")
        self.assert_finding(report, "high", "数据来源", "30%")
        self.assert_finding(report, "high", "大纲", "[F9]")

    def test_missing_doubtful_reference_reports_both_risks(self):
        article = self.write_article("未知且存疑 [?9]。\n")
        cards = self.write("empty-cards.md", "无表格\n")
        _, report = self.report(article, "--cards", cards)
        hit = self.assert_finding(report, "high", "正文引用", "[?9]")
        self.assertIn("存疑", hit["message"])
        self.assertIn("空引用", hit["message"])

    def test_number_line_is_not_shifted_by_preceding_blank_lines(self):
        article = self.write_article("前段。\n\n\n30个百分点。\n")
        cards = self.write_cards(*BASE_CARDS)
        _, report = self.report(article, "--cards", cards)
        hit = self.assert_finding(report, "high", "数据来源", "30个百分点")
        self.assertEqual(hit["line"], 7)

    def test_reordered_identifier_and_missing_columns_are_parsed(self):
        article = self.write_article("测得 30% [D1]。\n")
        cards = self.write("cards.md", "| 内容 | 类型 | 编号 | 出处 |\n"
                           "| --- | --- | --- | --- |\n"
                           "| 30% | 数据 | D1 | L1 |\n")
        proc, report = self.report(article, "--cards", cards, "--strict")
        self.assertEqual(proc.returncode, 0, report)
        self.assertEqual(report["指标"]["素材卡"], 1)
        self.assertEqual(report["findings"], [])

    def test_omitted_cards_still_degrade_all_number_hints(self):
        article = self.write_article("[F9] [?1]\n" +
                                     "\n".join("测得 %d人。" % i for i in range(1, 17)))
        proc, report = self.report(article, "--strict")
        self.assertEqual(proc.returncode, 0, report)
        self.assertEqual(self.find(report, "high"), [])
        hints = [f for f in self.find(report, "low", "数据来源") if f["line"]]
        self.assertEqual(len(hints), 16)
        self.assertEqual({f["matched"] for f in hints}, {"%d人" % i for i in range(1, 17)})

    def test_reordered_blank_source_does_not_fall_back_to_note(self):
        article = self.write_article("测得 30%。\n")
        cards = self.write("cards.md", "| 编号 | 类型 | 内容 | 备注 | 出处 |\n"
                           "| --- | --- | --- | --- | --- |\n"
                           "| D1 | 数据 | 30% | L21 已核验 | |\n")
        proc, report = self.report(article, "--cards", cards, "--strict")
        self.assertEqual(proc.returncode, 1, report)
        self.assert_finding(report, "high", "素材卡", "D1 缺出处")
        self.assert_finding(report, "high", "数据来源", "30%")

    def test_card_type_contradictions_are_high(self):
        for cid, declared in (("F1", "数据"), ("D1", "存疑"),
                              ("?1", "事实"), ("F1", "O"), ("F1", "未知")):
            with self.subTest(cid=cid, declared=declared):
                article = self.write_article()
                cards = self.write_cards("| %s | %s | 30%% | L1 | |" % (cid, declared))
                proc, report = self.report(article, "--cards", cards, "--strict")
                self.assertEqual(proc.returncode, 1, report)
                self.assert_finding(report, "high", "素材卡", cid)

    def test_unsourced_or_mistyped_fact_numbers_are_not_verified(self):
        for source, declared in (("", "事实"), ("—", "事实"), ("-", "事实"),
                                 ("L1", "存疑")):
            with self.subTest(source=source, declared=declared):
                article = self.write_article("测得 98% [F1]。\n")
                cards = self.write_cards("| F1 | %s | 98%% | %s | 已验证 |" %
                                         (declared, source))
                proc, report = self.report(article, "--cards", cards, "--strict")
                self.assertEqual(proc.returncode, 1, report)
                self.assert_finding(report, "high", "数据来源", "98%")

    def test_fences_close_only_with_matching_symbol_and_length(self):
        for opening, inner, closing in (("````", "```", "````"),
                                        ("```", "~~~", "```"),
                                        ("~~~", "```", "~~~"),
                                        ("~~~~", "~~~", "~~~~~")):
            with self.subTest(opening=opening, inner=inner):
                body = opening + "\n" + inner + "\n[F8] 88%\n" + closing
                article = self.write_article(body + "\n\n[F9] 99%。\n")
                cards = self.write_cards(*BASE_CARDS)
                _, report = self.report(article, "--cards", cards)
                self.assertEqual([f["matched"] for f in self.find(report, None, "正文引用")],
                                 ["[F9]"])
                self.assertEqual([f["matched"] for f in self.find(report, None, "数据来源")],
                                 ["99%"])
                self.assertEqual(self.assert_finding(report, "high", "正文引用")["line"], 9)

    def test_fence_with_info_string_cannot_close_existing_block(self):
        article = self.write_article("```\n```python\n[F8] 88%\n```\n[F9]\n")
        cards = self.write_cards(*BASE_CARDS)
        _, report = self.report(article, "--cards", cards)
        self.assertEqual([f["matched"] for f in self.find(report, None, "正文引用")], ["[F9]"])
        self.assertEqual(self.find(report, None, "数据来源"), [])

    def test_bold_main_heading_reads_following_paragraph(self):
        for heading in ("**主论点**", "## **主论点：**", "**主论点**："):
            with self.subTest(heading=heading):
                article = self.write_article()
                outline = self.write("outline.md", heading + "\n\n缓存能降低延迟\n\n"
                                     "- 支撑一：实测 [F1]\n\n缺口清单：暂无\n")
                proc, report = self.report(article, "--outline", outline, "--strict")
                self.assertEqual(proc.returncode, 0, report)
                self.assertEqual(self.find(report, "high", "大纲"), [])
                self.assertEqual(report["指标"]["大纲支撑"], 1)

    def test_short_judgment_is_not_high_but_topic_is(self):
        for main, expected in (("缓存能降低延迟", 0), ("缓存缩短耗时。", 0), ("故障延长耗时。", 0), ("缓存", 1)):
            with self.subTest(main=main):
                article = self.write_article()
                outline = self.write_outline(main=main)
                proc, report = self.report(article, "--outline", outline, "--strict")
                self.assertEqual(proc.returncode, expected, report)

    def test_phrasey_main_with_terminal_punctuation_is_medium(self):
        for mark in ("。", "！", "!", ".", "？", "?"):
            with self.subTest(mark=mark):
                article = self.write_article()
                outline = self.write_outline(main="缓存命中率提升非常重要" + mark)
                _, report = self.report(article, "--outline", outline)
                self.assert_finding(report, "medium", "大纲", "非常重要")

    def test_chinese_support_number_without_reference_is_high(self):
        article = self.write_article()
        outline = self.write_outline(supports=("- 支撑一：实测缓存有效",))
        proc, report = self.report(article, "--outline", outline, "--strict")
        self.assertEqual(proc.returncode, 1, report)
        self.assertEqual(report["指标"]["大纲支撑"], 1)
        self.assert_finding(report, "high", "大纲", "支撑一")


# ---------------------------------------------------------------- 交付物版本

class ArtifactVersionTests(LintContractTest):
    def build(self, out=None):
        """用 md2wx 生成一套真实产物：article.html / body / sheet / build.json。"""
        article = self.write("article.md", CLEAN_ARTICLE)
        out = self.root / "out" if out is None else out
        proc = self.run_script("md2wx.py", article, "--sheet",
                               "-o", out / "article.html")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return article, out

    def test_fresh_artifacts_have_no_version_finding(self):
        article, out = self.build()
        proc, report = self.report(article, "--out", out)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.find(report, None, "产物版本"), [])
        self.assertEqual(report["counts"]["high"], 0)

    def test_stale_artifacts_after_source_edit_are_high(self):
        article, out = self.build()
        with article.open("a", encoding="utf-8") as fh:
            fh.write("\n源稿后来又改了一段。\n")
        proc = self.run_script("lint.py", article, "--out", out, "--strict", "--json")
        self.assertEqual(proc.returncode, 1)
        report = json.loads(proc.stdout)
        hits = self.find(report, "high", "产物版本")
        self.assertTrue(hits, report)
        matched = " ".join(f["matched"] for f in hits)
        messages = " ".join(f["message"] for f in hits)
        # 产物本身与清单一致；问题出在清单与当前源稿不一致
        self.assertIn("build.json", matched)
        self.assertTrue("旧版本" in messages or "不一致" in messages, hits)

    def test_tampered_body_fragment_is_high(self):
        for how in ("append", "replace"):
            with self.subTest(how=how):
                article, out = self.build()
                body = out / "article.body.html"
                if how == "append":
                    body.write_text(body.read_text(encoding="utf-8") + "<p>手工追加</p>\n",
                                    encoding="utf-8")
                else:
                    body.write_text("<p>换成了另一版正文</p>\n", encoding="utf-8")
                _, report = self.report(article, "--out", out)
                hits = self.find(report, "high", "产物版本")
                self.assertEqual([f["matched"] for f in hits], ["article.body.html"])

    def test_handcrafted_html_without_fingerprint_is_medium(self):
        article = self.write("article.md", CLEAN_ARTICLE)
        out = self.root / "handmade"
        out.mkdir()
        (out / "article.html").write_text(
            "<!DOCTYPE html><html><head><title>手造</title></head>"
            "<body><p>正文</p></body></html>\n",
            encoding="utf-8",
        )
        _, report = self.report(article, "--out", out)
        hit = self.assert_finding(report, "medium", "产物版本", "缺 build.json")
        self.assertIn("无法校验", hit["message"])
        self.assertEqual(self.find(report, "high", "产物版本"), [])

    def test_missing_out_dir_is_high(self):
        article = self.write("article.md", CLEAN_ARTICLE)
        missing = self.root / "not-created"
        _, report = self.report(article, "--out", missing)
        hits = self.find(report, "high", "产物版本")
        self.assertEqual(len(hits), 1, report)
        self.assertEqual(hits[0]["matched"], str(missing))
        self.assertIn("不存在", hits[0]["message"])

    def test_out_dir_without_artifacts_is_medium(self):
        article = self.write("article.md", CLEAN_ARTICLE)
        out = self.root / "empty-out"
        out.mkdir()
        _, report = self.report(article, "--out", out)
        hit = self.assert_finding(report, "medium", "产物版本", str(out))
        self.assertIn("没有可校验的产物", hit["message"])


# ---------------------------------------------------------------- CLI 契约

class CliContractTests(LintContractTest):
    def test_json_report_has_stable_shape(self):
        article = self.write_article("缓存有效 [F9]，增长了 42%。\n")
        cards = self.write_cards("| D1 | 数据 | 转化率 30% | L21 | 数据 |")
        outline = self.write_outline(supports=("- 支撑 1：没有编号",), gap=False)
        proc, report = self.report(article, "--cards", cards, "--outline", outline)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(set(report), {"指标", "findings", "counts"})
        self.assertEqual(set(report["counts"]), {"high", "medium", "low"})
        for key in ("标题", "正文字数", "素材卡", "大纲支撑",
                    "正文引用编号", "构建指纹"):
            self.assertIn(key, report["指标"])
        self.assertTrue(report["findings"], report)
        for finding in report["findings"]:
            self.assertEqual(
                set(finding),
                {"severity", "category", "line", "matched",
                 "message", "suggest", "file"},
            )
            self.assertIn(finding["severity"], ("high", "medium", "low"))
        self.assertEqual(sum(report["counts"].values()), len(report["findings"]))

    def test_strict_exit_code_is_one_when_high(self):
        article = self.write_article("缓存有效 [F9]。\n")
        cards = self.write_cards(*BASE_CARDS)
        proc = self.run_script("lint.py", article, "--cards", cards,
                               "--strict", "--json")
        self.assertEqual(proc.returncode, 1)
        self.assertGreater(json.loads(proc.stdout)["counts"]["high"], 0)

    def test_strict_exit_code_is_zero_without_high(self):
        article = self.write_article("缓存有效 [F1]。\n")
        cards = self.write_cards(*BASE_CARDS)
        proc = self.run_script("lint.py", article, "--cards", cards,
                               "--strict", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(json.loads(proc.stdout)["counts"]["high"], 0)

    def test_text_report_shows_severity_and_totals(self):
        article = self.write_article("缓存有效 [F9]。\n")
        cards = self.write_cards(*BASE_CARDS)
        proc = self.run_script("lint.py", article, "--cards", cards)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("写作闸门校验", proc.stdout)
        self.assertIn("【必须修】", proc.stdout)
        self.assertIn("必须修", proc.stdout)

    def test_missing_cards_file_is_reported(self):
        article = self.write_article()
        proc = self.run_script("lint.py", article,
                               "--cards", self.root / "no-such-cards.md")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("找不到素材卡文件", proc.stderr)

    def test_missing_article_file_is_reported(self):
        proc = self.run_script("lint.py", self.root / "no-such-article.md")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("找不到正文", proc.stderr)

    def test_direct_build_report_returns_contract_dict(self):
        article = self.write_article("缓存有效 [F9]。\n")
        cards = self.write_cards(*BASE_CARDS)
        report = lint.build_report(str(article), str(cards), None)
        self.assertEqual(set(report), {"指标", "findings", "counts"})
        self.assertEqual(report["指标"]["素材卡"], len(BASE_CARDS))
        self.assertEqual(report["指标"]["标题"], "一篇普通文章")
        self.assertTrue(any(f["category"] == "正文引用"
                            and f["severity"] == "high"
                            and f["matched"] == "[F9]"
                            for f in report["findings"]))

    def test_example_article_has_no_blocking_finding(self):
        proc, report = self.report(SKILL_ROOT / "examples/sample-article.md")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(report["counts"]["high"], 0)


if __name__ == "__main__":
    unittest.main()
