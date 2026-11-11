"""指令的静态契约检查，不等价于 Agent 行为 benchmark 或法律审核。"""

import unittest

from support import SKILL_ROOT


class SourcePolicyTests(unittest.TestCase):
    def read_reference(self, name):
        return (SKILL_ROOT / "references" / name).read_text(encoding="utf-8")

    def test_external_views_cannot_be_relabelled_as_personal_observation(self):
        policy = self.read_reference("writing-playbook.md")
        self.assertNotIn("无法给出处时写成自己的观察", policy)
        self.assertIn("出处不明", policy)
        self.assertIn("补来源或排除", policy)

    def test_unknown_authorization_cannot_be_bypassed_by_rounding(self):
        policy = self.read_reference("writing-playbook.md")
        self.assertNotIn("不确定就改成量级描述", policy)
        self.assertIn("授权不明", policy)
        self.assertIn("暂停使用", policy)
        self.assertIn("脱敏、改量级不能替代授权", policy)

    def test_license_and_disclaimer_constraints_are_retained(self):
        policy = self.read_reference("ingest.md")
        self.assertNotIn("| 免责声明、版权声明 | 与正文无关 |", policy)
        self.assertIn("许可与限制", policy)
        self.assertIn("署名要求", policy)
        self.assertIn("授权状态", policy)

    def test_exact_values_are_not_silently_made_approximate(self):
        policy = self.read_reference("ingest.md")
        self.assertNotIn("可以写「约 45 分钟」", policy)
        self.assertIn("精确值与近似值不互换", policy)

    def test_sensitive_information_is_not_released_by_anonymization(self):
        policy = self.read_reference("compliance.md")
        self.assertNotIn("| 涉密单位、政务系统操作细节 | 保密义务 | 抽象为「某内部系统」", policy)
        self.assertIn("改写或脱敏不能解除保密义务", policy)
        for state in ("待复核", "确认误报", "完成修订", "拒绝发布"):
            self.assertIn(state, policy)

    def test_main_skill_distinguishes_scan_from_human_release(self):
        policy = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("0 个未解决高风险", policy)
        self.assertIn("扫描通过不等于允许发布", policy)
        self.assertIn("title_short", policy)


if __name__ == "__main__":
    unittest.main()
