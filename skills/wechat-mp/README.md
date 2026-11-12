# wechat-mp · 公众号内容工厂

把「稿子写完」到「能在公众号发出去」之间那些手工活自动化：**排版、配图、合规体检、交付工作台**。

写作本身交给模型；这个 skill 负责让一篇稿子**发得出去、发得好看、不踩雷**。

> 这是一个 **agent skill**：入口是 [`skills/wechat-mp/SKILL.md`](SKILL.md)，执行者按里面的工作流调用
> `skills/wechat-mp/scripts/` 下的脚本。人也可以直接跑这些脚本。

---

## 目录结构

```
skills-hub/
├── skills/wechat-mp/                # skill 本体
│   ├── SKILL.md              # 入口：任务分支 + 9 步工作流 + 硬性标准
│   ├── scripts/              # 8 个脚本（多为纯标准库）
│   │   ├── md2wx.py          # Markdown → 公众号内联样式 HTML + 发布工作台
│   │   ├── wxbuild.py        # 构建清单 / 指纹 / 快照 / 回退 / 封面校验
│   │   ├── wxmeta.py         # frontmatter 解析、字数统计、默认署名等共享工具
│   │   ├── cover.py          # 封面三档生成（900×383 / 1080×1080 / 200×200）
│   │   ├── check.py          # 发布体检（合规词 / 长度 / 外链 / 图片域名 / HTML 兼容）
│   │   ├── lint.py           # 写作闸门（引用 / 数字出处 / 论点 / 产物版本 / 封面）
│   │   ├── ingest.py         # 素材摄入（PDF/docx/pptx/网页 → 结构化文本）
│   │   └── preview.py        # 用 Chrome 截图，确认排版
│   ├── references/           # 6 份方法论，按需加载
│   ├── examples/             # 示例稿
│   └── tests/                # 150 个回归测试 + 交付验收脚本
├── outputs/wechat-mp/              # 端到端演示 + 首次正式验收
├── docs/wechat-mp/           # 设计、计划与验收记录
└── .claude/launch.json       # 本地起 http.server 预览工作台
```

---

## 快速开始

在**仓库根目录**执行（脚本内部按自身位置找主题与规则，跨目录可用）：

```bash
# 1. 有素材文件时先摄入（PDF / docx / pptx / 网页）
python3 skills/wechat-mp/scripts/ingest.py 素材.pdf -o outputs/wechat-mp/my-article/ingest

# 2. 生成封面 —— 公众号发布必填，不是可选项
python3 skills/wechat-mp/scripts/cover.py --md 稿子.md --all -o outputs/wechat-mp/my-article

# 3. 先出预览页（此步不生成工作台）
python3 skills/wechat-mp/scripts/md2wx.py 稿子.md -o outputs/wechat-mp/my-article/article.html

# 4. 双重体检：改稿发现问题就回到第 3 步
python3 skills/wechat-mp/scripts/lint.py 稿子.md --cards outputs/wechat-mp/my-article/素材卡.md --outline outputs/wechat-mp/my-article/大纲.md --strict
python3 skills/wechat-mp/scripts/check.py 稿子.md --html outputs/wechat-mp/my-article/article.body.html --strict

# 5. 全部通过后，最后生成发布工作台并打快照
python3 skills/wechat-mp/scripts/md2wx.py 稿子.md --sheet --snapshot -o outputs/wechat-mp/my-article/article.html

# 6. 交付前终检：产物必须等于当前源稿，且三档封面齐全
python3 skills/wechat-mp/scripts/lint.py 稿子.md --out outputs/wechat-mp/my-article --publish --strict
```

**顺序很重要**：工作台是快照，提前生成会在改稿后变成旧版本，第 6 步会直接拦下来。

## 脚本一览

