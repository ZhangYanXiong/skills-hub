# skills-hub · 内容制作技能

这是一个可复用的内容制作 skill 仓库。**找技能看 `skills/`，找作品看 `outputs/`，找开发记录看 `docs/`。**

## 从这里开始

| 技能 | 用途 | 给人看的说明 | 给 Agent 的规则 |
| --- | --- | --- | --- |
| article-video | 文章 → 2–3分钟竖屏动态图文视频 | [使用说明](skills/article-video/README.md) | [SKILL.md](skills/article-video/SKILL.md) |
| wechat-mp | 公众号写作、排版、封面及交付 | [使用说明](skills/wechat-mp/README.md) | [SKILL.md](skills/wechat-mp/SKILL.md) |

## 目录导航

```text
skills-hub/
├── README.md          总导航
├── CLAUDE.md          仓库目录及协作约定
├── skills/            技能源码、使用说明、模板与测试
├── outputs/           已生成的作品，按技能和日期主题分类
├── workspaces/        临时制作、调试和技能行为评估
├── docs/              按技能分类的设计、计划和验收记录
└── .claude/           项目工具配置与skill注册链接
```

- [技能目录](skills/README.md)：新增或修改一个 skill 从这里开始。
- [作品目录](outputs/README.md)：找到视频、公众号成品和历史演示。
- [临时工作区说明](workspaces/README.md)：区分中间实验与可交付成品。
- [开发文档](docs/README.md)：按技能查设计和验收，不再按开发工具分类。
- [目录迁移记录](docs/repository/reports/2026-11-12-directory-layout-verification.md)：旧位置与新位置对照、保留范围和检查结果。

## 当前示例

- **文章转视频**：[作品入口](outputs/article-video/README.md)。示例《提示词不是越长越好》约2分5秒，1080×1920、30fps；使用明确标注的本地演示配音。视频是本机生成产物，不随git分发，其他机器按使用说明重新生成。
- **公众号**：[作品入口](outputs/wechat-mp/README.md)。保留首次正式验收、周报复盘、数字人协同办公、素材摄入、交付流程及CRUD接口示例。

## 使用与维护约定

所有命令示例默认在仓库根目录执行。源码路径统一为 `skills/<技能名>/`；正式作品建议使用 `outputs/<技能名>/YYYY-MM-DD-主题/`，临时实验放 `workspaces/<任务名>/`。

`.claude/skills/` 只放指向技能源码的链接，不复制另一份实现。两项技能的说明和全部操作步骤都在自己的目录中，根README只负责导航。

在线配音需要独立外发与费用批准；没有音频或真实MP4时只能交付制作包。不自动发布，不在项目或聊天中保存密钥。
