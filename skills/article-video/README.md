# article-video · 文章转视频

第一版：**已有文章 → 120–180秒竖屏动态图文 → 中文旁白/字幕 → MP4**。

入口为 [SKILL.md](SKILL.md)。Agent负责文章理解与改编，脚本负责契约、实际配音时间轴、动画渲染和交付验收。不是上传文章就能不经模型改编的一键转换器。

## 当前能力

- Markdown/纯文本摄入，原文保留、段落编号、SHA-256。
- 五种动画版式：开场、要点、流程、对比、总结；9:16，1080×1920，30fps。
- Azure Speech REST中文预设音色客户端，明确外发/费用授权后才请求。
- 每句实测音频对应一条字幕，未修改句子可复用完整缓存。
- MP4、封面、可播放工作台和文案/分镜/字幕/源文件交付。
- 构建与渲染指纹防止交付旧版本；ffprobe规格校验、FFmpeg全解码与非静音检查。

不包括AI镜头、克隆声音、背景音乐、自动发布或横屏。首轮在线客户端通过传输边界测试，未用真实Azure账号合成；本地演示不能代表在线音色质量。

## 运行环境

Python3.10+、Node22+、FFmpeg/ffprobe。运行目录不限，以下命令默认在仓库根目录。

```bash
python3 -I -B skills/article-video/scripts/video.py doctor
```

```bash
npm ci --prefix skills/article-video/renderer
```

Remotion依赖锁定为4.0.543；安装及渲染可能下载官方浏览器/FFmpeg组件。可用 `REMOTION_BROWSER_EXECUTABLE` 提供已安装浏览器绝对路径。许可须按 [Remotion许可条款](https://www.remotion.dev/license) 判断个人/团队用途；不能因示例可运行就认定所有商用免费。需许可时将密钥放 `REMOTION_LICENSE_KEY` 环境变量，不提交到git。

## 直接试用本地示例（macOS）

仓库提供自有文章与已改编方案，无需外发内容或Azure密钥。**明确采用demo-local，只验收本地制作能力。**

```bash
python3 -I -B skills/article-video/scripts/video.py ingest skills/article-video/examples/article.md --project outputs/article-video/2026-11-12-提示词不是越长越好
```

```bash
cp skills/article-video/examples/plan.json outputs/article-video/2026-11-12-提示词不是越长越好/plan.json
```

```bash
python3 -I -B skills/article-video/scripts/video.py validate --project outputs/article-video/2026-11-12-提示词不是越长越好
```

```bash
python3 -I -B skills/article-video/scripts/video.py audio --project outputs/article-video/2026-11-12-提示词不是越长越好 --provider demo-local
```

```bash
python3 -I -B skills/article-video/scripts/video.py build --project outputs/article-video/2026-11-12-提示词不是越长越好
```

```bash
node skills/article-video/renderer/render.mjs --project "$PWD/outputs/article-video/2026-11-12-提示词不是越长越好"
```

```bash
python3 -I -B skills/article-video/scripts/video.py verify --project outputs/article-video/2026-11-12-提示词不是越长越好
```

默认 `verify` 强制120–180秒；实际示例约2分5秒，证据和未验证项见 [第一版验收记录](../../docs/article-video/reports/2026-11-12-article-video-verification.md)。只有明确要求短测试时才用 `--allow-short`，它不豁免1080×1920等规格。

生成后可使用 Claude Code 桌面预览配置 `article-video-preview` 打开本地播放器，支持播放、暂停和拖动。配置使用仅绑定 `127.0.0.1`、支持 HTTP Range 的 `scripts/preview.py`。`outputs/article-video/` 是本机生成目录，不纳入git；其他机器需运行上述命令重新生成。

## 用自己的文章

让Agent读本skill，摄入你的文章，写 `plan.json`，先确认文案/分镜。Azure配音设置见 [providers.md](references/providers.md)；正文外发和费用另行确认。没有凭据时只能交付制作包，不会静默改为本地声音。不要将密钥粘贴到聊天或项目文件。

修改 `plan.json` 后重新执行 validate → 新授权（在线模式）→ audio → build → render → verify。没有改的句子可复用经过摘要和WAV检查的音频缓存，整条时间轴及成片仍需重新生成。

## 让 Claude Code 发现 skill

仓库在 `.claude/skills/article-video` 提供指向skill目录的符号链接，新的项目会话可自动发现；本会话开始时的skill列表不会因文件创建立即刷新。也可直接要求“读取 skills/article-video/SKILL.md，把这篇文章转成视频”。不自动写入用户全局目录。

## 产物

```text
outputs/article-video/<项目>/
├── original.md / source.json    原始正文、段落与来源指纹
├── plan.json                   可编辑改编方案
├── approval.json               在线模式外发与费用确认（不含密钥）
├── audio/ / voice.json         分句WAV、缓存状态及真实时长
├── timeline.json               完整帧时间轴
├── narration.md / storyboard.md
├── subtitles.srt               实测分句字幕，不是逐字识别
├── build.json                  源输入/声音/脚本指纹
├── video.mp4 / cover.png / index.html
├── render-receipt.json         现行渲染输入、代码和输出指纹
└── verification.json           真实媒体检查结果
```

`verify`不验证事实真伪、朗读自然度和所有平台遮挡；实际播放抽查仍属于skill交付流程。工作台为本地审阅，不自动上传或发布。

## 回归测试

```bash
python3 -I -B -m unittest discover -s skills/article-video/tests -v
```

```bash
npm test --prefix skills/article-video/renderer
```

```bash
npm run typecheck --prefix skills/article-video/renderer
```

[evals/evals.json](evals/evals.json) 提供技能行为场景，首轮样本不是统计benchmark。代码测试、技能执行和真实成片验收分别报告，不互相冒充。
