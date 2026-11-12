# 仓库约定

## 目录职责

- `skills/<skill>/`：技能本体。`README.md`给人看，`SKILL.md`给Agent执行；scripts、renderer、references、examples、tests、evals随所属skill组织。
- `outputs/<skill>/YYYY-MM-DD-主题/`：可审阅作品及交付文件。一个作品的原文、素材、声音、字幕、播放器和构建记录保持自包含，不为了分类拆散相对资源路径。命令示例中的my-video等只是示意命名，正式作品采用日期主题名。
- `workspaces/<skill或任务>/`：临时制作、调试、行为评估、迁移清单，不当作已验收作品。除导航README外默认gitignore。
- `docs/<skill>/designs/`、`plans/`、`reports/`：设计、实施计划和真实验收证据。仓库级事项用`docs/repository/`。即使工具默认生成docs/superpowers，也遵循这里的项目路径。
- `.claude/`：项目配置和skill注册链接；不存业务源码，不复制skill目录，不擅自修改用户全局配置。
- 根`README.md`只做导航，详细使用说明归各skill。不要在根目录新建demo-output、article-video-output、article-video-workspace或out等并列杂项目录。

## 修改与交付

- 使用简体中文说明和注释；保留技术标识符原名。
- 不经用户要求，不commit、push、建PR或发布内容。
- 目录移动前核对来源与目标，不覆盖已有项目，不删除既有作品、快照或历史回执。
- 历史回执如有旧绝对路径，保留其证据语义，不批量替换路径/摘要冒充当前构建。需要新版本时明确执行当前制作和验收流程。
- 修改路径时同步命令示例、文档链接、测试fixture、.claude/launch.json及skill符号链接；复核发现确认问题同轮修复并复测。
- 制作包、历史演示、本地演示配音、在线成品分开标注；来源对应不等于外部事实核查。
- 外发文章、在线费用、发布、声音克隆均不由整理或创作批准自动授权；不把密钥写入源码、产物或聊天。

## 验证入口

命令默认从仓库根目录运行：

```bash
python3 -I -B -m unittest discover -s skills/article-video/tests -v
```

```bash
python3 -I -B -m unittest discover -s skills/wechat-mp/tests -v
```

```bash
python3 -I -B skills/wechat-mp/tests/verify_delivery.py
```

```bash
npm test --prefix skills/article-video/renderer
```

```bash
npm run typecheck --prefix skills/article-video/renderer
```

渲染器真实浏览器/编码测试需显式设置`REMOTION_BROWSER_EXECUTABLE`为已安装浏览器；没有设置会跳过，不能将跳过称为已实测。预览服务器使用运行环境提供的preview工具启动，不擅自终止用户或其他会话的服务。
