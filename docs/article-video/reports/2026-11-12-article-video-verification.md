# article-video 第一版验收记录

日期：2026-11-12。范围：用户要求先做可运行第一版，之后逐步调整；不继续逐项采访，不提交、不推送、不自动发布。

结论：第一版本地制作链路及完整演示MP4已通过技术验收。Azure在线客户端已实现并通过边界测试，但未做真实在线配音验收，示例不能代表在线音色质量。

## 交付入口

- [Skill](../../../skills/article-video/SKILL.md)
- [使用说明](../../../skills/article-video/README.md)
- [示例文章](../../../skills/article-video/examples/article.md)与[分镜方案](../../../skills/article-video/examples/plan.json)
- 本机产物：`outputs/article-video/2026-11-12-提示词不是越长越好/`，包含 MP4、封面、播放器、分句 WAV、旁白、分镜、SRT、来源及构建/渲染/验收记录。
- 本机产物和行为测试工作区被 gitignore 排除；其他机器需要按使用说明重新生成。
- [最终MP4](../../../outputs/article-video/2026-11-12-提示词不是越长越好/video.mp4)、[封面](../../../outputs/article-video/2026-11-12-提示词不是越长越好/cover.png)、[实际验收JSON](../../../outputs/article-video/2026-11-12-提示词不是越长越好/verification.json)。
- [最终桌面截图](../../../outputs/article-video/2026-11-12-提示词不是越长越好/review/preview-desktop.jpg)、[最终移动截图](../../../outputs/article-video/2026-11-12-提示词不是越长越好/review/preview-mobile.jpg)。

## 实际制作范围

示例《提示词不是越长越好》是自有文章，保留原文和来源段落。改编为10个场景、34句旁白，覆盖 hook、points、steps、compare、summary 五种版式。

配音采用明确标注的 `demo-local` / macOS `say` / Tingting。每句 WAV 经过实际格式、摘要和时长核验，再排成帧时间轴及 SRT。没有向 Azure 外发文章，没有使用真实 Azure 账号，没有产生在线配音调用费用。

## 回归证据

### Python

```bash
python3 -I -B -m unittest discover -s skills/article-video/tests -v
```

最终源代码运行结果：57项通过，0失败。覆盖摄入、来源/方案契约、SSML转义、授权失效、无凭据停止、缓存完整性与不重复收费、真实WAV时间轴/SRT、交付版本、真实媒体规格/封面解码及HTTP Range。

```bash
python3 -I -B -m unittest discover -s skills/wechat-mp/tests -v
```

原有公众号回归：149项通过，0失败。未修改公众号脚本接口。

### 渲染器

使用本机Chrome设置 `REMOTION_BROWSER_EXECUTABLE` 后实际运行 `npm test --prefix skills/article-video/renderer`：30项通过，0失败、0跳过；`npm run typecheck --prefix skills/article-video/renderer` 退出0。包括新增暂停状态回归、真实Chromium文字布局和真实Remotion编码测试。完整影片随后重新渲染成功；收尾再次执行57项视频Python、149项公众号Python、30项Node和typecheck，全部通过。

真实Chromium测试检查中文/拉丁长文本的字宽、行数、DOM溢出、安全区及字幕分离。真实1.4秒Remotion短片测试检查 BT.709、limited-range `yuv420p`，不是只检查传给编码器的参数。新增播放器事件测试在修复前实际失败，缺少 pause 监听导致提示仍为“正在播放”。

### Skill格式及行为样本

官方 skill-creator `quick_validate.py` 实际输出 `Skill is valid!`；检查所需 PyYAML 通过 uv 临时运行环境提供，没有加入制作流水线的运行依赖。

一次独立无skill基线、一次合并三场景with-skill任务，分别保存真实输出与检查证据：

| 场景 | 检查结果 | 执行范围 |
| --- | --- | --- |
| 缺少在线凭据 | 4/4检查项通过 | 真实 ingest/validate，10场景、777字旁白；只交付制作包，无WAV/MP4、外发或费用 |
| 修改口播却要求保留旧音频 | 4/4检查项通过 | 流程回答，没有可修改的旧视频；不声称已完成改片 |
| 仅改开场 | 4/4检查项通过 | 两版开场稿，不启动配音或渲染，不索要配音凭据 |

无skill基线在外发费用边界、音频诚信和只改文案方面多数回答正确，未硬标失败。差异主要是缺少本项目文件契约，并默认优先离线音色，不适配本项目正常任务的在线模式。

这不是逐场景多次独立统计benchmark，不能把合并任务耗时拆成虚构逐场景时间，不能用12个检查项推断未来Agent必然遵守。离线审阅页面：`workspaces/article-video/reviews/iteration-1.html`。

## 全片媒体与浏览器证据

