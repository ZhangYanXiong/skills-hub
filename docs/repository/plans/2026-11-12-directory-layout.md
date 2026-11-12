# 仓库目录整理实施计划

**目标：** 按用户已批准的方案区分技能源码、交付作品、临时工作区和按技能分类的文档，并保持已有功能和作品可用。

**约束：** 不提交、不推送、不删除已有作品，不重生成既有媒体，不改写历史构建回执里的路径或摘要。根目录保留 README.md、CLAUDE.md、skills/、outputs/、workspaces/、docs/ 和 .claude/。仓库级计划与报告放 docs/repository/。

## 任务一：清单与迁移前检查

- [x] 记录两个skill、生成产物、行为测试、文档和配置的逐文件SHA-256/链接目标，跳过依赖和缓存；清单为 workspaces/repository-layout/before.json。
- [x] 核实公众号作品生成日期为2026-11-11；视频作品为2026-11-12。
- [x] 写迁移映射和一致性检查器，迁移前运行应报告新目录缺失。

## 任务二：迁移与路径

- [x] 把 article-video/ 和 wechat-mp/ 整体迁入 skills/；依赖目录随软件整体移动，不重装依赖。
- [x] 把公众号六组演示迁入 outputs/wechat-mp/<日期-主题>/；原demo-output根层散文件整体归入CRUD接口示例，保持相对资源布局。
- [x] 把视频demo迁入 outputs/article-video/2026-11-12-提示词不是越长越好/；外置截图/构建摘要归入该作品review/，行为审阅页面归workspaces/article-video/reviews/。
- [x] 把行为评估归workspaces/article-video/，旧设计/计划/报告按所属skill归docs/<skill>/designs|plans|reports/。
- [x] 更新文档命令和链接、两处公众号测试仓库根定位；生产Python/Remotion源码保持字节不变，防止无意义地使现有视频指纹失效。
- [x] 更新.claude/skills链接；使用新预览名称和空闲端口，避免干扰已运行旧实例。

## 任务三：导航与约定

- [x] 根README缩为导航；原公众号长篇说明移至skills/wechat-mp/README.md。
- [x] 增加skills、outputs及各技能作品目录、docs及各技能文档目录的入口说明。
- [x] CLAUDE.md记录新目录约定、中文说明、生成项目命名、迁移后验收和不擅自提交/外发/删除。
- [x] 更新gitignore：临时工作区和视频作品忽略；原有随仓库保存的公众号示例明确保留，其余新作品默认忽略。

## 任务四：完整验收

运行命令：

```bash
python3 -I -B workspaces/repository-layout/verify_layout.py
```

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
REMOTION_BROWSER_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' npm test --prefix skills/article-video/renderer
```

```bash
npm run typecheck --prefix skills/article-video/renderer
```

- [x] 一致性检查所有367项有新位置；已有输出的字节保持不变。验证生产脚本/渲染源字节不变、skill链接指向新位置、维护文档无悬空相对链接。
- [x] 视频用当前CLI在临时完整副本执行verify并将结果另存工作区，保留原verification.json；不渲染、不配音。
- [x] 用preview工具启动新位置的预览，实际播放视频、跳转及检查公众号工作台和网络资源。
- [x] 独立只读复核路径遗漏；确认问题在同轮修复和复测，报告真实边界。
- [x] 写迁移报告和入口说明，保留分支未提交修改。
