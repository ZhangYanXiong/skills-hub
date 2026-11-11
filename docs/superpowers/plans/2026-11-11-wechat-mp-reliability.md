# wechat-mp 关键修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 修复已复现的事实保护、发布检查和素材丢失/覆盖问题。

**Architecture:** 沿用标准库脚本、JSON 规则和按需引用文档。测试通过真实函数与 CLI 检查失败场景，不新增运行依赖；文档契约用静态回归检查，行为判断交给最终审查，不把静态检查称为 Agent benchmark。

**Tech Stack:** Python 3.9+、unittest、argparse、JSON、Markdown。

## Global Constraints

- 不修改已有 demo-output、lint.py、主题、封面或 L3 实现。
- 不安装依赖、不获取凭证、不上传、不发布。
- 非 Git 工作目录，不提交、不推送。
- title/title_short/summary 必填；现有规则上限分别为 64/20/120 字。
- 原有 build_report 参数保持兼容，末尾新增 meta=None。
- 文档中的授权不明和出处不明必须暂停/补证据/排除，不能换身份或改量级绕过。

---

### Task 1: 写失败回归用例

**状态：已完成。** 旧实现运行 32 个测试方法，出现 42 个预期断言失败，无测试加载错误。后续补充空 CLI 覆盖的失败用例，并增加大小写命名兼容测试。

**Files:**
- Create: `wechat-mp/tests/test_check.py`
- Create: `wechat-mp/tests/test_ingest.py`
- Create: `wechat-mp/tests/test_policy.py`

**Interfaces:**
- Consumes: check.build_report、check.main、ingest.extract_facts、ingest.main 和现有引用文档。
- Produces: 标准库 unittest 回归套件。

- [x] 为标题/摘要风险、三项必填/长度、元信息代码标记、覆盖参数和缺失 HTML 写真实函数/CLI 测试。核心断言：
  ```python
  self.assertEqual(proc.returncode, 1)
  self.assertGreater(report['counts']['high'], 0)
  ```
- [x] 为共同句首但数据不同、长句数据、超过 80 条素材和同名文件写用例。核心断言：
  ```python
  self.assertEqual(len(facts), 2)
  self.assertIn('成本200元', facts[1]['text'])
  self.assertNotEqual(results[0]['产出'], results[1]['产出'])
  ```
- [x] 为保留出处/许可与人工复核写契约检查，用原有危险语句导致失败。
- [x] 运行 `python3 -I -B -m unittest discover -s wechat-mp/tests -v`，记录具体失败，区分预期失败和测试错误。

### Task 2: 修复最小实现与指令

**状态：已完成。** 最终 36 个回归测试通过；保留正文的既有行号口径，修正测试对 frontmatter 后空行的预期。独立代码复核提出多行字段变体与 Unicode 规范等价名称覆盖两项问题，均先独立复现，再补失败测试并修复。

**Files:**
- Modify: `wechat-mp/scripts/check.py`
- Modify: `wechat-mp/scripts/ingest.py`
- Modify: `wechat-mp/SKILL.md`
- Modify: `wechat-mp/references/writing-playbook.md`
- Modify: `wechat-mp/references/ingest.md`
- Modify: `wechat-mp/references/compliance.md`

**Interfaces:**
- Consumes: 已失败的回归用例与现有 compliance.json limits。
- Produces: 带 field 定位的 findings、唯一的摄入输出路径、明确的来源/许可/人工复核契约。

- [x] 提取字段长度和必填检查，元信息独立扫描。以附加参数兼容原有调用：
  ```python
  def build_report(md, title, summary, rules, html_path=None, meta=None):
      metadata = dict(meta or {})
      metadata.update(title=title, summary=summary)
  ```
- [x] findings 去重加入 field；显示来源字段；显式缺失 HTML 产生 high。
- [x] 候选句按全文去重且保存全文，默认不截断数量。
- [x] 预分配所有输出名：唯一原名优先保留；重复来源用扩展名，碰撞时递增 `_2`、`_3`，跳过已保留名字。
- [x] 修改文档中的来源/授权出口、许可丢弃、精度互换和涉密改写出口；同步 strict 与人工复核说明。
- [x] 重新运行完整回归套件，任何失败先定位原因，不扩大功能范围。

### Task 3: 验证与复核

**状态：已完成。** 最终全量回归 36/36 通过；四套主题渲染和 strict 体检通过，11 个脚本/测试文件通过 Python 3.9 语法解析。独立文档复核在指定范围未发现剩余危险出口；代码复核提出的两项边界问题已通过新增回归验证修复。已有两篇演示稿只读体检通过 strict，未修改演示文件。非 Git 工作目录，没有提交或推送。

**Files:**
- Test: `wechat-mp/tests/test_check.py`
- Test: `wechat-mp/tests/test_ingest.py`
- Test: `wechat-mp/tests/test_policy.py`
- Create: `wechat-mp/tests/README.md`

**Interfaces:**
- Consumes: Task 2 修复后的 CLI 与文档。
- Produces: 可复制的测试命令、验证范围与限制。

- [x] 四套主题在临时目录输出并检查正文 HTML；示例文运行 check --strict 应通过。
- [x] 验证失败场景 strict 返回 1、无 strict 返回 0 但仍报告 high。
- [x] 用 Python AST 检查脚本/测试语法，并检查新增代码满足 Python 3.9 语法。
- [x] 只读审查本轮修改，修复确认属于本轮的缺陷并补失败测试。
- [x] README 记录测试命令和不覆盖的微信实机、法律裁定、Office/Pillow、Agent 输出质量范围。