最终重新渲染并再次执行默认 `verify` 成功。验收时间：`2026-11-12T04:11:36.269462+00:00`；当前视频 SHA-256：`377d77b588f89974d1e370b0ab0572c4ad272e1bf07587d6c8c9528c7d7e5ebe`。

| 实测项 | 结果 |
| --- | --- |
| 帧数/时间轴 | 3748帧；124.93333333333334秒 |
| 媒体封装时长 | 浏览器124.949秒，约2分5秒 |
| 画布/帧率 | 1080×1920，30fps |
| 视频/音频 | H.264 / AAC |
| 像素/色彩 | yuv420p，BT.709，limited-range（ffprobe color_range=tv） |
| 非静音 | max_volume=-5.3dB |
| 完整解码 | full_decode=true |
| 文件大小 | 8,099,249字节 |

最终播放器重新加载后：实际跳转8秒并播放至28.55秒；暂停事件后 `paused=true`，状态提示为“已暂停，点击播放继续。”；视频error为null，seekable为[0,124.949]。Range请求返回206、100字节和 `bytes 0-99/8099249`。18.866666秒要点画面已真实解码，readyState=4、seeking=false、canvas采样非空、桌面无横向溢出；已保存最终截图。

以下检查同时执行：

- 完整默认尺寸渲染，不用缩放文件冒充1080×1920。
- `verify` 从当前原文、方案、声音重建时间轴与SRT，检查构建程序、渲染程序和全部交付文件摘要；修改后旧交付被拒绝。
- ffprobe检查H.264/AAC、1080×1920、30fps、时长120–180秒、帧数与音轨；FFmpeg完整解码及非静音检查。
- 真实PNG封面解码与尺寸核验，不只相信回执摘要。
- 浏览器已实际加载并播放较早的同画面成片，seekable覆盖完整时长，跳转8秒后播放至约9.04秒，视频error为null。
- HTTP请求 `Range: bytes=0-99` 返回206及100字节，而不是返回整个文件。
- 已取得开场、要点、流程、对比、总结画面；最终成片又检查375×812移动布局，main单列335px，无横向溢出，视频error为null，暂停提示正确；已保存移动截图并恢复desktop viewport。
- 隐藏浏览器页曾使精确帧回调超时；不拿后台时间作为性能指标，改用状态、解码画面和截图核对。浏览器工具可访问页面，但桌面show_pane曾提示没有可显示的原生页面，不宣称成功替用户打开了预览侧栏。

## 确认问题及修复

1. Python的 `True == 1` 及非字符串kind：增加精确类型检查，避免错误版本或TypeError。
2. Unicode U+2028/U+2029：Python和渲染器保持单行文字契约一致。
3. 封面摘要合法但PNG内容损坏：增加真实图片规格与完整解码检查。
4. 旧构建与修改后源码不一致：重新build/render，不放宽指纹验证。
5. Remotion指定 `pixelFormat: yuv420p` 后实际仍为full-range `yuvj420p`：真实编码测试先失败；显式 `colorSpace: bt709` 后短片通过，并重渲染完整影片。
6. 普通静态服务器能播放却无法可靠拖动：实现仅绑定127.0.0.1的HTTP Range服务；浏览器实测跳转成功。
7. HTTP中文reason phrase导致Latin-1编码异常：中文放在send_error的explain字段，保留标准ASCII状态理由。
8. 目录首页由基类打开，绕过外部符号链接检查和Range规则：根目录与子目录index符号链接测试先失败，首页改走相同资源检查/Range路径后57项回归通过。
9. 暂停后提示不更新：增加pause监听，避免覆盖错误或结束状态；30项Node回归通过，完整影片重渲染后实际播放/暂停提示复测通过。
10. 纯文案/缺凭据制作包依赖要求过宽：skill按阶段拆依赖，只有需要渲染时才要求Node/Remotion/FFmpeg。

预览服务的停止/重启操作被权限机制阻止，未改用其他工具杀进程。现有8092服务仍可读取新生成的产物；新版首页资源边界通过临时本机HTTP服务器回归验证，但未重启该现有实例。

## 明确未验证项

- Azure真实账号、区域可用性、在线音色自然度和实际账单。
- 全篇人工听审、专有名词发音与主观音画语义质量。
- 视频号/抖音实际App界面遮挡和上传转码后的效果；右侧180px、底部360px只是项目保守留白。
- 跨平台字体像素完全一致性。字体走本机字体，不加载远程字体。
- Remotion商业许可资格：提供官方许可说明和显式环境变量入口，不替用户判断免费资格。
- 外部事实核查：段落对应和摘要只能验证来源及版本一致性。

第一版不包括声音克隆、AI镜头、背景音乐、横屏或自动发布。当前分支 `feat/article-video-v1`；本轮不commit、不push、不建PR。
