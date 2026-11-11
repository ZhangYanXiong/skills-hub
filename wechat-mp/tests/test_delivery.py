"""交付链路的真实 CLI 回归与静态任务路由契约。"""

from html.parser import HTMLParser
import struct
import unittest
import zlib

from support import SKILL_ROOT, WorkspaceTest


ARTICLE = """---
title: 普通文章
title_short: 普通文章
summary: 介绍具体做法与适用范围。
theme: tech
---

# 普通文章

这是已经定稿的正文。
"""


class SheetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cover_sources = []
        self.article_parts = []
        self.in_article = False
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "img" and values.get("class") == "cover":
            self.cover_sources.append(values.get("src"))
        if tag == "div" and values.get("id") == "article-body":
            self.in_article = True
            self.depth = 1
        elif self.in_article:
            self.article_parts.append(self.get_starttag_text())
            if tag == "div":
                self.depth += 1

    def handle_endtag(self, tag):
        if not self.in_article:
            return
        if tag == "div":
            self.depth -= 1
            if not self.depth:
                self.in_article = False
                return
        self.article_parts.append("</%s>" % tag)

    def handle_data(self, data):
        if self.in_article:
            self.article_parts.append(data)

    def handle_entityref(self, name):
        if self.in_article:
            self.article_parts.append("&%s;" % name)

    def handle_charref(self, name):
        if self.in_article:
            self.article_parts.append("&#%s;" % name)


def write_test_png(path):
    """生成真实的 1×1 PNG 测试资产；只验证文件发现，不验证封面画图。"""
    def chunk(kind, content):
        return (struct.pack(">I", len(content)) + kind + content
                + struct.pack(">I", zlib.crc32(kind + content) & 0xffffffff))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                     + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
                     + chunk(b"IEND", b""))


class DeliveryRegressionTests(WorkspaceTest):
    def setUp(self):
        super().setUp()
        self.article = self.write("article.md", ARTICLE)

    def render(self, target, *options):
        return self.run_script("md2wx.py", self.article, "-o", target, *options)

    def test_render_creates_missing_nested_output_directory(self):
        target = self.root / "new" / "nested" / "article.html"
        proc = self.render(target, "--sheet")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(target.is_file())
        self.assertTrue(target.with_name("article.body.html").is_file())
        self.assertTrue(target.with_name("sheet.html").is_file())

    def test_output_path_with_spaces_is_created(self):
        target = self.root / "发布 目录" / "稿件.html"
        proc = self.render(target, "--sheet")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(target.with_name("sheet.html").is_file())

    def test_no_body_creates_only_requested_outputs_in_new_directory(self):
        target = self.root / "new" / "article.html"
        proc = self.render(target, "--sheet", "--no-body")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(target.is_file())
        self.assertTrue(target.with_name("sheet.html").is_file())
        self.assertFalse(target.with_name("article.body.html").exists())

    def test_check_does_not_create_output_directory(self):
        target = self.root / "no-output" / "article.html"
        proc = self.render(target, "--check", "--sheet")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(target.parent.exists())

    def test_bad_input_or_theme_does_not_create_output_directory(self):
        target = self.root / "no-output" / "article.html"
        proc = self.run_script("md2wx.py", self.root / "missing.md", "-o", target)
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(target.parent.exists())
        proc = self.render(target, "-t", "missing-theme")
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(target.parent.exists())

    def test_render_preserves_source_and_existing_directory(self):
        source = self.article.read_bytes()
        out = self.root / "existing"
        out.mkdir()
        unrelated = self.write("existing/keep.txt", "不应改动")
        proc = self.render(out / "article.html", "--sheet")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.article.read_bytes(), source)
        self.assertEqual(unrelated.read_text(), "不应改动")

    def test_final_rerender_discovers_covers_created_after_preview(self):
        out = self.root / "out"
        out.mkdir()
        target = out / "article.html"
        initial = self.render(target)
        self.assertEqual(initial.returncode, 0, initial.stderr)
        self.assertFalse((out / "sheet.html").exists())
        for name in ("cover.png", "cover-square.png", "cover-thumb.png"):
            write_test_png(out / name)
        final = self.render(target, "--sheet")
        self.assertEqual(final.returncode, 0, final.stderr)
        parser = SheetParser()
        parser.feed((out / "sheet.html").read_text())
        self.assertEqual(parser.cover_sources,
                         ["cover.png", "cover-square.png", "cover-thumb.png"])
        self.assertNotIn("还没生成", (out / "sheet.html").read_text())

    def test_missing_covers_explain_snapshot_refresh_and_output_location(self):
        out = self.root / "out"
        out.mkdir()
        proc = self.render(out / "article.html", "--sheet")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        sheet = (out / "sheet.html").read_text()
        self.assertIn("刷新浏览器不会重新生成工作台", sheet)
        self.assertIn("同目录", sheet)
        self.assertIn("--sheet", sheet)

    def test_rerender_updates_existing_sheet_metadata_and_body(self):
        out = self.root / "out"
        out.mkdir()
        target = out / "article.html"
        proc = self.render(target, "--sheet")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.article.write_text(ARTICLE.replace("普通文章", "最终标题")
                                .replace("这是已经定稿的正文。", "这是最终正文。"), encoding="utf-8")
        proc = self.render(target, "--sheet")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        sheet = (out / "sheet.html").read_text()
        self.assertIn("最终标题", sheet)
        self.assertIn("这是最终正文。", sheet)
        self.assertNotIn("这是已经定稿的正文。", sheet)

    def test_four_themes_generate_consistent_final_sheet_and_body(self):
        for theme in ("tech", "growth", "minimal", "elegant"):
            with self.subTest(theme=theme):
                target = self.root / theme / "article.html"
                proc = self.render(target, "--sheet", "-t", theme)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                body = target.with_name("article.body.html").read_text()
                parser = SheetParser()
                parser.feed(target.with_name("sheet.html").read_text())
                self.assertEqual("".join(parser.article_parts), body)
                checked = self.run_script("check.py", self.article,
                                          "--html", target.with_name("article.body.html"),
                                          "--strict")
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)


class DeliveryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    def section(self, start, end):
        return self.skill.split(start, 1)[1].split(end, 1)[0]

    def test_quick_start_keeps_both_strict_gates(self):
        quick = self.section('## 快速开始', '## 写文章前')
        commands = [line for line in quick.splitlines() if line.startswith('python3 scripts/')]
        for script in ('check.py', 'lint.py'):
            relevant = [line for line in commands if 'scripts/' + script in line]
            self.assertTrue(relevant)
            self.assertTrue(all('--strict' in line for line in relevant))
        last_render = quick.rindex('python3 scripts/md2wx.py')
        self.assertIn('python3 scripts/check.py', quick[last_render:])

    def test_final_self_checks_are_scoped_to_requested_task(self):
        final = self.section('### Step 7', '## 发布到公众号')
        self.assertIn('按任务范围自检', final)
        self.assertIn('仅排版不要求三档封面', final)
        self.assertIn('恢复源稿', final)
        self.assertIn('本地图片', final)

    def test_quick_start_generates_cover_before_sheet(self):
        quick = self.section("## 快速开始", "## 写文章前")
        self.assertLess(quick.index("python3 scripts/cover.py"),
                        quick.index("python3 scripts/md2wx.py"))

    def test_preview_step_defers_sheet_until_final_delivery(self):
        preview = self.section("### Step 4", "### Step 5")
        self.assertNotIn("--sheet", preview)
        final = self.section("### Step 7", "## 发布到公众号")
        self.assertIn("python3 scripts/md2wx.py article.md --sheet -o out/article.html", final)
        self.assertIn("重新生成", final)
        self.assertIn("缺失项", final)

    def test_task_routing_precedes_full_creation_intake(self):
        entry = self.section("## 工作流", "### Step 0")
        for mode in ("完整创作", "仅排版", "仅封面", "仅体检"):
            self.assertIn(mode, entry)
        self.assertIn("仅排版", entry)
        self.assertIn("Step 4", entry)
        self.assertIn("Step 6", entry)
        self.assertIn("只补当前任务必要信息", entry)
        self.assertIn("不得重写已定稿正文或已有标题", entry)

    def test_partial_delivery_does_not_require_full_creation_artifacts(self):
        final = self.section("### Step 7", "## 发布到公众号")
        self.assertIn("局部任务只交付请求的产物", final)
        self.assertIn("不要求补齐封面、素材卡或大纲", final)
        self.assertIn("不能把局部检查当成完整发布验收", final)


if __name__ == "__main__":
    unittest.main()