| 脚本 | 做什么 | 关键参数 |
| --- | --- | --- |
| `md2wx.py` | Markdown → 公众号 HTML、正文片段、发布工作台 | `--sheet`、`--snapshot`、`-t`、`-o`、`--check`、`--list-builds`、`--rollback` |
| `wxbuild.py` | 构建清单与校验（被其它脚本调用） | — |
| `cover.py` | 封面三档生成 | `--md`、`--all`、`--style`、`--tag`、`--author` |
| `check.py` | 发布体检 | `--html`、`--json`、`--strict` |
| `lint.py` | 写作闸门 + 产物版本 + 封面 | `--cards`、`--outline`、`--out`、`--publish`、`--strict` |
| `ingest.py` | 素材摄入 | `-o`、`--json` |
| `preview.py` | 排版截图 | `-o`、`--width`、`--height` |

标题、摘要、作者、主题都从 Markdown 开头的 frontmatter 读，**只写一次**：

```markdown
---
title: 长标题，≤64 字
title_short: 短标题，≤20 字（信息流展示用）
summary: 摘要，≤120 字
author: 云光迷途          # 不写则默认「云光迷途」
tag: 技术拆解             # 封面左上角标签
theme: tech               # tech / growth / minimal / elegant
---
```

---

## 四条核心设计

**1. 只输出内联样式。**
微信编辑器会丢弃 `<style>`、`class` 和外部 CSS，所以每个标签都自带 `style`，
容器统一用 `<section>`。根 `<section>` 承载字体/字号/行距，靠继承生效——复制到编辑器不会掉字体。

**2. 交付物带构建指纹。**
指纹 = `渲染代码哈希 + 源稿全文 + 合并后的主题 + 本地图片`。写进 `article.html` 和
`sheet.html` 的 `<meta>`，并落一份 `build.json`。

它的作用不是记录版本号，而是**让机器拒绝交付旧东西**：改了稿没重跑，`lint --out` 直接报「必须修」。
`article.body.html` 保持纯净不带标记（它要粘进微信），改由 `build.json` 的摘要旁路校验。

**3. 双重闸门，各管一段。**

| 闸门 | 管什么 | 什么时候跑 |
| --- | --- | --- |
| `lint.py` | 引用有没有空号、数字有没有出处、论点挂没挂素材、产物是不是当前源稿、封面齐不齐 | 大纲定稿、正文定稿、交付前 |
| `check.py` | 广告法极限词、诱导行为、标题/摘要长度、外链、图片域名、HTML 兼容 | 发布前 |

两个都支持 `--strict`（有硬问题时退出码 1），可以进 CI。

**4. 封面和图片是发布硬约束。**
公众号头条封面是后台必填项；正文图片在粘贴时**不会被带过去**（微信编辑器只接文字和样式）。
发布工作台因此提供「正文图片」清单：缩略图 + 序号 + 一键复制，把「凭记忆逐张找」变成「照清单点」。

---

## 公众号硬约束（写稿前就该知道）

| 约束 | 数值 | 后果 |
| --- | --- | --- |
| 标题长度 | ≤64 字 | 超出无法保存 |
| 信息流展示 | 约 20 字后截断 | 必须有短标题版本 |
| 摘要 | ≤120 字 | 超出无法保存 |
| 头条封面 | 900×383（2.35:1）必填 | 没有封面发不出去 |
| 正文外链 | 非微信域名不可点 | 改成文字描述或放「阅读原文」 |
| 正文图片 | 必须已在微信素材库 | 粘贴不会自动上传本地图片 |
| 扫描版 PDF | 无文字层 | 需先 OCR，`ingest.py` 会明确报错 |

---

## 测试

```bash
# 150 个回归测试（纯标准库）
python3 -I -B -m unittest discover -s skills/wechat-mp/tests -v

# 临时目录真实 CLI 验收，输出 JSON 汇总
python3 -I -B skills/wechat-mp/tests/verify_delivery.py
```

覆盖：`check.py` 合规与长度、`ingest.py` 多源与命名碰撞、`md2wx.py` 输出目录/主题/工作台、
`wxbuild.py` 指纹/快照/回退/封面校验、`lint.py` 全部闸门规则、以及 SKILL.md 的文档契约。

> **注意**：`test_policy.py` / `test_delivery.py` 里的路由与流程检查是**静态契约检查**——
> 它们防止文档规则被改坏，但不证明 Agent 在真实执行时一定遵守。Agent 行为没有自动化度量。

## 演示与验收

