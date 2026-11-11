"""素材候选句与多源输出不能丢失证据的回归测试。"""

import json
import unittest

from support import WorkspaceTest
import ingest


class FactRegressionTests(unittest.TestCase):
    def test_same_prefix_with_different_values_keeps_both_sentences(self):
        prefix = "本次项目统计采用完全一致的统计口径并且经过项目团队核对所用指标与时间范围均相同"
        facts = ingest.extract_facts(prefix + "，成本100元。\n" + prefix + "，成本200元。")
        self.assertEqual(len(facts), 2)
        self.assertEqual([f["line"] for f in facts], [1, 2])
        self.assertIn("成本200元", facts[1]["text"])
        self.assertEqual(len(ingest.collect_values(facts)), 2)

    def test_long_sentences_keep_values_after_160_characters(self):
        sentence = "本次统计范围需要按照项目实际情况逐项核对" * 12 + "，成本200元。"
        facts = ingest.extract_facts(sentence)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["text"], sentence)
        self.assertTrue(any(v["raw"] == "200元" for v in ingest.collect_values(facts)))

    def test_default_extraction_does_not_silently_stop_at_80(self):
        text = "\n".join("第%d个项目成本%d元。" % (i, i) for i in range(1, 91))
        facts = ingest.extract_facts(text)
        self.assertEqual(len(facts), 90)
        self.assertIn("第90个项目", facts[-1]["text"])

    def test_exact_duplicates_are_still_deduplicated(self):
        facts = ingest.extract_facts("项目成本100元。\n项目成本100元。")
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["line"], 1)

    def test_whitespace_that_changes_the_source_is_not_discarded(self):
        facts = ingest.extract_facts("报告称公司A B成本100元。\n报告称公司AB成本100元。")
        self.assertEqual(len(facts), 2)

    def test_explicit_limit_remains_supported(self):
        facts = ingest.extract_facts("项目成本100元。\n项目成本200元。", limit=1)
        self.assertEqual(len(facts), 1)


class MultiSourceRegressionTests(WorkspaceTest):
    def ingest_files(self, sources):
        paths = [self.write(name, text) for name, text in sources]
        out = self.root / "ingest"
        proc = self.run_script("ingest.py", *paths, "-o", out, "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads(proc.stdout), out

    def assert_preserved_sources(self, results, expected):
        outputs = [tuple(r["产出"]) for r in results]
        self.assertEqual(len(set(outputs)), len(expected))
        for result, text in zip(results, expected):
            with open(result["产出"][0], encoding="utf-8") as fh:
                self.assertEqual(fh.read(), text)

    def test_same_name_same_format_from_different_directories_is_preserved(self):
        sources = [("a/report.md", "来源甲：成本100元。"),
                   ("b/report.md", "来源乙：成本200元。")]
        results, _ = self.ingest_files(sources)
        self.assert_preserved_sources(results, [text for _, text in sources])

    def test_three_collisions_and_natural_suffix_names_are_preserved(self):
        sources = [("a/report.md", "来源甲：成本100元。"),
                   ("b/report.md", "来源乙：成本200元。"),
                   ("c/report.md", "来源丙：成本300元。"),
                   ("report_md.md", "自然名称：成本400元。"),
                   ("report_md_2.md", "自然后缀：成本500元。")]
        results, _ = self.ingest_files(sources)
        self.assert_preserved_sources(results, [text for _, text in sources])
        self.assertTrue(results[3]["产出"][0].endswith("report_md.clean.txt"))
        self.assertTrue(results[4]["产出"][0].endswith("report_md_2.clean.txt"))

    def test_case_only_names_do_not_collide_on_case_insensitive_filesystems(self):
        sources = [("a/Report.md", "来源甲：成本100元。"),
                   ("b/report.md", "来源乙：成本200元。")]
        results, _ = self.ingest_files(sources)
        self.assert_preserved_sources(results, [text for _, text in sources])
        names = [r["产出"][0].casefold() for r in results]
        self.assertEqual(len(set(names)), 2)

    def test_unicode_equivalent_names_are_preserved_without_overwriting(self):
        sources = [("a/café.md", "来源甲：成本100元。"),
                   ("b/café.md", "来源乙：成本200元。")]
        results, _ = self.ingest_files(sources)
        self.assert_preserved_sources(results, [text for _, text in sources])

    def test_same_stem_different_formats_stay_distinct(self):
        sources = [("report.md", "Markdown来源：成本100元。"),
                   ("report.txt", "纯文本来源：成本200元。")]
        results, _ = self.ingest_files(sources)
        self.assert_preserved_sources(results, [text for _, text in sources])
        self.assertTrue(results[0]["产出"][0].endswith("report_md.clean.txt"))
        self.assertTrue(results[1]["产出"][0].endswith("report_txt.clean.txt"))

    def test_single_source_filename_remains_unchanged(self):
        results, _ = self.ingest_files([("report.md", "项目成本100元。")])
        self.assertTrue(results[0]["产出"][0].endswith("report.clean.txt"))

    def test_index_records_distinct_full_source_paths(self):
        sources = [("a/report.md", "来源甲：成本100元。"),
                   ("b/report.md", "来源乙：成本200元。")]
        results, out = self.ingest_files(sources)
        index = (out / "index.md").read_text(encoding="utf-8")
        for result in results:
            self.assertIn(result["文件"], index)


if __name__ == "__main__":
    unittest.main()
