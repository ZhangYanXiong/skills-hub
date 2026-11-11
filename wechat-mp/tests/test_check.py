"""发布检查的元信息、返回码与既有行为回归测试。"""

import json
import unittest

from support import SKILL_ROOT, WorkspaceTest
import check


VALID_META = {
    "title": "一篇普通文章",
    "title_short": "普通文章",
    "summary": "介绍具体做法与适用范围。",
}


class CheckRegressionTests(WorkspaceTest):
    def check_article(self, meta=None, body="这是普通正文。", strict=True, extra=()):
        fields = VALID_META if meta is None else meta
        header = "\n".join("%s: %s" % item for item in fields.items())
        path = self.write("article.md", "---\n%s\n---\n\n%s\n" % (header, body))
        args = [path, "--json"]
        if strict:
            args.append("--strict")
        proc = self.run_script("check.py", *args, *extra)
        self.assertIn(proc.returncode, (0, 1), proc.stderr)
        return proc, json.loads(proc.stdout)

    def assert_blocked_field(self, proc, report, field):
        self.assertEqual(proc.returncode, 1, report)
        self.assertTrue(
            any(f["severity"] == "high" and f.get("field") == field
                for f in report["findings"]),
            report,
        )

    def test_valid_metadata_passes(self):
        proc, report = self.check_article()
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(report["counts"]["high"], 0)

    def test_risk_in_each_visible_metadata_field_is_scanned(self):
        for field in ("title", "title_short", "summary", "cover_title", "author", "tag"):
            with self.subTest(field=field):
                meta = dict(VALID_META, **{field: "保证包过"})
                proc, report = self.check_article(meta)
                self.assert_blocked_field(proc, report, field)

    def test_inline_code_markers_do_not_hide_metadata_risk(self):
        proc, report = self.check_article(dict(VALID_META, title="`保证包过`"))
        self.assert_blocked_field(proc, report, "title")

    def test_missing_or_blank_required_fields_are_blocked(self):
        for field in ("title", "title_short", "summary"):
            for blank in (None, "", "   "):
                with self.subTest(field=field, blank=blank):
                    meta = dict(VALID_META)
                    if blank is None:
                        del meta[field]
                    else:
                        meta[field] = blank
                    proc, report = self.check_article(meta)
                    self.assert_blocked_field(proc, report, field)

    def test_required_fields_are_blocked_without_frontmatter(self):
        path = self.write("no-meta.md", "# 普通正文\n\n具体内容。\n")
        proc = self.run_script("check.py", path, "--strict", "--json")
        report = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual({f.get("field") for f in report["findings"]
                          if f["severity"] == "high"},
                         {"title", "title_short", "summary"})

    def test_exact_field_limits_pass_and_overflow_is_blocked(self):
        for field, limit in (("title", 64), ("title_short", 20), ("summary", 120)):
            with self.subTest(field=field, size=limit):
                proc, report = self.check_article(dict(VALID_META, **{field: "字" * limit}))
                self.assertEqual(proc.returncode, 0, report)
            with self.subTest(field=field, size=limit + 1):
                proc, report = self.check_article(dict(VALID_META, **{field: "字" * (limit + 1)}))
                self.assert_blocked_field(proc, report, field)

    def test_unsupported_yaml_multiline_values_are_not_valid_metadata(self):
        for marker in ("|", ">", "|-", ">-"):
            with self.subTest(marker=marker):
                proc, report = self.check_article(dict(VALID_META, summary=marker))
                self.assert_blocked_field(proc, report, "summary")

    def test_yaml_multiline_markers_with_comments_and_optional_fields_are_blocked(self):
        for field in ("title", "title_short", "summary", "cover_title", "author", "tag", "theme"):
            for marker in ("| # 摘要", ">- # 摘要", "|2- # 摘要", "|", ">"):
                with self.subTest(field=field, marker=marker):
                    meta = dict(VALID_META, **{field: marker + "\n  保证包过"})
                    proc, report = self.check_article(meta)
                    self.assert_blocked_field(proc, report, field)

    def test_cli_overrides_are_the_final_scan_targets(self):
        proc, report = self.check_article(
            dict(VALID_META, title="保证包过", summary="保证包就业"),
            extra=("--title", "安全标题", "--summary", "安全摘要"),
        )
        self.assertEqual(proc.returncode, 0, report)
        self.assertEqual(report["指标"]["标题"], "安全标题")
        self.assertEqual(report["指标"]["摘要"], "安全摘要")
        proc, report = self.check_article(extra=("--title", "保证包过"))
        self.assert_blocked_field(proc, report, "title")

    def test_explicit_empty_cli_overrides_are_not_replaced_by_old_metadata(self):
        for field, option in (("title", "--title"), ("summary", "--summary")):
            with self.subTest(field=field):
                proc, report = self.check_article(extra=(option, ""))
                self.assert_blocked_field(proc, report, field)

    def test_non_strict_reports_errors_without_failing_exit(self):
        proc, report = self.check_article(dict(VALID_META, title="字" * 65), strict=False)
        self.assertEqual(proc.returncode, 0)
        self.assertGreater(report["counts"]["high"], 0)

    def test_explicit_missing_html_is_blocked(self):
        proc, report = self.check_article(extra=("--html", self.root / "missing.html"))
        self.assertEqual(proc.returncode, 1, report)
        self.assertTrue(any(f["category"] == "HTML 兼容" and f["severity"] == "high"
                            for f in report["findings"]))

    def test_body_code_is_still_masked_and_body_risk_still_blocks(self):
        proc, report = self.check_article(body="```text\n保证包过\n```\n\n这是普通正文。")
        self.assertEqual(proc.returncode, 0, report)
        proc, report = self.check_article(body="普通正文。\n\n保证包过。")
        self.assertEqual(proc.returncode, 1, report)
        # frontmatter 后保留的一行空白属于正文，风险句的正文行号是 4。
        self.assertTrue(any(f.get("field") == "body" and f["line"] == 4
                            for f in report["findings"] if f["severity"] == "high"))

    def test_external_images_remain_medium_and_local_images_low(self):
        for src, severity in (("https://example.com/img.png", "medium"), ("image.png", "low")):
            with self.subTest(src=src):
                proc, report = self.check_article(body="![示意图](%s)" % src)
                self.assertEqual(proc.returncode, 0, report)
                self.assertTrue(any(f["severity"] == severity and "图片" in f["category"]
                                    for f in report["findings"]))

    def test_json_and_text_reports_identify_short_title_and_metadata_field(self):
        path = self.write("article.md", "---\ntitle: 保证包过\ntitle_short: 普通文章\nsummary: 内容摘要\n---\n\n普通正文。\n")
        proc = self.run_script("check.py", path, "--strict")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("title", proc.stdout)
        self.assertIn("短标题", proc.stdout)

    def test_existing_build_report_call_shape_is_supported(self):
        report = check.build_report("普通正文。", "普通标题", "普通摘要", check.load_rules())
        self.assertIn("findings", report)
        self.assertIn("counts", report)

    def test_example_article_passes_release_checks(self):
        proc = self.run_script("check.py", SKILL_ROOT / "examples/sample-article.md", "--strict", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["counts"]["high"], 0)


if __name__ == "__main__":
    unittest.main()