六组历史示例和阅读入口见 [作品导航](../../outputs/wechat-mp/README.md)。它们保留原生成记录，搬目录不等于重新制作；历史回执的旧绝对路径保持原样。

| 目录 | 内容 |
| --- | --- |
| [`outputs/wechat-mp/2026-11-11-首次正式验收/`](../../outputs/wechat-mp/2026-11-11-首次正式验收) | **首次正式验收**：话题「AI 给人带来的焦虑」，含验收报告、选题大纲、成品与体检报告 |
| [`outputs/wechat-mp/2026-11-11-周报复盘/`](../../outputs/wechat-mp/2026-11-11-周报复盘) | 职场成长类：周报复盘（配图 + growth 主题） |
| [`outputs/wechat-mp/2026-11-11-数字人协同办公/`](../../outputs/wechat-mp/2026-11-11-数字人协同办公) | 观点类：数字人协同办公（minimal 主题） |
| [`outputs/wechat-mp/2026-11-11-素材摄入演示/`](../../outputs/wechat-mp/2026-11-11-素材摄入演示) | 素材摄入演示：html/pdf/docx/pptx 四格式 → 素材卡 → 选题大纲 |
| [`outputs/wechat-mp/2026-11-11-交付流程演示/`](../../outputs/wechat-mp/2026-11-11-交付流程演示) | 交付流程演示：带构建清单与快照 |

看效果最直接的方式：浏览器打开某个目录下的 `sheet.html`（发布工作台）或 `article.html`（排版预览）。

---

## 环境与依赖

| 依赖 | 用途 | 缺失时 |
| --- | --- | --- |
| Python 3.9+ | 全部脚本（已用 AST 校验 3.9 语法） | 必须 |
| Pillow | `cover.py` 生成封面 | 封面这一步失败，其余可用 |
| Chrome / Chromium / Edge | `preview.py` 截图 | 跳过截图，直接开 HTML 看 |
| pypdf | `ingest.py` 解析 PDF | 已 vendored 到 `scripts/vendor`，无需另装 |
| python-docx / python-pptx | `ingest.py` 解析 docx/pptx | 只影响对应格式 |

`md2wx.py`、`check.py`、`lint.py`、`wxbuild.py` **纯标准库**。

## 文档索引（按需要读，不必全读）

| 文档 | 什么时候读 |
| --- | --- |
| [`SKILL.md`](SKILL.md) | **入口**：任务分支、9 步工作流、硬性标准 |
| [`references/ingest.md`](references/ingest.md) | 素材怎么提炼成可引用的素材卡 |
| [`references/topic-expand.md`](references/topic-expand.md) | 一句话话题怎么长成不注水的大纲 |
| [`references/writing-playbook.md`](references/writing-playbook.md) | 标题公式、开头钩子、结构模板、去 AI 味 |
| [`references/compliance.md`](references/compliance.md) | 极限词、违规类型、替代表述 |
| [`references/layout-spec.md`](references/layout-spec.md) | 排版规范、主题字段、怎么加主题 |
| [`references/api.md`](references/api.md) | L3 草稿箱接口契约（未实现） |

---

## 已知限制

- **L3 自动发布未实现**。需要已认证账号的 AppID + AppSecret；未认证订阅号拿不到开发者权限。
  接口契约见 [`references/api.md`](references/api.md)。
- **正文图片仍需手动上传**。没有 API 就无法把图片送进微信服务器，只能靠工作台清单降低漏图概率。
- **Agent 行为没有度量**。测试保证脚本契约与文档规则，不保证模型每次都按流程走。
- **中文数字识别偏宽**。`lint.py` 会把「一条」「三个月」这类普通量词也列进数据提示，
  正常稿子会带几条噪音提示，需人工忽略。

## 维护注意

- **改完脚本必须重新渲染**。`md2wx.py` / `wxmeta.py` / `wxbuild.py` 的哈希进了指纹，
  代码一改，旧产物立刻被判「旧版本」——这是设计生效，不是故障。
- 主题加一个 JSON 即可，不用改代码；字段说明见 `references/layout-spec.md` §13。
- 默认署名「云光迷途」在 `scripts/wxmeta.py` 的 `DEFAULT_AUTHOR`；frontmatter 或 `--author` 可覆盖。
