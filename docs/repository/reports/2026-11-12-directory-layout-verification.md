# 目录整理与验收记录

日期：2026-11-12。用户批准按用途统一整理目录；本轮不提交、不推送、不删除旧作品、不重新配音或渲染成片。

## 新入口

- [总导航](../../../README.md)
- [目录及协作约定](../../../CLAUDE.md)
- [技能目录](../../../skills/README.md)
- [作品目录](../../../outputs/README.md)
- [开发文档](../../README.md)
- [临时工作区说明](../../../workspaces/README.md)

根目录只保留源码入口、作品入口、临时工作区、文档与项目工具配置，不再并列放多个output/workspace目录。各技能使用说明在自己的README，根README由原219行长篇混合说明缩为导航。

## 迁移对照

| 原位置 | 新位置 |
| --- | --- |
| article-video/ | skills/article-video/ |
| wechat-mp/ | skills/wechat-mp/ |
| article-video-output/demo/ | outputs/article-video/2026-11-12-提示词不是越长越好/ |
| article-video-output/demo-preview-*.jpg、demo-build-summary.json | 同一视频作品的review/ |
| article-video-output/skill-review.html | workspaces/article-video/reviews/iteration-1.html |
| article-video-workspace/ | workspaces/article-video/ |
| demo-output/acceptance-01/ | outputs/wechat-mp/2026-11-11-首次正式验收/ |
| demo-output/weekly-report/ | outputs/wechat-mp/2026-11-11-周报复盘/ |
| demo-output/worker-digital-human/ | outputs/wechat-mp/2026-11-11-数字人协同办公/ |
| demo-output/ingest-demo/ | outputs/wechat-mp/2026-11-11-素材摄入演示/ |
| demo-output/delivery-demo/ | outputs/wechat-mp/2026-11-11-交付流程演示/ |
| demo-output根层散文件 | outputs/wechat-mp/2026-11-11-CRUD接口示例/ |
| docs/superpowers/specs、plans、reports | docs/<所属skill>/designs、plans、reports |
| 根README中的公众号长篇说明 | skills/wechat-mp/README.md |

公众号日期据原build.json的2026-11-11生成时间核实，不按搬迁日期冒充新作品。视频日期为原第一版制作日期2026-11-12。

## 保留与路径处理

- 迁移前记录367项原文件/链接，包含源码、作品、工作区、旧文档与项目配置，不把node_modules和缓存作为源文件清单。
- 已逐项找到367/367个新位置；320项应保持不变的文件（生产代码、渲染代码/包配置、已有作品和行为样本）SHA-256一致。
- 两个skill整体移动，包括已有本地依赖，不重新安装；生产Python与Remotion源码字节不变，因此原视频构建/渲染指纹无需改写。
- 文档命令、相对链接、公众号测试仓库根深度与fixture位置同步更新；.claude/skills两项链接分别指向../../skills/<skill>。
- 已有原文、图片、音频、MP4、HTML、快照和构建/渲染/验收JSON原样保留。历史回执中的旧绝对源稿路径不批量改写，不冒充新版本。
- 临时工作区与视频作品gitignore；原有六组公众号作品明确保留，其余新作品默认忽略。实际检查127个当前公众号文件无错误忽略。
- 最终111项维护导航相对链接检查通过，0项悬空；检查不修改历史产物内容。检查器和完整映射保存在workspaces/repository-layout/。

## 回归与修复

### 代码测试

- 视频Python：57项通过。
- 公众号Python：150项通过，包含原149项及新增1项目录约定回归。
- 渲染器Node：30项通过，0失败、0跳过；使用本机Chrome运行真实文字布局及真实1.4秒Remotion编码测试。
- TypeScript：typecheck退出0。
- 公众号真实CLI：16步符合预期；其中故意错误输入的退出1属于负向验收，不是测试失败。16个脚本/测试文件保持Python3.9语法解析通过。
- 两项skill均通过官方quick_validate，输出Skill is valid!。

### 确认问题同轮处理

1. 独立只读复核指出verify_delivery.py仍引用outputs/wechat-mp/weekly-report。实际运行复现FileNotFoundError后改为日期主题目录，16步CLI重新通过。
2. 公众号SKILL仍要求在skill目录执行，并输出到out/。新增回归先失败，随后统一为仓库根命令和outputs/wechat-mp/my-article示例；原静态流程检查同步新路径，没有移除严格闸门或任务路由断言。
3. 使用说明中封面与HTML示例输出目录不一致。改为同一项目根目录，并在新回归断言封面输出目录等于HTML父目录，防止示例再次把封面放错位置。
4. 视频命令中的$PWD/旧目录不会被普通文本前缀替换覆盖；逐条核对并修复绝对项目路径，示例摄入、复制方案、配音、构建、渲染和验收使用同一日期主题目录。

### 已有作品验收

视频没有重渲染。为避免当前verify命令写入原verification.json，复制完整作品到本轮新建的临时目录，用当前CLI执行默认verify，成功后将新报告另存工作区，临时副本清理，原作品字节保持不变。

- 视频SHA-256：377d77b588f89974d1e370b0ab0572c4ad272e1bf07587d6c8c9528c7d7e5ebe。
- 时间轴124.93333333333334秒，1080×1920、30fps、H.264/AAC，完整解码true，max_volume=-5.3dB。
- 实际预览已从新目录加载，浏览器时长124.949秒。跳转8秒后真实播放至99.42秒；暂停状态及提示正确，video.error为null。
- Range请求返回206、100字节及bytes 0-99/8099249，seekable覆盖[0,124.949]；浏览器控制台无错误。
- 新位置公众号工作台正常加载标题、正文和6项发布清单；三档封面分别900×383、1080×1080、200×200，正文配图1400×610均加载完整；console无错误、network无失败请求。
- 公开作品HTML的41项本地资源检查无缺失。

## 历史快照边界

首次扫描全部HTML发现12项缺失资源，均在原交付流程示例的两个隐藏.builds历史快照中。逐项对照迁移前清单，缺失在搬迁之前就存在，不是本轮丢文件。当前公开工作台和正文资源完整，当前程序的完整快照/回退链路由16步CLI覆盖。

本轮保留历史快照及其JSON原样，不伪造资源、不把旧快照称为当前完整恢复包，不把隐藏快照中的HTML当作独立可打开的作品入口。

## 预览入口与范围

- article-video-preview：[视频预览](http://localhost:8093/)。
- wechat-mp-preview：[公众号工作台](http://localhost:8094/sheet.html)。

使用新名称和端口，避免覆盖或终止已有旧预览进程。旧8091/8092地址不再是新目录的入口，使用更新后的配置和链接。两个服务仅绑定127.0.0.1。

此次是目录维护，不补验Azure真实账号、在线音色、平台上传效果、公众号发布权限或商业许可。仍保留本地演示与在线成品的区别。功能分支保留，未commit、未push、未建PR。
