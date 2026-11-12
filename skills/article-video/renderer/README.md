# 本地文章视频渲染器

需要 Node.js 22+。在此目录运行 `npm ci`、`npm test`、`npm run typecheck`。

```bash
node render.mjs --project /absolute/path/to/build
```

仅供测试：输出 270×480，不能当成 1080×1920 发布成品。

```bash
node render.mjs --project /absolute/path/to/build --scale 0.25
```

构建目录提供 `timeline.json` 和 `audio/<ASCII键>.wav`；目录作为 Remotion 的 `publicDir`，不允许资源 URL、绝对音频路径、嵌套音频目录、目录逃逸或静态资源软链接。渲染器不获取文章、不请求配音服务。默认生成 1080×1920、30 fps、H.264/AAC、BT.709 limited-range `yuv420p` 的 `video.mp4`、同尺寸 `cover.png` 和无 CDN 的本地播放器 `index.html`。播放器显示模式、时长、音色限制；错误状态会显示文件读取或解码问题。

`REMOTION_BROWSER_EXECUTABLE` 可指定已安装的 Chrome/Chromium；未指定时使用 Remotion 的默认浏览器选择行为（可能需要下载浏览器）。本地 CJK 字体栈为 macOS Songti SC/PingFang SC，Linux 可预先安装 Noto Serif CJK SC/Noto Sans CJK SC。没有远程字体；实际浏览器字宽决定分行，超出最多 2–3 行或保留高度会显式失败，不截断文字。字体文件不在源码摘要中；跨平台像素一致性需要调用方另行固定本地字体环境。

## Remotion 许可

所有 Remotion 包固定为 **4.0.543**。必须自行核对安装版本 `node_modules/@remotion/renderer/LICENSE.md`（或 `node_modules/remotion/LICENSE.md`）和使用主体资格。本项目**不判断或宣称使用者符合 Free License**。安装版条款列出的免费资格是个人、最多 3 名员工的盈利组织、非盈利组织、尚未商业使用的评估；不在适用组内则需 Company License，衍生软件销售等另有限制。这里是安装版本说明，不是法律判断。

4.0.543 的 `renderMedia`/`renderStill` 接受可选 `licenseKey`。默认不传 key；当前 v4 实现取 `null` 并允许本地渲染，不注册许可 usage event。只有显式设置环境变量 `REMOTION_LICENSE_KEY` 时才转发其值；**不会自动填入 `free-license`**、不会伪造资格，也不会为了绕过许可证配置 v5 开关。显式 key 可能触发 Remotion 的 usage event 网络请求；使用者应先独立核对许可与网络授权。没有 key 的技术可运行性不等于法律上免费可用。不要把 key 写进构建文件或日志。

## 可追溯交付与失败

开始渲染时会删除旧 `video.mp4`、`cover.png`、`index.html`、`render-receipt.json`；时间轴、音频或渲染失败也不能留下旧成片冒充新交付。输出先在临时目录准备，输入和源码再次核验后发布，最后写入 receipt。

`render-receipt.json` 记录 `timelineSha256`、`rendererSha256`、三个 `outputs` 摘要以及 `scale,width,height,fps`。`timelineSha256` 是 timeline 文件的原始字节 SHA-256。`render-support.mjs` 导出异步 `codeFingerprint()`，包含 `src/` 中非缓存文件（包括隐藏源码），根目录 `render*.mjs`、`package.json`、`package-lock.json` 和 `tsconfig.json`。按 POSIX 相对路径排序，生成 `[path,fileSha256]` 数组的紧凑 JSON，取 UTF-8 SHA-256；不包含测试、文档、node_modules 或输出。父级 verify 应调用此接口，而非仅检查输出文件存在。

`.render-lock` 防止并行进程互相覆盖交付。若进程被强制终止，确认没有渲染器运行后再移除遗留锁；不能在运行期间删锁或修改 timeline/audio/src。receipt 是输入与文件版本绑定，不代替父级的 ffprobe、全解码、非静音或实际播放验收。

## 本地浏览器边界测试

普通 `npm test` 不下载浏览器；真实字宽/DOM 和实际编码色彩测试在显式提供本地浏览器时执行，否则报告跳过。实际编码测试另需 FFmpeg/ffprobe。

```bash
REMOTION_BROWSER_EXECUTABLE="/path/to/local/chrome" npm test
```

DOM 测试使用合成重复字符、阻断远程 HTTP/HTTPS 页面资源，检查五种版式的实际字宽、最大标题/正文/字幕、安全区域、边框和字幕分离。色彩测试用本地生成的测试音频，真实渲染1.4秒短片，再用ffprobe检查 `yuv420p`、BT.709、limited-range，避免只检查配置参数。测试没有外发文章或付费配音，不代表完整示例影片验收。
