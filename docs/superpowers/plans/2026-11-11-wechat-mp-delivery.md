# wechat-mp 交付流程 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 在新目录可靠输出，并按最终资产生成工作台，局部请求只走必要步骤。

**Architecture:** 在现有写文件入口创建父目录；工作台沿用 `--sheet` 快照，调整 skill 的生成顺序和任务路由，不添加服务器、自动上传或新参数。

**Tech Stack:** Python 3.9+ 标准库、unittest、Markdown。

## Global Constraints

- 不安装依赖，不修改演示稿，不提交/推送，不登录或发布。
- `--check` 只统计，不创建目录和文件。
- 局部任务不得重写已定稿正文或已有标题。
- 局部任务只交付请求的产物，不冒充完整发布验收。
- 测试 PNG 仅用于文件发现验证，不声称通过 Pillow 或微信实机验收。

---

### Task 1: 失败回归

**状态：已完成。** 新目录输出与旧任务/交付顺序契约在修复前失败，既有目录、只统计无写入等兼容用例通过；补充工作台缺失封面的刷新说明失败用例。最终新增 14 个测试方法。

**Files:** Create `wechat-mp/tests/test_delivery.py`。

**Interfaces:** Consumes 现有 md2wx.py CLI；Produces 标准库 unittest 交付用例。

- [x] 真实 CLI 在新嵌套目录带 `--sheet` 输出，断言 article.html、article.body.html、sheet.html 均存在；在旧实现观察 FileNotFoundError。
  ```python
  self.assertEqual(proc.returncode, 0, proc.stderr)
  self.assertTrue((out.parent / 'sheet.html').is_file())
  ```
- [x] 检查 `--no-body`、`--check` 无写入、已有目录、定稿源文件未变、四主题末次工作台正文一致。
- [x] 检查快速开始的封面命令在首次 `--sheet` 命令之前、Step 4 不生成工作台、Step 7 重新生成工作台，以及四个局部/完整入口的静态契约。
- [x] 运行 `python3 -I -B -m unittest discover -s wechat-mp/tests -p test_delivery.py -v`，确认失败来自旧实现/旧流程，而非测试加载错误。

### Task 2: 最小修复

**状态：已完成。** 目录创建位于输入/主题验证和 `--check` 返回之后；工作台保持静态快照语义，完整流程在 Step 7 生成最终版本。局部任务明确沿用定稿、限定提问和交付范围。

**Files:** Modify `wechat-mp/scripts/md2wx.py`、`wechat-mp/SKILL.md`。

**Interfaces:** Consumes 现有 Markdown/frontmatter；Produces 同名 HTML/正文/最终工作台，不改变 CLI。

- [x] 写文件前创建目录，位置保持在 `--check` 返回之后：
  ```python
  os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
  ```
- [x] 快速开始封面先于工作台；Step 4 生成预览和正文，Step 7 使用 `--sheet` 刷新最终产物。
- [x] 写明确的任务表，完整创作进入 Step 0；仅排版进入 Step 4/6.2/7；仅封面进入 Step 5/请求范围的复核；仅体检进入 Step 6 的相关检查。
- [x] 说明缺失资产/依赖、局部交付范围、后续改动后必须重新生成与复查；保留第一批事实保护和人工终审规则。
- [x] 运行交付测试和完整回归，失败则先定位，不扩大功能范围。

### Task 3: 最终验证

**状态：已完成。** 最终全量回归 50/50 通过，12 个脚本/测试文件通过 Python 3.9 语法解析。独立静态复核在本轮指定范围未发现实质问题。封面文件发现用标准库构造 PNG 验证；当前 Python 缺 Pillow，未重跑真实封面绘制。未验证真实 Agent 路由行为、剪贴板或微信后台；未安装依赖、修改演示稿、提交或发布。

**Files:** Modify `wechat-mp/tests/README.md`。

**Interfaces:** Consumes 修复后的 CLI/指令；Produces 可重复验证说明。

- [x] 用四套主题真实 CLI 在新目录生成最终工作台；检查已存在 PNG 的引用、正文与 body.html 一致、check.py --strict 通过。
- [x] Python 3.9 语法解析新测试与修改脚本。
- [x] 只读复核本轮目录和指令改动，确认无重新引入第一批危险出口。
- [x] README 记录工作台快照的限制、测试资产来源及未验收的真实 Agent/微信后台范围。
