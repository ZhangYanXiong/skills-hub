# wechat-mp 全问题修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** 关闭新版评估问题并主动复核、处理新增发现。

**Architecture:** wxbuild 统一清单、指纹上下文、快照和验证；lint 保留写作规则并委托产物校验。保持现有 CLI。

**Tech Stack:** Python 3.9+ 标准库、unittest、Markdown。

## Global Constraints

不安装、不修改原演示稿、不访问或发布微信、不提交。真实 CLI 测试使用临时目录。局部任务不被强制扩展为完整发布。

**当前状态：** 已完成修复、独立复核新增问题闭环及最终验收。全量 149/149；真实 CLI 16 步全部符合预期；16 个脚本/测试文件通过 Python 3.9 语法解析，实际运行 Python 3.13.15。覆盖完整交付、实际参数、改稿/换图阻断、源稿/图片/封面回退、局部 no-body 和 stdin 回退。验收报告见 `docs/wechat-mp/reports/2026-11-11-wechat-mp-verification.md`；微信、图片完整解码、授权事实及 Python 3.9 运行时未验证。

## Task 1: 写作闸门

**Files:** scripts/lint.py、tests/test_lint.py（均在 skills/wechat-mp/）。
**Interfaces:** 保留 build_report/article CLI；lint_artifacts 最后委托 wxbuild.validate_artifacts(out_dir, raw, meta)。

- [x] 加失败用例：30万人/30万元、正负百分比、小数等价、空卡但有引用、重排列空出处、混合/嵌套围栏、加粗主论点、短中文判断、标点套话、中文支撑编号。
- [x] 真实 CLI 验证失败来自原行为。
- [x] 修解析与判定，保留未传 cards 的正常降级及有出处 F 卡数字支持。
- [x] 运行 test_lint.py，补修测试发现；现有与新增写作及产物测试均纳入全量通过。

## Task 2: 清单和快照

**Files:** scripts/wxmeta.py、scripts/md2wx.py、新 scripts/wxbuild.py、新 tests/test_build.py。
**Interfaces:** fingerprint(md, theme, images=None, options=None, asset_hashes=None)；wxbuild.validate_artifacts(out_dir, raw, meta) -> findings；生成器调用共享构建上下文与清单函数。

- [x] 失败用例检查声明文件丢失/篡改、合法主题覆盖、损坏清单、标题选项与图片字节改变指纹、完整回退、快照不可覆盖、回退失败不改文件、危险路径、旧版输出清理及 no-body/check 兼容。
- [x] 创建 schema 2，每项产物使用完整 SHA256，所有声明路径做输出根目录限制。
- [x] 快照保存源稿/资产/产物；先完整验证，再恢复。
- [x] 真实 CLI 重跑新增与旧交付测试。

## Task 3: 文档与复核闭环

**Files:** SKILL.md、tests/README.md、tests/test_delivery.py。

- [x] 恢复快速开始双 strict；最终渲染后再检查。
- [x] 自检限定请求范围，明确完整快照内容与回退影响。
- [x] 独立复核实现与测试；确认发现先补失败测试再修。
- [x] 全量 unittest 与 Python3.9语法解析；真实交付/主题覆盖/快照回退验收。
- [x] 更新实测结果和剩余人工验收边界。
